#!/usr/bin/env bash
#
# Длительная проверка стенда «Секисовское»: bash scripts/stand-soak.sh [минуты]
# (по умолчанию 60). Ставит сценарий 2,5 млн т/год (цель 2500 и все меры
# советника), раз в минуту снимает показания и в конце печатает итог. Код
# возврата не нулевой, если есть хотя бы один флаг:
#   - часы имитации отстали: пройдено меньше 0,9 от ожидаемого при ускорении;
#   - память контейнера выше 90 % его предела;
#   - контейнер перезапускался или исчез;
#   - в журналах сервисов команды, Telegraf или Ditto были ошибки;
#   - Ditto не в состоянии UP или стенд не отвечал;
#   - поток telemetry/sekis/# выше 20 сообщений в секунду.
# В конце сценарий возвращается в базовый режим. Нужны bash, curl, python3, docker.
# STAND_SOAK_KEEP_SCENARIO=1 не трогает сценарий; STAND_SOAK_INTERVAL_S меняет
# период снятия показаний (60 с).
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT/deploy/compose/.env"
[ -f "$ENV_FILE" ] || ENV_FILE="$PWD/deploy/compose/.env"
if [ ! -f "$ENV_FILE" ]; then
  echo "ОШИБКА: нет файла deploy/compose/.env. Сначала запустите: make stand" >&2
  exit 1
fi
# shellcheck disable=SC1090
set -a; . "$ENV_FILE"; set +a

MINUTES="${1:-60}"
if ! [[ "$MINUTES" =~ ^[0-9]+$ ]] || [ "$MINUTES" -lt 1 ]; then
  echo "Использование: bash scripts/stand-soak.sh [минуты]   (целое число, по умолчанию 60)" >&2
  exit 2
fi
INTERVAL="${STAND_SOAK_INTERVAL_S:-60}"
SAMPLES=$(( (MINUTES * 60 + INTERVAL - 1) / INTERVAL + 1 ))
HOST=127.0.0.1
STAND="http://$HOST:${STAND_PORT:-8088}"
DITTO="http://$HOST:$DITTO_PORT"
RATE_WINDOW_S=5

# Services whose logs are searched for errors. The team services and Telegraf are
# searched for error words; the Ditto services only for the ERROR log level. Ditto
# connectivity logs every inbound message at INFO with "response","error" among
# the expected response types of its headers; those lines are never counted.
LOG_WORDS='error|exception|traceback|critical|fatal|ошибк|сбой|не удалось|не прочитан|не отвечает|потеряно|отклонён|read failed| E! '
TEAM_LOG_SERVICES="sekis-sim sekis-advisor sekis-stand telegraf"
DITTO_LOG_SERVICES="connectivity things policies things-search gateway"

TMP="$(mktemp -d)"
SCENARIO_TOUCHED=0

post() { curl -sS --max-time 20 -X POST -H 'Content-Type: application/json' -d "$1" "$STAND/api/scenario"; }
cid() { docker ps -q --filter "label=com.docker.compose.service=$1" | head -n 1; }

cleanup() {
  if [ "$SCENARIO_TOUCHED" = 1 ]; then post '{"preset":"reset"}' >/dev/null 2>&1 || true; fi
  rm -rf "$TMP"
}
trap cleanup EXIT

say() { printf '%s\n' "$*"; }

# ---------------------------------------------------------------- preparation

docker ps --format '{{.Names}}|{{.Label "com.docker.compose.service"}}' | awk -F'|' '$2 != ""' >"$TMP/names.txt"
if [ ! -s "$TMP/names.txt" ]; then echo "ОШИБКА: не найдено ни одного работающего контейнера стенда." >&2; exit 1; fi
SIM_ID="$(cid sekis-sim)"
MOSQ_ID="$(cid mosquitto)"
if [ -z "$SIM_ID" ] || [ -z "$MOSQ_ID" ]; then echo "ОШИБКА: не работают sekis-sim или mosquitto. Запустите: make stand" >&2; exit 1; fi
SPEEDUP="$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$SIM_ID" | sed -n 's/^SIM_SPEEDUP=//p' | head -n 1)"
SPEEDUP="${SPEEDUP:-60}"

# Memory limit of every container in MiB (0: no limit) and the start state for restarts.
# shellcheck disable=SC2046
docker inspect -f '{{.Name}}|{{.HostConfig.Memory}}' $(docker ps -q) | sed 's|^/||' >"$TMP/limits.txt"
inspect_state() {
  # shellcheck disable=SC2046
  docker inspect -f '{{.Name}}|{{.RestartCount}}|{{.State.StartedAt}}|{{.State.Status}}|{{.State.OOMKilled}}' $(docker ps -q) 2>/dev/null | sed 's|^/||'
}
inspect_state >"$TMP/baseline.txt"

