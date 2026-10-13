"""Tests for the simulator core, team/sekis/sim/.

Covers the simulator checks of spec 2.9 (C3, C8, C11 and the three consistency checks), the mass
balance from the stopes to the tailings, the traffic rules on the single-lane declines, the
snapshot against the registry, determinism, the scenario effects of spec 3.3 with their undo, the
publishing budget of spec 1.2 and the run time (60 simulated days in 60 real seconds or less).

The expected values written out here are those of the spec; the simulator reads every number from
params.json, registry.json and geometry.json.
"""

import bisect
import json
import math
import sys
import time
import unittest
from pathlib import Path

TEAM = Path(__file__).resolve().parent.parent
if str(TEAM) not in sys.path:
    sys.path.insert(0, str(TEAM))

from sekis import capacity as cap  # noqa: E402
from sekis import geometry  # noqa: E402
from sekis.sim import (MISSING_PARAMS, TUNED_PARAMS, PublishPlanner, STRING_FEATURES, Simulator,  # noqa: E402
                       ditto_modify, telemetry_topic)

REGISTRY = json.loads((TEAM / "model" / "registry.json").read_text(encoding="utf-8"))
MODEL = cap.load_model()
GEO = geometry.load()

# The run opens at 09:30 on the epoch day (sim.epoch), 45 minutes into the first productive block.
EPOCH = "2027-01-01T09:30:00"
EPOCH_H = 9.5
MOVING = {"surface_haul", "descending", "tram_level", "hauling_up"}

FULL_1200 = dict(m_haul=1, m_stopes=1, m_vent=1, m_plant=1, m_water=1, m_tailings=1)
FULL_2000 = dict(m_haul=2, m_stopes=2, m_vent=2, m_plant=2, m_water=2, m_tailings=1, m_dev=1)
FULL_2500 = dict(m_haul=3, m_stopes=3, m_vent=2, m_plant=3, m_water=2, m_tailings=1, m_dev=1)

# State tokens of spec 1.2, 2.4 and 2.5 by kind.
STATES = {
    "mine": {"production", "blast_window", "restricted_air", "evacuation"},
    "level": {"ventilation", "mined_out", "production", "development", "planned", "flooded"},
    "stope": {"planned", "preparation", "standby", "drilling", "charging", "awaiting_blast", "ventilating",
              "mucking", "backfilling", "flooded"},
    "decline": {"open", "closed"},
    "shaft": {"in_service", "planned"},
    "raise": {"in_service", "planned"},
    "main_fan": {"running", "failed", "planned"},
    "pump_station": {"idle", "pumping", "alarm_high", "failed", "planned"},
    "settling_pond": {"in_service"},
    "monitoring_point": {"normal", "warning", "exceeded"},
    "haul_truck": {"parked", "descending", "waiting_bay", "tram_level", "queue_load", "loading", "hauling_up",
                   "surface_haul", "dumping", "held_vent", "maintenance", "shift_break"},
    "lhd": {"parked", "idle", "mucking", "loading_truck", "standby_vent", "shift_break"},
    "drill_rig": {"parked", "drilling", "tramming", "shift_break"},
    "rom_stockpile": {"normal", "low", "empty"},
    "plant": {"running", "starved", "water_limited"},
    "plant_line": {"running", "starved", "maintenance", "water_limited", "off", "planned"},
    "tailings_facility": {"ok", "short_horizon", "full"},
    "tailings_dam": {"active", "standby", "full", "planned"},
    "water_system": {"balanced", "deficit", "discharge_over_permit"},
}

KIND = {t["thingId"].split(":", 1)[1]: t["attributes"]["kind"] for t in REGISTRY["things"]}
TRUCKS = [name for name, kind in KIND.items() if kind == "haul_truck"]
STOPES = [name for name, kind in KIND.items() if kind == "stope"]


def new_sim(seed=None, **knobs):
    sim = Simulator(MODEL, GEO, REGISTRY, seed=seed)
    if knobs:
        sim.apply_scenario(knobs)
    return sim


def copy_snapshot(sim):
    return {name: dict(features) for name, features in sim.snapshot().items()}


class Run:
    """A finished run with what the tests read from it."""

    def __init__(self, days, sample_h=None, **knobs):
        self.sim = new_sim(**knobs)
        self.samples = []
        self.hoisted_by_day = [0.0]
        started = time.perf_counter()
        if sample_h is None:
            for _ in range(int(days)):
                self.sim.run_days(1)
                self.hoisted_by_day.append(self.sim.ore_hoisted_t)
            self.elapsed = time.perf_counter() - started
        else:
            # timed without the sampling, then sampled on a second, identical run
            self.sim.run_days(days)
            self.elapsed = time.perf_counter() - started
            again = new_sim(**knobs)
            per_day = int(24 / sample_h)
            for step in range(int(days) * per_day):
                again.advance(sample_h * 60)
                self.samples.append(copy_snapshot(again))
                if (step + 1) % per_day == 0:
                    self.hoisted_by_day.append(again.ore_hoisted_t)
            self.identical = again.totals() == self.sim.totals()
        self.totals = self.sim.totals()
        self.year = self.sim.annualised()


_RUNS = {}


def baseline_run():
    """The calibration run of spec 2.9: baseline, seed 53, 60 simulated days."""
    if "baseline" not in _RUNS:
        _RUNS["baseline"] = Run(MODEL.p("calib.run_days"), sample_h=1.0)
    return _RUNS["baseline"]


def run_of(key, days, **knobs):
    if key not in _RUNS:
        _RUNS[key] = Run(days, **knobs)
    return _RUNS[key]


class SimCase(unittest.TestCase):
    def assertWithin(self, value, expected, pct, msg=None):
        self.assertAlmostEqual(value, expected, delta=abs(expected) * pct / 100,
                               msg=f"{msg or ''} simulator {value:.1f}, expected {expected:.1f} +-{pct} %")


# ---------------------------------------------------------------------------------------------
# calibration checks of spec 2.9
# ---------------------------------------------------------------------------------------------

class TestCalibration(SimCase):
    @classmethod
    def setUpClass(cls):
        cls.run_ = baseline_run()
        cls.totals = cls.run_.totals
        cls.year = cls.run_.year

    def test_c3_ore_hoisted_matches_fy2025(self):
        self.assertEqual(self.totals["sim_days"], 60.0)
        self.assertWithin(self.year["ore_hoisted_t"], 926422, 3, "C3 annualised ore hoisted:")

    def test_baseline_matches_analytic_haulage_capacity(self):
        analytic = cap.evaluate(MODEL).capacity_ktpa["haulage"] * 1000
        self.assertWithin(self.year["ore_hoisted_t"], analytic, MODEL.p("calib.c3.tol_pct"),
                          "haulage binds at baseline:")
        self.assertEqual(self.run_.sim.analytic.binding_link, "haulage")

    def test_c8_plant_feed_matches_nameplate(self):
        self.assertGreater(self.totals["min_stockpile_t"], MODEL.p("plant.min_stockpile_t"),
                           "the stockpile must stay available during the run")
        self.assertWithin(self.year["ore_milled_t"], 1000000, 3, "C8 annualised plant feed:")

    def test_c11_mass_balance_stockpile_and_tailings(self):
        t = self.totals
        self.assertWithin(t["stockpile_t"] - t["stockpile_start_t"] + t["ore_milled_t"], t["ore_hoisted_t"], 0.1,
                          "C11 hoisted = stockpile change + milled:")
        self.assertWithin(t["tailings_stored_t"] - t["tailings_stored_start_t"], t["ore_milled_t"], 0.1,
                          "C11 milled = tailings added:")
        self.assertWithin(t["tailings_placed_t"], t["ore_milled_t"], 0.1)

    def test_mass_balance_from_stopes_to_trucks(self):
        t = self.totals
        # blasted ore is either still broken in the stopes or was loaded
        self.assertAlmostEqual(t["ore_broken_start_t"] + t["ore_blasted_t"], t["ore_broken_t"] + t["ore_loaded_t"],
                               delta=1e-6 * t["ore_loaded_t"])
        # loaded ore is either still on a truck or was tipped on the pad
        self.assertAlmostEqual(t["ore_loaded_t"], t["ore_hoisted_t"] + t["ore_on_trucks_t"],
                               delta=1e-6 * t["ore_loaded_t"])
        # in the twins: ore left in the stopes fell by what was blasted
        last = self.run_.samples[-1]
        left = sum(last[name]["ore_remaining_t"] + last[name]["broken_ore_t"] for name in STOPES)
        start = sum(t_["attributes"]["ore_initial_t"] for t_ in REGISTRY["things"]
                    if t_["attributes"]["kind"] == "stope")
        self.assertAlmostEqual(start - left, t["ore_loaded_t"], delta=1.0)

    def test_calibration_rows_for_the_stand(self):
        rows = self.run_.sim.calibration_checks()
        self.assertEqual([row.id for row in rows], ["C3", "C8", "C11", "C11"])
        for row in rows:
            self.assertTrue(row.ok, f"{row.id} {row.quantity}: deviation {row.deviation:.2f} {row.deviation_unit}")
            self.assertIsInstance(row, cap.CalibrationCheck)

    def test_gold_follows_feed_grade_and_recovery(self):
        expected = cap.gold_oz(MODEL, self.year["ore_milled_t"], MODEL.p("plant.grade_base"))
        self.assertWithin(self.year["gold_oz"], expected, 1.0, "gold poured:")
        self.assertWithin(self.year["gold_oz"], 53852 * self.year["ore_milled_t"] / 966592, 2.0,
                          "gold at the FY2025 grade, scaled to the tonnes milled:")

    def test_air_demand_fits_the_supply_without_holds(self):
        t = self.totals
        self.assertAlmostEqual(t["air_supply_m3s"], 322.0, places=6)
        self.assertAlmostEqual(t["air_demand_peak_m3s"], 317.2, delta=0.05)
        self.assertTrue(all(s["mine"]["units_held_vent"] == 0.0 for s in self.run_.samples))
        self.assertFalse(any(s["mine"]["state"] == "restricted_air" for s in self.run_.samples))

    def test_water_volumes(self):
        y = self.year
        inflow = MODEL.p("water.inflow_m3h") * MODEL.hours_per_year
        self.assertWithin(y["water_inflow_m3"], inflow, 0.01, "mine inflow:")
        self.assertWithin(y["water_pumped_m3"], inflow, 1.0, "pumped to the ponds:")
        self.assertWithin(y["water_site_use_m3"], MODEL.p("water.site_m3_per_t") * self.totals["ore_hoisted_t"]
                          * 365 / 60, 0.01, "site use per tonne hoisted:")
        self.assertWithin(y["water_plant_supply_m3"], MODEL.p("water.plant_m3_per_t") * y["ore_milled_t"], 0.01,
                          "plant water per tonne milled:")
        # at 1000 kt/yr the demand equals the mine water (C10), so next to nothing is discharged
        self.assertLess(y["water_discharge_m3"], 0.05 * inflow)
        self.assertEqual(self.totals["water_deficit_m3"], 0.0)
        self.assertEqual(self.totals["flood_volume_m3"], 0.0)

    def test_no_negative_stock_sump_or_pond(self):
        t = self.totals
        for key in ("min_stockpile_t", "min_ponds_m3", "min_sump_m3"):
            self.assertGreaterEqual(t[key], 0.0, key)
        for sample in self.run_.samples:
            self.assertGreaterEqual(sample["rom-stockpile"]["tonnes"], 0.0)
            self.assertGreaterEqual(sample["mine"]["flood_volume_m3"], 0.0)
            for station in ("ps-p150", "ps-m050"):
                self.assertTrue(0.0 <= sample[station]["sump_level_pct"] <= 100.0)
            for pond in ("pond-upper", "pond-lower"):
                self.assertGreaterEqual(sample[pond]["retention_h"], 0.0)
            for name in STOPES:
                self.assertGreaterEqual(sample[name]["broken_ore_t"], 0.0)
                self.assertGreaterEqual(sample[name]["ore_remaining_t"], 0.0)
            for name in TRUCKS:
                self.assertGreaterEqual(sample[name]["payload"], 0.0)

    def test_every_number_of_every_sample_is_finite_and_not_negative_where_it_counts(self):
        signed = {"elevation", "pos_x", "pos_y", "pos_z", "bottom_elevation", "air_margin_pct"}
        for sample in self.run_.samples[::24]:
            for name, features in sample.items():
                for fid, value in features.items():
                    if fid in STRING_FEATURES:
                        continue
                    self.assertTrue(math.isfinite(value), f"{name}.{fid}")
                    if fid not in signed:
                        self.assertGreaterEqual(value, 0.0, f"{name}.{fid}")

    def test_performance_60_days_within_60_seconds(self):
        self.assertLessEqual(self.run_.elapsed, 60.0, f"60 simulated days took {self.run_.elapsed:.1f} s")
        self.assertTrue(self.run_.identical, "the sampled run must equal the timed run")

    def test_long_run_rates_stay_realistic(self):
        t = self.totals
        self.assertWithin(t["truck_cycle_mean_min"], 52.0, 5, "mean loaded truck cycle, minutes:")
        availability = 1 - t["truck_maintenance_h"] / (60 * 24 * 5)
        self.assertAlmostEqual(availability, MODEL.p("truck.availability"), delta=0.03)
        self.assertLess(t["bay_wait_min_per_trip"], MODEL.p("haul.K_BAY") * 3)
        self.assertEqual(t["truck_trips_aborted"], 0.0)


