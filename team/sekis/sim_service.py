"""Simulator service (spec 2.1, 5.1, 5.2): ``python -m sekis.sim_service``.

Every 0.5 real seconds the service advances the simulator (``sim.step(0.5)``: 30 simulated
seconds at the compression 60) and publishes the twins that are due, as Ditto-protocol ``modify``
messages on ``features`` to MQTT topic ``telemetry/sekis/<name>``. It never publishes
``kz.sekis:scenario`` (the Stand writes that thing) or ``kz.sekis:advisor`` (the advisor does).

The scenario thing is read from Ditto over HTTP once a second, in a background thread. When its
content differs from what was applied last (a new ``revision``, a lower one after a reset, or
changed knobs) it goes to ``Simulator.apply_scenario``; a set the simulator rejects (``ValueError``)
is logged, and the previous scenario stays in force.

The service outlives Ditto and the broker. A failed read is retried with a growing pause and the
simulation goes on with the last scenario; a message that could not be sent waits and goes out
again, newest state first, within the budget of ``publish.max_msg_per_s`` messages in any second.
The loop keeps real-time pace without drift: it sleeps up to a fixed schedule, skips the sleep
when a step overran, and gives up lag beyond a few seconds. ``/tmp/alive`` is touched on every
pass and at least once a second while waiting.

Log lines (Russian): one at the start, one per applied scenario revision, one per simulated day.

Fixture mode (``--fixture <path>`` or ``SIM_FIXTURE=<path>``) needs neither Ditto nor a broker:
the scenario comes from a JSON file (the Stand's ``GET /api/state``, a list of Ditto things or
``{"scenario": {"f": {knob: value}}}``; re-read when it changes) and the messages are only counted.
``SIM_FIXTURE=1`` runs on the baseline scenario.

Environment (default): SIM_SPEEDUP (``sim.speedup``, 60), SIM_SEED (``sim.seed``, 53),
PUBLISH_SCALE (``publish.scale_default``, 1.0), MQTT_HOST (mosquitto), MQTT_PORT (1883),
DITTO_URL (http://localhost:8080), DITTO_USER (ditto), DITTO_PASSWORD, SIM_FIXTURE (unset),
ALIVE_FILE (/tmp/alive). Standard library, plus paho-mqtt outside fixture mode.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

from .advisor.service import DittoSource, FixtureSource, SourceError, plain_things
from .advisor.wording import LINK_RU, num
from .sim import (ADVISOR_THING, SCENARIO_THING, PublishPlanner, Simulator, ditto_modify,
                  telemetry_topic)

POLL_S = 1.0             # the scenario thing is read this often (spec 5.2)
BACKOFF_MAX_S = 15.0     # longest pause between reads while Ditto does not answer
MAX_LAG_S = 3.0          # real-time lag the loop gives up instead of catching up
SLICE_S = 1.0            # the health file is touched at least this often while waiting
REPEAT_LOG_S = 60.0      # a persisting fault is logged again after this long
DEFAULT_ALIVE_FILE = "/tmp/alive"
NEVER_PUBLISHED = (SCENARIO_THING, ADVISOR_THING)
META_KNOBS = ("revision", "label")   # features of the scenario thing that are not knobs

Log = Callable[[str], None]


def log_line(message: str) -> None:
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} sim: {message}", flush=True)


# --- scenario sources --------------------------------------------------------------------------

class ScenarioReader:
    """Adapter over a source of the advisor service: ``read()`` -> features of the scenario thing
    as ``{feature id: value}``, or ``None`` when the source has none (yet)."""

    def __init__(self, inner: Any):
        self.inner = inner
        self.mode = getattr(inner, "mode", "live")

    def read(self) -> Optional[Dict[str, Any]]:
        things = self.inner.read()
        return things.get(SCENARIO_THING)


class BackgroundSource:
    """Reads ``inner`` in a thread every ``interval`` seconds and hands out the last result.

    ``read()`` never blocks: it returns the last features (``None`` before the first success) or
    raises ``SourceError`` while the latest attempt is failing. After a failure the thread waits
    ``interval`` x 2^(failures - 1) seconds, at most ``backoff_max``.
    """

    def __init__(self, inner: Any, interval: float = POLL_S, backoff_max: float = BACKOFF_MAX_S):
        self.inner = inner
        self.mode = getattr(inner, "mode", "live")
        self.interval = interval
        self.backoff_max = backoff_max
        self.failures = 0
        self._value: Any = None
        self._error: Optional[str] = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="scenario-poll", daemon=True)

    def start(self) -> "BackgroundSource":
        self._thread.start()
        return self

    def close(self) -> None:
        self._stop.set()

    def read(self) -> Any:
        with self._lock:
            if self._error is not None:
                raise SourceError(self._error)
            return self._value

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                value, error = self.inner.read(), None
            except Exception as exc:
                value, error = None, (str(exc) if isinstance(exc, SourceError)
                                      else f"{type(exc).__name__}: {exc}")
            with self._lock:
                if error is None:
                    self._value, self._error, self.failures = value, None, 0
                else:
                    self._error, self.failures = error, self.failures + 1
            pause = self.interval if error is None else min(self.backoff_max,
                                                           self.interval * 2 ** min(self.failures - 1, 10))
            self._stop.wait(pause)


# --- publishers --------------------------------------------------------------------------------

class NullPublisher:
    """Counts the messages instead of sending them (fixture mode)."""

    enabled = False

    def __init__(self) -> None:
        self.count = 0

    def publish(self, topic: str, payload: str) -> bool:
        self.count += 1
        return True

    def close(self) -> None:
        pass


class MqttPublisher:
    """paho-mqtt client that connects in the background and reconnects by itself."""

    enabled = True

    def __init__(self, host: str, port: int, log: Log = log_line):
        import paho.mqtt.client as mqtt  # imported here: fixture mode and the tests run without it

        self._mqtt = mqtt
        self._log = log
        self._where = f"{host}:{port}"
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="sekis-sim")
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)
        self._client.connect_async(host, port, keepalive=30)
        self._client.loop_start()  # the loop thread retries the first connection as well

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if getattr(reason_code, "is_failure", False):
            self._log(f"MQTT {self._where}: брокер отклонил подключение ({reason_code})")
        else:
            self._log(f"MQTT {self._where}: подключено")

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        self._log(f"MQTT {self._where}: соединение потеряно ({reason_code}), переподключение")

    def publish(self, topic: str, payload: str) -> bool:
        if not self._client.is_connected():
            return False
        return self._client.publish(topic, payload, qos=0).rc == self._mqtt.MQTT_ERR_SUCCESS

    def close(self) -> None:
        self._client.loop_stop()
        try:
            self._client.disconnect()
        except Exception:  # not connected
            pass


# --- the service -------------------------------------------------------------------------------

def _plain(features: Mapping[str, Any]) -> Dict[str, Any]:
    """``{feature id: value}`` from the Ditto shape or from plain values."""
    out = {}
    for key, body in features.items():
        if isinstance(body, Mapping):
            body = (body.get("properties") or {}).get("value")
        out[key] = body
    return out


class SimService:
    """Steps the simulator, follows the scenario thing and publishes the twins.

    ``scenario`` has ``read() -> features or None`` (it may raise); ``publisher`` has
    ``publish(topic, payload) -> bool``. ``tick()`` is one pass of the loop and ``run()`` repeats
    it in real time until ``stop`` is set.
    """

    def __init__(self, sim: Simulator, planner: PublishPlanner, scenario: Any, publisher: Any,
                 alive_file: Optional[str] = None, clock: Callable[[], float] = time.monotonic,
                 log: Log = log_line):
        self.sim = sim
        self.planner = planner
        self.scenario = scenario
        self.publisher = publisher
        self.alive_file = alive_file
        self.clock = clock
        self.log = log
        self.loop_s = float(sim.p("sim.loop_s"))
        self.budget = int(sim.p("publish.max_msg_per_s"))
        self.sent = 0
        self.ticks = 0
        self._window: deque = deque()                 # times of the messages sent in the last second
        self._pending: Dict[str, None] = {}           # names that are due and not sent yet, in order
        self._applied_key: Optional[str] = None
        self._rejected_key: Optional[str] = None
        self._last_revision: Optional[float] = None
        self._read_error: Optional[str] = None
        self._read_error_at = 0.0
        self._send_failed = False
        self._send_failed_at = 0.0
        self._failed_ticks = 0
        self._alive_failed = False
        self._fault_logged = 0.0
        self._day = int(sim.sim_days)
        self._day_totals = self._totals_now()

    # one pass ------------------------------------------------------------------------------

    def tick(self) -> None:
        """Touch the health file, step the simulator, follow the scenario, publish what is due."""
        self.touch_alive()
        self.ticks += 1
        self.sim.step(self.loop_s)
        self._follow_scenario()
        self._publish_due()
        self._daily_summary()

    # scenario ------------------------------------------------------------------------------

    def _follow_scenario(self) -> None:
        now = self.clock()
        try:
            raw = self.scenario.read()
        except Exception as exc:  # Ditto does not answer: the last scenario stays in force
            reason = str(exc) if isinstance(exc, SourceError) else f"{type(exc).__name__}: {exc}"
            if self._read_error is None or now - self._read_error_at >= REPEAT_LOG_S:
                self.log(f"сценарий не прочитан: {reason}; имитация идёт по прежнему сценарию, "
                         f"чтение повторяется")
                self._read_error_at = now
            self._read_error = reason
            return
        if self._read_error is not None:
            self.log("чтение сценария восстановлено")
            self._read_error = None
        if not raw:
            return
        features = _plain(raw)
        key = json.dumps(features, sort_keys=True, ensure_ascii=False, default=str)
        if key == self._applied_key or key == self._rejected_key:
            return
        revision = features.get("revision")
        label = features.get("label") or "без названия"
        revision_text = f"{revision:g}" if isinstance(revision, (int, float)) else "?"
        try:
            changed = self.sim.apply_scenario(raw)
        except (ValueError, KeyError, TypeError) as exc:
            self._rejected_key = key
            self.log(f"ревизия {revision_text} «{label}»: сценарий отклонён ({exc}); "
                     f"действует прежний сценарий")
            return
        self._applied_key, self._rejected_key = key, None
        knobs = [name for name in changed if name not in META_KNOBS]
        note = ""
        if (isinstance(revision, (int, float)) and isinstance(self._last_revision, (int, float))
                and revision < self._last_revision):
            note = f" (ревизия ниже прежней {self._last_revision:g}: сброс сценария)"
        if isinstance(revision, (int, float)):
            self._last_revision = revision
        what = "изменено: " + ", ".join(knobs) if knobs else "параметры не изменились"
        self.log(f"ревизия {revision_text} «{label}»: сценарий применён{note}; {what}")

    # publishing ----------------------------------------------------------------------------

    def _publish_due(self) -> None:
        now = self.clock()
        window = self._window
        while window and window[0] <= now - 1.0:
            window.popleft()
        for name in self.planner.due(now):
            if name not in NEVER_PUBLISHED:
                self._pending.setdefault(name)
        failed = False
        for name in list(self._pending):
            if len(window) >= self.budget:
                break                                   # the rest waits for the next pass
            try:
                payload = json.dumps(ditto_modify(self.sim.namespace, name, self.sim.features(name)),
                                     ensure_ascii=False, allow_nan=False)
            except (ValueError, KeyError, TypeError) as exc:   # a defect in one twin skips only that twin
                del self._pending[name]
                self.log(f"двойник {name}: сообщение не сформировано ({exc})")
                continue
            try:
                ok = bool(self.publisher.publish(telemetry_topic(name), payload))
            except Exception as exc:
                ok = False
                if not self._send_failed:
                    self.log(f"MQTT: ошибка отправки ({type(exc).__name__}: {exc})")
            if not ok:
                failed = True
                break                                   # the broker is away: try again next pass
            del self._pending[name]
            window.append(now)
            self.sent += 1
        self._note_send_state(failed, now)

    def _note_send_state(self, failed: bool, now: float) -> None:
        if failed:
            self._failed_ticks += 1
            if not self._send_failed or now - self._send_failed_at >= REPEAT_LOG_S:
                self.log(f"MQTT: сообщения не уходят, ожидают отправки: {len(self._pending)}; "
                         f"имитация продолжается, отправка повторяется")
                self._send_failed_at = now
            self._send_failed = True
        elif self._send_failed:
            self._send_failed = False
            self.log(f"MQTT: отправка восстановлена после {self._failed_ticks} неудачных проходов; "
                     f"в очереди {len(self._pending)}")
            self._failed_ticks = 0

    # day summary ---------------------------------------------------------------------------

    def _totals_now(self) -> Dict[str, float]:
        totals = self.sim.totals()
        return {key: totals[key] for key in ("ore_hoisted_t", "ore_milled_t", "gold_oz")}

    def _daily_summary(self) -> None:
        day = int(self.sim.sim_days)
        if day <= self._day:
            return
        totals = self.sim.totals()
        span, previous = day - self._day, self._day_totals
        link = str(self.sim.features("enterprise").get("binding_link", ""))
        head = f"сутки {day}" if span == 1 else f"сутки {self._day + 1}–{day} (за {span} сут.)"
        self.log(f"{head}: поднято руды {num(totals['ore_hoisted_t'] - previous['ore_hoisted_t'])} т, "
                 f"переработано {num(totals['ore_milled_t'] - previous['ore_milled_t'])} т, "
                 f"золота {num(totals['gold_oz'] - previous['gold_oz'], 1)} унц.; воздух: потребность "
                 f"{num(totals['air_demand_m3s'], 1)} / подача {num(totals['air_supply_m3s'], 1)} м³/с; "
                 f"узкое звено {LINK_RU.get(link, link or 'не определено').lower()}")
        self._day = day
        self._day_totals = {key: totals[key] for key in previous}

    # health and the loop -------------------------------------------------------------------

    def touch_alive(self) -> None:
        """Touch the health file (compose checks that it is younger than 30 s)."""
        if not self.alive_file:
            return
        try:
            Path(self.alive_file).touch()
        except OSError as exc:
            if not self._alive_failed:
                self._alive_failed = True
                self.log(f"файл готовности {self.alive_file} недоступен: {exc}")

    def run(self, stop: Any, max_seconds: Optional[float] = None) -> None:
        """Run in real time until ``stop`` is set (or ``max_seconds`` of real time have passed)."""
        self.touch_alive()
        started = next_at = self.clock()
        failures = 0
        while not stop.is_set():
            if max_seconds is not None and self.clock() - started >= max_seconds:
                break
            try:
                self.tick()
            except Exception as exc:  # a defect must not end the process
                failures += 1
                if failures == 1 or failures % 120 == 0:
                    self.log(f"сбой цикла (раз {failures}): {type(exc).__name__}: {exc}")
            next_at += self.loop_s
            now = self.clock()
            if now - next_at > MAX_LAG_S:               # do not catch up beyond a few seconds
                next_at = now
            while not stop.is_set():
                remaining = next_at - self.clock()
                if remaining <= 0:
                    break
                stop.wait(min(remaining, SLICE_S))
                self.touch_alive()

    def start_line(self, source_text: str, mqtt_text: str) -> str:
        periods = self.planner.periods()
        return (f"имитатор запущен: зерно {self.sim.seed}, ускорение ×{self.sim.speedup:g}, "
                f"периоды публикации S/M/L {periods['S']:g}/{periods['M']:g}/{periods['L']:g} с "
                f"(масштаб {self.planner.scale:g}, не более {self.budget} сообщений/с), шаг цикла "
                f"{self.loop_s:g} с, двойников в публикации {len(self.planner._names)}; "
                f"сценарий: {source_text}; {mqtt_text}")


# --- entry point -------------------------------------------------------------------------------

def env_number(name: str, cast: Callable[[str], Any], default: Any, log: Log = log_line) -> Any:
    """A positive number from the environment; a bad or missing value gives ``default``."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = cast(raw.strip())
        if not value > 0:
            raise ValueError("значение должно быть больше нуля")
        return value
    except ValueError as exc:
        log(f"переменная {name}={raw!r} не принята ({exc}); используется {default}")
        return default


