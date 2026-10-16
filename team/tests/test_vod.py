"""Ventilation on demand (spec 3.5) and the plausibility fixes of 17 October (decision 11.4).

B   the control rule in the simulator: supply never below the requirement over seven days, the
    duty drops in the shift changes and with units held, the energy saving follows the cube law,
    the calibration at full work (the design 322 m3/s), the knob and its undo on the Stand.
A1  air only to the levels in use, leakage on the others, none on planned or flooded levels.
A2  flood thresholds sized from the workings, the time compression of the flood episode.
A3  the decline length factor explained against the reported development metres.
A4  the advisor's water figures on the basis of the twins; the stockpile stat in Grafana; the
    scenarios panel names the smallest link and the repair apart.
"""

import json
import math
import os
import socket
import statistics
import subprocess
import sys
import time
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

TEAM = Path(__file__).resolve().parent.parent
REPO = TEAM.parent
if str(TEAM) not in sys.path:
    sys.path.insert(0, str(TEAM))

from sekis import capacity as cap  # noqa: E402
from sekis import geometry  # noqa: E402
from sekis.advisor import Advisor  # noqa: E402
from sekis.sim import Simulator  # noqa: E402

REGISTRY = json.loads((TEAM / "model" / "registry.json").read_text(encoding="utf-8"))
PARAMS = json.loads((TEAM / "model" / "params.json").read_text(encoding="utf-8"))
MODEL = cap.load_model()
GEO = geometry.load()
BASE_FANS = ("fan-vs1", "fan-ug-p320", "fan-vs2")
SPEC = (TEAM / "SPEC.md").read_text(encoding="utf-8")


def new_sim(**knobs):
    sim = Simulator(MODEL, GEO, REGISTRY)
    if knobs:
        sim.apply_scenario(knobs)
    return sim


def hour_of_day(sim):
    clock = sim.sim_time[11:16]
    return int(clock[:2]) + int(clock[3:]) / 60.0


