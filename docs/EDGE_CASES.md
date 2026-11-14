# Edge-case protections and acceptance matrix

These are requirements and future test cases, not already-passing application tests. P0 blocks any tenant pilot; P1 blocks public release.

| ID / Priority | Scenario | Required behavior / test |
|---|---|---|
| ISO-01 P0 | Tenant A supplies B UUID in list/detail/update/nested URL | 404; zero B records, counts, file links or event metadata |
| ISO-02 P0 | A inserts B customer/assignee/stock FK | Composite FK rejects, whole transaction rolls back |
| ISO-03 P0 | API/worker has no context or pooled B connection reused for A | ORM fails closed; DB RLS denies; context reset tested across commit/rollback and task errors |
| ISO-04 P0 | Missing raw SQL filter | RLS scopes non-owner runtime role; CI checks every new business table has tenant_id, composite PK/FKs and FORCE RLS |
| ISO-05 P0 | Engineer changes role/owner/version in mass payload | Reject unknown/privileged fields, never silently promote |
| ISO-06 P0 | Platform token sent to tenant API / tenant token to platform API | Audience/routes reject; no generic admin bypass |
| ISO-07 P0 | Search/cache/export/media/SSE/report/PDF references another tenant | Key namespace plus authorization checked at retrieval and worker execution |
| IAM-01 P0 | Refresh token reused, password reset, suspended tenant | Revoke family or all required sessions; access and streams stop despite token expiry remaining |
| IAM-02 P0 | Simultaneous employee invites/reactivations at cap | Quota row serialized; at most cap active/invited reserved slots |
| IAM-03 P0 | Delete/demote last active admin | 409 replacement-required; deletion request still accepted for managed transfer and personal-data erasure |
| IAM-04 P0 | Disable feature while worker queued | Worker rechecks; no prohibited new action; pending jobs marked skipped/recoverable |
| GPS-01 P1 | Approximate/denied GPS, inaccurate indoor fix | Retry or explicit review; no synthetic success; other screens remain usable |
| GPS-02 P1 | Mock flag, impossible jump, old timestamp, replayed event | Flag/review or reject per policy, preserve reason; never claim fraud conclusively |
| GPS-03 P0 | Wrong user/device supplies location or signature | Check actor and parent binding; reject even if tenant matches |
| GPS-04 P1 | Geocoder timeout/provider rate cap | Preserve coordinates; address pending/retry; no external request to client-controlled URL |
| GPS-05 P1 | Off-shift/background consent revoked or app killed | Stop native tracking on revocation/end, enforce server cutoff; kill/reboot path tested on physical Android |
| ATT-01 P0 | Double tap / concurrent punch-in | Unique constraint + idempotency yields one open record |
| ATT-02 P1 | Overnight shift, month boundary, DST tenant | Assign start-date; compute UTC instants from IANA zone, test ambiguous/nonexistent local times; policy uses earlier instant for ambiguous start, later end; nonexistent time advances to first valid instant and flags schedule |
| ATT-03 P1 | Late arrival changed by retroactive shift edit | Snapshot remains stable; approved correction retains old/new evidence |
| ATT-04 P1 | Missing checkout or forgotten days-old open log | Mark incomplete, request reviewed closure before new shift; never invent worked hours |
| ATT-05 P0 | Concurrent leave approval/attendance | Lock employee/day range; overlap check in transaction; separate reviewer; no self-approval |
| SVC-01 P0 | Skip state, engineer not assigned, reassigned while offline | 409/403; preserve draft, require refresh; no status jump |
| SVC-02 P0 | Complete without notes/photo/proof/location | 422; no completion/outbox/payment mutation |
| SVC-03 P0 | OTP brute force/replay/old resolution | Bounded attempts, expiry/cooldown, one-use verified proof bound to version; redact logs |
| SVC-04 P1 | Customer absent/site pin wrong/walk-in device | Waiting state or audited site exception; walk-in bench path distinct |
| SVC-05 P0 | Two jobs consume last spare | Lock stock rows; one succeeds, other 409; ledger and balance agree |
| SVC-06 P1 | Partial part return, RMA replaced serial | Return ≤net consumption, compensating ledger; old serial preserved |
| CRM-01 P0 | Two reps claim same lead or retry WON | One claim; exactly one linked ticket; atomic conversion rollback on failure |
| CRM-02 P1 | Lost without reason or accepted quote edited | Reject; new quote revision invalidates acceptance |
| AMC-01 P0 | Scheduler restart/catch-up, two workers same occurrence | Unique occurrence; one maintenance ticket; clamp month-end recurrence to last valid day |
| AMC-02 P1 | Expired/cancelled coverage, different-customer asset | No automatic generation/coverage; validate asset belongs to contract customer |
| JOB-01 P0 | Broker outage after DB commit | Outbox retained and replayed; no missing assigned-ticket inbox event |
| JOB-02 P1 | Crash after external SMTP/FCM accepted | Retry bounded, report/delivery ID stable; possible duplicate email recorded honestly |
| FILE-01 P0 | Spoofed MIME, oversized file, malicious SVG/HTML | Quarantine and inspect; bounded processing; no attachment before CLEAN |
| FILE-02 P0 | Concurrent uploads exceed quota, abandoned reservation | Atomic reservation; verify actual bytes; release on expiry; prevent malicious over-reservation |
| FILE-03 P0 | PDF SSRF / CSV formula injection | Renderer cannot fetch arbitrary URLs; escape content, prefix dangerous spreadsheet cells |
| OFF-01 P0 | Same key different body / stale draft / wrong tenant switch | 409 or queue expired; namespace/purge; never automatic cross-user replay |
| OFF-02 P1 | Network lost after server commit | Replay same operation ID returns same authorized result |
| REP-01 P0 | Month timezone boundaries / disabled module | Exact half-open interval; correct enabled sections; zero-data denominator N/A |
| REP-02 P0 | Admin email changed before delivery | Reverify active authorized recipients immediately before send; no arbitrary address injection |
| PRIV-01 P0 | Account deletion / backup restore resurrects user | Revoke first, purge/minimize linked data, apply tombstone ledger on restore; verified case trail |
| OPS-01 P0 | DB migration fails halfway / corruption / backup missing | Transaction/expand-contract policy; restore drill into isolated DB and documented RPO/RTO evidence |
| MOB-01 P1 | Small screen, sunlight, screen reader, big text | 48px controls, non-color statuses, accessible forms; no clipped primary action |
| AND-01 P1 | Release merged manifest adds unwanted permissions | Inspect merged manifest/SDKs; remove unjustified permissions before Play upload |

