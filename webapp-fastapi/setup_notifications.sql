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
