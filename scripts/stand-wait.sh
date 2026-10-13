#!/usr/bin/env bash
#
# Wait until the Sekisovskoye stand really works, not only until its containers
# are healthy: /api/state lists all 96 twins, the simulator clock moves and the
# advisor answers. Gives up after 300 s.
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
set -a; . "$ROOT/deploy/compose/.env"; set +a

STAND="http://127.0.0.1:${STAND_PORT:-8088}"
EXPECTED_THINGS=96
LIMIT_S="${STAND_WAIT_S:-300}"
deadline=$((SECONDS + LIMIT_S))

# Two readings of the simulator clock this many seconds apart must differ.
CLOCK_GAP_S=6

# A thing in /api/state is a key "kz.sekis:<name>" followed by an object.
count_things() {
  { grep -oE '"kz\.sekis:[^"]+" *: *\{' <<<"$1" || true; } | wc -l
}
# enterprise.sim_day, the first number after the key "sim_day".
sim_day() {
  grep -oE '"sim_day" *: *-?[0-9.]+' <<<"$1" | head -n 1 | grep -oE -- '-?[0-9.]+$' || true
}
# Top-level "sim_time" string (ISO time of the simulation).
sim_time() {
  grep -oE '"sim_time" *: *"[^"]*"' <<<"$1" | head -n 1 || true
}

fail() {
  echo
  echo "ОШИБКА: стенд не заработал за ${LIMIT_S} с: $1" >&2
  echo "        Посмотреть состояние: make ps" >&2
  echo "        Журналы: make logs S=sekis-sim   (или sekis-stand, sekis-advisor, sekis-setup)" >&2
  exit 1
}

printf 'Ожидание стенда на %s ' "$STAND"
last_reason="стенд не отвечает"
while :; do
  if [ "$SECONDS" -ge "$deadline" ]; then fail "$last_reason"; fi
  printf '.'
  state="$(curl -sf --max-time 10 "$STAND/api/state" || true)"
  if [ -z "$state" ]; then last_reason="/api/state не отвечает"; sleep 3; continue; fi
  n="$(count_things "$state")"
  if [ "$n" -lt "$EXPECTED_THINGS" ]; then
    last_reason="/api/state показывает $n двойников из $EXPECTED_THINGS"; sleep 3; continue
  fi
  day_a="$(sim_day "$state")"; time_a="$(sim_time "$state")"
  if [ -z "$day_a" ]; then last_reason="у предприятия нет признака sim_day (симулятор не публикует)"; sleep 3; continue; fi
  sleep "$CLOCK_GAP_S"
  state_b="$(curl -sf --max-time 10 "$STAND/api/state" || true)"
  day_b="$(sim_day "$state_b")"; time_b="$(sim_time "$state_b")"
  # sim_day grows by fractions or whole days; the ISO clock moves in every case.
  if awk -v a="$day_a" -v b="${day_b:-$day_a}" 'BEGIN { exit !(b > a) }' \
     || { [ -n "$time_b" ] && [ "$time_b" != "$time_a" ]; }; then
    :
  else
    last_reason="часы симулятора стоят (sim_day и sim_time не меняются)"; continue
  fi
  if ! curl -sf --max-time 10 -o /dev/null "$STAND/api/advisor"; then
    last_reason="/api/advisor не отвечает"; sleep 3; continue
  fi
  break
done
echo " готово"
echo "Двойников: $n, день симуляции: ${day_b:-$day_a}, советник отвечает."