# ---------------------------------------------------------------------------------------------
# snapshot against the registry
# ---------------------------------------------------------------------------------------------

class TestSnapshot(SimCase):
    def check(self, sim, where):
        snap = sim.snapshot()
        expected = {t["thingId"].split(":", 1)[1]: t for t in REGISTRY["things"]}
        del expected["advisor"]                       # the advisor publishes itself
        self.assertEqual(set(snap), set(expected), where)
        self.assertEqual(len(snap), 95)
        for name, thing in expected.items():
            features = snap[name]
            self.assertEqual(list(features), list(thing["features"]), f"{where}: feature ids of {name}")
            kind = thing["attributes"]["kind"]
            for fid, value in features.items():
                if fid in STRING_FEATURES:
                    self.assertIs(type(value), str, f"{where}: {name}.{fid}")
                else:
                    self.assertIs(type(value), float, f"{where}: {name}.{fid} = {value!r}")
                    self.assertTrue(math.isfinite(value), f"{where}: {name}.{fid}")
            if kind in STATES:
                self.assertIn(features["state"], STATES[kind], f"{where}: {name}.state")
            if kind == "haul_truck":
                self.assertIn(features["decline"], {"tu1", "tu2", "none"})
            if kind in ("lhd", "drill_rig"):
                self.assertIn(features["stope"], set(STOPES) | {"none"})
        self.assertIn(snap["enterprise"]["shift"], {"A", "B", "blast"})
        self.assertIn(snap["enterprise"]["binding_link"], cap.LINKS)
        self.assertEqual(sim.validate_snapshot(), [], where)
        json.dumps(snap)                              # plain JSON types only

    def test_baseline_at_the_epoch_and_later(self):
        sim = new_sim()
        self.check(sim, "epoch")
        for hours in (0.5, 3, 11.4, 12.2, 30, 100):
            sim.advance(hours * 60)
            self.check(sim, f"after {hours} more hours")

    def test_with_every_measure_and_disturbance(self):
        sim = new_sim(**FULL_2500)
        sim.run_days(2.3)
        self.check(sim, "full set for 2.5 Mtpa")
        sim.apply_scenario({"tu2_closed": 1, "fan_vs2_off": 1, "pumps_failed_p150": 3, "inflow_factor": 2.18,
                            "grade_gpt": 1.76, "line_down": 2})
        for _ in range(8):
            sim.advance(6 * 60)
            self.check(sim, "all disturbances")

    def test_epoch_values_agree_with_the_registry_baseline(self):
        snap = new_sim().snapshot()
        for thing in REGISTRY["things"]:
            name = thing["thingId"].split(":", 1)[1]
            kind = thing["attributes"]["kind"]
            if name == "advisor":
                continue
            baseline = {fid: body["properties"]["value"] for fid, body in thing["features"].items()}
            if kind in ("scenario_control", "main_fan", "tailings_dam", "decline"):
                for fid in baseline:
                    if kind == "decline" and fid != "bottom_elevation" and fid != "state":
                        continue
                    self.assertEqual(snap[name][fid], baseline[fid], f"{name}.{fid}")
            if kind in ("haul_truck", "lhd", "drill_rig"):
                self.assertEqual(snap[name]["state"] == "parked", baseline["state"] == "parked", name)
            if kind in ("shaft", "raise", "level", "pump_station", "plant_line", "settling_pond"):
                if not (kind == "pump_station" and baseline["state"] == "idle"):
                    self.assertEqual(snap[name]["state"], baseline["state"], name)
            if kind == "stope" and baseline["state"] in ("planned", "preparation", "standby"):
                self.assertEqual(snap[name]["state"], baseline["state"], name)
        self.assertEqual(snap["enterprise"]["sim_time"], EPOCH)
        self.assertEqual(MODEL.p("sim.epoch"), EPOCH)
        self.assertEqual(snap["enterprise"]["binding_link"], "haulage")
        self.assertEqual(snap["mine"]["air_supply_m3s"], 322.0)
        self.assertEqual(snap["mine"]["air_demand_m3s"], 317.2)
        self.assertEqual(snap["mine"]["trucks_active"], 5.0)
        self.assertEqual(snap["mine"]["inflow_m3h"], 197.0)
        self.assertEqual(snap["rom-stockpile"]["tonnes"], 36000.0)
        self.assertEqual(snap["rom-stockpile"]["grade"], 2.05)
        self.assertEqual(snap["plant"]["capacity_ktpa"], 1000.0)
        self.assertEqual(snap["tailings"]["stored_t"], 2863755.0)
        self.assertEqual(snap["tailings"]["free_capacity_t"], 3172095.0)
        self.assertEqual(snap["tsf-dam4"]["fill_pct"], 90.0)
        self.assertEqual(sum(1 for n in STOPES if snap[n]["state"] not in ("planned", "preparation", "standby")), 4)

    def test_positions_stay_inside_the_scene(self):
        low, high = GEO.doc["bounds"]["min"], GEO.doc["bounds"]["max"]
        sim = new_sim(**FULL_2000)
        for _ in range(200):
            sim.advance(17)
            snap = sim.snapshot()
            for name, kind in KIND.items():
                if kind in ("haul_truck", "lhd", "drill_rig"):
                    f = snap[name]
                    for axis, key in enumerate(("pos_x", "pos_y", "pos_z")):
                        self.assertTrue(low[axis] - 1 <= f[key] <= high[axis] + 1, f"{name}.{key} = {f[key]}")

    def test_level_air_and_airways_add_up(self):
        sim = new_sim()
        sim.advance(4 * 60)
        snap = sim.snapshot()
        levels = [n for n, k in KIND.items() if k == "level"]
        self.assertAlmostEqual(sum(snap[n]["air_flow_m3s"] for n in levels), 322.0, delta=0.5)
        self.assertEqual(snap["lvl-m100"]["air_flow_m3s"], 0.0)
        self.assertEqual(snap["raise-vhv-exhaust"]["air_flow_m3s"], 322.0)
        self.assertEqual(snap["shaft-vs1"]["air_flow_m3s"], 150.0)
        self.assertEqual(snap["shaft-vs2"]["air_flow_m3s"], 70.0)
        self.assertAlmostEqual(snap["shaft-vs1"]["air_velocity_ms"], 150 / 10.86, places=2)
        self.assertEqual(snap["raise-vhv-tu1"]["air_flow_m3s"] + snap["raise-vhv-tu2"]["air_flow_m3s"], 102.0)
        self.assertEqual(snap["fan-vs1"]["power_kw"], 500.0)
        self.assertAlmostEqual(sum(snap[n]["water_inflow_m3h"] for n in levels), 197.0, delta=0.5)


# ---------------------------------------------------------------------------------------------
# time base and determinism
# ---------------------------------------------------------------------------------------------

class TestTimeBase(SimCase):
    def test_compression_and_step(self):
        sim = new_sim()
        self.assertEqual(sim.step_s, 10)
        sim.step(1.0)                                 # one real second is one simulated minute
        self.assertEqual(sim.t, 60)
        sim.step(0.5)                                 # the service loop: 3 steps
        self.assertEqual(sim.tick, 9)
        sim.advance(0.1)                              # 6 s: less than a step, carried over
        self.assertEqual(sim.tick, 9)
        sim.advance(0.1)
        self.assertEqual(sim.tick, 10)

    def test_day_of_two_shifts_and_two_blast_windows(self):
        sim = new_sim()
        seen = {}
        productive = {"A": 0, "B": 0}
        for minute in range(24 * 60):
            snap = sim.snapshot(["enterprise", "mine"])
            hour = round((EPOCH_H + minute / 60) % 24, 6)
            seen.setdefault(snap["enterprise"]["shift"], []).append(hour)
            if snap["enterprise"]["shift"] == "blast":
                self.assertEqual(snap["mine"]["state"], "blast_window")
            if sim.productive:
                productive[snap["enterprise"]["shift"]] += 1
            sim.advance(1)
        self.assertEqual((min(seen["A"]), max(seen["A"])), (8.0, round(19 - 1 / 60, 6)))
        self.assertEqual(len(seen["A"]), 11 * 60)
        self.assertEqual(len(seen["B"]), 11 * 60)
        self.assertEqual(len(seen["blast"]), 2 * 60)
        self.assertTrue(all(19 <= h < 20 or 7 <= h < 8 for h in seen["blast"]))
        self.assertEqual(productive, {"A": 510, "B": 510})    # 8.5 h in each shift
        self.assertEqual(sim.sim_time, "2027-01-02T09:30:00")
        self.assertEqual(sim.snapshot()["enterprise"]["sim_day"], 1.0)

    def test_daily_totals_reset_at_0800(self):
        sim = new_sim()
        sim.advance((24 + 7 - EPOCH_H) * 60)          # 07:00 on day 2: both shifts of the first day are over
        self.assertGreater(sim.snapshot()["mine"]["ore_hoisted_today_t"], 1000.0)
        self.assertGreater(sim.snapshot()["truck-01"]["trips_today"], 0.0)
        total = sim.ore_hoisted_t
        sim.advance(61)
        snap = sim.snapshot()
        self.assertEqual(snap["mine"]["ore_hoisted_today_t"], 0.0)
        self.assertEqual(snap["truck-01"]["trips_today"], 0.0)
        self.assertEqual(snap["mine"]["ore_hoisted_total_t"], total)

    def test_trucks_rest_outside_the_productive_time(self):
        sim = new_sim()
        sim.advance((19.5 - EPOCH_H) * 60)            # 19:30, inside the blast window
        snap = sim.snapshot()
        for name in TRUCKS[:5]:
            self.assertIn(snap[name]["state"], ("shift_break", "maintenance"), name)
        self.assertEqual(snap["mine"]["diesel_kw_active"], 0.0)

    def test_other_epoch(self):
        sim = Simulator(MODEL, GEO, REGISTRY, epoch="2027-03-10T14:00:00")
        self.assertEqual(sim.snapshot()["enterprise"]["shift"], "A")
        sim.advance(5 * 60 + 30)
        self.assertEqual(sim.sim_time, "2027-03-10T19:30:00")
        self.assertEqual(sim.snapshot()["enterprise"]["shift"], "blast")


