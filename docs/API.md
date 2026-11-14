# REST API contract — v1

Design contract for implementation; no endpoints are deployed yet. Base `/api/v1`. JSON UTF-8, UUID resource IDs, ISO-8601 UTC timestamps; local business dates `YYYY-MM-DD`. Monetary values are decimal strings. Tenant derived from authenticated context, never from a business payload. The tables below define endpoint families and their permissions. Phase 2 will produce machine-validated OpenAPI directly from implemented request/response schemas.

## Transport, authorization and common contracts

Native/API requests use `Authorization: Bearer <access_token>`. Browser holds access token in memory; refresh/logout additionally use HttpOnly refresh cookie with `X-CSRF-Token` and checked Origin. Control-plane tokens use a distinct audience. HTTPS mandatory; CORS permits only configured web/native origins. Never include bearer tokens in URLs or SSE query strings.

Write headers: `Idempotency-Key: <UUID>` on all POST business commands; `If-Match: "<version>"` on updates/transitions/deletes. Missing required precondition → 428. Successful resource response includes `ETag: "<version>"`. Server locks and compares version atomically; mismatch →409 with latest version accessible only after authorization. Retry of identical completed idempotency key returns the recorded result before evaluating old version. Same key with changed body →409. Replay retains original authorization checks; revoked users cannot retrieve old results. Responses carrying PII: `Cache-Control: no-store`.

List query: `limit` 1–100 (default 25), opaque signed `cursor`, allowlisted `sort`, `q` ≤200 chars and documented filters; no arbitrary SQL fields. Cursor binds tenant, scope and filter hash; mismatched cursors rejected. Range queries use `[from,to)` and maximum 366 days for reports. Bulk operations ≤100 IDs, each independently scoped and version checked; `results` returns per-item outcome. No cross-tenant total counts. Server-generated identifiers/numbers, versions, status timestamps, audit actor and tenant cannot be mass-assigned.

```json
{"data":{"id":"c90a2f20-70c8-4a85-a314-d3f42d35ea9b","version":2},"request_id":"0ba8a4ba-bb86-4377-9d56-4b229c56ca89"}
```

List response: `{ "data": [...], "next_cursor": null, "request_id": "uuid" }`.
Error: `{ "error": { "code": "SITE_VERIFICATION_REQUIRED", "message": "Capture a fresh location or request review.", "fields": {} }, "request_id": "uuid" }`. Statuses: 400 malformed, 401 unauthenticated, 403 role/flag/tenant inactive, 404 inaccessible or absent object, 409 version/state/idempotency/stock conflict, 413 upload too large, 422 semantic validation, 428 missing version, 429 rate limit (`Retry-After`), 503 unavailable dependency. Foreign tenant IDs must yield indistinguishable 404, not names/SQL errors.

Roles below: A company admin; D dispatcher; E engineer; S sales; P platform admin; U any active tenant user. `own`, `assigned`, `queue` qualifiers are enforced on every read and write. Every feature-guarded family also checks tenant activity/expiry.

## Authentication and platform administration

| Method/path | Access | Payload / result |
|---|---|---|
| POST `/auth/login` | Public rate-limited | slug, email, password, client_type web/native, installation_id; access token + user/capabilities; refresh cookie on web or secure-storage token on native |
| POST `/auth/refresh` | Refresh credential | Rotates refresh family, returns short-lived access; reuse revokes family |
| POST `/auth/logout` | Session + CSRF on web | Revoke current session/device binding, 204 |
| POST `/auth/forgot-password` | Public rate-limited | slug,email; always generic 202 |
| POST `/auth/reset-password` | One-use reset | token,new_password; revoke existing sessions, 204 |
| POST `/auth/accept-invite` | One-use invite | token,new_password; activates invited identity within cap, 201 |
| GET `/me` | U | Identity, role, flags, limits, policy versions; no secrets |
| GET `/me/sessions` | U own | Devices and session last-used metadata |
| DELETE `/me/sessions/{id}` | U own | Revoke, 204 |
| POST `/platform/auth/login` | P credentials + MFA | Separate platform session/audience, 200 |
| POST `/platform/auth/logout` | P | Revoke, 204 |
| GET/POST `/platform/tenants` | P | List metadata / create tenant with first branch, shift, admin invite; 201 |
| GET/PATCH `/platform/tenants/{id}` | P | Plan limits, validity,status,timezone; expected version + reason |
| PUT `/platform/tenants/{id}/features` | P | Full named feature map + reason; validate dependencies |
| POST `/platform/tenants/{id}/reset-admin` | P | admin_user_id,reason; enqueue reset link to verified address, 202 |
| GET `/platform/audit` | P | actor,target tenant,date filters; metadata only |
| GET `/platform/health` | P | Dependency, queue, backup/storage metrics; no raw tenant records |