class TestVodRule(unittest.TestCase):
    """The control rule of spec 3.5 in the simulator."""

    @classmethod
    def setUpClass(cls):
        # one seven-day baseline run, sampled every simulated minute
        sim = new_sim()
        cls.samples = []
        for _ in range(7 * 1440):
            sim.advance(1)
            mine = sim.snapshot()["mine"]
            cls.samples.append((hour_of_day(sim), sim.shift, sim.productive, mine["air_delivered_m3s"], mine["vod_demand_m3s"], mine["fan_power_kw"],
                                mine["vod_units_waiting"], dict(sim.vod.flow)))
        cls.sim = sim
        cls.totals = sim.totals()

    def test_supply_never_below_the_requirement_in_seven_days(self):
        self.assertGreaterEqual(self.sim.vod.minutes, 7 * 1440)
        self.assertGreaterEqual(self.totals["vod_min_margin_m3s"], 0.0)       # every minute, unrounded
        for hour, _, _, delivered, demand, *_ in self.samples:
            self.assertGreaterEqual(delivered + 0.05, demand, hour)
        # units wait for the fans only rarely (a truck back from repair), never at a block start
        waiting = [s for s in self.samples if s[6] > 0]
        self.assertLess(len(waiting), 0.01 * len(self.samples))

    def test_full_work_needs_the_design_duty(self):
        # calibration: the baseline fleet in full work (317.2 m3/s + 5 %) takes the whole 322 m3/s,
        # so checks C6 and C7 and the advisor's supply hold as they are
        self.assertEqual(cap.vod_setpoint_m3s(MODEL, 317.22, BASE_FANS), 322.0)
        epoch = new_sim().snapshot()["mine"]
        self.assertEqual((epoch["air_delivered_m3s"], epoch["vod_state"]), (322.0, "full"))
        self.assertAlmostEqual(epoch["vod_demand_m3s"], 317.2, delta=0.05)
        rows = {row.id: row for row in cap.calibration_checks(MODEL)}
        self.assertTrue(rows["C6"].ok and rows["C7"].ok)
        busy = [s[3] for s in self.samples if s[2] and s[4] >= 317.0]
        self.assertTrue(busy)
        self.assertTrue(all(abs(value - 322.0) < 0.5 for value in busy))

    def test_duty_drops_in_the_shift_change_and_the_blast_windows(self):
        by_hour = {}
        for hour, _, productive, delivered, *_ in self.samples:
            by_hour.setdefault(int(hour), []).append(delivered)
        mean = {h: statistics.mean(v) for h, v in by_hour.items()}
        # 19:00-20:00 and 07:00-08:00 are blast windows, 13:00 and 01:00 the meal hours
        for quiet in (19, 7):
            self.assertLess(mean[quiet], 0.75 * 322, quiet)
        for busy in (10, 16, 22, 4):
            self.assertGreater(mean[busy], mean[19] + 50, busy)
        self.assertEqual(min(s[3] for s in self.samples), 189.0)   # the lowest duty: 75 + 51 + 63 m3/s
        # pre-ventilation: at the first minute of every productive block the air is already there
        starts = [i for i in range(1, len(self.samples)) if self.samples[i][2] and not self.samples[i - 1][2]]
        self.assertGreaterEqual(len(starts), 7 * 4 - 1)
        for i in starts:
            self.assertEqual(self.samples[i][6], 0.0, self.samples[i][0])       # nobody waits for air
            self.assertGreaterEqual(self.samples[i][3], self.samples[i][4], self.samples[i][0])
            self.assertGreater(self.samples[i][4], 250.0, self.samples[i][0])   # the block's units are in work

    def test_duty_drops_with_units_held_or_under_repair(self):
        held = new_sim(fan_vs2_off=1)
        held.advance(5)
        self.assertEqual(held.snapshot()["mine"]["air_delivered_m3s"], 252.0)   # the minimum on-time first
        held.advance(MODEL.p("vod.min_on_min") + 10)
        mine = held.snapshot()["mine"]
        self.assertGreater(mine["units_held_vent"], 0)
        # the units the hold rule keeps waiting are not in the demand: 238.6 m3/s + 5 % < 252
        self.assertAlmostEqual(mine["vod_demand_m3s"], 238.6, delta=0.05)
        self.assertAlmostEqual(mine["air_delivered_m3s"], min(252.0, 238.6 * 1.05), delta=0.6)
        # a truck under repair needs no air: with one of the five trucks away the fans run below 322
        repair = [s for s in self.samples if s[2] and 290.0 < s[4] < 310.0]
        self.assertTrue(repair)
        self.assertTrue(all(s[3] < 322.0 - 1.0 for s in repair if s[3] <= s[4] * 1.05 + 0.5))

    def test_energy_follows_the_cube_law_and_saves(self):
        fan = MODEL.fans["fan-vs1"]
        self.assertAlmostEqual(cap.fan_pressure_pa(fan, 75.0), 2500 / 4)
        self.assertAlmostEqual(cap.fan_power_at_kw(MODEL, fan, 75.0), 500.0 / 8)
        self.assertAlmostEqual(cap.fan_power_at_kw(MODEL, fan, 150.0), 500.0)
        # the energy of the run equals the sum of P_design x (Q / duty)^3 over the minutes
        energy = 0.0
        for *_, flows in self.samples:
            energy += sum(MODEL.fans[name].duty_m3s * MODEL.fans[name].pressure_pa / 0.75 / 1000
                          * (flow / MODEL.fans[name].duty_m3s) ** 3 for name, flow in flows.items()) / 60.0
        self.assertAlmostEqual(energy, self.totals["fan_energy_kwh"], delta=1.0)
        fixed = self.totals["fan_energy_fixed_kwh"]
        self.assertAlmostEqual(fixed / 7, 1120.0 * 24, delta=1.0)
        saving_per_day = (fixed - self.totals["fan_energy_kwh"]) / 7
        self.assertGreater(saving_per_day, 3000.0)
        self.assertLess(saving_per_day, 0.5 * 1120 * 24)
        mine = self.sim.snapshot()["mine"]
        self.assertGreater(mine["fan_saving_day_kwh"], 3000.0)
        self.assertAlmostEqual(mine["fan_saving_today_kzt"], round(mine["fan_saving_today_kwh"] * 35), delta=35)

    def test_off_runs_the_design_duty_and_the_toggle_works_both_ways(self):
        sim = new_sim(vod_enabled=0)
        sim.run_days(1)
        mine = sim.snapshot()["mine"]
        self.assertEqual((mine["vod_state"], mine["air_delivered_m3s"], mine["fan_power_kw"]), ("off", 322.0, 1120.0))
        self.assertEqual(mine["fan_saving_day_kwh"], 0.0)
        self.assertEqual({sim.snapshot()[f]["air_flow_m3s"] for f in BASE_FANS}, {150.0, 102.0, 70.0})
        # switched on in the blast window: after the minimum on-time the fans come down to the floor
        while not sim.in_blast:
            sim.advance(1)
        sim.apply_scenario({"vod_enabled": 1})
        self.assertEqual(sim.snapshot()["mine"]["air_delivered_m3s"], 322.0)
        sim.advance(MODEL.p("vod.min_on_min") + 15)
        self.assertLess(sim.snapshot()["mine"]["air_delivered_m3s"], 322.0)
        # and off again (the undo): the design duty at once
        sim.apply_scenario({"vod_enabled": 0})
        self.assertEqual(sim.snapshot()["mine"]["air_delivered_m3s"], 322.0)

    def test_new_units_enter_only_when_the_fans_have_ramped_up(self):
        sim = new_sim()
        sim.advance(24.5 * 60)                       # 10:00 on day 2
        sim.apply_scenario({"m_haul": 1})            # trucks 06 and 07 wait for air (the hold rule)
        sim.advance(2)
        self.assertEqual(sim.held_trucks, ("truck-07", "truck-06"))
        sim.apply_scenario({"m_vent": 1})            # 427 m3/s in service: the hold rule releases them
        margins = []
        for _ in range(90):
            sim.advance(1)
            mine = sim.snapshot()["mine"]
            margins.append(mine["air_delivered_m3s"] - mine["vod_demand_m3s"])
        self.assertGreaterEqual(min(margins), -0.05)
        self.assertEqual(sim.held_trucks, ())
        self.assertGreater(sim.snapshot()["mine"]["air_delivered_m3s"], 322.0)   # 369.9 m3/s + 5 %
        self.assertLessEqual(sim.snapshot()["mine"]["air_delivered_m3s"], 427.0)

    def test_hoisting_is_not_changed_by_the_fans(self):
        hoisted = {}
        for enabled in (1, 0):
            sim = new_sim(vod_enabled=enabled)
            sim.run_days(30)
            hoisted[enabled] = sim.ore_hoisted_t
        self.assertAlmostEqual(hoisted[1] / hoisted[0], 1.0, delta=0.01)


