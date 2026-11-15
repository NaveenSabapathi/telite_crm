"""Tenant-local analytics and reproducible monthly report snapshots."""

import csv
import io
import json
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import Response
from fastapi.encoders import jsonable_encoder
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from xml.sax.saxutils import escape
from .operations_schemas import ReportPeriod
from .schemas import Strict
from .operations import guard, ADMIN, public, record, command, require_feature
from .db import one, many, run, TenantSession, engine
from .security import now, fail
from .services import audit, rate, tenant_identity, tenant_active

router = APIRouter(prefix="/api/v1", tags=["Analytics and reports"])


def report_identity(request: Request, identity=Depends(tenant_identity)):
    if request.state.user["role"] != "COMPANY_ADMIN":
        fail(403, "ROLE_FORBIDDEN")
    with (
        TenantSession(
            engine("operations").execution_options(isolation_level="REPEATABLE READ"), tenant_id=request.state.tenant_id
        ) as db,
        db.begin(),
    ):
        tenant_active(db)
        yield db


admin = report_identity
MODULES = {"attendance": "attendance_gps", "service": "field_service_tickets", "crm": "sales_crm"}


def flags(db):
    return {
        r["feature"]: r["enabled"]
        for r in many(db, "SELECT feature,enabled FROM control.tenant_features WHERE tenant_id=app.current_tenant()")
    }


def period(month, zone):
    start = datetime.strptime(month, "%Y-%m").replace(tzinfo=ZoneInfo(zone))
    end = start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def snapshot(db, month):
    cfg = one(db, "SELECT * FROM control.operations_settings()")
    tenant = one(db, "SELECT * FROM control.tenant_state()")
    start, end = period(month, cfg["timezone"])
    enabled = flags(db)
    result = {
        "tenant": tenant["name"],
        "month": month,
        "timezone": cfg["timezone"],
        "currency": cfg["currency"],
        "snapshot_at": now().isoformat(),
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "sections": {},
        "notes": "Straight-line travel is an unapproved estimate, not road distance. Incomplete attendance excludes worked hours. Late submissions may change later revisions.",
    }
    if enabled.get("attendance_gps"):
        rows = many(
            db,
            """SELECT u.id,u.display_name,count(a.id) FILTER(WHERE a.status<>'REVIEW') AS days_worked,
            count(a.id) FILTER(WHERE a.late_minutes>0 AND a.status<>'REVIEW') AS late_count,
            count(a.id) FILTER(WHERE a.punch_out IS NULL) AS incomplete,
            COALESCE(sum(GREATEST(0,extract(epoch FROM(a.punch_out-a.punch_in))/3600-a.break_minutes/60.0)) FILTER(WHERE a.status='COMPLETE'),0) AS hours,
            COALESCE((SELECT sum(distance_km) FROM app.travel_segments s WHERE s.tenant_id=u.tenant_id AND s.user_id=u.id AND s.created_at>=:start AND s.created_at<:end),0) AS straight_line_km
            FROM app.users u LEFT JOIN app.attendance a ON a.tenant_id=u.tenant_id AND a.user_id=u.id AND a.scheduled_start>=:start AND a.scheduled_start<:end
            WHERE u.tenant_id=app.current_tenant() GROUP BY u.tenant_id,u.id,u.display_name ORDER BY u.display_name""",
            start=start,
            end=end,
        )
        result["sections"]["attendance"] = [dict(r) for r in rows]
    if enabled.get("field_service_tickets"):
        metrics = dict(
            one(
                db,
                """SELECT count(*) FILTER(WHERE completed_at>=:start AND completed_at<:end) AS closed,
            count(*) FILTER(WHERE completed_at>=:start AND completed_at<:end AND completed_at<=sla_due_at+make_interval(secs=>sla_paused_seconds)) AS sla_met
            FROM app.tickets WHERE tenant_id=app.current_tenant()""",
                start=start,
                end=end,
            )
        )
        metrics["sla_percent"] = round(metrics["sla_met"] * 100 / metrics["closed"], 2) if metrics["closed"] else None
        metrics.update(
            one(
                db,
                """SELECT COALESCE(sum(CASE WHEN status IN ('VERIFIED','REVERSED') AND received_at>=:start AND received_at<:end THEN amount ELSE 0 END),0)
            -COALESCE(sum(CASE WHEN status='REVERSED' AND reversed_at>=:start AND reversed_at<:end THEN amount ELSE 0 END),0) AS verified_revenue,
            COALESCE(sum(amount) FILTER(WHERE status='RECORDED' AND received_at>=:start AND received_at<:end),0) AS recorded_unverified
            FROM app.payments WHERE tenant_id=app.current_tenant()""",
                start=start,
                end=end,
            )
        )
        result["sections"]["service"] = [metrics]
    if enabled.get("sales_crm"):
        result["sections"]["crm"] = [
            dict(r)
            for r in many(
                db,
                """SELECT details->>'owner_at_win' AS owner_at_win,count(*) AS wins,
            COALESCE(sum((details->>'won_value')::numeric),0) AS won_value FROM app.lead_activities
            WHERE tenant_id=app.current_tenant() AND kind='STAGE' AND details->>'to'='WON' AND occurred_at>=:start AND occurred_at<:end
            GROUP BY details->>'owner_at_win' """,
                start=start,
                end=end,
            )
        ]
        result["lead_cohort"] = dict(
            one(
                db,
                """SELECT count(*) AS created,count(*) FILTER(WHERE stage='WON') AS won_by_snapshot
            FROM app.leads WHERE tenant_id=app.current_tenant() AND created_at>=:start AND created_at<:end""",
                start=start,
                end=end,
            )
        )
    return jsonable_encoder(result, custom_encoder={Decimal: str})


