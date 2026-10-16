#!/usr/bin/env python3
"""Web Stand of the Sekisovskoye twin: static page and HTTP API (standard library only).

    python stand/server.py [--port 8088] [--host 0.0.0.0]

Live mode (default): a background thread reads every kz.sekis thing from Eclipse
Ditto in batches once a second and caches the result; scenario actions are
written to kz.sekis:scenario with one PUT of all features; the advisor report is
proxied from ADVISOR_URL. The Ditto credentials stay in this process.

Fixture mode (STAND_FIXTURE=1): no Ditto and no advisor. State and report come
from stand/fixtures/ and scenario actions are applied to the in-memory fixture.

Environment: DITTO_URL, DITTO_USER, DITTO_PASSWORD, ADVISOR_URL, STAND_FIXTURE,
STAND_HOST, STAND_HTTP_PORT, STAND_FIXTURE_SPEED (simulated seconds per real
second of the fixture clock, default 60; 0 freezes it).

HTTP API (JSON, UTF-8; an error is {"ok": false, "code": "...", "error": "<Russian text>"}):

    GET  /healthz          {"status": "ok", "mode": "live"|"fixture", "things": n, "state_age_s": s}
    GET  /api/state        {"sim_time", "revision", "label", "mode", "age_s",
                            "things": {"kz.sekis:<name>": {"kind", "name", "parent", "attrs", "f"}}}
                           attrs: the Ditto attributes as stored; f: feature id -> properties.value
    GET  /api/scenario     {"revision", "label", "knobs", "defaults", "values", "undo_depth",
                            "presets", "mode"}
    POST /api/scenario     body {"preset": id} | {"action": id} | {"set": {knob: value}} |
                           {"step": {measure knob: +1 | -1}}; answers the GET shape plus
                           {"ok": true, "applied", "changed": {knob: [before, after]}, "message"?}
                           409 both_declines_closed | nothing_to_undo | out_of_range, 400 bad input
    POST /api/scenario/<id>   the same as {"preset": id}
    GET  /api/advisor      the advisor report, as the advisor service returns it at /report
    GET  /api/calibration  {"checks": [...], "analytic_total", "analytic_passed",
                            "all_analytic_passed"}
    GET  /api/params       model/params.json
    GET  /api/geometry     model/geometry.json (404 no_geometry while it does not exist)
    GET  /terrain/texture.jpg   model/terrain/texture.jpg, the satellite image of the 3D terrain
    GET  /, /embed/scene, /embed/section   the page; other paths are files of stand/web
"""

import argparse
import gzip
import importlib.util
import json
import mimetypes
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STAND_DIR = os.path.dirname(os.path.abspath(__file__))
TEAM_DIR = os.path.dirname(STAND_DIR)
WEB_DIR = os.path.join(STAND_DIR, "web")
FIXTURE_DIR = os.path.join(STAND_DIR, "fixtures")
MODEL_DIR = os.path.join(TEAM_DIR, "model")

NS = "kz.sekis:"
SCENARIO_ID = NS + "scenario"
BATCH = 40           # thing ids per Ditto request (spec 4.4)
POLL_S = 1.0         # Ditto polling period
UNDO_DEPTH = 50
MAX_BODY = 64 * 1024

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8", ".mjs": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8", ".svg": "image/svg+xml",
    ".png": "image/png", ".jpg": "image/jpeg", ".ico": "image/x-icon",
    ".txt": "text/plain; charset=utf-8", ".map": "application/json; charset=utf-8",
    ".woff2": "font/woff2", ".wasm": "application/wasm",
}
INDEX_PATHS = {"/", "/index.html", "/embed/scene", "/embed/section"}

