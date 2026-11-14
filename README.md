# Telite CRM

Multi-tenant hardware sales and field-service SaaS: employee workspace, company administration and platform control plane.

**Phase 2 implemented:** FastAPI backend, PostgreSQL tenant isolation, authentication, MFA-protected super-admin portal, company provisioning, feature/plan controls, administrator recovery and employee access management. Attendance, tickets, CRM workflows, reports and Android packaging remain later phases.

## Start locally

Requires Docker with Compose v2 and Python 3. Run from repository root:

```bash
python scripts/generate_dev_env.py
docker compose --profile dev-mail up --build -d
docker compose run --rm migrate python -m app.provision admin --email your-admin@example.com
```

The bootstrap command prompts for a password and authenticator enrollment. No default admin credentials exist. Portal: `http://localhost:8080`. Development invitation/reset inbox: `http://localhost:8025`. Local Mailpit captures messages without sending external mail.

**Read [Phase 2 setup](docs/PHASE2_SETUP.md) before deployment.** The Compose stack is a local/single-host starting point, not a completed production backup/HA deployment. Production requires HTTPS, real SMTP/TLS, protected secrets and verified recovery procedures.

## Implemented safeguards

- All 49 business tables have composite tenant identities, tenant foreign keys and FORCE row-level security.
- Separate migration, tenant API, platform API and mail roles; runtime APIs reject owner/superuser/BYPASSRLS connections.
- Mandatory scoped SQLAlchemy sessions; platform operations cannot query future customer/ticket tables.
- Argon2id password hashing, distinct platform/tenant JWT secrets and audiences, rotating refresh families with replay detection and absolute expiry.
- MFA for platform administrators; secure web refresh cookies with Origin/CSRF validation; no access/refresh tokens in localStorage.
- Transactional company creation and invitation delivery; idempotent company creation, versioned edits, atomic employee quotas and last-admin protection.
- Server feature guards, suspension/session revocation, redacted audit, encrypted recovery-link outbox and bounded mail retries.

## Project layout

| Path | Purpose |
|---|---|
| `backend/app/` | Separate tenant/control API entrypoints, auth, scoped DB sessions, services and mail worker |
| `backend/migrations/` | Alembic revisions and frozen initial schema snapshots |
| `backend/tests/` | PostgreSQL integration tests and synthetic browser fixtures |
| `frontend/` | React/TypeScript/Vite/Tailwind responsive administration portal |
| `infra/`, `compose.yaml` | Container builds, same-origin gateway and local service orchestration |
| `.github/workflows/phase2-ci.yml` | Backend verification, frontend build and browser workflow |
| `db/` | Phase 1 reference SQL and Phase 2 initial extension |

## Documentation

| Document | Contents |
|---|---|
| [Phase 2 setup](docs/PHASE2_SETUP.md) | Installation, bootstrap, environment, operations and current limitations |
| [Phase 2 API](docs/PHASE2_API.md) | Implemented routes and permissions |
| [Validation](docs/VALIDATION.md) | Executed checks and remaining validation |
| [PRD](PRD.md) | Product scope, workflows and phase gates |
| [Architecture](ARCHITECTURE.md) | Target architecture, isolation and domain boundaries |
| [Database model](docs/DATABASE.md) | Mermaid ERDs and reference schema |
| [Target API](docs/API.md) | Full planned API across all phases |
| [Edge cases](docs/EDGE_CASES.md) | Acceptance matrix for security, concurrency and business workflows |
| [Reporting](docs/REPORTING.md) | Future KPI formulas and month-end reporting contract |
| [Android release plan](PLAYSTORE_DEPLOY.md) | Future Capacitor, permissions, signing and Play requirements |
| [Sources](docs/SOURCES.md) | Primary technical/policy references |

Phase 1 files remain the design baseline. Phase 2 uses bounded offset pagination and independent HS256 keys configured through environment variables; signed cursors/asymmetric signing configuration from the target design is not implemented. Browser native integration, policy/deletion UI, FCM, Redis/Celery and monthly reporting are not advertised as working Phase 2 features.
