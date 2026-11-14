import hmac
from fastapi import APIRouter, Request, Response
from sqlalchemy import text
from .db import tenant_db, engine, one, run
from .schemas import Login, Refresh, Forgot, Reset
from .security import now, fail, digest, password_ok, PH, parse_secret, web_guard
from .services import rate, tenant_active, queue_password, issue_session, session_response

router = APIRouter(prefix="/api/v1/auth", tags=["Tenant authentication"])


def resolve(slug):
    with engine().begin() as conn:
        return conn.execute(text("SELECT control.resolve_slug(:slug)"), {"slug": slug}).scalar_one_or_none()


@router.post("/login")
def login(body: Login, request: Request, response: Response):
    rate(request, "tenant-login", f"{body.slug}:{str(body.email).lower()}")
    tid = resolve(body.slug)
    if not tid:
        password_ok(body.password, None)
        fail()
    with tenant_db(tid) as db:
        user = one(db, "SELECT * FROM app.users WHERE lower(email)=:email", email=str(body.email).lower())
        valid = password_ok(body.password, user["password_hash"] if user else None)
        if not valid or not user or not user["active"] or user["must_reset_password"]:
            fail()
        tenant_active(db)
        result, refresh = issue_session(db, user, tid, client=body.client_type)
    return session_response(response, result, refresh, native=body.client_type == "native")


@router.post("/refresh")
def refresh_session(body: Refresh, request: Request, response: Response):
    raw = body.refresh_token or request.cookies.get("tenant_refresh", "")
    tid, sid = parse_secret(raw)
    rate(request, "tenant-refresh", str(tid) + str(sid))
    rejected = False
    with tenant_db(tid) as db:
        session = one(db, "SELECT * FROM app.auth_sessions WHERE id=:id FOR UPDATE", id=sid)
        if not session or not hmac.compare_digest(session["refresh_hash"], digest(raw)):
            fail()
        if session["client_type"] == "web":
            if body.refresh_token:
                fail()
            web_guard(request, session["csrf_hash"])
        elif not body.refresh_token:
            fail()
        if session["revoked_at"]:
            run(
                db, "UPDATE app.auth_sessions SET revoked_at=now() WHERE family_id=:family", family=session["family_id"]
            )
            rejected = True
        elif session["expires_at"] <= now():
            fail()
        else:
            tenant_active(db)
            user = one(db, "SELECT * FROM app.users WHERE id=:id", id=session["user_id"])
            if not user or not user["active"] or user["must_reset_password"]:
                fail()
            run(db, "UPDATE app.auth_sessions SET revoked_at=now(),last_used_at=now() WHERE id=:id", id=sid)
            result, replacement = issue_session(
                db,
                user,
                tid,
                family=session["family_id"],
                client=session["client_type"],
                expires_at=session["expires_at"],
            )
    # Raise only after committing family revocation on replay.
    if rejected:
        fail()
    return session_response(response, result, replacement, native=session["client_type"] == "native")


@router.post("/logout", status_code=204)
def logout(body: Refresh, request: Request, response: Response):
    raw = body.refresh_token or request.cookies.get("tenant_refresh", "")
    tid, sid = parse_secret(raw)
    with tenant_db(tid) as db:
        session = one(db, "SELECT * FROM app.auth_sessions WHERE id=:id", id=sid)
        if not session or not hmac.compare_digest(session["refresh_hash"], digest(raw)):
            fail()
        if session["client_type"] == "web":
            if body.refresh_token:
                fail()
            web_guard(request, session["csrf_hash"])
        elif not body.refresh_token:
            fail()
        run(db, "UPDATE app.auth_sessions SET revoked_at=now() WHERE family_id=:id", id=session["family_id"])
    response.delete_cookie("tenant_refresh", path="/api/v1/auth")
    response.delete_cookie("tenant_csrf", path="/")


@router.post("/forgot-password", status_code=202)
def forgot(body: Forgot, request: Request):
    rate(request, "forgot", f"{body.slug}:{str(body.email).lower()}")
    tid = resolve(body.slug)
    if tid:
        with tenant_db(tid) as db:
            state = one(db, "SELECT * FROM control.tenant_state()")
            user = one(db, "SELECT * FROM app.users WHERE lower(email)=:email", email=str(body.email).lower())
            if (
                state
                and state["status"] == "ACTIVE"
                and state["valid_until"] > now()
                and user
                and user["active"]
                and user["email_verified_at"]
            ):
                queue_password(db, tid, user, "RESET")
    return {"message": "If the account is eligible, a reset message will be sent."}


def apply_password(body, request, purpose):
    tid, identifier = parse_secret(body.token)
    rate(request, "reset-password", str(tid) + str(identifier))
    with tenant_db(tid) as db:
        tenant_active(db)
        run(db, "SELECT control.lock_tenant()")
        token = one(db, "SELECT * FROM app.password_tokens WHERE id=:id FOR UPDATE", id=identifier)
        if (
            not token
            or not hmac.compare_digest(token["token_hash"], digest(body.token))
            or token["purpose"] != purpose
            or token["used_at"]
            or token["expires_at"] <= now()
        ):
            fail(400, "INVALID_OR_EXPIRED_LINK")
        user = one(db, "SELECT * FROM app.users WHERE id=:id FOR UPDATE", id=token["user_id"])
        if not user or not user["active"]:
            fail(400, "INVALID_OR_EXPIRED_LINK")
        run(
            db,
            """UPDATE app.users SET password_hash=:hash,must_reset_password=false,token_version=token_version+1,
            email_verified_at=COALESCE(email_verified_at,now()) WHERE id=:id""",
            hash=PH.hash(body.new_password),
            id=user["id"],
        )
        run(db, "UPDATE app.password_tokens SET used_at=now() WHERE user_id=:id AND used_at IS NULL", id=user["id"])
        run(db, "UPDATE app.auth_sessions SET revoked_at=now() WHERE user_id=:id", id=user["id"])


@router.post("/reset-password", status_code=204)
def reset(body: Reset, request: Request):
    apply_password(body, request, "RESET")


@router.post("/accept-invite", status_code=204)
def invite(body: Reset, request: Request):
    apply_password(body, request, "INVITE")