class TestOpening(SimCase):
    """The run opens mid-shift on a working mine (sim.epoch, 09:30), not on the walk-in at 08:00."""

    def test_trucks_are_spread_along_their_cycles_at_the_epoch(self):
        sim = new_sim()
        self.assertEqual((sim.sim_time, sim.t, sim.shift, sim.productive), (EPOCH, 0, "A", True))
        snap = sim.snapshot()
        fleet = TRUCKS[:5]
        states = [snap[name]["state"] for name in fleet]
        self.assertFalse({"shift_break", "parked", "held_vent", "maintenance"} & set(states), states)
        self.assertGreaterEqual(len(set(states)), 3, states)
        places = {(snap[n]["pos_x"], snap[n]["pos_y"], snap[n]["pos_z"]) for n in fleet}
        self.assertEqual(len(places), 5, "no two trucks stand at the same place")
        self.assertGreaterEqual(sum(1 for n in fleet if snap[n]["chainage_m"] > 0.0), 2, "trucks on the declines")
        self.assertGreaterEqual(sum(1 for n in fleet if snap[n]["payload"] > 0.0), 1, "a truck is already loaded")
        self.assertGreaterEqual(sum(1 for n in fleet if snap[n]["payload"] == 0.0), 1)
        self.assertEqual(snap["mine"]["state"], "production")
        self.assertEqual(snap["mine"]["trucks_active"], 5.0)
        self.assertGreater(snap["mine"]["diesel_kw_active"], 1000.0)
        # LHDs and rigs are at work too
        self.assertTrue(all(snap[f"lhd-0{n}"]["state"] in ("mucking", "loading_truck") for n in (1, 2, 3, 4)))
        self.assertEqual((snap["rig-01"]["state"], snap["rig-02"]["state"]), ("drilling", "drilling"))

    def test_at_least_three_trucks_move_in_the_first_minute_and_ore_is_hoisted_in_the_first_half_hour(self):
        sim = new_sim()
        fleet = TRUCKS[:5]
        for _ in range(7):                            # 0, 10, ... 60 simulated seconds
            snap = sim.snapshot(fleet)
            states = [snap[name]["state"] for name in fleet]
            moving = [name for name in fleet if snap[name]["state"] in MOVING]
            self.assertGreaterEqual(len(moving), 3, f"{sim.t} s: {states}")
            self.assertTrue(all(snap[name]["speed"] > 0.0 for name in moving))
            sim.advance(1 / 6)
        self.assertEqual(sim.ore_hoisted_t, 0.0)
        sim.advance(29)                               # 30 simulated minutes after the epoch
        self.assertLessEqual(sim.t, 30 * 60 + 10)
        self.assertGreater(sim.ore_hoisted_t, 0.0)
        self.assertGreater(sim.snapshot()["mine"]["ore_hoisted_total_t"], 0.0)
        self.assertGreater(sim.snapshot()["mine"]["ore_hoisted_tph"], 0.0)

    def test_totals_start_at_zero_and_the_mass_balance_holds_at_the_epoch(self):
        sim = new_sim()
        t = sim.totals()
        self.assertEqual((t["ore_hoisted_t"], t["truck_trips"], t["ore_milled_t"], t["ore_blasted_t"]),
                         (0.0, 0.0, 0.0, 0.0))
        self.assertEqual(t["stockpile_t"], MODEL.p("stockpile.start_t"))
        # ore already on the trucks was loaded from the broken ore of the warm start
        self.assertGreater(t["ore_on_trucks_t"], 0.0)
        self.assertEqual(t["ore_loaded_t"], t["ore_on_trucks_t"])
        self.assertAlmostEqual(t["ore_broken_start_t"], t["ore_broken_t"] + t["ore_loaded_t"])
        self.assertEqual(sim.snapshot()["enterprise"]["sim_day"], 0.0)

    def test_stopes_keep_their_warm_start(self):
        sim = new_sim()
        t = sim.totals()
        # one ring of broken ore in each of the four producing stopes
        self.assertAlmostEqual(t["ore_broken_start_t"], 4 * MODEL.p("stope.blast_t"))
        self.assertEqual([st.last_blast_w for st in sim.mining.producing], [0, -1, -2, -3])   # a shift apart
        snap = sim.snapshot()
        drilled = [snap[st.name]["drilled_pct"] for st in sim.mining.producing]
        # the ring of the first stope is 45 minutes into its 12.75 h of drilling, the second a shift further
        self.assertAlmostEqual(drilled[0], 0.75 / 12.75 * 100, delta=0.1)
        self.assertAlmostEqual(drilled[1], (8.5 + 0.75) / 12.75 * 100, delta=0.1)
        self.assertEqual(drilled[2:], [100.0, 100.0])
        fired = []
        sim.advance((19.5 - EPOCH_H) * 60 + 1)        # 19:31, just after the rings of the first window are fired
        for _ in range(4):                            # one ring per blast window, four shifts after the stope's last
            fired.append(sim.last_blast)
            sim.advance(12 * 60)
        self.assertEqual(fired, [("stp-000-1",), ("stp-p050-1",), ("stp-p100-1",), ("stp-p150-1",)])

    def test_state_at_the_epoch_does_not_depend_on_the_seed(self):
        first, second = new_sim(seed=1), new_sim(seed=2)
        self.assertEqual(first.snapshot(), second.snapshot())
        self.assertEqual(first.totals(), second.totals())
        first.run_days(2)
        second.run_days(2)
        self.assertNotEqual(first.totals()["ore_hoisted_t"], second.totals()["ore_hoisted_t"])

    def test_epoch_outside_productive_time_starts_from_the_pad(self):
        sim = Simulator(MODEL, GEO, REGISTRY, epoch="2027-01-01T08:00:00")     # the walk-in at the shift start
        snap = sim.snapshot()
        self.assertFalse(sim.productive)
        self.assertEqual({snap[name]["state"] for name in TRUCKS[:5]}, {"shift_break"})
        self.assertEqual(sim.totals()["ore_loaded_t"], 0.0)
        sim.advance(60)                               # 09:00: production began at 08:45
        self.assertTrue(any(sim.snapshot()[name]["state"] in MOVING for name in TRUCKS[:5]))


class TestDeterminism(SimCase):
    def test_same_seed_gives_the_same_snapshot_after_10_days(self):
        first, second = new_sim(seed=53), new_sim(seed=53)
        first.run_days(10)
        for _ in range(10 * 24 * 120):                # the service loop: 0.5 real seconds at a time
            second.step(0.5)
        self.assertEqual(first.tick, second.tick)
        self.assertEqual(first.snapshot(), second.snapshot())
        self.assertEqual(first.totals(), second.totals())

    def test_default_seed_is_53(self):
        default, explicit = new_sim(), new_sim(seed=53)
        self.assertEqual(default.seed, 53)
        default.run_days(3)
        explicit.run_days(3)
        self.assertEqual(default.snapshot(), explicit.snapshot())

    def test_another_seed_gives_another_run(self):
        first, second = new_sim(seed=53), new_sim(seed=54)
        first.run_days(10)
        second.run_days(10)
        self.assertNotEqual(first.totals()["ore_hoisted_t"], second.totals()["ore_hoisted_t"])

    def test_scenario_does_not_change_the_breakdowns_of_a_truck(self):
        # every truck has its own random streams: a scenario is compared with the baseline on
        # the same breakdown history
        base, other = new_sim(), new_sim(line_down=2)
        base.run_days(8)
        other.run_days(8)
        self.assertEqual(base.totals()["truck_maintenance_h"], other.totals()["truck_maintenance_h"])
        self.assertEqual(base.totals()["ore_hoisted_t"], other.totals()["ore_hoisted_t"])


# ---------------------------------------------------------------------------------------------
# trucks and decline traffic
# ---------------------------------------------------------------------------------------------

class TestTraffic(SimCase):
    def nodes(self, key):
        return [node["chainage"] for node in GEO.passing_bays(key)]

    def test_no_opposing_trucks_share_a_segment(self):
        """12 trucks, every 10 s step of two days, checked on the published twin values."""
        sim = new_sim(m_haul=3, m_vent=2)
        nodes = {key: self.nodes(key) for key in ("tu1", "tu2")}
        met_on_ramp = 0
        for _ in range(2 * 8640):
            sim.advance(1 / 6)
            snap = sim.snapshot(TRUCKS)
            inside = {}
            for name in TRUCKS:
                f = snap[name]
                state = f["state"]
                if state == "waiting_bay":
                    # waits only at a node (a bay or the portal), never loaded
                    self.assertEqual(f["payload"], 0.0, name)
                    self.assertEqual(f["speed"], 0.0, name)
                    chain = nodes[f["decline"]]
                    self.assertTrue(any(abs(f["chainage_m"] - c) < 0.11 for c in chain), name)
                if state not in ("descending", "hauling_up") or f["speed"] == 0.0:
                    continue
                chain = nodes[f["decline"]]
                segment = bisect.bisect_right(chain, f["chainage_m"]) - 1
                at_node = min(abs(f["chainage_m"] - c) for c in chain) < 0.3
                if not at_node:
                    inside.setdefault((f["decline"], segment), set()).add(state)
            for where, states in inside.items():
                self.assertEqual(len(states), 1, f"opposing trucks inside segment {where} at {sim.sim_time}")
            if len({decline for decline, _ in inside}) and len(inside) > 3:
                met_on_ramp += 1
        self.assertGreater(met_on_ramp, 1000, "the test must have seen busy declines")
        self.assertEqual(sim.totals()["traffic_conflicts"], 0.0)
        self.assertGreater(sim.totals()["bay_wait_min_per_trip"], 0.0, "trucks did wait in bays")

    def test_no_truck_waits_two_hours_in_a_bay_over_30_days_with_12_trucks(self):
        run = run_of("twelve", 30, m_haul=3, m_vent=2)
        self.assertLess(run.totals["max_bay_wait_min"], 120.0)
        self.assertEqual(run.totals["traffic_conflicts"], 0.0)
        self.assertGreater(run.totals["truck_trips"], 2000)
        # hauling went on to the last day: no deadlock
        last_day = run.hoisted_by_day[-1] - run.hoisted_by_day[-2]
        self.assertGreater(last_day, 2000.0)
        self.assertGreater(run.totals["bay_wait_min_per_trip"], 0.5)

    def test_truck_cycle_visits_the_states_in_order(self):
        sim = new_sim()                               # 09:30: every truck is on a trip
        fleet = TRUCKS[:5]
        order = {name: [sim.snapshot(fleet)[name]["state"]] for name in fleet}
        for _ in range(6 * 170):                      # to 12:20, inside the first productive block
            sim.advance(1 / 6)
            snap = sim.snapshot(fleet)
            for name in fleet:
                state = snap[name]["state"]
                if not order[name] or order[name][-1] != state:
                    order[name].append(state)
        cycle = " ".join(["surface_haul", "descending", "tram_level", "queue_load", "loading", "tram_level",
                          "hauling_up", "surface_haul", "dumping", "surface_haul"])
        complete = []
        for name in fleet:
            moving = [state for state in order[name] if state != "waiting_bay"]     # waits in bays aside
            moving = [state for i, state in enumerate(moving) if i == 0 or moving[i - 1] != state]
            if cycle in " ".join(moving):
                complete.append(name)
        self.assertGreaterEqual(len(complete), 3, f"states seen: {order}")
        working = set(cycle.split()) | {"waiting_bay"}
        for name in fleet:
            self.assertIn(order[name][0], working, name)
            self.assertNotIn("shift_break", order[name], name)

    def test_truck_payload_grade_and_position_follow_the_cycle(self):
        sim = new_sim()
        sim.advance(60)
        fleet = TRUCKS[:5]
        seen = set()
        for _ in range(6 * 240):
            sim.advance(1 / 6)
            snap = sim.snapshot(fleet)
            for name in fleet:
                f = snap[name]
                key = f["decline"]
                payload = 45.0 if name == "truck-05" else 30.0
                seen.add(f["state"])
                if f["state"] == "hauling_up":
                    self.assertEqual(f["payload"], payload, name)
                    self.assertGreater(f["grade"], 1.0)
                    self.assertEqual(key, "tu1" if name == "truck-05" else "tu2")
                    self.assertLessEqual(f["elevation"], 430.0 if key == "tu1" else 320.0)
                    self.assertGreaterEqual(f["chainage_m"], 0.0)
                    self.assertIn(f["speed"], (0.0, 9.0))
                if f["state"] == "descending":
                    self.assertEqual(f["payload"], 0.0)
                    self.assertEqual(f["grade"], 0.0)
                    self.assertEqual(f["speed"], 16.0)
                    point = GEO.decline_point(key, distance=f["chainage_m"])
                    self.assertAlmostEqual(point[1], f["elevation"], delta=0.2)
                    self.assertAlmostEqual(point[0], f["pos_x"], delta=0.2)
                    self.assertAlmostEqual(point[2], f["pos_z"], delta=0.2)
                if f["state"] == "loading":
                    self.assertIn(f["elevation"], (150.0, 100.0, 50.0, 0.0))
                    self.assertEqual(f["speed"], 0.0)
                if f["state"] == "surface_haul":
                    self.assertIn(f["speed"], (15.0, 20.0))
                    self.assertEqual(f["chainage_m"], 0.0)
                if f["state"] == "dumping":
                    self.assertEqual(f["payload"], payload)
                    rom = GEO.obj("rom-stockpile")["dump"]
                    self.assertAlmostEqual(f["pos_x"], rom[0], delta=0.1)
                    self.assertAlmostEqual(f["pos_z"], rom[2], delta=0.1)
        self.assertTrue({"surface_haul", "descending", "tram_level", "queue_load", "loading", "hauling_up",
                         "dumping"} <= seen, seen)

    def test_haul_distance_uses_chainage_times_length_factor(self):
        sim = new_sim()
        ramp = sim.haul.ramps["tu2"]
        down = sum(ramp.t_down[:ramp.node_of[100.0]]) / 60
        up = sum(ramp.t_up[:ramp.node_of[100.0]]) / 60
        analytic = cap.haul_cycle(MODEL, MODEL.trucks[0], "tu2", 100.0, 1)
        self.assertAlmostEqual(down, analytic.ramp_down_min, delta=0.01)
        self.assertAlmostEqual(up, analytic.ramp_up_min, delta=0.01)
        self.assertAlmostEqual(ramp.surface_loaded_s / 60, analytic.surface_loaded_min, places=6)
        # one undisturbed trip takes the analytic cycle time without its delay terms
        nominal = (analytic.cycle_min - analytic.bay_min) * 60
        legs = (ramp.surface_empty_s + ramp.surface_loaded_s + (down + up) * 60 + 2 * sim.haul.level_s
                + sim.haul.load_s + sim.haul.dump_s)
        self.assertAlmostEqual(legs, nominal, delta=1.0)

    def test_breakdown_sends_the_truck_to_maintenance_at_the_surface(self):
        sim = new_sim()
        seen = False
        for _ in range(20 * 24 * 6):
            sim.advance(10)
            snap = sim.snapshot(TRUCKS[:5])
            for name in TRUCKS[:5]:
                if snap[name]["state"] == "maintenance":
                    seen = True
                    self.assertEqual(snap[name]["payload"], 0.0)
                    self.assertEqual(snap[name]["speed"], 0.0)
                    self.assertEqual(snap[name]["chainage_m"], 0.0)
        self.assertTrue(seen)