## Test strategy by phase

Phase 2 PostgreSQL integration suite uses two seeded tenants with colliding human-visible ticket numbers/emails and different UUIDs. Run API/worker tests as the actual non-owner/non-BYPASSRLS role, not migration superuser. Exercise SELECT/INSERT/UPDATE/DELETE, relationship loading, bulk writes, raw SQL, report queries and connection pool reuse. Test role × feature × object ownership independently; RLS does not enforce engineer assignment.

Phase 3 uses deterministic clocks/location fixtures, concurrency barriers for stock/idempotency, and browser network failure tests. Phase 4 uses stub FCM/SMTP/geocoder and injected worker crashes, then real sandbox integrations with synthetic data. Phase 5 uses physical Android permission/reboot/battery tests and a signed release build with production-like HTTPS. CI must fail on unexpected table without policy, secret detection, type/lint/test failures and failed schema migration roundtrip on a disposable database.

## Data and policy subtleties

Device installation ID is random and resettable, not IMEI or a permanent hardware ID. Browser GPS cannot expose reliable Android mock-location flags; even native detection can be bypassed. Precise client coordinates are evidence with risk checks, not cryptographic proof of presence. No automatic punitive payroll action based only on a spoof flag.

A map coordinate pair gives a straight-line lower-bound distance. Routed estimates require routing provider calls; actual traces require consented active travel tracking and outlier filtering. Keep method, validity and approved allowance rate in records. Do not present summed estimates as exact kilometres driven.

Biometric use means local Android authentication only; never upload fingerprint/face templates. Employee selfie is a normal photo and does not establish liveness or face identity. Customer signature records acknowledgement of the specific work; it is not a blanket assertion of legally certified e-signature.
