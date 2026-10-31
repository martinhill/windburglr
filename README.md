Windburglr
==========

`Windburglr` is a mobile-friendly web application that collects and displays real-time and historical wind data from online weather stations.

This project is a monorepo containing two sub-projects:

-   **`scraper`**: A Python application responsible for scraping wind data from various sources and storing it in a database. For more details, see the [`scraper/README.md`](scraper/README.md).
-   **`webapp`**: A FastAPI web application that provides a web interface for viewing the collected wind data. It features real-time updates via WebSockets and interactive charts. For more details, see the [`webapp/README.md`](webapp/README.md).

## Development environment

A single Nix flake at the repository root provides the toolchain (Python 3.13, uv, PostgreSQL 18 with
the Apache-licensed TimescaleDB build, and Node.js 22 / pyright for the webapp). Each sub-project's
`.envrc` loads its shell (`use flake ..#webapp`, `use flake ..#scraper`); without direnv, run
`nix develop ..#webapp` (or `#scraper`, or `nix develop` at the root).

Loading the environment only sets variables (`PGHOST`, `PGUSER`, `PGDATABASE`, the virtualenv `PATH`);
it never starts anything. That keeps it cheap enough to load on every command, which is what
agent shells and direnv do. The database is managed explicitly with `scripts/db.sh` (or `make db-*`
at the root or in `webapp/`):

```bash
scripts/db.sh up          # start the cluster; build the template and dev database if needed,
                          # and apply pending migrations to the dev database
scripts/db.sh status      # list databases
scripts/db.sh reset-dev   # recreate windburglr_dev from the migrations (destroys its data)
scripts/db.sh down        # stop the cluster
```

There is one socket-only cluster (no TCP port) in `.pgdata/` of the main checkout, shared by both
sub-projects and all git worktrees. It holds:

-   **`windburglr_dev`**: persistent development database with all migrations applied, including
    the `scraper` and `webapp` roles, plus the seed data in `webapp/db/seed.sql`. Connect the apps
    as their own role, e.g. `postgresql://scraper@/windburglr_dev` and
    `postgresql://webapp@/windburglr_dev`, to get the same least-privilege permissions as
    production. `scripts/db.sh up` applies pending migrations to it. The dev database is shared by
    all worktrees, so a migration from one branch stays applied when you switch to another; run
    `reset-dev` to start over.
-   **`windburglr_template`**: all migrations applied, no data. It is rebuilt automatically
    whenever a file in `webapp/db/migrations/` is added or changed.
-   **`windburglr_test_*`**: each pytest session clones its own database from the template and drops
    it afterwards, so concurrent runs (in different worktrees, say) don't interfere. Set
    `TEST_DATABASE_URL` to use a specific database instead. `scripts/db.sh test-clean` removes
    databases left behind by aborted runs.

## Database

