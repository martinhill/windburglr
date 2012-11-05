#!/usr/bin/python

import os
import sys
from bs4 import BeautifulSoup
import urllib2
import re
import time
from datetime import datetime
import psycopg2
import urlparse

url_base = "http://atm.navcanada.ca/atm/iwv/"
station_default = 'CYTZ'
default_db = 'postgres://localhost'

refresh_rate_default = 60

wind_dir_re = re.compile('Wind Direction:')
wind_speed_re = re.compile('Wind Speed:')
wind_gust_re = re.compile('Gusting:')
updated_re = re.compile('Updated:')
error_time_fmt = '%m-%d %H:%M:%S'


def scrapeIIDSWebView(url):
    "Returns the wind data as tuple (direction, speed, gust, datetime)"
    response = urllib2.urlopen(url)
    html = response.read()
    response.close()
    soup = BeautifulSoup(html)
    wind_dir = None
    wind_dir_text = None
    wind_speed = None
    wind_speed_text = None
    wind_gust = None
    wind_gust_text = None

    # Wind direction
    try:
        wind_dir_elmt = soup.find_all(text=wind_dir_re)
        wind_dir_text = wind_dir_elmt[0].next_element.next_element.text.strip()
        wind_dir = len(wind_dir_text) > 0 and int(wind_dir_text) or None
    except ValueError, ex:
        sys.stderr.write('ValueError %s: wind_dir_text="%s"\n' % (str(ex), wind_dir_text))
    
    # Wind speed
    try:
        wind_speed_elmt = soup.find_all(text=wind_speed_re)
        wind_speed_text = wind_speed_elmt[0].next_element.next_element.text.strip()
        wind_speed = len(wind_speed_text) > 0 and wind_speed_text != 'CALM' \
            and int(wind_speed_text) or None
    except ValueError, ex:
        sys.stderr.write('ValueError %s: wind_speed_text="%s"\n' % (str(ex), wind_speed_text))

    # Wind gust
    try:
        wind_gust_elmt = soup.find_all(text=wind_gust_re)
        wind_gust_text = wind_gust_elmt[0].next_element.next_element.text.strip()
        wind_gust = len(wind_gust_text) > 0 and wind_gust_text != '--' and \
            int(wind_gust_text.strip('G')) or None
    except ValueError, ex:
        sys.stderr.write('ValueError %s: wind_gust_text="%s"\n' % (str(ex), wind_gust_text))
    
    # Update date/time
    try:
        updated_elmt = soup.find_all(text=updated_re)
        updated_text = updated_elmt[0].next_element.next_element.text
        updated = datetime.strptime(updated_text, '%Y-%m-%d %H:%M:%SZ')
    except ValueError, ex:
        sys.stderr.write('ValueError %s: updated_text="%s"\n' % (str(ex), updated_text))
        updated = None

    return (wind_dir, wind_speed, wind_gust, updated)


def writeObservation(c, obs):
    "Write an observation to the database"
    c.execute("""INSERT INTO obs (station, direction, speed_kts, gust_kts, update_time) 
        VALUES (%s, %s, %s, %s, %s)""", obs)


def run(c, station, refresh_rate=60):
    "Loop indefinitely scraping the data and writing to the connection c"
    last_obs_time = None
    while True:
        obs = scrapeIIDSWebView(url_base + station)
        try:
            obs = scrapeIIDSWebView(url_base + station)
        except Exception, ex:
            sys.stderr.write('%s Error in scrapeIIDSWebView(%s): %s\n' %
                (datetime.now().strftime(error_time_fmt), url_base+station, str(ex)))
            time.sleep(refresh_rate)
        else:
            # Ensure the observation is new (check update time)
            if last_obs_time is None or obs[3] > last_obs_time:
                try:
                    writeObservation(c, (station,) + obs)
                except Exception, ex:
                    sys.stderr.write('%s Error in writeObservation: %s\n' % 
                        (datetime.now().strftime(error_time_fmt), str(ex)) )
                    sys.stderr.write('obs = %s\n' % str(obs))
                else:
                    conn.commit()
                    last_obs_time = obs[3]
                finally:
                    time.sleep(refresh_rate)
            else:
                # sleep half the refresh time when we get a duplicate
                time.sleep(refresh_rate / 2)


if __name__ == '__main__':
    urlparse.uses_netloc.append("postgres")
    url = urlparse.urlparse(os.getenv("DATABASE_URL") or default_db)

    conn = psycopg2.connect(
        database=url.path[1:],
        user=url.username,
        password=url.password,
        host=url.hostname,
        port=url.port
    )
    
    c = conn.cursor()
    run(c, station_default)
    conn.close()

