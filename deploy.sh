#!/usr/bin/env sh

git pull
set -x
docker pull tomasbedrich/xcontest-rss-monitor:latest
mkdir -p state/
sudo chown -R ja:ja state/
docker-compose down
docker-compose up -d
