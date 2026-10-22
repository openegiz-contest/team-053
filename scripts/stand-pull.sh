#!/usr/bin/env bash
#
# Download the images of the stand before it starts, and try again when the
# network to Docker Hub fails (a TLS handshake timeout, a broken download):
# the platform images, the stand overlay's images and the base images of the
# two local builds (python:3.12-slim for team/Dockerfile, node:20-slim for the
# Ditto extended API). Never fails: whatever is still missing after the last
# attempt, `docker compose up` downloads itself.
#
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

COMPOSE=(docker compose -f deploy/compose/docker-compose.yml -f team/compose.yml)
BASE_IMAGES=(python:3.12-slim node:20-slim)
PAUSES_S=(0 15 30 60 90)   # pause before each attempt

for pause in "${PAUSES_S[@]}"; do
  sleep "$pause"
  ok=1
  "${COMPOSE[@]}" pull --quiet --ignore-buildable || ok=0
  for image in "${BASE_IMAGES[@]}"; do
    docker pull --quiet "$image" >/dev/null || ok=0
  done
  if [ "$ok" = 1 ]; then
    echo "Образы скачаны."
    exit 0
  fi
  echo "Не все образы скачались (сбой сети?), пробую ещё раз."
done
echo "Не все образы скачались; docker compose попробует скачать их сам."
exit 0