This project uses [PostgreSQL](https://www.postgresql.org/) 18 with the [TimescaleDB](https://www.timescale.com/)
extension (`wind_obs` is a hypertable). Production runs on Aiven. The schema includes NOTIFY
triggers, which push new observations and scraper status to the webapp, and two least-privilege
login roles:

-   **`scraper`**: upserts stations, inserts observations and updates `scraper_status`.
-   **`webapp`**: read-only access to the tables and query functions, plus `LISTEN`. It can't run DDL.

### Migrations

The schema is managed with [dbmate](https://github.com/amacneil/dbmate): plain SQL migrations in
`webapp/db/migrations/`, applied in file-name order and recorded in the `schema_migrations` table.
The first migration, `20261031000000_baseline.sql`, is the schema and roles as they were before
migrations were introduced. The migrations live in `webapp/` because the webapp's deploy applies
them, so a new migration also triggers a webapp deploy in CI. `webapp/db/seed.sql` is development
seed data, not a migration. dbmate is in the dev shell, and `dbmate` commands there default to
this migrations directory.

To change the schema:

```bash
dbmate new add_station_elevation    # creates webapp/db/migrations/<timestamp>_add_station_elevation.sql
```

1.  Write the SQL under `-- migrate:up` (and `-- migrate:down` if it can be undone). Each migration
    runs in a transaction. Grant the `scraper` and `webapp` roles whatever they need on new objects.
    Passwords never go in a migration.
2.  Run `scripts/db.sh up` to apply it to `windburglr_dev`. The test template rebuilds automatically
    the next time a test session starts.
3.  Don't edit a migration after it has been deployed; add a new one instead. dbmate never re-runs
    an applied migration, so production would never get the edit.

On deploy, migrations run before the new webapp release starts, but the scraper deploys
independently (in parallel, in CI), and old machines keep serving until they are replaced. A
migration therefore has to work with both the old and the new code of both apps:
add columns before code uses them, and drop them only after no deployed code reads them.

### Migrations on deploy

The webapp's Fly release command (`webapp/fly.toml`) runs
`dbmate --env MIGRATION_DATABASE_URL --migration-lock migrate --strict`. It runs in a temporary
machine from the new image, before the new release replaces the running machines. If it fails,
the deploy stops and the previous release keeps running. `--strict` refuses to apply a migration
whose version is older than the latest applied one. If two branches add migrations and merge in
the other order, rename the later-merged one so its timestamp is newer. `--migration-lock` stops
two releases from migrating at once.

`DATABASE_URL` uses the `webapp` role, which can't change the schema, so the release command uses
a second Fly secret on the `windburglr` app:

-   **`MIGRATION_DATABASE_URL`**: a connection URL for the role that owns the tables, `avnadmin` on
    Aiven unless you've moved ownership, e.g.
    `postgres://avnadmin:<password>@<host>:<port>/<database>?sslmode=require`. Only an owner can
    `ALTER` or `DROP` a table, so a less privileged role won't do. The role also needs
    `CREATEROLE` if a migration creates roles; `avnadmin` has it.

Fly exposes every secret to every machine of the app, so the image starts the web server with
`MIGRATION_DATABASE_URL` removed from its environment. The secret is still visible in
`fly ssh console` sessions and to the release command.

### Setting up a database

-   **New database**: run `dbmate --url "$OWNER_URL" migrate` as the role that should own the
    schema, then set the role passwords, which the migrations don't set:
    `ALTER ROLE scraper PASSWORD '...'; ALTER ROLE webapp PASSWORD '...';`.
-   **Existing database without migration history** (production when migrations were introduced,
    or a `windburglr_dev` created before them): the schema is already there, so record the baseline
    as applied instead of running it. Connect as the owner and run:

    ```sql
    CREATE TABLE IF NOT EXISTS schema_migrations (version varchar PRIMARY KEY);
    INSERT INTO schema_migrations (version) VALUES ('20261031000000');
    ```

    This is the table dbmate creates itself, so dbmate treats the baseline as applied and runs only
    later migrations. Check with `dbmate --url "$OWNER_URL" status`. To confirm the database
    really matches the baseline first, compare
    `pg_dump --schema-only --no-owner --no-privileges` of it with the same dump of a fresh
    `scripts/db.sh test-create` clone (ignore the `schema_migrations` table and pg_dump's
    `\restrict` lines).

If the baseline is run against a database that already has the schema, it changes nothing. Its first
statement checks for the `station` table and raises
`windburglr schema already exists; mark the baseline as applied instead of running it`. The
migration's transaction rolls back and no version is recorded. dbmate only leaves behind an
empty `schema_migrations` table, which is the table the steps above fill in. So a deploy against
an un-baselined production database fails safely in the release command, and the running
release is untouched.

## Deployment

Both sub-projects deploy to [Fly.io](https://fly.io) (apps `windburglr` and `windburglr-scraper`).
CI (`.github/workflows/ci.yml`) deploys automatically: a push to `master` deploys each app whose
directory changed, once all checks pass. To deploy without a change, run the CI workflow manually
from the Actions tab and choose the apps. CI uses the `FLY_API_TOKEN` and `SENTRY_AUTH_TOKEN`
repository secrets.

CI runs each app's `fly-deploy.sh`, which also works by hand from a clean checkout. The script tags
the build with the commit SHA as the Sentry release; set `ALLOW_DIRTY=1` to deploy uncommitted
changes anyway. Extra arguments go to `flyctl deploy`.

-   **webapp**: with `SENTRY_AUTH_TOKEN` set, or in `webapp/.env.sentry-build-plugin`, the build uploads
    source maps to Sentry. The maps are not served.
-   **scraper**: station config is kept out of the repository and the image. The scraper reads it from
    the `SCRAPER_CONFIG` secret (base64-encoded TOML). When `scraper/windburglr.prod.toml` exists, the
    deploy script stages it as that secret first. CI has no copy of the file, so it deploys with the
    secret already set; to change the config, run the script by hand. Use `SCRAPER_CONFIG_FILE` to name
    a different file. Locally, the scraper reads `--config-file` (default `windburglr.toml`) when `SCRAPER_CONFIG` is unset.

Runtime settings such as `DATABASE_URL` and `SENTRY_DSN` are Fly secrets (`flyctl secrets list`).
