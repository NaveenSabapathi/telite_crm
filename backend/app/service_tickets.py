"""Assigned service workflow with immutable GPS events and customer signature closure."""

import base64
import hashlib
import io
import json
from datetime import timedelta
from uuid import UUID, uuid4
from PIL import Image, UnidentifiedImageError
from fastapi import APIRouter, Depends, Request, Query
from .schemas import Reason
from .operations_schemas import TicketCreate, Transition, Completion, Evidence, Assignment, PartLog
from .operations import (
    guard,
    DISPATCH,
    SERVICE,
    assigned,
    eligible,
    record,
    public,
    version,
    command,
    location,
    intake,
    notify,
    require_feature,
)
from .db import one, many, run
from .security import now, fail
from .services import audit

router = APIRouter(prefix="/api/v1", tags=["Service tickets"])
service = guard("field_service_tickets", SERVICE)
dispatch = guard("field_service_tickets", DISPATCH)

TICKET_FIELDS = "t.id,t.number,t.version,t.customer_id,t.site_id,t.asset_id,t.assigned_to,t.lead_id,t.reported_issue,t.estimated_cost,t.currency,t.status,t.priority,t.sla_due_at,t.resolution_notes,t.completed_at,t.payment_mode,t.coverage_snapshot,t.created_at"


def ticket_event(db, request, tid, old, new, note, lid=None, details=None):
    run(
        db,
        """INSERT INTO app.ticket_events(tenant_id,ticket_id,actor_id,from_status,to_status,note,location_id,occurred_at,details)
        VALUES(app.current_tenant(),:tid,:actor,:old,:new,:note,:lid,now(),CAST(:details AS jsonb))""",
        tid=tid,
        actor=request.state.user["id"],
        old=old,
        new=new,
        note=note,
        lid=lid,
        details=json.dumps(details or {}),
    )


def new_ticket(
    db, request, customer, site, issue, value, assignee=None, asset=None, lead=None, priority="NORMAL", coverage=None
):
    if assignee:
        eligible(db, assignee, "ENGINEER")
    number = one(
        db,
        """INSERT INTO app.document_sequences(tenant_id,kind,next_value) VALUES(app.current_tenant(),'TICKET',2)
        ON CONFLICT(tenant_id,kind) DO UPDATE SET next_value=document_sequences.next_value+1 RETURNING next_value-1 AS n""",
    )["n"]
    hours = {"URGENT": 4, "HIGH": 8, "NORMAL": 24, "LOW": 72}[priority]
    row = one(
        db,
        """INSERT INTO app.tickets(tenant_id,number,customer_id,site_id,asset_id,lead_id,assigned_to,service_mode,reported_issue,
        physical_condition,coverage_snapshot,estimated_cost,currency,status,priority,sla_due_at,sla_policy_snapshot)
        VALUES(app.current_tenant(),:number,:customer,:site,:asset,:lead,:assigned,'ON_SITE',:issue,'{}',CAST(:coverage AS jsonb),:value,
        (SELECT currency FROM control.operations_settings()),:status,:priority,:due,CAST(:policy AS jsonb)) RETURNING *""",
        number=number,
        customer=customer,
        site=site,
        asset=asset,
        lead=lead,
        assigned=assignee,
        issue=issue,
        value=value,
        status="ASSIGNED" if assignee else "NEW",
        priority=priority,
        due=now() + timedelta(hours=hours),
        coverage=json.dumps(coverage or {"status": "CHARGEABLE"}),
        policy=json.dumps({"hours": hours, "waiting_pauses": False}),
    )
    ticket_event(db, request, row["id"], None, row["status"], "Ticket created")
    notify(db, assignee, "TICKET_ASSIGNED", row["id"], f"assigned:{row['id']}:1")
    audit(db, request, "TICKET_CREATED", row["id"])
    return public(row)


@router.get("/dispatch/employees")
def engineers(db=Depends(dispatch)):
    return {
        "data": many(
            db,
            "SELECT id,display_name,role FROM app.users WHERE tenant_id=app.current_tenant() AND active AND NOT must_reset_password AND role='ENGINEER' ORDER BY display_name LIMIT 100",
        )
    }


