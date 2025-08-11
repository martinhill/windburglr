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
