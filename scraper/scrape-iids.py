import os
import sys
from bs4 import BeautifulSoup
import re
import time
from datetime import datetime
import json
import requests
import argparse
from functools import partial
from porc import Client
from sshtunnel import SSHTunnelForwarder
import pymysql


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


def insert_obs(c, obs):
    "Insert an observation to the database"
    c.execute("""INSERT INTO wind_obs (station_id, direction, speed_kts, gust_kts, update_time)
        VALUES ((SELECT id FROM station WHERE name = %s), %s, %s, %s, %s)""", obs)


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
    client.post_event('obs', obs[0], 'obs', event, timestamp=obs[4])
    return event


def generate_obs(station, endpoint, refresh_rate=60):
    "Loop indefinitely scraping the data and writing to the obs_writer"
    last_obs_time = None
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
                    yield (station,) + obs
                    time.sleep(refresh_rate)
                    last_obs_time = obs[3]
                else:
                    print('Skipping observation %s' % str(obs))
                    time.sleep(refresh_rate / 2)
            else:
                # sleep half the refresh time when we get a duplicate
                time.sleep(refresh_rate / 2)


def init_db(db, schema_file='schema_mysql.sql'):
    "Initialize the database"
    with open(schema_file) as f:
        db.cursor().execute(f.read())
    db.commit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-t', '--target', type=str, help='target endpoint', default=endopint_default)
    parser.add_argument(
        '-k', '--api-key', type=str, help='Orchistrate API key',
        default=os.environ.get('ORCHESTRATE_API_KEY'))
    parser.add_argument(
        '--ssh-host', type=str, help='SSH host',
        default=os.environ.get('SSH_HOST', 'ssh.pythonanywhere.com'))
    parser.add_argument(
        '--ssh-user', type=str, help='SSH user',
        default=os.environ.get('SSH_USER', 'martinh'))
    parser.add_argument(
        '--ssh-pkey', type=str, help='SSH private key file',
        default=os.environ.get('SSH_PKEY'))
    parser.add_argument(
        '--mysql-host', type=str, help='MySQL host',
        default=os.environ.get('MYSQL_HOST', 'martinh.mysql.pythonanywhere-services.com'))
    parser.add_argument(
        '--mysql-user', type=str, help='MySQL user',
        default=os.environ.get('MYSQL_USER', 'martinh'))
    parser.add_argument(
        '--mysql-db', type=str, help='MySQL database',
        default=os.environ.get('MYSQL_DB', 'martinh$windburglr'))
    parser.add_argument(
        '--mysql-password', type=str, help='MySQL password',
        default=os.environ.get('MYSQL_PASSWORD'))
    args = parser.parse_args()

    # Connect to databases
    print('Connecting to Orchestrate')
    orc_client = Client(args.api_key)
    with SSHTunnelForwarder(
        (args.ssh_host),
        remote_bind_address=(args.mysql_host, 3306),
        local_bind_address=('localhost', 3306),
        ssh_username=args.ssh_user,
        ssh_pkey=args.ssh_pkey,
        ) as tunnel:
        time.sleep(1)
        print('Connecting to PythonAnywhere MySQL')
        conn = pymysql.connect(
            host='localhost', user=args.mysql_user, password=args.mysql_password, db=args.mysql_db)
        cursor = conn.cursor()
        print('Starting...')

        # MAIN LOOP

        for obs in generate_obs(station_default, args.target):
            print(obs)

            # Send to PythonAnywhere mysql
            try:
                insert_obs(cursor, obs)
            except Exception as ex:
                sys.stderr.write('%s %s in insert_obs: %s\n' %
                                 (datetime.now().strftime(error_time_fmt),
                                  type(ex).__name__, str(ex)))
                sys.stderr.write(f'obs = {obs}\n')
                cursor.close()
                conn.rollback()
                cursor = conn.cursor()
            else:
                conn.commit()

            # Send to AppFog Orchestrate
            event = post_orc_event(orc_client, obs)
            print(f'{obs[4]}: {event}')

            # Check the tunnel
            tunnel.check_tunnels()
            if not all(tunnel.tunnel_is_up.values()):
                print(f'Terminating: tunnel_is_up = {tunnel.tunnel_is_up}')
                break

    # conn.close()


if __name__ == '__main__':
    main()
