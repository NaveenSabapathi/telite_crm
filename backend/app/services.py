import json
import secrets
from datetime import timedelta
from uuid import uuid4
from fastapi import Depends, Request
from sqlalchemy import text
from .config import settings
from .db import engine, tenant_db, control_db, one, run
from .security import claims, now, fail, digest, encrypt, secret_token

USER_FIELDS = "id,email,display_name,role,work_mode,active,branch_id,shift_id,version,must_reset_password"
TENANT_FIELDS = "id,name,slug,status,timezone,currency,max_active_employees,storage_quota_bytes,storage_used_bytes,valid_until,version,created_at"


def rate(request, label, account=""):
    # Deliberately do not trust client-supplied X-Forwarded-For.
    ip = request.client.host if request.client else "unknown"
    kind = "control" if request.app.state.platform else "tenant"
    for key, cap in [(f"{label}:ip:{ip}", 60), (f"{label}:account:{account}", 10)]:
        with engine(kind).begin() as conn:
            allowed = conn.execute(
                text("SELECT control.rate_limit(:key,:cap,600)"), {"key": digest(key), "cap": cap}
            ).scalar_one()
        if not allowed:
            fail(429, "RATE_LIMITED")


def tenant_active(db):
    state = one(db, "SELECT * FROM control.tenant_state()")
    if not state or state["status"] != "ACTIVE" or state["valid_until"] <= now():
        fail(403, "TENANT_INACTIVE")
    return state


def tenant_identity(request: Request):
    token = claims(request, "tenant")
    with tenant_db(token["tid"]) as db:
        tenant = tenant_active(db)
        user = one(db, "SELECT * FROM app.users WHERE id=:id", id=token["sub"])
        session = one(
            db, "SELECT * FROM app.auth_sessions WHERE id=:id AND user_id=:uid", id=token["sid"], uid=token["sub"]
        )
        if not user or not user["active"] or user["must_reset_password"] or user["token_version"] != token["ver"]:
            fail()
        if not session or session["revoked_at"] or session["expires_at"] <= now():
            fail()
        # Never derive tenant from body or a header. Bound once from the verified token.
        request.state.tenant_id = token["tid"]
        request.state.user = user
        request.state.tenant = tenant
        request.state.session_id = token["sid"]
        yield db


def company_admin(request: Request, db=Depends(tenant_identity)):
    if request.state.user["role"] != "COMPANY_ADMIN":
        fail(403, "ROLE_FORBIDDEN")
    return db


def feature(name):
    def guard(db=Depends(tenant_identity)):
        row = one(db, "SELECT enabled FROM control.tenant_features WHERE feature=:name", name=name)
        if not row or not row["enabled"]:
            fail(403, "FEATURE_DISABLED")
        return db

    return guard


def platform_identity(request: Request):
    token = claims(request, "platform")
    with control_db() as db:
        user = one(db, "SELECT * FROM control.platform_admins WHERE id=:id", id=token["sub"])
        session = one(
            db,
            "SELECT * FROM control.platform_sessions WHERE id=:id AND admin_id=:uid",
            id=token["sid"],
            uid=token["sub"],
        )
        if not user or not user["active"] or user["token_version"] != token["ver"]:
            fail()
        if not session or session["revoked_at"] or session["expires_at"] <= now():
            fail()
        request.state.platform_user = user
        request.state.session_id = token["sid"]
        return user


def audit(db, request, action, entity_id=None, changes=None):
    run(
        db,
        """INSERT INTO app.audit_logs(tenant_id,actor_id,action,entity_type,entity_id,request_id,redacted_changes,occurred_at)
        VALUES(app.current_tenant(),:actor,:action,'user',:eid,:rid,CAST(:changes AS jsonb),now())""",
        changes=json.dumps(changes or {}),
        actor=request.state.user["id"],
        action=action,
        eid=entity_id,
        rid=request.state.request_id,
    )


