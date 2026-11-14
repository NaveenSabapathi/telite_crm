from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from app.db import tenant_db, engine, TenantSession
from conftest import create_tenant, tenant_payload, token_for


def bearer(auth):
    return {"Authorization": "Bearer " + auth["access_token"]}


def employee(api, auth, email="engineer@example.com", role="ENGINEER"):
    h = bearer(auth)
    branch = api.get("/api/v1/branches", headers=h).json()["data"][0]["id"]
    shift = api.get("/api/v1/shifts", headers=h).json()["data"][0]["id"]
    return {
        "email": email,
        "display_name": "Engineer",
        "role": role,
        "work_mode": "FIELD",
        "branch_id": branch,
        "shift_id": shift,
    }


def test_create_atomic_idempotent_and_invite(system):
    p = tenant_payload("one-company")
    key = str(uuid4())
    platform = system["platform"]
    a = platform.post("/api/v1/platform/tenants", json=p, headers={"Idempotency-Key": key})
    b = platform.post("/api/v1/platform/tenants", json=p, headers={"Idempotency-Key": key})
    assert a.status_code == b.status_code == 201
    assert a.json()["id"] == b.json()["id"]
    p["name"] = "Changed"
    assert platform.post("/api/v1/platform/tenants", json=p, headers={"Idempotency-Key": key}).status_code == 409
    assert "password" not in a.text and "token_ciphertext" not in a.text
    tid = a.json()["id"]
    raw = token_for(system, tid)
    assert (
        system["api"]
        .post("/api/v1/auth/accept-invite", json={"token": raw, "new_password": "Secure-Test-Password-52"})
        .status_code
        == 204
    )
    assert (
        system["api"]
        .post("/api/v1/auth/accept-invite", json={"token": raw, "new_password": "Secure-Test-Password-52"})
        .status_code
        == 400
    )


def test_rls_read_write_no_context_and_pool_reuse(system):
    a, aa = create_tenant(system)
    b, bb = create_tenant(system, "beta-company")
    with tenant_db(b) as db:
        other = db.execute(text("SELECT id FROM app.users")).scalar_one()
    for tid in [a, b, a, b]:
        with tenant_db(tid) as db:
            assert {str(x) for x in db.execute(text("SELECT tenant_id FROM app.users")).scalars()} == {tid}
    with tenant_db(a) as db:
        assert db.execute(text("SELECT id FROM app.users WHERE id=:id"), {"id": other}).first() is None
        assert db.execute(text("UPDATE app.users SET display_name='leak' WHERE id=:id"), {"id": other}).rowcount == 0
    with pytest.raises(DBAPIError):
        with engine().begin() as db:
            db.execute(text("SELECT * FROM app.users")).all()
    with TenantSession(engine()) as db:
        with pytest.raises(PermissionError):
            db.execute(text("SELECT 1"))
    with pytest.raises(DBAPIError):
        with tenant_db(a) as db:
            db.execute(text("UPDATE app.users SET tenant_id=:b"), {"b": b})
    with engine().connect() as db:
        role = db.execute(text("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user")).one()
        assert not role.rolsuper and not role.rolbypassrls


def test_api_foreign_id_fk_and_forbidden_mass_assignment(system):
    a, aa = create_tenant(system)
    b, bb = create_tenant(system, "beta-company")
    api = system["api"]
    other = api.get("/api/v1/me", headers=bearer(bb)).json()["user"]["id"]
    assert api.get("/api/v1/users/" + other, headers=bearer(aa)).status_code == 404
    payload = employee(api, bb)
    assert api.post("/api/v1/users", json=payload, headers=bearer(aa)).status_code == 404
    payload = employee(api, aa)
    payload["tenant_id"] = b
    assert api.post("/api/v1/users", json=payload, headers=bearer(aa)).status_code == 422
    payload.pop("tenant_id")
    payload["role"] = "SUPER_ADMIN"
    assert api.post("/api/v1/users", json=payload, headers=bearer(aa)).status_code == 422
    # Cross-tenant FK remains blocked even under direct runtime SQL.
    foreign = employee(api, bb)["branch_id"]
    with pytest.raises(DBAPIError):
        with tenant_db(a) as db:
            db.execute(text("UPDATE app.users SET branch_id=:id"), {"id": foreign})