# ---------------------------------------------------------------------------------------------
# stopes, rigs, LHDs
# ---------------------------------------------------------------------------------------------

class TestStopes(SimCase):
    def test_stope_goes_through_its_cycle_and_blasts_in_the_windows(self):
        sim = new_sim()
        blast_t = MODEL.p("stope.blast_t")
        states = {name: [] for name in STOPES}
        broken = {name: sim.snapshot()[name]["broken_ore_t"] for name in STOPES}
        blasts = {name: [] for name in STOPES}
        for minute in range(8 * 24 * 60):
            sim.advance(1)
            snap = sim.snapshot(STOPES + ["enterprise"])
            for name in STOPES:
                f = snap[name]
                if not states[name] or states[name][-1] != f["state"]:
                    states[name].append(f["state"])
                if f["broken_ore_t"] > broken[name] + 1.0:
                    self.assertAlmostEqual(f["broken_ore_t"] - broken[name], blast_t, delta=0.11)
                    self.assertEqual(snap["enterprise"]["shift"], "blast", "rings are fired in a blast window")
                    self.assertEqual(f["state"], "ventilating")
                    blasts[name].append(minute)
                broken[name] = f["broken_ore_t"]
        producing = ["stp-p150-1", "stp-p100-1", "stp-p050-1", "stp-000-1"]
        for name in producing:
            seen = set(states[name])
            self.assertTrue({"drilling", "charging", "ventilating", "mucking"} <= seen, f"{name}: {seen}")
            self.assertGreaterEqual(len(blasts[name]), 3, name)
            gaps = [b - a for a, b in zip(blasts[name], blasts[name][1:])]
            # never more often than every 4 shifts (2 days): the analytic stoping capacity
            self.assertGreaterEqual(min(gaps), MODEL.p("stope.cycle_shifts") * 12 * 60 - 1, name)
            # re-entry: 30 minutes of ventilating after each blast
            i = states[name].index("ventilating")
            self.assertIn(states[name][i + 1], ("drilling", "mucking", "charging"))
        for name in STOPES:
            if name not in producing:
                self.assertEqual(len(states[name]), 1, f"{name} must not move: {states[name]}")
                self.assertEqual(blasts[name], [])

    def test_one_lhd_per_producing_stope_and_one_stope_per_rig(self):
        sim = new_sim(**FULL_2000)
        for _ in range(60):
            sim.advance(47)
            snap = sim.snapshot()
            lhd_stopes = [snap[n]["stope"] for n, k in KIND.items() if k == "lhd" and snap[n]["stope"] != "none"]
            self.assertEqual(len(lhd_stopes), len(set(lhd_stopes)))
            self.assertEqual(len(lhd_stopes), 8)
            rig_stopes = [snap[n]["stope"] for n, k in KIND.items() if k == "drill_rig"
                          and snap[n]["state"] == "drilling"]
            self.assertEqual(len(rig_stopes), len(set(rig_stopes)))
            for name in rig_stopes:
                self.assertEqual(snap[name]["state"], "drilling")
            self.assertEqual(sum(snap[n]["active_stopes"] for n, k in KIND.items() if k == "level"), 8.0)

    def test_lhd_follows_its_stope(self):
        sim = new_sim()
        seen = set()
        for _ in range(6 * 600):
            sim.advance(1 / 6)
            snap = sim.snapshot(["lhd-01", "stp-p150-1"] + TRUCKS[:5])
            lhd = snap["lhd-01"]
            seen.add(lhd["state"])
            self.assertEqual(lhd["stope"], "stp-p150-1")
            loading_here = any(snap[t]["state"] == "loading" and abs(snap[t]["elevation"] - 150.0) < 0.01
                               for t in TRUCKS[:5])
            self.assertEqual(lhd["state"] == "loading_truck", loading_here)
        self.assertTrue({"loading_truck", "mucking", "shift_break"} <= seen, seen)

    def test_stope_grades_average_to_the_feed_grade(self):
        for knobs in ({}, {"m_stopes": 1}, {"m_stopes": 3}, {"grade_gpt": 1.76}, {"m_stopes": 2, "grade_gpt": 1.76}):
            sim = new_sim(**knobs)
            producing = [st.name for st in sim.mining.producing]
            snap = sim.snapshot()
            mean = sum(snap[n]["grade"] for n in producing) / len(producing)
            self.assertAlmostEqual(mean, knobs.get("grade_gpt", 2.05), delta=0.002, msg=str(knobs))

    def test_mined_out_block_is_backfilled_and_reopens(self):
        sim = new_sim()
        stope = sim.mining.by_name["stp-p150-1"]
        stope.ore_remaining = 1000.0                  # the last ring of the block
        seen = []
        for _ in range(40 * 24):
            sim.advance(60)
            state = sim.snapshot(["stp-p150-1"])["stp-p150-1"]["state"]
            if not seen or seen[-1] != state:
                seen.append(state)
        self.assertIn("backfilling", seen)
        self.assertEqual(seen[-3:], ["backfilling", "preparation", "standby"])
        snap = sim.snapshot()
        self.assertEqual(snap["stp-p150-1"]["block_no"], 2.0)
        self.assertEqual(snap["stp-p150-1"]["ore_remaining_t"], 90000.0)
        # the next stope in the activation order took its place, with the LHD
        self.assertNotIn(snap["stp-p150-2"]["state"], ("standby", "planned", "preparation"))
        self.assertEqual(snap["lhd-01"]["stope"], "stp-p150-2")
        self.assertEqual(len(sim.mining.producing), 4)


# ---------------------------------------------------------------------------------------------
# scenarios of spec 3.3 and their undo
# ---------------------------------------------------------------------------------------------

class TestScenarioKnobs(SimCase):
    def test_knobs_in_ditto_shape_and_plain(self):
        sim = new_sim()
        scenario = next(t for t in REGISTRY["things"] if t["thingId"].endswith(":scenario"))
        features = json.loads(json.dumps(scenario["features"]))
        features["m_haul"]["properties"]["value"] = 1.0
        features["revision"]["properties"]["value"] = 7.0
        features["label"]["properties"]["value"] = "test"
        self.assertEqual(sorted(sim.apply_scenario(features)), ["label", "m_haul", "revision"])
        snap = sim.snapshot()["scenario"]
        self.assertEqual((snap["m_haul"], snap["revision"], snap["label"]), (1.0, 7.0, "test"))
        self.assertEqual(sim.apply_scenario({"m_haul": 1, "unknown": 5}), [])
        self.assertEqual(sim.apply_scenario({"m_haul": 2.0}), ["m_haul"])
        self.assertEqual(sim.cap_state.m_haul, 2)
        self.assertEqual(sorted(sim.knobs), sorted(sim.default_knobs()))

    def test_fifteen_knobs_of_the_spec(self):
        knobs = set(new_sim().default_knobs()) - {"revision", "label"}
        self.assertEqual(knobs, {"target_ktpa", "m_plant", "m_haul", "m_stopes", "m_vent", "m_dev", "m_water",
                                 "m_tailings", "tu1_closed", "tu2_closed", "fan_vs2_off", "pumps_failed_p150",
                                 "inflow_factor", "grade_gpt", "line_down"})

    def test_invalid_sets_are_rejected_and_change_nothing(self):
        sim = new_sim()
        sim.advance(90)
        before = dict(sim.knobs)
        for bad in ({"tu1_closed": 1, "tu2_closed": 1}, {"m_haul": 4}, {"m_plant": -1}, {"line_down": 5},
                    {"pumps_failed_p150": 4}, {"grade_gpt": 0}, {"inflow_factor": float("nan")}):
            with self.assertRaises(ValueError, msg=str(bad)):
                sim.apply_scenario(bad)
            self.assertEqual(sim.knobs, before)
        sim.apply_scenario({"tu2_closed": 1})
        with self.assertRaises(ValueError):
            sim.apply_scenario({"tu1_closed": 1})
        self.assertEqual(sim.snapshot()["decline-tu1"]["state"], "open")

    def test_reset_restores_the_baseline_fleet(self):
        sim = new_sim()
        sim.advance(100)
        sim.apply_scenario(dict(FULL_2500, tu2_closed=1, fan_vs2_off=1, line_down=1, revision=3))
        sim.advance(300)
        sim.reset_scenario()
        sim.advance(180)
        snap = sim.snapshot()
        self.assertEqual({k: v for k, v in sim.knobs.items() if k not in ("revision", "label")},
                         {k: v for k, v in sim.default_knobs().items() if k not in ("revision", "label")})
        self.assertEqual(snap["scenario"]["revision"], 3.0)
        fresh = new_sim().snapshot()
        for name, kind in KIND.items():
            if kind in ("haul_truck", "lhd", "drill_rig"):
                self.assertEqual(snap[name]["state"] == "parked", fresh[name]["state"] == "parked", name)
            if kind in ("main_fan", "shaft", "raise", "decline", "tailings_dam"):
                self.assertEqual(snap[name]["state"], fresh[name]["state"], name)
            if kind == "plant_line":
                self.assertEqual(snap[name]["state"] == "planned", fresh[name]["state"] == "planned", name)
        self.assertEqual(snap["mine"]["air_supply_m3s"], 322.0)
        self.assertEqual(snap["mine"]["units_held_vent"], 0.0)
        self.assertEqual(snap["plant"]["capacity_ktpa"], 1000.0)
        self.assertEqual(len(sim.mining.producing), 4)


