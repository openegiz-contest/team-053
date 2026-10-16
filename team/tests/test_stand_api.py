"""Stand server and page (work package C3).

The server is started as a separate process on a free port: once in fixture mode
(no Ditto, no advisor) and once in live mode against two small stub servers that
stand in for Ditto and for the advisor service.
"""

import base64
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TEAM_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STAND_DIR = os.path.join(TEAM_DIR, "stand")
WEB_DIR = os.path.join(STAND_DIR, "web")
MODEL_DIR = os.path.join(TEAM_DIR, "model")
FIXTURE_DIR = os.path.join(STAND_DIR, "fixtures")
SECRET = "s3kis-Secret-Marker-91"   # stands in for the Ditto password
NS = "kz.sekis:"

# Buttons of spec 3.2: id -> Russian label that must be on the page.
BUTTONS = {
    "base": "Базовый режим",
    "step1200": "Цель 1,2 млн т/год",
    "step2000": "Цель 2,0 млн т/год",
    "step2500": "Цель 2,5 млн т/год",
    "advisor_next": "Снять узкое место",
    "advisor_all": "Применить все меры",
    "close_tu2": "Закрыть уклон ТУ-2",
    "close_tu1": "Закрыть уклон ТУ-1",
    "fan_vs2_fail": "Отказ вентилятора ВС-2",
    "pump_one_fail": "Отказ одного насоса +150",
    "pump_station_fail": "Обесточена насосная +150",
    "flood": "Паводок: приток 430 м³/ч",
    "grade_drop": "Содержание 1,76 г/т",
    "line2_down": "Остановить линию № 2",
    "vod_toggle": "Вентиляция по потребности",
    "undo": "Шаг назад",
    "reset": "Сброс",
}
# Toggle id -> (knob, value when on, check of a twin that visibly changes).
TOGGLES = {
    "close_tu2": ("tu2_closed", 1.0, lambda t: t["decline-tu2"]["state"] == "closed"),
    "close_tu1": ("tu1_closed", 1.0, lambda t: t["decline-tu1"]["state"] == "closed"),
    "fan_vs2_fail": ("fan_vs2_off", 1.0, lambda t: t["fan-vs2"]["state"] == "failed"
                     and t["mine"]["air_supply_m3s"] == 252.0),
    "pump_one_fail": ("pumps_failed_p150", 1.0, lambda t: t["ps-p150"]["pumps_available"] == 2.0),
    "pump_station_fail": ("pumps_failed_p150", 3.0, lambda t: t["ps-p150"]["state"] == "failed"
                          and t["lvl-000"]["state"] == "flooded"),
    "flood": ("inflow_factor", 2.18, lambda t: t["mine"]["inflow_m3h"] > 420
              and t["mon-volchevka"]["state"] == "exceeded"),
    "grade_drop": ("grade_gpt", 1.76, lambda t: t["plant"]["feed_grade"] == 1.76),
    "line2_down": ("line_down", 2.0, lambda t: t["plant-line-2"]["state"] == "off"),
}


def load_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Client:
    def __init__(self, port):
        self.base = f"http://127.0.0.1:{port}"

    def request(self, method, path, body=None, raw=None):
        data = raw if raw is not None else None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self.base + path, data=data, method=method)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as error:
            return error.code, dict(error.headers), error.read()

    def get(self, path):
        return self.request("GET", path)

    def json(self, path):
        status, _, body = self.get(path)
        return status, json.loads(body.decode("utf-8"))

    def post(self, body=None, path="/api/scenario", raw=None):
        status, _, answer = self.request("POST", path, body, raw)
        return status, json.loads(answer.decode("utf-8"))

    def features(self):
        """Thing name -> features, from GET /api/state."""
        _, state = self.json("/api/state")
        return {tid[len(NS):]: thing["f"] for tid, thing in state["things"].items()}


def start_server(extra_env):
    port = free_port()
    env = dict(os.environ)
    for key in ("STAND_FIXTURE", "DITTO_URL", "DITTO_USER", "ADVISOR_URL", "STAND_FIXTURE_SPEED"):
        env.pop(key, None)
    env.update(DITTO_PASSWORD=SECRET, PYTHONIOENCODING="utf-8", **extra_env)
    process = subprocess.Popen(
        [sys.executable, os.path.join(STAND_DIR, "server.py"), "--host", "127.0.0.1",
         "--port", str(port)],
        cwd=TEAM_DIR, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    client = Client(port)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"stand server exited with code {process.returncode}")
        try:
            if client.get("/healthz")[0] == 200:
                return process, client
        except OSError:
            time.sleep(0.1)
    process.kill()
    raise RuntimeError("stand server did not start")


def stop_server(process):
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()


class FixtureStandTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.process, cls.client = start_server({"STAND_FIXTURE": "1"})
        cls.registry = load_json(os.path.join(MODEL_DIR, "registry.json"))
        cls.ids = [thing["thingId"] for thing in cls.registry["things"]]

    @classmethod
    def tearDownClass(cls):
        stop_server(cls.process)

    def setUp(self):
        status, answer = self.client.post({"action": "reset"})
        self.assertEqual(status, 200, answer)
        self.defaults = answer["defaults"]

    # ---- reading

    def test_healthz(self):
        status, data = self.client.json("/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["mode"], "fixture")
        self.assertEqual(data["things"], 96)

    def test_state_shape(self):
        status, headers, body = self.client.get("/api/state")
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("application/json"))
        text = body.decode("utf-8")
        state = json.loads(text)
        self.assertIsInstance(state["sim_time"], str)
        self.assertRegex(state["sim_time"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d")
        self.assertIsInstance(state["revision"], int)
        self.assertEqual(list(state["things"]), self.ids)
        self.assertEqual(len(state["things"]), 96)
        # What scripts/stand-wait.sh looks for.
        self.assertEqual(len(re.findall(r'"kz\.sekis:[^"]+" *: *\{', text)), 96)
        self.assertRegex(text, r'"sim_day" *: *-?[0-9.]+')
        self.assertRegex(text, r'"sim_time" *: *"[^"]+"')
        by_id = {thing["thingId"]: thing for thing in self.registry["things"]}
        for thing_id, thing in state["things"].items():
            attrs = by_id[thing_id]["attributes"]
            self.assertEqual(set(thing), {"kind", "name", "parent", "attrs", "f"}, thing_id)
            self.assertEqual(thing["kind"], attrs["kind"])
            self.assertEqual(thing["name"], attrs["name"])
            self.assertEqual(thing["parent"], attrs.get("_parents"))
            self.assertEqual(thing["attrs"], attrs)
            self.assertEqual(set(thing["f"]), set(by_id[thing_id]["features"]), thing_id)
            for feature, value in thing["f"].items():
                baseline = by_id[thing_id]["features"][feature]["properties"]["value"]
                self.assertIs(type(value), type(baseline), f"{thing_id}.{feature} = {value!r}")
        self.assertEqual(state["things"][NS + "enterprise"]["f"]["sim_time"], state["sim_time"])

    def test_clock_moves(self):
        first = self.client.json("/api/state")[1]
        time.sleep(1.2)
        second = self.client.json("/api/state")[1]
        self.assertNotEqual(first["sim_time"], second["sim_time"])
        day = lambda state: state["things"][NS + "enterprise"]["f"]["sim_day"]
        self.assertGreaterEqual(day(second), day(first))

    def test_scenario_description(self):
        status, info = self.client.json("/api/scenario")
        self.assertEqual(status, 200)
        self.assertEqual(info["knobs"], info["defaults"])
        self.assertEqual(len(info["knobs"]), 16)
        self.assertEqual(info["undo_depth"], 0)
        self.assertEqual(set(info["presets"]), set(BUTTONS))
        self.assertEqual(info["label"], "Базовый режим")

    def test_advisor_report(self):
        status, report = self.client.json("/api/advisor")
        self.assertEqual(status, 200)
        caps = {row["id"]: row["cap_ktpa"] for row in report["links"]}
        reference = {"haulage": 926, "ventilation": 958, "stopes": 1024, "development": 1750,
                     "plant": 1000, "water": 1000, "tailings": 1057}      # spec 2.3, baseline
        for link, value in reference.items():
            self.assertAlmostEqual(caps[link], value, delta=value * 0.01, msg=link)
        self.assertEqual(len(report["links"]), 8)
        self.assertEqual(report["binding_link"], "haulage")
        self.assertEqual(next(iter(report["next_measure"]["set"])), "m_haul")
        first = ["haulage", "ventilation", "plant", "water", "stopes", "tailings"]
        second = first + ["plant", "stopes", "ventilation", "haulage", "water", "development"]
        expected = {1000: ["haulage", "ventilation"], 1200: first, 2000: second,
                    2500: second + ["plant", "stopes", "haulage"]}        # spec 3.4
        gold = {1000: 56.0, 1200: 67.2, 2000: 112.0, 2500: 140.0}
        self.assertEqual([row["target_ktpa"] for row in report["ladder"]], [1000, 1200, 2000, 2500])
        for row in report["ladder"]:
            target = int(row["target_ktpa"])
            self.assertEqual([step["link"] for step in row["steps"]], expected[target], target)
            self.assertEqual(row["achievable_ktpa"], target)
            self.assertAlmostEqual(row["gold_koz_year"], gold[target], delta=0.15)
        self.assertEqual(len(report["projection"]["rows"]), 10)
        self.assertEqual([row["year"] for row in report["projection"]["rows"]], list(range(2027, 2037)))
        self.assertEqual({check["id"] for check in report["calibration"]},
                         {f"C{n}" for n in range(1, 17)})       # C13-C16: out-of-sample checks
        for check in report["calibration"]:
            self.assertIn(check["basis_name"], ("подгонка", "независимая", "тождество"))
            self.assertTrue(check["source"])
        simulator = [check for check in report["calibration"] if check["kind"] == "simulator"]
        self.assertTrue(simulator and all(isinstance(check["model"], (int, float)) for check in simulator))
        for row in report["ladder"]:                              # one economics block per target
            self.assertEqual(row["economics"]["gold_price_usd_oz"], 4615)
        self.assertEqual([row["economics"]["capex_usd_m"] for row in report["ladder"]], [None, None, 125, 125])
        # the horizon of each target (section 11 item 3): the year it is held to, and the economics after tax
        self.assertEqual([row["horizon"]["held_to_year"] for row in report["ladder"]], [2036, 2036, 2034, 2030])
        self.assertEqual([row["horizon"]["label"] for row in report["ladder"]],
                         ["держится до 2036 г.", "держится до 2036 г.", "держится до 2034 г.", "держится до 2030 г."])
        for row in report["ladder"]:
            self.assertEqual(row["economics"]["cit_rate_pct"], 20)
            if not row["horizon"]["holds"]:
                self.assertIsNone(row["economics"]["variants"]["disclosed"]["payback_year"])
        self.assertEqual(report["projection"]["label"], "держится до 2036 г.")
        self.assertTrue(all(step["in_service_text"] for step in report["sequence"]))
        self.assertEqual(report["kpi"]["dewatering_margin_next_failure"], 2.54)

    def test_fixture_files(self):
        state = load_json(os.path.join(FIXTURE_DIR, "state.json"))
        self.assertEqual(list(state["things"]), self.ids)
        report = load_json(os.path.join(FIXTURE_DIR, "advisor.json"))
        self.assertEqual(self.client.json("/api/advisor")[1]["links"], report["links"])

    def test_calibration(self):
        status, data = self.client.json("/api/calibration")
        self.assertEqual(status, 200)
        self.assertTrue(data["all_analytic_passed"])
        self.assertGreaterEqual(data["analytic_total"], 9)
        self.assertEqual(data["analytic_passed"], data["analytic_total"])

    def test_params_and_geometry(self):
        status, params = self.client.json("/api/params")
        self.assertEqual(status, 200)
        self.assertEqual(params, load_json(os.path.join(MODEL_DIR, "params.json")))
        status, data = self.client.json("/api/geometry")
        path = os.path.join(MODEL_DIR, "geometry.json")
        if os.path.isfile(path):
            self.assertEqual(status, 200)
            self.assertEqual(data, load_json(path))
        else:
            self.assertEqual(status, 404)
            self.assertEqual(data["code"], "no_geometry")

    # ---- scenario actions

    def test_every_toggle_and_its_undo(self):
        for preset, (knob, on, visible) in TOGGLES.items():
            with self.subTest(preset=preset):
                status, answer = self.client.post({"preset": preset})
                self.assertEqual(status, 200, answer)
                self.assertTrue(answer["ok"])
                self.assertEqual(answer["knobs"][knob], on)
                self.assertEqual(answer["changed"], {knob: [self.defaults[knob], on]})
                features = self.client.features()
                self.assertEqual(features["scenario"][knob], on)
                self.assertEqual(features["scenario"]["label"], answer["label"])
                self.assertTrue(visible(features), f"{preset} changed no twin")
                # «Шаг назад»
                status, answer = self.client.post({"action": "undo"})
                self.assertEqual(status, 200, answer)
                self.assertEqual(answer["knobs"], self.defaults)
                features = self.client.features()
                self.assertEqual(features["scenario"][knob], self.defaults[knob])
                self.assertFalse(visible(features), f"{preset} not undone in the twins")
                # A toggle is its own undo.
                self.client.post({"preset": preset})
                status, answer = self.client.post({"preset": preset})
                self.assertEqual(answer["knobs"], self.defaults)
                self.client.post({"action": "reset"})

    def test_pump_presets_share_one_knob(self):
        self.client.post({"preset": "pump_station_fail"})
        _, answer = self.client.post({"preset": "pump_one_fail"})
        self.assertEqual(answer["knobs"]["pumps_failed_p150"], 1.0)
        _, answer = self.client.post({"preset": "pump_one_fail"})
        self.assertEqual(answer["knobs"]["pumps_failed_p150"], 0.0)

    def test_targets(self):
        _, answer = self.client.post({"preset": "step1200"})
        self.assertEqual((answer["knobs"]["target_ktpa"], answer["knobs"]["m_plant"]), (1200.0, 1.0))
        features = self.client.features()
        self.assertEqual(features["plant"]["capacity_ktpa"], 1200.0)
        self.assertEqual(features["advisor"]["target_ktpa"], 1200.0)
        _, answer = self.client.post({"preset": "step2000"})
        self.assertEqual((answer["knobs"]["target_ktpa"], answer["knobs"]["m_plant"]), (2000.0, 2.0))
        _, answer = self.client.post({"preset": "step2500"})
        self.assertEqual((answer["knobs"]["target_ktpa"], answer["knobs"]["m_plant"]), (2500.0, 3.0))
        self.assertNotEqual(self.client.features()["plant-line-6"]["state"], "planned")
        _, answer = self.client.post({"preset": "step1200"})     # m_plant never goes down here
        self.assertEqual((answer["knobs"]["target_ktpa"], answer["knobs"]["m_plant"]), (1200.0, 3.0))
        for expected_plant in (3.0, 2.0, 1.0):
            _, answer = self.client.post({"action": "undo"})
            self.assertEqual(answer["knobs"]["m_plant"], expected_plant)
        _, answer = self.client.post({"action": "undo"})
        self.assertEqual(answer["knobs"], self.defaults)
        self.assertEqual(answer["undo_depth"], 0)

    def test_advisor_next_and_undo(self):
        before = self.client.features()
        self.assertEqual(before["truck-06"]["state"], "parked")
        status, answer = self.client.post({"action": "advisor_next"})
        self.assertEqual(status, 200, answer)
        self.assertEqual(answer["changed"], {"m_haul": [0.0, 1.0]})
        features = self.client.features()
        self.assertNotEqual(features["truck-06"]["state"], "parked")
        self.assertGreater(features["advisor"]["cap_haulage_ktpa"], 1300)
        self.assertNotEqual(features["advisor"]["binding_link"], "haulage")
        report = self.client.json("/api/advisor")[1]
        self.assertEqual(report["report_revision"], answer["revision"])
        self.assertTrue(report["effects"]["items"])
        self.assertTrue(all(item["text"] for item in report["effects"]["items"]))
        _, answer = self.client.post({"action": "undo"})
        self.assertEqual(answer["knobs"], self.defaults)
        self.assertEqual(self.client.features()["truck-06"]["state"], "parked")

    def test_new_trucks_wait_for_air_and_the_advisor_says_so(self):
        """Spec 2.6 and decision 10.5: the bars, the twins and the texts tell one story."""
        self.client.post({"action": "advisor_next"})                 # haulage: trucks 06 and 07
        features = self.client.features()
        self.assertEqual((features["truck-06"]["state"], features["truck-07"]["state"]),
                         ("held_vent", "held_vent"))
        mine, advisor = features["mine"], features["advisor"]
        self.assertEqual((mine["state"], mine["units_held_vent"], mine["trucks_active"]),
                         ("restricted_air", 2.0, 5.0))
        self.assertEqual((mine["air_supply_m3s"], mine["air_demand_m3s"]), (322.0, 317.2))
        # the target is not shown as reached while two trucks stand at the portal
        self.assertEqual((advisor["binding_link"], advisor["next_measure"]), ("ventilation", "m_vent"))
        self.assertEqual((advisor["cap_ventilation_ktpa"], advisor["achievable_ktpa"]), (926.0, 926.0))
        self.assertEqual(advisor["air_demand_m3s"], 369.9)           # what the whole fleet in service needs
        self.assertEqual(features["enterprise"]["annual_rate_ktpa"], 926.0)
        report = self.client.json("/api/advisor")[1]
        self.assertFalse(report["target_reached"])
        waiting = "самосвалы №\u00a06–7"
        self.assertIn("в ожидании воздуха: " + waiting, report["links"][1]["detail"])
        self.assertIn("в работу возвращаются: " + waiting, report["next_measure"]["text"])
        held = [item for item in report["effects"]["items"] if item["id"] == "units_held_vent"]
        self.assertEqual(len(held), 1)
        self.assertIn(waiting, held[0]["text"])
        self.assertEqual((held[0]["before"], held[0]["after"], held[0]["trend"]), (0, 2, "worse"))
        # the fan on raise VPV returns them to work and the target is reached
        status, answer = self.client.post({"action": "advisor_next"})
        self.assertEqual(answer["changed"], {"m_vent": [0.0, 1.0]})
        features = self.client.features()
        self.assertEqual(features["mine"]["units_held_vent"], 0.0)
        self.assertNotEqual(features["mine"]["state"], "restricted_air")
        self.assertNotIn(features["truck-06"]["state"], ("held_vent", "parked"))
        self.assertEqual(features["mine"]["air_demand_m3s"], 369.9)
        report = self.client.json("/api/advisor")[1]
        self.assertTrue(report["target_reached"])
        self.assertEqual((report["binding_link"], report["achievable_ktpa"]), ("plant", 1000.0))

    def test_fan_failure_holds_the_units_of_the_hold_rule(self):
        self.client.post({"preset": "fan_vs2_fail"})
        features = self.client.features()
        self.assertEqual([features[f"truck-0{n}"]["state"] for n in (3, 4, 5)], ["held_vent"] * 3)
        self.assertEqual((features["lhd-04"]["state"], features["stp-000-1"]["state"]), ("standby_vent", "standby"))
        self.assertEqual((features["mine"]["units_held_vent"], features["mine"]["trucks_active"]), (4.0, 2.0))
        self.assertEqual(features["mine"]["air_demand_m3s"], 238.6)
        self.assertEqual((features["advisor"]["binding_link"], features["advisor"]["cap_ventilation_ktpa"]),
                         ("ventilation", 374.0))

    def test_advisor_all_and_undo(self):
        self.client.post({"preset": "step1200"})
        status, answer = self.client.post({"action": "advisor_all"})
        self.assertEqual(status, 200, answer)
        knobs = answer["knobs"]
        self.assertEqual([knobs[k] for k in ("m_haul", "m_plant", "m_water", "m_stopes", "m_vent",
                                             "m_tailings", "m_dev")], [1, 1, 1, 1, 1, 1, 0])
        report = self.client.json("/api/advisor")[1]
        self.assertTrue(report["target_reached"])
        self.assertIsNone(report["next_measure"])
        features = self.client.features()
        self.assertEqual(features["fan-vpv"]["state"], "running")
        self.assertEqual(features["tsf-cell5"]["state"], "standby")
        # With the target reached the action changes nothing and keeps the revision.
        status, again = self.client.post({"action": "advisor_all"})
        self.assertEqual((status, again["changed"], again["revision"]), (200, {}, answer["revision"]))
        self.assertIn("message", again)
        _, undone = self.client.post({"action": "undo"})
        self.assertEqual(undone["knobs"]["m_haul"], 0.0)
        self.assertEqual(undone["knobs"]["target_ktpa"], 1200.0)

    def test_line2_down_is_repaired_before_any_expansion(self):
        """Fix round 2, item 1: the advisor restarts the line through the same knob."""
        self.client.post({"preset": "line2_down"})
        report = self.client.json("/api/advisor")[1]
        step = report["next_measure"]
        self.assertEqual((step["kind"], step["measure"], step["set"]), ("disturbance", "restart_line",
                                                                      {"line_down": 0.0}))
        self.assertTrue(step["text"].startswith("запустить технологическую линию"), step["text"])
        self.assertEqual(self.client.features()["advisor"]["next_measure"], "restart_line")
        status, answer = self.client.post({"action": "advisor_next"})
        self.assertEqual(status, 200, answer)
        self.assertEqual(answer["changed"], {"line_down": [2.0, 0.0]})
        self.assertNotEqual(self.client.features()["plant-line-2"]["state"], "off")
        _, answer = self.client.post({"action": "undo"})
        self.assertEqual(answer["knobs"]["line_down"], 2.0)
        self.client.post({"action": "reset"})

    def test_economics_follow_a_new_target(self):
        self.client.post({"preset": "step2000"})
        items = self.client.json("/api/advisor")[1]["effects"]["items"]
        economics = [item for item in items if item["id"] == "economics"]
        self.assertEqual(len(economics), 1)
        # section 11 item 3: the ten-year economics and the hold year, never a payback for a target not held
        self.assertIn("держится до 2034 г.", economics[0]["text"])
        self.assertIn("окупаемость не указывается", economics[0]["text"])
        projection = self.client.json("/api/advisor")[1]["projection"]
        self.assertEqual((projection["target_ktpa"], projection["held_to_year"]), (2000, 2034))
        self.client.post({"action": "reset"})

    def test_knob_minus_plus(self):
        _, answer = self.client.post({"step": {"m_vent": 1}})
        self.assertEqual(answer["knobs"]["m_vent"], 1.0)
        self.assertEqual(self.client.features()["mine"]["air_supply_m3s"], 427.0)
        _, answer = self.client.post({"step": {"m_vent": 1}})
        self.assertEqual(answer["knobs"]["m_vent"], 2.0)
        status, answer = self.client.post({"step": {"m_vent": 1}})
        self.assertEqual((status, answer["code"]), (409, "out_of_range"))
        _, answer = self.client.post({"step": {"m_vent": -1}})
        self.assertEqual(answer["knobs"]["m_vent"], 1.0)
        _, answer = self.client.post({"set": {"m_haul": 2, "m_tailings": 1}})
        self.assertEqual((answer["knobs"]["m_haul"], answer["knobs"]["m_tailings"]), (2.0, 1.0))
        self.assertEqual(self.client.features()["truck-10"]["state"] == "parked", False)
        _, answer = self.client.post({"action": "undo"})
        self.assertEqual((answer["knobs"]["m_haul"], answer["knobs"]["m_tailings"]), (0.0, 0.0))
        status, answer = self.client.post({"step": {"m_dev": -1}})
        self.assertEqual((status, answer["code"]), (409, "out_of_range"))

    def test_rejected_requests(self):
        revision = self.client.json("/api/scenario")[1]["revision"]
        for body, code in (({"set": {"m_haul": 7}}, "bad_value"),
                           ({"set": {"m_haul": "2"}}, "bad_value"),
                           ({"set": {"revision": 5}}, "unknown_knob"),
                           ({"set": {"nope": 1}}, "unknown_knob"),
                           ({"step": {"tu1_closed": 1}}, "unknown_knob"),
                           ({"step": {"m_haul": 2}}, "bad_value"),
                           ({"preset": "nope"}, "unknown_preset"),
                           ({}, "bad_request"), ([1, 2], "bad_request")):
            with self.subTest(body=body):
                status, answer = self.client.post(body)
                self.assertEqual((status, answer["ok"], answer["code"]), (400, False, code))
                self.assertTrue(answer["error"])
        status, answer = self.client.post(raw=b"{not json")
        self.assertEqual((status, answer["code"]), (400, "bad_json"))
        status, answer = self.client.post({"action": "undo"})
        self.assertEqual((status, answer["code"]), (409, "nothing_to_undo"))
        self.assertEqual(self.client.json("/api/scenario")[1]["revision"], revision)
        self.assertEqual(self.client.json("/api/scenario")[1]["knobs"], self.defaults)

    def test_both_declines_closed_is_rejected(self):
        _, first = self.client.post({"preset": "close_tu2"})
        status, answer = self.client.post({"preset": "close_tu1"})
        self.assertEqual((status, answer["ok"], answer["code"]), (409, False, "both_declines_closed"))
        info = self.client.json("/api/scenario")[1]
        self.assertEqual((info["knobs"]["tu1_closed"], info["knobs"]["tu2_closed"]), (0.0, 1.0))
        self.assertEqual(info["revision"], first["revision"])
        self.assertEqual(info["undo_depth"], 1)
        status, answer = self.client.post({"set": {"tu1_closed": 1}})
        self.assertEqual((status, answer["code"]), (409, "both_declines_closed"))
        self.client.post({"action": "reset"})
        status, answer = self.client.post({"set": {"tu1_closed": 1, "tu2_closed": 1}})
        self.assertEqual((status, answer["code"]), (409, "both_declines_closed"))
        features = self.client.features()
        self.assertEqual((features["decline-tu1"]["state"], features["decline-tu2"]["state"]),
                         ("open", "open"))

    def test_reset_and_base(self):
        for ident, key in (("reset", "action"), ("base", "preset")):
            with self.subTest(ident=ident):
                self.client.post({"preset": "step2000"})
                self.client.post({"preset": "flood"})
                _, before = self.client.post({"step": {"m_haul": 1}})
                self.assertEqual(before["undo_depth"], 3)
                status, answer = self.client.post({key: ident})
                self.assertEqual(status, 200)
                self.assertEqual(answer["knobs"], self.defaults)
                self.assertEqual(answer["undo_depth"], 0)
                self.assertEqual(answer["label"], "Базовый режим")
                self.assertEqual(answer["revision"], before["revision"] + 1)
                status, answer = self.client.post({"action": "undo"})
                self.assertEqual((status, answer["code"]), (409, "nothing_to_undo"))
                features = self.client.features()
                self.assertEqual(features["mine"]["inflow_m3h"], 197.0)
                self.assertEqual(features["truck-06"]["state"], "parked")

    def test_revision_and_label(self):
        start = self.client.json("/api/scenario")[1]["revision"]
        _, first = self.client.post({"preset": "grade_drop"})
        self.assertEqual(first["revision"], start + 1)
        self.assertRegex(first["label"], "[А-Яа-я]")
        _, second = self.client.post({"preset": "step1200"})
        self.assertEqual(second["revision"], start + 2)
        _, same = self.client.post({"preset": "step1200"})          # nothing changes
        self.assertEqual((same["revision"], same["changed"]), (start + 2, {}))
        _, undone = self.client.post({"action": "undo"})            # undo is a change too
        self.assertEqual(undone["revision"], start + 3)
        state = self.client.json("/api/state")[1]
        self.assertEqual(state["revision"], start + 3)
        self.assertEqual(state["things"][NS + "scenario"]["f"]["revision"], float(start + 3))

    def test_undo_stack_is_50_deep(self):
        for _ in range(27):
            self.client.post({"preset": "grade_drop"})
            _, answer = self.client.post({"preset": "flood"})
        self.assertEqual(answer["undo_depth"], 50)

    def test_path_alias(self):
        status, answer = self.client.post(path="/api/scenario/close_tu2")
        self.assertEqual((status, answer["knobs"]["tu2_closed"]), (200, 1.0))
        status, answer = self.client.post(path="/api/scenario/undo")
        self.assertEqual((status, answer["knobs"]["tu2_closed"]), (200, 0.0))

    # ---- page and static files

    def owned_files(self):
        files = [os.path.join(WEB_DIR, "index.html"), os.path.join(WEB_DIR, "js", "app.js")]
        for folder in ("css", os.path.join("js", "panels")):
            for name in sorted(os.listdir(os.path.join(WEB_DIR, folder))):
                files.append(os.path.join(WEB_DIR, folder, name))
        return files

    def test_page_and_references(self):
        status, headers, body = self.client.get("/")
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("text/html"))
        html = body.decode("utf-8")
        self.assertIn('lang="ru"', html)
        references = re.findall(r'<link[^>]+href="([^"]+)"', html) \
            + re.findall(r'<script[^>]+src="([^"]+)"', html)
        self.assertGreaterEqual(len(references), 3)
        seen, queue = set(), list(references)
        while queue:
            path = queue.pop()
            if path in seen:
                continue
            seen.add(path)
            self.assertTrue(path.startswith("/"), path)
            self.assertTrue(os.path.isfile(os.path.join(WEB_DIR, path.lstrip("/"))), path)
            status, headers, content = self.client.get(path)
            self.assertEqual(status, 200, path)
            if path.endswith(".js"):
                self.assertTrue(headers["Content-Type"].startswith("text/javascript"), path)
                # Static imports; the two view modules are loaded with import() and may be absent.
                for target in re.findall(r"""^\s*(?:import|export)\b[^'"]*?from\s+['"]([^'"]+)['"]""",
                                         content.decode("utf-8"), re.M):
                    queue.append(urllib.parse.urljoin(path, target))
            elif path.endswith(".css"):
                self.assertTrue(headers["Content-Type"].startswith("text/css"), path)
        self.assertIn("/js/panels/dict.js", seen)
        for page in ("/embed/scene", "/embed/section", "/index.html"):
            self.assertEqual(self.client.get(page)[2], body, page)

    def test_no_external_url(self):
        for path in self.owned_files():
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
            self.assertNotRegex(text, r"https?://", path)
            self.assertNotRegex(text, r"""(?:src|href)\s*=\s*["']//""", path)
            self.assertNotRegex(text, r"@import|url\(\s*['\"]?(?:https?:)?//", path)
            self.assertNotIn("\r", text, f"{path} must have LF line endings")

    def test_all_buttons_in_russian(self):
        html = self.client.get("/")[2].decode("utf-8")
        found = dict(re.findall(r'<button[^>]*data-preset="([^"]+)"[^>]*>\s*([^<]+?)\s*<', html))
        static = {k: v for k, v in BUTTONS.items() if k != "vod_toggle"}   # the VOD switch is drawn by panels/vod.js
        self.assertEqual(set(found), set(static))
        for preset, label in static.items():
            self.assertEqual(found[preset], label, preset)
        for panel in ("Сценарии", "Советник по расширению", "Что изменилось", "Двойники",
                      "Проверка калибровки", "Данные и допущения"):
            self.assertIn(f">{panel}", html)
        for container in ("view-scene3d", "view-section2d"):
            self.assertIn(f'id="{container}"', html)

    def test_not_found(self):
        for path in ("/api/nope", "/nope.js", "/../server.py", "/%2e%2e/server.py",
                     "/js/../../server.py", "/css/..%2f..%2ffixtures/engine.py"):
            status, _, body = self.client.get(path)
            self.assertEqual(status, 404, path)
            self.assertNotIn(b"import ", body)
        status, answer = self.client.post({"preset": "base"}, path="/api/state")
        self.assertEqual(status, 404)

    def test_no_password_in_any_response(self):
        self.client.post({"preset": "close_tu2"})
        paths = ["/", "/healthz", "/api/state", "/api/scenario", "/api/advisor", "/api/calibration",
                 "/api/params", "/api/geometry", "/api/nope", "/embed/scene"]
        paths += ["/" + os.path.relpath(path, WEB_DIR).replace(os.sep, "/") for path in self.owned_files()]
        bodies = [self.client.get(path)[2] for path in paths]
        bodies.append(json.dumps(self.client.post({"preset": "close_tu1"})[1]).encode())
        bodies.append(json.dumps(self.client.post({"set": {"x": 1}})[1]).encode())
        for path, body in zip(paths + ["POST 409", "POST 400"], bodies):
            self.assertNotIn(SECRET.encode(), body, path)
            self.assertNotIn(b"password", body.lower(), path)


# --------------------------------------------------------------- live mode

class StubDitto(BaseHTTPRequestHandler):
    """Answers the three Ditto calls the Stand makes; records what it was asked."""

    things = {}
    batches = []
    puts = []
    auth = set()

    def log_message(self, fmt, *args):
        pass

    def reply(self, status, data=None):
        body = b"" if data is None else json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        StubDitto.auth.add(self.headers.get("Authorization"))
        url = urllib.parse.urlsplit(self.path)
        if url.path == "/api/2/things":
            ids = urllib.parse.parse_qs(url.query)["ids"][0].split(",")
            StubDitto.batches.append(len(ids))
            self.reply(200, [StubDitto.things[i] for i in ids if i in StubDitto.things])
        elif url.path == "/api/2/things/kz.sekis:scenario/features":
            self.reply(200, StubDitto.things[NS + "scenario"]["features"])
        else:
            self.reply(404, {"status": 404})

    def do_PUT(self):
        StubDitto.auth.add(self.headers.get("Authorization"))
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])).decode("utf-8"))
        if self.path == "/api/2/things/kz.sekis:scenario/features":
            StubDitto.puts.append(body)
            StubDitto.things[NS + "scenario"]["features"] = body
            self.reply(204)
        else:
            self.reply(404, {"status": 404})


