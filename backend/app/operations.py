"""Reviewed tenant repositories and transactional command primitives."""

import json
from math import radians, sin, cos, asin, sqrt
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo
from fastapi import Depends, Request
from fastapi.encoders import jsonable_encoder
from .db import tenant_db, one, run
from .security import fail, now, digest, expected_version
from .services import tenant_identity, tenant_active

TABLES = frozenset(
    "branches shifts users devices consents attendance leave_requests customers sites assets tickets ticket_events leads lead_activities media ticket_media customer_acceptances payments report_runs report_preferences deletion_requests notifications".split()
)


def operations_identity(request: Request, identity=Depends(tenant_identity)):
    with tenant_db(request.state.tenant_id, "operations") as db:
        tenant_active(db)
        user = one(
            db,
            "SELECT id,role,active,token_version FROM app.users WHERE tenant_id=app.current_tenant() AND id=:id",
            id=request.state.user["id"],
        )
        if not user or not user["active"] or user["token_version"] != request.state.user["token_version"]:
            fail()
        session = one(
            db,
            "SELECT id FROM app.auth_sessions WHERE tenant_id=app.current_tenant() AND id=:id AND user_id=:uid AND revoked_at IS NULL AND expires_at>now()",
            id=request.state.session_id,
            uid=user["id"],
        )
        if not session:
            fail()
        yield db


def require_feature(db, name):
    row = one(
        db,
        "SELECT enabled FROM control.tenant_features WHERE tenant_id=app.current_tenant() AND feature=:name",
        name=name,
    )
    if not row or not row["enabled"]:
        fail(403, "FEATURE_DISABLED")


def guard(name=None, roles=()):
    def dependency(request: Request, db=Depends(operations_identity)):
        if roles and request.state.user["role"] not in roles:
            fail(403, "ROLE_FORBIDDEN")
        if name:
            require_feature(db, name)
        return db

    return dependency


ADMIN = ("COMPANY_ADMIN",)
DISPATCH = ("COMPANY_ADMIN", "DISPATCHER")
SERVICE = (*DISPATCH, "ENGINEER")
SALES = ("COMPANY_ADMIN", "SALES")


def record(db, table, identifier, lock=False):
    assert table in TABLES
    row = one(
        db,
        f"SELECT * FROM app.{table} WHERE tenant_id=app.current_tenant() AND id=:id" + (" FOR UPDATE" if lock else ""),
        id=identifier,
    )
    if not row:
        fail(404, "NOT_FOUND")
    return row


def version(row, request):
    if row["version"] != expected_version(request):
        fail(409, "VERSION_CONFLICT")


def public(row):
    return {k: v for k, v in row.items() if k not in ("tenant_id", "inline_data", "object_key", "sha256", "otp_hash")}


def assigned(db, table, identifier, request, lock=False):
    row = record(db, table, identifier, lock)
    wide = request.state.user["role"] in (DISPATCH if table == "tickets" else ADMIN)
    if not wide and row["assigned_to"] != request.state.user["id"]:
        fail(404, "NOT_FOUND")
    return row


def eligible(db, uid, role):
    row = one(
        db,
        "SELECT id FROM app.users WHERE tenant_id=app.current_tenant() AND id=:id AND active AND NOT must_reset_password AND role=:role",
        id=uid,
        role=role,
    )
    if not row:
        fail(404, "ASSIGNEE_NOT_FOUND")


def command(db, request, body, action):
    try:
        key = UUID(request.headers.get("idempotency-key", ""))
    except ValueError:
        fail(428, "IDEMPOTENCY_KEY_REQUIRED")
    route = request.url.path
    uid = request.state.user["id"]
    fingerprint = digest(body.model_dump_json())
    run(
        db,
        "SELECT pg_advisory_xact_lock(hashtextextended(:key,0))",
        key=f"{request.state.tenant_id}:{uid}:{route}:{key}",
    )
    previous = one(
        db,
        "SELECT * FROM app.idempotency_keys WHERE tenant_id=app.current_tenant() AND user_id=:uid AND route=:route AND key=:key",
        uid=uid,
        route=route,
        key=key,
    )
    if previous:
        if previous["request_hash"] != fingerprint or previous["expires_at"] <= now():
            fail(409, "IDEMPOTENCY_CONFLICT")
        return previous["response_body"]
    result = jsonable_encoder(action())
    run(
        db,
        """INSERT INTO app.idempotency_keys(tenant_id,user_id,key,route,request_hash,response_status,response_body,expires_at)
        VALUES(app.current_tenant(),:uid,:key,:route,:hash,200,CAST(:result AS jsonb),now()+interval '30 days')""",
        uid=uid,
        key=key,
        route=route,
        hash=fingerprint,
        result=json.dumps(result),
    )
    return result


def haversine(lat1, lng1, lat2, lng2):
    a, b, c, d = map(radians, map(float, (lat1, lng1, lat2, lng2)))
    h = sin((c - a) / 2) ** 2 + cos(a) * cos(c) * sin((d - b) / 2) ** 2
    return 6371000 * 2 * asin(sqrt(min(1, max(0, h))))


def local_instant(day, value, zone, end=False):
    naive = datetime.combine(day, value)
    # Resolve folds explicitly and advance nonexistent wall times to first valid minute.
    for minute in range(181):
        wall = naive + timedelta(minutes=minute)
        candidates = []
        for fold in (0, 1):
            instant = wall.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc)
            if instant.astimezone(zone).replace(tzinfo=None) == wall:
                candidates.append(instant)
        if candidates:
            return (max if end else min)(candidates)
    fail(422, "INVALID_LOCAL_SCHEDULE")