class TestDisturbances(SimCase):
    def test_close_tu2_moves_all_trucks_to_tu1_and_cuts_hoisting_about_ten_percent(self):
        base = baseline_run()
        closed = run_of("tu2_closed", 30, tu2_closed=1)
        ratio = closed.totals["ore_hoisted_t"] / base.hoisted_by_day[30]
        self.assertTrue(0.86 <= ratio <= 0.94, f"hoisting with TU2 closed is {ratio:.3f} of the baseline")
        analytic = cap.evaluate(MODEL, cap.State(tu2_closed=True))
        self.assertWithin(closed.year["ore_hoisted_t"], analytic.capacity_ktpa["haulage"] * 1000, 5)
        snap = closed.sim.snapshot()
        self.assertEqual(snap["decline-tu2"]["state"], "closed")
        self.assertEqual(snap["decline-tu2"]["ore_today_t"], 0.0)
        self.assertEqual(snap["enterprise"]["annual_rate_ktpa"], 833.6)

        sim = new_sim()
        sim.advance(30)                               # 10:00, trucks on both declines
        self.assertEqual([sim.snapshot()[n]["decline"] for n in TRUCKS[:5]], ["tu2"] * 4 + ["tu1"])
        sim.apply_scenario({"tu2_closed": 1})
        self.assertEqual(sim.snapshot()["decline-tu2"]["state"], "closed")
        sim.advance(100)                              # 11:40: every truck has finished the trip it was on
        snap = sim.snapshot()
        self.assertEqual([snap[n]["decline"] for n in TRUCKS[:5]], ["tu1"] * 5)
        self.assertEqual(snap["decline-tu2"]["trucks_on_ramp"], 0.0)
        busy = 0
        for _ in range(60):
            sim.advance(1)
            snap = sim.snapshot()
            self.assertEqual(snap["decline-tu2"]["trucks_on_ramp"], 0.0)
            self.assertFalse(any(snap[n]["decline"] == "tu2" for n in TRUCKS))
            busy = max(busy, snap["decline-tu1"]["trucks_on_ramp"])
        self.assertGreaterEqual(busy, 3.0)
        # undo
        sim.apply_scenario({"tu2_closed": 0})
        sim.advance(120)                              # 14:40, after the meal hour
        snap = sim.snapshot()
        self.assertEqual(snap["decline-tu2"]["state"], "open")
        self.assertEqual([snap[n]["decline"] for n in TRUCKS[:5]], ["tu2"] * 4 + ["tu1"])

    def test_close_tu1_sends_its_truck_through_tu2(self):
        sim = new_sim()
        sim.advance(100)
        sim.apply_scenario({"tu1_closed": 1})
        sim.advance(80)
        snap = sim.snapshot()
        self.assertEqual(snap["decline-tu1"]["state"], "closed")
        self.assertEqual(snap["truck-05"]["decline"], "tu2")
        self.assertEqual(snap["decline-tu1"]["trucks_on_ramp"], 0.0)

    def test_fan_vs2_fail_holds_units_and_restricts_the_mine(self):
        sim = new_sim()
        sim.advance(24.5 * 60)                        # 10:00 on day 2
        before = sim.snapshot()
        self.assertEqual(before["mine"]["state"], "production")
        sim.apply_scenario({"fan_vs2_off": 1})
        snap = sim.snapshot()
        self.assertEqual(snap["fan-vs2"]["state"], "failed")
        self.assertEqual(snap["fan-vs2"]["air_flow_m3s"], 0.0)
        self.assertEqual(snap["shaft-vs2"]["air_flow_m3s"], 0.0)
        self.assertEqual(snap["mine"]["air_supply_m3s"], 252.0)
        self.assertEqual(snap["mine"]["state"], "restricted_air")
        # hold order: truck 05, truck 04, LHD 04, truck 03; then the demand fits
        self.assertEqual(snap["mine"]["units_held_vent"], 4.0)
        self.assertEqual(sim.held_trucks, ("truck-05", "truck-04", "truck-03"))
        self.assertEqual(sim.held_lhds, ("lhd-04",))
        self.assertAlmostEqual(snap["mine"]["air_demand_m3s"], 180 + 0.06 * (2 * 304 + 3 * 123), places=1)
        self.assertLessEqual(snap["mine"]["air_demand_m3s"], 252.0)
        self.assertEqual(snap["lhd-04"]["state"], "standby_vent")
        self.assertEqual(snap["stp-000-1"]["state"], "standby")
        self.assertEqual(snap["enterprise"]["binding_link"], "ventilation")
        # the twin shows the analytic rate of the units left working: trucks 01, 02 and three stopes
        analytic = cap.evaluate(MODEL, cap.State(fan_vs2_off=True))
        self.assertEqual((sim.held_trucks, sim.held_lhds), (analytic.air.held_trucks, analytic.air.held_lhds))
        self.assertAlmostEqual(snap["mine"]["air_demand_m3s"], analytic.air.used_m3s, places=1)
        self.assertAlmostEqual(snap["enterprise"]["annual_rate_ktpa"], analytic.capacity_ktpa["ventilation"], delta=0.05)
        self.assertAlmostEqual(snap["enterprise"]["annual_rate_ktpa"], 374, delta=1)
        self.assertLess(snap["lvl-p150"]["air_flow_m3s"], before["lvl-p150"]["air_flow_m3s"])
        sim.advance(90)                               # held trucks finish their trip
        snap = sim.snapshot()
        for name in ("truck-03", "truck-04", "truck-05"):
            self.assertIn(snap[name]["state"], ("held_vent", "maintenance"), name)
            self.assertEqual(snap[name]["payload"], 0.0)
        self.assertGreaterEqual(sum(1 for n in ("truck-03", "truck-04", "truck-05")
                                    if snap[n]["state"] == "held_vent"), 2)
        hoisted = sim.ore_hoisted_t
        sim.run_days(4)
        rate = (sim.ore_hoisted_t - hoisted) / 4
        self.assertLess(rate, 0.55 * 926422 / 360, "two trucks cannot haul the baseline tonnage")
        self.assertGreater(rate, 0.25 * 926422 / 360)
        # undo
        sim.apply_scenario({"fan_vs2_off": 0})
        snap = sim.snapshot()
        self.assertEqual(snap["fan-vs2"]["state"], "running")
        self.assertEqual(snap["mine"]["air_supply_m3s"], 322.0)
        self.assertEqual(snap["mine"]["units_held_vent"], 0.0)
        self.assertNotEqual(snap["mine"]["state"], "restricted_air")
        self.assertNotEqual(snap["stp-000-1"]["state"], "standby")
        self.assertNotEqual(snap["lhd-04"]["state"], "standby_vent")
        hoisted = sim.ore_hoisted_t
        sim.run_days(6)
        self.assertGreater((sim.ore_hoisted_t - hoisted) / 6, 0.85 * 926422 / 360)
        self.assertFalse(any(sim.snapshot()[n]["state"] == "held_vent" for n in TRUCKS))

    def test_pump_one_fail_changes_nothing_but_the_pump_count(self):
        sim = new_sim(pumps_failed_p150=1)
        worst = 0.0
        for _ in range(5 * 24):
            sim.advance(60)
            snap = sim.snapshot(["ps-p150", "mine"])
            self.assertEqual(snap["ps-p150"]["pumps_available"], 2.0)
            self.assertIn(snap["ps-p150"]["state"], ("idle", "pumping"))
            worst = max(worst, snap["ps-p150"]["sump_level_pct"])
        self.assertLess(worst, 85.0)
        self.assertEqual(sim.totals()["flood_volume_m3"], 0.0)
        self.assertEqual(sim.analytic.binding_link, "haulage")

    def test_pump_station_fail_floods_the_lower_levels_and_drains_the_ponds(self):
        sim = new_sim()
        sim.advance(26 * 60)
        sim.apply_scenario({"pumps_failed_p150": 3})
        first = {}
        history = []
        for minute in range(40 * 60):
            sim.advance(1)
            if minute % 10:
                continue
            snap = copy_snapshot(sim)
            history.append(snap)
            marks = {"sump_full": snap["ps-p150"]["sump_level_pct"] >= 100.0,
                     "flood": snap["mine"]["flood_volume_m3"] > 0.0,
                     "lvl-m050": snap["lvl-m050"]["state"] == "flooded",
                     "lvl-000": snap["lvl-000"]["state"] == "flooded",
                     "ponds_empty": snap["pond-upper"]["retention_h"] == 0.0,
                     "plant_short": snap["plant"]["state"] == "water_limited"}
            for key, reached in marks.items():
                if reached and key not in first:
                    first[key] = minute / 60
        early = history[3]
        self.assertEqual(early["ps-p150"]["state"], "failed")
        self.assertEqual(early["ps-p150"]["pumps_available"], 0.0)
        self.assertEqual(early["ps-p150"]["pumped_m3h"], 0.0)
        # the sump rises and the hours to overflow count down
        rising = [h["ps-p150"] for h in history if h["ps-p150"]["sump_level_pct"] < 100.0]
        self.assertGreater(len(rising), 6)
        levels = [r["sump_level_pct"] for r in rising]
        self.assertEqual(levels, sorted(levels))
        countdown = [r["hours_to_overflow"] for r in rising if r["hours_to_overflow"] > 0]
        self.assertGreater(countdown[0], 1.0)
        self.assertLess(countdown[-1], 0.5)
        # order of events (hours after the failure)
        self.assertEqual(set(first), {"sump_full", "flood", "lvl-m050", "lvl-000", "ponds_empty", "plant_short"})
        self.assertLess(first["sump_full"], first["flood"])
        self.assertLess(first["flood"], first["lvl-m050"])
        self.assertLess(first["lvl-m050"], first["lvl-000"])
        self.assertTrue(8 < first["lvl-000"] < 30, first)
        self.assertTrue(12 < first["ponds_empty"] < 30, first)
        # the pond reserve counts down in hours, then the plant slows
        reserve = [h["pond-upper"]["retention_h"] + h["pond-lower"]["retention_h"] for h in history]
        self.assertGreater(reserve[0], 12.0)
        self.assertEqual(reserve[-1], 0.0)
        self.assertLessEqual(abs(first["plant_short"] - first["ponds_empty"]), 0.5)
        last = history[-1]
        self.assertEqual(last["plant"]["feed_tph"], 0.0)
        self.assertEqual(last["water"]["state"], "deficit")
        self.assertTrue(all(last[f"plant-line-{n}"]["state"] in ("water_limited", "maintenance") for n in (1, 2, 3)))
        for name in ("stp-000-1", "stp-000-2", "stp-000-3", "stp-m050-1"):
            self.assertEqual(last[name]["state"], "flooded", name)
        self.assertEqual(last["lvl-000"]["active_stopes"], 0.0)
        self.assertNotEqual(last["stp-p050-1"]["state"], "flooded")
        self.assertEqual(last["enterprise"]["binding_link"], "dewatering")
        self.assertAlmostEqual(last["enterprise"]["annual_rate_ktpa"], 3 * 255.875, delta=0.1)
        self.assertEqual(last["ps-m050"]["state"], "alarm_high")
        self.assertGreater(last["mine"]["flood_volume_m3"], 1500.0)
        # no truck is sent to a flooded stope
        self.assertFalse(any(abs(last[n]["elevation"]) < 0.01 and last[n]["state"] in ("loading", "queue_load")
                             for n in TRUCKS))
        # undo: the pumps clear the flood and the mine comes back
        sim.apply_scenario({"pumps_failed_p150": 0})
        sim.advance(30)
        snap = sim.snapshot()
        self.assertEqual(snap["ps-p150"]["pumps_available"], 3.0)
        self.assertEqual(snap["ps-p150"]["pumps_running"], 2.0)
        self.assertGreater(snap["plant"]["feed_tph"], 0.0)
        sim.run_days(4)
        snap = sim.snapshot()
        self.assertEqual(snap["mine"]["flood_volume_m3"], 0.0)
        self.assertEqual(snap["lvl-000"]["state"], "production")
        self.assertEqual(snap["lvl-m050"]["state"], "development")
        self.assertNotEqual(snap["stp-000-1"]["state"], "flooded")
        self.assertEqual(snap["stp-m050-1"]["state"], "preparation")
        self.assertEqual(snap["enterprise"]["binding_link"], "haulage")
        self.assertIn(snap["ps-p150"]["state"], ("idle", "pumping"))
        hoisted = sim.ore_hoisted_t
        sim.run_days(6)
        self.assertGreater((sim.ore_hoisted_t - hoisted) / 6, 0.85 * 926422 / 360)

    def test_flood_raises_the_discharge_above_the_permit(self):
        sim = new_sim()
        sim.advance(26 * 60)
        self.assertEqual(sim.snapshot()["mon-volchevka"]["state"], "normal")
        sim.apply_scenario({"inflow_factor": 2.18})
        self.assertAlmostEqual(sim.snapshot()["mine"]["inflow_m3h"], 430, delta=1)
        together = False
        for _ in range(48):
            sim.advance(60)
            snap = sim.snapshot(["ps-p150", "ps-m050"])
            together = together or snap["ps-p150"]["pumps_running"] == 2.0
        self.assertTrue(together, "the pumps of ps-p150 run together")
        sim.run_days(2)
        over = []
        for _ in range(48):
            sim.advance(30)
            snap = sim.snapshot()
            over.append(snap["mon-volchevka"]["discharge_m3h"])
            self.assertEqual(snap["mine"]["flood_volume_m3"], 0.0, "the pumps cope with the design inflow")
        mean = sum(over) / len(over)
        self.assertAlmostEqual(mean, 238, delta=15)
        self.assertGreater(mean, MODEL.p("water.permit_m3h"))
        snap = sim.snapshot()
        self.assertEqual(snap["mon-volchevka"]["state"], "exceeded")
        self.assertGreater(snap["mon-volchevka"]["permit_use_pct"], 100.0)
        self.assertEqual(snap["water"]["state"], "discharge_over_permit")
        self.assertGreater(snap["water"]["mine_water_m3h"], 400.0)
        self.assertEqual(snap["mon-volchevka"]["discharge_m3h"], snap["water"]["discharge_m3h"])
        self.assertGreater(snap["mon-volchevka"]["tss_mgl"], 0.0)
        # undo
        sim.apply_scenario({"inflow_factor": 1.0})
        self.assertEqual(sim.snapshot()["mine"]["inflow_m3h"], 197.0)
        sim.run_days(2)
        snap = sim.snapshot()
        self.assertEqual(snap["mon-volchevka"]["state"], "normal")
        self.assertEqual(snap["water"]["state"], "balanced")
        self.assertLess(snap["mon-volchevka"]["discharge_m3h"], 60.0)

    def test_grade_drop_lowers_the_gold(self):
        sim = new_sim()
        sim.advance(30 * 60)                          # 15:30 on day 2: three lines running
        before = sim.snapshot()
        self.assertEqual(before["plant"]["lines_running"], 3.0)
        sim.apply_scenario({"grade_gpt": 1.76})
        snap = sim.snapshot()
        self.assertAlmostEqual(snap["stp-p150-1"]["grade"], 1.75 * 1.76 / 2.05, places=3)
        self.assertAlmostEqual(snap["stp-m100-2"]["grade"], 2.55 * 1.76 / 2.05, places=3)
        self.assertAlmostEqual(snap["rom-stockpile"]["grade"], before["rom-stockpile"]["grade"] * 1.76 / 2.05,
                               delta=0.002)
        self.assertEqual(snap["plant"]["feed_grade"], snap["rom-stockpile"]["grade"])
        self.assertLess(snap["plant"]["recovery_pct"], before["plant"]["recovery_pct"])
        self.assertAlmostEqual(snap["plant"]["recovery_pct"], 84.50, delta=0.05)
        sim.advance(150)                              # the rolling window of the "now" rates
        snap = sim.snapshot()
        ratio = snap["plant"]["gold_poured_oz_day"] / before["plant"]["gold_poured_oz_day"]
        self.assertAlmostEqual(ratio, 47.8 / 56.0, delta=0.012)
        self.assertEqual(snap["plant"]["feed_tph"], before["plant"]["feed_tph"])
        loaded = [n for n in TRUCKS if snap[n]["payload"] > 0]
        self.assertTrue(all(snap[n]["grade"] < 2.05 for n in loaded))
        # a year at this grade: 47.8 koz per 1000 kt milled
        rate = snap["plant"]["gold_poured_oz_day"] / (snap["plant"]["feed_tph"] * 24)
        self.assertAlmostEqual(rate * 1e6, 47800, delta=600)
        # undo
        sim.apply_scenario({"grade_gpt": 2.05})
        sim.advance(150)
        snap = sim.snapshot()
        self.assertAlmostEqual(snap["stp-p150-1"]["grade"], 1.75, places=3)
        self.assertAlmostEqual(snap["plant"]["gold_poured_oz_day"], before["plant"]["gold_poured_oz_day"], delta=1.5)

    def test_line2_down_cuts_the_feed_by_a_third(self):
        sim = new_sim()
        sim.advance(30 * 60)
        before = sim.snapshot()
        sim.apply_scenario({"line_down": 2})
        sim.advance(1)
        snap = sim.snapshot()
        self.assertEqual(snap["plant-line-2"]["state"], "off")
        self.assertEqual(snap["plant-line-2"]["feed_tph"], 0.0)
        self.assertEqual([snap[f"plant-line-{n}"]["state"] for n in (1, 3)], ["running", "running"])
        self.assertAlmostEqual(snap["plant"]["feed_tph"] / before["plant"]["feed_tph"], 2 / 3, delta=0.002)
        self.assertEqual(snap["plant"]["lines_running"], 2.0)
        self.assertAlmostEqual(snap["plant"]["capacity_ktpa"], 667, delta=0.5)
        self.assertEqual(snap["enterprise"]["binding_link"], "plant")
        self.assertEqual(snap["plant"]["tailings_tph"], snap["plant"]["feed_tph"])
        # the stockpile grows: the mine delivers more than two lines mill
        stock = snap["rom-stockpile"]["tonnes"]
        sim.run_days(3)
        self.assertGreater(sim.snapshot()["rom-stockpile"]["tonnes"], stock + 800)
        # undo
        sim.apply_scenario({"line_down": 0})
        sim.advance(1)
        snap = sim.snapshot()
        self.assertEqual(snap["plant-line-2"]["state"], "running")
        self.assertEqual(snap["plant"]["capacity_ktpa"], 1000.0)
        self.assertEqual(snap["enterprise"]["binding_link"], "haulage")


