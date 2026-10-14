#!/usr/bin/env bash
#
# Проверка работающего стенда «Секисовское» целиком: контейнеры команды, двойники
# в Ditto, часы имитатора, путь данных в InfluxDB, советник, цикл сценария,
# страница стенда, Grafana. Запуск: make stand-smoke (после make stand).
# Занимает 1-2 минуты; в конце оставляет сценарий в базовом режиме.
# Нужны только bash, curl и python3.
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# The credentials live in deploy/compose/.env of the clone the stack runs from.
ENV_FILE="$ROOT/deploy/compose/.env"
[ -f "$ENV_FILE" ] || ENV_FILE="$PWD/deploy/compose/.env"
if [ ! -f "$ENV_FILE" ]; then
  echo "ОШИБКА: нет файла deploy/compose/.env. Сначала запустите: make stand" >&2
  exit 1
fi
# shellcheck disable=SC1090
set -a; . "$ENV_FILE"; set +a

HOST=127.0.0.1
STAND="http://$HOST:${STAND_PORT:-8088}"
DITTO="http://$HOST:$DITTO_PORT"
GRAFANA="http://$HOST:${GRAFANA_PORT:-3000}"
EXPECTED_THINGS=96
EXPECTED_TYPES=22
START=$SECONDS
FAILED=0
TOUCHED=0

pass() { printf '  \033[32mok\033[0m    %s\n' "$1"; }
fail() { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; FAILED=1; }

# run "name" cmd...: the command prints a detail on success or the reason on failure.
run() {
  local name="$1" out; shift
  if out=$("$@" 2>&1); then
    out="${out%%$'\n'*}"; pass "$name${out:+ ($out)}"
  else
    out="${out%%$'\n'*}"; fail "$name${out:+: $out}"
  fi
}

# poll SECONDS cmd...: repeat the command every 2 s until it succeeds.
poll() {
  local secs="$1" out end=$((SECONDS + $1)); shift
  while :; do
    if out=$("$@" 2>&1); then printf '%s' "$out"; return 0; fi
    if [ "$SECONDS" -ge "$end" ]; then printf '%s' "$out"; return 1; fi
    sleep 2
  done
}

# jx 'expression': read JSON from stdin as d, print the value of the expression.
jx() {
  python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
    v = eval(sys.argv[1])
except Exception:
    sys.exit(1)
print("" if v is None else v)' "$1"
}

get() { curl -sf --max-time 10 "$STAND$1"; }
post() { curl -sS --max-time 15 -X POST -H 'Content-Type: application/json' -d "$1" "$STAND/api/scenario"; }
cid() { docker ps -a -q --filter "label=com.docker.compose.service=$1" | head -n 1; }

# Whatever happens, leave the scenario in its base state.
cleanup() {
  if [ "$TOUCHED" = 1 ]; then post '{"preset":"reset"}' >/dev/null 2>&1 || true; fi
}
trap cleanup EXIT

# ---------------------------------------------------------------- checks

check_team_containers() {
  local bad="" svc id info
  for svc in sekis-sim sekis-advisor sekis-stand; do
    id=$(cid "$svc")
    if [ -z "$id" ]; then bad+=" $svc(нет контейнера)"; continue; fi
    info=$(docker inspect -f '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}без-проверки{{end}}' "$id")
    [ "$info" = "running healthy" ] || bad+=" $svc($info)"
  done
  id=$(cid sekis-setup)
  if [ -z "$id" ]; then bad+=" sekis-setup(нет контейнера)"; else
    info=$(docker inspect -f '{{.State.Status}} {{.State.ExitCode}}' "$id")
    [ "$info" = "exited 0" ] || bad+=" sekis-setup($info)"
  fi
  if [ -n "$bad" ]; then echo "не в порядке:$bad"; return 1; fi
  echo "sekis-sim, sekis-advisor, sekis-stand работают; sekis-setup завершён с кодом 0"
}