def schedule(db, user, clock=None):
    clock = clock or now()
    branch = record(db, "branches", user["branch_id"])
    shift = record(db, "shifts", user["shift_id"])
    zone = ZoneInfo(branch["timezone"])
    local = clock.astimezone(zone)
    day = local.date()
    if shift["end_day_offset"] and local.timetz().replace(tzinfo=None) < shift["end_local"]:
        day -= timedelta(days=1)
    start = local_instant(day, shift["start_local"], zone)
    end = local_instant(day + timedelta(days=shift["end_day_offset"]), shift["end_local"], zone, True)
    return branch, shift, day, start, end


def location(db, request, fix, purpose, fence=None):
    if abs((now() - fix.captured_at).total_seconds()) > 60 or fix.mock_signal:
        fail(422, "FRESH_ACCURATE_LOCATION_REQUIRED")
    if not one(
        db,
        "SELECT id FROM app.consents WHERE tenant_id=app.current_tenant() AND user_id=:uid AND purpose='FOREGROUND_LOCATION' AND policy_version='foreground-2026-11' AND revoked_at IS NULL",
        uid=request.state.user["id"],
    ):
        fail(403, "LOCATION_CONSENT_REQUIRED")
    if fence and haversine(fix.lat, fix.lng, fence["lat"], fence["lng"]) + fix.accuracy_meters > float(
        fence["radius_m"]
    ):
        fail(422, "OUTSIDE_GEOFENCE")
    uid = request.state.user["id"]
    # Serialize each actor's evidence to keep travel segments sequential.
    run(db, "SELECT pg_advisory_xact_lock(hashtextextended(:key,0))", key=f"location:{request.state.tenant_id}:{uid}")
    device = one(
        db,
        """INSERT INTO app.devices(tenant_id,user_id,installation_id,platform,last_seen_at)
        VALUES(app.current_tenant(),:uid,:installation,:platform,now())
        ON CONFLICT(tenant_id,installation_id) DO UPDATE SET last_seen_at=now()
        WHERE devices.user_id=:uid AND devices.revoked_at IS NULL RETURNING id""",
        uid=uid,
        installation=fix.installation_id,
        platform=fix.platform,
    )
    if not device:
        fail(403, "DEVICE_NOT_OWNED")
    previous = one(
        db,
        """SELECT id,lat,lng,captured_at FROM app.location_events
        WHERE tenant_id=app.current_tenant() AND user_id=:uid AND verification='ACCEPTED' AND redacted_at IS NULL
        ORDER BY received_at DESC,id DESC LIMIT 1""",
        uid=uid,
    )
    lid = uuid4()
    run(
        db,
        """INSERT INTO app.location_events(tenant_id,id,user_id,device_id,client_event_id,lat,lng,accuracy_m,captured_at,purpose,mock_signal,verification)
        VALUES(app.current_tenant(),:id,:uid,:device,:event,:lat,:lng,:accuracy,:captured,:purpose,false,'ACCEPTED')""",
        id=lid,
        uid=uid,
        device=device["id"],
        event=fix.client_event_id,
        lat=fix.lat,
        lng=fix.lng,
        accuracy=fix.accuracy_meters,
        captured=fix.captured_at,
        purpose=purpose,
    )
    zone = ZoneInfo(one(db, "SELECT timezone FROM control.operations_settings()")["timezone"])
    if previous and previous["captured_at"].astimezone(zone).date() == fix.captured_at.astimezone(zone).date():
        distance = haversine(previous["lat"], previous["lng"], fix.lat, fix.lng) / 1000
        elapsed = (fix.captured_at - previous["captured_at"]).total_seconds()
        if elapsed < 0 or (distance > 1 and distance / max(elapsed / 3600, 0.0001) > 200):
            fail(422, "LOCATION_SEQUENCE_REQUIRES_REVIEW")
        run(
            db,
            """INSERT INTO app.travel_segments(tenant_id,user_id,from_location_id,to_location_id,distance_km,method)
            VALUES(app.current_tenant(),:uid,:a,:b,:km,'STRAIGHT_LINE')""",
            uid=uid,
            a=previous["id"],
            b=lid,
            km=distance,
        )
    return lid


def notify(db, uid, kind, entity, key):
    if uid:
        run(
            db,
            """INSERT INTO app.notifications(tenant_id,user_id,kind,title,body,entity_id,dedupe_key)
            VALUES(app.current_tenant(),:uid,:kind,:title,'Open your workspace for details.',:entity,:key)
            ON CONFLICT(tenant_id,user_id,dedupe_key) DO NOTHING""",
            uid=uid,
            kind=kind,
            title=kind.replace("_", " ").title(),
            entity=entity,
            key=key,
        )


def intake(db, body):
    customer, site = uuid4(), uuid4()
    run(
        db,
        """INSERT INTO app.customers(tenant_id,id,name,phone,billing_address) VALUES(app.current_tenant(),:id,:name,:phone,:address)""",
        id=customer,
        name=body.customer_name,
        phone=body.customer_phone,
        address=body.address,
    )
    run(
        db,
        """INSERT INTO app.sites(tenant_id,id,customer_id,name,address,lat,lng,coordinates_verified)
        VALUES(app.current_tenant(),:id,:customer,'Service site',:address,:lat,:lng,false)""",
        id=site,
        customer=customer,
        address=body.address,
        lat=body.site_lat,
        lng=body.site_lng,
    )
    return customer, site
