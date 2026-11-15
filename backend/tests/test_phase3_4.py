"""Operational integration tests run against real, non-owner PostgreSQL roles."""

import base64
import io
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time, timezone, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo
import pytest
from PIL import Image, ImageDraw
from sqlalchemy import text, create_engine
from app.db import tenant_db, one
from app.operations import haversine, local_instant
from app.reporting import period, safe_cell
from conftest import create_tenant, token_for
from test_phase2 import bearer, employee


def post(api, auth, path, body, version=None, key=None):
    headers = {**bearer(auth), "Idempotency-Key": str(key or uuid4())}
    if version is not None:
        headers["If-Match"] = str(version)
    return api.post("/api/v1" + path, json=body, headers=headers)


def fix(lat=11.3, lng=77.7):
    return {
        "client_event_id": str(uuid4()),
        "installation_id": str(uuid4()),
        "lat": lat,
        "lng": lng,
        "accuracy_meters": 5,
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }


def consent(api, auth):
    r = post(api, auth, "/me/location-consent", {"granted": True, "policy_version": "foreground-2026-11"})
    assert r.status_code == 200, r.text


def staff(system, auth, tid, role="ENGINEER", email="engineer@example.com"):
    api = system["api"]
    body = employee(api, auth, email, role)
    r = api.post("/api/v1/users", json=body, headers=bearer(auth))
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    r = api.post(
        "/api/v1/auth/accept-invite",
        json={"token": token_for(system, tid, email), "new_password": "Operations-Test-Password-42"},
    )
    assert r.status_code == 204, r.text
    r = api.post(
        "/api/v1/auth/login",
        json={
            "slug": "alpha-company",
            "email": email,
            "password": "Operations-Test-Password-42",
            "client_type": "native",
        },
    )
    assert r.status_code == 200, r.text
    return uid, r.json()


def ticket_body(assigned=None):
    return {
        "customer_name": "Hardware customer",
        "customer_phone": "9999999999",
        "address": "Erode service site",
        "site_lat": 11.3,
        "site_lng": 77.7,
        "category": "Laptop",
        "serial_number": "SN-42",
        "reported_issue": "Laptop cannot power on",
        "estimated_cost": "500.00",
        "assigned_to": assigned,
    }


def lead_body():
    b = ticket_body()
    return {
        k: v for k, v in b.items() if k in ("customer_name", "customer_phone", "address", "site_lat", "site_lng")
    } | {"requirement": "Install CCTV cameras", "estimated_value": "2000.00"}


def enable_reports(system, tid):
    with system["owner"].begin() as db:
        db.execute(
            text(
                "UPDATE control.tenant_features SET enabled=true WHERE tenant_id=:tid AND feature='monthly_email_reports'"
            ),
            {"tid": tid},
        )


def always_shift(system, tid):
    with system["owner"].begin() as db:
        db.execute(
            text(
                "UPDATE app.shifts SET weekdays=ARRAY[1,2,3,4,5,6,7]::smallint[],start_local='00:00',end_local='23:59',grace_minutes=0 WHERE tenant_id=:tid"
            ),
            {"tid": tid},
        )


def image():
    p = Image.new("RGB", (80, 50), "white")
    ImageDraw.Draw(p).line((5, 5, 60, 40), fill="black", width=3)
    out = io.BytesIO()
    p.save(out, format="PNG")
    return base64.b64encode(out.getvalue()).decode()


def test_attendance_geofence_replay_late_and_checkout(system):
    tid, auth = create_tenant(system)
    api = system["api"]
    always_shift(system, tid)
    consent(api, auth)
    r = post(api, auth, "/attendance/punch-in", {"location": fix(12, 78), "work_mode": "OFFICE"})
    assert r.status_code == 422, r.text
    key = uuid4()
    body = {"location": fix(), "work_mode": "OFFICE"}
    r = post(api, auth, "/attendance/punch-in", body, key=key)
    assert r.status_code == 201, r.text
    row = r.json()
    assert row["arrival_status"] == "LATE"
    replay = post(api, auth, "/attendance/punch-in", body, key=key)
    assert replay.json()["id"] == row["id"]
    assert post(api, auth, "/attendance/punch-in", {"location": fix(), "work_mode": "OFFICE"}).status_code == 409
    assert post(api, auth, f"/attendance/{row['id']}/punch-out", {"location": fix()}, 999).status_code == 409
    out = post(api, auth, f"/attendance/{row['id']}/punch-out", {"location": fix()}, row["version"])
    assert out.status_code == 200, out.text
    assert out.json()["status"] == "COMPLETE"
    assert api.get("/api/v1/travel-summary", headers=bearer(auth)).json()["method"] == "STRAIGHT_LINE"


