import hmac
import secrets
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, Request, Response
from .db import control_db, tenant_db, one, many, run
from .schemas import PlatformLogin, Refresh, CreateTenant, UpdateTenant, FeaturesUpdate, AdminReset
from .security import now, fail, digest, decrypt, password_ok, PH, totp_step, parse_secret, web_guard, expected_version
from .services import (
    rate,
    platform_identity,
    platform_audit,
    queue_password,
    issue_session,
    session_response,
    TENANT_FIELDS,
)

router = APIRouter(prefix="/api/v1/platform", tags=["Platform administration"])


@router.post("/auth/login")
def login(body: PlatformLogin, request: Request, response: Response):
    rate(request, "platform-login", str(body.email).lower())
    with control_db() as db:
        user = one(
            db, "SELECT * FROM control.platform_admins WHERE email=:email FOR UPDATE", email=str(body.email).lower()
        )
        valid = password_ok(body.password, user["password_hash"] if user else None)
        if not valid or not user or not user["active"]:
            fail()
        step = totp_step(decrypt(user["mfa_secret_ciphertext"]), body.otp)
        if step is None or step <= user["last_totp_step"]:
            fail()
        run(db, "UPDATE control.platform_admins SET last_totp_step=:step WHERE id=:id", step=step, id=user["id"])
        result, refresh = issue_session(db, user)
    return session_response(response, result, refresh, platform=True)


@router.post("/auth/refresh")
def refresh(body: Refresh, request: Request, response: Response):
    if body.refresh_token:
        fail()
    raw = request.cookies.get("platform_refresh", "")
    uid, sid = parse_secret(raw)
    rate(request, "platform-refresh", str(sid))
    rejected = False
    with control_db() as db:
        session = one(
            db, "SELECT * FROM control.platform_sessions WHERE id=:id AND admin_id=:uid FOR UPDATE", id=sid, uid=uid
        )
        if not session or not hmac.compare_digest(session["token_hash"], digest(raw)):
            fail()
        web_guard(request, session["csrf_hash"])
        if session["revoked_at"]:
            run(
                db, "UPDATE control.platform_sessions SET revoked_at=now() WHERE family_id=:id", id=session["family_id"]
            )
            rejected = True
        else:
            user = one(db, "SELECT * FROM control.platform_admins WHERE id=:id", id=uid)
            if session["expires_at"] <= now() or not user or not user["active"]:
                fail()
            run(db, "UPDATE control.platform_sessions SET revoked_at=now() WHERE id=:id", id=sid)
            result, replacement = issue_session(db, user, family=session["family_id"], expires_at=session["expires_at"])
    if rejected:
        fail()
    return session_response(response, result, replacement, platform=True)


@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response):
    raw = request.cookies.get("platform_refresh", "")
    uid, sid = parse_secret(raw)
    with control_db() as db:
        session = one(db, "SELECT * FROM control.platform_sessions WHERE id=:id AND admin_id=:uid", id=sid, uid=uid)
        if not session or not hmac.compare_digest(session["token_hash"], digest(raw)):
            fail()
        web_guard(request, session["csrf_hash"])
        run(db, "UPDATE control.platform_sessions SET revoked_at=now() WHERE family_id=:id", id=session["family_id"])
    response.delete_cookie("platform_refresh", path="/api/v1/platform/auth")
    response.delete_cookie("platform_csrf", path="/")


@router.get("/me", dependencies=[Depends(platform_identity)])
def me(request: Request):
    user = request.state.platform_user
    return {"id": user["id"], "email": user["email"], "role": "SUPER_ADMIN"}


@router.get("/tenants", dependencies=[Depends(platform_identity)])
def tenants(limit: int = 25, offset: int = 0, q: str = ""):
    if not 1 <= limit <= 100 or offset < 0 or len(q) > 200:
        fail(422, "INVALID_PAGINATION")
    with control_db() as db:
        rows = many(
            db,
            f"SELECT {TENANT_FIELDS} FROM control.tenants WHERE name ILIKE :q OR slug ILIKE :q ORDER BY created_at DESC,id LIMIT :limit OFFSET :offset",
            q=f"%{q}%",
            limit=limit,
            offset=offset,
        )
        return {"data": rows, "next_offset": offset + limit if len(rows) == limit else None}