class TestMeasures(SimCase):
    def test_step1200_raises_the_line_rates_and_then_water_binds(self):
        sim = new_sim()
        sim.advance(30 * 60)
        sim.apply_scenario({"target_ktpa": 1200, "m_plant": 1})
        sim.advance(1)
        snap = sim.snapshot()
        self.assertEqual(snap["plant"]["capacity_ktpa"], 1200.0)
        for n in (1, 2, 3):
            self.assertAlmostEqual(snap[f"plant-line-{n}"]["feed_tph"], 49.63, delta=0.01)   # decision 9.4
            self.assertEqual(snap[f"plant-line-{n}"]["utilisation_pct"], 100.0)
        self.assertEqual(snap["plant-line-4"]["state"], "planned")
        self.assertEqual(snap["enterprise"]["binding_link"], "haulage")
        days_before = snap["rom-stockpile"]["days_of_feed"]
        self.assertLess(days_before, 36000 / (1000000 / 365))        # stockpile days fall
        # without a water measure the ponds run down and the last line goes short of water
        sim.run_days(12)
        milled = sim.plant.milled_t
        states = set()
        for _ in range(4 * 24):
            sim.advance(60)
            snap = sim.snapshot()
            states.add(snap["plant-line-3"]["state"])
            self.assertIn(snap["plant-line-1"]["state"], ("running", "maintenance"))
        self.assertIn("water_limited", states)
        self.assertGreater(snap["water"]["deficit_m3h"], 5.0)
        rate = (sim.plant.milled_t - milled) / 4 * 365
        self.assertLess(rate, 1100000, "the plant cannot hold 1200 kt/yr on the mine water alone")
        self.assertLess(sim.snapshot()["rom-stockpile"]["days_of_feed"], days_before)
        # measure W1: tailings reclaim covers the plant
        sim.apply_scenario({"m_water": 1})
        sim.run_days(2)
        snap = sim.snapshot()
        self.assertGreater(snap["water"]["reclaim_m3h"], 60.0)
        self.assertEqual(snap["tailings"]["reclaim_m3h"], snap["water"]["reclaim_m3h"])
        self.assertEqual(snap["water"]["state"], "balanced")
        self.assertLess(snap["water"]["deficit_m3h"], 1.0)
        self.assertNotEqual(snap["plant"]["state"], "water_limited")

    def test_m_plant_stages_bring_lines_4_to_6_into_service(self):
        sim = new_sim()
        sim.advance(30 * 60)
        sim.apply_scenario({"m_plant": 2})
        snap = sim.snapshot()
        self.assertEqual([snap[f"plant-line-{n}"]["state"] for n in (4, 5, 6)], ["running", "running", "planned"])
        self.assertEqual(sim.tier("plant-line-4"), "M")
        sim.advance(1)
        snap = sim.snapshot()
        self.assertEqual(snap["plant"]["capacity_ktpa"], 2000.0)
        self.assertEqual(snap["plant"]["lines_running"], 5.0)
        for n in (1, 2, 3, 4, 5):
            self.assertAlmostEqual(snap[f"plant-line-{n}"]["feed_tph"], 49.63, delta=0.01)
        self.assertAlmostEqual(snap["plant"]["feed_tph"], 5 * 49.63, delta=0.1)
        self.assertEqual(snap["enterprise"]["binding_link"], "haulage")
        sim.apply_scenario({"m_plant": 3, "m_water": 2})
        sim.advance(1)
        snap = sim.snapshot()
        self.assertEqual(snap["plant"]["capacity_ktpa"], 2500.0)
        self.assertAlmostEqual(snap["plant-line-6"]["feed_tph"], 62.04, delta=0.01)
        self.assertEqual(snap["plant-line-6"]["utilisation_pct"], 100.0)
        # six lines with water for them mill far more than the mine hoists: the stockpile is used
        # up and the last lines starve
        sim.run_days(12)
        states = set()
        for _ in range(48):
            sim.advance(30)
            snap = sim.snapshot()
            states.update(snap[f"plant-line-{n}"]["state"] for n in (5, 6))
        self.assertEqual(states, {"starved"})
        self.assertIn(snap["rom-stockpile"]["state"], ("low", "empty"))
        self.assertEqual(snap["plant"]["state"], "starved")
        self.assertLess(snap["plant"]["feed_tph"], 200.0)
        self.assertGreaterEqual(snap["rom-stockpile"]["tonnes"], 0.0)
        # undo
        sim.apply_scenario({"m_plant": 0, "m_water": 0})
        snap = sim.snapshot()
        self.assertEqual([snap[f"plant-line-{n}"]["state"] for n in (4, 5, 6)], ["planned"] * 3)
        self.assertEqual(snap["plant"]["capacity_ktpa"], 1000.0)

    def test_m_haul_brings_trucks_06_07_and_they_wait_for_air_until_m_vent(self):
        sim = new_sim()
        sim.advance(24.5 * 60)                        # 10:00 on day 2
        sim.apply_scenario({"m_haul": 1})
        snap = sim.snapshot()
        self.assertNotEqual(snap["truck-06"]["state"], "parked")
        self.assertNotEqual(snap["truck-07"]["state"], "parked")
        self.assertEqual(snap["truck-08"]["state"], "parked")
        self.assertEqual(snap["truck-06"]["decline"], "tu1")
        # 7 trucks need 369.9 m3/s; 322 are supplied: the two new trucks are held
        self.assertEqual(sim.held_trucks, ("truck-07", "truck-06"))
        self.assertEqual(snap["mine"]["state"], "restricted_air")
        self.assertEqual((snap["truck-06"]["state"], snap["truck-07"]["state"]), ("held_vent", "held_vent"))
        self.assertEqual(sim.tier("truck-06"), "S")
        capacity = sim.analytic.capacity_ktpa
        self.assertLess(capacity["ventilation"], capacity["haulage"], "the air now carries less than the trucks")
        # the advisor's view of the same state: the trucks left working haul the baseline tonnage
        self.assertEqual(sim.analytic.air.held_trucks, sim.held_trucks)
        self.assertEqual(snap["enterprise"]["binding_link"], "ventilation")
        self.assertEqual(snap["enterprise"]["annual_rate_ktpa"], round(sim.baseline.capacity_ktpa["haulage"], 1))
        self.assertAlmostEqual(snap["mine"]["air_demand_m3s"], sim.analytic.air.used_m3s, places=1)
        self.assertEqual(sim.trucks_on_decline, {"tu1": 1, "tu2": 4})     # held trucks are not on the decline
        sim.apply_scenario({"m_vent": 1})
        snap = sim.snapshot()
        self.assertEqual(snap["fan-vpv"]["state"], "running")
        self.assertEqual(snap["fan-vpv"]["air_flow_m3s"], 105.0)
        self.assertEqual(snap["raise-vpv"]["state"], "in_service")
        self.assertEqual(snap["raise-vpv"]["air_flow_m3s"], 105.0)
        self.assertEqual(snap["raise-vpv"]["air_velocity_ms"], 15.0)
        self.assertEqual(snap["mine"]["air_supply_m3s"], 427.0)
        self.assertAlmostEqual(snap["mine"]["air_demand_m3s"], 369.9, delta=0.05)
        self.assertEqual(snap["mine"]["units_held_vent"], 0.0)
        on_tu1 = 0
        working = set()
        for _ in range(90):
            sim.advance(1)
            snap = sim.snapshot()
            on_tu1 = max(on_tu1, snap["decline-tu1"]["trucks_on_ramp"])
            working.update(n for n in ("truck-06", "truck-07") if snap[n]["state"] in ("descending", "hauling_up"))
        self.assertEqual(working, {"truck-06", "truck-07"})
        self.assertGreaterEqual(on_tu1, 2.0)
        self.assertGreater(snap["lvl-p150"]["air_flow_m3s"], 40.0)
        # undo: the trucks finish their trip and park
        sim.apply_scenario({"m_haul": 0, "m_vent": 0})
        sim.advance(90)
        snap = sim.snapshot()
        self.assertEqual((snap["truck-06"]["state"], snap["truck-07"]["state"]), ("parked", "parked"))
        self.assertEqual(snap["truck-06"]["decline"], "none")
        self.assertEqual(snap["fan-vpv"]["state"], "planned")
        self.assertEqual(snap["raise-vpv"]["state"], "planned")
        self.assertEqual(snap["mine"]["air_supply_m3s"], 322.0)
        self.assertEqual(sim.tier("truck-06"), "L")

    def test_m_vent_stages(self):
        sim = new_sim(m_vent=2)
        snap = sim.snapshot()
        self.assertEqual(snap["mine"]["air_supply_m3s"], 667.0)
        self.assertEqual(snap["fan-vs3"]["state"], "running")
        self.assertEqual(snap["shaft-vs3"]["state"], "in_service")
        self.assertEqual(snap["shaft-vs3"]["air_flow_m3s"], 240.0)
        self.assertEqual(snap["shaft-vs3"]["air_velocity_ms"], 15.0)
        self.assertEqual(snap["raise-vhv-exhaust"]["air_flow_m3s"], 667.0)
        self.assertGreater(snap["fan-vs3"]["power_kw"], 0.0)

    def test_m_stopes_brings_the_next_stope_lhd_and_rig(self):
        sim = new_sim()
        sim.advance(26 * 60)
        self.assertEqual(sim.snapshot()["stp-p150-2"]["state"], "standby")
        sim.apply_scenario({"m_stopes": 1})
        snap = sim.snapshot()
        self.assertNotEqual(snap["stp-p150-2"]["state"], "standby")
        self.assertEqual(snap["lhd-05"]["stope"], "stp-p150-2")
        self.assertNotEqual(snap["lhd-05"]["state"], "parked")
        self.assertNotEqual(snap["rig-03"]["state"], "parked")
        self.assertEqual(snap["rig-04"]["state"], "parked")
        self.assertEqual(snap["lvl-p150"]["active_stopes"], 2.0)
        self.assertEqual(snap["stp-p100-2"]["state"], "standby")
        states = set()
        for _ in range(5 * 24 * 2):
            sim.advance(30)
            states.add(sim.snapshot(["stp-p150-2"])["stp-p150-2"]["state"])
        self.assertTrue({"drilling", "charging", "ventilating", "mucking"} <= states, states)
        self.assertGreater(sim.snapshot()["lhd-05"]["tonnes_today"] + sim.mining.by_name["stp-p150-2"].broken, 0.0)
        # undo
        sim.apply_scenario({"m_stopes": 0})
        snap = sim.snapshot()
        self.assertEqual(snap["stp-p150-2"]["state"], "standby")
        self.assertEqual((snap["lhd-05"]["state"], snap["lhd-05"]["stope"]), ("parked", "none"))
        self.assertEqual(snap["rig-03"]["state"], "parked")
        self.assertEqual(snap["lvl-p150"]["active_stopes"], 1.0)

    def test_m_water_2_takes_river_water_only_when_it_is_missing(self):
        sim = new_sim(m_water=2)
        sim.run_days(6)
        snap = sim.snapshot()
        self.assertEqual(snap["mon-sekisovka"]["intake_m3h"], 0.0, "no intake while the mine water covers the demand")
        self.assertGreater(snap["water"]["reclaim_m3h"], 50.0)
        sim = new_sim(**FULL_2500)
        sim.run_days(10)
        snap = sim.snapshot()
        self.assertGreater(snap["mon-sekisovka"]["intake_m3h"], 20.0)
        self.assertLessEqual(snap["mon-sekisovka"]["intake_m3h"], 150.0)
        self.assertEqual(snap["water"]["extra_intake_m3h"], snap["mon-sekisovka"]["intake_m3h"])
        self.assertEqual(snap["mon-sekisovka"]["state"], "normal")
        self.assertLess(snap["water"]["deficit_m3h"], 1.0)

    def test_m_tailings_builds_the_new_cell(self):
        sim = new_sim()
        before = sim.snapshot()
        self.assertEqual(before["tsf-cell5"]["state"], "planned")
        self.assertAlmostEqual(before["tailings"]["years_left"], 3172095 / 926110, delta=0.01)
        sim.apply_scenario({"m_tailings": 1})
        snap = sim.snapshot()
        self.assertEqual(snap["tsf-cell5"]["state"], "standby")
        self.assertEqual(snap["tsf-cell5"]["free_capacity_t"], 6000000.0)
        self.assertEqual(snap["tailings"]["free_capacity_t"], before["tailings"]["free_capacity_t"] + 6000000.0)
        self.assertGreater(snap["tailings"]["years_left"], before["tailings"]["years_left"] + 6.0)
        sim.apply_scenario({"m_tailings": 0})
        self.assertEqual(sim.snapshot()["tsf-cell5"]["state"], "planned")

    def test_tailings_fill_the_dams_in_order_and_stop_the_plant_when_full(self):
        sim = new_sim()
        sim.plant.tailings_t = 318195.0 - 2000.0      # dam 4 is nearly full
        sim.plant.configure()
        sim.run_days(1.5)
        snap = sim.snapshot()
        self.assertEqual((snap["tsf-dam4"]["state"], snap["tsf-dam2"]["state"], snap["tsf-dam3"]["state"]),
                         ("full", "active", "standby"))
        self.assertGreater(snap["tsf-dam2"]["inflow_tph"], 0.0)
        self.assertEqual(snap["tsf-dam4"]["inflow_tph"], 0.0)
        sim.plant.tailings_t = 3172095.0 - 1500.0     # everything is nearly full
        sim.plant.configure()
        sim.run_days(1.5)
        snap = sim.snapshot()
        self.assertEqual(snap["tailings"]["state"], "full")
        self.assertEqual(snap["tailings"]["free_capacity_t"], 0.0)
        self.assertEqual(snap["plant"]["feed_tph"], 0.0)
        self.assertEqual(snap["tsf-dam3"]["state"], "full")
        self.assertEqual(snap["enterprise"]["binding_link"], "tailings")
        sim.apply_scenario({"m_tailings": 1})         # the new cell takes over
        sim.advance(5)
        snap = sim.snapshot()
        self.assertEqual(snap["tsf-cell5"]["state"], "active")
        self.assertGreater(snap["plant"]["feed_tph"], 0.0)

    def test_m_dev_advances_the_declines_faster(self):
        slow, fast = new_sim(), new_sim(m_dev=1)
        slow.run_days(36)
        fast.run_days(36)
        advance_slow = -50.0 - slow.snapshot()["decline-tu1"]["bottom_elevation"]
        advance_fast = -50.0 - fast.snapshot()["decline-tu1"]["bottom_elevation"]
        self.assertAlmostEqual(advance_slow, 34 * 36 / 360, delta=0.05)
        self.assertAlmostEqual(advance_fast, 50 * 36 / 360, delta=0.05)

    def test_full_set_for_2000_hoists_the_analytic_minimum_of_haulage_and_stopes(self):
        run = run_of("full2000", 60, **FULL_2000)
        analytic = cap.evaluate(MODEL, cap.State(**FULL_2000))
        expected = min(analytic.capacity_ktpa["haulage"], analytic.capacity_ktpa["stopes"]) * 1000
        self.assertWithin(run.year["ore_hoisted_t"], expected, MODEL.p("calib.sim_consistency_tol_pct"),
                          "full set for 2.0 Mtpa:")
        self.assertWithin(run.year["ore_milled_t"], 2000000, 3, "plant feed at 2.0 Mtpa:")
        self.assertGreater(run.year["gold_oz"], 100000, "C12 in the simulator")
        self.assertEqual(run.totals["water_deficit_m3"], 0.0)
        self.assertEqual(run.totals["traffic_conflicts"], 0.0)
        self.assertLessEqual(run.elapsed, 60.0)
        snap = run.sim.snapshot()
        self.assertEqual(snap["mine"]["units_held_vent"], 0.0)
        self.assertEqual(snap["mine"]["trucks_active"] + sum(1 for n in TRUCKS if snap[n]["state"] == "maintenance"),
                         10.0)
        self.assertEqual(sum(1 for n in (4, 5) if snap[f"plant-line-{n}"]["state"] != "planned"), 2)
        self.assertEqual(snap["plant-line-6"]["state"], "planned")
        self.assertAlmostEqual(snap["mine"]["air_demand_m3s"], 512.0, delta=0.5)

    def test_more_trucks_than_ore_wait_for_the_stopes(self):
        # haulage for 2.5 Mtpa on four stopes: the stopes bind, trucks queue for ore
        run = run_of("twelve", 30, m_haul=3, m_vent=2)
        stopes_kt = cap.evaluate(MODEL).capacity_ktpa["stopes"]
        # the stopes' output plus the broken ore that was in them at the epoch
        drawn = (run.totals["ore_broken_start_t"] - run.totals["ore_broken_t"]) * 360 / 30
        self.assertWithin(run.year["ore_hoisted_t"] - drawn, stopes_kt * 1000, 3)
        self.assertGreater(run.totals["load_wait_min_per_trip"], 1.0)


