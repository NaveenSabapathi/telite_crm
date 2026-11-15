# Tenant operations implementation

The continuation uses the existing FastAPI/Pydantic/SQLAlchemy/psycopg stack and frozen Phase 2 migrations. Existing Phase 2 endpoints and tests are unchanged. Migration `0003_phase3_operations` adds evidence bytes, report snapshots and attendance branch/break snapshots to existing RLS tables. It does not introduce a second business schema.

## Upgrade and credentials

Generate a separate random `OPERATIONS_DB_PASSWORD` (at least 24 characters); configure `OPERATIONS_DATABASE_URL` for direct execution. The Compose file supplies it to the tenant API and mail worker. Apply `alembic upgrade head`, then `python -m app.provision roles` as the migration operator. Never grant the operations role to the platform role.

The `crm_api` role retains the Phase 2 denial of ticket access. Operations authenticate using the existing dependency, then open a new `TenantSession` with the same verified tenant ID and a restricted, non-owner `crm_operations` connection. SQL includes explicit tenant predicates in addition to FORCE RLS. The operations role has no global tenant/platform-identity read access. Role, feature and assignment guards apply before command replay.

## Commands

All new POST commands require a UUID `Idempotency-Key`. Transitions, decisions and assignments also require `If-Match` with the current integer version. Replaying the same command key returns the stored result; changed payloads return 409. Client tenant IDs and extra fields are forbidden. GET collections use bounded pages; no secret hashes or evidence bytes appear in ordinary responses.

| Routes | Permissions / behavior |
|---|---|
| GET `/api/v1/workforce/settings`; POST/PATCH `/branches`, `/shifts` | Company admin; existing branch/shift GET contracts retained |
| PATCH `/users/{id}/schedule` | Company admin; scoped branch/shift IDs, version and audit reason |
| GET `/attendance`, `/attendance/status`; POST `/attendance/punch-in`, `/attendance/{id}/punch-out` | Attendance feature; own punches, admin collection visibility |
| GET/POST `/leave-requests`; POST `/{id}/decision` | Attendance feature; own request, admin decision, no self-review or overlap |
| GET `/travel-summary` | Attendance feature; straight-line estimates, explicitly not approved reimbursement |
| GET/POST `/tickets`; GET `/{id}`; POST `/{id}/assign`, `/transition`, `/parts`, `/evidence`, `/complete` | Service feature; admin/dispatcher intake, assigned engineer execution |
| GET `/tickets/{id}/payments`; POST `/payments/{id}/verify` | Assigned ticket readers; only company admin reconciles collections |
| GET/POST `/leads`; GET `/{id}`; POST `/{id}/assign`, `/activities`, `/stage`, `/convert` | CRM feature; admin or assigned sales user; conversion also requires service feature |
| GET `/dashboard` | Company admin; enabled modules only |
| POST `/reports`; GET `/reports/{id}/download?format=csv\|pdf` | Company admin; retained snapshot and revision; feature recheck at download |
| POST `/reports/test-email`; PUT `/report-settings` | Report feature; verified admin address, no arbitrary recipients |
| POST `/me/location-consent` | Explicit foreground consent/revocation, policy version recorded |
| POST/GET `/me/deletion-requests` | Own requests; password reauthentication and session revocation on submission |
| GET `/notifications` | Own durable inbox; hides alerts for disabled modules |

## Behavior and limits

- Preserve canonical roles `COMPANY_ADMIN`, `DISPATCHER`, `ENGINEER`, `SALES` and feature names `attendance_gps`, `field_service_tickets`, `sales_crm`, `amc_tracker`, `monthly_email_reports`.
- Office acceptance requires distance plus GPS accuracy to fit the configured radius. Fixes must be at most 60 seconds old, accuracy at most 50 m, and have foreground consent. Work mode is the employee's configured mode. Client coordinates remain evidence, not proof against spoofing.
- Attendance preserves shift start date, UTC schedule, grace, break and branch fence. Overnight/DST calculations are explicit. Missing checkout is flagged, never fabricated. Stale open punches require operational review; an automated correction/exception UI is not included.
- Service follows ASSIGNED → EN_ROUTE → ON_SITE → IN_PROGRESS, optional waiting states, RESOLVED → COMPLETED. Arrival and completion locations are append-only. Arrival GPS is recorded; customer-site geofencing/coordinate verification is not claimed. Active-job reassignment is rejected pending a reviewed reassignment workflow.
- Customer signature plus a completion photo is the implemented acceptance route. SMS OTP provider integration is not included. The engineer freezes resolution notes at RESOLVED; completion must use those exact notes. Photos/signatures are decoded, pixel-bounded, re-encoded JPEGs stored inside scoped PostgreSQL media rows, with quota accounting; private object storage migration is separate work.
- `/parts` records external spares and vendor-RMA notes/cost. It does not decrement warehouse inventory or replace the fuller vendor/RMA/AMC contract lifecycle described in Phase 1. AMC coverage at intake is explicitly administrator-declared.
- Sales stage `SURVEY_DONE` is displayed as Site Visit. WON stores owner/value/currency history; conversion locks the lead and uses the existing unique lead→ticket constraint.
- Payments start RECORDED, then require explicit administrator reconciliation to become VERIFIED. Cash and UPI are collection modes; warranty/credit do not create payments. No bank/payment-provider processing is claimed.
- Reports use local calendar month boundaries, safe CSV cells and a server PDF renderer without remote content. Snapshot-based downloads are repeatable; current reports show current incomplete entries. Monetary service totals separate verified and recorded collections. Email delivery uses bounded retry and stable report IDs, but SMTP cannot guarantee exactly-once delivery.
- Monthly subscription is explicit per verified active admin. Scheduler catches up at most three eligible months after the tenant-local first day at 08:00; current recipient role/status/opt-in is checked before delivery. Auth email behavior remains unchanged.
- Durable notifications cover upcoming shifts, late punches, missed checkout and due follow-ups. External FCM delivery is not configured.
- Android readiness includes manifest, bundled-assets Capacitor configuration, location disclosure and deletion request UI. Native platform generation, secure native token storage, final HTTPS API origin, native plugin integration, signed AAB and physical-device validation remain release gates. The web implementation must not be advertised as a finished Play Store build.
- Deletion requests revoke sessions and retain a review case. Automated erasure/anonymization, public verified deletion recovery, retention execution and backup tombstone replay are not implemented; request submission is not completed deletion.

The feature flags do not advertise future capabilities as implemented. `background_location` remains unused; no background collection is introduced.