@router.post("/tenants", status_code=201, dependencies=[Depends(platform_identity)])
def create(body: CreateTenant, request: Request):
    try:
        key = UUID(request.headers.get("idempotency-key", ""))
    except ValueError:
        fail(428, "IDEMPOTENCY_KEY_REQUIRED")
    if body.valid_until <= now():
        fail(422, "VALIDITY_MUST_BE_FUTURE")
    fingerprint = digest(body.model_dump_json())
    tid = uuid4()
    with tenant_db(tid, "control") as db:
        # Advisory lock serializes retries before a tenant row exists.
        run(db, "SELECT pg_advisory_xact_lock(hashtextextended(:key,0))", key=str(key))
        existing = one(
            db, f"SELECT {TENANT_FIELDS},creation_hash,created_by FROM control.tenants WHERE creation_key=:key", key=key
        )
        if existing:
            if existing["creation_hash"] != fingerprint or existing["created_by"] != request.state.platform_user["id"]:
                fail(409, "IDEMPOTENCY_CONFLICT")
            return {k: v for k, v in existing.items() if k not in ("creation_hash", "created_by")}
        values = body.model_dump(exclude={"branch", "shift", "admin", "features"})
        run(
            db,
            """INSERT INTO control.tenants(id,name,slug,status,timezone,currency,max_active_employees,storage_quota_bytes,valid_until,creation_key,creation_hash,created_by)
            VALUES(:id,:name,:slug,'ACTIVE',:timezone,:currency,:max_active_employees,:storage_quota_bytes,:valid_until,:key,:hash,:actor)""",
            **values,
            id=tid,
            key=key,
            hash=fingerprint,
            actor=request.state.platform_user["id"],
        )
        branch = uuid4()
        shift = uuid4()
        uid = uuid4()
        run(
            db,
            """INSERT INTO app.branches(tenant_id,id,name,address,lat,lng,radius_m,timezone)
            VALUES(:tid,:id,:name,:address,:lat,:lng,:radius_m,:timezone)""",
            tid=tid,
            id=branch,
            timezone=body.timezone,
            **body.branch.model_dump(),
        )
        run(
            db,
            """INSERT INTO app.shifts(tenant_id,id,name,start_local,end_local,end_day_offset,grace_minutes,weekdays)
            VALUES(:tid,:id,:name,:start_local,:end_local,:end_day_offset,:grace_minutes,:weekdays)""",
            tid=tid,
            id=shift,
            **body.shift.model_dump(),
        )
        run(
            db,
            """INSERT INTO app.users(tenant_id,id,email,display_name,password_hash,role,work_mode,branch_id,shift_id)
            VALUES(:tid,:id,:email,:name,:password,'COMPANY_ADMIN','OFFICE',:branch,:shift)""",
            tid=tid,
            id=uid,
            email=str(body.admin.email).lower(),
            name=body.admin.display_name,
            password=PH.hash(secrets.token_urlsafe(48)),
            branch=branch,
            shift=shift,
        )
        for name, enabled in body.features.model_dump().items():
            run(
                db,
                "INSERT INTO control.tenant_features(tenant_id,feature,enabled) VALUES(:tid,:feature,:enabled)",
                tid=tid,
                feature=name,
                enabled=enabled,
            )
        queue_password(db, tid, {"id": uid, "email": str(body.admin.email).lower()}, "INVITE")
        platform_audit(db, request, "TENANT_CREATED", tid, "Company created with initial administrator invitation")
        return one(db, f"SELECT {TENANT_FIELDS} FROM control.tenants WHERE id=:id", id=tid)


@router.get("/tenants/{tid}", dependencies=[Depends(platform_identity)])
def detail(tid: UUID):
    with tenant_db(tid, "control") as db:
        tenant = one(db, f"SELECT {TENANT_FIELDS} FROM control.tenants WHERE id=:id", id=tid)
        if not tenant:
            fail(404, "NOT_FOUND")
        return {
            **tenant,
            "features": {
                r["feature"]: r["enabled"] for r in many(db, "SELECT feature,enabled FROM control.tenant_features")
            },
            "admins": many(
                db,
                "SELECT id,email,display_name,must_reset_password FROM app.users WHERE role='COMPANY_ADMIN' AND active",
            ),
            "active_employees": one(db, "SELECT count(*) AS count FROM app.users WHERE active")["count"],
        }