class StubAdvisor(BaseHTTPRequestHandler):
    applied = []

    def log_message(self, fmt, *args):
        pass

    def reply(self, data):
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.reply({"report_revision": 0, "binding_link": "haulage", "calibration": [
            {"id": "C1", "kind": "analytic", "passed": True}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])).decode("utf-8"))
        StubAdvisor.applied.append(body)
        self.reply({"changes": {"m_haul": 1.0} if body["mode"] == "next"
                    else {"m_haul": 1.0, "m_vent": 1.0}})


class LiveStandTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        registry = load_json(os.path.join(MODEL_DIR, "registry.json"))
        StubDitto.things = {t["thingId"]: {k: v for k, v in t.items() if k != "_meta"}
                            for t in registry["things"]}
        cls.stubs = []
        for handler in (StubDitto, StubAdvisor):
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            cls.stubs.append(server)
        ditto, advisor = (f"http://127.0.0.1:{s.server_address[1]}" for s in cls.stubs)
        cls.process, cls.client = start_server(
            {"DITTO_URL": ditto, "DITTO_USER": "ditto", "ADVISOR_URL": advisor})
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and cls.client.json("/healthz")[1]["things"] < 96:
            time.sleep(0.2)

    @classmethod
    def tearDownClass(cls):
        stop_server(cls.process)
        for server in cls.stubs:
            server.shutdown()
            server.server_close()

    def test_reads_ditto_in_batches(self):
        status, state = self.client.json("/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(state["mode"], "live")
        self.assertEqual(len(state["things"]), 96)
        self.assertEqual(state["sim_time"], "2027-01-01T09:30:00")
        truck = state["things"][NS + "truck-01"]
        self.assertEqual((truck["kind"], truck["parent"]), ("haul_truck", NS + "mine"))
        self.assertEqual(truck["f"]["state"], "surface_haul")
        self.assertEqual(truck["attrs"]["payload_t"], 30)
        self.assertEqual(set(StubDitto.batches), {40, 16})          # 96 ids in batches of 40
        expected = "Basic " + base64.b64encode(f"ditto:{SECRET}".encode()).decode()
        self.assertEqual(StubDitto.auth, {expected})

    def test_scenario_is_written_with_one_put(self):
        self.client.post({"action": "reset"})
        StubDitto.puts.clear()
        status, answer = self.client.post({"preset": "close_tu2"})
        self.assertEqual(status, 200, answer)
        self.assertEqual(len(StubDitto.puts), 1)
        written = {key: body["properties"]["value"] for key, body in StubDitto.puts[0].items()}
        self.assertEqual(len(written), 18)                           # 16 knobs (with vod_enabled), revision, label
        self.assertEqual(written["tu2_closed"], 1.0)
        self.assertEqual(written["revision"], float(answer["revision"]))
        self.assertEqual(written["label"], "Закрыт уклон ТУ-2")
        for key, value in written.items():
            self.assertIs(type(value), str if key == "label" else float, key)
        state = self.client.json("/api/state")[1]
        self.assertEqual(state["things"][NS + "scenario"]["f"]["tu2_closed"], 1.0)
        status, answer = self.client.post({"preset": "close_tu1"})
        self.assertEqual((status, answer["code"]), (409, "both_declines_closed"))
        self.assertEqual(len(StubDitto.puts), 1)
        status, answer = self.client.post({"action": "undo"})
        self.assertEqual(answer["knobs"]["tu2_closed"], 0.0)
        self.assertEqual(StubDitto.puts[-1]["tu2_closed"]["properties"]["value"], 0.0)
        self.assertEqual(StubDitto.puts[-1]["revision"]["properties"]["value"], written["revision"] + 1)

    def test_foreign_reset_clears_undo(self):
        self.client.post({"action": "reset"})
        _, answer = self.client.post({"preset": "flood"})
        self.assertEqual(answer["undo_depth"], 1)
        # sekis-setup rewrites the scenario twin with revision 0.
        StubDitto.things[NS + "scenario"]["features"]["revision"]["properties"]["value"] = 0.0
        status, answer = self.client.post({"action": "undo"})
        self.assertEqual((status, answer["code"]), (409, "nothing_to_undo"))

    def test_advisor_proxy_and_apply(self):
        status, report = self.client.json("/api/advisor")
        self.assertEqual((status, report["binding_link"]), (200, "haulage"))
        status, data = self.client.json("/api/calibration")
        self.assertEqual((status, data["all_analytic_passed"]), (200, True))
        self.client.post({"action": "reset"})
        StubAdvisor.applied.clear()
        _, answer = self.client.post({"action": "advisor_next"})
        self.assertEqual(answer["changed"], {"m_haul": [0.0, 1.0]})
        _, answer = self.client.post({"action": "advisor_all"})
        self.assertEqual(answer["changed"], {"m_vent": [0.0, 1.0]})
        self.assertEqual(StubAdvisor.applied, [{"mode": "next"}, {"mode": "all"}])

    def test_no_password_in_any_response(self):
        for path in ("/healthz", "/api/state", "/api/scenario", "/api/advisor", "/api/calibration",
                     "/api/nope"):
            body = self.client.get(path)[2]
            self.assertNotIn(SECRET.encode(), body, path)
            self.assertNotIn(b"password", body.lower(), path)
            self.assertNotIn(b"Basic ", body, path)


if __name__ == "__main__":
    unittest.main()
