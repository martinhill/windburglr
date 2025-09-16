import argparse
import asyncio
import logging
import os

from .config import Config, load_config_from_toml
from .database import (
    DatabaseHandler,
    handle_postgres,
    handle_status_postgres,
)
from .models import WindburglrError, WindObs
from .scraper import (
    OutputHandler,
    Scraper,
    StatusHandler,
    WebRequesterContext,
    create_json_parser,
)

logger = logging.getLogger(__name__)

async def handle_stdout(obs: WindObs):
    speed_str = f'{obs.speed}-{obs.gust}' if obs.gust else f'{obs.speed}'
    print(f'{obs.station}: {obs.direction} deg, {speed_str} kts, {obs.timestamp}')

async def handle_status_stdout(station: str, status: str, error_message: str | None):
    if error_message:
        print(f"Error: {station} - {status}: {error_message}")
    else:
        print(f"Status: {station} - {status}")


class StdoutHandler:
    def __init__(self, config: Config):
        self.config = config

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


def create_output_handler(config: Config, handler: DatabaseHandler | StdoutHandler) -> OutputHandler:
    if config.output_mode == "postgres":
        return lambda obs: handle_postgres(obs, handler)
    else:
        return handle_stdout

def create_status_handler(config: Config, handler: DatabaseHandler | StdoutHandler) -> StatusHandler:
    if config.output_mode == "postgres":
        return lambda station, status, msg: handle_status_postgres(station, status, msg, handler)
    else:
        return handle_status_stdout


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config-file', type=str, default='windburglr.toml', help='Path to config file')
    parser.add_argument('--log-file', type=str, default='', help='Path to log file')
    parser.add_argument('--log-level', type=str, default='', help='Log level')
    parser.add_argument('--database-url', type=str, default='', help='Database URL')
    args = parser.parse_args()

    logger.info("Loading config")

    if os.path.exists(args.config_file):
        config = load_config_from_toml(args.config_file)
    else:
        logger.error(f"Config file {args.config_file} not found")
        return

    log_level = args.log_level or config.log_level
    logger.info("Log level: %s", log_level)
    from . import logger as package_logger
    package_logger.setLevel(getattr(logging, log_level, logging.INFO))
    if args.log_file:
        handler = logging.FileHandler(args.log_file)
        handler.setLevel(getattr(logging, log_level, logging.INFO))
        package_logger.addHandler(handler)
    logger.debug("Config = %s", config)

    # DB URL order of precedence: command line, environment variable, config file
    config.db_url = args.database_url or os.environ.get('DATABASE_URL') or config.db_url

    output_handler_cls_map = {
        'stdout': StdoutHandler,
        'postgres': DatabaseHandler,
    }
    try:
        output_handler_cls = output_handler_cls_map[config.output_mode]
    except KeyError:
        logger.error("Invalid output mode: %s", config.output_mode)
        return

    async with WebRequesterContext(config) as requester_builder, output_handler_cls(config) as output_ctx:
        Scraper.set_output_handler(create_output_handler(config, output_ctx))
        Scraper.set_status_handler(create_status_handler(config, output_ctx))

        scrapers = [
            Scraper.create(
                station_config,
                requester_builder.create_requester(station_config),
                create_json_parser(station_config),
            ) for station_config in config.stations
        ]

        logger.info("Starting main loop")
        while True:
            tasks = [scraper.fetch_and_process() for scraper in scrapers]
            # Run the scrapers in parallel
            logger.debug("Running all %s scrapers", len(scrapers))
            results = await asyncio.gather(*tasks, asyncio.sleep(config.refresh_rate), return_exceptions=True)
            # Check for errors
            for result in results:
                if isinstance(result, WindburglrError):
                    logger.warning('Handled exception: %s', result)
                elif isinstance(result, Exception):
                    # Unexpected exception
                    logger.error('Oh crap! Unexpected exception: %s', result)
                    raise result