Platform password recovery/MFA recovery is an audited operator procedure requiring identity verification, not a public unauthenticated reset bypass. Provision example:

```json
{"name":"Breeze Computers","slug":"breeze-erode","timezone":"Asia/Kolkata","currency":"INR","max_active_employees":25,"storage_quota_bytes":10737418240,"valid_until":"2027-11-14T18:30:00Z","branch":{"name":"Erode","address":"Configured office address","lat":11.341000,"lng":77.717000,"radius_m":150},"shift":{"name":"Day","start_local":"09:30:00","end_local":"18:30:00","end_day_offset":0,"grace_minutes":15,"weekdays":[1,2,3,4,5,6]},"admin":{"email":"owner@example.com","display_name":"Company owner"},"features":{"attendance_gps":true,"field_service_tickets":true,"sales_crm":true,"amc_tracker":true,"monthly_email_reports":true,"background_location":false}}
```

Coordinates are illustrative and must be verified at setup. Public `example.com` addresses in examples are not actual recipients.

## Workforce and location — feature `attendance_gps`

| Method/path | Access | Payload / result |
|---|---|---|
| GET/POST `/users` | A | Paginated employee list / invite: email,display_name,phone,role,branch_id,shift_id,work_mode |
| GET/PATCH `/users/{id}` | A; U own read with reduced fields | Update allowed profile/role/active; recheck last admin/cap and revoke sessions |
| GET/POST/PATCH `/branches[/{id}]` | A | Name,address,coordinates,radius,timezone; audit geofence change |
| GET/POST/PATCH `/shifts[/{id}]` | A | Local times,end_day_offset,weekdays ISO 1–7,grace,break; effective dates |
| POST `/users/{id}/shift-assignments` | A | shift_id,effective_from,effective_to; no overlapping intervals |
| GET/POST/DELETE `/holidays[/{id}]` | A | branch_id,date,name; explicit effective calendar |
| GET `/attendance` | A all; U own | date,user,status filters; nonadmin user filter cannot broaden |
| POST `/attendance/punch-in` | U own | location,device_id,optional selfie_media_id; 201 accepted or 202 review |
| POST `/attendance/{id}/punch-out` | U own | location,device_id; attendance version; 200 or review |
| POST `/attendance/{id}/corrections` | U own or A | proposed values,reason; 202 pending |
| POST `/attendance/corrections/{id}/decision` | A not requester | APPROVE/REJECT,reason; audit original and corrected values |
| GET/POST `/leave-requests` | A all; U own | kind,starts_at,ends_at,reason; 201 |
| POST `/leave-requests/{id}/decision` | A not requester | APPROVE/REJECT,reason; version checked |
| POST `/leave-requests/{id}/cancel` | U own pending; A approved | reason; audit |
| POST `/travel-sessions` | E/S own + background flag/consent | consent_id,initial location; starts only while punched in |
| POST `/travel-sessions/{id}/locations` | Owner active session | Bounded array ≤100 fixes with event IDs, max 7 days old → review if delayed |
| POST `/travel-sessions/{id}/stop` | Owner/A | End time accepted by server; stop native collection immediately |
| GET `/travel-summary` | A all; U own | period,method,approved distance/rate; never blend estimate and actual |
| POST `/travel-segments/{id}/approve` | A not owner | approved distance/rate,reason; audit |
| GET `/staff-map` | A | Latest authorized location per active employee with captured_at,accuracy,source,stale flag |

User/branch/shift configuration remains available to A even when attendance feature is off; GPS/attendance data endpoints require the flag. Location payload shared by attendance, ticket and sales visit commands:

```json
{"device_id":"4ead36fa-79ee-4526-95b4-9c0d7e24d96c","location":{"client_event_id":"f7952f46-875a-4c78-a5d8-cbe078ee2876","lat":11.341000,"lng":77.717000,"accuracy_m":12.5,"captured_at":"2026-11-14T03:59:45Z","mock_signal":false},"selfie_media_id":null}
```

Validate ranges, finite numeric values, freshness, device ownership and risk signals. Address/verification are server-only. Manual exceptions never set verification=ACCEPTED automatically.

## Customers, service and inventory — feature `field_service_tickets`