if [ "${STAND_SOAK_KEEP_SCENARIO:-0}" != 1 ]; then
  SCENARIO_TOUCHED=1
  post '{"preset":"step2500"}' >/dev/null
  post '{"action":"advisor_all"}' >/dev/null
  # The simulator and the advisor take a new revision within a few seconds.
  sleep 10
  scen="$(curl -sf --max-time 10 "$STAND/api/scenario" || true)"
  say "Сценарий: $(python3 -c 'import json,sys; d=json.load(sys.stdin); k=d["knobs"]; print("ревизия %s, «%s», цель %g, меры: фабрика %g, откатка %g, блоки %g, вентиляция %g, проходка %g, вода %g, хвосты %g" % (d["revision"], d["label"], k["target_ktpa"], k["m_plant"], k["m_haul"], k["m_stopes"], k["m_vent"], k["m_dev"], k["m_water"], k["m_tailings"]))' <<<"$scen" 2>/dev/null || echo "не прочитан")"
else
  say "Сценарий не меняется (STAND_SOAK_KEEP_SCENARIO=1)."
fi
say "Длительность: $MINUTES мин, показаний: $SAMPLES, период $INTERVAL с, ускорение имитации ×$SPEEDUP."
say
say "  №      время   сутки    время имитации       сообщ/с  память МиБ (самый полный)      рестарт ошибок Ditto"

# ---------------------------------------------------------------- sampling

