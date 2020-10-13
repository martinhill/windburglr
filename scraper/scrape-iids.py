import os
import sys
from bs4 import BeautifulSoup
import re
import time
from datetime import datetime
import json
import asyncio
import aiohttp
import argparse
from functools import partial
import aiomysql
from collections import namedtuple

WindObs = namedtuple('WindObs', ['station', 'direction', 'speed', 'gust', 'timestamp'])
url_base = "http://atm.navcanada.ca/atm/iwv/"
station_default = 'CYTZ'

refresh_rate_default = 60
socket_timeout = 15

wind_dir_re = re.compile('Wind Direction:')
wind_speed_re = re.compile('Wind Speed:')
wind_gust_re = re.compile('Gusting:')
updated_re = re.compile('Updated:')
error_time_fmt = '%m-%d %H:%M:%S'

value_lookup = {'': None, 'CALM': 0, '?': None, '--': None}


class MaxRetriesExceeded(Exception):
    pass


class StaleWindObservation(Exception):
    pass


def coerce_int(x):
    try:
        return value_lookup[x]
    except KeyError:
        return int(x)


def find_iids_text_in_soup(soup, text):
    return soup.find_all(text=text)[0].next_element.next_element.text.strip()


async def scrape_iids_web_view(url, session: aiohttp.ClientSession):
    """Returns the wind data as tuple (direction, speed, gust, datetime)"""
    response = await session.get(url, timeout=socket_timeout)
    response.raise_for_status()
    soup = BeautifulSoup(await response.text(), "html.parser")
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
        sys.stdout.write('ValueError %s: wind_dir_text="%s"\n' % (str(ex), wind_dir_text))

    # Wind speed
    try:
        wind_speed_text = find_iids_text(wind_speed_re)
        wind_speed = coerce_int(wind_speed_text)
    except ValueError as ex:
        sys.stdout.write('ValueError %s: wind_speed_text="%s"\n' % (str(ex), wind_speed_text))

    # Wind gust
    try:
        wind_gust_text = find_iids_text(wind_gust_re)
        wind_gust = coerce_int(wind_gust_text.strip('G'))
    except ValueError as ex:
        sys.stdout.write('ValueError %s: wind_gust_text="%s"\n' % (str(ex), wind_gust_text))

    # Update date/time
    updated_text = find_iids_text(updated_re)
    try:
        updated = datetime.strptime(updated_text, '%Y-%m-%d %H:%M:%SZ')
    except ValueError as ex:
        sys.stdout.write('ValueError %s: updated_text="%s"\n' % (str(ex), updated_text))
        raise

    return wind_dir, wind_speed, wind_gust, updated


async def insert_obs(conn: aiomysql.Connection, obs: WindObs):
    """Insert an observation to the database"""
    c: aiomysql.cursors.Cursor = await conn.cursor()
    try:
        await c.execute("""INSERT INTO wind_obs (station_id, direction, speed_kts, gust_kts, update_time)
            VALUES ((SELECT id FROM station WHERE name = %s), %s, %s, %s, %s)""", obs)
    except Exception as ex:
        sys.stderr.write('%s %s in insert_obs: %s\n' %
                         (datetime.now().strftime(error_time_fmt),
                          type(ex).__name__, str(ex)))


last_obs_time = dict()


def is_new_obs(obs: WindObs) -> bool:
    station_last_obs_time = last_obs_time.get(obs.station)
    return not station_last_obs_time or station_last_obs_time < obs.timestamp


def set_obs_last_timestamp(obs: WindObs):
    last_obs_time[obs.station] = obs.timestamp


