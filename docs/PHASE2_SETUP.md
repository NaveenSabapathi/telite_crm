# Phase 2 — installation and operations

Phase 2 implements the backend identity/control plane and responsive administration portal. It does not implement attendance punches, tickets, leads, reports, Android packaging, billing or production disaster recovery. The 49-table Phase 1 database is migrated, but runtime accounts intentionally have no privileges on unimplemented business modules.

## Local installation with Docker Compose

Requirements: Docker Engine with Compose v2, Python 3 for secret-file generation, Git. Commands run from repository root. Use a new database; do not point these commands at another application's database.

```bash
python scripts/generate_dev_env.py
docker compose --profile dev-mail up --build -d
```

The generator refuses to overwrite `.env`. `migrate` waits for PostgreSQL, runs `alembic upgrade head`, then creates the three restricted runtime roles. API/control/mail start only after migration succeeds. Migration has a separate DB credential and is never performed by runtime APIs. Only the web portal and local Mailpit UI publish host ports, bound to loopback; PostgreSQL and backend ports are not published.

Create the first platform administrator interactively:

```bash
docker compose run --rm migrate python -m app.provision admin --email owner@example.com
```

Replace the email with your actual administrator address. The command prompts for a password, prints an authenticator enrollment URI once, and asks for a valid authenticator code before saving. Enroll it in an authenticator app; keep recovery material securely offline. There are no default passwords or public bootstrap routes. Platform MFA is mandatory; reused TOTP time steps are rejected.

Open `http://localhost:8080` → Platform admin. Create a company with branch coordinates, shift, limits and initial administrator email. Open `http://localhost:8025` to inspect the captured development invitation. This local mail service never sends the message externally. Accept the invitation, set a password and sign into Company using the slug and email. The admin's invited account reserves one employee slot.

### Available portal actions

- Platform login with MFA, session resume and logout.
- Company listing/search/pagination, creation and selected-company detail.
- Subscription validity, employee cap, storage quota, suspension/reactivation.
- Full feature matrix with dependency validation and optimistic version checks.
- Company-admin reset/invitation recovery; no password/secret returned to browser.
- Platform audit and DB-backed company/active-subscription metrics.
- Company owner employee invitations, role changes, enable/disable and audit history.
- Invitation/password-reset screens; self-service forgot-password request.
- Non-admin login shows identity and phase status without exposing employee administration.

The Phase 2 employee invitation UI uses the initial branch and shift. Additional branch/shift configuration belongs to Phase 4. The UI lists up to 100 employees; the API supports pagination. Platform search uses bounded offset pagination in Phase 2; signed cursor pagination in the Phase 1 design is not implemented yet.

## Production deployment checklist for this phase

Set `.env`: real HTTPS `PUBLIC_WEB_URL` without trailing slash, actual `ALLOWED_HOSTS`, `APP_ENV=production`, `COOKIE_SECURE=true`, and SMTP host/port/sender with `SMTP_STARTTLS=true`. Store SMTP credentials only in the mail service's environment. Use independent random signing secrets and protect/back up the field-encryption key; losing that key makes queued recovery links and platform MFA secrets unreadable. No automatic key rotation is supplied in this phase: rotate with a planned session invalidation/re-enrollment procedure.

Put a TLS reverse proxy in front of the loopback web port. Forward the original Host and ensure it matches ALLOWED_HOSTS. The container gateway overwrites X-Forwarded-For; APIs accept proxy headers only because they are internal and not published. If another host proxy sits in front, configure its trusted source addresses and the gateway real-IP rules explicitly; never accept arbitrary forwarded IPs from the internet. Without that configuration rate limits aggregate clients at the proxy IP.

The supplied Compose is a single-host bootstrap, not a completed HA/backup solution. Provision encrypted DB backups/WAL archive, object storage, monitoring, tested restores, dependency scans and TLS before a production pilot. Docker image execution was not validated in the authoring workspace because Docker was unavailable; API/PostgreSQL and frontend build/browser tests are independent checks documented in VALIDATION.md. Pin reviewed image digests for deployment.

```bash
docker compose logs --tail=100 migrate api control auth-mail
docker compose exec api python -c 'from app.db import verify_runtime_role; verify_runtime_role("tenant")'
docker compose exec control python -c 'from app.db import verify_runtime_role; verify_runtime_role("control")'
```

