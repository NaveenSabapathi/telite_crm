"""Operator commands: migrate roles, bootstrap MFA administrator; never HTTP routes."""

import argparse
import getpass
import os
from uuid import uuid4
import psycopg
from psycopg import sql
from sqlalchemy import create_engine, text
import pyotp
from .security import PH, encrypt


def roles():
    # Run after migration with a role allowed to CREATE ROLE/GRANT.
    url = os.environ["MIGRATION_DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(url) as conn:
        for name, variable in [
            ("crm_api", "API_DB_PASSWORD"),
            ("crm_control", "CONTROL_DB_PASSWORD"),
            ("crm_mail", "MAIL_DB_PASSWORD"),
        ]:
            password = os.environ[variable]
            if len(password) < 24:
                raise ValueError(f"{variable} must be at least 24 random characters")
            exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (name,)).fetchone()
            if not exists:
                conn.execute(
                    sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE").format(
                        sql.Identifier(name)
                    )
                )
            conn.execute(sql.SQL("ALTER ROLE {} PASSWORD {}").format(sql.Identifier(name), sql.Literal(password)))
        conn.execute("GRANT USAGE ON SCHEMA app,control TO crm_api,crm_control,crm_mail")
        conn.execute(
            "GRANT EXECUTE ON FUNCTION app.current_tenant(), app.protect_row(), app.enforce_user_limit(), control.tenant_state(), control.lock_tenant() TO crm_api,crm_control"
        )
        conn.execute(
            "GRANT EXECUTE ON FUNCTION control.resolve_slug(text), control.rate_limit(text,integer,integer) TO crm_api,crm_control"
        )
        conn.execute("GRANT SELECT ON control.tenant_features TO crm_api")
        conn.execute(
            "GRANT SELECT,INSERT,UPDATE ON app.users,app.auth_sessions,app.password_tokens TO crm_api,crm_control"
        )
        conn.execute("GRANT SELECT ON app.branches,app.shifts TO crm_api")
        conn.execute("GRANT SELECT,INSERT ON app.audit_logs TO crm_api,crm_control")
        conn.execute("GRANT INSERT ON app.outbox TO crm_api,crm_control")
        conn.execute(
            "GRANT SELECT,INSERT,UPDATE ON control.tenants,control.tenant_features,control.platform_admins,control.platform_sessions TO crm_control"
        )
        conn.execute("GRANT SELECT,INSERT ON control.platform_audit TO crm_control")
        conn.execute("GRANT SELECT,INSERT ON app.branches,app.shifts TO crm_control")
        conn.execute("GRANT SELECT ON control.tenants TO crm_mail")
        conn.execute("GRANT EXECUTE ON FUNCTION control.prune_rate_buckets() TO crm_mail")
        conn.execute("GRANT EXECUTE ON FUNCTION app.current_tenant(),app.protect_row() TO crm_mail")
        conn.execute("GRANT SELECT,UPDATE ON app.outbox TO crm_mail")
        conn.execute("GRANT SELECT ON app.users,app.password_tokens TO crm_mail")
    print("Runtime roles provisioned with explicit grants; no business-module privileges granted.")


def admin(email):
    password = getpass.getpass("New platform password (12+ characters): ")
    if len(password) < 12:
        raise ValueError("Use at least 12 characters")
    secret = pyotp.random_base32()
    # Show once locally for enrollment, not an HTTP response or log sink.
    print(pyotp.TOTP(secret).provisioning_uri(email, issuer_name="Telite CRM Platform"))
    code = getpass.getpass("Enter authenticator code to confirm enrollment: ")
    if not pyotp.TOTP(secret).verify(code, valid_window=1):
        raise ValueError("Authenticator verification failed")
    with create_engine(os.environ["MIGRATION_DATABASE_URL"]).begin() as conn:
        conn.execute(
            text(
                "INSERT INTO control.platform_admins(id,email,password_hash,mfa_secret_ciphertext) VALUES(:id,:email,:password,:secret)"
            ),
            {"id": uuid4(), "email": email.lower(), "password": PH.hash(password), "secret": encrypt(secret)},
        )
    print("Platform administrator created. Keep the authenticator recovery secret securely offline.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["roles", "admin"])
    parser.add_argument("--email")
    args = parser.parse_args()
    if args.command == "roles":
        roles()
    else:
        if not args.email:
            parser.error("--email required")
        admin(args.email)