def platform_audit(db, request, action, tid, reason):
    run(
        db,
        """INSERT INTO control.platform_audit(actor_id,target_tenant_id,action,reason,request_id)
        VALUES(:actor,:tid,:action,:reason,:rid)""",
        actor=request.state.platform_user["id"],
        tid=tid,
        action=action,
        reason=reason,
        rid=request.state.request_id,
    )


def queue_password(db, tid, user, purpose):
    identifier = uuid4()
    token = secret_token(tid, identifier)
    run(db, "UPDATE app.password_tokens SET used_at=now() WHERE user_id=:id AND used_at IS NULL", id=user["id"])
    run(
        db,
        """INSERT INTO app.password_tokens(tenant_id,id,user_id,token_hash,purpose,expires_at)
        VALUES(:tid,:id,:uid,:hash,:purpose,:expires)""",
        tid=tid,
        id=identifier,
        uid=user["id"],
        hash=digest(token),
        purpose=purpose,
        expires=now() + timedelta(hours=24 if purpose == "INVITE" else 1),
    )
    # Token ciphertext persists only until SMTP delivery. Never returned by API.
    payload = json.dumps(
        {"token_ciphertext": encrypt(token), "email": user["email"], "purpose": purpose, "token_id": str(identifier)}
    )
    run(
        db,
        """INSERT INTO app.outbox(tenant_id,event_type,aggregate_type,aggregate_id,payload,dedupe_key,available_at)
        VALUES(:tid,'AUTH_EMAIL','user',:uid,CAST(:payload AS jsonb),:key,now())""",
        tid=tid,
        uid=user["id"],
        payload=payload,
        key=f"auth:{identifier}",
    )


def issue_session(db, user, tid=None, family=None, client="web", expires_at=None):
    sid = uuid4()
    csrf = secrets.token_urlsafe(32)
    refresh = secret_token(tid or user["id"], sid)
    expiry = expires_at or now() + timedelta(seconds=settings().refresh_token_ttl_seconds)
    if tid:
        run(
            db,
            """INSERT INTO app.auth_sessions(tenant_id,id,user_id,refresh_hash,family_id,expires_at,csrf_hash,client_type)
            VALUES(:tid,:sid,:uid,:hash,:family,:expiry,:csrf,:client)""",
            tid=tid,
            sid=sid,
            uid=user["id"],
            hash=digest(refresh),
            family=family or uuid4(),
            expiry=expiry,
            csrf=digest(csrf),
            client=client,
        )
    else:
        run(
            db,
            """INSERT INTO control.platform_sessions(id,admin_id,token_hash,family_id,expires_at,csrf_hash)
            VALUES(:sid,:uid,:hash,:family,:expiry,:csrf)""",
            sid=sid,
            uid=user["id"],
            hash=digest(refresh),
            family=family or uuid4(),
            expiry=expiry,
            csrf=digest(csrf),
        )
    from .security import access_token

    result = {
        "access_token": access_token(user["id"], sid, user["token_version"], tid),
        "token_type": "bearer",
        "expires_in": settings().access_token_ttl_seconds,
        "csrf_token": csrf,
    }
    return result, refresh


def session_response(response, result, refresh, platform=False, native=False):
    if native:
        result["refresh_token"] = refresh
    else:
        path = "/api/v1/platform/auth" if platform else "/api/v1/auth"
        prefix = "platform" if platform else "tenant"
        response.set_cookie(
            f"{prefix}_refresh",
            refresh,
            httponly=True,
            secure=settings().cookie_secure,
            samesite="strict",
            path=path,
            max_age=settings().refresh_token_ttl_seconds,
        )
        response.set_cookie(
            f"{prefix}_csrf",
            result["csrf_token"],
            httponly=False,
            secure=settings().cookie_secure,
            samesite="strict",
            path="/",
            max_age=settings().refresh_token_ttl_seconds,
        )
    return result
