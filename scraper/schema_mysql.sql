-- MySQL
CREATE TABLE IF NOT EXISTS station (
	id INT NOT NULL AUTO_INCREMENT,
    name VARCHAR(10) NOT NULL, 
    PRIMARY KEY (id)
);
CREATE TABLE IF NOT EXISTS wind_obs (
	id INT NOT NULL AUTO_INCREMENT,
	station_id INT NOT NULL,
    direction DECIMAL(3,0) NOT NULL, 
    speed_kts DECIMAL(3,1) NOT NULL, 
    gust_kts DECIMAL(3,1), 
    update_time timestamp NOT NULL, 
    CONSTRAINT wind_obs_pkey PRIMARY KEY (id),
    FOREIGN KEY (station_id) REFERENCES station(id)
    	ON DELETE RESTRICT,
    CONSTRAINT wind_obs_station_update_time UNIQUE KEY (station_id, update_time)
);