Never use `docker compose down -v` on data you need to retain. Downgrade is intentionally blocked: restore to an isolated database and review any destructive recovery action. Initial SQL snapshots are frozen under `backend/migrations/sql`; future changes must use a new Alembic revision rather than editing the installed initial revision.

## Direct developer workflow

Python 3.12+, PostgreSQL 17+, Node 24. Create a virtual environment and install `backend/requirements.lock`. Build frontend with `npm ci && npm run build`. Runtime roles must be provisioned before starting APIs.

From `backend`, with the appropriate environment loaded:

```bash
alembic upgrade head
python -m app.provision roles
python -m app.provision admin --email owner@example.com
uvicorn app.api:app --host 127.0.0.1 --port 8000
# Separate terminal with CONTROL_DATABASE_URL and PLATFORM_JWT_SECRET:
uvicorn app.control_api:app --host 127.0.0.1 --port 8001
# Separate terminal using the mail role:
python -m app.mail_worker
```

From `frontend`, run `npm run dev`. Set `PUBLIC_WEB_URL=http://localhost:5173` and `COOKIE_SECURE=false` for this local Vite workflow. The Vite proxy routes both APIs under the same browser origin; no browser tokens are stored in localStorage. Access tokens stay in memory; refresh cookies are HttpOnly and CSRF-protected. Session resume uses a readable CSRF cookie and validates exact Origin. Native token transport is implemented at the API level, but Capacitor integration/CORS adapters are later phases.

OpenAPI is generated from implemented routers: tenant `/docs`, control `/docs` on their respective direct services. The web gateway intentionally exposes API paths, not the direct backend documentation paths. `docs/API.md` remains the broader target contract; `docs/PHASE2_API.md` lists the implemented subset.

## Mail delivery and recovery

The auth-mail worker reads a scoped durable outbox and checks active user, current token, expiration and tenant eligibility before sending. Sensitive link tokens are encrypted at rest and removed after delivery/supersession. SMTP has a timeout, bounded retries (8 attempts) and exponential backoff. A crash after provider acceptance may produce a duplicate email; links remain single-use. No external mail is sent by tests. Failed jobs retain the `DELIVERY_FAILED` code without provider text or token leakage.

To inspect failed authentication mail as a trusted operator, use a migration/admin connection with an explicit tenant filter and select only `id,event_type,attempts,last_error_code,available_at` from `app.outbox`. Never print `payload`. Fix SMTP first; a new password reset/invitation supersedes earlier links. Expired employee invitations can be reissued using the company admin invitation-reissue endpoint; platform can reissue initial admin access through Reset access. Operator retry of a still-valid message must reset attempts/available_at for that one selected tenant/job only. Scheduled retention cleanup and full delivery dashboards are future operations work.

## Security implementation notes

- PostgreSQL RLS and composite tenant FKs cover all 49 business tables. SQLAlchemy TenantSession rejects missing context for all queries, attaches transaction-local context, filters ORM selects, rejects bulk ORM writes, and checks flush ownership. Reviewed SQL repositories rely additionally on enforced database policies.
- Control API and tenant API are separate processes and roles; their JWT signing secrets and audiences are distinct. Both reject inactive/revoked sessions server-side. Platform cannot query ticket/customer business tables with its runtime role.
- Tenant quota enforcement uses a PostgreSQL trigger plus row lock; initial and pending invitations count as active reserved accounts. Concurrent invitations cannot exceed cap.
- Passwords use Argon2id. Refresh tokens and reset tokens are hashed; MFA secrets/outbox links use Fernet. Web refresh/logout requires exact Origin and CSRF proof. Refresh replay revokes the whole family and commits that revocation before rejecting the request. Refresh family lifetime is absolute, not silently extended on rotation.
- Tenant suspension revokes existing sessions; reactivation does not resurrect them. Role/active changes and password resets revoke sessions. Last active admin cannot be removed/demoted through the service.
- Module guards are reusable dependencies. `/capabilities/{feature}` reports authorization eligibility, explicitly `workflow_available=false`; it is not a placeholder business workflow.
- Login/reset rate limits use a shared database counter, so limits apply across API processes. Expired rate buckets are pruned by the auth-mail worker through a restricted cleanup function. Keep that worker running even when messages are infrequent. No secrets/credentials are accepted through business role fields.
- Idempotent company creation uses a unique key, request digest and transaction lock. All edits use `If-Match`. Employee invitations use per-tenant email uniqueness; retries cannot create duplicates but currently return conflict rather than replaying the first response. No deletion endpoint for customer/business data is implemented in Phase 2.