| Method/path | Access | Payload / result |
|---|---|---|
| GET/POST `/customers` | A/D; S scoped CRM | Name,contact,company,GSTIN,address; duplicate warning (phone not globally unique) |
| GET/PATCH `/customers/{id}` | A/D; E assigned read; S scoped | Restricted contact fields only; cross-record permission checks |
| GET/POST/PATCH `/customers/{id}/sites[/{site_id}]` | A/D; S scoped survey | Address,coordinates,radius; coordinate verification requires A/D |
| GET/POST/PATCH `/customers/{id}/assets[/{asset_id}]` | A/D; E assigned read | Category,brand,model,serial,warranty,purchase,site |
| GET `/assets/{id}/history` | A/D; E assigned current asset | Scoped ticket/RMA/AMC history |
| GET/POST `/tickets` | A/D; E assigned GET | Intake fields,customer/site/asset,mode,condition,issue,estimate,priority; 201 |
| GET/PATCH `/tickets/{id}` | A/D; E assigned restricted | Metadata edits only; status via command; E diagnostics through events |
| POST `/tickets/{id}/assign` | A/D | engineer_id,reason; active-role eligibility checked |
| POST `/tickets/bulk-assign` | A/D | [{id,version}],engineer_id; per-record result |
| POST `/tickets/{id}/transition` | A/D dispatch actions; E assigned work | target status,note,location when required; state-machine checks |
| POST `/tickets/{id}/completion-otp` | E assigned/A/D | No arbitrary phone override; use verified customer contact; 202 |
| POST `/tickets/{id}/acceptance` | E assigned/A/D | method OTP+code or SIGNATURE+clean media, signer name/consent; proof ID |
| POST `/tickets/{id}/complete` | E assigned/A/D | notes,photo_id,acceptance_id,location,mode; 200 only when all valid |
| POST `/tickets/{id}/reopen` | A/D | reason; new cycle, preserve history |
| POST `/tickets/{id}/cancel` | A/D | reason; release reservations, disallow finalized money mismatch |
| GET/POST `/tickets/{id}/notes` | A/D/E assigned | append diagnostic note; cannot rewrite author/history |
| GET `/tickets/{id}/events` | Ticket readers | Ordered transition/assignment/diagnostic timeline |
| GET/POST `/inventory/parts` | A/D; E assigned part search | sku,name,unit,cost,price,reorder; 201 for A/D |
| PATCH `/inventory/parts/{id}` | A/D | Metadata; quantities must use ledger commands |
| POST `/inventory/receipts` | A/D | part_id,quantity,cost,reference; locked atomic ledger |
| POST `/tickets/{id}/parts/reserve` | A/D | part_id,quantity; 201 or insufficient-stock 409 |
| POST `/tickets/{id}/parts/consume` | A/D/E assigned | part_id,quantity,reservation_id(optional); ledger + stock atomic |
| POST `/tickets/{id}/parts/return` | A/D/E assigned | movement_id,quantity,reason; cannot exceed consumed amount |
| GET/POST/PATCH `/vendors[/{id}]` | A/D | Name,contact,address |
| GET/POST/PATCH `/rma-cases[/{id}]` | A/D; E assigned read | ticket,asset,vendor,reference,sent/expected/received dates,replacement serial,status |
| GET/POST `/tickets/{id}/payments` | A/D/E assigned | amount,currency,mode,reference,event_id; record only |
| POST `/payments/{id}/verify` | A | Reconciliation evidence, status; no implicit bank integration |
| POST `/payments/{id}/reverse` | A | reason; compensating audited correction |
| POST `/tickets/{id}/documents` | A/D | kind; generate immutable gate pass/intake/service receipt; 202 |

Example completion command (UUIDs are illustrative; all referenced objects must already be authorized in tenant):

```json
{"resolution_notes":"Replaced failed power adapter; load test passed.","photo_id":"11111111-1111-4111-8111-111111111111","acceptance_id":"22222222-2222-4222-8222-222222222222","payment_mode":"UPI","location":{"client_event_id":"33333333-3333-4333-8333-333333333333","lat":11.342000,"lng":77.719000,"accuracy_m":9,"captured_at":"2026-11-14T08:30:00Z","mock_signal":false}}
```

Payment ledger entry is a separate idempotent command; completion does not invent a payment. Signature, photo, acceptance and location must belong to this ticket/user/customer context; merely knowing a same-tenant media ID is insufficient.

## CRM and contracts

