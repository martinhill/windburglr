# Environment for local development; sourced by the flake's shellHook.
# Must stay free of side effects: it runs on every direnv load and every agent shell command.

# The cluster lives in the main checkout so all git worktrees share it.
_wb_common_dir="$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)"
if [ -n "$_wb_common_dir" ]; then
  export WINDBURGLR_MAIN_ROOT="$(dirname "$_wb_common_dir")"
else
  export WINDBURGLR_MAIN_ROOT="$PWD"
fi
unset _wb_common_dir

# Socket-only cluster (no TCP), so it cannot clash with other local Postgres servers.
export PGDATA="$WINDBURGLR_MAIN_ROOT/.pgdata"
export PGHOST="$PGDATA"
export PGPORT=5432
export PGUSER=windburglr
export PGDATABASE=windburglr_dev

# Test sessions clone their own database from this template (see scripts/db.sh test-create).
export WINDBURGLR_TEMPLATE_DB=windburglr_template

# Activate the project virtualenv if it exists; `uv sync` creates it.
if [ -d "$PWD/.venv" ]; then
  export VIRTUAL_ENV="$PWD/.venv"
  export PATH="$VIRTUAL_ENV/bin:$PATH"
fi
