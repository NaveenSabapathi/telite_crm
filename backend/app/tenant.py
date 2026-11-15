import secrets
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, Request
from .db import one, many, run
from .schemas import Employee, EmployeeUpdate, FEATURES, Reason
from .security import PH, fail, expected_version
from .services import tenant_identity, company_admin, feature, audit, queue_password, USER_FIELDS, rate

router = APIRouter(prefix="/api/v1", tags=["Company administration"])


@router.get("/me")
def me(request: Request, db=Depends(tenant_identity)):
    user = request.state.user
    return {
        "user": {k: user[k] for k in USER_FIELDS.split(",")},
        "tenant": request.state.tenant,
        "features": {
            r["feature"]: r["enabled"] for r in many(db, "SELECT feature,enabled FROM control.tenant_features")
        },
    }


@router.get("/users")
def users(limit: int = 25, offset: int = 0, db=Depends(company_admin)):
    if not 1 <= limit <= 100 or offset < 0:
        fail(422, "INVALID_PAGINATION")
    return {
        "data": many(
            db,
            f"SELECT {USER_FIELDS} FROM app.users ORDER BY display_name,id LIMIT :n OFFSET :offset",
            n=limit,
            offset=offset,
        )
    }


@router.get("/users/{uid}")
def user(uid: UUID, db=Depends(company_admin)):
    row = one(db, f"SELECT {USER_FIELDS} FROM app.users WHERE id=:id", id=uid)
    if not row:
        fail(404, "NOT_FOUND")
    return row


@router.get("/branches")
def branches(db=Depends(company_admin)):
    return {"data": many(db, "SELECT id,name FROM app.branches ORDER BY name")}


@router.get("/shifts")
def shifts(db=Depends(company_admin)):
    return {"data": many(db, "SELECT id,name FROM app.shifts ORDER BY name")}


@router.post("/users", status_code=201)
def add_employee(body: Employee, request: Request, db=Depends(company_admin)):
    run(db, "SELECT control.lock_tenant()")
    for table, identifier in [("branches", body.branch_id), ("shifts", body.shift_id)]:
        if not one(db, f"SELECT id FROM app.{table} WHERE id=:id", id=identifier):
            fail(404, "NOT_FOUND")
    uid = uuid4()
    run(
        db,
        """INSERT INTO app.users(tenant_id,id,email,display_name,role,work_mode,branch_id,shift_id,password_hash)
        VALUES(app.current_tenant(),:id,:email,:display_name,:role,:work_mode,:branch_id,:shift_id,:hash)""",
        **body.model_dump(exclude={"email"}),
        email=str(body.email).lower(),
        id=uid,
        hash=PH.hash(secrets.token_urlsafe(48)),
    )
    queue_password(db, request.state.tenant_id, {"id": uid, "email": str(body.email).lower()}, "INVITE")
    audit(db, request, "EMPLOYEE_INVITED", uid)
    return one(db, f"SELECT {USER_FIELDS} FROM app.users WHERE id=:id", id=uid)


@router.patch("/users/{uid}")
def update_employee(uid: UUID, body: EmployeeUpdate, request: Request, db=Depends(company_admin)):
    run(db, "SELECT control.lock_tenant()")
    user = one(db, "SELECT * FROM app.users WHERE id=:id FOR UPDATE", id=uid)
    if not user:
        fail(404, "NOT_FOUND")
    if user["version"] != expected_version(request):
        fail(409, "VERSION_CONFLICT")
    if user["active"] and user["role"] == "COMPANY_ADMIN" and (not body.active or body.role != "COMPANY_ADMIN"):
        count = one(db, "SELECT count(*) AS n FROM app.users WHERE active AND role='COMPANY_ADMIN'")["n"]
        if count <= 1:
            fail(409, "LAST_ADMIN_PROTECTED")
    run(
        db,
        """UPDATE app.users SET display_name=:display_name,role=:role,active=:active,work_mode=:work_mode,
        token_version=token_version+1 WHERE id=:id""",
        **body.model_dump(exclude={"reason"}),
        id=uid,
    )
    run(db, "UPDATE app.auth_sessions SET revoked_at=now() WHERE user_id=:id", id=uid)
    audit(
        db,
        request,
        "EMPLOYEE_UPDATED",
        uid,
        {
            "reason": body.reason,
            "before": {"role": user["role"], "active": user["active"]},
            "after": {"role": body.role, "active": body.active},
        },
    )
    return one(db, f"SELECT {USER_FIELDS} FROM app.users WHERE id=:id", id=uid)


@router.get("/audit")
def audit_log(db=Depends(company_admin)):
    return {
        "data": many(
            db,
            "SELECT id,actor_id,action,entity_id,occurred_at FROM app.audit_logs ORDER BY occurred_at DESC LIMIT 100",
        )
    }


@router.get("/me/sessions")
def sessions(request: Request, db=Depends(tenant_identity)):
    return {
        "data": many(
            db,
            "SELECT id,created_at,expires_at,last_used_at,client_type FROM app.auth_sessions WHERE user_id=:id AND revoked_at IS NULL",
            id=request.state.user["id"],
        )
    }


@router.delete("/me/sessions/{sid}", status_code=204)
def revoke(sid: UUID, request: Request, db=Depends(tenant_identity)):
    row = one(
        db,
        "SELECT family_id FROM app.auth_sessions WHERE id=:id AND user_id=:uid",
        id=sid,
        uid=request.state.user["id"],
    )
    if not row:
        fail(404, "NOT_FOUND")
    run(db, "UPDATE app.auth_sessions SET revoked_at=now() WHERE family_id=:id", id=row["family_id"])


# Capability metadata reflects implemented modules; optional future modules remain unavailable.
def capability_route(name):
    def eligibility(db=Depends(feature(name))):
        return {
            "feature": name,
            "enabled": True,
            "workflow_available": name
            in ("attendance_gps", "field_service_tickets", "sales_crm", "monthly_email_reports"),
        }

    return eligibility


for name in FEATURES:
    router.add_api_route(f"/capabilities/{name}", capability_route(name), methods=["GET"])


@router.post("/users/{uid}/reissue-invite", status_code=202)
def reissue_invite(uid: UUID, body: Reason, request: Request, db=Depends(company_admin)):
    rate(request, "invite-reissue", str(request.state.user["id"]))
    run(db, "SELECT control.lock_tenant()")
    target = one(db, "SELECT * FROM app.users WHERE id=:id AND active FOR UPDATE", id=uid)
    if not target:
        fail(404, "NOT_FOUND")
    if not target["must_reset_password"] or target["email_verified_at"]:
        fail(409, "NOT_A_PENDING_INVITATION")
    queue_password(db, request.state.tenant_id, target, "INVITE")
    audit(db, request, "INVITATION_REISSUED", uid, {"reason": body.reason})
    return {"message": "A new invitation is queued; previous links are invalid."}
