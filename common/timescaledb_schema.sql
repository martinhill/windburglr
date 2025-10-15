-- PostgreSQL with TimescaleDB

CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS station (
  id serial PRIMARY KEY,
  name VARCHAR(10) UNIQUE NOT NULL,
  timezone VARCHAR(50) NOT NULL DEFAULT 'UTC'
);
CREATE TABLE IF NOT EXISTS wind_obs (
  station_id integer references station (id),
  update_time timestamp with time zone,
  direction numeric,
  speed_kts numeric,
  gust_kts numeric,
  PRIMARY KEY (station_id, update_time)
);

-- Conditionally create hypertable if TimescaleDB is available, otherwise create regular index
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
        SELECT create_hypertable('wind_obs', 'update_time');
    ELSE
        -- Fallback for development environments without TimescaleDB
        CREATE INDEX IF NOT EXISTS idx_wind_obs_update_time ON wind_obs (update_time);
    END IF;
END $$;

-- WindBurglr PostgreSQL Stored Procedures
-- These functions encapsulate common queries for better performance and maintainability

-- 1. Historical wind data by station and time range
CREATE OR REPLACE FUNCTION get_wind_data_by_station_range(
    station_name TEXT,
    start_time TIMESTAMP WITH TIME ZONE,
    end_time TIMESTAMP WITH TIME ZONE
) RETURNS TABLE (
    update_time TIMESTAMP WITH TIME ZONE,
    direction NUMERIC,
    speed_kts NUMERIC,
    gust_kts NUMERIC
) AS $$
BEGIN
    RETURN QUERY
    SELECT wo.update_time, wo.direction, wo.speed_kts, wo.gust_kts
    FROM wind_obs wo
    JOIN station s ON wo.station_id = s.id
    WHERE s.name = station_name
    AND wo.update_time BETWEEN start_time AND end_time
    ORDER BY wo.update_time;
END;
$$ LANGUAGE plpgsql STABLE;

-- 2. Latest wind observation for a station
CREATE OR REPLACE FUNCTION get_latest_wind_observation(
    station_name TEXT
) RETURNS TABLE (
    update_time TIMESTAMP WITH TIME ZONE,
    direction NUMERIC,
    speed_kts NUMERIC,
    gust_kts NUMERIC
) AS $$
BEGIN
    RETURN QUERY
    SELECT wo.update_time, wo.direction, wo.speed_kts, wo.gust_kts
    FROM wind_obs wo
    JOIN station s ON wo.station_id = s.id
    WHERE s.name = station_name
    ORDER BY wo.update_time DESC
    LIMIT 1;
END;
$$ LANGUAGE plpgsql STABLE;

-- 3. Station timezone lookup with fallback to UTC
CREATE OR REPLACE FUNCTION get_station_timezone_name(
    station_name TEXT
) RETURNS TEXT AS $$
DECLARE
    tz_name TEXT;
BEGIN
    SELECT timezone INTO tz_name
    FROM station
    WHERE name = station_name;

    IF tz_name IS NULL THEN
        RETURN 'UTC';
    END IF;

    RETURN tz_name;
END;
$$ LANGUAGE plpgsql STABLE;

-- 4. Station ID and name lookup
CREATE OR REPLACE FUNCTION get_station_id_by_name(
    station_name TEXT
) RETURNS TABLE (
    id INTEGER,
    name TEXT
) AS $$
BEGIN
    RETURN QUERY
    SELECT s.id, s.name
    FROM station s
    WHERE s.name = station_name;
END;
$$ LANGUAGE plpgsql STABLE;

-- 5. List all available stations
CREATE OR REPLACE FUNCTION get_all_stations()
 RETURNS TABLE (
    name TEXT
) AS $$
BEGIN
    RETURN QUERY
    SELECT s.name
    FROM station s
    ORDER BY s.name;
END;
$$ LANGUAGE plpgsql STABLE;

