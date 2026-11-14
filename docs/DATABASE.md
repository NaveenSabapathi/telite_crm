# Database model

Reference: [schema.sql](../db/schema.sql). Every app table has a composite `(tenant_id,id)` primary key, timestamps and version; every business foreign key includes tenant_id. Control-plane exceptions are explicitly listed in ARCHITECTURE.md.

## Workforce

```mermaid
erDiagram
    branches {
        uuid tenant_id PK
        uuid id PK
        text name
        text address
        numeric lat
        numeric lng
        integer radius_m
        text timezone
    }
    shifts {
        uuid tenant_id PK
        uuid id PK
        text name
        time start_local
        time end_local
        smallint end_day_offset
        integer grace_minutes
        smallint_array weekdays
        integer break_minutes
    }
    users {
        timestamptz email_verified_at
        uuid tenant_id PK
        uuid id PK
        date employment_starts_on
        date employment_ends_on
        text email
        text phone
        text display_name
        text password_hash
        text role
        text work_mode
        boolean active
        integer token_version
        uuid branch_id
        uuid shift_id
        boolean must_reset_password
        text mfa_secret_ciphertext
    }
    shift_assignments {
        uuid tenant_id PK
        uuid id PK
        uuid user_id
        uuid shift_id
        date effective_from
        date effective_to
    }
    holidays {
        uuid tenant_id PK
        uuid id PK
        uuid branch_id
        date holiday_date
        text name
    }
    teams {
        uuid tenant_id PK
        uuid id PK
        text name
    }
    team_members {
        uuid tenant_id PK
        uuid id PK
        uuid team_id
        uuid user_id
    }
    devices {
        uuid tenant_id PK
        uuid id PK
        uuid user_id
        uuid installation_id
        text platform
        text push_token_ciphertext
        timestamptz last_seen_at
        timestamptz revoked_at
    }
    auth_sessions {
        uuid tenant_id PK
        uuid id PK
        uuid user_id
        uuid device_id
        text refresh_hash
        uuid family_id
        timestamptz expires_at
        timestamptz revoked_at
        timestamptz last_used_at
    }
    password_tokens {
        uuid tenant_id PK
        uuid id PK
        uuid user_id
        text token_hash
        text purpose
        timestamptz expires_at
        timestamptz used_at
    }
    consents {
        uuid tenant_id PK
        uuid id PK
        uuid user_id
        text purpose
        text policy_version
        timestamptz granted_at
        timestamptz revoked_at
    }
    location_events {
        uuid tenant_id PK
        uuid id PK
        timestamptz redacted_at
        uuid user_id
        uuid device_id
        uuid client_event_id
        numeric lat
        numeric lng
        numeric accuracy_m
        timestamptz captured_at
        timestamptz received_at
        text purpose
        text address
        boolean mock_signal
        jsonb risk_flags
        text verification
    }
    attendance {
        uuid tenant_id PK
        uuid id PK
        uuid user_id
        uuid shift_id
        date shift_date
        timestamptz scheduled_start
        timestamptz scheduled_end
        integer grace_minutes
        text work_mode
        timestamptz punch_in
        timestamptz punch_out
        uuid in_location_id
        uuid out_location_id
        uuid selfie_media_id
        text status
        integer late_minutes
        integer approved_overtime_minutes
    }
    attendance_corrections {
        uuid tenant_id PK
        uuid id PK
        uuid attendance_id
        uuid requested_by
        uuid reviewed_by
        text reason
        jsonb proposed_values
        text status
    }
    leave_requests {
        uuid tenant_id PK
        uuid id PK
        uuid user_id
        timestamptz starts_at
        timestamptz ends_at
        text kind
        text reason
        text status
        uuid reviewed_by
        timestamptz reviewed_at
    }
    branches ||--o{ users : "branch_id"
    shifts ||--o{ users : "shift_id"
    users ||--o{ shift_assignments : "user_id"
    shifts ||--o{ shift_assignments : "shift_id"
    branches ||--o{ holidays : "branch_id"
    teams ||--o{ team_members : "team_id"
    users ||--o{ team_members : "user_id"
    users ||--o{ devices : "user_id"
    users ||--o{ auth_sessions : "user_id"
    devices ||--o{ auth_sessions : "device_id"
    users ||--o{ password_tokens : "user_id"
    users ||--o{ consents : "user_id"
    users ||--o{ location_events : "user_id"
    devices ||--o{ location_events : "device_id"
    users ||--o{ attendance : "user_id"
    shifts ||--o{ attendance : "shift_id"
    location_events ||--o{ attendance : "in_location_id"
    location_events ||--o{ attendance : "out_location_id"
    media ||--o{ attendance : "selfie_media_id"
    attendance ||--o{ attendance_corrections : "attendance_id"
    users ||--o{ attendance_corrections : "requested_by"
    users ||--o{ attendance_corrections : "reviewed_by"
    users ||--o{ leave_requests : "user_id"
    users ||--o{ leave_requests : "reviewed_by"
```

