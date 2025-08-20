-- PostgreSQL with TimescaleDB

CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS station (
  id serial PRIMARY KEY,
  name VARCHAR(10) UNIQUE NOT NULL,
  timezone VARCHAR(50) NOT NULL DEFAULT 'UTC'
);
CREATE TABLE IF NOT EXISTS wind_obs (
  station_id integer references station (id),
  update_time timestamp,
  direction numeric,
  speed_kts numeric,
  gust_kts numeric,
  PRIMARY KEY (station_id, update_time)
);

SELECT create_hypertable('wind_obs','update_time');

-- WindBurglr PostgreSQL Stored Procedures
-- These functions encapsulate common queries for better performance and maintainability

-- 1. Historical wind data by station and time range
CREATE OR REPLACE FUNCTION get_wind_data_by_station_range(
    station_name TEXT,
    start_time TIMESTAMP,
    end_time TIMESTAMP
) RETURNS TABLE (
    update_time TIMESTAMP,
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
    update_time TIMESTAMP,
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
