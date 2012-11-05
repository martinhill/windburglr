-- PostgreSQL
DROP TABLE obs;
CREATE TABLE obs (station text, direction numeric, speed_kts numeric, gust_kts numeric, update_time timestamp);
CREATE UNIQUE INDEX obs_idx on obs (station, update_time);