## Customers and service

```mermaid
erDiagram
    customers {
        timestamptz phone_verified_at
        uuid tenant_id PK
        uuid id PK
        text name
        text company_name
        text phone
        text email
        varchar gstin
        text billing_address
        timestamptz archived_at
    }
    sites {
        uuid tenant_id PK
        uuid id PK
        uuid customer_id
        text name
        text address
        numeric lat
        numeric lng
        integer radius_m
        boolean coordinates_verified
    }
    assets {
        uuid tenant_id PK
        uuid id PK
        uuid customer_id
        uuid site_id
        text category
        text brand
        text model
        text serial_number
        date warranty_until
        date purchase_date
        timestamptz archived_at
    }
    tickets {
        uuid tenant_id PK
        uuid id PK
        text_array diagnostic_tags
        bigint number
        uuid customer_id
        uuid site_id
        uuid asset_id
        uuid assigned_to
        uuid lead_id
        uuid amc_id
        text service_mode
        text reported_issue
        jsonb physical_condition
        jsonb coverage_snapshot
        numeric estimated_cost
        char currency
        text status
        text priority
        timestamptz sla_due_at
        jsonb sla_policy_snapshot
        integer sla_paused_seconds
        text resolution_notes
        timestamptz completed_at
        integer reopened_count
        uuid checkout_location_id
        uuid completion_photo_id
        uuid signature_media_id
        timestamptz customer_accepted_at
        text payment_mode
    }
    ticket_events {
        uuid tenant_id PK
        uuid id PK
        jsonb details
        uuid ticket_id
        uuid actor_id
        text from_status
        text to_status
        text note
        uuid location_id
        timestamptz occurred_at
        timestamptz sla_pause_started_at
        timestamptz sla_pause_ended_at
    }
    media {
        uuid tenant_id PK
        uuid id PK
        uuid uploaded_by
        text object_key
        text content_type
        bigint bytes
        text sha256
        text state
        text purpose
        timestamptz expires_at
    }
    ticket_media {
        uuid tenant_id PK
        uuid id PK
        uuid ticket_id
        uuid media_id
        text kind
    }
    customer_acceptances {
        uuid tenant_id PK
        uuid id PK
        uuid ticket_id
        text method
        text otp_hash
        uuid signature_media_id
        timestamptz expires_at
        integer attempts
        timestamptz verified_at
        text contact_snapshot
        integer resolution_version
    }
    payments {
        uuid tenant_id PK
        uuid id PK
        timestamptz verified_at
        timestamptz reversed_at
        text reversal_reason
        uuid ticket_id
        uuid received_by
        numeric amount
        char currency
        text mode
        text reference
        timestamptz received_at
        text status
        uuid client_event_id
    }
    service_documents {
        uuid tenant_id PK
        uuid id PK
        uuid ticket_id
        text kind
        bigint number
        uuid media_id
        jsonb snapshot
    }
    customers ||--o{ sites : "customer_id"
    customers ||--o{ assets : "customer_id"
    sites ||--o{ assets : "site_id"
    users ||--o{ media : "uploaded_by"
    customers ||--o{ tickets : "customer_id"
    sites ||--o{ tickets : "site_id"
    assets ||--o{ tickets : "asset_id"
    users ||--o{ tickets : "assigned_to"
    leads ||--o{ tickets : "lead_id"
    amc_contracts ||--o{ tickets : "amc_id"
    location_events ||--o{ tickets : "checkout_location_id"
    media ||--o{ tickets : "completion_photo_id"
    media ||--o{ tickets : "signature_media_id"
    tickets ||--o{ ticket_events : "ticket_id"
    users ||--o{ ticket_events : "actor_id"
    location_events ||--o{ ticket_events : "location_id"
    tickets ||--o{ ticket_media : "ticket_id"
    media ||--o{ ticket_media : "media_id"
    tickets ||--o{ customer_acceptances : "ticket_id"
    media ||--o{ customer_acceptances : "signature_media_id"
    tickets ||--o{ payments : "ticket_id"
    users ||--o{ payments : "received_by"
    tickets ||--o{ service_documents : "ticket_id"
    media ||--o{ service_documents : "media_id"
```

## Sales, contracts and stock

