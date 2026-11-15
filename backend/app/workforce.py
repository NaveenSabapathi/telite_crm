"""Workforce configuration and GPS attendance commands."""

import json
from datetime import timedelta
from uuid import UUID
from fastapi import APIRouter, Depends, Request, Query
from .schemas import Branch, Shift
from .operations_schemas import Punch, Checkout, Leave, Decision, EmployeeSchedule
from .operations import guard, ADMIN, record, version, public, command, schedule, location, notify
from .db import one, many, run
from .security import now, fail
from .services import audit

router = APIRouter(prefix="/api/v1", tags=["Workforce"])
admin = guard(roles=ADMIN)
attendance = guard("attendance_gps")


@router.get("/workforce/settings")
def settings(db=Depends(admin)):
    return {
        name: [
            public(r)
            for r in many(db, f"SELECT * FROM app.{name} WHERE tenant_id=app.current_tenant() ORDER BY name LIMIT 100")
        ]
        for name in ("branches", "shifts")
    }


@router.post("/branches", status_code=201)
def create_branch(body: Branch, request: Request, db=Depends(admin)):
    def action():
        zone = one(db, "SELECT timezone FROM control.operations_settings()")["timezone"]
        row = one(
            db,
            """INSERT INTO app.branches(tenant_id,name,address,lat,lng,radius_m,timezone)
            VALUES(app.current_tenant(),:name,:address,:lat,:lng,:radius_m,:zone) RETURNING *""",
            **body.model_dump(),
            zone=zone,
        )
        audit(db, request, "BRANCH_CREATED", row["id"])
        return public(row)

    return command(db, request, body, action)


@router.patch("/branches/{bid}")
def edit_branch(bid: UUID, body: Branch, request: Request, db=Depends(admin)):
    row = record(db, "branches", bid, True)
    version(row, request)
    run(
        db,
        """UPDATE app.branches SET name=:name,address=:address,lat=:lat,lng=:lng,radius_m=:radius_m
        WHERE tenant_id=app.current_tenant() AND id=:id""",
        id=bid,
        **body.model_dump(),
    )
    audit(db, request, "GEOFENCE_UPDATED", bid)
    return public(record(db, "branches", bid))


@router.post("/shifts", status_code=201)
def create_shift(body: Shift, request: Request, db=Depends(admin)):
    def action():
        row = one(
            db,
            """INSERT INTO app.shifts(tenant_id,name,start_local,end_local,end_day_offset,grace_minutes,weekdays)
            VALUES(app.current_tenant(),:name,:start_local,:end_local,:end_day_offset,:grace_minutes,:weekdays) RETURNING *""",
            **body.model_dump(),
        )
        audit(db, request, "SHIFT_CREATED", row["id"])
        return public(row)

    return command(db, request, body, action)


@router.patch("/shifts/{sid}")
def edit_shift(sid: UUID, body: Shift, request: Request, db=Depends(admin)):
    row = record(db, "shifts", sid, True)
    version(row, request)
    run(
        db,
        """UPDATE app.shifts SET name=:name,start_local=:start_local,end_local=:end_local,
        end_day_offset=:end_day_offset,grace_minutes=:grace_minutes,weekdays=:weekdays WHERE tenant_id=app.current_tenant() AND id=:id""",
        id=sid,
        **body.model_dump(),
    )
    audit(db, request, "SHIFT_UPDATED", sid)
    return public(record(db, "shifts", sid))


@router.patch("/users/{uid}/schedule")
def employee_schedule(uid: UUID, body: EmployeeSchedule, request: Request, db=Depends(admin)):
    row = record(db, "users", uid, True)
    version(row, request)
    record(db, "branches", body.branch_id)
    record(db, "shifts", body.shift_id)
    run(
        db,
        "UPDATE app.users SET branch_id=:branch_id,shift_id=:shift_id WHERE tenant_id=app.current_tenant() AND id=:id",
        id=uid,
        **body.model_dump(exclude={"reason"}),
    )
    audit(db, request, "EMPLOYEE_SCHEDULE_UPDATED", uid, {"reason": body.reason})
    return {"id": uid, "version": row["version"] + 1}