ditto_count() {
  curl -sf --max-time 10 -u "ditto:$DITTO_PASSWORD" -G "$DITTO/api/2/search/things/count" \
    --data-urlencode "namespaces=$1" | tr -d '[:space:]'
}
check_ditto_counts() {
  local things types
  things=$(ditto_count kz.sekis) || { echo "Ditto не ответил на поиск"; return 1; }
  types=$(ditto_count kz.sekis.type) || { echo "Ditto не ответил на поиск"; return 1; }
  if [ "$things" = "$EXPECTED_THINGS" ] && [ "$types" = "$EXPECTED_TYPES" ]; then
    echo "$things двойников kz.sekis, $types типов kz.sekis.type"; return 0
  fi
  echo "kz.sekis: $things (нужно $EXPECTED_THINGS), kz.sekis.type: $types (нужно $EXPECTED_TYPES)"; return 1
}

check_healthz() {
  local h
  h=$(get /healthz) || { echo "/healthz не отвечает"; return 1; }
  if [ "$(jx 'd["status"]' <<<"$h")" = ok ] && [ "$(jx 'd["mode"]' <<<"$h")" = live ] \
     && [ "$(jx 'd["things"]' <<<"$h")" = "$EXPECTED_THINGS" ]; then
    echo "режим live, двойников $(jx 'd["things"]' <<<"$h"), возраст кэша $(jx 'd["state_age_s"]' <<<"$h") с"; return 0
  fi
  echo "ответ: $h"; return 1
}

# The enterprise twin is published every 20 s of real time, so wait up to 45 s.
check_clock() {
  local a b end=$((SECONDS + 45))
  a=$(get /api/state | jx 'd["sim_time"]') || { echo "/api/state не отвечает"; return 1; }
  while [ "$SECONDS" -lt "$end" ]; do
    sleep 3
    b=$(get /api/state | jx 'd["sim_time"]') || continue
    if [ -n "$b" ] && [ "$b" != "$a" ]; then echo "$a -> $b"; return 0; fi
  done
  echo "часы стоят на $a"; return 1
}

# Trucks stand still for up to two real minutes around the shift change (the
# simulated day is 24 real minutes), and the simulator breaks trucks down for
# 10 simulated hours at random, so the check looks for movement for up to 120 s
# and counts different trucks seen moving. Three are required; when breakdowns
# leave fewer than three trucks fit for work (not parked, held or in repair), all
# of the fit ones must be seen moving.
check_trucks_moving() {
  local began=$SECONDS out total fit k seen=" " n_seen=0 need
  while :; do
    out=$(get /api/state | jx '" ".join([
        str(sum(1 for t in d["things"].values() if t.get("kind") == "haul_truck")),
        str(sum(1 for t in d["things"].values() if t.get("kind") == "haul_truck"
                and t["f"].get("state") not in ("parked", "maintenance", "held_vent")))] + [
        k for k, t in d["things"].items() if t.get("kind") == "haul_truck"
        and t["f"].get("state") in ("hauling_up", "descending", "surface_haul", "tram_level")])') || out=""
    if [ -n "$out" ]; then
      # shellcheck disable=SC2086
      set -- $out; total="$1"; fit="$2"; shift 2
      for k in "$@"; do case "$seen" in *" $k "*) ;; *) seen+="$k "; n_seen=$((n_seen + 1)) ;; esac; done
      need=3; [ "$fit" -lt 3 ] && need="$fit"
      if [ "$n_seen" -ge "$need" ] && [ "$n_seen" -ge 1 ]; then
        echo "за $((SECONDS - began)) с замечено в движении $n_seen из $total самосвалов, годных к работе: $fit"; return 0
      fi
    fi
    if [ $((SECONDS - began)) -ge 120 ]; then
      echo "за 120 с замечено в движении самосвалов: $n_seen, годных к работе: ${fit:-?}, нужно не меньше ${need:-3}"; return 1
    fi
    sleep 2
  done
}

# A point written after T0 must show up in the default bucket within 30 s.
check_influx() {
  local t0 flux end=$((SECONDS + 30)) influx out
  influx=$(cid influxdb)
  [ -n "$influx" ] || { echo "нет контейнера influxdb"; return 1; }
  t0=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  flux="from(bucket:\"default\") |> range(start: $t0) |> filter(fn:(r) => r.thingId == \"kz.sekis:truck-01\" and r._field == \"value_chainage_m_properties_value\") |> count() |> keep(columns:[\"_value\"])"
  while [ "$SECONDS" -lt "$end" ]; do
    out=$(docker exec "$influx" influx query --org opentwins --token "$INFLUXDB_TOKEN" --raw "$flux" 2>/dev/null \
          | tr -d '\r' | grep -E '^,,[0-9]+,[1-9][0-9]*$' | head -n 1 || true)
    if [ -n "$out" ]; then echo "через Telegraf за $((SECONDS - end + 30)) с, точек: ${out##*,}"; return 0; fi
    sleep 2
  done
  echo "значение chainage_m самосвала 01 не дошло до InfluxDB за 30 с"; return 1
}

