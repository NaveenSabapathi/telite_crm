import hashlib
import hmac
import secrets
import time
from datetime import datetime, timezone, timedelta
from uuid import UUID, uuid4
import jwt
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from cryptography.fernet import Fernet
from fastapi import HTTPException, Request
from .config import settings

PH = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
DUMMY_HASH = PH.hash(secrets.token_urlsafe(32))


def now():
    return datetime.now(timezone.utc)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def encrypt(value):
    return Fernet(settings().field_encryption_key.encode()).encrypt(value.encode()).decode()


def decrypt(value):
    return Fernet(settings().field_encryption_key.encode()).decrypt(value.encode()).decode()


def password_ok(value, hashed):
    try:
        return PH.verify(hashed or DUMMY_HASH, value)
    except (VerificationError, InvalidHashError):
        return False


def fail(status=401, code="INVALID_CREDENTIALS"):
    raise HTTPException(status, detail=code)


def access_token(user_id, session_id, version, tenant_id=None):
    cfg = settings()
    return jwt.encode(
        {
            "sub": str(user_id),
            "sid": str(session_id),
            "ver": version,
            "tid": str(tenant_id) if tenant_id else None,
            "aud": "tenant" if tenant_id else "platform",
            "iss": cfg.jwt_issuer,
            "iat": now(),
            "exp": now() + timedelta(seconds=cfg.access_token_ttl_seconds),
            "jti": str(uuid4()),
        },
        cfg.jwt_secret if tenant_id else cfg.platform_jwt_secret,
        algorithm="HS256",
    )


def claims(request: Request, audience):
    value = request.headers.get("authorization", "")
    if not value.startswith("Bearer "):
        fail()
    try:
        data = jwt.decode(
            value[7:],
            settings().jwt_secret if audience == "tenant" else settings().platform_jwt_secret,
            algorithms=["HS256"],
            audience=audience,
            issuer=settings().jwt_issuer,
            options={"require": ["exp", "iat", "sub", "sid", "ver", "aud", "iss"]},
        )
        UUID(data["sub"])
        UUID(data["sid"])
        if audience == "tenant":
            UUID(data["tid"])
        elif data.get("tid"):
            fail()
        return data
    except (jwt.PyJWTError, ValueError, TypeError, KeyError):
        fail()


def secret_token(tenant_id, identifier):
    return f"{tenant_id}.{identifier}.{secrets.token_urlsafe(40)}"


def parse_secret(value):
    try:
        tid, sid, secret = value.split(".")
        if len(secret) < 40:
            fail()
        return UUID(tid), UUID(sid)
    except (ValueError, AttributeError):
        fail()


def totp_step(secret, code):
    current = int(time.time()) // 30
    generator = pyotp.TOTP(secret)
    for step in (current, current - 1):
        if hmac.compare_digest(generator.at(step * 30), code):
            return step
    return None


def expected_version(request):
    value = request.headers.get("if-match", "").strip('"')
    if not value.isdigit():
        fail(428, "VERSION_REQUIRED")
    return int(value)


def web_guard(request, csrf_hash):
    if request.headers.get("origin") != settings().public_web_url:
        fail(403, "ORIGIN_REJECTED")
    if not hmac.compare_digest(digest(request.headers.get("x-csrf-token", "")), csrf_hash):
        fail(403, "CSRF_REJECTED")