def test_location_consent_freshness_and_mode_enforced(system):
    tid, auth = create_tenant(system)
    api = system["api"]
    always_shift(system, tid)
    assert post(api, auth, "/attendance/punch-in", {"location": fix(), "work_mode": "OFFICE"}).status_code == 403
    consent(api, auth)
    assert post(api, auth, "/attendance/punch-in", {"location": fix(), "work_mode": "FIELD"}).status_code == 403
    bad = fix()
    bad["captured_at"] = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    assert post(api, auth, "/attendance/punch-in", {"location": bad, "work_mode": "OFFICE"}).status_code == 422
    bad = fix()
    bad["accuracy_meters"] = 100
    assert post(api, auth, "/attendance/punch-in", {"location": bad, "work_mode": "OFFICE"}).status_code == 422


def test_ticket_full_assigned_gps_signature_workflow(system):
    tid, auth = create_tenant(system)
    api = system["api"]
    uid, engineer = staff(system, auth, tid)
    consent(api, engineer)
    r = post(api, auth, "/tickets", ticket_body(uid))
    assert r.status_code == 201, r.text
    row = r.json()
    ticket = row["id"]
    assert (
        post(
            api,
            engineer,
            f"/tickets/{ticket}/transition",
            {"status": "RESOLVED", "note": "cannot skip"},
            row["version"],
        ).status_code
        == 409
    )
    for status in ["EN_ROUTE", "ON_SITE", "IN_PROGRESS", "WAITING_SPARES", "IN_PROGRESS", "RESOLVED"]:
        body = {"status": status, "note": "Replaced adapter and tested"}
        if status == "ON_SITE":
            body["location"] = fix()
        r = post(api, engineer, f"/tickets/{ticket}/transition", body, row["version"])
        assert r.status_code == 200, r.text
        row = r.json()
    evidence = []
    for kind in ["AFTER", "SIGNATURE"]:
        r = post(api, engineer, f"/tickets/{ticket}/evidence", {"kind": kind, "image_base64": image()})
        assert r.status_code == 201, r.text
        evidence.append(r.json()["id"])
    body = {
        "location": fix(),
        "resolution_notes": "Replaced adapter and tested",
        "photo_id": evidence[0],
        "signature_id": evidence[1],
        "signer_name": "Customer Name",
        "customer_consent": True,
        "payment_mode": "UPI",
        "collected_amount": "500.00",
    }
    r = post(api, engineer, f"/tickets/{ticket}/complete", body, row["version"])
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "COMPLETED"
    with tenant_db(tid, "operations") as db:
        assert one(db, "SELECT status FROM app.payments")["status"] == "RECORDED"
    metrics = api.get("/api/v1/dashboard", headers=bearer(auth))
    assert metrics.status_code == 200, metrics.text
    assert metrics.json()["service"]["verified_revenue"] == 0


def test_ticket_foreign_assignment_and_idempotency(system):
    a, aa = create_tenant(system)
    b, bb = create_tenant(system, "beta-company")
    api = system["api"]
    row = post(api, bb, "/tickets", ticket_body()).json()
    assert api.get("/api/v1/tickets/" + row["id"], headers=bearer(aa)).status_code == 404
    assert (
        post(
            api, aa, f"/tickets/{row['id']}/transition", {"status": "EN_ROUTE", "note": "Foreign ticket"}, 1
        ).status_code
        == 404
    )
    assert api.get("/api/v1/tickets", headers=bearer(aa)).json()["data"] == []
    key = uuid4()
    body = ticket_body()
    with ThreadPoolExecutor(max_workers=2) as pool:
        rs = list(pool.map(lambda _: post(api, aa, "/tickets", body, key=key), range(2)))
    assert all(r.status_code == 201 for r in rs), [r.text for r in rs]
    assert rs[0].json()["id"] == rs[1].json()["id"]
    body["reported_issue"] = "Different issue"
    assert post(api, aa, "/tickets", body, key=key).status_code == 409