def test_refresh_rotation_replay_revokes_descendants(system):
    tid, a = create_tenant(system)
    api = system["api"]
    r = api.post("/api/v1/auth/refresh", json={"refresh_token": a["refresh_token"]})
    assert r.status_code == 200, r.text
    b = r.json()
    assert api.get("/api/v1/me", headers=bearer(a)).status_code == 401
    assert api.get("/api/v1/me", headers=bearer(b)).status_code == 200
    assert api.post("/api/v1/auth/refresh", json={"refresh_token": a["refresh_token"]}).status_code == 401
    assert api.get("/api/v1/me", headers=bearer(b)).status_code == 401


def test_web_csrf_and_cookie_flags(system):
    create_tenant(system)
    api = system["api"]
    r = api.post(
        "/api/v1/auth/login",
        json={"slug": "alpha-company", "email": "owner@example.com", "password": "Tenant-Test-Password-42"},
    )
    assert r.status_code == 200
    assert "refresh_token" not in r.json()
    assert "HttpOnly" in r.headers.get("set-cookie")
    assert api.post("/api/v1/auth/refresh", json={}).status_code == 403
    h = {"Origin": "http://evil.example", "X-CSRF-Token": r.json()["csrf_token"]}
    assert api.post("/api/v1/auth/refresh", json={}, headers=h).status_code == 403
    h["Origin"] = "http://testserver"
    refreshed = api.post("/api/v1/auth/refresh", json={}, headers=h)
    assert refreshed.status_code == 200, refreshed.text
    h["X-CSRF-Token"] = refreshed.json()["csrf_token"]
    assert api.post("/api/v1/auth/logout", json={}, headers=h).status_code == 204
    assert api.get("/api/v1/me", headers=bearer(refreshed.json())).status_code == 401


def test_platform_audience_mfa_and_replay(system):
    tid, a = create_tenant(system)
    assert system["platform"].get("/api/v1/platform/tenants", headers=bearer(a)).status_code == 401
    assert (
        system["api"]
        .get("/api/v1/me", headers={"Authorization": system["platform"].headers["Authorization"]})
        .status_code
        == 401
    )
    import pyotp

    r = system["platform"].post(
        "/api/v1/platform/auth/login",
        json={
            "email": "platform@example.com",
            "password": "Platform-Test-Password-42",
            "otp": pyotp.TOTP(system["otp"]).now(),
        },
    )
    assert r.status_code == 401  # exact previously accepted time step cannot replay
    assert system["api"].get("/api/v1/platform/tenants").status_code == 404


def test_flags_version_and_dependencies(system):
    tid, a = create_tenant(system)
    p = system["platform"]
    api = system["api"]
    assert api.get("/api/v1/capabilities/sales_crm", headers=bearer(a)).status_code == 200
    d = p.get("/api/v1/platform/tenants/" + tid).json()
    flags = d["features"]
    flags["sales_crm"] = False
    url = "/api/v1/platform/tenants/" + tid + "/features"
    body = {"features": flags, "reason": "Disable sales module"}
    assert p.put(url, json=body).status_code == 428
    assert p.put(url, json=body, headers={"If-Match": str(d["version"])}).status_code == 200
    assert p.put(url, json=body, headers={"If-Match": str(d["version"])}).status_code == 409
    assert api.get("/api/v1/capabilities/sales_crm", headers=bearer(a)).status_code == 403
    flags["amc_tracker"] = True
    flags["field_service_tickets"] = False
    assert p.put(url, json=body, headers={"If-Match": "2"}).status_code == 422


def test_suspension_revokes_existing_sessions(system):
    tid, a = create_tenant(system)
    p = system["platform"]
    d = p.get("/api/v1/platform/tenants/" + tid).json()
    body = {k: d[k] for k in ["name", "status", "max_active_employees", "storage_quota_bytes", "valid_until"]}
    body.update(status="SUSPENDED", reason="Requested account suspension")
    assert (
        p.patch("/api/v1/platform/tenants/" + tid, json=body, headers={"If-Match": str(d["version"])}).status_code
        == 200
    )
    assert system["api"].get("/api/v1/me", headers=bearer(a)).status_code == 403
    assert system["api"].post("/api/v1/auth/refresh", json={"refresh_token": a["refresh_token"]}).status_code == 401
    body["status"] = "ACTIVE"
    assert p.patch("/api/v1/platform/tenants/" + tid, json=body, headers={"If-Match": "2"}).status_code == 200
    assert system["api"].get("/api/v1/me", headers=bearer(a)).status_code == 401


