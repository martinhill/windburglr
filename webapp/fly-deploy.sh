#!/bin/bash
# Deploy the application to Fly.io

SENTRY_RELEASE=$(git rev-parse HEAD)
SENTRY_AUTH_TOKEN=$(cat .env.sentry-build-plugin | xargs)

echo "Deploying with SENTRY_RELEASE=$SENTRY_RELEASE"
flyctl deploy --build-arg SENTRY_RELEASE=$SENTRY_RELEASE --build-secret SENTRY_AUTH_TOKEN=$SENTRY_AUTH_TOKEN $@
