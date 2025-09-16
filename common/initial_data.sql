-- Insert default station
--
INSERT INTO station (name, timezone) VALUES ('CYTZ', 'America/Toronto');

-- Initialize scraper status for default station
-- This will be updated by the scraper as it runs
INSERT INTO scraper_status (station_id, status)
SELECT id, 'unknown' FROM station WHERE name = 'CYTZ';
