-- Phase 1 reference DDL. PostgreSQL; fresh database only. Not an applied migration.
-- Execute as migration owner; runtime role must be a different NON-superuser, NOBYPASSRLS.
BEGIN;
CREATE SCHEMA control;
CREATE SCHEMA app;
CREATE TABLE control.tenants (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), name text NOT NULL,
 slug text NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$'),
 status text NOT NULL CHECK (status IN ('ACTIVE','SUSPENDED','CLOSED')),
 timezone text NOT NULL DEFAULT 'Asia/Kolkata', currency char(3) NOT NULL DEFAULT 'INR',
 max_active_employees integer NOT NULL CHECK (max_active_employees > 0),
 storage_quota_bytes bigint NOT NULL CHECK (storage_quota_bytes > 0),
 storage_reserved_bytes bigint NOT NULL DEFAULT 0 CHECK (storage_reserved_bytes >= 0),
 storage_used_bytes bigint NOT NULL DEFAULT 0 CHECK (storage_used_bytes >= 0),
 settings jsonb NOT NULL DEFAULT '{}',
 valid_until timestamptz NOT NULL, report_local_time time NOT NULL DEFAULT '08:00',
 created_at timestamptz NOT NULL DEFAULT now(), version integer NOT NULL DEFAULT 1
);
CREATE TABLE control.tenant_features (
 tenant_id uuid NOT NULL REFERENCES control.tenants(id),
 feature text NOT NULL CHECK (feature IN ('attendance_gps','field_service_tickets','sales_crm','amc_tracker','monthly_email_reports','background_location')),
 enabled boolean NOT NULL DEFAULT false, PRIMARY KEY (tenant_id,feature)
);
CREATE TABLE control.platform_admins (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), email text NOT NULL UNIQUE,
 password_hash text NOT NULL, mfa_secret_ciphertext text NOT NULL,
 active boolean NOT NULL DEFAULT true, token_version integer NOT NULL DEFAULT 1
);
CREATE TABLE control.platform_sessions (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), admin_id uuid NOT NULL REFERENCES control.platform_admins(id),
 token_hash text NOT NULL UNIQUE, expires_at timestamptz NOT NULL, revoked_at timestamptz
);
CREATE TABLE control.platform_audit (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), actor_id uuid NOT NULL REFERENCES control.platform_admins(id),
 target_tenant_id uuid REFERENCES control.tenants(id), action text NOT NULL,
 reason text NOT NULL, request_id uuid NOT NULL, occurred_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX platform_audit_tenant_time ON control.platform_audit(target_tenant_id,occurred_at);
-- Throws rather than silently supplying a global context. SET LOCAL is transaction-scoped.
CREATE FUNCTION app.current_tenant() RETURNS uuid LANGUAGE plpgsql STABLE AS $$
DECLARE v text;
BEGIN
 v := current_setting('app.tenant_id', true);
 IF v IS NULL OR v = '' THEN RAISE EXCEPTION 'tenant context required' USING ERRCODE = '42501'; END IF;
 RETURN v::uuid;
END; $$;

CREATE TABLE app.branches (
  tenant_id uuid NOT NULL REFERENCES control.tenants(id),
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  name text NOT NULL,
  address text NOT NULL,
  lat numeric(9,6) NOT NULL CHECK (lat BETWEEN -90 AND 90),
  lng numeric(9,6) NOT NULL CHECK (lng BETWEEN -180 AND 180),
  radius_m integer NOT NULL CHECK (radius_m BETWEEN 25 AND 5000),
  timezone text NOT NULL DEFAULT 'Asia/Kolkata',
  PRIMARY KEY (tenant_id, id)
);
CREATE INDEX branches_tenant_created ON app.branches(tenant_id,created_at);

CREATE TABLE app.shifts (
  tenant_id uuid NOT NULL REFERENCES control.tenants(id),
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  name text NOT NULL,
  start_local time NOT NULL,
  end_local time NOT NULL,
  end_day_offset smallint NOT NULL CHECK (end_day_offset IN (0,1)),
  grace_minutes integer NOT NULL DEFAULT 15 CHECK (grace_minutes >= 0),
  weekdays smallint[] NOT NULL,
  break_minutes integer NOT NULL DEFAULT 0 CHECK (break_minutes >= 0),
  PRIMARY KEY (tenant_id, id)
);
CREATE INDEX shifts_tenant_created ON app.shifts(tenant_id,created_at);

CREATE TABLE app.users (
  email_verified_at timestamptz,
  tenant_id uuid NOT NULL REFERENCES control.tenants(id),
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  employment_starts_on date NOT NULL DEFAULT CURRENT_DATE,
  employment_ends_on date,
  CHECK (employment_ends_on IS NULL OR employment_ends_on >= employment_starts_on),
  email text NOT NULL,
  phone text,
  display_name text NOT NULL,
  password_hash text NOT NULL,
  role text NOT NULL CHECK (role IN ('COMPANY_ADMIN','DISPATCHER','ENGINEER','SALES')),
  work_mode text NOT NULL CHECK (work_mode IN ('OFFICE','FIELD')),
  active boolean NOT NULL DEFAULT true,
  token_version integer NOT NULL DEFAULT 1,
  branch_id uuid NOT NULL,
  shift_id uuid NOT NULL,
  must_reset_password boolean NOT NULL DEFAULT true,
  mfa_secret_ciphertext text,
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, branch_id) REFERENCES app.branches(tenant_id, id),
  FOREIGN KEY (tenant_id, shift_id) REFERENCES app.shifts(tenant_id, id)
);
CREATE INDEX users_tenant_created ON app.users(tenant_id,created_at);

CREATE TABLE app.shift_assignments (
  tenant_id uuid NOT NULL REFERENCES control.tenants(id),
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  user_id uuid NOT NULL,
  shift_id uuid NOT NULL,
  effective_from date NOT NULL,
  effective_to date,
  CHECK (effective_to IS NULL OR effective_to >= effective_from),
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, user_id) REFERENCES app.users(tenant_id, id),
  FOREIGN KEY (tenant_id, shift_id) REFERENCES app.shifts(tenant_id, id),
  UNIQUE (tenant_id,user_id,effective_from)
);
CREATE INDEX shift_assignments_tenant_created ON app.shift_assignments(tenant_id,created_at);

CREATE TABLE app.holidays (
  tenant_id uuid NOT NULL REFERENCES control.tenants(id),
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  branch_id uuid NOT NULL,
  holiday_date date NOT NULL,
  name text NOT NULL,
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, branch_id) REFERENCES app.branches(tenant_id, id),
  UNIQUE (tenant_id,branch_id,holiday_date)
);
CREATE INDEX holidays_tenant_created ON app.holidays(tenant_id,created_at);

CREATE TABLE app.teams (
  tenant_id uuid NOT NULL REFERENCES control.tenants(id),
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  name text NOT NULL,
  PRIMARY KEY (tenant_id, id),
  UNIQUE (tenant_id,name)
);
CREATE INDEX teams_tenant_created ON app.teams(tenant_id,created_at);

CREATE TABLE app.team_members (
  tenant_id uuid NOT NULL REFERENCES control.tenants(id),
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  team_id uuid NOT NULL,
  user_id uuid NOT NULL,
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, team_id) REFERENCES app.teams(tenant_id, id),
  FOREIGN KEY (tenant_id, user_id) REFERENCES app.users(tenant_id, id),
  UNIQUE (tenant_id,team_id,user_id)
);
CREATE INDEX team_members_tenant_created ON app.team_members(tenant_id,created_at);

CREATE TABLE app.devices (
  tenant_id uuid NOT NULL REFERENCES control.tenants(id),
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  user_id uuid NOT NULL,
  installation_id uuid NOT NULL,
  platform text NOT NULL,
  push_token_ciphertext text,
  last_seen_at timestamptz,
  revoked_at timestamptz,
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, user_id) REFERENCES app.users(tenant_id, id),
  UNIQUE (tenant_id,installation_id)
);
CREATE INDEX devices_tenant_created ON app.devices(tenant_id,created_at);

CREATE TABLE app.auth_sessions (
  tenant_id uuid NOT NULL REFERENCES control.tenants(id),
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  user_id uuid NOT NULL,
  device_id uuid,
  refresh_hash text NOT NULL,
  family_id uuid NOT NULL,
  expires_at timestamptz NOT NULL,
  revoked_at timestamptz,
  last_used_at timestamptz,
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, user_id) REFERENCES app.users(tenant_id, id),
  FOREIGN KEY (tenant_id, device_id) REFERENCES app.devices(tenant_id, id),
  UNIQUE (tenant_id,refresh_hash)
);
CREATE INDEX auth_sessions_tenant_created ON app.auth_sessions(tenant_id,created_at);

