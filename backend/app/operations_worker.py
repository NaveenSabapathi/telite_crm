"""Durable in-app reminders and bounded monthly mail delivery. SMTP is at-least-once."""

import json
import smtplib
import ssl
from datetime import timedelta
from email.message import EmailMessage
from zoneinfo import ZoneInfo
from sqlalchemy import text
from .config import settings
from .db import TenantSession, one, many, run
from .security import now
from .operations import schedule, notify
from .reporting import flags, create_run, csv_bytes, pdf_bytes, MODULES


def deliver_report(email, report):
    cfg = settings()
    if not cfg.smtp_host or not cfg.smtp_from_address:
        raise RuntimeError("SMTP not configured")
    data = report["snapshot"]
    pdf = pdf_bytes(data)
    csv = csv_bytes(data)
    if len(pdf) + len(csv) > 10 * 1024 * 1024:
        raise RuntimeError("Report attachment limit")
    message = EmailMessage()
    message["From"] = cfg.smtp_from_address
    message["To"] = email
    message["Subject"] = ("TEST — " if report["kind"] == "TEST" else "") + f"Telite CRM monthly report {data['month']}"
    message["Message-ID"] = f"<{report['id']}@telite-crm>"
    message.set_content(
        f"{data['tenant']} — {data['month']}\nReport {report['id']} revision {report['revision']}\n{data['notes']}"
    )
    message.add_attachment(pdf, maintype="application", subtype="pdf", filename="monthly-report.pdf")
    message.add_attachment(csv, maintype="text", subtype="csv", filename="monthly-report.csv")
    with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=20) as smtp:
        smtp.ehlo()
        if cfg.smtp_starttls:
            smtp.starttls(context=ssl.create_default_context())
            smtp.ehlo()
        if cfg.smtp_username:
            smtp.login(cfg.smtp_username, cfg.smtp_password)
        smtp.send_message(message)


def reminders(db):
    enabled = flags(db)
    clock = now()
    if enabled.get("attendance_gps"):
        for user in many(
            db,
            "SELECT id,branch_id,shift_id FROM app.users WHERE tenant_id=app.current_tenant() AND active AND NOT must_reset_password",
        ):
            branch, shift, day, start, end = schedule(db, user, clock)
            if day.isoweekday() not in shift["weekdays"]:
                continue
            if one(
                db,
                "SELECT id FROM app.holidays WHERE tenant_id=app.current_tenant() AND branch_id=:bid AND holiday_date=:day",
                bid=branch["id"],
                day=day,
            ):
                continue
            if one(
                db,
                "SELECT id FROM app.leave_requests WHERE tenant_id=app.current_tenant() AND user_id=:uid AND status='APPROVED' AND starts_at<:end AND ends_at>:start",
                uid=user["id"],
                start=start,
                end=end,
            ):
                continue
            punch = one(
                db,
                "SELECT id,punch_out FROM app.attendance WHERE tenant_id=app.current_tenant() AND user_id=:uid AND shift_date=:day",
                uid=user["id"],
                day=day,
            )
            kind = None
            if start - timedelta(minutes=10) <= clock < start and not punch:
                kind = "SHIFT_UPCOMING"
            elif start + timedelta(minutes=shift["grace_minutes"]) < clock < end and not punch:
                kind = "SHIFT_LATE"
            if kind:
                notify(db, user["id"], kind, user["id"], f"{kind}:{day}:{shift['version']}")
        # Query open records independently: overnight/date boundaries must not hide missed checkout.
        for row in many(
            db,
            "SELECT id,user_id,shift_date FROM app.attendance WHERE tenant_id=app.current_tenant() AND punch_out IS NULL AND scheduled_end+interval '30 minutes'<now()",
        ):
            run(
                db,
                "UPDATE app.attendance SET status='INCOMPLETE' WHERE tenant_id=app.current_tenant() AND id=:id AND status='OPEN'",
                id=row["id"],
            )
            notify(db, row["user_id"], "MISSED_PUNCH_OUT", row["id"], f"missed:{row['id']}")
    if enabled.get("sales_crm"):
        for row in many(
            db,
            "SELECT id,assigned_to,next_followup_at,version FROM app.leads WHERE tenant_id=app.current_tenant() AND stage NOT IN ('WON','LOST') AND next_followup_at<=now()+interval '30 minutes'",
        ):
            notify(
                db,
                row["assigned_to"],
                "LEAD_FOLLOWUP_DUE",
                row["id"],
                f"followup:{row['id']}:{row['next_followup_at']}",
            )