@router.get("/attendance")
def listing(
    request: Request, limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0), db=Depends(attendance)
):
    return {
        "data": [
            public(r)
            for r in many(
                db,
                """SELECT a.*,u.display_name FROM app.attendance a JOIN app.users u ON u.tenant_id=a.tenant_id AND u.id=a.user_id
        WHERE a.tenant_id=app.current_tenant() AND (:admin OR a.user_id=:uid) ORDER BY a.punch_in DESC LIMIT :limit OFFSET :offset""",
                admin=request.state.user["role"] == "COMPANY_ADMIN",
                uid=request.state.user["id"],
                limit=limit,
                offset=offset,
            )
        ]
    }


@router.get("/attendance/status")
def status(request: Request, db=Depends(attendance)):
    branch, shift, day, start, end = schedule(db, request.state.user)
    current = one(
        db,
        "SELECT * FROM app.attendance WHERE tenant_id=app.current_tenant() AND user_id=:uid AND punch_out IS NULL",
        uid=request.state.user["id"],
    )
    return {
        "open": public(current) if current else None,
        "shift_date": day,
        "scheduled_start": start,
        "scheduled_end": end,
        "grace_minutes": shift["grace_minutes"],
        "work_mode": request.state.user["work_mode"],
        "branch": branch["name"],
    }


