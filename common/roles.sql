-- WindBurglr database roles with least-privilege access
--
-- Run as the schema owner (or a superuser) AFTER timescaledb_schema.sql, using psql:
--
--   psql "$ADMIN_DATABASE_URL" \
--     -v scraper_password='...' \
--     -v webapp_password='...' \
--     -f common/roles.sql
--
-- Safe to re-run: roles are created if missing, passwords are reset, grants are idempotent.
--
-- Notes:
--  * All app functions are SECURITY INVOKER (the default), so callers need
--    privileges on the underlying tables as well as EXECUTE on the function.
--  * Trigger functions (notify_wind_obs_insert, notify_scraper_status) do not
--    require EXECUTE; they run as the inserting role, which therefore needs
--    SELECT on station (they look up the station name).
--  * FK checks run as the table owner, so no REFERENCES privilege is needed.
--  * LISTEN/NOTIFY requires no privileges.

\set ON_ERROR_STOP on

BEGIN;

-- ---------------------------------------------------------------------------
-- Roles
-- ---------------------------------------------------------------------------

SELECT 'CREATE ROLE scraper'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'scraper') \gexec
SELECT 'CREATE ROLE webapp'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'webapp') \gexec

-- Only LOGIN/PASSWORD are set: CREATE ROLE already defaults to NOSUPERUSER, NOCREATEDB,
-- NOCREATEROLE, NOREPLICATION, NOBYPASSRLS, and naming those attributes explicitly requires
-- superuser, which managed services (e.g. Aiven's avnadmin) don't provide.
ALTER ROLE scraper WITH LOGIN PASSWORD :'scraper_password';
ALTER ROLE webapp WITH LOGIN PASSWORD :'webapp_password';

-- ---------------------------------------------------------------------------
-- Database / schema
-- ---------------------------------------------------------------------------

-- Lock down defaults (PUBLIC can CREATE in schema public before PG15)
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database()) \gexec

SELECT format('GRANT CONNECT ON DATABASE %I TO scraper, webapp', current_database()) \gexec
GRANT USAGE ON SCHEMA public TO scraper, webapp;

-- Strip any previously granted table/sequence privileges so only the grants below apply
REVOKE ALL ON station, wind_obs, scraper_status FROM PUBLIC, scraper, webapp;
REVOKE ALL ON SEQUENCE station_id_seq FROM PUBLIC, scraper, webapp;

-- Functions are executable by PUBLIC by default; restrict them to the roles that use them
REVOKE ALL ON FUNCTION
    get_wind_data_by_station_range(TEXT, TIMESTAMPTZ, TIMESTAMPTZ),
    get_latest_wind_observation(TEXT),
    get_station_timezone_name(TEXT),
    get_station_id_by_name(TEXT),
    get_all_stations(),
    update_scraper_status(TEXT, TEXT, TEXT),
    get_scraper_status(),
    get_scraper_health(),
    notify_wind_obs_insert(),
    notify_scraper_status()
FROM PUBLIC;

-- ---------------------------------------------------------------------------
-- scraper: upserts stations, inserts observations, maintains scraper_status
-- ---------------------------------------------------------------------------

-- INSERT ... ON CONFLICT (name) DO UPDATE SET timezone; SELECT id by name
GRANT SELECT, INSERT ON station TO scraper;
GRANT UPDATE (timezone) ON station TO scraper;
GRANT USAGE ON SEQUENCE station_id_seq TO scraper;

-- INSERT INTO wind_obs (append-only)
GRANT INSERT ON wind_obs TO scraper;

-- update_scraper_status() reads, inserts and updates its row
GRANT SELECT, INSERT, UPDATE ON scraper_status TO scraper;
GRANT EXECUTE ON FUNCTION update_scraper_status(TEXT, TEXT, TEXT) TO scraper;

-- ---------------------------------------------------------------------------
-- webapp: read-only access via query functions + LISTEN
-- ---------------------------------------------------------------------------

GRANT SELECT ON station, wind_obs, scraper_status TO webapp;

GRANT EXECUTE ON FUNCTION
    get_wind_data_by_station_range(TEXT, TIMESTAMPTZ, TIMESTAMPTZ),
    get_latest_wind_observation(TEXT),
    get_station_timezone_name(TEXT),
    get_scraper_status(),
    get_scraper_health()
TO webapp;

COMMIT;
