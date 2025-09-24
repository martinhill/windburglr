import asyncio

import sentry_sdk
from sentry_sdk.integrations.asyncpg import AsyncPGIntegration

from . import logger
from .config import get_sentry_config
from .main import main

# Initialize Sentry
sentry_config: dict[str, str] = get_sentry_config()
if sentry_config.get("dsn"):
    sentry_sdk.init(
        dsn=sentry_config["dsn"],
        integrations=[
            AsyncPGIntegration(),
        ],
        environment=sentry_config["environment"],
        release=sentry_config["release"],
        traces_sample_rate=1.0,
        profiles_sample_rate=1.0,
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info('KeyboardInterrupt received - pulling QR!')