-- Usage examples:
-- SELECT * FROM get_wind_data_by_station_range('CYTZ', '2023-01-01', '2023-12-31');
-- SELECT * FROM get_latest_wind_observation('CYTZ');
-- SELECT get_station_timezone_name('CYTZ');
-- SELECT * FROM get_station_id_by_name('CYTZ');
-- SELECT * FROM get_all_stations();


-- Scraper status tracking table
CREATE TABLE IF NOT EXISTS scraper_status (
    station_id INTEGER REFERENCES station(id) PRIMARY KEY,
    last_success TIMESTAMP WITH TIME ZONE,
    last_attempt TIMESTAMP WITH TIME ZONE,
    status VARCHAR(50) NOT NULL DEFAULT 'unknown',
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Index for efficient status queries
CREATE INDEX IF NOT EXISTS idx_scraper_status_updated_at ON scraper_status (updated_at);
CREATE INDEX IF NOT EXISTS idx_scraper_status_status ON scraper_status (status);

-- Function to update scraper status
CREATE OR REPLACE FUNCTION update_scraper_status(
    station_name TEXT,
    new_status TEXT,
    error_msg TEXT DEFAULT NULL
) RETURNS VOID AS $$
DECLARE
    station_id_var INTEGER;
    existing_status TEXT;
BEGIN
    -- Get station ID
    SELECT id INTO station_id_var
    FROM station
    WHERE name = station_name;

    IF station_id_var IS NULL THEN
        RAISE EXCEPTION 'Station % not found', station_name;
    END IF;

    -- Check if row exists
    SELECT status INTO existing_status
    FROM scraper_status
    WHERE station_id = station_id_var;

    IF existing_status IS NULL THEN
        -- Insert new row
        INSERT INTO scraper_status (station_id, last_attempt, status, error_message, retry_count, updated_at, last_success)
        VALUES (
            station_id_var,
            clock_timestamp(),
            new_status,
            error_msg,
            0,
            clock_timestamp(),
            CASE
                WHEN new_status = 'healthy' THEN clock_timestamp()
                ELSE NULL
            END
        );
    ELSE
        -- Update existing row
        UPDATE scraper_status SET
            last_attempt = clock_timestamp(),
            status = new_status,
            error_message = CASE
                WHEN error_msg is NULL THEN error_message
                ELSE error_msg
            END,
            retry_count = CASE
                WHEN new_status = 'healthy' THEN 0
                WHEN new_status IN ('error', 'http_error', 'network_error', 'parse_error', 'stale_data') THEN retry_count + 1
                ELSE retry_count
            END,
            updated_at = clock_timestamp(),
            last_success = CASE
                WHEN new_status = 'healthy' THEN clock_timestamp()
                ELSE last_success
            END
        WHERE station_id = station_id_var;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- Function to get scraper status for all stations
CREATE OR REPLACE FUNCTION get_scraper_status()
RETURNS TABLE (
    station_name TEXT,
    last_success TIMESTAMP WITH TIME ZONE,
    last_attempt TIMESTAMP WITH TIME ZONE,
    status TEXT,
    error_message TEXT,
    retry_count INTEGER,
    time_since_last_attempt INTERVAL,
    time_since_last_success INTERVAL
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        s.name::TEXT,
        ss.last_success,
        ss.last_attempt,
        COALESCE(ss.status, 'unknown')::TEXT,
        ss.error_message,
        COALESCE(ss.retry_count, 0),
        CASE
            WHEN ss.last_attempt IS NOT NULL THEN NOW() - ss.last_attempt
            ELSE NULL
        END,
        CASE
            WHEN ss.last_success IS NOT NULL THEN NOW() - ss.last_success
            ELSE NULL
        END
    FROM station s
    LEFT JOIN scraper_status ss ON s.id = ss.station_id
    ORDER BY s.name;
END;
$$ LANGUAGE plpgsql STABLE;

-- Function to get overall scraper health
CREATE OR REPLACE FUNCTION get_scraper_health()
RETURNS TABLE (
    total_stations BIGINT,
    healthy_stations BIGINT,
    error_stations BIGINT,
    stale_stations BIGINT,
    overall_status TEXT
) AS $$
DECLARE
    total_count BIGINT;
    healthy_count BIGINT;
    error_count BIGINT;
    stale_count BIGINT;
BEGIN
    SELECT COUNT(*) INTO total_count FROM station;

    SELECT COUNT(*) INTO healthy_count
    FROM scraper_status
    WHERE status = 'healthy'
    AND last_attempt > NOW() - INTERVAL '5 minutes';

    SELECT COUNT(*) INTO error_count
    FROM scraper_status
    WHERE status in ('error', 'http_error', 'network_error', 'parse_error')
    OR (status in ('healthy', 'stale_data') AND last_attempt <= NOW() - INTERVAL '5 minutes');

    SELECT COUNT(*) INTO stale_count
    FROM scraper_status
    WHERE status = 'stale_data';

    RETURN QUERY SELECT
        total_count,
        healthy_count,
        error_count,
        stale_count,
        CASE
            WHEN error_count > 0 THEN 'error'
            WHEN stale_count > 0 THEN 'warning'
            WHEN healthy_count = total_count THEN 'healthy'
            ELSE 'unknown'
        END;
END;
$$ LANGUAGE plpgsql STABLE;

-- PostgreSQL trigger function and trigger for wind_obs notifications
-- Run this SQL to set up database-level notifications


-- Create trigger function that sends notifications on wind_obs insert
CREATE OR REPLACE FUNCTION notify_wind_obs_insert()
RETURNS trigger AS $$
DECLARE
    station_name_var TEXT;
BEGIN
    -- Get station name for the notification
    SELECT name INTO station_name_var
    FROM station
    WHERE id = NEW.station_id;

    -- Send notification with station name and observation data
    PERFORM pg_notify('wind_obs_insert',
        json_build_object(
            'station_id', NEW.station_id,
            'station_name', station_name_var,
            'direction', NEW.direction,
            'speed_kts', NEW.speed_kts,
            'gust_kts', NEW.gust_kts,
            'update_time', extract(epoch from NEW.update_time)
        )::text
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger that fires after each insert
CREATE TRIGGER wind_obs_insert_trigger
    AFTER INSERT ON wind_obs
    FOR EACH ROW
    EXECUTE FUNCTION notify_wind_obs_insert();

-- Trigger function for scraper_status notifications
CREATE OR REPLACE FUNCTION notify_scraper_status()
RETURNS TRIGGER AS $$
DECLARE
    station_name_var TEXT;
    status_data JSON;
BEGIN
    -- Get station name for the notification
    SELECT name INTO station_name_var
    FROM station
    WHERE id = NEW.station_id;

    -- Build status data JSON using information similar to get_scraper_status()
    SELECT json_build_object(
        'station_name', station_name_var,
        'last_success', NEW.last_success,
        'last_attempt', NEW.last_attempt,
        'status', COALESCE(NEW.status, 'unknown'),
        'error_message', NEW.error_message,
        'retry_count', COALESCE(NEW.retry_count, 0),
        'time_since_last_attempt', CASE
            WHEN NEW.last_attempt IS NOT NULL THEN NOW() - NEW.last_attempt
            ELSE NULL
        END,
        'time_since_last_success', CASE
            WHEN NEW.last_success IS NOT NULL THEN NOW() - NEW.last_success
            ELSE NULL
        END,
        'updated_at', NEW.updated_at
    ) INTO status_data;

    -- Send notification with the status data
    PERFORM pg_notify('scraper_status_update', status_data::text);

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger that fires after insert or update on scraper_status
CREATE TRIGGER scraper_status_notify_trigger
    AFTER INSERT OR UPDATE ON scraper_status
    FOR EACH ROW
    EXECUTE FUNCTION notify_scraper_status();