CREATE TABLE app.password_tokens (
  tenant_id uuid NOT NULL REFERENCES control.tenants(id),
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  user_id uuid NOT NULL,
  token_hash text NOT NULL,
  purpose text NOT NULL CHECK (purpose IN ('INVITE','RESET')),
  expires_at timestamptz NOT NULL,
  used_at timestamptz,
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, user_id) REFERENCES app.users(tenant_id, id),
  UNIQUE (tenant_id,token_hash)
);
CREATE INDEX password_tokens_tenant_created ON app.password_tokens(tenant_id,created_at);

CREATE TABLE app.consents (
  tenant_id uuid NOT NULL REFERENCES control.tenants(id),
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  user_id uuid NOT NULL,
  purpose text NOT NULL,
  policy_version text NOT NULL,
  granted_at timestamptz NOT NULL,
  revoked_at timestamptz,
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, user_id) REFERENCES app.users(tenant_id, id)
);
CREATE INDEX consents_tenant_created ON app.consents(tenant_id,created_at);

CREATE TABLE app.customers (
  phone_verified_at timestamptz,
  tenant_id uuid NOT NULL REFERENCES control.tenants(id),
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  name text NOT NULL,
  company_name text,
  phone text NOT NULL,
  email text,
  gstin varchar(15),
  billing_address text,
  archived_at timestamptz,
  PRIMARY KEY (tenant_id, id)
);
CREATE INDEX customers_tenant_created ON app.customers(tenant_id,created_at);

CREATE TABLE app.sites (
  tenant_id uuid NOT NULL REFERENCES control.tenants(id),
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  customer_id uuid NOT NULL,
  name text NOT NULL,
  address text NOT NULL,
  lat numeric(9,6) CHECK (lat BETWEEN -90 AND 90),
  lng numeric(9,6) CHECK (lng BETWEEN -180 AND 180),
  radius_m integer NOT NULL DEFAULT 200 CHECK (radius_m > 0),
  coordinates_verified boolean NOT NULL DEFAULT false,
  CHECK ((lat IS NULL) = (lng IS NULL)),
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, customer_id) REFERENCES app.customers(tenant_id, id),
  UNIQUE (tenant_id,id,customer_id)
);
CREATE INDEX sites_tenant_created ON app.sites(tenant_id,created_at);

CREATE TABLE app.assets (
  tenant_id uuid NOT NULL REFERENCES control.tenants(id),
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  customer_id uuid NOT NULL,
  site_id uuid,
  category text NOT NULL,
  brand text,
  model text,
  serial_number text,
  warranty_until date,
  purchase_date date,
  archived_at timestamptz,
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, customer_id) REFERENCES app.customers(tenant_id, id),
  FOREIGN KEY (tenant_id, site_id) REFERENCES app.sites(tenant_id, id),
  UNIQUE (tenant_id,id,customer_id),
  FOREIGN KEY (tenant_id,site_id,customer_id) REFERENCES app.sites(tenant_id,id,customer_id)
);
CREATE INDEX assets_tenant_created ON app.assets(tenant_id,created_at);

CREATE TABLE app.media (
  tenant_id uuid NOT NULL REFERENCES control.tenants(id),
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  uploaded_by uuid NOT NULL,
  object_key text NOT NULL,
  content_type text NOT NULL,
  bytes bigint NOT NULL CHECK (bytes > 0),
  sha256 text NOT NULL,
  state text NOT NULL CHECK (state IN ('PENDING','SCANNING','CLEAN','REJECTED','DELETED')),
  purpose text NOT NULL,
  expires_at timestamptz,
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, uploaded_by) REFERENCES app.users(tenant_id, id),
  UNIQUE (tenant_id,object_key)
);
CREATE INDEX media_tenant_created ON app.media(tenant_id,created_at);

CREATE TABLE app.location_events (
  tenant_id uuid NOT NULL REFERENCES control.tenants(id),
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  redacted_at timestamptz,
  user_id uuid NOT NULL,
  device_id uuid,
  client_event_id uuid NOT NULL,
  lat numeric(9,6) CHECK (lat BETWEEN -90 AND 90),
  lng numeric(9,6) CHECK (lng BETWEEN -180 AND 180),
  accuracy_m numeric(10,2) CHECK (accuracy_m >= 0),
  captured_at timestamptz NOT NULL,
  received_at timestamptz NOT NULL DEFAULT now(),
  purpose text NOT NULL,
  address text,
  mock_signal boolean,
  risk_flags jsonb NOT NULL DEFAULT '[]',
  verification text NOT NULL CHECK (verification IN ('ACCEPTED','REVIEW','REJECTED')),
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, user_id) REFERENCES app.users(tenant_id, id),
  FOREIGN KEY (tenant_id, device_id) REFERENCES app.devices(tenant_id, id),
  UNIQUE (tenant_id,user_id,client_event_id),
  CHECK ((redacted_at IS NULL AND lat IS NOT NULL AND lng IS NOT NULL AND accuracy_m IS NOT NULL) OR (redacted_at IS NOT NULL AND lat IS NULL AND lng IS NULL AND accuracy_m IS NULL AND address IS NULL))
);
CREATE INDEX location_events_tenant_created ON app.location_events(tenant_id,created_at);

CREATE TABLE app.attendance (
  tenant_id uuid NOT NULL REFERENCES control.tenants(id),
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  user_id uuid NOT NULL,
  shift_id uuid NOT NULL,
  shift_date date NOT NULL,
  scheduled_start timestamptz NOT NULL,
  scheduled_end timestamptz NOT NULL,
  grace_minutes integer NOT NULL,
  work_mode text NOT NULL CHECK (work_mode IN ('OFFICE','FIELD')),
  punch_in timestamptz NOT NULL,
  punch_out timestamptz,
  in_location_id uuid NOT NULL,
  out_location_id uuid,
  selfie_media_id uuid,
  status text NOT NULL CHECK (status IN ('OPEN','COMPLETE','INCOMPLETE','REVIEW')),
  late_minutes integer NOT NULL DEFAULT 0 CHECK (late_minutes >= 0),
  approved_overtime_minutes integer NOT NULL DEFAULT 0 CHECK (approved_overtime_minutes >= 0),
  CHECK (punch_out IS NULL OR punch_out >= punch_in),
  CHECK (scheduled_end > scheduled_start),
  CHECK ((punch_out IS NULL) = (out_location_id IS NULL)),
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, user_id) REFERENCES app.users(tenant_id, id),
  FOREIGN KEY (tenant_id, shift_id) REFERENCES app.shifts(tenant_id, id),
  FOREIGN KEY (tenant_id, in_location_id) REFERENCES app.location_events(tenant_id, id),
  FOREIGN KEY (tenant_id, out_location_id) REFERENCES app.location_events(tenant_id, id),
  FOREIGN KEY (tenant_id, selfie_media_id) REFERENCES app.media(tenant_id, id),
  UNIQUE (tenant_id,user_id,shift_date)
);
CREATE INDEX attendance_tenant_created ON app.attendance(tenant_id,created_at);

CREATE TABLE app.attendance_corrections (
  tenant_id uuid NOT NULL REFERENCES control.tenants(id),
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  attendance_id uuid NOT NULL,
  requested_by uuid NOT NULL,
  reviewed_by uuid,
  reason text NOT NULL,
  proposed_values jsonb NOT NULL,
  status text NOT NULL CHECK (status IN ('PENDING','APPROVED','REJECTED')),
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, attendance_id) REFERENCES app.attendance(tenant_id, id),
  FOREIGN KEY (tenant_id, requested_by) REFERENCES app.users(tenant_id, id),
  FOREIGN KEY (tenant_id, reviewed_by) REFERENCES app.users(tenant_id, id)
);
CREATE INDEX attendance_corrections_tenant_created ON app.attendance_corrections(tenant_id,created_at);

CREATE TABLE app.leave_requests (
  tenant_id uuid NOT NULL REFERENCES control.tenants(id),
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  user_id uuid NOT NULL,
  starts_at timestamptz NOT NULL,
  ends_at timestamptz NOT NULL,
  kind text NOT NULL CHECK (kind IN ('HALF_DAY','ON_DUTY','SICK','ANNUAL','PERMISSION')),
  reason text NOT NULL,
  status text NOT NULL CHECK (status IN ('PENDING','APPROVED','REJECTED','CANCELLED')),
  reviewed_by uuid,
  reviewed_at timestamptz,
  CHECK (ends_at > starts_at),
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, user_id) REFERENCES app.users(tenant_id, id),
  FOREIGN KEY (tenant_id, reviewed_by) REFERENCES app.users(tenant_id, id)
);
CREATE INDEX leave_requests_tenant_created ON app.leave_requests(tenant_id,created_at);