def create_run(db, month, actor=None, kind="DOWNLOAD", recipients=None):
    # Serialize revisions, and scheduled dedupe, inside the same tenant transaction.
    run(db, "SELECT pg_advisory_xact_lock(hashtextextended(:key,0))", key=f"report:{db._tenant_id}:{month}:{kind}")
    cfg = one(db, "SELECT * FROM control.operations_settings()")
    start, end = period(month, cfg["timezone"])
    if start > now():
        fail(422, "FUTURE_REPORT_PERIOD")
    if kind == "SCHEDULED":
        old = one(
            db,
            "SELECT * FROM app.report_runs WHERE tenant_id=app.current_tenant() AND kind='SCHEDULED' AND period_start=:start",
            start=start,
        )
        if old:
            return public(old)
    revision = one(
        db,
        "SELECT COALESCE(max(revision),0)+1 AS n FROM app.report_runs WHERE tenant_id=app.current_tenant() AND kind=:kind AND period_start=:start",
        kind=kind,
        start=start,
    )["n"]
    data = snapshot(db, month)
    data["revision"] = revision
    row = one(
        db,
        """INSERT INTO app.report_runs(tenant_id,period_start,period_end,timezone,kind,revision,status,requested_by,recipient_snapshot,snapshot_at,snapshot)
        VALUES(app.current_tenant(),:start,:end,:zone,:kind,:revision,:status,:actor,CAST(:recipients AS jsonb),now(),CAST(:data AS jsonb)) RETURNING *""",
        start=start,
        end=end,
        zone=cfg["timezone"],
        kind=kind,
        revision=revision,
        status="READY" if kind == "DOWNLOAD" else "QUEUED",
        actor=actor,
        recipients=json.dumps(recipients or []),
        data=json.dumps(data),
    )
    return public(row)


def safe_cell(value):
    value = str(value) if value is not None else "N/A"
    return (
        "'" + value
        if value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")) or value.startswith(("\t", "\r"))
        else value
    )