| Method/path | Access/flag | Payload / result |
|---|---|---|
| GET/POST/PATCH `/teams[/{id}]` | A, sales_crm | name,members; membership revokes queue access immediately |
| GET/POST `/leads` | A/S own or member queue, sales_crm | customer,site,source,requirement,value,currency,assignee or queue,followup |
| GET/PATCH `/leads/{id}` | A/S scoped, sales_crm | Contact/requirement/value/follow-up fields; stage via command |
| POST `/leads/{id}/claim` | S member queue/A | Atomic claim only when unassigned |
| POST `/leads/{id}/assign` | A | user_id/team_id; validates role/team |
| POST `/leads/{id}/activities` | A/S scoped | CALL/NOTE/VISIT,note,location for visit |
| POST `/leads/{id}/stage` | A/S scoped | stage,reason; WON via conversion endpoint |
| POST `/leads/{id}/convert` | A/S scoped + service flag | won_value,site,asset,installation issue,priority; one ticket, 201/replay |
| GET/POST `/quotations` | A/D ticket or S lead scoped | customer,parent ID,lines,valid_until,currency; totals server computed |
| POST `/quotations/{id}/send` | Scoped quote editor | Freeze revision; generate PDF, mark sent; sending to customer explicit |
| POST `/quotations/{id}/decision` | A/D/S scoped with evidence | accepted/rejected,customer evidence; cannot approve changed revision |
| GET/POST/PATCH `/amc-contracts[/{id}]` | A/D, amc_tracker | number,customer,dates,value,coverage,asset IDs,status |
| POST `/amc-contracts/{id}/schedules` | A/D, amc_tracker | asset_id,interval_months,next_due; one occurrence per date |
| GET `/amc-contracts/{id}/occurrences` | A/D, amc_tracker | Scheduled and generated tickets |

Customers/sites are shared module resources: access requires either service or CRM flag plus role/record permission. Quotes inherit parent module/permissions. Missing service flag prevents won-to-installation conversion with actionable error; preserve lead draft.

## Media, notifications, reports and privacy

| Method/path | Access | Payload / result |
|---|---|---|
| POST `/media/uploads` | U authorized parent | parent_type,parent_id,purpose,mime,bytes,sha256; quota reservation + short-lived signed upload, 201 |
| POST `/media/{id}/finalize` | Owner/authorized actor | Actual object metadata verified; 202 scanning |
| GET `/media/{id}` | Authorized parent reader | State; download URL only CLEAN |
| DELETE `/media/{id}` | A/owner unattached draft | Retention check; purge job,204 |
| PUT/DELETE `/devices/{id}/push-token` | U own | Token registration/rotation or unbind; no raw token reads |
| GET `/notifications` | U own | Cursor unread/all |
| POST `/notifications/{id}/read` | U own | Idempotent read timestamp |
| GET `/events` | U | SSE authorized event IDs/versions, Last-Event-ID supported |
| GET `/dashboard` | A tenant; U personal | Enabled-module metrics only, period and snapshot timestamps |
| GET `/audit` | A | Safe redacted tenant audit only |
| POST `/reports` | A | from,to,timezone,sections; 202 run ID; custom download available without email module |
| GET `/reports/{id}` | A | Status,report version and authorized download links |
| POST `/reports/test-email` | A + monthly_email_reports | Period; recipient restricted to caller's verified admin email, `TEST` subject; 202 |
| GET/PATCH `/report-settings` | A + monthly_email_reports | Approved verified-admin recipients,local time,sections; audited |
| POST `/me/consents` | U own | purpose,policy_version,granted; server timestamps |
| POST `/me/consents/{id}/revoke` | U own | Stop collection and sessions immediately |
| POST `/me/deletion-requests` | U reauthenticated | reason optional; 202 case reference and retention explanation |
| GET `/me/deletion-requests/{id}` | U own / verified recovery link | Status and disclosed exceptions |
| POST `/public/deletion-requests` | Public rate-limited | slug,email; generic 202 verification message; no account enumeration |
| POST `/public/deletion-requests/verify` | One-use signed link | Token verifies identity; start same deletion process |
| GET `/privacy`, `/delete-account` | Public | Human-readable policy/request page; no app installation needed |
| GET `/health/live` | Public | Minimal alive flag |
| GET `/health/ready` | Internal/operator | Dependency status without secrets |

Report settings use tenant report time plus report_preferences for opted-in verified active admins. Do not email arbitrary request-supplied addresses.

## Contract verification

Each family must test unauthenticated, forbidden role, disabled feature, suspended tenant, foreign UUID, stale version, duplicate replay and malformed payload. POST attempts with `tenant_id`, `role=SUPER_ADMIN`, server timestamps or ownership overrides must fail validation. Responses never include password hashes, OTP hashes, refresh/push tokens, private bucket keys or unrestricted audit JSON. Generate OpenAPI examples from fixtures and test frontend contracts against those schemas during implementation.