# ------------------------------------------------------------------ scenario
# Knobs of kz.sekis:scenario and the values each may take (spec 3.1).
KNOB_VALUES = {
    "target_ktpa": (1000.0, 1200.0, 2000.0, 2500.0),
    "m_plant": (0.0, 1.0, 2.0, 3.0),
    "m_haul": (0.0, 1.0, 2.0, 3.0),
    "m_stopes": (0.0, 1.0, 2.0, 3.0),
    "m_vent": (0.0, 1.0, 2.0),
    "m_dev": (0.0, 1.0),
    "m_water": (0.0, 1.0, 2.0),
    "m_tailings": (0.0, 1.0),
    "tu1_closed": (0.0, 1.0),
    "tu2_closed": (0.0, 1.0),
    "fan_vs2_off": (0.0, 1.0),
    "pumps_failed_p150": (0.0, 1.0, 3.0),
    "inflow_factor": (1.0, 2.18),
    "grade_gpt": (2.05, 1.76),
    "line_down": (0.0, 1.0, 2.0, 3.0),
}
MEASURE_RU = {
    "m_plant": "Фабрика", "m_haul": "Откатка", "m_stopes": "Очистные блоки",
    "m_vent": "Вентиляция", "m_dev": "Проходка", "m_water": "Водоснабжение",
    "m_tailings": "Хвостохранилище",
}
BASE_LABEL = "Базовый режим"
# Toggles: id -> (knob, value when on, label when switched on, label when switched off).
TOGGLES = {
    "close_tu2": ("tu2_closed", 1.0, "Закрыт уклон ТУ-2", "Уклон ТУ-2 открыт"),
    "close_tu1": ("tu1_closed", 1.0, "Закрыт уклон ТУ-1", "Уклон ТУ-1 открыт"),
    "fan_vs2_fail": ("fan_vs2_off", 1.0, "Отказ вентилятора ВС-2", "Вентилятор ВС-2 восстановлен"),
    "pump_one_fail": ("pumps_failed_p150", 1.0, "Отказ одного насоса, гор. +150 м",
                      "Насосы гор. +150 м восстановлены"),
    "pump_station_fail": ("pumps_failed_p150", 3.0, "Обесточена насосная, гор. +150 м",
                          "Насосная гор. +150 м восстановлена"),
    "flood": ("inflow_factor", 2.18, "Паводок: приток 430 м³/ч", "Приток воды в норме"),
    "grade_drop": ("grade_gpt", 1.76, "Содержание 1,76 г/т", "Содержание 2,05 г/т"),
    "line2_down": ("line_down", 2.0, "Остановлена линия № 2", "Линия № 2 запущена"),
}
TARGETS = {
    "step1200": (1200.0, 1.0, False, "Цель 1,2 млн т/год"),
    "step2000": (2000.0, 2.0, False, "Цель 2,0 млн т/год"),
    "step2500": (2500.0, 3.0, True, "Цель 2,5 млн т/год"),
}
PRESET_IDS = (["base"] + list(TARGETS) + ["advisor_next", "advisor_all"] + list(TOGGLES)
              + ["undo", "reset"])


class ApiError(Exception):
    """An API failure with an HTTP status, a stable code and a Russian message."""

    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def load_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def default_knobs():
    """Defaults of the scenario knobs: the baseline of the scenario twin in the registry."""
    registry = load_json(os.path.join(MODEL_DIR, "registry.json"))
    for thing in registry["things"]:
        if thing["thingId"] == SCENARIO_ID:
            features = thing["features"]
            return {knob: float(features[knob]["properties"]["value"]) for knob in KNOB_VALUES}
    raise RuntimeError("registry.json has no kz.sekis:scenario")


def thing_ids():
    registry = load_json(os.path.join(MODEL_DIR, "registry.json"))
    return [thing["thingId"] for thing in registry["things"]]


def same(a, b):
    return abs(float(a) - float(b)) < 1e-9


def check_value(knob, value):
    """Return the allowed value equal to `value`, or raise ApiError."""
    if knob not in KNOB_VALUES:
        raise ApiError(400, "unknown_knob", f"Неизвестный параметр сценария: {knob}")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(400, "bad_value", f"Значение параметра {knob} должно быть числом")
    for allowed in KNOB_VALUES[knob]:
        if same(allowed, value):
            return allowed
    options = ", ".join(f"{v:g}" for v in KNOB_VALUES[knob])
    raise ApiError(400, "bad_value", f"Параметр {knob} принимает значения: {options}")


