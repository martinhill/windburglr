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

# The Sentry token comes from the environment (CI, or direnv) or .env.sentry-build-plugin
if [ -z "${SENTRY_AUTH_TOKEN:-}" ] && [ -f .env.sentry-build-plugin ]; then
    SENTRY_AUTH_TOKEN=$(sed -n 's/^SENTRY_AUTH_TOKEN=//p' .env.sentry-build-plugin)
fi
build_secret_args=()
if [ -n "${SENTRY_AUTH_TOKEN:-}" ]; then
    build_secret_args=(--build-secret "SENTRY_AUTH_TOKEN=$SENTRY_AUTH_TOKEN")
else
    echo "No SENTRY_AUTH_TOKEN; source maps won't be uploaded to Sentry" >&2
fi

echo "Deploying with SENTRY_RELEASE=$SENTRY_RELEASE"
flyctl deploy --build-arg "SENTRY_RELEASE=$SENTRY_RELEASE" ${build_secret_args[@]+"${build_secret_args[@]}"} "$@"