def test_assignment_rbac_and_foreign_evidence(system):
    tid, auth = create_tenant(system)
    api = system["api"]
    uid, eng = staff(system, auth, tid)
    r = post(api, auth, "/tickets", ticket_body())
    assert r.status_code == 201, r.text
    assert api.get("/api/v1/tickets/" + r.json()["id"], headers=bearer(eng)).status_code == 404
    assert post(api, eng, "/tickets", ticket_body()).status_code == 403
    assert api.get("/api/v1/leads", headers=bearer(eng)).status_code == 403
    assert api.get("/api/v1/dashboard", headers=bearer(eng)).status_code == 403


def test_crm_stage_followup_conversion_concurrent(system):
    tid, auth = create_tenant(system)
    api = system["api"]
    r = post(api, auth, "/leads", lead_body())
    assert r.status_code == 201, r.text
    row = r.json()
    r = post(
        api,
        auth,
        f"/leads/{row['id']}/activities",
        {"note": "Customer requested quote", "next_followup_at": datetime.now(timezone.utc).isoformat()},
        row["version"],
    )
    assert r.status_code == 201, r.text
    row = r.json()
    r = post(
        api,
        auth,
        f"/leads/{row['id']}/stage",
        {"stage": "WON", "reason": "Customer accepted proposal", "won_value": "1800.00"},
        row["version"],
    )
    assert r.status_code == 200, r.text
    row = r.json()

    def convert(_):
        return post(
            api, auth, f"/leads/{row['id']}/convert", {"reported_issue": "Install CCTV hardware"}, row["version"]
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        rs = list(pool.map(convert, range(2)))
    assert all(r.status_code == 201 for r in rs), [r.text for r in rs]
    assert rs[0].json()["id"] == rs[1].json()["id"]
    with tenant_db(tid, "operations") as db:
        assert one(db, "SELECT count(*) AS n FROM app.tickets")["n"] == 1
        history = one(db, "SELECT details FROM app.lead_activities WHERE kind='STAGE'")["details"]
        assert history["won_value"] == "1800.00"


@pytest.mark.parametrize(
    "path,feature", [("/attendance", "attendance_gps"), ("/tickets", "field_service_tickets"), ("/leads", "sales_crm")]
)
def test_module_disabled_and_no_context(system, path, feature):
    tid, auth = create_tenant(system)
    api = system["api"]
    assert api.get("/api/v1" + path).status_code == 401
    with system["owner"].begin() as db:
        db.execute(
            text("UPDATE control.tenant_features SET enabled=false WHERE tenant_id=:tid AND feature=:feature"),
            {"tid": tid, "feature": feature},
        )
    assert api.get("/api/v1" + path, headers=bearer(auth)).status_code == 403


def test_leave_self_review_overlap_and_foreign_id(system):
    tid, auth = create_tenant(system)
    api = system["api"]
    uid, eng = staff(system, auth, tid)
    start = datetime.now(timezone.utc) + timedelta(days=1)
    body = {
        "starts_at": start.isoformat(),
        "ends_at": (start + timedelta(hours=3)).isoformat(),
        "kind": "PERMISSION",
        "reason": "Personal appointment",
    }
    own = post(api, auth, "/leave-requests", body).json()
    assert (
        post(
            api,
            auth,
            f"/leave-requests/{own['id']}/decision",
            {"decision": "APPROVED", "reason": "Approve request"},
            own["version"],
        ).status_code
        == 403
    )
    row = post(api, eng, "/leave-requests", body).json()
    approved = post(
        api,
        auth,
        f"/leave-requests/{row['id']}/decision",
        {"decision": "APPROVED", "reason": "Approve request"},
        row["version"],
    )
    assert approved.status_code == 200, approved.text
    overlap = post(api, eng, "/leave-requests", body).json()
    assert (
        post(
            api,
            auth,
            f"/leave-requests/{overlap['id']}/decision",
            {"decision": "APPROVED", "reason": "Approve overlapping request"},
            overlap["version"],
        ).status_code
        == 409
    )


def test_reports_download_cross_tenant_safe_csv_pdf_and_email(system):
    a, auth = create_tenant(system)
    b, other = create_tenant(system, "beta-company")
    api = system["api"]
    enable_reports(system, a)
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    r = post(api, auth, "/reports", {"month": month})
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    assert api.get(f"/api/v1/reports/{rid}/download", headers=bearer(other)).status_code == 404
    csv = api.get(f"/api/v1/reports/{rid}/download?format=csv", headers=bearer(auth))
    assert csv.status_code == 200, csv.text
    assert "straight_line_km" in csv.text
    pdf = api.get(f"/api/v1/reports/{rid}/download?format=pdf", headers=bearer(auth))
    assert pdf.status_code == 200, pdf.text
    assert pdf.content.startswith(b"%PDF")
    r = post(api, auth, "/reports/test-email", {"month": month})
    assert r.status_code == 202, r.text
    from app.operations_worker import tick_operations

    mail = create_engine(os.environ["MAIL_DATABASE_URL"])
    ops = create_engine(os.environ["OPERATIONS_DATABASE_URL"])
    captured = []
    assert tick_operations(mail, ops, lambda email, report: captured.append((email, report))) == 1
    assert captured[0][0] == "owner@example.com"
    assert captured[0][1]["tenant_id"].__str__() == a
    assert tick_operations(mail, ops, lambda *args: captured.append(args)) == 0
    mail.dispose()
    ops.dispose()


def test_report_worker_failure_backoff_and_disabled_section(system):
    tid, auth = create_tenant(system)
    api = system["api"]
    enable_reports(system, tid)
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    r = post(api, auth, "/reports/test-email", {"month": month})
    assert r.status_code == 202, r.text
    from app.operations_worker import tick_operations

    mail = create_engine(os.environ["MAIL_DATABASE_URL"])
    ops = create_engine(os.environ["OPERATIONS_DATABASE_URL"])

    def fail_send(*args):
        raise RuntimeError("provider unavailable")

    assert tick_operations(mail, ops, fail_send) == 0
    with tenant_db(tid, "operations") as db:
        assert one(db, "SELECT snapshot FROM app.report_runs WHERE kind='TEST'")["snapshot"]["attempts"] == 1
    with system["owner"].begin() as db:
        db.execute(
            text("UPDATE control.tenant_features SET enabled=false WHERE tenant_id=:id AND feature='sales_crm'"),
            {"id": tid},
        )
    assert api.get("/api/v1/reports/" + r.json()["id"] + "/download", headers=bearer(auth)).status_code == 403
    mail.dispose()
    ops.dispose()


def test_deletion_reauthentication_and_session_revocation(system):
    tid, auth = create_tenant(system)
    api = system["api"]
    assert post(api, auth, "/me/deletion-requests", {"password": "wrong"}).status_code == 401
    r = post(api, auth, "/me/deletion-requests", {"password": "Tenant-Test-Password-42"})
    assert r.status_code == 202, r.text
    assert r.json()["status"] == "VERIFIED"
    assert api.get("/api/v1/me", headers=bearer(auth)).status_code == 401


def test_month_dst_and_haversine():
    assert haversine(11.3, 77.7, 11.3, 77.7) == 0
    assert 110000 < haversine(0, 0, 1, 0) < 112000
    start, end = period("2024-02", "Asia/Kolkata")
    assert (end - start).days == 29
    z = ZoneInfo("America/New_York")
    ambiguous = datetime(2026, 11, 1).date()
    assert (local_instant(ambiguous, time(1, 30), z, True) - local_instant(ambiguous, time(1, 30), z)).seconds == 3600
    missing = local_instant(datetime(2026, 3, 8).date(), time(2, 30), z)
    assert missing.astimezone(z).hour == 3
    assert safe_cell('=HYPERLINK("bad")').startswith("'")
    assert safe_cell(" @SUM(1)").startswith("'")
