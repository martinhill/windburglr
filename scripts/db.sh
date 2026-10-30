#!/usr/bin/env bash
# Local PostgreSQL cluster shared by webapp, scraper and all git worktrees.
#
# Databases:
#   windburglr_template   schema + roles, rebuilt automatically when common/*.sql changes
#   windburglr_dev        persistent development database (schema, roles, initial data)
#   windburglr_test_*     per-test-session clones of the template, dropped afterwards
#
# Requires the dev environment (nix develop / direnv), which sets PGDATA, PGHOST, PGUSER, etc.
set -euo pipefail

: "${PGDATA:?load the dev environment first (nix develop, or direnv)}"
: "${WINDBURGLR_TEMPLATE_DB:?load the dev environment first (nix develop, or direnv)}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMMON="$ROOT/common"
TEMPLATE_DB="$WINDBURGLR_TEMPLATE_DB"
DEV_DB=windburglr_dev
LOCK_DIR="$PGDATA/.windburglr.lock"

log() { echo "db: $*" >&2; }

psql_admin() { psql -X -q -v ON_ERROR_STOP=1 -d postgres "$@"; }

is_running() { pg_ctl status >/dev/null 2>&1; }

db_exists() {
  [ "$(psql_admin -tAc "SELECT 1 FROM pg_database WHERE datname = '$1'")" = 1 ]
}

# Serialise template rebuilds and clones between concurrent test sessions and worktrees.
with_lock() {
  local waited=0
  until mkdir "$LOCK_DIR" 2>/dev/null; do
    if [ "$waited" -ge 120 ]; then
      log "timed out waiting for $LOCK_DIR (remove it if no db.sh is running)"
      exit 1
    fi
    sleep 0.5
    waited=$((waited + 1))
  done
  trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT
  "$@"
  rmdir "$LOCK_DIR" 2>/dev/null || true
  trap - EXIT
}

init_cluster() {
  log "initialising cluster in $PGDATA"
  initdb -D "$PGDATA" -U "$PGUSER" --auth=trust --no-locale --encoding=UTF8 >/dev/null
  cat >>"$PGDATA/postgresql.conf" <<EOF

# windburglr: socket-only, so it never clashes with other local servers
listen_addresses = ''
unix_socket_directories = '$PGDATA'
port = $PGPORT
shared_preload_libraries = 'timescaledb'
timescaledb.telemetry_level = off
EOF
}

start() {
  [ -f "$PGDATA/PG_VERSION" ] || init_cluster
  if ! is_running; then
    log "starting PostgreSQL"
    pg_ctl -D "$PGDATA" -l "$PGDATA/logfile" -w start >/dev/null
  fi
}

schema_hash() {
  cat "$COMMON/timescaledb_schema.sql" "$COMMON/roles.sql" | shasum -a 256 | cut -c1-16
}

apply_roles() {
  # Passwords are irrelevant locally (trust auth on the socket) but roles.sql requires them.
  psql -X -q -d "$1" -v scraper_password=scraper -v webapp_password=webapp \
    -f "$COMMON/roles.sql" >/dev/null
}

build_template() {
  local hash
  hash="$(schema_hash)"
  if db_exists "$TEMPLATE_DB" &&
    [ "$(psql_admin -tAc "SELECT shobj_description(oid, 'pg_database') FROM pg_database WHERE datname = '$TEMPLATE_DB'")" = "$hash" ]; then
    return
  fi
  log "building $TEMPLATE_DB (schema $hash)"
  if db_exists "$TEMPLATE_DB"; then
    psql_admin -c "ALTER DATABASE $TEMPLATE_DB WITH IS_TEMPLATE false"
    dropdb --force "$TEMPLATE_DB"
  fi
  createdb "$TEMPLATE_DB"
  psql -X -q -v ON_ERROR_STOP=1 -d "$TEMPLATE_DB" -f "$COMMON/timescaledb_schema.sql" >/dev/null
  apply_roles "$TEMPLATE_DB"
  # No connections allowed, so nothing (e.g. TimescaleDB background workers) blocks cloning.
  psql_admin -c "COMMENT ON DATABASE $TEMPLATE_DB IS '$hash'" \
    -c "ALTER DATABASE $TEMPLATE_DB WITH IS_TEMPLATE true ALLOW_CONNECTIONS false"
}

# Cloning fails while anything is connected to the template; after the ALLOW_CONNECTIONS change
# only a TimescaleDB scheduler that attached during the build can still be there.
clone_template() {
  psql_admin -tAc "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$TEMPLATE_DB'" >/dev/null
  createdb -T "$TEMPLATE_DB" "$1"
}

create_dev() {
  log "creating $DEV_DB"
  clone_template "$DEV_DB"
  # Database-level grants (CONNECT) are not copied from the template.
  apply_roles "$DEV_DB"
  psql -X -q -v ON_ERROR_STOP=1 -d "$DEV_DB" -f "$COMMON/initial_data.sql" >/dev/null
}

prepare() {
  build_template
  db_exists "$DEV_DB" || create_dev
}

cmd_up() {
  start
  with_lock prepare
  log "ready: psql -d $DEV_DB  (socket $PGHOST)"
}

cmd_down() {
  if is_running; then pg_ctl -D "$PGDATA" -w stop >/dev/null && log "stopped"; else log "not running"; fi
}

cmd_status() {
  if ! is_running; then
    log "not running ($PGDATA)"
    return 1
  fi
  psql_admin -c "SELECT datname AS database, pg_size_pretty(pg_database_size(datname)) AS size,
                        shobj_description(oid, 'pg_database') AS comment
                 FROM pg_database WHERE datname LIKE 'windburglr%' ORDER BY datname"
}

reset_dev() {
  build_template
  if db_exists "$DEV_DB"; then dropdb --force "$DEV_DB"; fi
  create_dev
}

cmd_reset_dev() {
  start
  with_lock reset_dev
}

# Used by the test suites: prints the name of a fresh clone of the template.
clone_test() {
  build_template
  clone_template "$1"
}

cmd_test_create() {
  local prefix="${1:-tests}"
  local name="windburglr_test_${prefix}_$$_$RANDOM"
  start
  with_lock clone_test "$name"
  echo "$name"
}

cmd_test_drop() {
  case "${1:-}" in
    windburglr_test_*) dropdb --force --if-exists "$1" ;;
    *) log "refusing to drop '${1:-}': not a test database"; exit 1 ;;
  esac
}

# Drops leftovers from aborted test runs; databases still in use are skipped.
cmd_test_clean() {
  start
  psql_admin -tAc "SELECT datname FROM pg_database WHERE datname LIKE 'windburglr\_test\_%'" |
    while read -r name; do
      if dropdb "$name" 2>/dev/null; then log "dropped $name"; else log "skipped $name (in use)"; fi
    done
}

case "${1:-}" in
  up) cmd_up ;;
  down) cmd_down ;;
  status) cmd_status ;;
  reset-dev) cmd_reset_dev ;;
  test-create) cmd_test_create "${2:-}" ;;
  test-drop) cmd_test_drop "${2:-}" ;;
  test-clean) cmd_test_clean ;;
  *)
    cat >&2 <<EOF
usage: scripts/db.sh <command>
  up            start the cluster; build the template and dev database if needed
  down          stop the cluster
  status        show running state and databases
  reset-dev     recreate $DEV_DB from the current schema (destroys its data)
  test-create   clone the template into a new test database and print its name
  test-drop     drop a test database
  test-clean    drop leftover test databases that are not in use
EOF
    exit 2
    ;;
esac