CREATE TABLE app.leads (
  tenant_id uuid NOT NULL REFERENCES control.tenants(id),
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  customer_id uuid NOT NULL,
  site_id uuid,
  assigned_to uuid,
  team_id uuid,
  source text NOT NULL CHECK (source IN ('WALK_IN','PHONE','WHATSAPP','INDIAMART_WEB','REFERRAL','FIELD_VISIT')),
  requirement text NOT NULL,
  estimated_value numeric(14,2) NOT NULL DEFAULT 0 CHECK (estimated_value >= 0),
  currency char(3) NOT NULL DEFAULT 'INR',
  stage text NOT NULL CHECK (stage IN ('NEW','CONTACTED','SURVEY_DONE','QUOTE_SENT','NEGOTIATION','WON','LOST')),
  lost_reason text,
  next_followup_at timestamptz,
  won_at timestamptz,
  won_value numeric(14,2) CHECK (won_value >= 0),
  CHECK (stage <> 'LOST' OR length(trim(lost_reason)) > 0 AND lost_reason IS NOT NULL),
  CHECK (stage <> 'WON' OR (won_at IS NOT NULL AND won_value IS NOT NULL)),
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, customer_id) REFERENCES app.customers(tenant_id, id),
  FOREIGN KEY (tenant_id, site_id) REFERENCES app.sites(tenant_id, id),
  FOREIGN KEY (tenant_id, assigned_to) REFERENCES app.users(tenant_id, id),
  FOREIGN KEY (tenant_id, team_id) REFERENCES app.teams(tenant_id, id),
  FOREIGN KEY (tenant_id,site_id,customer_id) REFERENCES app.sites(tenant_id,id,customer_id)
);
CREATE INDEX leads_tenant_created ON app.leads(tenant_id,created_at);

CREATE TABLE app.lead_activities (
  tenant_id uuid NOT NULL REFERENCES control.tenants(id),
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  details jsonb NOT NULL DEFAULT '{}',
  lead_id uuid NOT NULL,
  actor_id uuid NOT NULL,
  kind text NOT NULL,
  note text NOT NULL,
  location_id uuid,
  occurred_at timestamptz NOT NULL,
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, lead_id) REFERENCES app.leads(tenant_id, id),
  FOREIGN KEY (tenant_id, actor_id) REFERENCES app.users(tenant_id, id),
  FOREIGN KEY (tenant_id, location_id) REFERENCES app.location_events(tenant_id, id)
);
CREATE INDEX lead_activities_tenant_created ON app.lead_activities(tenant_id,created_at);

CREATE TABLE app.amc_contracts (
  tenant_id uuid NOT NULL REFERENCES control.tenants(id),
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  customer_id uuid NOT NULL,
  number text NOT NULL,
  starts_on date NOT NULL,
  ends_on date NOT NULL,
  value numeric(14,2) NOT NULL CHECK (value >= 0),
  currency char(3) NOT NULL DEFAULT 'INR',
  coverage jsonb NOT NULL,
  status text NOT NULL CHECK (status IN ('DRAFT','ACTIVE','EXPIRED','CANCELLED')),
  CHECK (ends_on >= starts_on),
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, customer_id) REFERENCES app.customers(tenant_id, id),
  UNIQUE (tenant_id,number)
);
CREATE INDEX amc_contracts_tenant_created ON app.amc_contracts(tenant_id,created_at);

CREATE TABLE app.amc_assets (
  tenant_id uuid NOT NULL REFERENCES control.tenants(id),
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  amc_id uuid NOT NULL,
  asset_id uuid NOT NULL,
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, amc_id) REFERENCES app.amc_contracts(tenant_id, id),
  FOREIGN KEY (tenant_id, asset_id) REFERENCES app.assets(tenant_id, id),
  UNIQUE (tenant_id,amc_id,asset_id)
);
CREATE INDEX amc_assets_tenant_created ON app.amc_assets(tenant_id,created_at);

CREATE TABLE app.amc_schedules (
  tenant_id uuid NOT NULL REFERENCES control.tenants(id),
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  amc_id uuid NOT NULL,
  asset_id uuid NOT NULL,
  interval_months integer NOT NULL CHECK (interval_months > 0),
  next_due_on date NOT NULL,
  active boolean NOT NULL DEFAULT true,
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, amc_id) REFERENCES app.amc_contracts(tenant_id, id),
  FOREIGN KEY (tenant_id, asset_id) REFERENCES app.assets(tenant_id, id)
);
CREATE INDEX amc_schedules_tenant_created ON app.amc_schedules(tenant_id,created_at);

CREATE TABLE app.tickets (
  tenant_id uuid NOT NULL REFERENCES control.tenants(id),
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  diagnostic_tags text[] NOT NULL DEFAULT '{}',
  number bigint NOT NULL,
  customer_id uuid NOT NULL,
  site_id uuid,
  asset_id uuid,
  assigned_to uuid,
  lead_id uuid,
  amc_id uuid,
  service_mode text NOT NULL CHECK (service_mode IN ('WALK_IN','ON_SITE')),
  reported_issue text NOT NULL,
  physical_condition jsonb NOT NULL,
  coverage_snapshot jsonb NOT NULL,
  estimated_cost numeric(14,2) NOT NULL DEFAULT 0 CHECK (estimated_cost >= 0),
  currency char(3) NOT NULL DEFAULT 'INR',
  status text NOT NULL CHECK (status IN ('NEW','ASSIGNED','EN_ROUTE','ON_SITE','IN_PROGRESS','WAITING_SPARES','WAITING_APPROVAL','RESOLVED','COMPLETED','CANCELLED')),
  priority text NOT NULL,
  sla_due_at timestamptz NOT NULL,
  sla_policy_snapshot jsonb NOT NULL,
  sla_paused_seconds integer NOT NULL DEFAULT 0 CHECK (sla_paused_seconds >= 0),
  resolution_notes text,
  completed_at timestamptz,
  reopened_count integer NOT NULL DEFAULT 0,
  checkout_location_id uuid,
  completion_photo_id uuid,
  signature_media_id uuid,
  customer_accepted_at timestamptz,
  payment_mode text CHECK (payment_mode IN ('CASH','UPI','CREDIT','WARRANTY')),
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, customer_id) REFERENCES app.customers(tenant_id, id),
  FOREIGN KEY (tenant_id, site_id) REFERENCES app.sites(tenant_id, id),
  FOREIGN KEY (tenant_id, asset_id) REFERENCES app.assets(tenant_id, id),
  FOREIGN KEY (tenant_id, assigned_to) REFERENCES app.users(tenant_id, id),
  FOREIGN KEY (tenant_id, lead_id) REFERENCES app.leads(tenant_id, id),
  FOREIGN KEY (tenant_id, amc_id) REFERENCES app.amc_contracts(tenant_id, id),
  FOREIGN KEY (tenant_id, checkout_location_id) REFERENCES app.location_events(tenant_id, id),
  FOREIGN KEY (tenant_id, completion_photo_id) REFERENCES app.media(tenant_id, id),
  FOREIGN KEY (tenant_id, signature_media_id) REFERENCES app.media(tenant_id, id),
  UNIQUE (tenant_id,number),
  UNIQUE (tenant_id,lead_id),
  FOREIGN KEY (tenant_id,asset_id,customer_id) REFERENCES app.assets(tenant_id,id,customer_id),
  FOREIGN KEY (tenant_id,site_id,customer_id) REFERENCES app.sites(tenant_id,id,customer_id),
  CHECK (service_mode <> 'ON_SITE' OR site_id IS NOT NULL),
  CHECK (status <> 'COMPLETED' OR (completed_at IS NOT NULL AND resolution_notes IS NOT NULL AND length(trim(resolution_notes)) > 0 AND completion_photo_id IS NOT NULL AND customer_accepted_at IS NOT NULL AND payment_mode IS NOT NULL AND (service_mode <> 'ON_SITE' OR checkout_location_id IS NOT NULL)))
);
CREATE INDEX tickets_tenant_created ON app.tickets(tenant_id,created_at);

CREATE TABLE app.amc_occurrences (
  tenant_id uuid NOT NULL REFERENCES control.tenants(id),
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  schedule_id uuid NOT NULL,
  due_on date NOT NULL,
  ticket_id uuid NOT NULL,
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, schedule_id) REFERENCES app.amc_schedules(tenant_id, id),
  FOREIGN KEY (tenant_id, ticket_id) REFERENCES app.tickets(tenant_id, id),
  UNIQUE (tenant_id,schedule_id,due_on)
);
CREATE INDEX amc_occurrences_tenant_created ON app.amc_occurrences(tenant_id,created_at);

CREATE TABLE app.ticket_events (
  tenant_id uuid NOT NULL REFERENCES control.tenants(id),
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  details jsonb NOT NULL DEFAULT '{}',
  ticket_id uuid NOT NULL,
  actor_id uuid,
  from_status text,
  to_status text NOT NULL,
  note text NOT NULL,
  location_id uuid,
  occurred_at timestamptz NOT NULL,
  sla_pause_started_at timestamptz,
  sla_pause_ended_at timestamptz,
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, ticket_id) REFERENCES app.tickets(tenant_id, id),
  FOREIGN KEY (tenant_id, actor_id) REFERENCES app.users(tenant_id, id),
  FOREIGN KEY (tenant_id, location_id) REFERENCES app.location_events(tenant_id, id)
);
CREATE INDEX ticket_events_tenant_created ON app.ticket_events(tenant_id,created_at);

