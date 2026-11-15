# Validation status

Updated 15 November 2026. The Phase 2 evidence below is preserved; continuation evidence is listed first.

## Continuation validation

- Mandatory onboarding completed at base commit `0a33fda`; all 24 unchanged backend tests passed before code changes.
- Applied migration `0003_phase3_operations` on PostgreSQL 17.11; provisioned the separate restricted operations role.
- The original 24 tests and the initial 14 new tests passed together (38 total). The expanded 17-test operational suite also passed, including scheduled reports, inbox deduplication, payment reconciliation and cross-tenant operations-role checks.
- Python lint/format and React/TypeScript production build passed.
- Browser suites are being verified through the repository CI; local Chromium launch is blocked by Unix-socket restrictions in the authoring environment.
- No external SMTP email, deployment, Android release build or Play publication was performed. Signature acceptance is implemented; SMS OTP is not configured. Read [implementation limits](PHASE3_4_API.md).

## Historical Phase 2 validation

## Executed locally

- Applied the complete initial schema using Alembic to PostgreSQL 17.11 and applied the rate-counter retention revision.
- Provisioned `crm_api`, `crm_control` and `crm_mail` as restricted non-owner, non-superuser, non-BYPASSRLS roles.
- **24 integration tests passed** against real PostgreSQL. Coverage includes atomic/idempotent onboarding, invitation acceptance/reissue, cross-tenant read/update/FK rejection, missing context and pooled connection reuse, ORM select/flush guards, runtime privilege restrictions, all 49 tables' FORCE RLS, role/mass-assignment denial, concurrent quota enforcement, last-admin protection, feature dependencies/version conflicts, suspension, refresh rotation/replay/absolute expiry, separate token audiences, MFA replay, web CSRF, resets/session revocation, login throttling, expired tokens/tenants, encrypted mail outbox delivery/retry, request body bounds and rate-counter cleanup.
- Python compile/lint/format checks and React/TypeScript production build passed.
- Initial frontend build measured approximately 76 KB gzip JavaScript and 3 KB gzip CSS; subsequent builds report exact sizes in Vite output.

SMTP tests use a captured sender function and synthetic accounts. No external mail was sent. RLS tests use runtime roles; database ownership is used only for disposable fixtures and migrations. Tests refuse to truncate databases unless APP_ENV=test and the database name is telite_test.

## Browser and deployment verification

A Playwright integration workflow covers platform MFA login, company provisioning, feature changes, responsive viewport checks, accepting an admin invitation, company login, employee invitations and audit activity. Local browser launch was blocked by the workspace's Chromium Unix-socket restrictions. The same test subsequently **passed on GitHub Actions**, including desktop/mobile viewport checks. [Successful verification run](https://github.com/NaveenSabapathi/telite_crm/actions/runs/43601188661) on implementation commit `babc97674cf1d5ffe0c1911af9aa70baa1b96332`: 24 PostgreSQL integration tests, frontend production build, and 1 complete browser workflow passed. The following documentation-only update records that evidence.

Docker was unavailable in the authoring workspace, so the Compose image build/start was not executed locally. The APIs, SQL migrations, role provisioning and frontend build were exercised directly. TLS, real SMTP deliverability, Android builds, load targets, backup/restore drills and Phase 3–5 workflows were unimplemented at that historical Phase 2 checkpoint; see continuation evidence above.

## Reproduce

Use a fresh disposable PostgreSQL database named `telite_test`, APP_ENV=test, separate random runtime DB passwords, JWT_SECRET/PLATFORM_JWT_SECRET, FIELD_ENCRYPTION_KEY and connection URLs described in PHASE2_SETUP.md. In `backend`:

```bash
pip install -r requirements.lock
alembic upgrade head
python -m app.provision roles
ruff check .
ruff format --check .
pytest -q
```

Browser test: set PUBLIC_WEB_URL=http://localhost:5173, start tenant API on 8000, control API on 8001, and Vite on 5173; then in `frontend` run `npm ci`, `npx playwright install chromium`, `npm run test:e2e`. Set E2E_PYTHON if Python is in a virtual environment. The test seeds synthetic platform credentials and clears the disposable test database; never run it against production.

No production deployment or Play Store publication has occurred.
