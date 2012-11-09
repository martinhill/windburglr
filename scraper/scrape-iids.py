#!/usr/bin/python

import os
import sys
try:
    from bs4 import BeautifulSoup
except ImportError, ie:
    sys.path.append(os.path.join(os.getcwd(), 'site-packages'))
    from bs4 import BeautifulSoup
import urllib2
import re
import time
from datetime import datetime
import psycopg2
import json
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

value_lookup = { '':None, 'CALM':0, '?':None, '--':None }
coerce_int = lambda x: value_lookup[x] if value_lookup.has_key(x) else int(x)

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
    find_iids_text = lambda expr: soup.find_all(text=expr)[0].next_element.next_element.text.strip()

    # Wind direction
    try:
        wind_dir_text = find_iids_text(wind_dir_re)
        wind_dir = coerce_int(wind_dir_text)
    except ValueError, ex:
        sys.stderr.write('ValueError %s: wind_dir_text="%s"\n' % (str(ex), wind_dir_text))
    
    # Wind speed
    try:
        wind_speed_text = find_iids_text(wind_speed_re)
        wind_speed = coerce_int(wind_speed_text)
    except ValueError, ex:
        sys.stderr.write('ValueError %s: wind_speed_text="%s"\n' % (str(ex), wind_speed_text))

    # Wind gust
    try:
        wind_gust_text = find_iids_text(wind_gust_re)
        wind_gust = coerce_int(wind_gust_text)
    except ValueError, ex:
        sys.stderr.write('ValueError %s: wind_gust_text="%s"\n' % (str(ex), wind_gust_text))
    
    # Update date/time
    try:
        updated_text = find_iids_text(updated_re)
        updated = datetime.strptime(updated_text, '%Y-%m-%d %H:%M:%SZ')
    except ValueError, ex:
        sys.stderr.write('ValueError %s: updated_text="%s"\n' % (str(ex), updated_text))
        updated = None

    return (wind_dir, wind_speed, wind_gust, updated)


def writeObservation(c, obs):
    "Write an observation to the database"
    c.execute("""INSERT INTO obs (station, direction, speed_kts, gust_kts, update_time) 
        VALUES (%s, %s, %s, %s, %s)""", obs)


def run(conn, station, refresh_rate=60):
    "Loop indefinitely scraping the data and writing to the connection c"
    last_obs_time = None
    c = conn.cursor()
    while True:
        try:
            obs = scrapeIIDSWebView(url_base + station)
        except Exception, ex:
            sys.stderr.write('%s %s in scrapeIIDSWebView(%s): %s\n' %
                (datetime.now().strftime(error_time_fmt), type(ex).__name__, 
                url_base+station, str(ex)))
            time.sleep(refresh_rate)
        else:
            # Ensure the observation is new (check update time)
            if last_obs_time is None or obs[3] > last_obs_time:
                if obs[0] is not None or obs[1] is not None:
                    try:
                        writeObservation(c, (station,) + obs)
                    except Exception, ex:
                        sys.stderr.write('%s %s in writeObservation: %s\n' % 
                            (datetime.now().strftime(error_time_fmt), 
                            type(ex).__name__, str(ex)) )
                        sys.stderr.write('obs = %s\n' % str(obs))
                        c.close()
                        conn.rollback()
                        c = conn.cursor()
                    else:
                        conn.commit()
                        last_obs_time = obs[3]
                    finally:
                        time.sleep(refresh_rate)
                else:
                    print 'Skipping observation %s' % str(obs)
            else:
                # sleep half the refresh time when we get a duplicate
                time.sleep(refresh_rate / 2)


def getdb():
    "Get the database connection. Auto-detects heroku, appfog, or local environment"

# Try appfog 
    services = json.loads(os.environ.get("VCAP_SERVICES", "{}"))
    if services:
        try:
            creds = services['postgresql-9.1'][0]['credentials']
        except KeyError, ke:
            print >> sys.stderr, "VCAP_SERVICES = %s" % str(services)
            raise ke
        database = creds['name']
        username = creds['username']
        password = creds['password']
        hostname = creds['hostname']
        port     = creds['port']

        uri = "postgres://%s:%s@%s:%d/%s" % (
            creds['username'],
            creds['password'],
            creds['hostname'],
            creds['port'],
            creds['name'])
    else:
# Try heroku / localhost
        urlparse.uses_netloc.append("postgres")
        uri = os.environ.get("DATABASE_URL", default_db)
        url = urlparse.urlparse(uri)
        database = url.path[1:]
        username = url.username
        password = url.password
        hostname = url.hostname
        port     = url.port

    print >> sys.stderr, "Connecting to database: %s" % uri

    return psycopg2.connect(
        database=database,
        user=username,
        password=password,
        host=hostname,
        port=port
    )

def init_db(db):
    "Initialize the database"
    with open('schema.sql') as f:
        db.cursor().execute(f.read())
    db.commit()

if __name__ == '__main__':
    conn = getdb()
    init_db(conn)   
    run(conn, station_default)
    conn.close()

