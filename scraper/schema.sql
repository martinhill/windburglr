-- PostgreSQL
CREATE TABLE IF NOT EXISTS wind_obs (
	id serial NOT NULL,
    station text, 
    direction numeric, 
    speed_kts numeric, 
    gust_kts numeric, 
    update_time timestamp, 
    CONSTRAINT wind_obs_pkey PRIMARY KEY (id)
    CONSTRAINT wind_obs_station_update_time UNIQUE (station, update_time)
);

