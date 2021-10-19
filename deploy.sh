#!/usr/bin/env sh

set -x
git pull
docker pull tomasbedrich/xcontest-rss-monitor:latest
mkdir -p state/
sudo chown -R ja:ja state/
docker-compose down
docker-compose up -d