```mermaid
erDiagram
    leads {
        uuid tenant_id PK
        uuid id PK
        uuid customer_id
        uuid site_id
        uuid assigned_to
        uuid team_id
        text source
        text requirement
        numeric estimated_value
        char currency
        text stage
        text lost_reason
        timestamptz next_followup_at
        timestamptz won_at
        numeric won_value
    }
    lead_activities {
        uuid tenant_id PK
        uuid id PK
        jsonb details
        uuid lead_id
        uuid actor_id
        text kind
        text note
        uuid location_id
        timestamptz occurred_at
    }
    quotations {
        uuid tenant_id PK
        uuid id PK
        uuid customer_id
        uuid lead_id
        uuid ticket_id
        bigint number
        integer revision
        text status
        date valid_until
        char currency
        numeric total
        uuid pdf_media_id
        timestamptz approved_at
        text approval_evidence
    }
    quotation_lines {
        uuid tenant_id PK
        uuid id PK
        uuid quotation_id
        uuid part_id
        text description
        numeric quantity
        numeric unit_price
        numeric tax_rate
    }
    amc_contracts {
        uuid tenant_id PK
        uuid id PK
        uuid customer_id
        text number
        date starts_on
        date ends_on
        numeric value
        char currency
        jsonb coverage
        text status
    }
    amc_assets {
        uuid tenant_id PK
        uuid id PK
        uuid amc_id
        uuid asset_id
    }
    amc_schedules {
        uuid tenant_id PK
        uuid id PK
        uuid amc_id
        uuid asset_id
        integer interval_months
        date next_due_on
        boolean active
    }
    amc_occurrences {
        uuid tenant_id PK
        uuid id PK
        uuid schedule_id
        date due_on
        uuid ticket_id
    }
    inventory_parts {
        uuid tenant_id PK
        uuid id PK
        text sku
        text name
        text unit
        numeric on_hand
        numeric reserved
        numeric reorder_level
        numeric unit_cost
        numeric sale_price
    }
    stock_movements {
        uuid tenant_id PK
        uuid id PK
        uuid part_id
        uuid ticket_id
        uuid actor_id
        numeric quantity_delta
        numeric unit_cost
        text reason
        uuid client_event_id
    }
    stock_reservations {
        uuid tenant_id PK
        uuid id PK
        uuid part_id
        uuid ticket_id
        numeric quantity
        text status
    }
    vendors {
        uuid tenant_id PK
        uuid id PK
        text name
        text contact
        text address
    }
    rma_cases {
        uuid tenant_id PK
        uuid id PK
        uuid ticket_id
        uuid asset_id
        uuid vendor_id
        text reference
        timestamptz sent_at
        timestamptz expected_at
        timestamptz received_at
        text replacement_serial
        text status
        text notes
    }
    customers ||--o{ leads : "customer_id"
    sites ||--o{ leads : "site_id"
    users ||--o{ leads : "assigned_to"
    teams ||--o{ leads : "team_id"
    leads ||--o{ lead_activities : "lead_id"
    users ||--o{ lead_activities : "actor_id"
    location_events ||--o{ lead_activities : "location_id"
    customers ||--o{ amc_contracts : "customer_id"
    amc_contracts ||--o{ amc_assets : "amc_id"
    assets ||--o{ amc_assets : "asset_id"
    amc_contracts ||--o{ amc_schedules : "amc_id"
    assets ||--o{ amc_schedules : "asset_id"
    amc_schedules ||--o{ amc_occurrences : "schedule_id"
    tickets ||--o{ amc_occurrences : "ticket_id"
    inventory_parts ||--o{ stock_reservations : "part_id"
    tickets ||--o{ stock_reservations : "ticket_id"
    inventory_parts ||--o{ stock_movements : "part_id"
    tickets ||--o{ stock_movements : "ticket_id"
    users ||--o{ stock_movements : "actor_id"
    tickets ||--o{ rma_cases : "ticket_id"
    assets ||--o{ rma_cases : "asset_id"
    vendors ||--o{ rma_cases : "vendor_id"
    customers ||--o{ quotations : "customer_id"
    leads ||--o{ quotations : "lead_id"
    tickets ||--o{ quotations : "ticket_id"
    media ||--o{ quotations : "pdf_media_id"
    quotations ||--o{ quotation_lines : "quotation_id"
    inventory_parts ||--o{ quotation_lines : "part_id"
```

## Operations

