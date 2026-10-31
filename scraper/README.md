# Windburglr scraper

Scrapes wind observations from the configured stations and stores them in the database, where
the webapp picks them up.

## Operation

The scraper fetches every configured station concurrently, once per `refresh_rate` seconds.
For each station it:

1.  **Fetches** the station's URL.
2.  **Decodes and parses** the response: optionally base64-decodes and AES-256-CBC-decrypts it,
    then extracts direction, speed, gust and timestamp from the JSON.
3.  **Stores** new observations in PostgreSQL (or prints them, with `output_mode = "stdout"`)
    and records the station's status in the `scraper_status` table, which the webapp shows.

## Configuration

The scraper reads its configuration from the `SCRAPER_CONFIG` environment variable
(base64-encoded TOML, as deployed) or, when that is unset, from `--config-file` (default
`windburglr.toml`). See `windburglr.toml.example`. Station configs are kept out of the
repository; see [Deployment](../README.md#deployment).

### `[general]`

-   `log_level`: logging level (e.g. `INFO`, `DEBUG`); `--log-level` overrides it.
-   `refresh_rate`: seconds between scraping cycles (default `60`).
-   `db_url`: PostgreSQL URL. `--database-url` and then `DATABASE_URL` take precedence.
-   `output_mode`: `postgres` (default) or `stdout`.

### `[[stations]]`

-   `name`: station name (e.g. `CYTZ`).
-   `url`: URL of the station's wind data feed.
-   `local_timezone` (required): the station's local timezone, e.g. `America/Toronto`.
-   `timeout`: request timeout in seconds (default `15`).
-   `headers`: table of HTTP headers to send.
-   `direction_path`, `speed_path`, `gust_path`, `timestamp_path`: dot-separated paths to the
    values in the JSON (defaults `direction`, `speed`, `gust`, `timestamp`).
-   `timestamp_format`: [`strptime` format](https://docs.python.org/3/library/datetime.html#strftime-and-strptime-format-codes)
    of the timestamp (default `%Y-%m-%d %H:%M`).
-   `timezone`: timezone of the feed's timestamps (default `UTC`).
-   `stale_data_timeout`: seconds without a new observation before the station is reported
    stale (default `300`).
-   `encoding`: `base64` if the response is base64-encoded.
-   `encryption`: `aes256cbc` if the (decoded) response is encrypted, with the 16-byte IV
    prepended. Requires:
    -   `key_url`: page to fetch the key from;
    -   `key_extract_regex`: regex whose first group extracts the key;
    -   `key_asset_regex` (optional): regex whose first group finds an asset (e.g. a
        content-hashed JS bundle) on the `key_url` page; the asset is fetched and
        `key_extract_regex` is applied to it instead.

For example, given this response:

```json
{
  "sensor_data": {
    "SENSOR_ID": {
      "wind_direction": "180",
      "wind_speed": "15.5",
      "wind_gust": "20.0",
      "updated": "2024-01-01 12:00"
    }
  }
}
```

configure the paths as:

```toml
direction_path = "sensor_data.SENSOR_ID.wind_direction"
speed_path = "sensor_data.SENSOR_ID.wind_speed"
gust_path = "sensor_data.SENSOR_ID.wind_gust"
timestamp_path = "sensor_data.SENSOR_ID.updated"
```

## Error handling

A failing station doesn't stop the others. Errors are recorded in `scraper_status`
(`http_error`, `parse_error`, `network_error`, `stale_data`, `error`) and logged:

-   Connection errors and timeouts are retried (up to 10 times, 5 seconds apart). HTTP error
    statuses are not retried within a cycle.
-   Repeated observations are ignored until `stale_data_timeout` passes, then the station is
    reported stale.
-   Configuration errors (the payload no longer matches the config, or the decryption key
    can't be found or no longer works) need a code or config change, so they're reported to
    Sentry as errors with the station's config attached.

Sentry is enabled when `SENTRY_DSN` is set, from the environment or a `.env.sentry` file,
along with `SENTRY_ENVIRONMENT` and `SENTRY_RELEASE`. `SENTRY_TRACES_SAMPLE_RATE` (default
`0.1`) and `SENTRY_PROFILES_SAMPLE_RATE` (default `0.0`, off) set the fraction of transactions
traced and of traced transactions profiled, 0.0-1.0.

## Development

The root Nix flake provides Python 3.13, uv and PostgreSQL. Enter it with
`nix develop ..#scraper` or direnv (`direnv allow`); see
[Development environment](../README.md#development-environment) for the shared database.

```bash
../scripts/db.sh up                   # start the shared PostgreSQL cluster
uv sync                               # install dependencies
uv run scraper --config-file my.toml  # run; --help lists the options
```

Locally, connect as the `scraper` role for production-like permissions:
`--database-url postgresql://scraper@/windburglr_dev`.

## Testing

```bash
uv run pytest                         # unit and integration tests
uv run pytest tests/unit/test_scraper.py
uv run ruff check .
```

The integration tests need the shared database: each session clones its own database from the
template and drops it afterwards. pytest settings live in `pyproject.toml`; pytest-asyncio runs
in strict mode, so async tests need `@pytest.mark.asyncio`. Coverage reports are written to
`htmlcov/` and `coverage.xml`; pass `--no-cov` to skip them.

## To do

-   Logging messages are missing at startup
-   Review and fix the generated test code