class Scenario:
    """Knob logic of spec 3.2 on top of a backend: presets, toggles, undo, reset."""

    def __init__(self, backend):
        self.backend = backend
        self.defaults = default_knobs()
        self.lock = threading.Lock()
        self.undo = []            # previous (knobs, label), newest last
        self.last_revision = None  # revision this process wrote last

    def read(self):
        """Current (knobs, revision, label) from the twin; forget undo after a foreign reset."""
        features = self.backend.read_scenario()
        knobs = dict(self.defaults)
        for knob in KNOB_VALUES:
            value = features.get(knob)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                knobs[knob] = float(value)
        revision = features.get("revision")
        revision = int(revision) if isinstance(revision, (int, float)) else 0
        label = features.get("label") if isinstance(features.get("label"), str) else BASE_LABEL
        if self.last_revision is not None and revision != self.last_revision:
            self.undo.clear()     # the twin was changed or reset by something else
        return knobs, revision, label

    def describe(self, knobs=None, revision=None, label=None):
        if knobs is None:
            with self.lock:
                knobs, revision, label = self.read()
        return {
            "revision": revision, "label": label, "knobs": knobs, "defaults": self.defaults,
            "values": {knob: list(values) for knob, values in KNOB_VALUES.items()},
            "undo_depth": len(self.undo), "presets": PRESET_IDS, "mode": self.backend.mode,
        }

    def handle(self, request):
        """Apply {"preset": id} | {"action": id} | {"set": {...}} | {"step": {...}}."""
        if not isinstance(request, dict):
            raise ApiError(400, "bad_request", "Ожидается JSON-объект")
        ident = request.get("preset", request.get("action"))
        with self.lock:
            knobs, revision, label = self.read()
            new, new_label, message = dict(knobs), label, None
            clear = False
            if ident is not None:
                if ident in ("base", "reset"):
                    new, new_label, clear = dict(self.defaults), BASE_LABEL, True
                elif ident == "undo":
                    if not self.undo:
                        raise ApiError(409, "nothing_to_undo", "Нет изменений для отмены")
                    new, previous_label = self.undo[-1]
                    new, new_label = dict(new), f"Шаг назад: {previous_label}"
                elif ident in TARGETS:
                    target, plant, exact, new_label = TARGETS[ident]
                    new["target_ktpa"] = target
                    new["m_plant"] = plant if exact else max(new["m_plant"], plant)
                elif ident in TOGGLES:
                    knob, on, label_on, label_off = TOGGLES[ident]
                    switch_on = not same(new[knob], on)
                    new[knob] = on if switch_on else self.defaults[knob]
                    new_label = label_on if switch_on else label_off
                elif ident in ("advisor_next", "advisor_all"):
                    mode = "next" if ident == "advisor_next" else "all"
                    changes, text, note = self.backend.advisor_apply(mode, knobs)
                    for knob, value in changes.items():
                        new[knob] = check_value(knob, value)
                    if not changes:
                        message = note or "Советник не предложил мер"
                    new_label = (f"Снято узкое место: {text}" if mode == "next" and text
                                 else "Снято узкое место" if mode == "next"
                                 else "Применены все меры советника")
                else:
                    raise ApiError(400, "unknown_preset", f"Неизвестный сценарий: {ident}")
                applied = ident
            elif isinstance(request.get("set"), dict) and request["set"]:
                for knob, value in request["set"].items():
                    new[knob] = check_value(knob, value)
                new_label, applied = self.knob_label(knobs, new), "set"
            elif isinstance(request.get("step"), dict) and request["step"]:
                for knob, delta in request["step"].items():
                    if knob not in MEASURE_RU:
                        raise ApiError(400, "unknown_knob", f"Кнопки − / + есть только у мер: {knob}")
                    if delta not in (1, -1):
                        raise ApiError(400, "bad_value", "Шаг меры равен +1 или −1")
                    target = new[knob] + delta
                    if not any(same(target, allowed) for allowed in KNOB_VALUES[knob]):
                        edge = "последняя" if delta > 0 else "нулевая"
                        raise ApiError(409, "out_of_range",
                                       f"Мера «{MEASURE_RU[knob]}»: уже {edge} ступень")
                    new[knob] = target
                new_label, applied = self.knob_label(knobs, new), "step"
            else:
                raise ApiError(400, "bad_request",
                               "Ожидается одно из полей: preset, action, set, step")

            if new["tu1_closed"] and new["tu2_closed"]:
                raise ApiError(409, "both_declines_closed",
                               "Нельзя закрыть оба транспортных уклона одновременно")
            changed = {knob: [knobs[knob], new[knob]] for knob in KNOB_VALUES
                       if not same(knobs[knob], new[knob])}
            if changed or clear:
                revision += 1
                features = dict(new)
                features["revision"] = float(revision)
                features["label"] = new_label
                self.backend.write_scenario(features, knobs)
                self.last_revision = revision
                if clear:
                    self.undo.clear()
                elif ident != "undo":
                    self.undo.append((knobs, label))
                    del self.undo[:-UNDO_DEPTH]
                label = new_label
            elif message is None:
                message = "Сценарий не изменился"
            if ident == "undo":
                self.undo.pop()
            result = self.describe(new, revision, label)
            result.update(ok=True, applied=applied, changed=changed)
            if message:
                result["message"] = message
            return result

    @staticmethod
    def knob_label(old, new):
        parts = []
        for knob in KNOB_VALUES:
            if same(old[knob], new[knob]):
                continue
            if knob in MEASURE_RU:
                parts.append(f"Мера «{MEASURE_RU[knob]}»: ступень {new[knob]:g}")
            elif knob == "target_ktpa":
                parts.append(f"Цель {new[knob]:g} тыс. т/год")
            else:
                parts.append(f"{knob} = {new[knob]:g}")
        return "; ".join(parts) if parts else "Сценарий не изменился"