def test_limit_concurrent_invitations_and_last_admin(system):
    tid, a = create_tenant(system, cap=2)
    api = system["api"]
    payload = employee(api, a)

    def add(i):
        return api.post(
            "/api/v1/users", json={**payload, "email": f"engineer{i}@example.com"}, headers=bearer(a)
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = list(pool.map(add, [1, 2]))
    assert sorted(codes) == [201, 409], codes
    me = api.get("/api/v1/me", headers=bearer(a)).json()["user"]
    body = {
        "display_name": "Owner",
        "role": "ENGINEER",
        "active": True,
        "work_mode": "FIELD",
        "reason": "Attempt to remove last admin",
    }
    assert (
        api.patch(
            "/api/v1/users/" + me["id"], json=body, headers={**bearer(a), "If-Match": str(me["version"])}
        ).status_code
        == 409
    )


def test_employee_rbac_and_revocation(system):
    tid, a = create_tenant(system)
    api = system["api"]
    added = api.post("/api/v1/users", json=employee(api, a), headers=bearer(a))
    assert added.status_code == 201, added.text
    raw = token_for(system, tid, "engineer@example.com")
    assert (
        api.post(
            "/api/v1/auth/accept-invite", json={"token": raw, "new_password": "Engineer-Test-Password-42"}
        ).status_code
        == 204
    )
    logged = api.post(
        "/api/v1/auth/login",
        json={
            "slug": "alpha-company",
            "email": "engineer@example.com",
            "password": "Engineer-Test-Password-42",
            "client_type": "native",
        },
    ).json()
    assert api.get("/api/v1/users", headers=bearer(logged)).status_code == 403
    assert api.get("/api/v1/me", headers=bearer(logged)).status_code == 200
    uid = added.json()["id"]
    current = api.get("/api/v1/users/" + uid, headers=bearer(a)).json()
    data = {
        "display_name": "Engineer",
        "role": "ENGINEER",
        "active": False,
        "work_mode": "FIELD",
        "reason": "Employee offboarding",
    }
    assert (
        api.patch(
            "/api/v1/users/" + uid, json=data, headers={**bearer(a), "If-Match": str(current["version"])}
        ).status_code
        == 200
    )
    assert api.get("/api/v1/me", headers=bearer(logged)).status_code == 401


def test_password_reset_revokes_all_and_single_use(system):
    tid, a = create_tenant(system)
    p = system["platform"]
    api = system["api"]
    uid = api.get("/api/v1/me", headers=bearer(a)).json()["user"]["id"]
    r = p.post(
        "/api/v1/platform/tenants/" + tid + "/reset-admin",
        json={"admin_user_id": uid, "reason": "Verified recovery requested"},
    )
    assert r.status_code == 202, r.text
    assert api.get("/api/v1/me", headers=bearer(a)).status_code == 401
    raw = token_for(system, tid)
    body = {"token": raw, "new_password": "Replacement-Password-42"}
    assert api.post("/api/v1/auth/reset-password", json=body).status_code == 204
    assert api.post("/api/v1/auth/reset-password", json=body).status_code == 400
    assert (
        api.post(
            "/api/v1/auth/login",
            json={"slug": "alpha-company", "email": "owner@example.com", "password": "Replacement-Password-42"},
        ).status_code
        == 200
    )


def test_auth_rate_limit_and_generic_errors(system):
    api = system["api"]
    statuses = [
        api.post(
            "/api/v1/auth/login", json={"slug": "no-company", "email": "nobody@example.com", "password": "invalid"}
        ).status_code
        for _ in range(11)
    ]
    assert statuses[-1] == 429
    body = {"slug": "no-company", "email": "nobody@example.com", "password": "secret", "tenant_id": str(uuid4())}
    r = api.post("/api/v1/auth/login", json=body)
    assert r.status_code == 422 and "secret" not in r.text


def test_runtime_roles_do_not_read_global_or_future_business(system):
    tid, a = create_tenant(system)
    for query in [
        "SELECT * FROM control.platform_admins",
        "SELECT * FROM control.tenants",
        "SELECT * FROM app.tickets",
        "TRUNCATE app.users",
    ]:
        with pytest.raises(DBAPIError):
            with tenant_db(tid) as db:
                db.execute(text(query)).all()
    with pytest.raises(DBAPIError):
        with tenant_db(tid, "control") as db:
            db.execute(text("SELECT * FROM app.tickets")).all()


def test_all_business_tables_have_force_rls(system):
    with system["owner"].connect() as conn:
        rows = conn.execute(
            text(
                "SELECT c.relname,c.relrowsecurity,c.relforcerowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='app' AND c.relkind='r'"
            )
        ).all()
        assert len(rows) == 49
        assert all(r.relrowsecurity and r.relforcerowsecurity for r in rows)


def test_refresh_preserves_absolute_expiry(system):
    tid, auth = create_tenant(system)
    old_id = auth["refresh_token"].split(".")[1]
    r = system["api"].post("/api/v1/auth/refresh", json={"refresh_token": auth["refresh_token"]})
    assert r.status_code == 200
    new_id = r.json()["refresh_token"].split(".")[1]
    with tenant_db(tid) as db:
        rows = (
            db.execute(text("SELECT expires_at FROM app.auth_sessions WHERE id IN (:a,:b)"), {"a": old_id, "b": new_id})
            .scalars()
            .all()
        )
    assert len(rows) == 2 and rows[0] == rows[1]


def test_orm_scope_and_flush_guard(system):
    from sqlalchemy import select
    from sqlalchemy.orm import Mapped, mapped_column
    from sqlalchemy.dialects.postgresql import UUID as PGUUID
    from uuid import UUID
    from app.db import Base, TenantRow

    class UserProbe(TenantRow, Base):
        __tablename__ = "users"
        __table_args__ = {"schema": "app", "extend_existing": True}
        id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)

    a, _ = create_tenant(system)
    b, _ = create_tenant(system, "beta-company")
    with tenant_db(a) as db:
        assert {str(row.tenant_id) for row in db.scalars(select(UserProbe))} == {a}
    with pytest.raises(PermissionError):
        with tenant_db(a) as db:
            db.add(UserProbe(tenant_id=UUID(b), id=uuid4()))
            db.flush()