sample() {   # sample INDEX SINCE NOW
  local i="$1" since="$2" now="$3" epoch rate n state day stime mem top health restarts errs svc id cnt lines
  epoch=$(date +%s)

  state="$(curl -sf --max-time 10 "$STAND/api/state" || true)"
  day="" stime=""
  if [ -n "$state" ]; then
    read -r day stime < <(python3 -c '
import json, sys
try:
    f = json.load(sys.stdin)["things"]["kz.sekis:enterprise"]["f"]
    print(f.get("sim_day", ""), f.get("sim_time", ""))
except Exception:
    print("", "")' <<<"$state") || true
  fi

  n=$(docker exec "$MOSQ_ID" sh -c "mosquitto_sub -h localhost -W $RATE_WINDOW_S -t 'telemetry/sekis/#' 2>/dev/null | wc -l" 2>/dev/null || echo 0)
  rate=$(awk -v n="${n:-0}" -v w="$RATE_WINDOW_S" 'BEGIN { printf "%.1f", n / w }')

  # Memory: one line per container, appended to mem.tsv; print the sum and the fullest container.
  mem=$(docker stats --no-stream --format '{{.Name}}|{{.MemUsage}}' | python3 -c '
import sys
epoch, names, limits, out = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
unit = {"B": 1 / 1048576, "KiB": 1 / 1024, "MiB": 1, "GiB": 1024, "TiB": 1048576,
        "kB": 1000 / 1048576, "MB": 1e6 / 1048576, "GB": 1e9 / 1048576}
def mib(text):
    text = text.strip()
    for u in sorted(unit, key=len, reverse=True):
        if text.endswith(u):
            return float(text[: -len(u)]) * unit[u]
    return 0.0
svc = dict(l.rstrip("\n").split("|") for l in open(names) if "|" in l)
lim = {}
for l in open(limits):
    name, value = l.rstrip("\n").split("|")
    lim[name] = int(value) / 1048576
total, top, top_pct = 0.0, "-", 0.0
with open(out, "a") as f:
    for line in sys.stdin:
        name, usage = line.rstrip("\n").split("|")
        used = mib(usage.split("/")[0])
        limit = lim.get(name, 0.0)
        total += used
        f.write("%s\t%s\t%.2f\t%.0f\n" % (epoch, svc.get(name, name), used, limit))
        pct = 100 * used / limit if limit else 0.0
        if pct > top_pct:
            top, top_pct = svc.get(name, name), pct
print("%.0f %s %.0f" % (total, top, top_pct))' "$epoch" "$TMP/names.txt" "$TMP/limits.txt" "$TMP/mem.tsv") || mem="? - 0"
  top="${mem#* }"

  # Restarts: a changed restart count or start time, or a container that is gone.
  restarts=$(inspect_state | python3 -c '
import sys
base = {}
for l in open(sys.argv[1]):
    p = l.rstrip("\n").split("|")
    base[p[0]] = p
now = {}
for l in sys.stdin:
    p = l.rstrip("\n").split("|")
    now[p[0]] = p
events = 0
with open(sys.argv[2], "a") as f:
    for name, b in base.items():
        c = now.get(name)
        if c is None:
            f.write("%s: контейнер исчез или остановлен\n" % name); events += 1
        elif c[1] != b[1] or c[2] != b[2] or c[4] == "true":
            f.write("%s: перезапуск (счётчик %s -> %s, запущен %s -> %s, нехватка памяти: %s)\n" % (name, b[1], c[1], b[2], c[2], c[4])); events += 1
            base[name] = c
        elif c[3] != "running":
            f.write("%s: состояние %s\n" % (name, c[3])); events += 1
        else:
            continue
        base[name] = c if c else b
    for name in list(base):
        if name not in now:
            del base[name]
with open(sys.argv[1], "w") as f:
    for p in base.values():
        f.write("|".join(p) + "\n")
print(events)' "$TMP/baseline.txt" "$TMP/restarts.log") || restarts="?"

  # Errors in the logs since the previous sample.
  errs=0
  for svc in $TEAM_LOG_SERVICES $DITTO_LOG_SERVICES; do
    id=$(cid "$svc")
    [ -n "$id" ] || continue
    if case " $DITTO_LOG_SERVICES " in *" $svc "*) true ;; *) false ;; esac; then
      lines=$(docker logs --since "$since" --until "$now" "$id" 2>&1 | grep -F ' ERROR ' | grep -vF '"response","error"' || true)
    else
      lines=$(docker logs --since "$since" --until "$now" "$id" 2>&1 | grep -iE "$LOG_WORDS|Ошибк|Сбой|Не удалось|Не прочитан|Не отвечает|Потеряно|Отклонён" | grep -vF '"response","error"' || true)
    fi
    if [ -n "$lines" ]; then
      cnt=$(printf '%s\n' "$lines" | wc -l)
      errs=$((errs + cnt))
      printf '%s\n' "$lines" | cut -c1-240 | sed "s|^|$svc: |" >>"$TMP/errors.log"
    fi
  done

  health=$(curl -sf --max-time 10 -u "devops:$DITTO_DEVOPS_PASSWORD" "$DITTO/status/health" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin).get("status","?"))' 2>/dev/null || echo "нет ответа")

  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$epoch" "${day:--}" "${stime:--}" "$rate" "$health" "$errs" "$restarts" >>"$TMP/samples.tsv"
  printf '  %2d/%-2d  +%02d:%02d  %-8s %-19s  %6s  %6s (%s %s%%)  %7s  %6s  %s\n' \
    "$((i + 1))" "$SAMPLES" "$(((epoch - T0) / 60))" "$(((epoch - T0) % 60))" "${day:--}" "${stime:--}" "$rate" \
    "${mem%% *}" "${top%% *}" "${top##* }" "$restarts" "$errs" "$health"
}

T0=$(date +%s)
since=$(date -u +%Y-%m-%dT%H:%M:%S.%NZ)
: >"$TMP/samples.tsv"; : >"$TMP/mem.tsv"; : >"$TMP/restarts.log"; : >"$TMP/errors.log"
for ((i = 0; i < SAMPLES; i++)); do
  target=$((T0 + i * INTERVAL))
  now_s=$(date +%s)
  if [ "$now_s" -lt "$target" ]; then sleep $((target - now_s)); fi
  now=$(date -u +%Y-%m-%dT%H:%M:%S.%NZ)
  sample "$i" "$since" "$now"
  since="$now"
done

# ---------------------------------------------------------------- summary

say
say "Итог"
set +e
python3 - "$TMP" "$SPEEDUP" "$MINUTES" <<'PY'
import collections, os, sys

tmp, speedup, minutes = sys.argv[1], float(sys.argv[2]), int(sys.argv[3])
flags = []
GREEN, RED, OFF = "\033[32m", "\033[31m", "\033[0m"

def rows(name):
    path = os.path.join(tmp, name)
    with open(path, encoding="utf-8") as f:
        return [line.rstrip("\n").split("\t") for line in f if line.strip()]

samples = rows("samples.tsv")
mem = rows("mem.tsv")