check_advisor() {
  local r
  r=$(get /api/advisor) || { echo "/api/advisor не отвечает"; return 1; }
  jx '"{}, {} тыс. т/год при цели {}".format(d["binding_link"], d["achievable_ktpa"], d["target_ktpa"]) if d.get("binding_link") else (_ for _ in ()).throw(ValueError())' <<<"$r" \
    || { echo "в отчёте нет узкого звена"; return 1; }
}

haul_cap() { get /api/advisor | jx '[l for l in d["links"] if l["id"] == "haulage"][0]["cap_ktpa"]'; }
tu2_state() { get /api/state | jx 'd["things"]["kz.sekis:decline-tu2"]["f"]["state"]'; }

expect_tu2() {      # expect_tu2 closed|open
  local s; s=$(tu2_state) || { echo "/api/state не отвечает"; return 1; }
  [ "$s" = "$1" ] && { echo "состояние $s"; return 0; }
  echo "состояние $s, ожидалось $1"; return 1
}
expect_cap_below() {  # expect_cap_below BASE
  local c; c=$(haul_cap) || { echo "/api/advisor не отвечает"; return 1; }
  if awk -v c="$c" -v b="$1" 'BEGIN { exit !(c < b) }'; then echo "$1 -> $c тыс. т/год"; return 0; fi
  echo "откатка $c, ожидалось меньше $1"; return 1
}
expect_cap_equal() {  # expect_cap_equal BASE
  local c; c=$(haul_cap) || { echo "/api/advisor не отвечает"; return 1; }
  if awk -v c="$c" -v b="$1" 'BEGIN { exit !(c == b) }'; then echo "откатка снова $c тыс. т/год"; return 0; fi
  echo "откатка $c, ожидалось $1"; return 1
}
post_ok() {         # post_ok BODY
  local r; r=$(post "$1") || { echo "POST /api/scenario не ответил"; return 1; }
  [ "$(jx 'd.get("ok")' <<<"$r")" = True ] && { echo "ревизия $(jx 'd["revision"]' <<<"$r")"; return 0; }
  echo "ответ: ${r:0:200}"; return 1
}
remaining() { local r=$((15 - (SECONDS - $1))); [ "$r" -gt 1 ] && echo "$r" || echo 1; }

scenario_is_base() {
  local s; s=$(get /api/scenario) || { echo "/api/scenario не отвечает"; return 1; }
  jx '"" if d["knobs"] == d["defaults"] else (_ for _ in ()).throw(ValueError())' <<<"$s" >/dev/null || return 1
  echo "ревизия $(jx 'd["revision"]' <<<"$s"), «$(jx 'd["label"]' <<<"$s")»"
}

check_page_hosts() {
  python3 - "$STAND" <<'PY'
import re, sys, urllib.parse, urllib.request
base = sys.argv[1]
allowed = {"localhost", "127.0.0.1", "www.w3.org"}
seen, queue, foreign, files = set(), ["/"], [], 0
while queue and len(seen) < 300:
    path = queue.pop()
    if path in seen or path.startswith("/vendor/"):
        continue
    seen.add(path)
    try:
        with urllib.request.urlopen(base + path, timeout=10) as r:
            text = r.read().decode("utf-8", "replace")
    except Exception as exc:
        if path == "/":
            print("страница / не отвечает: %s" % exc); sys.exit(1)
        continue
    files += 1
    for m in re.finditer(r"https?://([^/\s\"'`)\\:?#]+)", text):
        if m.group(1) not in allowed:
            foreign.append("%s -> %s" % (path, m.group(1)))
    for m in re.finditer(r"""["'`(]([^"'`()\s]*\.(?:js|mjs|css))["'`)]""", text):
        ref = urllib.parse.urljoin(base + path, m.group(1))
        if ref.startswith(base + "/"):
            queue.append(ref[len(base):])
if foreign:
    print("есть обращения к другим хостам: " + "; ".join(sorted(set(foreign))[:5])); sys.exit(1)
print("проверено файлов: %d, других хостов нет" % files)
PY
}

