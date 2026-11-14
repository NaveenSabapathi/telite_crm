import os
from uuid import uuid4
import pytest
import pyotp
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from app.main import create_app
from app.security import PH, encrypt, decrypt


@pytest.fixture
def system():
    if os.environ.get("APP_ENV") != "test" or not os.environ.get("MIGRATION_DATABASE_URL", "").endswith("/telite_test"):
        pytest.fail("Integration suite requires APP_ENV=test and a disposable database named telite_test")
    owner = create_engine(os.environ["MIGRATION_DATABASE_URL"])
    with owner.begin() as conn:
        conn.execute(text("TRUNCATE control.tenants,control.platform_admins,control.rate_buckets CASCADE"))
        uid = uuid4()
        secret = pyotp.random_base32()
        conn.execute(
            text(
                "INSERT INTO control.platform_admins(id,email,password_hash,mfa_secret_ciphertext) VALUES(:id,:email,:hash,:secret)"
            ),
            {
                "id": uid,
                "email": "platform@example.com",
                "hash": PH.hash("Platform-Test-Password-42"),
                "secret": encrypt(secret),
            },
        )
    with TestClient(create_app()) as api, TestClient(create_app(True)) as platform:
        result = platform.post(
            "/api/v1/platform/auth/login",
            json={
                "email": "platform@example.com",
                "password": "Platform-Test-Password-42",
                "otp": pyotp.TOTP(secret).now(),
            },
        )
        assert result.status_code == 200, result.text
        platform.headers["Authorization"] = "Bearer " + result.json()["access_token"]
        yield {"api": api, "platform": platform, "owner": owner, "otp": secret}
    owner.dispose()


def tenant_payload(slug, cap=4):
    return {
        "name": slug.title(),
        "slug": slug,
        "max_active_employees": cap,
        "storage_quota_bytes": 10485760,
        "valid_until": "2030-11-14T00:00:00Z",
        "branch": {"name": "Main", "address": "Office", "lat": 11.3, "lng": 77.7},
        "shift": {"name": "Day", "start_local": "09:30", "end_local": "18:30", "weekdays": [1, 2, 3, 4, 5]},
        "admin": {"email": "owner@example.com", "display_name": "Owner"},
        "features": {"attendance_gps": True, "field_service_tickets": True, "sales_crm": True},
    }


def token_for(system, tid, email="owner@example.com"):
    with system["owner"].begin() as conn:
        record = conn.execute(
            text(
                "SELECT o.payload FROM app.outbox o JOIN app.users u ON u.tenant_id=o.tenant_id AND u.id=o.aggregate_id WHERE o.tenant_id=:tid AND u.email=:email ORDER BY o.created_at DESC LIMIT 1"
            ),
            {"tid": tid, "email": email},
        ).scalar_one()
    return decrypt(record["token_ciphertext"])


def create_tenant(system, slug="alpha-company", cap=4):
    r = system["platform"].post(
        "/api/v1/platform/tenants", json=tenant_payload(slug, cap), headers={"Idempotency-Key": str(uuid4())}
    )
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    token = token_for(system, tid)
    accepted = system["api"].post(
        "/api/v1/auth/accept-invite", json={"token": token, "new_password": "Tenant-Test-Password-42"}
    )
    assert accepted.status_code == 204, accepted.text
    r = system["api"].post(
        "/api/v1/auth/login",
        json={
            "slug": slug,
            "email": "owner@example.com",
            "password": "Tenant-Test-Password-42",
            "client_type": "native",
        },
    )
    assert r.status_code == 200, r.text
    return tid, r.json()
