"""Sales pipeline and atomic, one-ticket-per-lead conversion."""

import json
from uuid import UUID
from fastapi import APIRouter, Depends, Request, Query
from .operations_schemas import LeadCreate, LeadStage, Activity, Assignment, Conversion
from .operations import (
    guard,
    SALES,
    ADMIN,
    assigned,
    eligible,
    record,
    public,
    version,
    command,
    intake,
    location,
    notify,
    require_feature,
)
from .db import one, many, run
from .security import fail
from .services import audit
from .service_tickets import new_ticket

router = APIRouter(prefix="/api/v1", tags=["Sales CRM"])
sales = guard("sales_crm", SALES)


@router.get("/sales/employees")
def reps(db=Depends(guard("sales_crm", ADMIN))):
    return {
        "data": many(
            db,
            "SELECT id,display_name FROM app.users WHERE tenant_id=app.current_tenant() AND active AND NOT must_reset_password AND role='SALES' ORDER BY display_name LIMIT 100",
        )
    }


@router.get("/leads")
def leads(request: Request, limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0), db=Depends(sales)):
    return {
        "data": [
            public(r)
            for r in many(
                db,
                """SELECT l.*,c.name AS customer_name FROM app.leads l JOIN app.customers c ON c.tenant_id=l.tenant_id AND c.id=l.customer_id
        WHERE l.tenant_id=app.current_tenant() AND (:wide OR assigned_to=:uid) ORDER BY l.created_at DESC LIMIT :limit OFFSET :offset""",
                wide=request.state.user["role"] == "COMPANY_ADMIN",
                uid=request.state.user["id"],
                limit=limit,
                offset=offset,
            )
        ]
    }


@router.post("/leads", status_code=201)
def create(body: LeadCreate, request: Request, db=Depends(sales)):
    def action():
        assignee = body.assigned_to or request.state.user["id"]
        if request.state.user["role"] == "SALES" and assignee != request.state.user["id"]:
            fail(403, "ASSIGNMENT_FORBIDDEN")
        if assignee != request.state.user["id"]:
            eligible(db, assignee, "SALES")
        customer, site = intake(db, body)
        row = one(
            db,
            """INSERT INTO app.leads(tenant_id,customer_id,site_id,assigned_to,source,requirement,estimated_value,currency,stage,next_followup_at)
            VALUES(app.current_tenant(),:customer,:site,:assigned,:source,:requirement,:value,(SELECT currency FROM control.operations_settings()),'NEW',:followup) RETURNING *""",
            customer=customer,
            site=site,
            assigned=assignee,
            source=body.source,
            requirement=body.requirement,
            value=body.estimated_value,
            followup=body.next_followup_at,
        )
        notify(db, assignee, "LEAD_ASSIGNED", row["id"], f"lead:{row['id']}")
        audit(db, request, "LEAD_CREATED", row["id"])
        return public(row)

    return command(db, request, body, action)


@router.get("/leads/{lid}")
def detail(lid: UUID, request: Request, db=Depends(sales)):
    row = assigned(db, "leads", lid, request)
    return {
        **public(row),
        "activities": [
            public(r)
            for r in many(
                db,
                "SELECT * FROM app.lead_activities WHERE tenant_id=app.current_tenant() AND lead_id=:id ORDER BY occurred_at,id",
                id=lid,
            )
        ],
    }


@router.post("/leads/{lid}/assign")
def assign(lid: UUID, body: Assignment, request: Request, db=Depends(guard("sales_crm", ADMIN))):
    row = assigned(db, "leads", lid, request, True)

    def action():
        version(row, request)
        eligible(db, body.user_id, "SALES")
        if row["stage"] in ("WON", "LOST"):
            fail(409, "LEAD_CLOSED")
        run(
            db,
            "UPDATE app.leads SET assigned_to=:uid WHERE tenant_id=app.current_tenant() AND id=:id",
            uid=body.user_id,
            id=lid,
        )
        audit(db, request, "LEAD_ASSIGNED", lid, {"reason": body.reason})
        notify(db, body.user_id, "LEAD_ASSIGNED", lid, f"lead:{lid}:{row['version'] + 1}")
        return public(record(db, "leads", lid))

    return command(db, request, body, action)


