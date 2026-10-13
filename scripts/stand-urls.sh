#!/usr/bin/env bash
# Print where the Sekisovskoye stand can be reached and how to log in to Grafana.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
set -a; . "$ROOT/deploy/compose/.env"; set +a
H="${OPENEGIZ_PUBLIC_HOST:-localhost}"
cat <<TXT

Стенд «Секисовское» запущен.

  Стенд (3D-сцена, разрез, сценарии)  http://$H:${STAND_PORT:-8088}
  Grafana (панели без входа)          http://$H:$GRAFANA_PORT
  Вход администратора Grafana         admin / $GRAFANA_ADMIN_PASSWORD

Двойники также видны в Grafana: приложение OpenEgiz, разделы Twins и Types.
Проверка всей системы: make stand-smoke
TXT