def csv_bytes(data):
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["Tenant", "Period", "Timezone", "Currency", "Snapshot", "Revision"])
    writer.writerow(
        [safe_cell(data[k]) for k in ("tenant", "month", "timezone", "currency", "snapshot_at", "revision")]
    )
    for section, rows in data["sections"].items():
        writer.writerow([])
        writer.writerow([section])
        if rows:
            keys = list(rows[0])
            writer.writerow(keys)
            for row in rows:
                writer.writerow([safe_cell(row.get(k)) for k in keys])
        else:
            writer.writerow(["No data for this period"])
    writer.writerow([data["notes"]])
    return out.getvalue().encode("utf-8-sig")


def pdf_bytes(data):
    output = io.BytesIO()
    styles = getSampleStyleSheet()
    story = []

    def para(value, style="BodyText"):
        return Paragraph(escape(str(value)), styles[style])

    story.extend(
        [
            para(data["tenant"], "Title"),
            para(f"Monthly report · {data['month']} · {data['currency']}", "Heading2"),
            para(f"Timezone: {data['timezone']} | Snapshot: {data['snapshot_at']} | Revision: {data['revision']}"),
            Spacer(1, 14),
        ]
    )
    for section, rows in data["sections"].items():
        story.append(para(section.title(), "Heading2"))
        if not rows:
            story.append(para("No data for this period."))
            continue
        # Vertical record layout avoids clipping wide employee tables.
        for row in rows:
            table = Table(
                [[para(k.replace("_", " ").title()), para("N/A" if v is None else v)] for k, v in row.items()],
                colWidths=[165, 340],
                hAlign="LEFT",
            )
            table.setStyle(
                TableStyle(
                    [
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#edf4f2")),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ]
                )
            )
            story.extend([table, Spacer(1, 12)])
    story.append(para(data["notes"]))

    def page(canvas, doc):
        canvas.setFont("Helvetica", 8)
        canvas.drawRightString(550, 25, f"Page {doc.page}")

    SimpleDocTemplate(output, title="Monthly operational report", leftMargin=40, rightMargin=40).build(
        story, onFirstPage=page, onLaterPages=page
    )
    return output.getvalue()


@router.get("/dashboard")
def dashboard(db=Depends(admin)):
    enabled = flags(db)
    cfg = one(db, "SELECT * FROM control.operations_settings()")
    day = now().astimezone(ZoneInfo(cfg["timezone"])).date()
    result = {"date": day, "currency": cfg["currency"], "snapshot_at": now()}
    if enabled.get("attendance_gps"):
        result["attendance"] = dict(
            one(
                db,
                """SELECT count(*) FILTER(WHERE status<>'REVIEW') AS present,count(*) FILTER(WHERE late_minutes>0 AND status<>'REVIEW') AS late,
            count(*) FILTER(WHERE work_mode='FIELD' AND status<>'REVIEW') AS on_field FROM app.attendance WHERE tenant_id=app.current_tenant() AND shift_date=:day""",
                day=day,
            )
        )
        result["attendance"]["absent"] = one(
            db,
            """SELECT count(*) AS n FROM app.users u JOIN app.shifts s ON s.tenant_id=u.tenant_id AND s.id=u.shift_id
            WHERE u.tenant_id=app.current_tenant() AND u.active AND NOT u.must_reset_password AND :weekday=ANY(s.weekdays)
            AND u.employment_starts_on<=:day AND (u.employment_ends_on IS NULL OR u.employment_ends_on>=:day)
            AND NOT EXISTS(SELECT 1 FROM app.attendance a WHERE a.tenant_id=u.tenant_id AND a.user_id=u.id AND a.shift_date=:day)
            AND NOT EXISTS(SELECT 1 FROM app.holidays h WHERE h.tenant_id=u.tenant_id AND h.branch_id=u.branch_id AND h.holiday_date=:day)
            AND NOT EXISTS(SELECT 1 FROM app.leave_requests l WHERE l.tenant_id=u.tenant_id AND l.user_id=u.id AND l.status='APPROVED' AND l.starts_at<=now() AND l.ends_at>now())""",
            day=day,
            weekday=day.isoweekday(),
        )["n"]
    if enabled.get("field_service_tickets"):
        result["service"] = dict(
            one(
                db,
                """SELECT count(*) FILTER(WHERE status NOT IN ('COMPLETED','CANCELLED')) AS open,
            count(*) FILTER(WHERE status='IN_PROGRESS') AS in_progress,count(*) FILTER(WHERE status='COMPLETED') AS completed,
            count(*) FILTER(WHERE status<>'CANCELLED' AND COALESCE(completed_at,now())>sla_due_at+make_interval(secs=>sla_paused_seconds)) AS sla_breached
            FROM app.tickets WHERE tenant_id=app.current_tenant()""",
            )
        )
        result["service"]["verified_revenue"] = one(
            db,
            "SELECT COALESCE(sum(amount),0) AS n FROM app.payments WHERE tenant_id=app.current_tenant() AND status='VERIFIED'",
        )["n"]
    if enabled.get("sales_crm"):
        result["crm"] = many(
            db,
            "SELECT stage,count(*) AS count,sum(estimated_value) AS pipeline FROM app.leads WHERE tenant_id=app.current_tenant() GROUP BY stage",
        )
    return result


@router.post("/reports", status_code=201)
def generate(body: ReportPeriod, request: Request, db=Depends(admin)):
    def action():
        report = create_run(db, body.month, request.state.user["id"])
        audit(db, request, "REPORT_GENERATED", report["id"])
        return {"id": report["id"], "status": report["status"]}

    return command(db, request, body, action)


@router.get("/reports/{rid}/download")
def download(rid: UUID, format: str = Query("csv", pattern="^(csv|pdf)$"), db=Depends(admin)):
    report = record(db, "report_runs", rid)
    data = report["snapshot"]
    if not data:
        fail(409, "REPORT_NOT_READY")
    for section in data["sections"]:
        require_feature(db, MODULES[section])
    payload = pdf_bytes(data) if format == "pdf" else csv_bytes(data)
    return Response(
        payload,
        media_type="application/pdf" if format == "pdf" else "text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="telite-{data["month"]}-r{report["revision"]}.{format}"'
        },
    )


