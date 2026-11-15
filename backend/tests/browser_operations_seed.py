"""Seed only the disposable telite_test database through authenticated application flows."""

import json
from conftest import system, create_tenant
from test_phase3_4 import staff, always_shift, ticket_body, post, enable_reports

fixture = system.__wrapped__()
s = next(fixture)
try:
    tid, admin = create_tenant(s)
    uid, engineer = staff(s, admin, tid)
    sid, sales = staff(s, admin, tid, "SALES", "sales@example.com")
    always_shift(s, tid)
    enable_reports(s, tid)
    ticket = post(s["api"], admin, "/tickets", ticket_body(uid))
    assert ticket.status_code == 201, ticket.text
    print(json.dumps({"tenant": tid, "engineer": uid, "ticket": ticket.json()["id"]}))
finally:
    try:
        next(fixture)
    except StopIteration:
        pass
