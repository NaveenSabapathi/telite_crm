# Implemented Phase 2 API

The complete target API is in API.md. These routes are implemented now. JSON DTOs reject unknown fields. Authentication failures use 401; denied role/module/tenant state uses 403; foreign/absent objects use 404; stale version or constraint conflict uses 409; missing write precondition uses 428. Errors never echo credentials or database details.

| Routes | Access |
|---|---|
| POST `/api/v1/auth/login`, `/refresh`, `/logout` | Tenant credentials / refresh proof; web CSRF+Origin or native token body |
| POST `/api/v1/auth/forgot-password`, `/reset-password`, `/accept-invite` | Rate-limited; one-use reset/invite proof |
| GET `/api/v1/me`, `/me/sessions`; DELETE `/me/sessions/{sid}` | Current tenant identity; own sessions only |
| GET `/api/v1/users`, `/users/{uid}`, `/branches`, `/shifts`, `/audit` | Company admin only, current tenant |
| POST `/api/v1/users`; PATCH `/api/v1/users/{uid}` | Company admin, quota/role/last-admin checks; PATCH needs If-Match |
| POST `/api/v1/users/{uid}/reissue-invite` | Company admin, pending invitation only |
| GET `/api/v1/capabilities/{feature}` | Authenticated active tenant and enabled module; workflow_available=false |
| POST `/api/v1/platform/auth/login`, `/refresh`, `/logout` | Platform MFA/session; browser CSRF on refresh/logout |
| GET `/api/v1/platform/me`, `/tenants`, `/tenants/{tid}`, `/audit`, `/health` | Platform admin only |
| POST `/api/v1/platform/tenants` | Platform admin; required UUID Idempotency-Key |
| PATCH `/api/v1/platform/tenants/{tid}` | Platform admin; required If-Match + reason |
| PUT `/api/v1/platform/tenants/{tid}/features` | Platform admin; full feature map, If-Match + reason |
| POST `/api/v1/platform/tenants/{tid}/reset-admin` | Platform admin; selected tenant admin + reason |
| GET `/health/live` on each API | Minimal liveness |

A successful login returns access_token, expires_in, token_type, csrf_token; native tenant login also returns refresh_token for secure native storage. Web access tokens stay in memory; response sets HttpOnly refresh and readable CSRF cookies. Platforms and tenants use distinct cookie names/paths. Header `Authorization: Bearer <access>` is required on protected routes. No business endpoint accepts tenant_id from the client.

API base URL/tenant domain mapping uses a single portal hostname in this phase. Slug selects company at login; authenticated identity establishes tenant thereafter. Tenant custom-subdomain DNS/host mapping is documented future work, not active routing.

List limit defaults to 25, max 100; user/company lists use offset pagination. Scope and filters are server controlled. The UI exposes company pagination and up to 100 employees. Reset/invite messages return generic delivery status, never raw tokens. The implementation does not expose plaintext password setters to administrators.