class TestLevelAir(unittest.TestCase):
    """A1: air only to the levels in use (decision 11.4)."""

    def test_backfilled_levels_carry_leakage_only(self):
        sim = new_sim()
        sim.advance(60)
        snap = sim.snapshot()
        for name in ("lvl-p320", "lvl-p250", "lvl-p200"):
            self.assertEqual(snap[name]["air_required_m3s"], 0.0, name)
            self.assertLess(snap[name]["air_flow_m3s"], 15.0, name)      # 36 m3/s of leakage over three levels
            self.assertGreater(snap[name]["air_flow_m3s"], 10.0, name)
        for name in ("lvl-p150", "lvl-p100", "lvl-p050", "lvl-000"):
            required = snap[name]["air_required_m3s"]
            self.assertAlmostEqual(required, 180 * 0.8 / 5 + 0.06 * snap[name]["diesel_kw"], delta=0.11)
            self.assertLessEqual(snap[name]["air_flow_m3s"], 1.06 * required + 0.1, name)   # VOD: about 5 % over

    def test_flooded_levels_get_no_air(self):
        sim = new_sim(pumps_failed_p150=3)
        sim.advance(12 * 60)
        snap = sim.snapshot()
        for name in ("lvl-m050", "lvl-000"):
            self.assertEqual(snap[name]["state"], "flooded")
            self.assertEqual((snap[name]["air_flow_m3s"], snap[name]["air_required_m3s"]), (0.0, 0.0))

    def test_a_level_whose_lhd_waits_for_air_shows_short(self):
        sim = new_sim(fan_vs2_off=1)
        sim.advance(30)
        snap = sim.snapshot()
        self.assertEqual(snap["mine"]["state"], "restricted_air")
        self.assertIn("lhd-04", sim.held_lhds)
        level = next(st.level.name for st in sim.mining.stopes if st.lhd is not None and st.lhd.name == "lhd-04")
        self.assertLess(snap[level]["air_flow_m3s"], snap[level]["air_required_m3s"])


