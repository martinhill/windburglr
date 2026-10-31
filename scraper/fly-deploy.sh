#!/usr/bin/env bash
# Deploy the scraper to Fly.io. Extra arguments are passed to `flyctl deploy`.
#
# Station config isn't committed or baked into the image. If SCRAPER_CONFIG_FILE (default
# windburglr.prod.toml) exists, it's staged as the base64-encoded SCRAPER_CONFIG secret and
# applied by this deploy; otherwise the secret already set on the app is used.
set -euo pipefail
cd "$(dirname "$0")"

# The Sentry release is the commit SHA, so it must describe exactly what's deployed
if [ -n "$(git status --porcelain -- .)" ] && [ -z "${ALLOW_DIRTY:-}" ]; then
    echo "Uncommitted changes in scraper/; commit them or set ALLOW_DIRTY=1" >&2
    exit 1
fi
SENTRY_RELEASE=$(git rev-parse HEAD)

config_file=${SCRAPER_CONFIG_FILE:-windburglr.prod.toml}
if [ -f "$config_file" ]; then
    echo "Staging SCRAPER_CONFIG secret from $config_file"
    # Passed on stdin so the config doesn't appear in the process list
    printf 'SCRAPER_CONFIG=%s\n' "$(base64 < "$config_file" | tr -d '\n')" \
        | flyctl secrets import --stage
else
    echo "No $config_file; deploying with the SCRAPER_CONFIG secret already set" >&2
fi

echo "Deploying with SENTRY_RELEASE=$SENTRY_RELEASE"
flyctl deploy --build-arg "SENTRY_RELEASE=$SENTRY_RELEASE" "$@"
