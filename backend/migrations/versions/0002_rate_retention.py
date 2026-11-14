"""Expire shared rate-limit counters without broad worker table privileges."""

from alembic import op

revision = "0002_rate_retention"
down_revision = "0001_phase2"


def upgrade():
    op.get_bind().connection.driver_connection.execute("""
ALTER TABLE control.rate_buckets ADD COLUMN expires_at timestamptz NOT NULL DEFAULT now();
CREATE INDEX rate_buckets_expiry ON control.rate_buckets(expires_at);
CREATE OR REPLACE FUNCTION control.rate_limit(p_key text,p_limit integer,p_window integer) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE n integer; b bigint;
BEGIN
 IF p_limit < 1 OR p_limit > 100 OR p_window < 60 OR p_window > 86400 OR length(p_key) <> 64 THEN
  RAISE EXCEPTION 'invalid rate policy';
 END IF;
 b := floor(extract(epoch from clock_timestamp())/p_window);
 INSERT INTO control.rate_buckets(key_hash,bucket,hits,expires_at)
 VALUES(p_key,b,1,to_timestamp((b+2)*p_window))
 ON CONFLICT(key_hash,bucket) DO UPDATE SET hits=control.rate_buckets.hits+1 RETURNING hits INTO n;
 RETURN n <= p_limit;
END; $$;
CREATE FUNCTION control.prune_rate_buckets() RETURNS void
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog AS $$
 DELETE FROM control.rate_buckets WHERE expires_at<now();
$$;
REVOKE ALL ON FUNCTION control.prune_rate_buckets() FROM PUBLIC;
""")


def downgrade():
    raise RuntimeError("Use a reviewed forward migration or isolated backup recovery")