class TestAirLimitedCases(SimCase):
    """Spec 2.6 against 2.3 item 3 (decision 10.5): where the air holds units, the simulated mine
    hoists what the analytic ventilation capacity says, and the twins never show more."""

    def check(self, key, knobs, held_trucks, held_lhds):
        run = run_of(key, MODEL.p("calib.run_days"), **knobs)
        analytic = cap.evaluate(MODEL, cap.State.from_knobs(knobs))
        sim = run.sim
        self.assertEqual((analytic.air.held_trucks, analytic.air.held_lhds), (held_trucks, held_lhds), key)
        self.assertEqual((sim.held_trucks, sim.held_lhds), (held_trucks, held_lhds), key)
        self.assertEqual(analytic.binding_link, "ventilation", key)
        self.assertAlmostEqual(analytic.achievable_ktpa, analytic.capacity_ktpa["ventilation"])
        self.assertWithin(run.year["ore_hoisted_t"], analytic.capacity_ktpa["ventilation"] * 1000,
                          MODEL.p("calib.sim_consistency_tol_pct"), f"{key}:")
        snap = sim.snapshot()
        self.assertEqual(snap["mine"]["state"], "restricted_air", key)
        self.assertEqual(snap["mine"]["units_held_vent"], float(len(held_trucks) + len(held_lhds)), key)
        self.assertAlmostEqual(snap["mine"]["air_demand_m3s"], analytic.air.used_m3s, places=1)
        self.assertLessEqual(snap["mine"]["air_demand_m3s"], snap["mine"]["air_supply_m3s"])
        self.assertEqual(snap["enterprise"]["binding_link"], "ventilation", key)
        self.assertEqual(snap["enterprise"]["annual_rate_ktpa"], round(analytic.capacity_ktpa["ventilation"], 1))
        for name in held_trucks:
            self.assertIn(snap[name]["state"], ("held_vent", "maintenance"), name)
        for name in held_lhds:
            self.assertEqual(snap[name]["state"], "standby_vent", name)
        self.assertEqual(run.totals["traffic_conflicts"], 0.0)
        return run, analytic

    def test_m_haul_1_alone_hoists_the_baseline(self):
        run, analytic = self.check("air m_haul=1", dict(m_haul=1), ("truck-07", "truck-06"), ())
        # 1000 kt/yr is not reached, in the library and in the mine alike
        self.assertEqual(analytic.capacity_rounded["ventilation"], 926)
        self.assertLess(run.year["ore_hoisted_t"], 0.97 * 1000000)
        # the two trucks never leave the portal: the run is the baseline run, tonne for tonne
        self.assertEqual(run.totals["ore_hoisted_t"], baseline_run().totals["ore_hoisted_t"])
        self.assertEqual(run.totals["truck_trips"], baseline_run().totals["truck_trips"])
        snap = run.sim.snapshot()
        self.assertEqual((snap["truck-06"]["trips_today"], snap["truck-07"]["trips_today"]), (0.0, 0.0))

    def test_m_haul_2_without_ventilation_leaves_two_stopes(self):
        run, analytic = self.check("air m_haul=2", dict(m_haul=2),
                                   ("truck-10", "truck-09", "truck-08", "truck-07"), ("lhd-04", "lhd-03"))
        # the stopes left working bind: more trucks in service, less ore than the baseline
        self.assertAlmostEqual(analytic.capacity_ktpa["ventilation"], 2 * 255.875)
        self.assertLess(run.year["ore_hoisted_t"], 0.6 * baseline_run().year["ore_hoisted_t"])
        snap = run.sim.snapshot()
        self.assertEqual((snap["stp-p050-1"]["state"], snap["stp-000-1"]["state"]), ("standby", "standby"))

    def test_fan_vs2_fail_at_baseline(self):
        run, analytic = self.check("air fan", dict(fan_vs2_off=1), ("truck-05", "truck-04", "truck-03"), ("lhd-04",))
        self.assertEqual(analytic.capacity_rounded["ventilation"], 374)
        self.assertEqual(analytic.air.centroid_working_m, 100)
        self.assertEqual(run.sim.snapshot()["stp-000-1"]["state"], "standby")

    def test_fan_vs2_fail_with_the_measure_set_for_1200(self):
        run, analytic = self.check("air fan 1200", dict(fan_vs2_off=1, **FULL_1200), ("truck-07", "truck-06"), ())
        self.assertEqual(run.sim.snapshot()["mine"]["air_supply_m3s"], 357.0)
        self.assertEqual(analytic.capacity_rounded["ventilation"], 926)
        self.assertLess(run.year["ore_hoisted_t"], 1200000 * 0.9)

    def test_m_stopes_1_alone_holds_the_only_ad45(self):
        # the rule holds trucks first: LHD 05 at 322 m3/s costs truck 05 and a fifth of the tonnage
        run, analytic = self.check("air m_stopes=1", dict(m_stopes=1), ("truck-05",), ())
        self.assertEqual(analytic.capacity_rounded["ventilation"], 683)
        self.assertLess(run.year["ore_hoisted_t"], 0.85 * baseline_run().year["ore_hoisted_t"])

    def test_gap_with_five_stopes_is_the_haulage_formula_not_the_air_rule(self):
        # The same five trucks on the same five stopes, once with trucks 06 and 07 held and once with
        # no hold at all: the simulator hoists the same, and both runs sit a few per cent above the
        # analytic haulage of the five trucks, which keeps the +75 m centroid for the fifth stope too.
        held = run_of("air fan 1200", MODEL.p("calib.run_days"), fan_vs2_off=1, **FULL_1200)
        free = run_of("five stopes", MODEL.p("calib.run_days"), m_stopes=1, m_vent=1)
        self.assertEqual((free.sim.held_trucks, free.sim.held_lhds), ((), ()))
        self.assertWithin(held.year["ore_hoisted_t"], free.year["ore_hoisted_t"], 1.0)
        haulage = cap.evaluate(MODEL, cap.State(m_stopes=1, m_vent=1)).capacity_ktpa["haulage"] * 1000
        self.assertAlmostEqual(haulage, cap.evaluate(MODEL).capacity_ktpa["haulage"] * 1000)
        for run in (held, free):
            self.assertGreater(run.year["ore_hoisted_t"], haulage)
            self.assertWithin(run.year["ore_hoisted_t"], haulage, MODEL.p("calib.sim_consistency_tol_pct"))

    def test_no_hold_and_no_restriction_once_the_air_fits(self):
        run = run_of("air m_haul=1 m_vent=1", 30, m_haul=1, m_vent=1)
        analytic = cap.evaluate(MODEL, cap.State(m_haul=1, m_vent=1))
        self.assertFalse(analytic.air.restricted)
        self.assertEqual((run.sim.held_trucks, run.sim.held_lhds), ((), ()))
        self.assertEqual((analytic.binding_link, analytic.capacity_rounded["plant"]), ("plant", 1000))
        # seven trucks on four stopes: the mine delivers the 1000 kt/yr the advisor names as reached
        self.assertGreater(run.year["ore_hoisted_t"], 0.97 * 1000000)


