#!/bin/bash
# Deploy the application to Fly.io

SENTRY_RELEASE=$(git rev-parse HEAD)

echo "Deploying with SENTRY_RELEASE=$SENTRY_RELEASE"
flyctl deploy --build-arg SENTRY_RELEASE=$SENTRY_RELEASE $@