async def fetch_obs(station: str, session: aiohttp.ClientSession, max_retries=10) -> WindObs:
    """Fetch the current observation for a station, retrying """
    retry_count = 0
    while True:
        try:
            obs = WindObs(station, *await scrape_iids_web_view(url_base + station, session))
            if is_new_obs(obs):
                set_obs_last_timestamp(obs)
                return obs
            else:
                raise StaleWindObservation(f'stale data: station={station} timestamp={obs.timestamp}')
        except ValueError:
            # Invalid data in page, probably temporary
            if retry_count < max_retries:
                print(f'data invalid, retrying for {station}')
                await asyncio.sleep(5)
                retry_count += 1
            else:
                raise MaxRetriesExceeded(f'max retries exceeded fetching {station}')


def pretty_obs(obs: WindObs) -> str:
    return ', '.join(f'{field}={getattr(obs, field)}' for field in ['station', 'direction', 'speed', 'gust', 'timestamp'])


async def fetch_and_save(
        station: str,
        session: aiohttp.ClientSession,
        conn: aiomysql.Connection):
    obs = await fetch_obs(station, session)
    print(pretty_obs(obs))
    await insert_obs(conn, obs)


async def fetch_and_print(station: str, session: aiohttp.ClientSession):
    obs = await fetch_obs(station, session)
    # Ensure the observation is new (check update time)
    print(pretty_obs(obs))


def init_db(db, schema_file='schema_mysql.sql'):
    """Initialize the database"""
    with open(schema_file) as f:
        db.cursor().execute(f.read())
    db.commit()


async def main():
    parser = argparse.ArgumentParser()
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

    async with aiohttp.ClientSession() as session:

        # Connect to databases via ssh tunnel, running outside pythonanywhere
        if args.ssh_user and args.ssh_pkey:
            from sshtunnel import SSHTunnelForwarder
            print('pkey =', args.ssh_pkey)
            with SSHTunnelForwarder(
                    (args.ssh_host),
                    remote_bind_address=(args.mysql_host, 3306),
                    local_bind_address=('localhost', 3306),
                    ssh_username=args.ssh_user,
                    ssh_pkey=args.ssh_pkey,
            ) as tunnel:
                print('Starting...')
                time.sleep(1)
                print('Connecting to PythonAnywhere MySQL')
                conn : aiomysql.Connection = await aiomysql.connect(
                    host='localhost', user=args.mysql_user, password=args.mysql_password, db=args.mysql_db,
                    autocommit=True)

                # MAIN LOOP

                while not conn.closed:
                    tasks = [fetch_and_save(station, session, conn) for station in [station_default]]
                    results = await asyncio.gather(*tasks, asyncio.sleep(refresh_rate_default), return_exceptions=True)
                    for result in results:
                        if isinstance(result, Exception):
                            print('caught exception:', result)
                    sys.stdout.flush()

                    # Check the tunnel
                    tunnel.check_tunnels()
                    if not all(tunnel.tunnel_is_up.values()):
                        print(f'Terminating: tunnel_is_up = {tunnel.tunnel_is_up}')
                        break
                print('Finishing')
                conn.close()

        elif args.mysql_password:
            # Not using ssh tunnel, executing on pythonanywhere
            print('Connecting to MySQL:', args.mysql_host)
            conn = await aiomysql.connect(
                host=args.mysql_host, user=args.mysql_user, password=args.mysql_password, db=args.mysql_db,
                autocommit=True)
            print('Starting...')

            # MAIN LOOP

            while not conn.closed:
                tasks = [fetch_and_save(station, session, conn) for station in [station_default]]
                results = await asyncio.gather(*tasks, asyncio.sleep(refresh_rate_default), return_exceptions=True)
                for result in results:
                    if isinstance(result, Exception):
                        print('caught exception:', result)
                sys.stdout.flush()

            conn.close()

        else:
            # No DB, just console output
            while True:
                tasks = [fetch_and_print(station, session) for station in [station_default, 'CYYZ', 'CYUL']]
                results = await asyncio.gather(*tasks, asyncio.sleep(refresh_rate_default), return_exceptions=True)
                for result in results:
                    if isinstance(result, Exception):
                        print('caught exception:', result)
                sys.stdout.flush()


if __name__ == '__main__':
    asyncio.run(main())