def build_service(fixture: Optional[str], alive_file: Optional[str], log: Log = log_line) -> tuple:
    """The service for fixture mode (``fixture`` is a path, or ``"1"`` for the baseline) or for
    Ditto and MQTT. Returns ``(service, start_line_parts)``."""
    seed = env_number("SIM_SEED", int, None, log)
    sim = Simulator.from_files(seed=seed)
    speedup = env_number("SIM_SPEEDUP", float, None, log)
    if speedup is not None:
        sim.speedup = speedup
    planner = PublishPlanner(sim, env_number("PUBLISH_SCALE", float, None, log))
    if fixture:
        path = None if fixture.lower() in ("1", "true", "yes", "epoch") else fixture
        scenario: Any = ScenarioReader(FixtureSource(path))
        publisher: Any = NullPublisher()
        source_text = f"файл {path}" if path else "базовый"
        mqtt_text = "режим без брокера, сообщения только считаются"
    else:
        scenario = BackgroundSource(ScenarioReader(DittoSource([SCENARIO_THING]))).start()
        host, port = os.environ.get("MQTT_HOST", "mosquitto"), env_number("MQTT_PORT", int, 1883, log)
        source_text = f"Ditto {os.environ.get('DITTO_URL', 'http://localhost:8080')}"
        try:
            publisher = MqttPublisher(host, port, log)
            mqtt_text = f"MQTT {host}:{port}"
        except Exception as exc:  # no client library or a bad address: the simulation still runs
            log(f"MQTT не запущен ({type(exc).__name__}: {exc}); сообщения не отправляются")
            publisher = NullPublisher()
            mqtt_text = "MQTT выключен"
    service = SimService(sim, planner, scenario, publisher, alive_file=alive_file, log=log)
    return service, (source_text, mqtt_text)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m sekis.sim_service", description="Simulator service")
    parser.add_argument("--fixture", default=os.environ.get("SIM_FIXTURE") or None,
                        help="scenario JSON file instead of Ditto and MQTT; 1 = the baseline scenario")
    parser.add_argument("--alive-file", default=os.environ.get("ALIVE_FILE", DEFAULT_ALIVE_FILE))
    parser.add_argument("--seconds", type=float, default=None, help="stop after this many real seconds")
    args = parser.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):  # Russian log lines on any console
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    service, (source_text, mqtt_text) = build_service(args.fixture, args.alive_file)
    stop = threading.Event()

    def on_signal(signum, frame):
        stop.set()

    for name in ("SIGTERM", "SIGINT"):
        try:
            signal.signal(getattr(signal, name), on_signal)
        except (AttributeError, ValueError, OSError):
            pass
    log_line(service.start_line(source_text, mqtt_text))
    started = time.monotonic()
    try:
        service.run(stop, max_seconds=args.seconds)
    except KeyboardInterrupt:
        pass
    finally:
        elapsed = max(time.monotonic() - started, 1e-9)
        if hasattr(service.scenario, "close"):
            service.scenario.close()
        service.publisher.close()
        log_line(f"имитатор остановлен: сообщений {service.sent} за {elapsed:.0f} с "
                 f"({service.sent / elapsed:.1f}/с), моделируемое время {service.sim.sim_time}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