check_http_200() {  # check_http_200 URL
  local code; code=$(curl -s -o /dev/null --max-time 15 -w '%{http_code}' "$1" || true)
  [ "$code" = 200 ] && { echo "200"; return 0; }
  echo "код ответа ${code:-нет}"; return 1
}

check_grafana_health() {
  curl -sf --max-time 10 "$GRAFANA/api/health" | jx 'd["database"]' | grep -qx ok && echo "база данных ok"
}

# Anonymous viewer: the page itself and the Ditto query the Twins list sends.
check_twins_page() {
  local code body
  code=$(curl -s -o /dev/null --max-time 15 -w '%{http_code}' "$GRAFANA/a/ertis-opentwins-app/twins" || true)
  [ "$code" = 200 ] || { echo "страница Twins: код ${code:-нет}"; return 1; }
  body=$(curl -sf --max-time 15 -G "$GRAFANA/api/plugin-proxy/ertis-opentwins-app/ditto/api/2/search/things" \
    --data-urlencode 'filter=ne(attributes/_isType,true)' --data-urlencode 'fields=thingId' \
    --data-urlencode 'option=size(200)') || { echo "список двойников без входа не отдаётся"; return 1; }
  grep -q 'kz.sekis:truck-01' <<<"$body" || { echo "в списке нет kz.sekis:truck-01"; return 1; }
  echo "страница 200, список двойников виден без входа"
}

# ---------------------------------------------------------------- run

echo "Стенд: $STAND   Ditto: $DITTO   Grafana: $GRAFANA"

echo "Контейнеры команды"
run "четыре контейнера команды" poll 30 check_team_containers

echo "Двойники"
run "Ditto хранит двойников и типы" poll 30 check_ditto_counts
run "стенд отвечает на /healthz" poll 30 check_healthz

# The checks below assume the base scenario.
if ! scenario_is_base >/dev/null 2>&1; then
  TOUCHED=1
  if post_ok '{"preset":"reset"}' >/dev/null 2>&1; then
    echo "  сценарий был не базовым, сброшен в базовый режим"
    sleep 6
  fi
fi

echo "Имитатор"
run "часы имитации идут" check_clock
run "значение имитатора дошло до InfluxDB через Telegraf" check_influx

echo "Советник"
run "отчёт отвечает и называет узкое звено" poll 20 check_advisor

echo "Сценарий"
base_cap=$(haul_cap || true)
if [ -z "$base_cap" ]; then
  fail "сценарий: мощность откатки в отчёте советника не читается"
else
  TOUCHED=1
  t_post=$SECONDS
  run "закрыть уклон ТУ-2: запрос принят" post_ok '{"preset":"close_tu2"}'
  run "kz.sekis:decline-tu2 в состоянии closed" poll "$(remaining "$t_post")" expect_tu2 closed
  run "мощность откатки у советника упала" poll "$(remaining "$t_post")" expect_cap_below "$base_cap"
  t_post=$SECONDS
  run "шаг назад: запрос принят" post_ok '{"preset":"undo"}'
  run "kz.sekis:decline-tu2 снова open" poll "$(remaining "$t_post")" expect_tu2 open
  run "мощность откатки вернулась" poll "$(remaining "$t_post")" expect_cap_equal "$base_cap"
fi
TOUCHED=1
run "сброс: запрос принят" post_ok '{"preset":"reset"}'
run "сценарий в базовом состоянии" poll 10 scenario_is_base
TOUCHED=0

echo "Страница стенда"
run "страница / отвечает, чужих хостов нет" check_page_hosts
run "/api/geometry отвечает" check_http_200 "$STAND/api/geometry"

echo "Grafana"
run "Grafana отвечает" poll 30 check_grafana_health
run "приложение OpenEgiz: страница Twins без входа" poll 30 check_twins_page

echo "Движение самосвалов"
run "в движении не меньше трёх самосвалов" check_trucks_moving

echo
elapsed=$((SECONDS - START))
if [ "$FAILED" = 0 ]; then
  echo "Проверка стенда пройдена за ${elapsed} с."
else
  echo "Проверка стенда НЕ пройдена (${elapsed} с)."
  exit 1
fi
