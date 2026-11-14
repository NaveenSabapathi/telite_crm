# Phase 1 validation status

14 November 2026. Repository was confirmed empty before documentation was added.

## Checks performed

Static checks cover 49 business tables, each with a non-null tenant UUID, composite primary key, tenant-leading created-time index, FORCE RLS and tenant policy. Business foreign keys include tenant_id and reference declared tables. Markdown local links/fences and JSON examples are checked.

These are structural checks, not PostgreSQL syntax execution or proof of isolation. No PostgreSQL server/client is available in this workspace, so the reference DDL has not been executed. Mermaid source has not been render-tested. No application, Android build, provider integration, load test or restore test exists yet.

## Required implementation verification

1. Apply reference schema through a reviewed initial Alembic migration to disposable PostgreSQL. Provision migration owner separately from API/worker/control roles; no runtime owner/BYPASSRLS/DDL/TRUNCATE. Restrict event/audit records to INSERT/SELECT for normal runtime users; retention uses a separate controlled role.
2. Test two tenants as actual runtime roles: reads/writes, composite FK failures, missing context, pool reuse, file access, SSE and exports.
3. Implement and test service-level invariants in DATABASE.md: lifecycle, assignment, photo/OTP binding, customer/AMC consistency, stock locks, quotas, shift overlaps and provider failure recovery.
4. Generate real OpenAPI from code and verify frontend contracts and role/feature matrix.
5. Render ERDs; verify responsive/accessibility behavior. Build and test the Android release in Phase 5.

Phase 1 is a design specification, not an implemented production system. Phase 2 requires owner confirmation.
