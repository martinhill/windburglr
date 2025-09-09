#!/bin/bash
# Deploy the application to Fly.io
flyctl deploy --build-arg SENTRY_RELEASE=$(git rev-parse HEAD)