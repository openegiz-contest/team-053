"""Expansion Advisor service (spec 3.4, 5.1, 5.2): ``python -m sekis.advisor.service``.

Every second the service reads the scenario thing and the live things the advisor needs.
On a new scenario revision, on a change of the flooded levels, and at least every 30 s it
recomputes the report, publishes the features of ``kz.sekis:advisor`` as one Ditto-protocol
``modify`` message to MQTT topic ``telemetry/sekis/advisor`` and logs one line.

HTTP (port 8089):
    GET  /report    the full report (see ``sekis.advisor.engine.Advisor.report``)
    GET  /features  the Ditto-protocol message published last
    GET  /healthz   200 once a report exists
    POST /apply     ``{"mode": "next" | "all"}`` -> the knob changes for the Stand to write;
                    an optional ``"knobs": {...}`` computes them for that knob set instead of
                    the scenario read from the twins

The service outlives Ditto and the broker: a failed read is retried with a growing pause,
the MQTT client reconnects by itself, and the last report stays available meanwhile.

Fixture mode (``--fixture <path>`` or ``ADVISOR_FIXTURE=<path>``) needs neither Ditto nor a
broker: the state comes from a JSON file, re-read when it changes. The file is the body of the
Stand's ``GET /api/state`` (``{"things": {"kz.sekis:scenario": {"f": {...}}}}``) or a list of
Ditto things; things and features it leaves out take their values at the epoch.
``ADVISOR_FIXTURE=1`` runs on the epoch state with no file.

Environment: DITTO_URL, DITTO_USER, DITTO_PASSWORD, MQTT_HOST, MQTT_PORT, ADVISOR_FIXTURE,
ADVISOR_HOST, ADVISOR_PORT, ALIVE_FILE. Standard library, plus paho-mqtt outside fixture mode.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

from .. import ditto as ditto_client
from . import wording
from .engine import MODES, NAMESPACE, SCENARIO_THING, TELEMETRY_TOPIC, Advisor, Inputs

POLL_S = 1.0            # the twins are read this often (spec 3.1)
REFRESH_S = 30.0        # a report is never older than this (spec 3.4)
BACKOFF_MAX_S = 15.0    # longest pause between reads while the twins do not answer
SLICE_S = 1.0           # the health file is touched at least this often
DEFAULT_PORT = 8089
DEFAULT_ALIVE_FILE = "/tmp/alive"

Log = Callable[[str], None]


class SourceError(RuntimeError):
    """The twins could not be read this time."""


class NotReady(RuntimeError):
    """No report or scenario is known yet."""


def log_line(message: str) -> None:
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} advisor: {message}", flush=True)


# --- reading the twins -----------------------------------------------------------------------

def _short(thing_id: str) -> str:
    return str(thing_id).split(":", 1)[-1]


def _feature_values(thing: Mapping[str, Any]) -> Dict[str, Any]:
    """Feature values of one thing, from the Ditto shape or the plain shape of the Stand."""
    if isinstance(thing.get("f"), Mapping):
        return dict(thing["f"])
    values = {}
    for feature_id, body in (thing.get("features") or {}).items():
        properties = (body or {}).get("properties") or {}
        if "value" in properties:
            values[feature_id] = properties["value"]
    return values


def plain_things(document: Any) -> Dict[str, Dict[str, Any]]:
    """Thing name -> ``{feature id: value}`` from any of the accepted documents.

    Accepted: a list of Ditto things; ``{"things": [...]}``; ``{"things": {thing id: {"f": {...}}}}``
    (the Stand's ``/api/state``); ``{thing id: {...}}``.
    """
    things = document.get("things", document) if isinstance(document, Mapping) else document
    result: Dict[str, Dict[str, Any]] = {}
    if isinstance(things, Mapping):
        for thing_id, thing in things.items():
            if isinstance(thing, Mapping):
                result[_short(thing_id)] = _feature_values(thing)
    elif isinstance(things, list):
        for thing in things:
            if isinstance(thing, Mapping) and "thingId" in thing:
                result[_short(thing["thingId"])] = _feature_values(thing)
    else:
        raise SourceError("состояние двойников не является JSON-объектом или списком")
    return result


class FixtureSource:
    """State from a JSON file, re-read when the file changes; ``None`` gives the epoch state."""

    mode = "fixture"

    def __init__(self, path: Optional[str] = None):
        self.path = Path(path) if path else None
        self._stamp: Any = None
        self._things: Dict[str, Dict[str, Any]] = {}

    def read(self) -> Dict[str, Dict[str, Any]]:
        if self.path is None:
            return {}
        try:
            stat = self.path.stat()
            stamp = (stat.st_mtime_ns, stat.st_size)
            if stamp != self._stamp:
                with open(self.path, encoding="utf-8") as handle:
                    self._things = plain_things(json.load(handle))
                self._stamp = stamp
        except (OSError, ValueError) as exc:
            raise SourceError(f"файл состояния {self.path}: {exc}") from exc
        return self._things


class DittoSource:
    """The things the advisor reads, in one Ditto HTTP request."""

    mode = "live"

    def __init__(self, names: List[str], client: Optional[ditto_client.Ditto] = None):
        self.ids = [f"{NAMESPACE}:{name}" for name in names]
        self._client = client

    def read(self) -> Dict[str, Dict[str, Any]]:
        try:
            if self._client is None:  # built here, so that a missing password is retried, not fatal
                self._client = ditto_client.Ditto.from_env(timeout=5.0, retries=1, log=lambda message: None)
            query = urllib.parse.urlencode({"ids": ",".join(self.ids), "fields": "thingId,features"}, safe=":,")
            _, data = self._client.request("GET", f"things?{query}")
        except ditto_client.DittoError as exc:
            reason = str(exc).split(": ", 1)[-1]  # without the request line and its list of ids
            raise SourceError(f"Ditto: {reason}") from exc
        things = plain_things(data or [])
        if SCENARIO_THING not in things:
            raise SourceError(f"в Ditto нет двойника {NAMESPACE}:{SCENARIO_THING}")
        return things


# --- publishing ------------------------------------------------------------------------------

class NullPublisher:
    """Keeps the last message instead of sending it (fixture mode)."""

    enabled = False

    def __init__(self) -> None:
        self.last: Optional[tuple] = None

    def publish(self, topic: str, payload: str) -> bool:
        self.last = (topic, payload)
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
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="sekis-advisor")
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)
        self._client.connect_async(host, port, keepalive=30)
        self._client.loop_start()  # the loop thread retries the first connection as well
        self._where = f"{host}:{port}"

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


# --- the service -----------------------------------------------------------------------------

class AdvisorService:
    """Reads the twins, keeps the current report, publishes the advisor twin.

    ``source`` has ``read() -> {thing name: {feature id: value}}`` and raises ``SourceError``;
    ``publisher`` has ``publish(topic, payload) -> bool``. ``tick()`` is one pass of the loop
    and never raises; ``run()`` repeats it until ``stop`` is set.
    """

    def __init__(self, advisor: Advisor, source: Any, publisher: Any, alive_file: Optional[str] = None,
                 clock: Callable[[], float] = time.monotonic, log: Log = log_line):
        self.advisor = advisor
        self.source = source
        self.publisher = publisher
        self.alive_file = alive_file
        self.clock = clock
        self.log = log
        self.report: Optional[Dict[str, Any]] = None     # replaced as a whole, never edited
        self.envelope: Optional[Dict[str, Any]] = None   # the message of the current report
        self._inputs: Optional[Inputs] = None            # inputs of the current report
        self._before: Optional[Inputs] = None            # inputs before the last scenario change
        self._key: Any = None
        self._computed_at: Optional[float] = None
        self._unsent = False
        self._failures = 0
        self._alive_failed = False

    # one pass ------------------------------------------------------------------------------

    def tick(self) -> float:
        """Read, recompute when due, publish. Returns the pause before the next pass, seconds."""
        self.touch_alive()
        try:
            inputs = self.advisor.inputs_from_things(self.source.read())
        except Exception as exc:  # no reading this time: keep the last report and try again
            self._failures += 1
            pause = min(BACKOFF_MAX_S, POLL_S * 2 ** min(self._failures - 1, 10))
            if self._failures == 1 or self._failures % 20 == 0:
                kind = "" if isinstance(exc, SourceError) else f"{type(exc).__name__}: "
                self.log(f"двойники не прочитаны (попытка {self._failures}): {kind}{exc}; "
                         f"повтор через {pause:g} с")
            return pause
        if self._failures:
            self.log(f"чтение двойников восстановлено после {self._failures} неудачных попыток")
            self._failures = 0
        now = self.clock()
        key = inputs.key()
        if self._computed_at is None or key != self._key or now - self._computed_at >= REFRESH_S:
            self._recompute(inputs, key, now)
        elif self._unsent:
            self._publish()
        return POLL_S

    def _recompute(self, inputs: Inputs, key: Any, now: float) -> None:
        previous = self._inputs
        changed = previous is not None and (inputs.revision != previous.revision
                                            or dict(inputs.knobs) != dict(previous.knobs))
        before = previous if changed else self._before
        self._key, self._computed_at = key, now
        try:
            report = self.advisor.report(inputs, before)
            envelope = self.advisor.envelope(report)
        except ValueError as exc:  # a knob set the model has no answer for: the last report stays
            self.log(f"ревизия {inputs.revision} «{inputs.label}»: сценарий отклонён моделью ({exc}); "
                     f"действует прежний отчёт")
            return
        self.report, self.envelope, self._inputs, self._before = report, envelope, inputs, before
        sent = self._publish()
        step = report["next_measure"]
        measure = f"{step['link_name'].lower()}, {step['text']}" if step else "не требуется"
        if not self.publisher.enabled:
            mqtt = "MQTT выключен"
        else:
            mqtt = "MQTT: отправлено" if sent else "MQTT: брокер недоступен, отправка повторяется"
        self.log(f"ревизия {inputs.revision} «{inputs.label}»: узкое место {wording.EM_DASH} "
                 f"{report['binding_link_name'].lower()}, {wording.num(report['achievable_ktpa'])} тыс. т/год "
                 f"при цели {wording.num(report['target_ktpa'])}; мер до цели: {report['measures_needed']}; "
                 f"следующая мера: {measure}; {mqtt}")

    def _publish(self) -> bool:
        payload = json.dumps(self.envelope, ensure_ascii=False, allow_nan=False)
        try:
            sent = bool(self.publisher.publish(TELEMETRY_TOPIC, payload))
        except Exception as exc:
            self.log(f"MQTT: ошибка отправки ({type(exc).__name__}: {exc})")
            sent = False
        self._unsent = not sent
        return sent

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

    def run(self, stop: threading.Event) -> None:
        while not stop.is_set():
            started = self.clock()
            try:
                pause = self.tick()
            except Exception as exc:  # a defect must not end the process
                self.log(f"сбой цикла: {type(exc).__name__}: {exc}")
                pause = BACKOFF_MAX_S
            deadline = started + pause
            while not stop.is_set():
                remaining = deadline - self.clock()
                if remaining <= 0:
                    break
                stop.wait(min(remaining, SLICE_S))
                self.touch_alive()

    # requests ------------------------------------------------------------------------------

    def apply(self, mode: str, knobs: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        """Knob changes for ``mode``; see ``Advisor.apply``.

        Without ``knobs`` the scenario is read afresh, so that a request right after a write
        sees it; if that read fails, the inputs of the current report are used.
        """
        if knobs is not None:
            plain = {k: (v["properties"]["value"] if isinstance(v, Mapping) else v) for k, v in knobs.items()}
            inputs = (self._inputs or self.advisor.default_inputs()).with_knobs(plain)
        else:
            try:
                inputs = self.advisor.inputs_from_things(self.source.read())
            except Exception:
                inputs = self._inputs
        if inputs is None:
            raise NotReady("сценарий ещё не прочитан")
        return self.advisor.apply(inputs, mode)

    def health(self) -> Dict[str, Any]:
        age = None if self._computed_at is None else round(self.clock() - self._computed_at, 1)
        return {"status": "ok" if self.report is not None else "starting",
                "mode": getattr(self.source, "mode", "live"),
                "report_revision": self.report["report_revision"] if self.report else None,
                "report_age_s": age, "read_failures": self._failures, "mqtt_pending": self._unsent}


# --- HTTP ------------------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "SekisAdvisor/1.0"
    timeout = 10
    service: AdvisorService = None  # set by make_server

    def log_message(self, fmt, *args):  # request lines are not logged
        pass

    def send_json(self, status: int, body: Any) -> None:
        data = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def send_error_json(self, status: int, code: str, message: str) -> None:
        self.send_json(status, {"error": code, "message": message})

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path.rstrip("/") or "/"
        service = self.service
        if path == "/report":
            if service.report is None:
                self.send_error_json(503, "report_not_ready", "Отчёт ещё не рассчитан")
            else:
                self.send_json(200, service.report)
        elif path == "/features":
            if service.envelope is None:
                self.send_error_json(503, "report_not_ready", "Отчёт ещё не рассчитан")
            else:
                self.send_json(200, service.envelope)
        elif path == "/healthz":
            self.send_json(200 if service.report is not None else 503, service.health())
        else:
            self.send_error_json(404, "not_found", "Нет такого адреса")

    def do_POST(self):
        path = urllib.parse.urlsplit(self.path).path.rstrip("/")
        if path != "/apply":
            self.send_error_json(404, "not_found", "Нет такого адреса")
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            request = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except (ValueError, UnicodeDecodeError):
            self.send_error_json(400, "bad_request", "Тело запроса не является JSON")
            return
        mode = request.get("mode") if isinstance(request, dict) else None
        knobs = request.get("knobs") if isinstance(request, dict) else None
        if mode not in MODES or not (knobs is None or isinstance(knobs, dict)):
            self.send_error_json(400, "bad_request", 'Ожидается {"mode": "next"} или {"mode": "all"}')
            return
        try:
            self.send_json(200, self.service.apply(mode, knobs))
        except NotReady as exc:
            self.send_error_json(503, "report_not_ready", f"Советник не готов: {exc}")
        except (ValueError, KeyError, TypeError) as exc:
            self.send_error_json(409, "scenario_rejected", f"Сценарий отклонён моделью: {exc}")


def make_server(service: AdvisorService, host: str = "0.0.0.0", port: int = DEFAULT_PORT) -> ThreadingHTTPServer:
    """HTTP server for ``service``; the caller runs ``serve_forever`` (port 0 picks a free port)."""
    handler = type("AdvisorHandler", (Handler,), {"service": service})
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server


# --- entry point -----------------------------------------------------------------------------

def build_service(fixture: Optional[str], alive_file: Optional[str], log: Log = log_line) -> AdvisorService:
    """The service for fixture mode (``fixture`` is a path, or ``"1"`` for the epoch state) or for Ditto and MQTT."""
    advisor = Advisor()
    if fixture:
        source: Any = FixtureSource(None if fixture.lower() in ("1", "true", "yes", "epoch") else fixture)
        publisher: Any = NullPublisher()
    else:
        source = DittoSource(advisor.thing_names())
        try:
            publisher = MqttPublisher(os.environ.get("MQTT_HOST", "mosquitto"),
                                      int(os.environ.get("MQTT_PORT", "1883")), log)
        except Exception as exc:  # no client library or a bad address: the report is still served
            log(f"MQTT не запущен ({type(exc).__name__}: {exc}); двойник советника не обновляется")
            publisher = NullPublisher()
    return AdvisorService(advisor, source, publisher, alive_file=alive_file, log=log)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m sekis.advisor.service", description="Expansion Advisor service")
    parser.add_argument("--fixture", default=os.environ.get("ADVISOR_FIXTURE") or None,
                        help="JSON state file instead of Ditto and MQTT; 1 = the state at the epoch")
    parser.add_argument("--host", default=os.environ.get("ADVISOR_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("ADVISOR_PORT", DEFAULT_PORT)))
    parser.add_argument("--alive-file", default=os.environ.get("ALIVE_FILE", DEFAULT_ALIVE_FILE))
    parser.add_argument("--once", action="store_true", help="print one report as JSON and exit")
    args = parser.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):  # Russian log lines on any console
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    if args.once:
        quiet = AdvisorService(Advisor(), FixtureSource(None if not args.fixture or args.fixture == "1"
                                                        else args.fixture), NullPublisher(), log=lambda m: None)
        quiet.tick()
        if quiet.report is None:
            print("отчёт не рассчитан: состояние не прочитано", file=sys.stderr)
            return 1
        print(json.dumps(quiet.report, ensure_ascii=False, allow_nan=False, indent=1))
        return 0

    service = build_service(args.fixture, args.alive_file)
    server = make_server(service, args.host, args.port)
    stop = threading.Event()

    def on_signal(signum, frame):
        stop.set()

    for name in ("SIGTERM", "SIGINT"):
        try:
            signal.signal(getattr(signal, name), on_signal)
        except (AttributeError, ValueError, OSError):
            pass
    threading.Thread(target=server.serve_forever, name="advisor-http", daemon=True).start()
    source = f"файл {args.fixture}" if args.fixture else os.environ.get("DITTO_URL", "Ditto")
    log_line(f"советник запущен: HTTP {args.host}:{server.server_address[1]}, источник {wording.EM_DASH} {source}")
    try:
        service.run(stop)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
        service.publisher.close()
        log_line("советник остановлен")
    return 0


if __name__ == "__main__":
    sys.exit(main())