@router.post("/leads/{lid}/stage")
def stage(lid: UUID, body: LeadStage, request: Request, db=Depends(sales)):
    row = assigned(db, "leads", lid, request, True)

    def action():
        version(row, request)
        steps = ["NEW", "CONTACTED", "SURVEY_DONE", "QUOTE_SENT", "NEGOTIATION", "WON"]
        if row["stage"] in ("WON", "LOST"):
            fail(409, "LEAD_CLOSED")
        if body.stage == row["stage"]:
            fail(409, "ALREADY_IN_STAGE")
        if (
            body.stage != "LOST"
            and request.state.user["role"] != "COMPANY_ADMIN"
            and steps.index(body.stage) != steps.index(row["stage"]) + 1
        ):
            fail(409, "INVALID_LEAD_TRANSITION")
        if body.stage == "WON" and body.won_value is None:
            fail(422, "WON_VALUE_REQUIRED")
        run(
            db,
            """UPDATE app.leads SET stage=:stage,lost_reason=:reason,won_value=:value,
            won_at=CASE WHEN :stage='WON' THEN now() ELSE NULL END WHERE tenant_id=app.current_tenant() AND id=:id""",
            stage=body.stage,
            reason=body.reason if body.stage == "LOST" else None,
            value=body.won_value if body.stage == "WON" else None,
            id=lid,
        )
        snapshot = {
            "schema_version": 1,
            "from": row["stage"],
            "to": body.stage,
            "won_value": str(body.won_value) if body.stage == "WON" else None,
            "currency": row["currency"],
            "owner_at_win": str(row["assigned_to"]),
            "lost_reason": body.reason if body.stage == "LOST" else None,
        }
        run(
            db,
            """INSERT INTO app.lead_activities(tenant_id,lead_id,actor_id,kind,note,occurred_at,details)
            VALUES(app.current_tenant(),:lid,:uid,'STAGE',:note,now(),CAST(:details AS jsonb))""",
            lid=lid,
            uid=request.state.user["id"],
            note=body.reason,
            details=json.dumps(snapshot),
        )
        audit(db, request, "LEAD_STAGE_CHANGED", lid, {"from": row["stage"], "to": body.stage})
        return public(record(db, "leads", lid))

    return command(db, request, body, action)


@router.post("/leads/{lid}/activities", status_code=201)
def activity(lid: UUID, body: Activity, request: Request, db=Depends(sales)):
    row = assigned(db, "leads", lid, request, True)

    def action():
        version(row, request)
        loc = location(db, request, body.location, "LEAD_VISIT") if body.location else None
        run(
            db,
            """INSERT INTO app.lead_activities(tenant_id,lead_id,actor_id,kind,note,location_id,occurred_at)
            VALUES(app.current_tenant(),:lid,:uid,:kind,:note,:loc,now())""",
            lid=lid,
            uid=request.state.user["id"],
            kind="VISIT" if loc else "NOTE",
            note=body.note,
            loc=loc,
        )
        run(
            db,
            "UPDATE app.leads SET next_followup_at=:followup WHERE tenant_id=app.current_tenant() AND id=:id",
            followup=body.next_followup_at,
            id=lid,
        )
        return public(record(db, "leads", lid))

    return command(db, request, body, action)


@router.post("/leads/{lid}/convert", status_code=201)
def convert(lid: UUID, body: Conversion, request: Request, db=Depends(sales)):
    require_feature(db, "field_service_tickets")
    row = assigned(db, "leads", lid, request, True)

    def action():
        existing = one(
            db, "SELECT id,number FROM app.tickets WHERE tenant_id=app.current_tenant() AND lead_id=:id", id=lid
        )
        if existing:
            return dict(existing)
        version(row, request)
        if row["stage"] != "WON":
            fail(409, "WON_LEAD_REQUIRED")
        result = new_ticket(
            db,
            request,
            row["customer_id"],
            row["site_id"],
            body.reported_issue,
            row["won_value"],
            body.assigned_to,
            lead=lid,
        )
        audit(db, request, "LEAD_CONVERTED", lid)
        return {"id": result["id"], "number": result["number"]}

    return command(db, request, body, action)
