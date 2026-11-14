# Telite CRM

Multi-tenant hardware sales and field-service SaaS: mobile employee workspace, company portal and platform administration.

**Current status: Phase 1 architecture and documentation only.** No backend, mobile app or production deployment has been implemented. Phase 2 requires owner confirmation.

## Review the design

| Document | Contents |
|---|---|
| [PRD.md](PRD.md) | Scope, role workflows, mobile UX, acceptance criteria and phase gates |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Stack, tenant isolation, RBAC, authentication, jobs, storage, deployment and folder plan |
| [db/schema.sql](db/schema.sql) | PostgreSQL reference DDL, tenant FKs, indexes, RLS policies and identity guard |
| [docs/DATABASE.md](docs/DATABASE.md) | Domain Mermaid ERDs and enforcement boundaries |
| [docs/API.md](docs/API.md) | REST routes, permissions, headers, payloads, errors, idempotency and concurrency |
| [docs/EDGE_CASES.md](docs/EDGE_CASES.md) | Security, offline, workflow and concurrency acceptance matrix |
| [docs/REPORTING.md](docs/REPORTING.md) | KPI formulas, monthly periods, scheduler recovery and PDF/CSV delivery |
| [PLAYSTORE_DEPLOY.md](PLAYSTORE_DEPLOY.md) | Capacitor/native plan, manifests, signing workflow, privacy and release gates |
| [.env.example](.env.example) | Environment contract; blank secrets, safe illustrative hostnames |
| [docs/SOURCES.md](docs/SOURCES.md) | Official technical and policy references |
| [docs/VALIDATION.md](docs/VALIDATION.md) | Checks performed and outstanding runtime validation |

## Key decisions for approval

FastAPI + PostgreSQL + React/Vite/Tailwind + Capacitor. All business data uses tenant_id, application guards and PostgreSQL FORCE RLS; platform identities are separate. PostgreSQL is required for the SaaS path, including development and test. Background travel tracking is explicit, consented, off by default and subject to a separate native/Play release gate. Offline drafts are supported; authoritative punches/completions require server validation. INR/Asia-Kolkata are initial configurable defaults; monthly reports run on the 1st at 08:00 local time.

## Next phase after approval

Build authentication/session rotation, migration/provisioning roles and RLS integration tests, tenant/feature/quota guards, and the working super-admin portal. Do not implement later modules as untested placeholders. Reference DDL is an executable design for a fresh database, not an already-tested migration or a command to run against existing production data.