@router.get("/tickets")
def tickets(request: Request, limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0), db=Depends(service)):
    return {
        "data": many(
            db,
            f"""SELECT {TICKET_FIELDS},c.name AS customer_name,a.serial_number,a.category FROM app.tickets t
        JOIN app.customers c ON c.tenant_id=t.tenant_id AND c.id=t.customer_id
        LEFT JOIN app.assets a ON a.tenant_id=t.tenant_id AND a.id=t.asset_id
        WHERE t.tenant_id=app.current_tenant() AND (:wide OR t.assigned_to=:uid) ORDER BY t.created_at DESC LIMIT :limit OFFSET :offset""",
            wide=request.state.user["role"] in DISPATCH,
            uid=request.state.user["id"],
            limit=limit,
            offset=offset,
        )
    }


@router.post("/tickets", status_code=201)
def create(body: TicketCreate, request: Request, db=Depends(dispatch)):
    if body.coverage == "AMC":
        require_feature(db, "amc_tracker")

    def action():
        customer, site = intake(db, body)
        asset = uuid4()
        run(
            db,
            """INSERT INTO app.assets(tenant_id,id,customer_id,site_id,category,brand,model,serial_number,warranty_until)
            VALUES(app.current_tenant(),:id,:customer,:site,:category,:brand,:model,:serial_number,:warranty_until)""",
            id=asset,
            customer=customer,
            site=site,
            **body.model_dump(include={"category", "brand", "model", "serial_number", "warranty_until"}),
        )
        return new_ticket(
            db,
            request,
            customer,
            site,
            body.reported_issue,
            body.estimated_cost,
            body.assigned_to,
            asset,
            priority=body.priority,
            coverage={
                "status": body.coverage,
                "warranty_until": str(body.warranty_until) if body.warranty_until else None,
                "source": "ADMIN_DECLARED",
            },
        )

    return command(db, request, body, action)


@router.get("/tickets/{tid}")
def detail(tid: UUID, request: Request, db=Depends(service)):
    row = assigned(db, "tickets", tid, request)
    customer = record(db, "customers", row["customer_id"])
    site = record(db, "sites", row["site_id"])
    return {
        **public(row),
        "customer": {"name": customer["name"], "phone": customer["phone"]},
        "site": public(site),
        "asset": public(record(db, "assets", row["asset_id"])) if row["asset_id"] else None,
        "events": [
            public(r)
            for r in many(
                db,
                "SELECT * FROM app.ticket_events WHERE tenant_id=app.current_tenant() AND ticket_id=:id ORDER BY occurred_at,id",
                id=tid,
            )
        ],
    }


@router.post("/tickets/{tid}/assign")
def assign(tid: UUID, body: Assignment, request: Request, db=Depends(dispatch)):
    row = assigned(db, "tickets", tid, request, True)

    def action():
        version(row, request)
        eligible(db, body.user_id, "ENGINEER")
        if row["status"] not in ("NEW", "ASSIGNED"):
            fail(409, "ACTIVE_JOB_REASSIGNMENT_REQUIRES_REVIEW")
        run(
            db,
            "UPDATE app.tickets SET assigned_to=:uid,status='ASSIGNED' WHERE tenant_id=app.current_tenant() AND id=:id",
            uid=body.user_id,
            id=tid,
        )
        ticket_event(db, request, tid, row["status"], "ASSIGNED", body.reason)
        notify(db, body.user_id, "TICKET_ASSIGNED", tid, f"assigned:{tid}:{row['version'] + 1}")
        return public(record(db, "tickets", tid))

    return command(db, request, body, action)


TRANSITIONS = {
    "ASSIGNED": {"EN_ROUTE"},
    "EN_ROUTE": {"ON_SITE"},
    "ON_SITE": {"IN_PROGRESS"},
    "IN_PROGRESS": {"WAITING_SPARES", "WAITING_APPROVAL", "RESOLVED"},
    "WAITING_SPARES": {"IN_PROGRESS"},
    "WAITING_APPROVAL": {"IN_PROGRESS"},
}