CREATE TABLE app.ticket_media (
  tenant_id uuid NOT NULL REFERENCES control.tenants(id),
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  ticket_id uuid NOT NULL,
  media_id uuid NOT NULL,
  kind text NOT NULL CHECK (kind IN ('BEFORE','AFTER','SIGNATURE','INTAKE')),
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, ticket_id) REFERENCES app.tickets(tenant_id, id),
  FOREIGN KEY (tenant_id, media_id) REFERENCES app.media(tenant_id, id),
  UNIQUE (tenant_id,ticket_id,media_id)
);
CREATE INDEX ticket_media_tenant_created ON app.ticket_media(tenant_id,created_at);

CREATE TABLE app.customer_acceptances (
  tenant_id uuid NOT NULL REFERENCES control.tenants(id),
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  ticket_id uuid NOT NULL,
  method text NOT NULL CHECK (method IN ('OTP','SIGNATURE')),
  otp_hash text,
  signature_media_id uuid,
  expires_at timestamptz,
  attempts integer NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 5),
  verified_at timestamptz,
  contact_snapshot text NOT NULL,
  resolution_version integer NOT NULL,
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, ticket_id) REFERENCES app.tickets(tenant_id, id),
  FOREIGN KEY (tenant_id, signature_media_id) REFERENCES app.media(tenant_id, id),
  CHECK ((method = 'OTP' AND otp_hash IS NOT NULL AND expires_at IS NOT NULL) OR (method = 'SIGNATURE' AND signature_media_id IS NOT NULL))
);
CREATE INDEX customer_acceptances_tenant_created ON app.customer_acceptances(tenant_id,created_at);

CREATE TABLE app.inventory_parts (
  tenant_id uuid NOT NULL REFERENCES control.tenants(id),
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  sku text NOT NULL,
  name text NOT NULL,
  unit text NOT NULL,
  on_hand numeric(14,3) NOT NULL DEFAULT 0 CHECK (on_hand >= 0),
  reserved numeric(14,3) NOT NULL DEFAULT 0 CHECK (reserved >= 0 AND reserved <= on_hand),
  reorder_level numeric(14,3) NOT NULL DEFAULT 0 CHECK (reorder_level >= 0),
  unit_cost numeric(14,2) NOT NULL CHECK (unit_cost >= 0),
  sale_price numeric(14,2) NOT NULL CHECK (sale_price >= 0),
  PRIMARY KEY (tenant_id, id),
  UNIQUE (tenant_id,sku)
);
CREATE INDEX inventory_parts_tenant_created ON app.inventory_parts(tenant_id,created_at);

CREATE TABLE app.stock_reservations (
  tenant_id uuid NOT NULL REFERENCES control.tenants(id),
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  part_id uuid NOT NULL,
  ticket_id uuid NOT NULL,
  quantity numeric(14,3) NOT NULL CHECK (quantity > 0),
  status text NOT NULL CHECK (status IN ('RESERVED','CONSUMED','RELEASED')),
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, part_id) REFERENCES app.inventory_parts(tenant_id, id),
  FOREIGN KEY (tenant_id, ticket_id) REFERENCES app.tickets(tenant_id, id)
);
CREATE INDEX stock_reservations_tenant_created ON app.stock_reservations(tenant_id,created_at);

CREATE TABLE app.stock_movements (
  tenant_id uuid NOT NULL REFERENCES control.tenants(id),
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  part_id uuid NOT NULL,
  ticket_id uuid,
  actor_id uuid NOT NULL,
  quantity_delta numeric(14,3) NOT NULL CHECK (quantity_delta <> 0),
  unit_cost numeric(14,2) NOT NULL CHECK (unit_cost >= 0),
  reason text NOT NULL,
  client_event_id uuid NOT NULL,
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, part_id) REFERENCES app.inventory_parts(tenant_id, id),
  FOREIGN KEY (tenant_id, ticket_id) REFERENCES app.tickets(tenant_id, id),
  FOREIGN KEY (tenant_id, actor_id) REFERENCES app.users(tenant_id, id),
  UNIQUE (tenant_id,client_event_id)
);
CREATE INDEX stock_movements_tenant_created ON app.stock_movements(tenant_id,created_at);

CREATE TABLE app.vendors (
  tenant_id uuid NOT NULL REFERENCES control.tenants(id),
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  name text NOT NULL,
  contact text NOT NULL,
  address text,
  PRIMARY KEY (tenant_id, id)
);
CREATE INDEX vendors_tenant_created ON app.vendors(tenant_id,created_at);

CREATE TABLE app.rma_cases (
  tenant_id uuid NOT NULL REFERENCES control.tenants(id),
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  ticket_id uuid NOT NULL,
  asset_id uuid NOT NULL,
  vendor_id uuid NOT NULL,
  reference text NOT NULL,
  sent_at timestamptz,
  expected_at timestamptz,
  received_at timestamptz,
  replacement_serial text,
  status text NOT NULL CHECK (status IN ('PENDING','SENT','RECEIVED','REJECTED','CLOSED')),
  notes text,
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, ticket_id) REFERENCES app.tickets(tenant_id, id),
  FOREIGN KEY (tenant_id, asset_id) REFERENCES app.assets(tenant_id, id),
  FOREIGN KEY (tenant_id, vendor_id) REFERENCES app.vendors(tenant_id, id),
  UNIQUE (tenant_id,vendor_id,reference)
);
CREATE INDEX rma_cases_tenant_created ON app.rma_cases(tenant_id,created_at);

CREATE TABLE app.quotations (
  tenant_id uuid NOT NULL REFERENCES control.tenants(id),
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  customer_id uuid NOT NULL,
  lead_id uuid,
  ticket_id uuid,
  number bigint NOT NULL,
  revision integer NOT NULL CHECK (revision > 0),
  status text NOT NULL CHECK (status IN ('DRAFT','SENT','ACCEPTED','REJECTED','EXPIRED')),
  valid_until date NOT NULL,
  currency char(3) NOT NULL DEFAULT 'INR',
  total numeric(14,2) NOT NULL CHECK (total >= 0),
  pdf_media_id uuid,
  approved_at timestamptz,
  approval_evidence text,
  CHECK (num_nonnulls(lead_id,ticket_id) = 1),
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, customer_id) REFERENCES app.customers(tenant_id, id),
  FOREIGN KEY (tenant_id, lead_id) REFERENCES app.leads(tenant_id, id),
  FOREIGN KEY (tenant_id, ticket_id) REFERENCES app.tickets(tenant_id, id),
  FOREIGN KEY (tenant_id, pdf_media_id) REFERENCES app.media(tenant_id, id),
  UNIQUE (tenant_id,number,revision)
);
CREATE INDEX quotations_tenant_created ON app.quotations(tenant_id,created_at);

CREATE TABLE app.quotation_lines (
  tenant_id uuid NOT NULL REFERENCES control.tenants(id),
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  quotation_id uuid NOT NULL,
  part_id uuid,
  description text NOT NULL,
  quantity numeric(14,3) NOT NULL CHECK (quantity > 0),
  unit_price numeric(14,2) NOT NULL CHECK (unit_price >= 0),
  tax_rate numeric(5,2) NOT NULL CHECK (tax_rate BETWEEN 0 AND 100),
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, quotation_id) REFERENCES app.quotations(tenant_id, id),
  FOREIGN KEY (tenant_id, part_id) REFERENCES app.inventory_parts(tenant_id, id)
);
CREATE INDEX quotation_lines_tenant_created ON app.quotation_lines(tenant_id,created_at);

CREATE TABLE app.payments (
  tenant_id uuid NOT NULL REFERENCES control.tenants(id),
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  verified_at timestamptz,
  reversed_at timestamptz,
  reversal_reason text,
  ticket_id uuid NOT NULL,
  received_by uuid NOT NULL,
  amount numeric(14,2) NOT NULL CHECK (amount > 0),
  currency char(3) NOT NULL DEFAULT 'INR',
  mode text NOT NULL CHECK (mode IN ('CASH','UPI')),
  reference text,
  received_at timestamptz NOT NULL,
  status text NOT NULL CHECK (status IN ('RECORDED','VERIFIED','REVERSED')),
  client_event_id uuid NOT NULL,
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, ticket_id) REFERENCES app.tickets(tenant_id, id),
  FOREIGN KEY (tenant_id, received_by) REFERENCES app.users(tenant_id, id),
  UNIQUE (tenant_id,client_event_id)
);
CREATE INDEX payments_tenant_created ON app.payments(tenant_id,created_at);