class TestFloodThresholds(unittest.TestCase):
    """A2: thresholds from the workings; the flood episode shown 24 times faster."""

    def lengths(self, level):
        obj = GEO.doc["objects"][f"kz.sekis:{level}"]
        drive = sum(math.dist(a, b) for a, b in zip(obj["points"], obj["points"][1:]))
        links = {}
        for link in obj["links"]:
            if "points" in link:
                length = sum(math.dist(a, b) for a, b in zip(link["points"], link["points"][1:]))
                links.setdefault(link.get("role"), []).append((link["to"], length))
        return drive, links

    def test_thresholds_follow_the_workings(self):
        section = MODEL.p("water.flood_section_m2")
        per_vm = 1 / math.sin(math.radians(MODEL.p("decline.slope_deg"))) * MODEL.p("decline.length_factor")
        drive, links = self.lengths("lvl-m050")
        access = dict(links["access"])["kz.sekis:decline-tu1"]       # TU2 does not reach -50 m yet
        m050 = (drive + access + sum(length for _, length in links["crosscut"])) * section
        self.assertAlmostEqual(m050, MODEL.p("water.flood_threshold_m050_m3"), delta=0.01 * m050)
        ramps = ((0 - MODEL.p("decline.tu1.bottom_m")) + (0 - MODEL.p("decline.tu2.bottom_m"))) * per_vm * section
        drive, links = self.lengths("lvl-000")
        level0 = (drive + sum(length for _, length in links["access"]) + sum(length for _, length in links["crosscut"]))
        total = m050 + ramps + level0 * section
        self.assertAlmostEqual(total, MODEL.p("water.flood_threshold_000_m3"), delta=0.01 * total)
        self.assertGreater(MODEL.p("water.flood_threshold_m050_m3"), 10000)

    def test_the_episode_is_compressed_and_the_stand_says_so(self):
        k = MODEL.p("water.flood_compression")
        free = 1800 * 0.6 + 600 * 0.6
        hours_m050 = (free + MODEL.p("water.flood_threshold_m050_m3")) / 197 / k
        hours_000 = (free + MODEL.p("water.flood_threshold_000_m3")) / 197 / k
        self.assertTrue(3.0 < hours_m050 < 4.0)           # about 3.5 real minutes at 60x
        self.assertTrue(9.0 < hours_000 < 11.0)           # about 10 real minutes
        scenarios = (TEAM / "stand" / "web" / "js" / "panels" / "scenarios.js").read_text(encoding="utf-8")
        self.assertIn("water.flood_compression", scenarios)
        self.assertIn("ускорен", scenarios)
        sim = new_sim()
        self.assertEqual(sim.dewater.compression(), 1.0)
        sim.apply_scenario({"pumps_failed_p150": 3})
        self.assertEqual(sim.dewater.compression(), k)


class TestDeclineLengthFactor(unittest.TestCase):
    """A3: the factor stays 1.15 and its source explains the 14.4 m per vertical metre."""

    def test_source_and_spec_explain_the_gap(self):
        self.assertEqual(MODEL.p("decline.length_factor"), 1.15)
        source = PARAMS["decline.length_factor"]["source"]
        for text in ("230", "14.4", "8.26", "turnouts", "K_HAUL"):
            self.assertIn(text, source)
        self.assertAlmostEqual(230 / 16, 14.4, delta=0.05)
        self.assertAlmostEqual(1 / math.sin(math.radians(8)) * 1.15, 8.26, delta=0.01)
        self.assertIn("14.4 m of decline per vertical metre", SPEC)