def tick_operations(discovery_engine, operations_engine, sender=deliver_report):
    sent = 0
    with discovery_engine.connect() as conn:
        tenants = (
            conn.execute(
                text(
                    "SELECT id,created_at FROM control.tenants WHERE status='ACTIVE' AND valid_until>now() ORDER BY id"
                )
            )
            .mappings()
            .all()
        )
    for tenant in tenants:
        with (
            TenantSession(
                operations_engine.execution_options(isolation_level="REPEATABLE READ"), tenant_id=tenant["id"]
            ) as db,
            db.begin(),
        ):
            state = one(db, "SELECT * FROM control.tenant_state()")
            if not state or state["status"] != "ACTIVE" or state["valid_until"] <= now():
                continue
            reminders(db)
            enabled = flags(db)
            if not enabled.get("monthly_email_reports"):
                continue
            cfg = one(db, "SELECT * FROM control.operations_settings()")
            local = now().astimezone(ZoneInfo(cfg["timezone"]))
            recipients = [
                str(r["id"])
                for r in many(
                    db,
                    """SELECT u.id FROM app.users u JOIN app.report_preferences p ON p.tenant_id=u.tenant_id AND p.user_id=u.id
                WHERE u.tenant_id=app.current_tenant() AND u.active AND u.role='COMPANY_ADMIN' AND u.email_verified_at IS NOT NULL AND p.email_enabled""",
                )
            ]
            if recipients and (local.day > 1 or local.time() >= cfg["report_local_time"]):
                cursor = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                for _ in range(3):
                    cursor = (cursor - timedelta(days=1)).replace(day=1)
                    if cursor.date() < tenant["created_at"].astimezone(ZoneInfo(cfg["timezone"])).date().replace(day=1):
                        break
                    create_run(db, cursor.strftime("%Y-%m"), kind="SCHEDULED", recipients=recipients)
        with (
            TenantSession(
                operations_engine.execution_options(isolation_level="REPEATABLE READ"), tenant_id=tenant["id"]
            ) as db,
            db.begin(),
        ):
            report = one(
                db,
                """SELECT * FROM app.report_runs WHERE tenant_id=app.current_tenant() AND status='QUEUED'
                AND COALESCE((snapshot->>'attempts')::int,0)<8 AND COALESCE((snapshot->>'retry_at')::timestamptz,created_at)<=now()
                ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1""",
            )
            if not report:
                continue
            current = one(db, "SELECT * FROM control.tenant_state()")
            enabled = flags(db)
            if (
                current["status"] != "ACTIVE"
                or current["valid_until"] <= now()
                or not enabled.get("monthly_email_reports")
            ):
                continue
            if any(not enabled.get(MODULES[s]) for s in report["snapshot"]["sections"]):
                run(
                    db,
                    "UPDATE app.report_runs SET status='FAILED' WHERE tenant_id=app.current_tenant() AND id=:id",
                    id=report["id"],
                )
                continue
            try:
                for uid in report["recipient_snapshot"]:
                    recipient = one(
                        db,
                        "SELECT id,email FROM app.users WHERE tenant_id=app.current_tenant() AND id=:id AND active AND role='COMPANY_ADMIN' AND email_verified_at IS NOT NULL",
                        id=uid,
                    )
                    if not recipient:
                        continue
                    if report["kind"] == "SCHEDULED" and not one(
                        db,
                        "SELECT id FROM app.report_preferences WHERE tenant_id=app.current_tenant() AND user_id=:id AND email_enabled",
                        id=uid,
                    ):
                        continue
                    sender(recipient["email"], report)
                    sent += 1
                run(
                    db,
                    "UPDATE app.report_runs SET status='SENT',sent_at=now() WHERE tenant_id=app.current_tenant() AND id=:id",
                    id=report["id"],
                )
            except Exception:
                data = dict(report["snapshot"])
                attempts = int(data.get("attempts", 0)) + 1
                data.update(
                    attempts=attempts,
                    retry_at=(now() + timedelta(seconds=min(3600, 30 * 2**attempts))).isoformat(),
                    error="DELIVERY_FAILED",
                )
                run(
                    db,
                    "UPDATE app.report_runs SET snapshot=CAST(:data AS jsonb),status=:status WHERE tenant_id=app.current_tenant() AND id=:id",
                    data=json.dumps(data),
                    status="FAILED" if attempts >= 8 else "QUEUED",
                    id=report["id"],
                )
    return sent
