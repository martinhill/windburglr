#!/usr/bin/env bash
# Deploy the webapp to Fly.io. Extra arguments are passed to `flyctl deploy`.
set -euo pipefail
cd "$(dirname "$0")"

# The Sentry release is the commit SHA, so it must describe exactly what's deployed
if [ -n "$(git status --porcelain -- .)" ] && [ -z "${ALLOW_DIRTY:-}" ]; then
    echo "Uncommitted changes in webapp/; commit them or set ALLOW_DIRTY=1" >&2
    exit 1
fi
SENTRY_RELEASE=$(git rev-parse HEAD)

build_secret_args=()
if [ -f .env.sentry-build-plugin ]; then
    SENTRY_AUTH_TOKEN=$(sed -n 's/^SENTRY_AUTH_TOKEN=//p' .env.sentry-build-plugin)
    build_secret_args=(--build-secret "SENTRY_AUTH_TOKEN=$SENTRY_AUTH_TOKEN")
else
    echo "No .env.sentry-build-plugin; source maps won't be uploaded to Sentry" >&2
fi

echo "Deploying with SENTRY_RELEASE=$SENTRY_RELEASE"
flyctl deploy --build-arg "SENTRY_RELEASE=$SENTRY_RELEASE" ${build_secret_args[@]+"${build_secret_args[@]}"} "$@"
