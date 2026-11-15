"""Deliver auth invitations/reset links from durable per-tenant outboxes.

Run as crm_mail only. No FCM/month-end jobs are claimed in Phase 2.
"""

import argparse
import os
import smtplib
import ssl
import time
from email.message import EmailMessage
from sqlalchemy import create_engine, text
from .config import settings
from .db import TenantSession, one, run
from .security import decrypt


def send_mail(recipient, slug, token, purpose):
    cfg = settings()
    if not cfg.smtp_host or not cfg.smtp_from_address:
        raise RuntimeError("SMTP is not configured")
    message = EmailMessage()
    message["From"] = cfg.smtp_from_address
    message["To"] = recipient
    message["Subject"] = "Telite CRM — " + ("Accept your invitation" if purpose == "INVITE" else "Reset your password")
    url = f"{cfg.public_web_url}/#token={token}&purpose={purpose}"
    message.set_content(
        f"Company: {slug}\n\nOpen this link to set your password:\n{url}\n\n"
        "This link is single-use and time-limited. If unexpected, contact your company administrator.\n"
    )
    with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=20) as client:
        client.ehlo()
        if cfg.smtp_starttls:
            client.starttls(context=ssl.create_default_context())
            client.ehlo()
        if cfg.smtp_username:
            client.login(cfg.smtp_username, cfg.smtp_password)
        client.send_message(message)


def tick(mail_engine, sender=send_mail):
    sent = 0
    with mail_engine.begin() as conn:
        conn.execute(text("SELECT control.prune_rate_buckets()"))
        tenants = (
            conn.execute(
                text("SELECT id,slug FROM control.tenants WHERE status='ACTIVE' AND valid_until>now() ORDER BY id")
            )
            .mappings()
            .all()
        )
    for tenant in tenants:
        with TenantSession(mail_engine, tenant_id=tenant["id"]) as db, db.begin():
            item = one(
                db,
                """SELECT * FROM app.outbox WHERE event_type='AUTH_EMAIL' AND delivered_at IS NULL
                AND available_at<=now() AND attempts<8 AND (locked_until IS NULL OR locked_until<now())
                ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1""",
            )
            if not item:
                continue
            item = dict(item)
            run(
                db,
                "UPDATE app.outbox SET locked_until=now()+interval '2 minutes',attempts=attempts+1 WHERE id=:id",
                id=item["id"],
            )
        try:
            with TenantSession(mail_engine, tenant_id=tenant["id"]) as db, db.begin():
                user = one(db, "SELECT email,active FROM app.users WHERE id=:id", id=item["aggregate_id"])
                proof = one(
                    db,
                    "SELECT id FROM app.password_tokens WHERE id=:id AND user_id=:uid AND used_at IS NULL AND expires_at>now()",
                    id=item["payload"]["token_id"],
                    uid=item["aggregate_id"],
                )
                if not user or not user["active"] or not proof or user["email"] != item["payload"]["email"]:
                    run(
                        db,
                        "UPDATE app.outbox SET delivered_at=now(),locked_until=NULL,payload='{}',last_error_code='SUPERSEDED' WHERE id=:id",
                        id=item["id"],
                    )
                    continue
            sender(
                user["email"], tenant["slug"], decrypt(item["payload"]["token_ciphertext"]), item["payload"]["purpose"]
            )
            with TenantSession(mail_engine, tenant_id=tenant["id"]) as db, db.begin():
                run(
                    db,
                    "UPDATE app.outbox SET delivered_at=now(),locked_until=NULL,payload='{}',last_error_code=NULL WHERE id=:id",
                    id=item["id"],
                )
            sent += 1
        except Exception:
            # Do not log SMTP exception bodies: providers may echo links/addresses.
            with TenantSession(mail_engine, tenant_id=tenant["id"]) as db, db.begin():
                delay = min(3600, 30 * 2 ** item["attempts"])
                run(
                    db,
                    "UPDATE app.outbox SET locked_until=NULL,available_at=now()+make_interval(secs=>:delay),last_error_code='DELIVERY_FAILED' WHERE id=:id",
                    id=item["id"],
                    delay=delay,
                )
    return sent


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    mail_engine = create_engine(os.environ["MAIL_DATABASE_URL"], pool_pre_ping=True)
    while True:
        tick(mail_engine)
        if settings().operations_database_url:
            from .db import engine
            from .operations_worker import tick_operations

            tick_operations(mail_engine, engine("operations"))
        if args.once:
            break
        time.sleep(10)
