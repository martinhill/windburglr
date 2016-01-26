#!/usr/bin/python

import os
import sys
try:
    from bs4 import BeautifulSoup
except ImportError:
    sys.path.append(os.path.join(os.getcwd(), 'site-packages'))
    from bs4 import BeautifulSoup
import re
import time
from datetime import datetime
# import psycopg2
import json
import requests
import argparse
from functools import partial
from porc import Client

url_base = "http://atm.navcanada.ca/atm/iwv/"
station_default = 'CYTZ'
default_db = 'postgres://localhost'
endopint_default = 'http://windburglr.aws.af.cm/wind'

refresh_rate_default = 58
socket_timeout = 15

wind_dir_re = re.compile('Wind Direction:')
wind_speed_re = re.compile('Wind Speed:')
wind_gust_re = re.compile('Gusting:')
updated_re = re.compile('Updated:')
error_time_fmt = '%m-%d %H:%M:%S'

value_lookup = {'': None, 'CALM': 0, '?': None, '--': None}


def coerce_int(x):
    try:
        return value_lookup[x]
    except KeyError:
        return int(x)


def find_iids_text_in_soup(soup, text):
    return soup.find_all(text=text)[0].next_element.next_element.text.strip()


def scrapeIIDSWebView(url):
    "Returns the wind data as tuple (direction, speed, gust, datetime)"
    response = requests.get(url, timeout=socket_timeout)
    soup = BeautifulSoup(response.text, "html.parser")
    wind_dir = None
    wind_dir_text = None
    wind_speed = None
    wind_speed_text = None
    wind_gust = None
    wind_gust_text = None
    find_iids_text = partial(find_iids_text_in_soup, soup)

    # Wind direction
    try:
        wind_dir_text = find_iids_text(wind_dir_re)
        wind_dir = coerce_int(wind_dir_text)
    except ValueError as ex:
        sys.stderr.write('ValueError %s: wind_dir_text="%s"\n' % (str(ex), wind_dir_text))

    # Wind speed
    try:
        wind_speed_text = find_iids_text(wind_speed_re)
        wind_speed = coerce_int(wind_speed_text)
    except ValueError as ex:
        sys.stderr.write('ValueError %s: wind_speed_text="%s"\n' % (str(ex), wind_speed_text))

    # Wind gust
    try:
        wind_gust_text = find_iids_text(wind_gust_re)
        wind_gust = coerce_int(wind_gust_text.strip('G'))
    except ValueError as ex:
        sys.stderr.write('ValueError %s: wind_gust_text="%s"\n' % (str(ex), wind_gust_text))

    # Update date/time
    try:
        updated_text = find_iids_text(updated_re)
        updated = datetime.strptime(updated_text, '%Y-%m-%d %H:%M:%SZ')
    except ValueError as ex:
        sys.stderr.write('ValueError %s: updated_text="%s"\n' % (str(ex), updated_text))
        updated = None

    return (wind_dir, wind_speed, wind_gust, updated)


def writeObservation(c, obs):
    "Write an observation to the database"
    c.execute("""INSERT INTO obs (station, direction, speed_kts, gust_kts, update_time) 
        VALUES (%s, %s, %s, %s, %s)""", obs)


def post_observation(endpoint, obs):
    "POST the observation to the service endpoint"
    payload = json.dumps({
        'station': obs[0],
        'direction': obs[1],
        'speed_kts': obs[2],
        'gust_kts': obs[3],
        'update_time': obs[4].strftime('%Y-%m-%d %H:%M:%S'),
    })
    print(str(payload))
    r = requests.post(endpoint, data=payload, headers={"Content-type": "application/json"})
    r.raise_for_status()
    return r


def post_orc_event(client, obs):
    event = {
        'direction': obs[1],
        'speed_kts': obs[2],
        'gust_kts': obs[3],
    }
    print('{}: {}'.format(obs[4], event))
    client.post_event('obs', obs[0], 'obs', event, timestamp=obs[4])


def run(conn, station, endpoint, orc_client, refresh_rate=60):
    "Loop indefinitely scraping the data and writing to the connection c"
    last_obs_time = None
    # c = conn.cursor()
    while True:
        try:
            obs = scrapeIIDSWebView(url_base + station)
        except Exception as ex:
            sys.stderr.write('%s %s in scrapeIIDSWebView(%s): %s\n' %
                             (datetime.now().strftime(error_time_fmt), type(ex).__name__,
                              url_base + station, str(ex)))
            time.sleep(refresh_rate)
        else:
            # Ensure the observation is new (check update time)
            if last_obs_time is None or obs[3] > last_obs_time:
                if obs[0] is not None or obs[1] is not None:
                    try:
                        # writeObservation(c, (station,) + obs)
                        # post_observation(endpoint, (station,) + obs)
                        post_orc_event(orc_client, (station,) + obs)
                    except Exception as ex:
                        sys.stderr.write('%s %s in writeObservation: %s\n' %
                                         (datetime.now().strftime(error_time_fmt),
                                          type(ex).__name__, str(ex)))
                        sys.stderr.write('obs = %s\n' % str(obs))
                        # c.close()
                        # conn.rollback()
                        # c = conn.cursor()
                    else:
                        # conn.commit()
                        last_obs_time = obs[3]
                    finally:
                        time.sleep(refresh_rate)
                else:
                    print('Skipping observation %s' % str(obs))
                    time.sleep(refresh_rate / 2)
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
        except KeyError as ke:
            print("VCAP_SERVICES = %s" % str(services))
            raise ke
        database = creds['name']
        username = creds['username']
        password = creds['password']
        hostname = creds['hostname']
        port = creds['port']

        uri = "postgres://%s:%s@%s:%d/%s" % (
            creds['username'],
            creds['password'],
            creds['hostname'],
            creds['port'],
            creds['name'])
    else:
# Try heroku / localhost
        # urlparse.uses_netloc.append("postgres")
        uri = os.environ.get("DATABASE_URL", default_db)
        url = urllib.parse.urlparse(uri)
        database = url.path[1:]
        username = url.username
        password = url.password
        hostname = url.hostname
        port = url.port

    print("Connecting to database: %s" % uri)

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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-t', '--target', type=str, help='target endpoint', default=endopint_default)
    parser.add_argument(
        '-k' '--api-key', type=str, help='Orchistrate API key',
        default=os.environ.get('ORCHESTRATE_API_KEY'))
    args = parser.parse_args()

    # conn = getdb()
    # init_db(conn)
    orc_client = Client(args.k__api_key)
    run(None, station_default, args.target, orc_client)
    # conn.close()


if __name__ == '__main__':
    main()