# 1. Simulated time against real time.
days = [(int(r[0]), float(r[1])) for r in samples if r[1] not in ("-", "")]
if len(days) >= 2:
    elapsed = days[-1][0] - days[0][0]
    got = days[-1][1] - days[0][1]
    expected = elapsed * speedup / 86400.0
    ratio = got / expected if expected > 0 else 0.0
    print("Сутки имитации: прошло %.3f, ожидалось %.3f за %d с при ускорении ×%g, отношение %.3f" % (got, expected, elapsed, speedup, ratio))
    if ratio < 0.9:
        flags.append("часы имитации отстают: отношение %.3f < 0.9" % ratio)
else:
    print("Сутки имитации: мало показаний sim_day")
    flags.append("sim_day не читался из /api/state")
unread = sum(1 for r in samples if r[1] in ("-", ""))
if unread:
    flags.append("стенд не отдал состояние в %d показаниях из %d" % (unread, len(samples)))

# 2. Message rate.
rates = [float(r[3]) for r in samples]
if rates:
    print("Поток telemetry/sekis/#: средний %.1f, наибольший %.1f сообщ/с (допустимо не больше 20)" % (sum(rates) / len(rates), max(rates)))
    if max(rates) > 20:
        flags.append("поток telemetry/sekis/# выше 20 сообщ/с: %.1f" % max(rates))

# 3. Peak memory per container against its limit.
by = collections.defaultdict(list)
for epoch, svc, used, limit in mem:
    by[svc].append((int(epoch), float(used), float(limit)))
print("Память контейнеров (пик, предел, доля):")
for svc in sorted(by):
    peak = max(u for _, u, _ in by[svc])
    limit = max(l for _, _, l in by[svc])
    if limit:
        pct = 100 * peak / limit
        mark = ""
        if pct > 90:
            flags.append("память %s: пик %.0f из %.0f МиБ (%.0f %% > 90 %%)" % (svc, peak, limit, pct))
            mark = "  <-- ВЫШЕ 90 %"
        print("  %-16s %7.0f МиБ из %5.0f   %5.1f %%%s" % (svc, peak, limit, pct, mark))
    else:
        print("  %-16s %7.0f МиБ, предел не задан" % (svc, peak))

# 4. Growth of the Ditto things container.
pts = by.get("things", [])
if len(pts) >= 3:
    t0 = pts[0][0]
    xs = [(e - t0) / 3600.0 for e, _, _ in pts]
    ys = [u for _, u, _ in pts]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den if den else 0.0
    line = "Рост памяти Ditto things: %+.1f МиБ в час (с %.0f до %.0f МиБ за %.0f мин)" % (slope, ys[0], ys[-1], xs[-1] * 60)
    limit = pts[0][2]
    if slope > 0 and limit:
        hours = (0.9 * limit - ys[-1]) / slope
        line += "; до 90 %% предела (%.0f МиБ) примерно %.1f ч" % (0.9 * limit, max(hours, 0))
    if minutes < 30:
        line += " (короткий прогон: оценка грубая)"
    print(line)
else:
    print("Рост памяти Ditto things: мало показаний")

# 5. Restarts.
with open(os.path.join(tmp, "restarts.log"), encoding="utf-8") as f:
    events = [l.rstrip("\n") for l in f if l.strip()]
if events:
    print("Перезапуски: %d" % len(events))
    for e in events:
        print("  " + e)
    flags.append("перезапусков или исчезнувших контейнеров: %d" % len(events))
else:
    print("Перезапусков нет.")

# 6. Errors in the logs.
with open(os.path.join(tmp, "errors.log"), encoding="utf-8") as f:
    errors = [l.rstrip("\n") for l in f if l.strip()]
if errors:
    per = collections.Counter(l.split(":", 1)[0] for l in errors)
    print("Ошибки в журналах: %d (%s)" % (len(errors), ", ".join("%s %d" % kv for kv in sorted(per.items()))))
    for l in errors[:10]:
        print("  " + l)
    if len(errors) > 10:
        print("  ... ещё %d" % (len(errors) - 10))
    flags.append("строк с ошибками в журналах: %d" % len(errors))
else:
    print("Ошибок в журналах нет.")

# 7. Ditto health.
bad = [r[4] for r in samples if r[4] != "UP"]
if bad:
    flags.append("Ditto не в состоянии UP в %d показаниях из %d" % (len(bad), len(samples)))
    print("Ditto: не UP в %d показаниях из %d" % (len(bad), len(samples)))
else:
    print("Ditto: состояние UP во всех %d показаниях." % len(samples))

print()
if flags:
    print(RED + "Проверка длительной работы НЕ пройдена:" + OFF)
    for f in flags:
        print("  - " + f)
    sys.exit(1)
print(GREEN + "Проверка длительной работы пройдена." + OFF)
PY
exit $?
