-- Installed by Alembic after schema.sql. Runtime roles are provisioned separately.
ALTER TABLE app.auth_sessions ADD COLUMN csrf_hash text NOT NULL DEFAULT '';
ALTER TABLE app.auth_sessions ADD COLUMN client_type text NOT NULL DEFAULT 'web' CHECK(client_type IN ('web','native'));
ALTER TABLE control.platform_sessions ADD COLUMN family_id uuid NOT NULL DEFAULT gen_random_uuid();
ALTER TABLE control.platform_sessions ADD COLUMN csrf_hash text NOT NULL DEFAULT '';
ALTER TABLE control.platform_admins ADD COLUMN last_totp_step bigint NOT NULL DEFAULT -1;
ALTER TABLE control.tenants ADD COLUMN creation_key uuid UNIQUE;
ALTER TABLE control.tenants ADD COLUMN creation_hash text;
ALTER TABLE control.tenants ADD COLUMN created_by uuid REFERENCES control.platform_admins(id);
CREATE TABLE control.rate_buckets (
 key_hash text NOT NULL, bucket bigint NOT NULL, hits integer NOT NULL,
 PRIMARY KEY(key_hash,bucket)
);
-- Functions owned by migration owner, fixed search_path, minimum return fields.
CREATE FUNCTION control.resolve_slug(p_slug text) RETURNS uuid
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog AS $$
 SELECT id FROM control.tenants WHERE slug=p_slug;
$$;
CREATE FUNCTION control.tenant_state() RETURNS TABLE(
 id uuid, name text, slug text, status text, valid_until timestamptz,
 max_active_employees integer, storage_quota_bytes bigint, version integer)
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog AS $$
 SELECT t.id,t.name,t.slug,t.status,t.valid_until,t.max_active_employees,t.storage_quota_bytes,t.version
 FROM control.tenants t WHERE t.id=app.current_tenant();
$$;
CREATE FUNCTION control.lock_tenant() RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 PERFORM 1 FROM control.tenants WHERE id=app.current_tenant() FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'tenant missing' USING ERRCODE='42501'; END IF;
END; $$;
CREATE FUNCTION control.rate_limit(p_key text,p_limit integer,p_window integer) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE n integer; b bigint;
BEGIN
 IF p_limit < 1 OR p_limit > 100 OR p_window < 60 OR length(p_key) <> 64 THEN
  RAISE EXCEPTION 'invalid rate policy';
 END IF;
 b := floor(extract(epoch from clock_timestamp())/p_window);
 INSERT INTO control.rate_buckets(key_hash,bucket,hits) VALUES(p_key,b,1)
 ON CONFLICT(key_hash,bucket) DO UPDATE SET hits=control.rate_buckets.hits+1 RETURNING hits INTO n;
 RETURN n <= p_limit;
END; $$;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA control FROM PUBLIC;
REVOKE ALL ON control.rate_buckets FROM PUBLIC;
-- A tenant-level quota lock is mandatory for every user insert/reactivation,
-- including writes that do not pass through the HTTP service.
CREATE FUNCTION app.enforce_user_limit() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE cap integer; used integer;
BEGIN
 PERFORM control.lock_tenant();
 SELECT max_active_employees INTO cap FROM control.tenant_state();
 IF NEW.active AND (TG_OP='INSERT' OR NOT OLD.active) THEN
  SELECT count(*) INTO used FROM app.users WHERE tenant_id=NEW.tenant_id AND active;
  IF used >= cap THEN RAISE EXCEPTION 'employee limit exceeded' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END; $$;
CREATE TRIGGER user_quota BEFORE INSERT OR UPDATE OF active ON app.users
 FOR EACH ROW EXECUTE FUNCTION app.enforce_user_limit();