```mermaid
erDiagram
    travel_sessions {
        uuid tenant_id PK
        uuid id PK
        uuid user_id
        timestamptz started_at
        timestamptz ended_at
        uuid consent_id
    }
    travel_segments {
        uuid tenant_id PK
        uuid id PK
        uuid user_id
        uuid session_id
        uuid from_location_id
        uuid to_location_id
        numeric distance_km
        text method
        uuid approved_by
        numeric allowance_rate
    }
    notifications {
        uuid tenant_id PK
        uuid id PK
        uuid user_id
        text kind
        text title
        text body
        text entity_type
        uuid entity_id
        text dedupe_key
        timestamptz read_at
    }
    notification_deliveries {
        uuid tenant_id PK
        uuid id PK
        uuid notification_id
        uuid device_id
        text channel
        text provider_reference
        text status
        integer attempts
    }
    outbox {
        uuid tenant_id PK
        uuid id PK
        text event_type
        text aggregate_type
        uuid aggregate_id
        jsonb payload
        text dedupe_key
        timestamptz available_at
        integer attempts
        timestamptz locked_until
        timestamptz delivered_at
        text last_error_code
    }
    report_runs {
        uuid tenant_id PK
        uuid id PK
        timestamptz period_start
        timestamptz period_end
        text timezone
        text kind
        integer revision
        text status
        uuid requested_by
        jsonb recipient_snapshot
        uuid pdf_media_id
        uuid csv_media_id
        timestamptz snapshot_at
        timestamptz sent_at
    }
    deletion_requests {
        uuid tenant_id PK
        uuid id PK
        uuid user_id
        timestamptz requested_at
        timestamptz due_at
        text status
        text retention_explanation
        timestamptz completed_at
    }
    idempotency_keys {
        uuid tenant_id PK
        uuid id PK
        uuid user_id
        uuid key
        text route
        text request_hash
        integer response_status
        jsonb response_body
        timestamptz expires_at
    }
    audit_logs {
        uuid tenant_id PK
        uuid id PK
        uuid actor_id
        text action
        text entity_type
        uuid entity_id
        uuid request_id
        jsonb redacted_changes
        timestamptz occurred_at
    }
    document_sequences {
        uuid tenant_id PK
        uuid id PK
        text kind
        bigint next_value
    }
    users ||--o{ travel_sessions : "user_id"
    consents ||--o{ travel_sessions : "consent_id"
    users ||--o{ travel_segments : "user_id"
    travel_sessions ||--o{ travel_segments : "session_id"
    location_events ||--o{ travel_segments : "from_location_id"
    location_events ||--o{ travel_segments : "to_location_id"
    users ||--o{ travel_segments : "approved_by"
    users ||--o{ notifications : "user_id"
    notifications ||--o{ notification_deliveries : "notification_id"
    devices ||--o{ notification_deliveries : "device_id"
    users ||--o{ report_runs : "requested_by"
    media ||--o{ report_runs : "pdf_media_id"
    media ||--o{ report_runs : "csv_media_id"
    users ||--o{ deletion_requests : "user_id"
    users ||--o{ idempotency_keys : "user_id"
    users ||--o{ audit_logs : "actor_id"
```

## Control plane

```mermaid
erDiagram
    tenants ||--o{ tenant_features : enables
    tenants ||--o{ users : contains
    tenants ||--o{ platform_audit : target
    platform_admins ||--o{ platform_sessions : authenticates
    platform_admins ||--o{ platform_audit : acts
```

## Enforcement boundaries

DDL enforces tenant FKs, immutable identity, RLS, open-attendance uniqueness, basic financial checks, and selected lifecycle invariants. Services must additionally enforce role/assignment permissions, overlapping leave/shift rules, customer/asset/AMC consistency, media ownership/purpose/clean status, legal transitions, OTP proof, active-user quotas and stock ledger balance. These are Phase 2–4 acceptance gates, not claims that the DDL alone enforces all business rules.

Serial numbers are searchable but deliberately not globally unique: incomplete or reused manufacturer serials occur. Confirm duplicate assets within a customer before creating; never merge automatically. Email uniqueness is per tenant. App user UUIDs have meaning only together with tenant UUIDs.

Date-times use timestamptz; business dates and local shift times are explicit. Amounts use decimal and an ISO currency snapshot, never floating point. No cascade deletes: retention/purge jobs delete dependent records in an audited order. A user tombstone can retain nonpersonal identifiers while credentials, profile fields and unneeded linked personal data are erased.

Polymorphic notification/outbox/audit entity IDs are intentionally not FKs; resolve through a fixed type allowlist under the same tenant and authorize the target before displaying. They never grant access. JSONB is limited to snapshots, checklists, redacted events and policy evidence, not core monetary or ownership relationships.