CREATE TABLE app.service_documents (
  tenant_id uuid NOT NULL REFERENCES control.tenants(id),
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  ticket_id uuid NOT NULL,
  kind text NOT NULL CHECK (kind IN ('GATE_PASS','INTAKE_RECEIPT','SERVICE_RECEIPT')),
  number bigint NOT NULL,
  media_id uuid NOT NULL,
  snapshot jsonb NOT NULL,
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, ticket_id) REFERENCES app.tickets(tenant_id, id),
  FOREIGN KEY (tenant_id, media_id) REFERENCES app.media(tenant_id, id),
  UNIQUE (tenant_id,kind,number)
);
CREATE INDEX service_documents_tenant_created ON app.service_documents(tenant_id,created_at);

CREATE TABLE app.travel_sessions (
  tenant_id uuid NOT NULL REFERENCES control.tenants(id),
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  user_id uuid NOT NULL,
  started_at timestamptz NOT NULL,
  ended_at timestamptz,
  consent_id uuid NOT NULL,
  CHECK (ended_at IS NULL OR ended_at >= started_at),
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, user_id) REFERENCES app.users(tenant_id, id),
  FOREIGN KEY (tenant_id, consent_id) REFERENCES app.consents(tenant_id, id)
);
CREATE INDEX travel_sessions_tenant_created ON app.travel_sessions(tenant_id,created_at);

CREATE TABLE app.travel_segments (
  tenant_id uuid NOT NULL REFERENCES control.tenants(id),
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  user_id uuid NOT NULL,
  session_id uuid,
  from_location_id uuid NOT NULL,
  to_location_id uuid NOT NULL,
  distance_km numeric(12,3) NOT NULL CHECK (distance_km >= 0),
  method text NOT NULL CHECK (method IN ('STRAIGHT_LINE','ROUTED_ESTIMATE','GPS_TRACE','APPROVED_MANUAL')),
  approved_by uuid,
  allowance_rate numeric(10,2) CHECK (allowance_rate >= 0),
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, user_id) REFERENCES app.users(tenant_id, id),
  FOREIGN KEY (tenant_id, session_id) REFERENCES app.travel_sessions(tenant_id, id),
  FOREIGN KEY (tenant_id, from_location_id) REFERENCES app.location_events(tenant_id, id),
  FOREIGN KEY (tenant_id, to_location_id) REFERENCES app.location_events(tenant_id, id),
  FOREIGN KEY (tenant_id, approved_by) REFERENCES app.users(tenant_id, id),
  UNIQUE (tenant_id,from_location_id,to_location_id,method)
);
CREATE INDEX travel_segments_tenant_created ON app.travel_segments(tenant_id,created_at);

CREATE TABLE app.notifications (
  tenant_id uuid NOT NULL REFERENCES control.tenants(id),
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  user_id uuid NOT NULL,
  kind text NOT NULL,
  title text NOT NULL,
  body text NOT NULL,
  entity_type text,
  entity_id uuid,
  dedupe_key text NOT NULL,
  read_at timestamptz,
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, user_id) REFERENCES app.users(tenant_id, id),
  UNIQUE (tenant_id,user_id,dedupe_key)
);
CREATE INDEX notifications_tenant_created ON app.notifications(tenant_id,created_at);

CREATE TABLE app.outbox (
  tenant_id uuid NOT NULL REFERENCES control.tenants(id),
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  event_type text NOT NULL,
  aggregate_type text NOT NULL,
  aggregate_id uuid NOT NULL,
  payload jsonb NOT NULL,
  dedupe_key text NOT NULL,
  available_at timestamptz NOT NULL,
  attempts integer NOT NULL DEFAULT 0,
  locked_until timestamptz,
  delivered_at timestamptz,
  last_error_code text,
  PRIMARY KEY (tenant_id, id),
  UNIQUE (tenant_id,dedupe_key)
);
CREATE INDEX outbox_tenant_created ON app.outbox(tenant_id,created_at);

CREATE TABLE app.notification_deliveries (
  tenant_id uuid NOT NULL REFERENCES control.tenants(id),
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  notification_id uuid NOT NULL,
  device_id uuid,
  channel text NOT NULL,
  provider_reference text,
  status text NOT NULL CHECK (status IN ('QUEUED','SENT','FAILED')),
  attempts integer NOT NULL DEFAULT 0,
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, notification_id) REFERENCES app.notifications(tenant_id, id),
  FOREIGN KEY (tenant_id, device_id) REFERENCES app.devices(tenant_id, id)
);
CREATE INDEX notification_deliveries_tenant_created ON app.notification_deliveries(tenant_id,created_at);

CREATE TABLE app.report_preferences (
  tenant_id uuid NOT NULL REFERENCES control.tenants(id),
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  user_id uuid NOT NULL,
  email_enabled boolean NOT NULL DEFAULT true,
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, user_id) REFERENCES app.users(tenant_id, id),
  UNIQUE (tenant_id,user_id)
);
CREATE INDEX report_preferences_tenant_created ON app.report_preferences(tenant_id,created_at);

CREATE TABLE app.report_runs (
  tenant_id uuid NOT NULL REFERENCES control.tenants(id),
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  period_start timestamptz NOT NULL,
  period_end timestamptz NOT NULL,
  timezone text NOT NULL,
  kind text NOT NULL,
  revision integer NOT NULL DEFAULT 1,
  status text NOT NULL CHECK (status IN ('QUEUED','RUNNING','READY','SENT','FAILED')),
  requested_by uuid,
  recipient_snapshot jsonb NOT NULL,
  pdf_media_id uuid,
  csv_media_id uuid,
  snapshot_at timestamptz,
  sent_at timestamptz,
  CHECK (period_end > period_start),
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, requested_by) REFERENCES app.users(tenant_id, id),
  FOREIGN KEY (tenant_id, pdf_media_id) REFERENCES app.media(tenant_id, id),
  FOREIGN KEY (tenant_id, csv_media_id) REFERENCES app.media(tenant_id, id),
  UNIQUE (tenant_id,kind,period_start,period_end,revision)
);
CREATE INDEX report_runs_tenant_created ON app.report_runs(tenant_id,created_at);

CREATE TABLE app.deletion_requests (
  tenant_id uuid NOT NULL REFERENCES control.tenants(id),
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  user_id uuid NOT NULL,
  requested_at timestamptz NOT NULL,
  due_at timestamptz NOT NULL,
  status text NOT NULL CHECK (status IN ('RECEIVED','VERIFIED','PROCESSING','COMPLETED','RETAINED_PARTIALLY')),
  retention_explanation text,
  completed_at timestamptz,
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, user_id) REFERENCES app.users(tenant_id, id)
);
CREATE INDEX deletion_requests_tenant_created ON app.deletion_requests(tenant_id,created_at);

CREATE TABLE app.idempotency_keys (
  tenant_id uuid NOT NULL REFERENCES control.tenants(id),
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  user_id uuid NOT NULL,
  key uuid NOT NULL,
  route text NOT NULL,
  request_hash text NOT NULL,
  response_status integer,
  response_body jsonb,
  expires_at timestamptz NOT NULL,
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, user_id) REFERENCES app.users(tenant_id, id),
  UNIQUE (tenant_id,user_id,route,key)
);
CREATE INDEX idempotency_keys_tenant_created ON app.idempotency_keys(tenant_id,created_at);

CREATE TABLE app.audit_logs (
  tenant_id uuid NOT NULL REFERENCES control.tenants(id),
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  actor_id uuid,
  action text NOT NULL,
  entity_type text NOT NULL,
  entity_id uuid,
  request_id uuid NOT NULL,
  redacted_changes jsonb NOT NULL,
  occurred_at timestamptz NOT NULL,
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, actor_id) REFERENCES app.users(tenant_id, id)
);
CREATE INDEX audit_logs_tenant_created ON app.audit_logs(tenant_id,created_at);