@router.post("/tickets/{tid}/transition")
def transition(tid: UUID, body: Transition, request: Request, db=Depends(service)):
    row = assigned(db, "tickets", tid, request, True)

    def action():
        version(row, request)
        if body.status not in TRANSITIONS.get(row["status"], set()):
            fail(409, "INVALID_TICKET_TRANSITION")
        if row["assigned_to"] != request.state.user["id"]:
            fail(403, "ASSIGNED_ENGINEER_REQUIRED")
        lid = None
        if body.status == "ON_SITE":
            if not body.location:
                fail(422, "ARRIVAL_LOCATION_REQUIRED")
            lid = location(db, request, body.location, "TICKET_ARRIVAL")
        run(
            db,
            "UPDATE app.tickets SET status=:status,resolution_notes=CASE WHEN :status='RESOLVED' THEN :note ELSE resolution_notes END WHERE tenant_id=app.current_tenant() AND id=:id",
            note=body.note,
            status=body.status,
            id=tid,
        )
        ticket_event(db, request, tid, row["status"], body.status, body.note, lid)
        audit(db, request, "TICKET_TRANSITION", tid, {"from": row["status"], "to": body.status})
        return public(record(db, "tickets", tid))

    return command(db, request, body, action)


@router.post("/tickets/{tid}/evidence", status_code=201)
def evidence(tid: UUID, body: Evidence, request: Request, db=Depends(service)):
    row = assigned(db, "tickets", tid, request, True)

    def action():
        if row["status"] != "RESOLVED":
            fail(409, "RESOLVE_BEFORE_CLOSURE_EVIDENCE")
        try:
            data = base64.b64decode(body.image_base64, validate=True)
            with Image.open(io.BytesIO(data)) as picture:
                if picture.format not in ("PNG", "JPEG") or picture.width * picture.height > 4000000:
                    raise ValueError("Invalid image")
                picture.load()
                if picture.mode == "RGBA":
                    background = Image.new("RGB", picture.size, "white")
                    background.paste(picture, mask=picture.getchannel("A"))
                    picture = background
                else:
                    picture = picture.convert("RGB")
                picture.thumbnail((1280, 1280))
                if body.kind == "SIGNATURE" and all(lo == hi for lo, hi in picture.getextrema()):
                    raise ValueError("Empty signature")
                output = io.BytesIO()
                picture.save(output, format="JPEG", quality=80)
                data = output.getvalue()
        except (ValueError, UnidentifiedImageError, OSError, Image.DecompressionBombError):
            fail(422, "INVALID_IMAGE")
        if len(data) > 100000:
            fail(413, "IMAGE_TOO_LARGE")
        run(db, "SELECT control.reserve_evidence(:size)", size=len(data))
        mid = uuid4()
        run(
            db,
            """INSERT INTO app.media(tenant_id,id,uploaded_by,object_key,content_type,bytes,sha256,state,purpose,inline_data)
            VALUES(app.current_tenant(),:id,:uid,:key,'image/jpeg',:size,:hash,'CLEAN',:purpose,:data)""",
            id=mid,
            uid=request.state.user["id"],
            key=f"{request.state.tenant_id}/{tid}/{mid}",
            size=len(data),
            hash=hashlib.sha256(data).hexdigest(),
            purpose=body.kind,
            data=data,
        )
        run(
            db,
            "INSERT INTO app.ticket_media(tenant_id,ticket_id,media_id,kind) VALUES(app.current_tenant(),:tid,:mid,:kind)",
            tid=tid,
            mid=mid,
            kind=body.kind,
        )
        return {"id": mid, "kind": body.kind}

    return command(db, request, body, action)