@router.post("/attendance/punch-in", status_code=201)
def punch_in(body: Punch, request: Request, db=Depends(attendance)):
    def action():
        user = record(db, "users", request.state.user["id"], True)
        if body.work_mode != user["work_mode"]:
            fail(403, "WORK_MODE_NOT_AUTHORIZED")
        branch, shift, day, start, end = schedule(db, user)
        if day.isoweekday() not in shift["weekdays"] or one(
            db,
            "SELECT id FROM app.holidays WHERE tenant_id=app.current_tenant() AND branch_id=:bid AND holiday_date=:day",
            bid=user["branch_id"],
            day=day,
        ):
            fail(409, "NOT_SCHEDULED_WORKDAY")
        if now() >= end + timedelta(minutes=30) or now() < start - timedelta(hours=4):
            fail(409, "OUTSIDE_SHIFT_WINDOW")
        if one(
            db,
            "SELECT id FROM app.leave_requests WHERE tenant_id=app.current_tenant() AND user_id=:uid AND status='APPROVED' AND starts_at<:end AND ends_at>:start",
            uid=user["id"],
            start=start,
            end=end,
        ):
            fail(409, "APPROVED_LEAVE_CONFLICT")
        lid = location(db, request, body.location, "PUNCH_IN", branch if body.work_mode == "OFFICE" else None)
        late = (
            max(0, int((now() - start).total_seconds() // 60))
            if now() > start + timedelta(minutes=shift["grace_minutes"])
            else 0
        )
        row = one(
            db,
            """INSERT INTO app.attendance(tenant_id,user_id,shift_id,shift_date,scheduled_start,scheduled_end,grace_minutes,work_mode,punch_in,in_location_id,status,late_minutes,branch_snapshot,break_minutes)
            VALUES(app.current_tenant(),:uid,:sid,:day,:start,:end,:grace,:mode,now(),:lid,'OPEN',:late,CAST(:branch AS jsonb),:breaks) RETURNING *""",
            uid=user["id"],
            sid=shift["id"],
            day=day,
            start=start,
            end=end,
            grace=shift["grace_minutes"],
            mode=body.work_mode,
            lid=lid,
            late=late,
            branch=json.dumps({k: float(branch[k]) for k in ("lat", "lng", "radius_m")}),
            breaks=shift["break_minutes"],
        )
        audit(db, request, "ATTENDANCE_PUNCH_IN", row["id"])
        return {**public(row), "arrival_status": "LATE" if late else "ON_TIME"}

    return command(db, request, body, action)


@router.post("/attendance/{aid}/punch-out")
def punch_out(aid: UUID, body: Checkout, request: Request, db=Depends(attendance)):
    row = record(db, "attendance", aid, True)
    if row["user_id"] != request.state.user["id"]:
        fail(404, "NOT_FOUND")

    def action():
        version(row, request)
        if row["punch_out"]:
            fail(409, "ALREADY_PUNCHED_OUT")
        if now() > row["scheduled_end"] + timedelta(hours=12):
            fail(409, "ATTENDANCE_REVIEW_REQUIRED")
        lid = location(
            db, request, body.location, "PUNCH_OUT", row["branch_snapshot"] if row["work_mode"] == "OFFICE" else None
        )
        run(
            db,
            "UPDATE app.attendance SET punch_out=now(),out_location_id=:lid,status='COMPLETE' WHERE tenant_id=app.current_tenant() AND id=:id",
            lid=lid,
            id=aid,
        )
        audit(db, request, "ATTENDANCE_PUNCH_OUT", aid)
        return public(record(db, "attendance", aid))

    return command(db, request, body, action)


@router.get("/leave-requests")
def leaves(request: Request, db=Depends(attendance)):
    return {
        "data": [
            public(r)
            for r in many(
                db,
                """SELECT l.*,u.display_name FROM app.leave_requests l JOIN app.users u ON u.tenant_id=l.tenant_id AND u.id=l.user_id
        WHERE l.tenant_id=app.current_tenant() AND (:admin OR l.user_id=:uid) ORDER BY l.created_at DESC LIMIT 100""",
                admin=request.state.user["role"] == "COMPANY_ADMIN",
                uid=request.state.user["id"],
            )
        ]
    }


@router.post("/leave-requests", status_code=201)
def leave(body: Leave, request: Request, db=Depends(attendance)):
    def action():
        row = one(
            db,
            """INSERT INTO app.leave_requests(tenant_id,user_id,starts_at,ends_at,kind,reason,status)
            VALUES(app.current_tenant(),:uid,:starts_at,:ends_at,:kind,:reason,'PENDING') RETURNING *""",
            uid=request.state.user["id"],
            **body.model_dump(),
        )
        audit(db, request, "LEAVE_REQUESTED", row["id"])
        return public(row)

    return command(db, request, body, action)


@router.post("/leave-requests/{lid}/decision")
def decision(lid: UUID, body: Decision, request: Request, db=Depends(guard("attendance_gps", ADMIN))):
    row = record(db, "leave_requests", lid, True)
    if row["user_id"] == request.state.user["id"]:
        fail(403, "SELF_APPROVAL_FORBIDDEN")

    def action():
        version(row, request)
        if row["status"] != "PENDING":
            fail(409, "ALREADY_REVIEWED")
        record(db, "users", row["user_id"], True)
        if body.decision == "APPROVED":
            if one(
                db,
                "SELECT id FROM app.leave_requests WHERE tenant_id=app.current_tenant() AND user_id=:uid AND status='APPROVED' AND starts_at<:end AND ends_at>:start",
                uid=row["user_id"],
                start=row["starts_at"],
                end=row["ends_at"],
            ) or one(
                db,
                "SELECT id FROM app.attendance WHERE tenant_id=app.current_tenant() AND user_id=:uid AND punch_in<:end AND COALESCE(punch_out,scheduled_end)>:start",
                uid=row["user_id"],
                start=row["starts_at"],
                end=row["ends_at"],
            ):
                fail(409, "OVERLAPPING_ATTENDANCE_OR_LEAVE")
        run(
            db,
            "UPDATE app.leave_requests SET status=:status,reviewed_by=:uid,reviewed_at=now() WHERE tenant_id=app.current_tenant() AND id=:id",
            status=body.decision,
            uid=request.state.user["id"],
            id=lid,
        )
        audit(db, request, "LEAVE_DECIDED", lid, {"reason": body.reason, "status": body.decision})
        notify(db, row["user_id"], "LEAVE_" + body.decision, lid, f"leave:{lid}")
        return public(record(db, "leave_requests", lid))

    return command(db, request, body, action)


@router.get("/travel-summary")
def travel(request: Request, db=Depends(attendance)):
    return {
        "method": "STRAIGHT_LINE",
        "allowance_approved": False,
        "data": many(
            db,
            """SELECT user_id,sum(distance_km) AS distance_km FROM app.travel_segments
        WHERE tenant_id=app.current_tenant() AND (:admin OR user_id=:uid) AND created_at>=now()-interval '31 days'
        GROUP BY user_id""",
            admin=request.state.user["role"] == "COMPANY_ADMIN",
            uid=request.state.user["id"],
        ),
    }