# ------------------------------------------------------------------ backends

class FixtureBackend:
    """State and advisor report from stand/fixtures, no network."""

    mode = "fixture"

    def __init__(self):
        spec = importlib.util.spec_from_file_location(
            "sekis_stand_fixture_engine", os.path.join(FIXTURE_DIR, "engine.py"))
        self.engine = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.engine)
        self.model = self.engine.Model(MODEL_DIR)
        self.paths = self.engine.Paths(self.model, MODEL_DIR)
        self.base = load_json(os.path.join(FIXTURE_DIR, "state.json"))
        self.report = load_json(os.path.join(FIXTURE_DIR, "advisor.json"))
        scenario = self.base["things"][SCENARIO_ID]["f"]
        self.knobs = {knob: float(scenario[knob]) for knob in KNOB_VALUES}
        self.revision, self.label = 0, BASE_LABEL
        self.speed = float(os.environ.get("STAND_FIXTURE_SPEED", "60"))
        self.started = time.monotonic()
        self.lock = threading.Lock()

    def sim_seconds(self):
        return self.engine.FIXTURE_START_S + (time.monotonic() - self.started) * self.speed

    def read_scenario(self):
        with self.lock:
            features = dict(self.knobs)
            features.update(revision=self.revision, label=self.label)
            return features

    def write_scenario(self, features, previous):
        knobs = {knob: float(features[knob]) for knob in KNOB_VALUES}
        revision, label = int(features["revision"]), features["label"]
        sim_time = self.engine.sim_clock(self.model, self.sim_seconds())[0]
        report = self.engine.build_report(self.model, knobs, before_knobs=previous,
                                          revision=revision, label=label, sim_time=sim_time)
        with self.lock:
            self.knobs, self.revision, self.label, self.report = knobs, revision, label, report

    def state(self):
        with self.lock:
            knobs, revision, label, report = self.knobs, self.revision, self.label, self.report
        state = self.engine.build_state(self.model, self.base, knobs, revision, label,
                                        self.sim_seconds(), report, self.paths)
        state.update(mode=self.mode, age_s=0.0)
        return state

    def advisor_report(self):
        with self.lock:
            return self.report

    def advisor_apply(self, mode, knobs):
        """(knob changes, text of the first step for the label, note when nothing changes)."""
        result = self.engine.apply_changes(self.model, knobs, mode)
        steps = result["steps"]
        text = f"{steps[0]['link_name'].lower()}, {steps[0]['text']}" if steps else ""
        note = None
        if not steps:
            cap = self.engine.capacities(self.model, knobs)
            note = ("Цель достигнута, меры не требуются." if cap["achievable"] >= knobs["target_ktpa"]
                    else "На узком месте все ступени мер уже введены.")
        return result["changes"], text, note

    def health(self):
        return {"things": len(self.base["things"]), "state_age_s": 0.0}


