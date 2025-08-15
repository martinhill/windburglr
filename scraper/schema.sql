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

INSERT INTO station (name, timezone) VALUES ('CYTZ', 'America/Toronto');

-- Copy old data
-- \copy wind_obs from '~/Downloads/wind_obs.csv' DELIMITER ',' CSV HEADER NULL AS 'NULL'