@router.post("/reports/test-email", status_code=202)
def email(body: ReportPeriod, request: Request, db=Depends(guard("monthly_email_reports", ADMIN))):
    rate(request, "report-email", str(request.state.user["id"]))
    if not request.state.user["email_verified_at"]:
        fail(403, "VERIFIED_EMAIL_REQUIRED")

    def action():
        recent = one(
            db,
            "SELECT count(*) AS n FROM app.report_runs WHERE tenant_id=app.current_tenant() AND requested_by=:uid AND kind='TEST' AND created_at>now()-interval '1 hour'",
            uid=request.state.user["id"],
        )["n"]
        if recent >= 3:
            fail(429, "REPORT_RATE_LIMIT")
        report = create_run(db, body.month, request.state.user["id"], "TEST", [str(request.state.user["id"])])
        return {"id": report["id"], "status": report["status"]}

    return command(db, request, body, action)


class Preference(Strict):
    email_enabled: bool


@router.put("/report-settings")
def preference(body: Preference, request: Request, db=Depends(guard("monthly_email_reports", ADMIN))):
    run(
        db,
        """INSERT INTO app.report_preferences(tenant_id,user_id,email_enabled) VALUES(app.current_tenant(),:uid,:enabled)
        ON CONFLICT(tenant_id,user_id) DO UPDATE SET email_enabled=:enabled""",
        uid=request.state.user["id"],
        enabled=body.email_enabled,
    )
    audit(db, request, "REPORT_PREFERENCE_UPDATED", request.state.user["id"])
    return body.model_dump()