class TestWaterBasis(unittest.TestCase):
    """A4a, A4b: the advisor's water figures on the basis of the twins."""

    @classmethod
    def setUpClass(cls):
        cls.advisor = Advisor()

    def kpi(self, **knobs):
        return self.advisor.report(self.advisor.default_inputs().with_knobs(knobs))["kpi"]

    def test_flood_discharge_mean_and_with_every_line(self):
        kpi = self.kpi(inflow_factor=2.18)
        self.assertAlmostEqual(kpi["discharge_m3h"], 236.6, delta=0.2)
        self.assertAlmostEqual(kpi["permit_use_pct"], 108.1, delta=0.2)
        self.assertAlmostEqual(kpi["discharge_all_lines_m3h"], 225.5, delta=0.2)
        self.assertAlmostEqual(kpi["permit_use_all_lines_pct"], 103.1, delta=0.2)
        site = 0.603 * 926.4 * 1000 / (360 * 24)           # the advisor's mine rate over the simulated days
        # the outfall twin of the simulator with every line running: the same plant feed, and the site water at
        # the simulator's own 24-hour hoisting rate, which swings with the trucks under repair
        sim = new_sim(inflow_factor=2.18)
        sim.run_days(1.5)
        values, sums = [], []
        for _ in range(5 * 24 * 6):
            sim.advance(10)
            snap = sim.snapshot()
            if snap["plant"]["lines_running"] == 3.0 and snap["mon-volchevka"]["discharge_m3h"] > 0:
                values.append(snap["mon-volchevka"]["discharge_m3h"])
                # same basis: discharge + site use = mine water - plant water of three lines (1-hour means)
                sums.append(snap["mon-volchevka"]["discharge_m3h"] + snap["water"]["site_use_m3h"])
        self.assertGreater(len(values), 100)
        self.assertAlmostEqual(statistics.median(sums), kpi["discharge_all_lines_m3h"] + site, delta=2.0)
        self.assertAlmostEqual(statistics.median(values), kpi["discharge_all_lines_m3h"], delta=6.0)
        self.assertGreater(abs(statistics.median(values) - 247.6), 15.0)     # the old basis: feed = mine rate

    def test_pump_station_failure_deficit(self):
        kpi = self.kpi(pumps_failed_p150=3.0)
        self.assertAlmostEqual(kpi["water_deficit_m3h"], 192.8, delta=0.2)
        self.assertAlmostEqual(kpi["water_deficit_all_lines_m3h"], 204.0, delta=0.2)
        plant_all_lines = 1.123 * 1000 * 1000 / 8760 / 0.92      # the plant water of three lines running
        sim = new_sim(pumps_failed_p150=3)
        sim.advance(36 * 60)                      # the ponds are empty after about 20 h
        values = []
        for _ in range(36 * 6):
            sim.advance(10)
            snap = sim.snapshot()
            if all(snap[f"plant-line-{n}"]["state"] != "maintenance" for n in (1, 2, 3)):
                values.append(snap["water"]["deficit_m3h"])
                # same basis: the deficit is the plant water of three lines plus the site water not met
                self.assertAlmostEqual(snap["water"]["deficit_m3h"] - snap["water"]["site_use_m3h"],
                                       plant_all_lines, delta=1.0)
        self.assertTrue(values)
        # the simulator still hoists the broken ore of the flooded days at about the baseline rate, so its site
        # water sits near the advisor's figure for the station failure before the levels flood
        self.assertAlmostEqual(statistics.median(values), kpi["water_deficit_all_lines_m3h"], delta=6.0)

    def test_the_basis_is_named(self):
        kpi = self.kpi(inflow_factor=2.18)
        self.assertIn("фабрика 1 000 тыс. т/год", kpi["water_basis"].replace(" ", " "))
        report = self.advisor.report(self.advisor.default_inputs().with_knobs({"inflow_factor": 2.18}))
        text = report["conditions"][0]["text"]
        self.assertIn("236,6", text)
        self.assertIn("при всех линиях фабрики в работе 225,5", text)