# ---------------------------------------------------------------------------------------------
# publishing support
# ---------------------------------------------------------------------------------------------

class TestPublishing(SimCase):
    def test_tiers(self):
        sim = new_sim()
        self.assertEqual(sim.tier("truck-01"), "S")
        self.assertEqual(sim.tier("kz.sekis:lhd-02"), "S")
        self.assertEqual(sim.tier("truck-06"), "L")           # parked
        self.assertEqual(sim.tier("lhd-05"), "L")
        self.assertEqual(sim.tier("rig-03"), "L")
        self.assertEqual(sim.tier("stp-p150-1"), "M")
        self.assertEqual(sim.tier("stp-m100-1"), "L")         # planned
        self.assertEqual(sim.tier("fan-vpv"), "L")
        self.assertEqual(sim.tier("plant-line-5"), "L")
        self.assertEqual(sim.tier("mine"), "M")
        self.assertEqual(sim.tier("lvl-p150"), "L")
        self.assertEqual(sim.tier("scenario"), "on_change")

    def publish(self, sim, seconds, scale=None, loop=0.5):
        planner = PublishPlanner(sim, scale)
        sent = []                                     # (time, name)
        clock = 1000.0
        for _ in range(int(seconds / loop)):
            sim.step(loop)
            for name in planner.due(clock):
                sent.append((clock, name))
            clock += loop
        return planner, sent

    def worst_second(self, sent):
        times = sorted(t for t, _ in sent)
        worst = 0
        start = 0
        for end, t in enumerate(times):
            while times[start] <= t - 1.0:
                start += 1
            worst = max(worst, end - start + 1)
        return worst

    def test_budget_and_periods_at_baseline(self):
        sim = new_sim()
        planner, sent = self.publish(sim, 120)
        self.assertEqual(planner.periods(), {"S": 2.0, "M": 6.0, "L": 20.0})
        self.assertLessEqual(self.worst_second(sent), 20)
        self.assertLessEqual(len(sent) / 120, 20)
        count = {}
        for _, name in sent:
            count[name] = count.get(name, 0) + 1
        self.assertNotIn("scenario", count)
        self.assertNotIn("advisor", count)
        self.assertEqual(set(count), set(sim.snapshot()) - {"scenario"})
        self.assertAlmostEqual(count["truck-01"], 60, delta=2)        # every 2 s
        self.assertAlmostEqual(count["mine"], 20, delta=1)            # every 6 s
        self.assertAlmostEqual(count["lvl-p150"], 6, delta=1)         # every 20 s
        self.assertAlmostEqual(count["truck-09"], 6, delta=1)         # parked: tier L

    def test_budget_with_every_unit_active(self):
        sim = new_sim(**FULL_2500)
        sim.advance(120)
        planner, sent = self.publish(sim, 120)
        self.assertEqual(planner.periods()["S"], 3.0)                 # more than 14 fast units
        self.assertLessEqual(self.worst_second(sent), 20)
        count = {}
        for _, name in sent:
            count[name] = count.get(name, 0) + 1
        self.assertAlmostEqual(count["truck-12"], 40, delta=2)
        self.assertGreaterEqual(min(count.values()), 5, "no thing is starved by the budget")

    def test_scale_and_hard_limit(self):
        sim = new_sim(**FULL_2500)
        planner, sent = self.publish(sim, 60, scale=0.25)             # four times faster than allowed
        self.assertEqual(planner.periods(), {"S": 0.75, "M": 1.5, "L": 5.0})
        self.assertLessEqual(self.worst_second(sent), 20)
        self.assertLessEqual(len(sent), 60 * 20 + 20)
        self.assertGreater(len(sent), 60 * 19, "the budget is used when more is due than fits")
        count = {}
        for _, name in sent:
            count[name] = count.get(name, 0) + 1
        self.assertEqual(len(count), 94)
        self.assertGreaterEqual(min(count.values()), 3, "the budget is shared: no thing is starved")
        planner, sent = self.publish(new_sim(), 60, scale=2.0)
        self.assertEqual(planner.periods(), {"S": 4.0, "M": 12.0, "L": 40.0})

    def test_changed_since(self):
        sim = new_sim()
        token, changed = sim.changed_since()
        self.assertEqual(len(changed), 95)
        token2, changed = sim.changed_since(token)
        self.assertEqual(changed, {})
        sim.advance(60)
        token3, changed = sim.changed_since(token2)
        self.assertIn("enterprise", changed)
        self.assertIn("truck-01", changed)
        self.assertNotIn("truck-12", changed)         # parked
        self.assertNotIn("scenario", changed)
        self.assertNotIn("stp-m100-1", changed)
        self.assertEqual(changed["enterprise"], sim.features("enterprise"))
        sim.apply_scenario({"m_haul": 1, "revision": 1})
        _, changed = sim.changed_since(token3)
        self.assertIn("scenario", changed)
        self.assertIn("truck-06", changed)
        # an older token still sees everything that changed after it
        _, since_first = sim.changed_since(token)
        self.assertIn("truck-01", since_first)
        self.assertIn("scenario", since_first)

    def test_message_helpers(self):
        sim = new_sim()
        message = ditto_modify(sim.namespace, "truck-01", sim.features("truck-01"))
        self.assertEqual(message["topic"], "kz.sekis/truck-01/things/twin/commands/modify")
        self.assertEqual(message["path"], "/features")
        self.assertEqual(message["value"]["state"], {"properties": {"value": "surface_haul"}})   # loaded, at 09:30
        self.assertEqual(set(message["value"]), set(sim.features("truck-01")))
        self.assertEqual(telemetry_topic("truck-01"), "telemetry/sekis/truck-01")
        self.assertLess(len(json.dumps(message)), 1024)


# ---------------------------------------------------------------------------------------------
# parameters
# ---------------------------------------------------------------------------------------------

class TestParameters(SimCase):
    def test_missing_params_are_labelled_and_really_missing(self):
        params = json.loads((TEAM / "model" / "params.json").read_text(encoding="utf-8"))
        for pid, (value, unit, source) in MISSING_PARAMS.items():
            self.assertTrue(source.startswith("ASSUMPTION: ") or source.startswith("FACT "), pid)
            self.assertIsInstance(unit, str)
            self.assertNotIn(pid, params, f"{pid} is in params.json now: drop it from MISSING_PARAMS")

    def test_tuned_delay_factor_is_inside_its_range(self):
        # the tuned value (0.785) lives in params.json; TUNED_PARAMS is empty but still works
        value = MODEL.p("sim.op_delay_factor")
        self.assertEqual(value, 0.785)
        self.assertTrue(MODEL.p("sim.op_delay_factor_min") <= value <= MODEL.p("sim.op_delay_factor_max"))
        for pid, (tuned, unit, source, replaces) in TUNED_PARAMS.items():
            self.assertTrue(source.startswith("ASSUMPTION: "), pid)
        sim = new_sim()
        self.assertEqual(sim.p("sim.op_delay_factor"), value)
        self.assertEqual(sim.haul.k_delay, value)

    def test_package_uses_the_standard_library_only(self):
        import ast
        allowed = {"__future__", "bisect", "collections", "datetime", "json", "math", "pathlib", "random", "typing"}
        for path in sorted((TEAM / "sekis" / "sim").glob("*.py")):
            source = path.read_bytes()
            self.assertNotIn(b"\r\n", source, f"{path.name} must use LF line endings")
            for node in ast.walk(ast.parse(source.decode("utf-8"))):
                names = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    names = [node.module]
                for name in names:
                    self.assertIn(name.split(".")[0], allowed, f"{path.name} imports {name}")


if __name__ == "__main__":
    unittest.main()