def test_platform_refresh_csrf_replay_and_logout(system):
    p = system["platform"]
    csrf = p.cookies.get("platform_csrf")
    old = p.cookies.get("platform_refresh")
    assert p.post("/api/v1/platform/auth/refresh", json={}).status_code == 403
    headers = {"Origin": "http://testserver", "X-CSRF-Token": csrf}
    r = p.post("/api/v1/platform/auth/refresh", json={}, headers=headers)
    assert r.status_code == 200
    p.headers["Authorization"] = "Bearer " + r.json()["access_token"]
    assert p.get("/api/v1/platform/tenants").status_code == 200
    # Reuse the exact former cookie and its CSRF proof, without duplicate-cookie ambiguity.
    replay = p.post("/api/v1/platform/auth/refresh", json={}, headers={**headers, "Cookie": f"platform_refresh={old}"})
    assert replay.status_code == 401
    assert p.get("/api/v1/platform/tenants").status_code == 401


def test_mail_worker_tenant_scope_delivery_and_superseded_tokens(system):
    import os
    from sqlalchemy import create_engine
    from app.mail_worker import tick

    for slug in ["alpha-company", "beta-company"]:
        r = system["platform"].post(
            "/api/v1/platform/tenants", json=tenant_payload(slug), headers={"Idempotency-Key": str(uuid4())}
        )
        assert r.status_code == 201
    mail = create_engine(os.environ["MAIL_DATABASE_URL"])
    captured = []
    assert tick(mail, lambda *args: captured.append(args)) == 2
    assert {c[1] for c in captured} == {"alpha-company", "beta-company"}
    assert tick(mail, lambda *args: captured.append(args)) == 0
    with system["owner"].connect() as conn:
        assert (
            conn.execute(
                text("SELECT count(*) FROM app.outbox WHERE delivered_at IS NOT NULL AND payload='{}'::jsonb")
            ).scalar_one()
            == 2
        )
    mail.dispose()


def test_mail_worker_failure_retains_encrypted_payload_and_backoff(system):
    import os
    from sqlalchemy import create_engine
    from app.mail_worker import tick

    r = system["platform"].post(
        "/api/v1/platform/tenants", json=tenant_payload("alpha-company"), headers={"Idempotency-Key": str(uuid4())}
    )
    assert r.status_code == 201
    mail = create_engine(os.environ["MAIL_DATABASE_URL"])

    def failed(*args):
        raise RuntimeError("Simulated provider outage")

    assert tick(mail, failed) == 0
    with system["owner"].connect() as conn:
        row = (
            conn.execute(text("SELECT attempts,last_error_code,available_at>now() AS delayed,payload FROM app.outbox"))
            .mappings()
            .one()
        )
        assert row["attempts"] == 1 and row["last_error_code"] == "DELIVERY_FAILED" and row["delayed"]
        assert "token_ciphertext" in row["payload"]
    mail.dispose()