class TestStandTexts(unittest.TestCase):
    """A4c, A4d and the VOD panel on the page."""

    def test_grafana_stockpile_stat_says_what_it_counts(self):
        path = REPO / "deploy" / "compose" / "grafana" / "dashboards" / "Sekisovskoye" / "sekis-overview.json"
        text = path.read_text(encoding="utf-8")
        self.assertIn("Склад: суток питания без подачи руды", text)
        self.assertNotIn("Хватит на", text)
        json.loads(text)

    def test_scenarios_panel_names_the_smallest_link_and_the_repair_apart(self):
        js = (TEAM / "stand" / "web" / "js" / "panels" / "scenarios.js").read_text(encoding="utf-8")
        self.assertIn("advisor.binding", js)
        self.assertIn("Сначала устранить: ", js)
        self.assertIn("Сейчас ограничивает: ", js)

    def test_vod_panel_is_mounted(self):
        web = TEAM / "stand" / "web"
        html = (web / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="vod"', html)
        self.assertIn("Вентиляция по потребности", html)
        app = (web / "js" / "app.js").read_text(encoding="utf-8")
        self.assertIn("createVod", app)
        js = (web / "js" / "panels" / "vod.js").read_text(encoding="utf-8")
        self.assertIn("vod_toggle", js)
        self.assertIn("Вентиляция по потребности: ", js)
        self.assertNotIn("http://", js)
        self.assertNotIn("https://", js)


# --- the Stand's switch -------------------------------------------------------------------------

#: The two entries stand/server.py needs for the switch (decision 11.4, spec 3.5). Until server.py
#: carries them, the launcher below adds them to the module before it starts the server.
VOD_KNOB = ("vod_enabled", (1.0, 0.0))
VOD_TOGGLE = ("vod_toggle", ("vod_enabled", 0.0, "Вентиляция по потребности выключена",
                             "Вентиляция по потребности включена"))
LAUNCHER = (
    "import importlib.util, sys\n"
    "spec = importlib.util.spec_from_file_location('stand_server', sys.argv[1])\n"
    "server = importlib.util.module_from_spec(spec)\n"
    "spec.loader.exec_module(server)\n"
    f"server.KNOB_VALUES.setdefault({VOD_KNOB[0]!r}, {VOD_KNOB[1]!r})\n"
    f"server.TOGGLES.setdefault({VOD_TOGGLE[0]!r}, {VOD_TOGGLE[1]!r})\n"
    "if 'vod_toggle' not in server.PRESET_IDS:\n"
    "    server.PRESET_IDS.insert(server.PRESET_IDS.index('undo'), 'vod_toggle')\n"
    "sys.argv = ['server.py'] + sys.argv[2:]\n"
    "server.main()\n")


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class TestStandSwitch(unittest.TestCase):
    """The switch «Вентиляция по потребности: вкл/выкл» and its undo, on the Stand in fixture mode."""

    @classmethod
    def setUpClass(cls):
        cls.port = _free_port()
        env = dict(os.environ, STAND_FIXTURE="1", PYTHONIOENCODING="utf-8")
        cls.process = subprocess.Popen(
            [sys.executable, "-c", LAUNCHER, str(TEAM / "stand" / "server.py"), "--host", "127.0.0.1",
             "--port", str(cls.port)], cwd=str(TEAM), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{cls.port}/healthz", timeout=2).read()
                return
            except OSError:
                time.sleep(0.2)
        cls.process.kill()
        raise RuntimeError("the Stand did not start")

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate()
        cls.process.wait(10)

    def post(self, body):
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/scenario", method="POST",
                                         data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))

    def mine(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/state", timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))["things"]["kz.sekis:mine"]["f"]

    def test_toggle_and_undo(self):
        self.post({"action": "reset"})
        self.assertNotEqual(self.mine()["vod_state"], "off")
        answer = self.post({"preset": "vod_toggle"})
        self.assertEqual(answer["knobs"]["vod_enabled"], 0.0)
        self.assertEqual(answer["changed"], {"vod_enabled": [1.0, 0.0]})
        self.assertEqual(answer["label"], "Вентиляция по потребности выключена")
        mine = self.mine()
        self.assertEqual((mine["vod_state"], mine["air_delivered_m3s"], mine["fan_saving_day_kwh"]), ("off", 322.0, 0.0))
        answer = self.post({"action": "undo"})                     # «Шаг назад»
        self.assertEqual(answer["knobs"]["vod_enabled"], 1.0)
        self.assertNotEqual(self.mine()["vod_state"], "off")
        self.post({"preset": "vod_toggle"})                        # a toggle is its own undo
        answer = self.post({"preset": "vod_toggle"})
        self.assertEqual(answer["knobs"]["vod_enabled"], 1.0)
        self.post({"action": "reset"})

    def test_scenario_logic_with_the_two_entries(self):
        # the same logic in process, with the entries patched into the module as the launcher does
        sys.path.insert(0, str(TEAM / "stand"))
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("stand_server_vod", TEAM / "stand" / "server.py")
            server = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(server)
        finally:
            sys.path.pop(0)
        with mock.patch.dict(server.KNOB_VALUES, [VOD_KNOB]), mock.patch.dict(server.TOGGLES, [VOD_TOGGLE]):
            backend = server.FixtureBackend()
            scenario = server.Scenario(backend)
            self.assertEqual(scenario.defaults["vod_enabled"], 1.0)
            answer = scenario.handle({"preset": "vod_toggle"})
            self.assertEqual(answer["knobs"]["vod_enabled"], 0.0)
            self.assertEqual(backend.state()["things"]["kz.sekis:mine"]["f"]["vod_state"], "off")
            answer = scenario.handle({"action": "undo"})
            self.assertEqual(answer["knobs"]["vod_enabled"], 1.0)
            self.assertEqual(answer["undo_depth"], 0)

    @unittest.skipUnless("vod_enabled" in (TEAM / "stand" / "server.py").read_text(encoding="utf-8"),
                         "stand/server.py does not carry the knob vod_enabled and the toggle vod_toggle yet; "
                         "the launcher of this test adds them (patch in the report of 17 October)")
    def test_server_carries_the_switch(self):
        text = (TEAM / "stand" / "server.py").read_text(encoding="utf-8")
        self.assertIn('"vod_toggle"', text)


if __name__ == "__main__":
    unittest.main()
