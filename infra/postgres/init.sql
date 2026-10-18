-- Executed once when the local Postgres volume is created.
-- Role model (see docs/DATABASE_SCHEMA.md#roles):
--   rp_owner   : migration owner (superuser in local dev only)
--   rp_app     : API request role, subject to row-level security, no BYPASSRLS
--   rp_ingest  : authorized ingestion/admin writer for global reference tables
--   rp_system  : maintenance processes (outbox relay, reconciler, monitors); BYPASSRLS
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rp_app') THEN
    CREATE ROLE rp_app LOGIN PASSWORD 'rp_app_dev' NOSUPERUSER NOBYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rp_ingest') THEN
    CREATE ROLE rp_ingest LOGIN PASSWORD 'rp_ingest_dev' NOSUPERUSER NOBYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rp_system') THEN
    CREATE ROLE rp_system LOGIN PASSWORD 'rp_system_dev' NOSUPERUSER BYPASSRLS;
  END IF;
END
$$;

CREATE DATABASE research_platform_test OWNER rp_owner;
\c research_platform_test
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
