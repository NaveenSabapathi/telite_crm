# Metrics and reporting contract

All reports are tenant-scoped and permission-checked at enqueue, generation and download/delivery. Store report period, timezone, revision, snapshot time and recipient snapshot. Tenant currency appears on every monetary total; no cross-currency addition.

## Metric definitions

| Metric | Exact v1 definition |
|---|---|
| Present today | Unique users with accepted attendance for today's shift-start date; review entries excluded and shown separately |
| Late arrivals | Accepted punches later than scheduled start + grace; late minutes measured after scheduled start, with threshold shown |
| Field / office | Attendance work-mode snapshot, not inferred from arbitrary current role |
| Leave | Approved scheduled leave hours/day-equivalents; On-Duty shown separately, not absence |
| Working days/hours | Scheduled nonholiday days in employment/assignment window; hours from complete accepted records minus scheduled break, capped at nonnegative; incomplete not counted as complete hours |
| Overtime | Explicitly approved overtime minutes only; report labels payroll input, no automatic pay calculation |
| Open tickets | Non-completed/non-cancelled tickets at report cutoff |
| SLA breach | Open past effective due time or completed later than effective due time; effective due = original due + eligible pause duration |
| SLA compliance | Completed tickets meeting effective SLA / eligible completed tickets ×100; no completed tickets → N/A |
| FTFR | Matured on-site jobs completed without revisit/reopen within 7 days / all matured on-site completions; exclude immature last 7 days, show cohort window and counts |
| Average resolution | Mean elapsed created→completed minus authorized pause seconds, for tickets completed in interval; show count and median, exclude cancelled |
| Pending spares/RMA | Current WAITING_SPARES tickets / nonclosed RMA cases, separate counts |
| Service revenue collected | VERIFIED payments received in period minus verified reversals attributable to period, reconciliation snapshot; recorded-unverified shown separately |
| Lead conversion | Leads created in interval and WON by snapshot / all leads created in interval; distinguish from count of wins closed in interval |
| Pipeline | Open leads' estimated values by current stage at snapshot; not recognized revenue |
| Sales leaderboard | Sum won_value for won_at within interval by assigned rep at win; immutable owner snapshot required in win activity |
| Lost breakdown | Count/value of LOST stage changes in period grouped by normalized reason; free-text notes remain private |
| Overdue follow-ups | Open leads with next_followup_at < now; alert dedupe includes followup timestamp/version |
| Travel | Approved segments in interval grouped by distance method; estimates and GPS traces separated to avoid double counting |
| Engineer efficiency | Display throughput, FTFR, SLA and hours as separate measures in v1; no opaque composite ranking until weights and fairness reviewed |
| Recurring issues | Intake category + curated diagnostic issue tags; free text alone not treated as consistent classification |

Historical counts use append-only transition/activity events, not today's state retrospectively applied. The reference schema provides activity details for win owner/value snapshots, payments.reversed_at, ticket diagnostic_tags and user employment dates. Validate immutable event snapshots in the domain services; do not parse human note text to compute financial history.

## Schedule and recovery

Default monthly run: 1st at 08:00 in tenant IANA timezone for the preceding calendar month. Convert local start-of-month and next-month to UTC; use `[start,end)`. No fixed 30-day subtraction. Include report snapshot timestamp and a warning if late offline submissions could change totals. Corrections regenerate a new revision, never silently rewrite sent reports.

Scheduler wakes every minute; iterates eligible active tenant IDs via restricted control-plane discovery. Each tenant gets a separate transaction/context. Determine missed periods since last successful schedule; queue bounded catch-up (max 3 months automatically, older requires admin request). Deduplicate `(tenant,kind,period_start,period_end,revision)`, plus outbox keys for dispatch. Worker uses repeatable-read snapshot to compile consistent sections and saves artifacts before email. Pause feature-disabled/suspended tenants; no accumulated duplicate sends on reactivation.

Reminders: start −10min; late at start+grace when no accepted punch; end+30min for open attendance; lead follow-up −30min; AMC expiry −30 days; SLA checks each minute. Recheck current record version, holiday/leave/tenant status when firing; dedupe by user/entity/event/date. Appointment edits cancel prior expected reminders logically by version mismatch. Off-hours notifications honor tenant quiet-hour policy except explicitly urgent operational alerts.

## PDF, CSV and email

PDF includes tenant name/logo, period/timezone/snapshot/revision, attendance summary, service metrics and CRM summary only for enabled modules. Employee details on separate pages with repeating headers and page numbers. CSV companion contains safe, documented columns with consistent IDs/timezones/currency; optional separate files in a ZIP by section. No precise GPS coordinates/signature images in routine emailed reports; authorised portal detail only.

Test report sends to caller's verified admin address with TEST prefix and rate limit 3/hour. Monthly recipients are opted-in verified active admins in the same tenant; revalidate before delivery. Do not use CC that leaks addresses across tenants. SMTP secrets server-side only; delivery status/provider errors redacted. Small PDF/CSV attachments capped at configurable total (default 10 MB); larger reports use short-lived authenticated download flow rather than publicly accessible links. Disable email rather than silently send incomplete reports. Include empty-data explanations, N/A denominators and missing/incomplete attendance counts.

CSV prevention: neutralize cells beginning with `=`, `+`, `-`, `@`, tab or carriage return where the value is user text; preserve numeric fields as vetted numeric values. Escape PDF HTML and forbid remote URL/file access in renderer. Render with bundled fonts, bounded images/time/memory; report generation cannot read host secrets.

## Required schema fields for reproducibility

Reference DDL includes these historical fields in event/details columns and explicit user employment dates. Phase 2 Alembic implementation must preserve them and validate JSON payloads with versioned typed schemas: lead stage transition details `{schema_version,from,to,won_value,currency,owner_at_win,lost_reason}`, ticket diagnostic tags, payment reversal effective time, report recipient preferences and scheduled job identity. Redacted audit is not a substitute for financial domain history. Report acceptance fixtures must prove recomputation after staff reassignment, profile anonymization and late corrections.