class LiveBackend:
    """Ditto for twins and the scenario, the advisor service for the report."""

    mode = "live"

    def __init__(self):
        sys.path.insert(0, TEAM_DIR)
        from sekis.ditto import Ditto, DittoError
        self.DittoError = DittoError
        quiet = lambda message: None  # the poll loop reports state changes itself
        self.reader = Ditto.from_env(timeout=5.0, retries=1, log=quiet)
        self.writer = Ditto.from_env(timeout=8.0, retries=3, delay=0.5, log=quiet)
        self.advisor_url = os.environ.get("ADVISOR_URL", "http://sekis-advisor:8089").rstrip("/")
        self.ids = thing_ids()
        self.things = {}          # thing id -> state entry, replaced as a whole
        self.polled_at = None     # monotonic time of the last complete poll
        self.poll_ok = None
        self.report = None
        self.report_at = 0.0
        self.report_lock = threading.Lock()
        threading.Thread(target=self.poll_forever, name="ditto-poll", daemon=True).start()

    @staticmethod
    def entry(thing):
        attrs = thing.get("attributes") or {}
        features = {}
        for fid, body in (thing.get("features") or {}).items():
            properties = (body or {}).get("properties") or {}
            if "value" in properties:
                features[fid] = properties["value"]
        return {"kind": attrs.get("kind"), "name": attrs.get("name"),
                "parent": attrs.get("_parents"), "attrs": attrs, "f": features}

    def poll_once(self):
        things = {}
        for start in range(0, len(self.ids), BATCH):
            ids = ",".join(self.ids[start:start + BATCH])
            query = urllib.parse.urlencode({"ids": ids}, safe=":,")
            _, data = self.reader.request("GET", f"things?{query}")
            for thing in data or []:
                if isinstance(thing, dict) and "thingId" in thing:
                    things[thing["thingId"]] = self.entry(thing)
        self.things = things
        self.polled_at = time.monotonic()

    def poll_forever(self):
        while True:
            began = time.monotonic()
            try:
                self.poll_once()
                if self.poll_ok is not True:
                    log(f"Ditto read: {len(self.things)} of {len(self.ids)} things")
                self.poll_ok = True
            except Exception as exc:  # keep the last good cache, try again
                if self.poll_ok is not False:
                    log(f"Ditto read failed: {type(exc).__name__}: {exc}")
                self.poll_ok = False
            time.sleep(max(0.1, POLL_S - (time.monotonic() - began)))

    def state_age(self):
        return None if self.polled_at is None else round(time.monotonic() - self.polled_at, 1)

    def state(self):
        things = self.things
        enterprise = things.get(NS + "enterprise", {}).get("f", {})
        scenario = things.get(SCENARIO_ID, {}).get("f", {})
        revision = scenario.get("revision")
        return {"sim_time": enterprise.get("sim_time"),
                "revision": int(revision) if isinstance(revision, (int, float)) else 0,
                "label": scenario.get("label"), "things": things, "mode": self.mode,
                "age_s": self.state_age()}

    def read_scenario(self):
        try:
            _, data = self.writer.request("GET", f"things/{SCENARIO_ID}/features")
        except self.DittoError as exc:
            raise ApiError(502, "ditto_unavailable",
                           "Платформа двойников (Ditto) не отвечает") from exc
        return LiveBackend.entry({"features": data})["f"]

    def write_scenario(self, features, previous):
        body = {key: {"properties": {"value": value}} for key, value in features.items()}
        try:
            self.writer.put_features(SCENARIO_ID, body)
        except self.DittoError as exc:
            raise ApiError(502, "ditto_unavailable",
                           "Не удалось записать сценарий в Ditto") from exc
        cached = self.things.get(SCENARIO_ID)
        if cached:  # show the change before the next poll
            things = dict(self.things)
            things[SCENARIO_ID] = dict(cached, f=dict(features))
            self.things = things

    def advisor_call(self, path, payload=None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.advisor_url + path, data=data, method="GET" if data is None else "POST",
            headers={"Accept": "application/json", "Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=5.0) as response:
            return json.loads(response.read().decode("utf-8"))

    def advisor_report(self):
        with self.report_lock:
            if self.report is not None and time.monotonic() - self.report_at < 1.0:
                return self.report
            try:
                self.report = self.advisor_call("/report")
                self.report_at = time.monotonic()
            except (OSError, ValueError, urllib.error.URLError) as exc:
                if self.report is None:
                    raise ApiError(503, "advisor_unavailable", "Советник не отвечает") from exc
            return self.report

    def advisor_apply(self, mode, knobs):
        """Knob changes from POST /apply; for one step fall back to the advisor twin."""
        try:
            answer = self.advisor_call("/apply", {"mode": mode})
        except (OSError, ValueError, urllib.error.URLError) as exc:
            token = self.things.get(NS + "advisor", {}).get("f", {}).get("next_measure")
            if mode == "next" and token in MEASURE_RU:
                return {token: knobs[token] + 1.0}, MEASURE_RU[token].lower(), None
            if mode == "next" and token == "restore_pumps":
                return {"pumps_failed_p150": 0.0}, "водоотлив", None
            raise ApiError(503, "advisor_unavailable", "Советник не отвечает") from exc
        answer = answer if isinstance(answer, dict) else {}
        changes = answer.get("changes") if isinstance(answer.get("changes"), dict) else {}
        changes = {k: v for k, v in changes.items() if k in KNOB_VALUES}
        steps = [s for s in answer.get("steps") or [] if isinstance(s, dict)]
        if steps and steps[0].get("text"):
            text = f"{str(steps[0].get('link_name', '')).lower()}, {steps[0]['text']}".lstrip(", ")
        else:
            text = ", ".join(MEASURE_RU.get(knob, knob).lower() for knob in changes)
        note = answer.get("message") if isinstance(answer.get("message"), str) else None
        return changes, text, note

    def health(self):
        return {"things": len(self.things), "state_age_s": self.state_age()}


# ---------------------------------------------------------------------- HTTP

def log(message):
    print(time.strftime("%H:%M:%S ") + message, file=sys.stderr, flush=True)


def calibration_summary(report):
    checks = report.get("calibration") if isinstance(report, dict) else None
    checks = checks if isinstance(checks, list) else []
    analytic = [c for c in checks if isinstance(c, dict) and c.get("kind", "analytic") == "analytic"]
    passed = [c for c in analytic if c.get("passed") is True]
    return {"checks": checks, "analytic_total": len(analytic), "analytic_passed": len(passed),
            "all_analytic_passed": bool(analytic) and len(passed) == len(analytic)}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "SekisStand/1.0"
    backend = None
    scenario = None

    def log_message(self, fmt, *args):  # request lines are not logged
        pass

    # -- responses

    def send_body(self, status, body, content_type, cache="no-store"):
        if len(body) > 1024 and "gzip" in self.headers.get("Accept-Encoding", ""):
            body = gzip.compress(body, compresslevel=5)
            encoding = "gzip"
        else:
            encoding = None
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        if encoding:
            self.send_header("Content-Encoding", encoding)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def send_json(self, status, data):
        body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_body(status, body, CONTENT_TYPES[".json"])

    def send_error_json(self, error):
        self.send_json(error.status, {"ok": False, "code": error.code, "error": error.message})

    def send_file(self, path, cache="no-cache"):
        try:
            with open(path, "rb") as handle:
                body = handle.read()
        except OSError:
            raise ApiError(404, "not_found", "Файл не найден") from None
        extension = os.path.splitext(path)[1].lower()
        content_type = CONTENT_TYPES.get(extension) or mimetypes.guess_type(path)[0] \
            or "application/octet-stream"
        self.send_body(200, body, content_type, cache)

    # -- routing

    def do_GET(self):
        self.route("GET")

    def do_HEAD(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")

    def route(self, method):
        path = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)
        try:
            if method == "POST":
                self.post(path)
            else:
                self.get(path)
        except ApiError as error:
            self.send_error_json(error)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:  # never leak a traceback or the environment
            log(f"{method} {path}: {type(exc).__name__}: {exc}")
            self.send_error_json(ApiError(500, "internal", "Внутренняя ошибка сервера стенда"))

    def get(self, path):
        backend = self.backend
        if path == "/healthz":
            data = {"status": "ok", "mode": backend.mode}
            data.update(backend.health())
            self.send_json(200, data)
        elif path == "/api/state":
            self.send_json(200, backend.state())
        elif path == "/api/scenario":
            self.send_json(200, self.scenario.describe())
        elif path == "/api/advisor":
            self.send_json(200, backend.advisor_report())
        elif path == "/api/calibration":
            self.send_json(200, calibration_summary(backend.advisor_report()))
        elif path == "/api/params":
            self.send_file(os.path.join(MODEL_DIR, "params.json"), cache="no-store")
        elif path == "/api/geometry":
            geometry = os.path.join(MODEL_DIR, "geometry.json")
            if not os.path.isfile(geometry):
                raise ApiError(404, "no_geometry", "Файл геометрии model/geometry.json отсутствует")
            self.send_file(geometry, cache="no-store")
        elif path == "/terrain/texture.jpg":
            self.send_file(os.path.join(MODEL_DIR, "terrain", "texture.jpg"), cache="public, max-age=86400")
        elif path.startswith("/api/"):
            raise ApiError(404, "not_found", "Нет такого адреса API")
        elif path in INDEX_PATHS:
            self.send_file(os.path.join(WEB_DIR, "index.html"))
        else:
            self.send_file(self.static_path(path))

    @staticmethod
    def static_path(path):
        root = os.path.realpath(WEB_DIR)
        target = os.path.realpath(os.path.join(root, path.lstrip("/")))
        if os.path.commonpath([root, target]) != root or not os.path.isfile(target):
            raise ApiError(404, "not_found", "Файл не найден")
        return target

    def post(self, path):
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            self.close_connection = True
            raise ApiError(413, "too_large", "Слишком большой запрос")
        raw = self.rfile.read(length) if length else b""
        if path == "/api/scenario":
            try:
                request = json.loads(raw.decode("utf-8")) if raw.strip() else {}
            except ValueError:
                raise ApiError(400, "bad_json", "Тело запроса не является JSON") from None
        elif path.startswith("/api/scenario/"):
            request = {"preset": path[len("/api/scenario/"):]}
        else:
            raise ApiError(404, "not_found", "Нет такого адреса API")
        result = self.scenario.handle(request)
        if result["changed"]:
            log(f"scenario revision {result['revision']}: {result['label']}")
        self.send_json(200, result)


def make_server(host, port, fixture):
    backend = FixtureBackend() if fixture else LiveBackend()
    handler = type("StandHandler", (Handler,), {"backend": backend, "scenario": Scenario(backend)})
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server


def main():
    parser = argparse.ArgumentParser(description="Sekisovskoye Stand server")
    parser.add_argument("--host", default=os.environ.get("STAND_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("STAND_HTTP_PORT", "8088")))
    args = parser.parse_args()
    fixture = os.environ.get("STAND_FIXTURE", "") not in ("", "0", "false", "no")
    server = make_server(args.host, args.port, fixture)
    log(f"Stand listening on {args.host}:{server.server_address[1]}, "
        f"mode {'fixture' if fixture else 'live'}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