@router.patch("/tenants/{tid}", dependencies=[Depends(platform_identity)])
def update(tid: UUID, body: UpdateTenant, request: Request):
    with tenant_db(tid, "control") as db:
        tenant = one(db, "SELECT * FROM control.tenants WHERE id=:id FOR UPDATE", id=tid)
        if not tenant:
            fail(404, "NOT_FOUND")
        if tenant["version"] != expected_version(request):
            fail(409, "VERSION_CONFLICT")
        used = one(db, "SELECT count(*) AS count FROM app.users WHERE active")["count"]
        if (
            body.max_active_employees < used
            or body.storage_quota_bytes < tenant["storage_used_bytes"] + tenant["storage_reserved_bytes"]
        ):
            fail(409, "QUOTA_BELOW_CURRENT_USAGE")
        run(
            db,
            """UPDATE control.tenants SET name=:name,status=:status,max_active_employees=:max_active_employees,
            storage_quota_bytes=:storage_quota_bytes,valid_until=:valid_until,version=version+1 WHERE id=:id""",
            **body.model_dump(exclude={"reason"}),
            id=tid,
        )
        if body.status != "ACTIVE":
            run(db, "UPDATE app.auth_sessions SET revoked_at=now() WHERE revoked_at IS NULL")
        platform_audit(db, request, "TENANT_UPDATED", tid, body.reason)
        return one(db, f"SELECT {TENANT_FIELDS} FROM control.tenants WHERE id=:id", id=tid)


@router.put("/tenants/{tid}/features", dependencies=[Depends(platform_identity)])
def flags(tid: UUID, body: FeaturesUpdate, request: Request):
    with tenant_db(tid, "control") as db:
        tenant = one(db, "SELECT version FROM control.tenants WHERE id=:id FOR UPDATE", id=tid)
        if not tenant:
            fail(404, "NOT_FOUND")
        if tenant["version"] != expected_version(request):
            fail(409, "VERSION_CONFLICT")
        for name, enabled in body.features.model_dump().items():
            run(
                db,
                "UPDATE control.tenant_features SET enabled=:enabled WHERE feature=:name",
                enabled=enabled,
                name=name,
            )
        run(db, "UPDATE control.tenants SET version=version+1 WHERE id=:id", id=tid)
        platform_audit(db, request, "FEATURES_UPDATED", tid, body.reason)
        return {"version": tenant["version"] + 1, "features": body.features.model_dump()}


@router.post("/tenants/{tid}/reset-admin", status_code=202, dependencies=[Depends(platform_identity)])
def reset_admin(tid: UUID, body: AdminReset, request: Request):
    with tenant_db(tid, "control") as db:
        run(db, "SELECT control.lock_tenant()")
        user = one(
            db,
            "SELECT * FROM app.users WHERE id=:id AND role='COMPANY_ADMIN' AND active FOR UPDATE",
            id=body.admin_user_id,
        )
        if not user:
            fail(404, "NOT_FOUND")
        run(
            db,
            "UPDATE app.users SET must_reset_password=true,token_version=token_version+1 WHERE id=:id",
            id=user["id"],
        )
        run(db, "UPDATE app.auth_sessions SET revoked_at=now() WHERE user_id=:id", id=user["id"])
        queue_password(db, tid, user, "RESET" if user["email_verified_at"] else "INVITE")
        platform_audit(db, request, "ADMIN_RESET_REQUESTED", tid, body.reason)
    return {"message": "Reset link queued to the administrator address; no password is exposed."}


@router.get("/audit", dependencies=[Depends(platform_identity)])
def audit(limit: int = 100):
    if not 1 <= limit <= 100:
        fail(422, "INVALID_LIMIT")
    with control_db() as db:
        return {
            "data": many(
                db,
                "SELECT id,actor_id,target_tenant_id,action,reason,occurred_at FROM control.platform_audit ORDER BY occurred_at DESC LIMIT :n",
                n=limit,
            )
        }


@router.get("/health", dependencies=[Depends(platform_identity)])
def health():
    with control_db() as db:
        return {
            "database": "available",
            "tenants": one(db, "SELECT count(*) AS count FROM control.tenants")["count"],
            "active": one(
                db, "SELECT count(*) AS count FROM control.tenants WHERE status='ACTIVE' AND valid_until>now()"
            )["count"],
        }