CREATE TABLE app.document_sequences (
  tenant_id uuid NOT NULL REFERENCES control.tenants(id),
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  kind text NOT NULL,
  next_value bigint NOT NULL CHECK (next_value > 0),
  PRIMARY KEY (tenant_id, id),
  UNIQUE (tenant_id,kind)
);
CREATE INDEX document_sequences_tenant_created ON app.document_sequences(tenant_id,created_at);
CREATE INDEX users_branch_id_idx ON app.users(tenant_id,branch_id);
CREATE INDEX users_shift_id_idx ON app.users(tenant_id,shift_id);
CREATE INDEX shift_assignments_user_id_idx ON app.shift_assignments(tenant_id,user_id);
CREATE INDEX shift_assignments_shift_id_idx ON app.shift_assignments(tenant_id,shift_id);
CREATE INDEX holidays_branch_id_idx ON app.holidays(tenant_id,branch_id);
CREATE INDEX team_members_team_id_idx ON app.team_members(tenant_id,team_id);
CREATE INDEX team_members_user_id_idx ON app.team_members(tenant_id,user_id);
CREATE INDEX devices_user_id_idx ON app.devices(tenant_id,user_id);
CREATE INDEX auth_sessions_user_id_idx ON app.auth_sessions(tenant_id,user_id);
CREATE INDEX auth_sessions_device_id_idx ON app.auth_sessions(tenant_id,device_id);
CREATE INDEX password_tokens_user_id_idx ON app.password_tokens(tenant_id,user_id);
CREATE INDEX consents_user_id_idx ON app.consents(tenant_id,user_id);
CREATE INDEX sites_customer_id_idx ON app.sites(tenant_id,customer_id);
CREATE INDEX assets_customer_id_idx ON app.assets(tenant_id,customer_id);
CREATE INDEX assets_site_id_idx ON app.assets(tenant_id,site_id);
CREATE INDEX media_uploaded_by_idx ON app.media(tenant_id,uploaded_by);
CREATE INDEX location_events_user_id_idx ON app.location_events(tenant_id,user_id);
CREATE INDEX location_events_device_id_idx ON app.location_events(tenant_id,device_id);
CREATE INDEX attendance_user_id_idx ON app.attendance(tenant_id,user_id);
CREATE INDEX attendance_shift_id_idx ON app.attendance(tenant_id,shift_id);
CREATE INDEX attendance_in_location_id_idx ON app.attendance(tenant_id,in_location_id);
CREATE INDEX attendance_out_location_id_idx ON app.attendance(tenant_id,out_location_id);
CREATE INDEX attendance_selfie_media_id_idx ON app.attendance(tenant_id,selfie_media_id);
CREATE INDEX attendance_corrections_attendance_id_idx ON app.attendance_corrections(tenant_id,attendance_id);
CREATE INDEX attendance_corrections_requested_by_idx ON app.attendance_corrections(tenant_id,requested_by);
CREATE INDEX attendance_corrections_reviewed_by_idx ON app.attendance_corrections(tenant_id,reviewed_by);
CREATE INDEX leave_requests_user_id_idx ON app.leave_requests(tenant_id,user_id);
CREATE INDEX leave_requests_reviewed_by_idx ON app.leave_requests(tenant_id,reviewed_by);
CREATE INDEX leads_customer_id_idx ON app.leads(tenant_id,customer_id);
CREATE INDEX leads_site_id_idx ON app.leads(tenant_id,site_id);
CREATE INDEX leads_assigned_to_idx ON app.leads(tenant_id,assigned_to);
CREATE INDEX leads_team_id_idx ON app.leads(tenant_id,team_id);
CREATE INDEX lead_activities_lead_id_idx ON app.lead_activities(tenant_id,lead_id);
CREATE INDEX lead_activities_actor_id_idx ON app.lead_activities(tenant_id,actor_id);
CREATE INDEX lead_activities_location_id_idx ON app.lead_activities(tenant_id,location_id);
CREATE INDEX amc_contracts_customer_id_idx ON app.amc_contracts(tenant_id,customer_id);
CREATE INDEX amc_assets_amc_id_idx ON app.amc_assets(tenant_id,amc_id);
CREATE INDEX amc_assets_asset_id_idx ON app.amc_assets(tenant_id,asset_id);
CREATE INDEX amc_schedules_amc_id_idx ON app.amc_schedules(tenant_id,amc_id);
CREATE INDEX amc_schedules_asset_id_idx ON app.amc_schedules(tenant_id,asset_id);
CREATE INDEX tickets_customer_id_idx ON app.tickets(tenant_id,customer_id);
CREATE INDEX tickets_site_id_idx ON app.tickets(tenant_id,site_id);
CREATE INDEX tickets_asset_id_idx ON app.tickets(tenant_id,asset_id);
CREATE INDEX tickets_assigned_to_idx ON app.tickets(tenant_id,assigned_to);
CREATE INDEX tickets_lead_id_idx ON app.tickets(tenant_id,lead_id);
CREATE INDEX tickets_amc_id_idx ON app.tickets(tenant_id,amc_id);
CREATE INDEX tickets_checkout_location_id_idx ON app.tickets(tenant_id,checkout_location_id);
CREATE INDEX tickets_completion_photo_id_idx ON app.tickets(tenant_id,completion_photo_id);
CREATE INDEX tickets_signature_media_id_idx ON app.tickets(tenant_id,signature_media_id);
CREATE INDEX amc_occurrences_schedule_id_idx ON app.amc_occurrences(tenant_id,schedule_id);
CREATE INDEX amc_occurrences_ticket_id_idx ON app.amc_occurrences(tenant_id,ticket_id);
CREATE INDEX ticket_events_ticket_id_idx ON app.ticket_events(tenant_id,ticket_id);
CREATE INDEX ticket_events_actor_id_idx ON app.ticket_events(tenant_id,actor_id);
CREATE INDEX ticket_events_location_id_idx ON app.ticket_events(tenant_id,location_id);
CREATE INDEX ticket_media_ticket_id_idx ON app.ticket_media(tenant_id,ticket_id);
CREATE INDEX ticket_media_media_id_idx ON app.ticket_media(tenant_id,media_id);
CREATE INDEX customer_acceptances_ticket_id_idx ON app.customer_acceptances(tenant_id,ticket_id);
CREATE INDEX customer_acceptances_signature_media_id_idx ON app.customer_acceptances(tenant_id,signature_media_id);
CREATE INDEX stock_reservations_part_id_idx ON app.stock_reservations(tenant_id,part_id);
CREATE INDEX stock_reservations_ticket_id_idx ON app.stock_reservations(tenant_id,ticket_id);
CREATE INDEX stock_movements_part_id_idx ON app.stock_movements(tenant_id,part_id);
CREATE INDEX stock_movements_ticket_id_idx ON app.stock_movements(tenant_id,ticket_id);
CREATE INDEX stock_movements_actor_id_idx ON app.stock_movements(tenant_id,actor_id);
CREATE INDEX rma_cases_ticket_id_idx ON app.rma_cases(tenant_id,ticket_id);
CREATE INDEX rma_cases_asset_id_idx ON app.rma_cases(tenant_id,asset_id);
CREATE INDEX rma_cases_vendor_id_idx ON app.rma_cases(tenant_id,vendor_id);
CREATE INDEX quotations_customer_id_idx ON app.quotations(tenant_id,customer_id);
CREATE INDEX quotations_lead_id_idx ON app.quotations(tenant_id,lead_id);
CREATE INDEX quotations_ticket_id_idx ON app.quotations(tenant_id,ticket_id);
CREATE INDEX quotations_pdf_media_id_idx ON app.quotations(tenant_id,pdf_media_id);
CREATE INDEX quotation_lines_quotation_id_idx ON app.quotation_lines(tenant_id,quotation_id);
CREATE INDEX quotation_lines_part_id_idx ON app.quotation_lines(tenant_id,part_id);
CREATE INDEX payments_ticket_id_idx ON app.payments(tenant_id,ticket_id);
CREATE INDEX payments_received_by_idx ON app.payments(tenant_id,received_by);
CREATE INDEX service_documents_ticket_id_idx ON app.service_documents(tenant_id,ticket_id);
CREATE INDEX service_documents_media_id_idx ON app.service_documents(tenant_id,media_id);
CREATE INDEX travel_sessions_user_id_idx ON app.travel_sessions(tenant_id,user_id);
CREATE INDEX travel_sessions_consent_id_idx ON app.travel_sessions(tenant_id,consent_id);
CREATE INDEX travel_segments_user_id_idx ON app.travel_segments(tenant_id,user_id);
CREATE INDEX travel_segments_session_id_idx ON app.travel_segments(tenant_id,session_id);
CREATE INDEX travel_segments_from_location_id_idx ON app.travel_segments(tenant_id,from_location_id);
CREATE INDEX travel_segments_to_location_id_idx ON app.travel_segments(tenant_id,to_location_id);
CREATE INDEX travel_segments_approved_by_idx ON app.travel_segments(tenant_id,approved_by);
CREATE INDEX notifications_user_id_idx ON app.notifications(tenant_id,user_id);
CREATE INDEX notification_deliveries_notification_id_idx ON app.notification_deliveries(tenant_id,notification_id);
CREATE INDEX notification_deliveries_device_id_idx ON app.notification_deliveries(tenant_id,device_id);
CREATE INDEX report_preferences_user_id_idx ON app.report_preferences(tenant_id,user_id);
CREATE INDEX report_runs_requested_by_idx ON app.report_runs(tenant_id,requested_by);
CREATE INDEX report_runs_pdf_media_id_idx ON app.report_runs(tenant_id,pdf_media_id);
CREATE INDEX report_runs_csv_media_id_idx ON app.report_runs(tenant_id,csv_media_id);
CREATE INDEX deletion_requests_user_id_idx ON app.deletion_requests(tenant_id,user_id);
CREATE INDEX idempotency_keys_user_id_idx ON app.idempotency_keys(tenant_id,user_id);
CREATE INDEX audit_logs_actor_id_idx ON app.audit_logs(tenant_id,actor_id);

