"""Synthetic browser fixtures: refuse to operate outside the disposable test DB."""

import json
import os
import sys
from uuid import uuid4
import pyotp
from sqlalchemy import create_engine, text
from app.security import PH, encrypt, decrypt

if os.environ.get("APP_ENV") != "test" or not os.environ.get("MIGRATION_DATABASE_URL", "").endswith("/telite_test"):
    raise RuntimeError("Only a disposable telite_test database is allowed")
owner = create_engine(os.environ["MIGRATION_DATABASE_URL"])
if sys.argv[1] == "bootstrap":
    secret = pyotp.random_base32()
    with owner.begin() as db:
        db.execute(text("TRUNCATE control.tenants,control.platform_admins,control.rate_buckets CASCADE"))
        db.execute(
            text(
                "INSERT INTO control.platform_admins(id,email,password_hash,mfa_secret_ciphertext) VALUES(:id,:email,:pw,:secret)"
            ),
            {
                "id": uuid4(),
                "email": "browser-admin@example.com",
                "pw": PH.hash("Browser-Platform-Test-42"),
                "secret": encrypt(secret),
            },
        )
    print(json.dumps({"otp": pyotp.TOTP(secret).now()}))
elif sys.argv[1] == "invitation":
    with owner.connect() as db:
        payload = db.execute(
            text(
                "SELECT o.payload FROM app.outbox o JOIN control.tenants t ON t.id=o.tenant_id WHERE t.slug=:slug ORDER BY o.created_at DESC LIMIT 1"
            ),
            {"slug": sys.argv[2]},
        ).scalar_one()
    print(json.dumps({"token": decrypt(payload["token_ciphertext"])}))
else:
    raise ValueError("Unknown fixture command")
