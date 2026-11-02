#!/usr/bin/env sh

set -x
git pull
docker pull tomasbedrich/xcontest-rss-monitor:latest
mkdir -p state/
docker compose down
docker compose up -d
