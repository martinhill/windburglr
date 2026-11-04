#!/usr/bin/env bash
# Deploy the scraper to Fly.io. Extra arguments are passed to `flyctl deploy`.
#
# Station config isn't committed or baked into the image. If SCRAPER_CONFIG_FILE (default
# windburglr.prod.toml) exists, it's staged as the base64-encoded SCRAPER_CONFIG secret and
# applied by this deploy; otherwise the secret already set on the app is used.
#
# With --config-only, the config is only staged, not deployed: it takes effect with the next
# deploy (such as CI's, when a scraper change is merged), or right away with
# `flyctl secrets deploy`.
set -euo pipefail
cd "$(dirname "$0")"

config_only=
if [ "${1:-}" = "--config-only" ]; then
    config_only=1
    shift
    if [ "$#" -gt 0 ]; then
        echo "--config-only takes no other arguments" >&2
        exit 2
    fi
fi

config_file=${SCRAPER_CONFIG_FILE:-windburglr.prod.toml}

stage_config() {
    echo "Staging SCRAPER_CONFIG secret from $config_file"
    # Passed on stdin so the config doesn't appear in the process list
    printf 'SCRAPER_CONFIG=%s\n' "$(base64 < "$config_file" | tr -d '\n')" \
        | flyctl secrets import --stage
}

if [ -n "$config_only" ]; then
    if [ ! -f "$config_file" ]; then
        echo "No $config_file to stage" >&2
        exit 1
    fi
    stage_config
    echo "Staged, not deployed. It takes effect with the next deploy, or now with" \
        "'flyctl secrets deploy'."
    exit 0
fi

# The Sentry release is the commit SHA, so it must describe exactly what's deployed
if [ -n "$(git status --porcelain -- .)" ] && [ -z "${ALLOW_DIRTY:-}" ]; then
    echo "Uncommitted changes in scraper/; commit them or set ALLOW_DIRTY=1" >&2
    exit 1
fi
SENTRY_RELEASE=$(git rev-parse HEAD)

if [ -f "$config_file" ]; then
    stage_config
else
    echo "No $config_file; deploying with the SCRAPER_CONFIG secret already set" >&2
fi

echo "Deploying with SENTRY_RELEASE=$SENTRY_RELEASE"
flyctl deploy --build-arg "SENTRY_RELEASE=$SENTRY_RELEASE" "$@"
