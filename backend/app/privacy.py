from fastapi import APIRouter, Depends, Request
from .operations import guard, command
from .operations_schemas import Consent, Deletion
from .schemas import Strict
from .db import run, one, many
from .security import fail, password_ok
from .services import audit, rate

router = APIRouter(prefix="/api/v1", tags=["Privacy and notifications"])
identity = guard()


@router.post("/me/location-consent")
def consent(body: Consent, request: Request, db=Depends(identity)):
    def action():
        run(
            db,
            "UPDATE app.consents SET revoked_at=now() WHERE tenant_id=app.current_tenant() AND user_id=:uid AND purpose='FOREGROUND_LOCATION' AND revoked_at IS NULL",
            uid=request.state.user["id"],
        )
        if body.granted:
            run(
                db,
                "INSERT INTO app.consents(tenant_id,user_id,purpose,policy_version,granted_at) VALUES(app.current_tenant(),:uid,'FOREGROUND_LOCATION',:policy,now())",
                uid=request.state.user["id"],
                policy=body.policy_version,
            )
        return {"granted": body.granted}

    return command(db, request, body, action)


@router.post("/me/deletion-requests", status_code=202)
def deletion(body: Deletion, request: Request, db=Depends(identity)):
    rate(request, "deletion", str(request.state.user["id"]))
    if not password_ok(body.password, request.state.user["password_hash"]):
        fail()

    def action():
        old = one(
            db,
            "SELECT id,status,due_at FROM app.deletion_requests WHERE tenant_id=app.current_tenant() AND user_id=:uid AND status IN ('RECEIVED','VERIFIED','PROCESSING')",
            uid=request.state.user["id"],
        )
        if old:
            return dict(old)
        result = one(
            db,
            """INSERT INTO app.deletion_requests(tenant_id,user_id,requested_at,due_at,status,retention_explanation)
            VALUES(app.current_tenant(),:uid,now(),now()+interval '30 days','VERIFIED','Company records may require retention; personal data and account ownership require administrator review. This is a request, not completed erasure.') RETURNING id,status,due_at,retention_explanation""",
            uid=request.state.user["id"],
        )
        run(
            db,
            "UPDATE app.auth_sessions SET revoked_at=now() WHERE tenant_id=app.current_tenant() AND user_id=:uid",
            uid=request.state.user["id"],
        )
        audit(db, request, "DELETION_REQUESTED", result["id"])
        return dict(result)

    # Never persist a deterministic digest of the reauthentication password.
    return command(db, request, Strict(), action)


@router.get("/me/deletion-requests")
def requests(request: Request, db=Depends(identity)):
    return {
        "data": many(
            db,
            "SELECT id,status,due_at,retention_explanation FROM app.deletion_requests WHERE tenant_id=app.current_tenant() AND user_id=:uid ORDER BY requested_at DESC",
            uid=request.state.user["id"],
        )
    }


@router.get("/notifications")
def notifications(request: Request, db=Depends(identity)):
    # Hide alerts whose module was disabled after delivery.
    return {
        "data": many(
            db,
            """SELECT n.id,n.kind,n.title,n.body,n.created_at,n.read_at FROM app.notifications n
        WHERE n.tenant_id=app.current_tenant() AND n.user_id=:uid AND EXISTS(
          SELECT 1 FROM control.tenant_features f WHERE f.tenant_id=n.tenant_id AND f.enabled AND f.feature=
          CASE WHEN n.kind LIKE 'LEAD%' THEN 'sales_crm' WHEN n.kind LIKE 'TICKET%' THEN 'field_service_tickets' ELSE 'attendance_gps' END)
        ORDER BY n.created_at DESC LIMIT 100""",
            uid=request.state.user["id"],
        )
    }
