import argparse
import asyncio
import json
import os
import sys
from collections import namedtuple
from datetime import datetime

import aiohttp
import asyncpg

WindObs = namedtuple('WindObs',
                     ['station', 'direction', 'speed', 'gust', 'timestamp'])
url_base = "https://spaces.navcanada.ca/service/iwv/api/collator/v2/"
station_default = 'CYTZ'

refresh_rate_default = 60
socket_timeout = 15

error_time_fmt = '%m-%d %H:%M:%S'

value_lookup = {'': None, 'CALM': 0, '?': None, '--': None}


class WindburglrException(Exception):
  pass


class MaxRetriesExceeded(WindburglrException):
  pass


class StaleWindObservation(WindburglrException):
  pass


def coerce_int(x):
  try:
    return value_lookup[x]
  except KeyError:
    return int(x)


def scrape_aeroview_json(resp_data: dict, station: str):
  """Returns the wind data as tuple (direction, speed, gust, datetime)"""

  sensor_data = resp_data['v2']['sensor_data'][station]

  # Wind direction
  wind_dir = sensor_data.get('wind_magnetic_dir_2_mean')

  # Wind speed
  wind_speed = sensor_data.get('wind_speed_2_mean') or 0

  # Wind gust
  wind_gust = sensor_data.get('gust_squall_speed')

  # Update date/time
  updated_text = sensor_data.get('observation_time')
  try:
    updated = datetime.strptime(updated_text, '%Y-%m-%d %H:%M')
  except ValueError as ex:
    sys.stdout.write('ValueError %s: updated_text="%s"\n' %
                     (str(ex), updated_text))
    raise

  return wind_dir, wind_speed, wind_gust, updated


async def insert_obs(conn: asyncpg.Connection, obs: WindObs):
  """Insert an observation to the database"""
  async with conn.transaction():
    await conn.execute(
        """
            INSERT INTO wind_obs (station_id, direction, speed_kts, gust_kts, update_time)
            VALUES (
                (SELECT id FROM station WHERE name = $1),
                $2, $3, $4, $5
            )
        """, obs.station, obs.direction, obs.speed, obs.gust, obs.timestamp)


last_obs_time = {}


def is_new_obs(obs: WindObs) -> bool:
  station_last_obs_time = last_obs_time.get(obs.station)
  return not station_last_obs_time or station_last_obs_time < obs.timestamp


def set_obs_last_timestamp(obs: WindObs):
  last_obs_time[obs.station] = obs.timestamp


async def fetch_obs(station: str,
                    session: aiohttp.ClientSession,
                    max_retries=10) -> WindObs:
  """Fetch the current observation for a station, retrying """
  retry_count = 0
  while True:
    try:
      response = await session.get(
          url_base + station,
          timeout=socket_timeout,
          headers={
              "Referer":
              f"https://spaces.navcanada.ca/workspace/aeroview/{station}/"
          })
      response.raise_for_status()
      resp_data = json.loads(await response.text())
      obs = WindObs(station, *scrape_aeroview_json(resp_data, station))
      if is_new_obs(obs):
        set_obs_last_timestamp(obs)
        return obs
      else:
        raise StaleWindObservation(
            f'stale data: station={station} timestamp={obs.timestamp}')
    except (ValueError, asyncio.exceptions.TimeoutError) as e:
      # Invalid data in page, probably temporary
      if retry_count < max_retries:
        print(f'{repr(e)}, retrying for {station}')
        await asyncio.sleep(5)
        retry_count += 1
      else:
        raise MaxRetriesExceeded(f'max retries exceeded fetching {station}')


def pretty_obs(obs: WindObs) -> str:
  return ', '.join(
      f'{field}={getattr(obs, field)}'
      for field in ['station', 'direction', 'speed', 'gust', 'timestamp'])


async def fetch_and_save(station: str, session: aiohttp.ClientSession,
                         conn: asyncpg.Connection):
  obs = await fetch_obs(station, session)
  print(pretty_obs(obs))
  await insert_obs(conn, obs)


async def fetch_and_print(station: str, session: aiohttp.ClientSession):
  obs = await fetch_obs(station, session)
  # Ensure the observation is new (check update time)
  print(pretty_obs(obs))


async def main():
  parser = argparse.ArgumentParser()
  parser.add_argument('--database_url',
                      type=str,
                      help='Database URL',
                      default=os.environ.get(
                          'DATABASE_URL',
                          'postgres://postgres:postgres@localhost/wind'))
  parser.add_argument('--postgres-host',
                      type=str,
                      help='PostgreSQL host',
                      default=os.environ.get('POSTGRES_HOST', 'localhost'))
  parser.add_argument('--postgres-user',
                      type=str,
                      help='PostgreSQL user',
                      default=os.environ.get('POSTGRES_USER', 'martinh'))
  parser.add_argument('--postgres-db',
                      type=str,
                      help='PostgreSQL database',
                      default=os.environ.get('POSTGRES_DB', 'windburglr'))
  parser.add_argument('--postgres-password',
                      type=str,
                      help='PostgreSQL password',
                      default=os.environ.get('POSTGRES_PASSWORD'))
  args = parser.parse_args()

  async with aiohttp.ClientSession() as session:

    if args.database_url:
      # Connecting to PostgreSQL
      print('Connecting to PostgreSQL')
      conn = await asyncpg.connect(args.database_url)
      print('Starting...')

      # MAIN LOOP

      while not conn.is_closed():
        tasks = [
            fetch_and_save(station, session, conn)
            for station in [station_default]
        ]
        results = await asyncio.gather(*tasks,
                                       asyncio.sleep(refresh_rate_default),
                                       return_exceptions=True)
        for result in results:
          if isinstance(result, WindburglrException):
            print('caught exception:', result)
          elif isinstance(result, Exception):
            raise result
        sys.stdout.flush()

    else:
      # No DB, just console output
      while True:
        tasks = [
            fetch_and_print(station, session)
            for station in [station_default, 'CYYZ', 'CYUL']
        ]
        results = await asyncio.gather(*tasks,
                                       asyncio.sleep(refresh_rate_default),
                                       return_exceptions=True)
        for result in results:
          if isinstance(result, WindburglrException):
            print('caught exception:', result)
          elif isinstance(result, Exception):
            raise result
        sys.stdout.flush()


if __name__ == '__main__':
  asyncio.run(main())
