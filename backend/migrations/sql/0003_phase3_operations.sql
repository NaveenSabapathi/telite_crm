ALTER TABLE app.media ADD COLUMN inline_data bytea;
ALTER TABLE app.report_runs ADD COLUMN snapshot jsonb;
ALTER TABLE app.attendance ADD COLUMN branch_snapshot jsonb NOT NULL DEFAULT '{}';
ALTER TABLE app.attendance ADD COLUMN break_minutes integer NOT NULL DEFAULT 0 CHECK(break_minutes>=0);
CREATE FUNCTION control.operations_settings() RETURNS TABLE(timezone text,currency char(3),report_local_time time)
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog AS $$
 SELECT timezone,currency,report_local_time FROM control.tenants WHERE id=app.current_tenant();
$$;
REVOKE ALL ON FUNCTION control.operations_settings() FROM PUBLIC;
CREATE FUNCTION control.reserve_evidence(p_bytes bigint) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF p_bytes < 1 OR p_bytes > 100000 THEN RAISE EXCEPTION 'invalid evidence size' USING ERRCODE='23514'; END IF;
 UPDATE control.tenants SET storage_used_bytes=storage_used_bytes+p_bytes
 WHERE id=app.current_tenant() AND storage_used_bytes+storage_reserved_bytes+p_bytes<=storage_quota_bytes;
 IF NOT FOUND THEN RAISE EXCEPTION 'storage quota exceeded' USING ERRCODE='23514'; END IF;
END; $$;
REVOKE ALL ON FUNCTION control.reserve_evidence(bigint) FROM PUBLIC;
CREATE UNIQUE INDEX deletion_one_pending ON app.deletion_requests(tenant_id,user_id)
 WHERE status IN ('RECEIVED','VERIFIED','PROCESSING');