CREATE UNIQUE INDEX users_email_unique ON app.users(tenant_id,lower(email));
CREATE UNIQUE INDEX attendance_one_open ON app.attendance(tenant_id,user_id) WHERE punch_out IS NULL;
CREATE INDEX tickets_queue ON app.tickets(tenant_id,assigned_to,status,sla_due_at);
CREATE INDEX leads_due ON app.leads(tenant_id,assigned_to,next_followup_at) WHERE stage NOT IN ('WON','LOST');
CREATE INDEX outbox_ready ON app.outbox(tenant_id,available_at) WHERE delivered_at IS NULL;
CREATE INDEX locations_user_time ON app.location_events(tenant_id,user_id,captured_at);
CREATE INDEX amc_due ON app.amc_schedules(tenant_id,next_due_on) WHERE active;
-- Prevent tenant movement and maintain optimistic concurrency metadata.
CREATE FUNCTION app.protect_row() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.tenant_id <> OLD.tenant_id OR NEW.id <> OLD.id THEN
  RAISE EXCEPTION 'immutable identity' USING ERRCODE = '42501';
 END IF;
 NEW.updated_at := now(); NEW.version := OLD.version + 1; RETURN NEW;
END; $$;
ALTER TABLE app.branches ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.branches FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON app.branches USING (tenant_id = app.current_tenant()) WITH CHECK (tenant_id = app.current_tenant());
CREATE TRIGGER protect_row BEFORE UPDATE ON app.branches FOR EACH ROW EXECUTE FUNCTION app.protect_row();
ALTER TABLE app.shifts ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.shifts FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON app.shifts USING (tenant_id = app.current_tenant()) WITH CHECK (tenant_id = app.current_tenant());
CREATE TRIGGER protect_row BEFORE UPDATE ON app.shifts FOR EACH ROW EXECUTE FUNCTION app.protect_row();
ALTER TABLE app.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.users FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON app.users USING (tenant_id = app.current_tenant()) WITH CHECK (tenant_id = app.current_tenant());
CREATE TRIGGER protect_row BEFORE UPDATE ON app.users FOR EACH ROW EXECUTE FUNCTION app.protect_row();
ALTER TABLE app.shift_assignments ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.shift_assignments FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON app.shift_assignments USING (tenant_id = app.current_tenant()) WITH CHECK (tenant_id = app.current_tenant());
CREATE TRIGGER protect_row BEFORE UPDATE ON app.shift_assignments FOR EACH ROW EXECUTE FUNCTION app.protect_row();
ALTER TABLE app.holidays ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.holidays FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON app.holidays USING (tenant_id = app.current_tenant()) WITH CHECK (tenant_id = app.current_tenant());
CREATE TRIGGER protect_row BEFORE UPDATE ON app.holidays FOR EACH ROW EXECUTE FUNCTION app.protect_row();
ALTER TABLE app.teams ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.teams FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON app.teams USING (tenant_id = app.current_tenant()) WITH CHECK (tenant_id = app.current_tenant());
CREATE TRIGGER protect_row BEFORE UPDATE ON app.teams FOR EACH ROW EXECUTE FUNCTION app.protect_row();
ALTER TABLE app.team_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.team_members FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON app.team_members USING (tenant_id = app.current_tenant()) WITH CHECK (tenant_id = app.current_tenant());
CREATE TRIGGER protect_row BEFORE UPDATE ON app.team_members FOR EACH ROW EXECUTE FUNCTION app.protect_row();
ALTER TABLE app.devices ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.devices FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON app.devices USING (tenant_id = app.current_tenant()) WITH CHECK (tenant_id = app.current_tenant());
CREATE TRIGGER protect_row BEFORE UPDATE ON app.devices FOR EACH ROW EXECUTE FUNCTION app.protect_row();
ALTER TABLE app.auth_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.auth_sessions FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON app.auth_sessions USING (tenant_id = app.current_tenant()) WITH CHECK (tenant_id = app.current_tenant());
CREATE TRIGGER protect_row BEFORE UPDATE ON app.auth_sessions FOR EACH ROW EXECUTE FUNCTION app.protect_row();
ALTER TABLE app.password_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.password_tokens FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON app.password_tokens USING (tenant_id = app.current_tenant()) WITH CHECK (tenant_id = app.current_tenant());
CREATE TRIGGER protect_row BEFORE UPDATE ON app.password_tokens FOR EACH ROW EXECUTE FUNCTION app.protect_row();
ALTER TABLE app.consents ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.consents FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON app.consents USING (tenant_id = app.current_tenant()) WITH CHECK (tenant_id = app.current_tenant());
CREATE TRIGGER protect_row BEFORE UPDATE ON app.consents FOR EACH ROW EXECUTE FUNCTION app.protect_row();
ALTER TABLE app.customers ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.customers FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON app.customers USING (tenant_id = app.current_tenant()) WITH CHECK (tenant_id = app.current_tenant());
CREATE TRIGGER protect_row BEFORE UPDATE ON app.customers FOR EACH ROW EXECUTE FUNCTION app.protect_row();
ALTER TABLE app.sites ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.sites FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON app.sites USING (tenant_id = app.current_tenant()) WITH CHECK (tenant_id = app.current_tenant());
CREATE TRIGGER protect_row BEFORE UPDATE ON app.sites FOR EACH ROW EXECUTE FUNCTION app.protect_row();
ALTER TABLE app.assets ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.assets FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON app.assets USING (tenant_id = app.current_tenant()) WITH CHECK (tenant_id = app.current_tenant());
CREATE TRIGGER protect_row BEFORE UPDATE ON app.assets FOR EACH ROW EXECUTE FUNCTION app.protect_row();
ALTER TABLE app.media ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.media FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON app.media USING (tenant_id = app.current_tenant()) WITH CHECK (tenant_id = app.current_tenant());
CREATE TRIGGER protect_row BEFORE UPDATE ON app.media FOR EACH ROW EXECUTE FUNCTION app.protect_row();
ALTER TABLE app.location_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.location_events FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON app.location_events USING (tenant_id = app.current_tenant()) WITH CHECK (tenant_id = app.current_tenant());
CREATE TRIGGER protect_row BEFORE UPDATE ON app.location_events FOR EACH ROW EXECUTE FUNCTION app.protect_row();
ALTER TABLE app.attendance ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.attendance FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON app.attendance USING (tenant_id = app.current_tenant()) WITH CHECK (tenant_id = app.current_tenant());
CREATE TRIGGER protect_row BEFORE UPDATE ON app.attendance FOR EACH ROW EXECUTE FUNCTION app.protect_row();
ALTER TABLE app.attendance_corrections ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.attendance_corrections FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON app.attendance_corrections USING (tenant_id = app.current_tenant()) WITH CHECK (tenant_id = app.current_tenant());
CREATE TRIGGER protect_row BEFORE UPDATE ON app.attendance_corrections FOR EACH ROW EXECUTE FUNCTION app.protect_row();
ALTER TABLE app.leave_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.leave_requests FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON app.leave_requests USING (tenant_id = app.current_tenant()) WITH CHECK (tenant_id = app.current_tenant());
CREATE TRIGGER protect_row BEFORE UPDATE ON app.leave_requests FOR EACH ROW EXECUTE FUNCTION app.protect_row();
ALTER TABLE app.leads ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.leads FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON app.leads USING (tenant_id = app.current_tenant()) WITH CHECK (tenant_id = app.current_tenant());
CREATE TRIGGER protect_row BEFORE UPDATE ON app.leads FOR EACH ROW EXECUTE FUNCTION app.protect_row();
ALTER TABLE app.lead_activities ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.lead_activities FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON app.lead_activities USING (tenant_id = app.current_tenant()) WITH CHECK (tenant_id = app.current_tenant());
CREATE TRIGGER protect_row BEFORE UPDATE ON app.lead_activities FOR EACH ROW EXECUTE FUNCTION app.protect_row();
ALTER TABLE app.amc_contracts ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.amc_contracts FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON app.amc_contracts USING (tenant_id = app.current_tenant()) WITH CHECK (tenant_id = app.current_tenant());
CREATE TRIGGER protect_row BEFORE UPDATE ON app.amc_contracts FOR EACH ROW EXECUTE FUNCTION app.protect_row();
ALTER TABLE app.amc_assets ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.amc_assets FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON app.amc_assets USING (tenant_id = app.current_tenant()) WITH CHECK (tenant_id = app.current_tenant());
CREATE TRIGGER protect_row BEFORE UPDATE ON app.amc_assets FOR EACH ROW EXECUTE FUNCTION app.protect_row();
ALTER TABLE app.amc_schedules ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.amc_schedules FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON app.amc_schedules USING (tenant_id = app.current_tenant()) WITH CHECK (tenant_id = app.current_tenant());
CREATE TRIGGER protect_row BEFORE UPDATE ON app.amc_schedules FOR EACH ROW EXECUTE FUNCTION app.protect_row();
ALTER TABLE app.tickets ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.tickets FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON app.tickets USING (tenant_id = app.current_tenant()) WITH CHECK (tenant_id = app.current_tenant());
CREATE TRIGGER protect_row BEFORE UPDATE ON app.tickets FOR EACH ROW EXECUTE FUNCTION app.protect_row();
ALTER TABLE app.amc_occurrences ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.amc_occurrences FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON app.amc_occurrences USING (tenant_id = app.current_tenant()) WITH CHECK (tenant_id = app.current_tenant());
CREATE TRIGGER protect_row BEFORE UPDATE ON app.amc_occurrences FOR EACH ROW EXECUTE FUNCTION app.protect_row();
ALTER TABLE app.ticket_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.ticket_events FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON app.ticket_events USING (tenant_id = app.current_tenant()) WITH CHECK (tenant_id = app.current_tenant());
CREATE TRIGGER protect_row BEFORE UPDATE ON app.ticket_events FOR EACH ROW EXECUTE FUNCTION app.protect_row();
ALTER TABLE app.ticket_media ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.ticket_media FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON app.ticket_media USING (tenant_id = app.current_tenant()) WITH CHECK (tenant_id = app.current_tenant());
CREATE TRIGGER protect_row BEFORE UPDATE ON app.ticket_media FOR EACH ROW EXECUTE FUNCTION app.protect_row();
ALTER TABLE app.customer_acceptances ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.customer_acceptances FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON app.customer_acceptances USING (tenant_id = app.current_tenant()) WITH CHECK (tenant_id = app.current_tenant());
CREATE TRIGGER protect_row BEFORE UPDATE ON app.customer_acceptances FOR EACH ROW EXECUTE FUNCTION app.protect_row();
ALTER TABLE app.inventory_parts ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.inventory_parts FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON app.inventory_parts USING (tenant_id = app.current_tenant()) WITH CHECK (tenant_id = app.current_tenant());
CREATE TRIGGER protect_row BEFORE UPDATE ON app.inventory_parts FOR EACH ROW EXECUTE FUNCTION app.protect_row();
ALTER TABLE app.stock_reservations ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.stock_reservations FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON app.stock_reservations USING (tenant_id = app.current_tenant()) WITH CHECK (tenant_id = app.current_tenant());
CREATE TRIGGER protect_row BEFORE UPDATE ON app.stock_reservations FOR EACH ROW EXECUTE FUNCTION app.protect_row();
ALTER TABLE app.stock_movements ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.stock_movements FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON app.stock_movements USING (tenant_id = app.current_tenant()) WITH CHECK (tenant_id = app.current_tenant());
CREATE TRIGGER protect_row BEFORE UPDATE ON app.stock_movements FOR EACH ROW EXECUTE FUNCTION app.protect_row();
ALTER TABLE app.vendors ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.vendors FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON app.vendors USING (tenant_id = app.current_tenant()) WITH CHECK (tenant_id = app.current_tenant());
CREATE TRIGGER protect_row BEFORE UPDATE ON app.vendors FOR EACH ROW EXECUTE FUNCTION app.protect_row();
ALTER TABLE app.rma_cases ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.rma_cases FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON app.rma_cases USING (tenant_id = app.current_tenant()) WITH CHECK (tenant_id = app.current_tenant());
CREATE TRIGGER protect_row BEFORE UPDATE ON app.rma_cases FOR EACH ROW EXECUTE FUNCTION app.protect_row();
ALTER TABLE app.quotations ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.quotations FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON app.quotations USING (tenant_id = app.current_tenant()) WITH CHECK (tenant_id = app.current_tenant());
CREATE TRIGGER protect_row BEFORE UPDATE ON app.quotations FOR EACH ROW EXECUTE FUNCTION app.protect_row();
ALTER TABLE app.quotation_lines ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.quotation_lines FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON app.quotation_lines USING (tenant_id = app.current_tenant()) WITH CHECK (tenant_id = app.current_tenant());
CREATE TRIGGER protect_row BEFORE UPDATE ON app.quotation_lines FOR EACH ROW EXECUTE FUNCTION app.protect_row();
ALTER TABLE app.payments ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.payments FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON app.payments USING (tenant_id = app.current_tenant()) WITH CHECK (tenant_id = app.current_tenant());
CREATE TRIGGER protect_row BEFORE UPDATE ON app.payments FOR EACH ROW EXECUTE FUNCTION app.protect_row();
ALTER TABLE app.service_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.service_documents FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON app.service_documents USING (tenant_id = app.current_tenant()) WITH CHECK (tenant_id = app.current_tenant());
CREATE TRIGGER protect_row BEFORE UPDATE ON app.service_documents FOR EACH ROW EXECUTE FUNCTION app.protect_row();
ALTER TABLE app.travel_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.travel_sessions FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON app.travel_sessions USING (tenant_id = app.current_tenant()) WITH CHECK (tenant_id = app.current_tenant());
CREATE TRIGGER protect_row BEFORE UPDATE ON app.travel_sessions FOR EACH ROW EXECUTE FUNCTION app.protect_row();
ALTER TABLE app.travel_segments ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.travel_segments FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON app.travel_segments USING (tenant_id = app.current_tenant()) WITH CHECK (tenant_id = app.current_tenant());
CREATE TRIGGER protect_row BEFORE UPDATE ON app.travel_segments FOR EACH ROW EXECUTE FUNCTION app.protect_row();
ALTER TABLE app.notifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.notifications FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON app.notifications USING (tenant_id = app.current_tenant()) WITH CHECK (tenant_id = app.current_tenant());
CREATE TRIGGER protect_row BEFORE UPDATE ON app.notifications FOR EACH ROW EXECUTE FUNCTION app.protect_row();
ALTER TABLE app.outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.outbox FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON app.outbox USING (tenant_id = app.current_tenant()) WITH CHECK (tenant_id = app.current_tenant());
CREATE TRIGGER protect_row BEFORE UPDATE ON app.outbox FOR EACH ROW EXECUTE FUNCTION app.protect_row();
ALTER TABLE app.notification_deliveries ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.notification_deliveries FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON app.notification_deliveries USING (tenant_id = app.current_tenant()) WITH CHECK (tenant_id = app.current_tenant());
CREATE TRIGGER protect_row BEFORE UPDATE ON app.notification_deliveries FOR EACH ROW EXECUTE FUNCTION app.protect_row();
ALTER TABLE app.report_preferences ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.report_preferences FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON app.report_preferences USING (tenant_id = app.current_tenant()) WITH CHECK (tenant_id = app.current_tenant());
CREATE TRIGGER protect_row BEFORE UPDATE ON app.report_preferences FOR EACH ROW EXECUTE FUNCTION app.protect_row();
ALTER TABLE app.report_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.report_runs FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON app.report_runs USING (tenant_id = app.current_tenant()) WITH CHECK (tenant_id = app.current_tenant());
CREATE TRIGGER protect_row BEFORE UPDATE ON app.report_runs FOR EACH ROW EXECUTE FUNCTION app.protect_row();
ALTER TABLE app.deletion_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.deletion_requests FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON app.deletion_requests USING (tenant_id = app.current_tenant()) WITH CHECK (tenant_id = app.current_tenant());
CREATE TRIGGER protect_row BEFORE UPDATE ON app.deletion_requests FOR EACH ROW EXECUTE FUNCTION app.protect_row();
ALTER TABLE app.idempotency_keys ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.idempotency_keys FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON app.idempotency_keys USING (tenant_id = app.current_tenant()) WITH CHECK (tenant_id = app.current_tenant());
CREATE TRIGGER protect_row BEFORE UPDATE ON app.idempotency_keys FOR EACH ROW EXECUTE FUNCTION app.protect_row();
ALTER TABLE app.audit_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.audit_logs FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON app.audit_logs USING (tenant_id = app.current_tenant()) WITH CHECK (tenant_id = app.current_tenant());
CREATE TRIGGER protect_row BEFORE UPDATE ON app.audit_logs FOR EACH ROW EXECUTE FUNCTION app.protect_row();
ALTER TABLE app.document_sequences ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.document_sequences FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON app.document_sequences USING (tenant_id = app.current_tenant()) WITH CHECK (tenant_id = app.current_tenant());
CREATE TRIGGER protect_row BEFORE UPDATE ON app.document_sequences FOR EACH ROW EXECUTE FUNCTION app.protect_row();

ALTER TABLE control.tenant_features ENABLE ROW LEVEL SECURITY;
ALTER TABLE control.tenant_features FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON control.tenant_features USING (tenant_id = app.current_tenant()) WITH CHECK (tenant_id = app.current_tenant());
REVOKE ALL ON SCHEMA control, app FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA control, app FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA app FROM PUBLIC;
-- Phase 2 provisioning must GRANT explicitly to separate API, worker and control roles.
-- Never GRANT TRUNCATE, DDL, role membership, table ownership or BYPASSRLS to runtime roles.
COMMIT;