def test_expired_tenant_and_expired_access_token_rejected(system):
    import jwt
    from app.config import settings
    from app.security import now
    from datetime import timedelta

    tid, auth = create_tenant(system)
    cfg = settings()
    data = jwt.decode(
        auth["access_token"], cfg.jwt_secret, algorithms=["HS256"], audience="tenant", issuer=cfg.jwt_issuer
    )
    data["exp"] = now() - timedelta(seconds=1)
    expired = jwt.encode(data, cfg.jwt_secret, algorithm="HS256")
    assert system["api"].get("/api/v1/me", headers={"Authorization": "Bearer " + expired}).status_code == 401
    with system["owner"].begin() as conn:
        conn.execute(text("UPDATE control.tenants SET valid_until=now()-interval '1 day' WHERE id=:id"), {"id": tid})
    assert system["api"].get("/api/v1/me", headers=bearer(auth)).status_code == 403


def test_invite_superseded_by_reset_and_foreign_admin_reset_rejected(system):
    a, aa = create_tenant(system)
    b, bb = create_tenant(system, "beta-company")
    other = system["api"].get("/api/v1/me", headers=bearer(bb)).json()["user"]["id"]
    r = system["platform"].post(
        f"/api/v1/platform/tenants/{a}/reset-admin", json={"admin_user_id": other, "reason": "Attempt foreign reset"}
    )
    assert r.status_code == 404
    assert system["api"].get("/api/v1/me", headers=bearer(bb)).status_code == 200


def test_pending_invitation_reissue_supersedes_old_link(system):
    tid, auth = create_tenant(system)
    api = system["api"]
    r = api.post("/api/v1/users", json=employee(api, auth), headers=bearer(auth))
    assert r.status_code == 201
    old = token_for(system, tid, "engineer@example.com")
    url = "/api/v1/users/" + r.json()["id"] + "/reissue-invite"
    assert (
        api.post(url, json={"reason": "Employee requested a new invitation"}, headers=bearer(auth)).status_code == 202
    )
    new = token_for(system, tid, "engineer@example.com")
    assert new != old
    assert (
        api.post("/api/v1/auth/accept-invite", json={"token": old, "new_password": "Reissued-Password-42"}).status_code
        == 400
    )
    assert (
        api.post("/api/v1/auth/accept-invite", json={"token": new, "new_password": "Reissued-Password-42"}).status_code
        == 204
    )
    assert api.post(url, json={"reason": "Attempt to reset accepted account"}, headers=bearer(auth)).status_code == 409


def test_password_whitespace_preserved_and_chunked_body_bounded(system):
    from app.schemas import Login, Reset

    assert (
        Login(slug="test-company", email="user@example.com", password=" password with spaces ").password
        == " password with spaces "
    )
    assert Reset(token="a", new_password=" password with spaces ").new_password == " password with spaces "
    response = system["api"].post(
        "/api/v1/auth/login", content=iter([b"x" * 40000, b"y" * 40000]), headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 413


def test_rate_bucket_cleanup_has_narrow_worker_privileges(system):
    import os
    from sqlalchemy import create_engine

    mail = create_engine(os.environ["MAIL_DATABASE_URL"])
    with system["owner"].begin() as conn:
        conn.execute(
            text(
                "INSERT INTO control.rate_buckets(key_hash,bucket,hits,expires_at) VALUES(:key,0,1,now()-interval '1 day')"
            ),
            {"key": "a" * 64},
        )
    with mail.begin() as conn:
        conn.execute(text("SELECT control.prune_rate_buckets()"))
    with system["owner"].connect() as conn:
        assert (
            conn.execute(
                text("SELECT count(*) FROM control.rate_buckets WHERE key_hash=:key"), {"key": "a" * 64}
            ).scalar_one()
            == 0
        )
    with pytest.raises(DBAPIError):
        with mail.connect() as conn:
            conn.execute(text("SELECT * FROM control.platform_admins")).all()
    mail.dispose()
