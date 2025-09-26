# Windburglr scraper

This sub-project is responsible for scraping wind data from various sources and storing it in the database.

## Operation

The scraper fetches wind observation data from one or more configured stations in a continuous loop. For each station, it performs the following steps:

1.  **Fetch**: It makes an HTTP request to the station's configured URL to retrieve the latest wind data.
2.  **Parse**: It parses the raw data (JSON is currently supported) to extract the wind direction, speed, gust, and timestamp.
3.  **Store**: It stores the parsed data in a PostgreSQL database.

The scraper is designed to be resilient, with a retry mechanism for network errors and the ability to handle stale data. It also tracks the status of each station and can report errors to the database.

## Configuration

The scraper is configured through a TOML file (e.g., `windburglr.toml.example`). The configuration file is divided into two sections: `general` and `stations`.

### General Configuration

The `general` section contains the following parameters:

-   `log_level`: The logging level (e.g., `INFO`, `DEBUG`).
-   `refresh_rate`: The number of seconds to wait between scraping cycles.
-   `db_url`: The URL of the PostgreSQL database. This can also be provided via the `--database-url` command-line argument or the `DATABASE_URL` environment variable.
-   `output_mode`: The output mode. Can be `postgres` (to store data in a PostgreSQL database) or `stdout` (to print data to the console).

### Station Configuration

The `stations` section is a list of one or more stations to scrape. Each station has the following parameters:

-   `name`: The name of the station (e.g., `CYTZ`).
-   `url`: The URL of the station's wind data feed.
-   `timeout`: The timeout in seconds for the HTTP request.
-   `headers`: A table of HTTP headers to include in the request.
-   `parser`: The parser to use for the data feed. Currently, only `json` is supported.
-   `direction_path`: The path to the wind direction value in the JSON data.
-   `speed_path`: The path to the wind speed value in the JSON data.
-   `gust_path`: The path to the wind gust value in the JSON data.
-   `time_format`: The format of the timestamp in the data feed.
-   `timezone`: The timezone of the timestamp in the data feed.
-   `local_timezone`: The local timezone of the station.
-   `stale_data_timeout`: The minimum elapsed time in seconds before data is considered stale.

## Error Handling

The scraper has robust error handling and can recover from transient errors. It catches and logs various exceptions, including:

-   HTTP errors
-   Parsing errors
-   Network timeouts
-   Stale data

The scraper also uses Sentry for error reporting. To enable Sentry, create a `.env.sentry` file with the following environment variables:

-   `SENTRY_DSN`: Your Sentry DSN.
-   `SENTRY_ENVIRONMENT`: The Sentry environment (e.g., `production`, `development`).
-   `SENTRY_RELEASE`: The Sentry release.

## Development Environment

### Requirements

- Python 3.13 or later
- UV
- Postgres with TimescaleDB (for storage - optional)

For the best development experience, use Nix to set up a complete development environment. This is the recommended approach as it automatically provides a PostgreSQL database for running integration tests.

1.  **Install Nix**: Follow the instructions at https://nixos.org/download.html to install Nix.

2.  **Enable Flakes**: If you haven't already, enable Nix flakes:
    ```bash
    echo "experimental-features = nix-command flakes" >> ~/.config/nix/nix.conf
    ```

3.  **Enter the Development Environment**:
    ```bash
    nix develop
    ```
    Or, if you use `direnv`:
    ```bash
    direnv allow
    ```

The Nix environment will automatically:
- Set up Python 3.13 with all dependencies
- Initialize a PostgreSQL 15 database
- Configure development tools (pyright, ruff, etc.)
- Create a Python virtual environment
- Install all Python dependencies

## Running

```bash
# Install dependencies
uv pip install -e .

# Run the scraper with default configuration from ./windburglr.toml
scraper

# Run the scraper with a custom configuration file
scraper --config-file custom.windburglr.toml
```

You can also use the `--help` flag to see a list of all available command-line arguments:

```bash
scraper --help
```

## Testing

To run the tests, you need to have pytest installed. You can then run the tests using the following command:

```bash
pytest
```

This will run all the unit and integration tests. You can also run specific tests by providing a path to a test file or directory. For example:

```bash
# Install dev dependencies
uv sync --extra dev

# Run all tests in the tests/unit directory
pytest tests/unit

# Run a specific test file
pytest tests/unit/test_scraper.py
```

**Note**: The integration tests require a running PostgreSQL database. The recommended way to run the tests is within the Nix development environment, which automatically provides a PostgreSQL database.
