-- PostgreSQL
CREATE TABLE IF NOT EXISTS obs (
    station text, 
    direction numeric, 
    speed_kts numeric, 
    gust_kts numeric, 
    update_time timestamp, 
    CONSTRAINT obs_idx UNIQUE (station, update_time)
);