@router.post("/tickets/{tid}/complete")
def complete(tid: UUID, body: Completion, request: Request, db=Depends(service)):
    row = assigned(db, "tickets", tid, request, True)

    def action():
        version(row, request)
        if row["status"] != "RESOLVED":
            fail(409, "RESOLUTION_REQUIRED")
        if row["assigned_to"] != request.state.user["id"]:
            fail(403, "ASSIGNED_ENGINEER_REQUIRED")
        if body.resolution_notes != row["resolution_notes"]:
            fail(409, "RESOLUTION_CHANGED")
        for mid, kind in ((body.photo_id, "AFTER"), (body.signature_id, "SIGNATURE")):
            if not one(
                db,
                """SELECT m.id FROM app.media m JOIN app.ticket_media tm ON tm.tenant_id=m.tenant_id AND tm.media_id=m.id
                WHERE m.tenant_id=app.current_tenant() AND m.id=:id AND tm.ticket_id=:tid AND tm.kind=:kind AND m.uploaded_by=:uid AND m.state='CLEAN'
                AND m.created_at >= (SELECT max(occurred_at) FROM app.ticket_events WHERE tenant_id=app.current_tenant() AND ticket_id=:tid AND to_status='RESOLVED')""",
                id=mid,
                tid=tid,
                kind=kind,
                uid=request.state.user["id"],
            ):
                fail(422, "INVALID_CLOSURE_EVIDENCE")
        if body.payment_mode in ("WARRANTY", "CREDIT") and body.collected_amount:
            fail(422, "NON_COLLECTION_MODE")
        lid = location(db, request, body.location, "TICKET_COMPLETION")
        run(
            db,
            """INSERT INTO app.customer_acceptances(tenant_id,ticket_id,method,signature_media_id,verified_at,contact_snapshot,resolution_version)
            VALUES(app.current_tenant(),:tid,'SIGNATURE',:signature,now(),:signer,:version)""",
            tid=tid,
            signature=body.signature_id,
            signer=body.signer_name,
            version=row["version"],
        )
        run(
            db,
            """UPDATE app.tickets SET status='COMPLETED',resolution_notes=:notes,completed_at=now(),checkout_location_id=:lid,
            completion_photo_id=:photo,signature_media_id=:signature,customer_accepted_at=now(),payment_mode=:mode
            WHERE tenant_id=app.current_tenant() AND id=:id""",
            id=tid,
            notes=body.resolution_notes,
            lid=lid,
            photo=body.photo_id,
            signature=body.signature_id,
            mode=body.payment_mode,
        )
        if body.collected_amount:
            run(
                db,
                """INSERT INTO app.payments(tenant_id,ticket_id,received_by,amount,currency,mode,reference,received_at,status,client_event_id)
                VALUES(app.current_tenant(),:tid,:uid,:amount,:currency,:mode,:reference,now(),'RECORDED',:event)""",
                tid=tid,
                uid=request.state.user["id"],
                amount=body.collected_amount,
                currency=row["currency"],
                mode=body.payment_mode,
                reference=body.payment_reference,
                event=uuid4(),
            )
        ticket_event(
            db,
            request,
            tid,
            "RESOLVED",
            "COMPLETED",
            body.resolution_notes,
            lid,
            {"acceptance": "SIGNATURE", "resolution_version": row["version"]},
        )
        audit(db, request, "TICKET_COMPLETED", tid)
        return public(record(db, "tickets", tid))

    return command(db, request, body, action)


@router.post("/tickets/{tid}/parts", status_code=201)
def parts(tid: UUID, body: PartLog, request: Request, db=Depends(service)):
    row = assigned(db, "tickets", tid, request, True)

    def action():
        version(row, request)
        if row["status"] not in ("IN_PROGRESS", "WAITING_SPARES"):
            fail(409, "PARTS_NOT_ALLOWED_IN_STATE")
        # External spares cost log is explicitly not an inventory stock movement.
        details = body.model_dump(mode="json")
        details["kind"] = "EXTERNAL_PART_OR_RMA"
        ticket_event(db, request, tid, row["status"], row["status"], body.note, details=details)
        run(db, "UPDATE app.tickets SET updated_at=now() WHERE tenant_id=app.current_tenant() AND id=:id", id=tid)
        audit(db, request, "SERVICE_PART_LOGGED", tid)
        return public(record(db, "tickets", tid))

    return command(db, request, body, action)


@router.get("/tickets/{tid}/payments")
def payments(tid: UUID, request: Request, db=Depends(service)):
    assigned(db, "tickets", tid, request)
    return {
        "data": many(
            db,
            "SELECT id,amount,currency,mode,status,reference,received_at,version FROM app.payments WHERE tenant_id=app.current_tenant() AND ticket_id=:id ORDER BY received_at DESC",
            id=tid,
        )
    }


@router.post("/payments/{pid}/verify")
def verify_payment(
    pid: UUID, body: Reason, request: Request, db=Depends(guard("field_service_tickets", ("COMPANY_ADMIN",)))
):
    row = record(db, "payments", pid, True)

    def action():
        version(row, request)
        if row["status"] != "RECORDED":
            fail(409, "PAYMENT_NOT_PENDING")
        run(
            db,
            "UPDATE app.payments SET status='VERIFIED',verified_at=now() WHERE tenant_id=app.current_tenant() AND id=:id",
            id=pid,
        )
        audit(db, request, "PAYMENT_VERIFIED", pid, {"reason": body.reason})
        return public(record(db, "payments", pid))

    return command(db, request, body, action)
