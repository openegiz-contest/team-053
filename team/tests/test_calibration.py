"""Tests for team/sekis/capacity.py.

Covers the reference table and the depth effect of spec 2.3, the analytic calibration checks of
spec 2.9 (C1, C2, C4-C7, C9, C10, C12), the scenario effects of spec 3.3 that are analytic, and
the four bottleneck sequences of spec 3.4. The numbers written out here are the expected values
of the spec; the library itself reads every number from params.json and registry.json.
"""

import ast
import json
import math
import re
import sys
import unittest
from pathlib import Path

TEAM = Path(__file__).resolve().parent.parent
if str(TEAM) not in sys.path:
    sys.path.insert(0, str(TEAM))

from sekis import capacity as cap  # noqa: E402

LIBRARY = TEAM / "sekis" / "capacity.py"
PARAMS = TEAM / "model" / "params.json"

# Full measure sets of the reference table (spec 2.3).
FULL_1200 = dict(m_haul=1, m_stopes=1, m_vent=1, m_plant=1, m_water=1, m_tailings=1)
FULL_2000 = dict(m_haul=2, m_stopes=2, m_vent=2, m_plant=2, m_water=2, m_tailings=1, m_dev=1)
FULL_2500 = dict(m_haul=3, m_stopes=3, m_vent=2, m_plant=3, m_water=2, m_tailings=1, m_dev=1)


class ModelCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = cap.load_model()
        cls.base = cap.evaluate(cls.model)

    def evaluate(self, **changes):
        return cap.evaluate(self.model, cap.State(**changes))

    def assertWithin(self, value, expected, pct, msg=None):
        self.assertAlmostEqual(value, expected, delta=abs(expected) * pct / 100,
                               msg=f"{msg or ''} model {value:.2f}, expected {expected} +-{pct} %")

    def tph(self, ktpa):
        return ktpa * 1000 / 8760


class TestReferenceTable(ModelCase):
    """Spec 2.3: reference values, each within +-1 %."""

    COLUMNS = ("haulage", "stopes", "development", "ventilation", "plant", "water", "tailings")
    TABLE = {
        "baseline": ({}, (926, 1024, 1750, 958, 1000, 1000, 1057), 317.2),
        "full set for 1.2 Mtpa": (FULL_1200, (1386, 1279, 1750, 1665, 1200, 1533, 3057), 385.7),
        "full set for 2.0 Mtpa": (FULL_2000, (2076, 2047, 2573, 3045, 2000, 2700, 3057), 512.0),
        "full set for 2.5 Mtpa": (FULL_2500, (2512, 2559, 2573, 2938, 2500, 2700, 3057), 596.3),
    }

    def test_capacities_within_one_percent(self):
        for name, (knobs, expected, _) in self.TABLE.items():
            res = self.evaluate(**knobs)
            for link, want in zip(self.COLUMNS, expected):
                with self.subTest(measure_set=name, link=link):
                    self.assertWithin(res.capacity_ktpa[link], want, 1.0, f"{name} / {link}:")

    def test_air_demand_within_one_percent(self):
        for name, (knobs, _, air_demand) in self.TABLE.items():
            with self.subTest(measure_set=name):
                self.assertWithin(self.evaluate(**knobs).air.demand_m3s, air_demand, 1.0, f"{name} air demand:")

    def test_dewatering_does_not_limit_in_the_reference_sets(self):
        for name, (knobs, _, _) in self.TABLE.items():
            res = self.evaluate(**knobs)
            self.assertTrue(math.isinf(res.capacity_ktpa["dewatering"]), name)
            self.assertIsNone(res.capacity_rounded["dewatering"], name)
            self.assertFalse(res.dewatering.limiting, name)

    def test_eight_links_in_tie_break_order(self):
        self.assertEqual(cap.LINKS, ("haulage", "ventilation", "stopes", "development", "dewatering",
                                     "plant", "water", "tailings"))
        self.assertEqual(tuple(self.base.capacity_ktpa), cap.LINKS)
        self.assertEqual(tuple(self.base.capacity_rounded), cap.LINKS)

    def test_baseline_haulage_matches_ore_mined(self):
        # K_HAUL is set so that the baseline is 926.4 kt/yr (FY2025 ore mined 926 422 t).
        self.assertWithin(self.base.capacity_ktpa["haulage"], 926.4, 0.1)
        self.assertEqual(self.base.haulage.trucks_by_decline, {"tu1": 1, "tu2": 4})
        self.assertEqual(self.base.haulage.centroid_m, 75)

    def test_depth_effect(self):
        expected = {75: 926, 25: 840, -25: 769, -75: 709}
        values = []
        for z, want in expected.items():
            value = self.evaluate(centroid_m=z).capacity_ktpa["haulage"]
            values.append(value)
            with self.subTest(centroid_m=z):
                self.assertWithin(value, want, 1.0, f"haulage at {z} m:")
        losses = [100 * (1 - low / high) for high, low in zip(values, values[1:])]
        self.assertAlmostEqual(sum(losses) / len(losses), 8.5, delta=0.5)  # about 8.5 % per 50 m


class TestCalibration(ModelCase):
    """Spec 2.9: analytic checks C1, C2, C4-C7, C9, C10, C12."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.rows = cap.calibration_checks(cls.model)

    def rows_of(self, check_id):
        rows = [r for r in self.rows if r.id == check_id]
        self.assertTrue(rows, check_id)
        return rows

    def test_table_holds_the_analytic_checks(self):
        self.assertEqual([r.id for r in self.rows],
                         ["C1", "C2", "C4", "C4", "C5", "C5", "C5", "C5", "C6", "C7", "C9", "C10", "C12"])
        for row in self.rows:
            with self.subTest(check=row.id, case=row.case):
                self.assertTrue(row.ok, f"{row.id} {row.case}: model {row.model:.3f}, reported {row.reported}, "
                                        f"deviation {row.deviation:+.3f} {row.deviation_unit}, {row.tolerance}")

    def gold_check(self, check_id, case, milled_t, grade, reported_oz):
        row = next(r for r in self.rows_of(check_id) if r.case == case)
        self.assertEqual(row.reported, reported_oz)
        self.assertAlmostEqual(row.model, cap.gold_oz(self.model, milled_t, grade))
        self.assertWithin(row.model, reported_oz, 1.5, f"{check_id} {case}:")
        self.assertAlmostEqual(row.deviation, (row.model / reported_oz - 1) * 100)

    def test_c1_gold_fy2025(self):
        self.gold_check("C1", "FY2025", 966592, 2.05, 53852)

    def test_c2_gold_fy2024(self):
        self.gold_check("C2", "FY2024", 593612, 2.29, 37279)

    def test_c4_gold_half_years(self):
        self.gold_check("C4", "H1 2026", 498331, 1.76, 23906)
        self.gold_check("C4", "H1 2025", 452593, 2.04, 25081)

    def test_c5_recovery_model(self):
        reported = {2.29: 85.42, 2.05: 85.07, 2.04: 84.75, 1.76: 84.55}
        rows = self.rows_of("C5")
        self.assertEqual(len(rows), len(reported))
        for (grade, want), row in zip(reported.items(), rows):
            with self.subTest(grade=grade):
                self.assertEqual(row.reported, want)
                self.assertEqual(row.deviation_unit, "points")
                self.assertAlmostEqual(cap.recovery_pct(self.model, grade), 81.616 + 1.637 * grade)
                self.assertAlmostEqual(cap.recovery_pct(self.model, grade), want, delta=0.25)

    def test_recovery_is_clamped(self):
        self.assertEqual(cap.recovery_pct(self.model, 10.0), 88)
        self.assertAlmostEqual(cap.recovery_pct(self.model, 3.8), 81.616 + 1.637 * 3.8)  # just under the cap
        # The intercept is above the lower limit, so no positive grade reaches the 80 % floor.
        self.assertAlmostEqual(cap.recovery_pct(self.model, 0.1), 81.616 + 1.637 * 0.1)
        self.assertGreaterEqual(cap.recovery_pct(self.model, 0.0), 80)

    def test_c6_air_demand_of_baseline_fleet(self):
        (row,) = self.rows_of("C6")
        self.assertEqual(row.reported, 322)
        self.assertAlmostEqual(row.model, 317.22, places=2)  # 180 + 0.06 x 2287 kW
        self.assertAlmostEqual(row.model, self.base.air.demand_m3s)
        self.assertTrue(0.95 * 322 <= row.model <= 322)

    def test_c7_air_demand_at_half_fleet_power(self):
        (row,) = self.rows_of("C7")
        self.assertEqual(row.reported, 252)
        self.assertAlmostEqual(row.model, 180 + 0.06 * self.base.air.fleet_kw / 2)
        self.assertWithin(row.model, 252, 3.0, "C7:")

    def test_c9_pond_sludge(self):
        (row,) = self.rows_of("C9")
        self.assertEqual(row.reported, 64.3)
        self.assertAlmostEqual(row.model, 197 * 8760 * 39.563 * 0.949 / 1e6)
        self.assertWithin(row.model, 64.3, 2.0, "C9:")

    def test_c10_water_demand_at_nameplate(self):
        (row,) = self.rows_of("C10")
        self.assertEqual(row.reported, 1725.72)
        self.assertAlmostEqual(row.model, (0.603 + 1.123) * 1000)
        self.assertWithin(row.model, 1725.72, 0.5, "C10:")

    def test_c12_gold_at_two_million_tonnes(self):
        (row,) = self.rows_of("C12")
        self.assertAlmostEqual(row.model, cap.gold_oz(self.model, 2_000_000, 2.05))
        self.assertGreater(row.model, 100_000)
        # the full measure set for 2.0 Mtpa reaches that throughput
        res = self.evaluate(**FULL_2000)
        self.assertEqual(res.capacity_rounded[res.binding_link], 2000)
        self.assertGreater(res.gold.oz_per_year, 100_000)


class TestBindingRule(ModelCase):
    """Spec 3.4 steps 1-3: rounding, tie-break, next measure."""

    def test_baseline_binds_on_haulage(self):
        self.assertEqual(self.base.binding_link, "haulage")
        self.assertEqual(self.base.capacity_rounded["haulage"], 926)
        self.assertAlmostEqual(self.base.achievable_ktpa, min(self.base.capacity_ktpa.values()))

    def test_ties_follow_the_link_order(self):
        even = {link: 1000.0 for link in cap.LINKS}
        self.assertEqual(cap.binding_link(even), "haulage")
        self.assertEqual(cap.binding_link(dict(even, haulage=1200.0, ventilation=1200.0)), "stopes")
        # plant 1000 and water 999.84 are equal after rounding: plant comes first
        self.assertEqual(cap.binding_link(dict(even, haulage=1386.0, ventilation=1036.0, stopes=1024.0,
                                               development=1750.0, dewatering=math.inf, water=999.84,
                                               tailings=1057.0)), "plant")
        self.assertEqual(cap.binding_link(dict(even, dewatering=999.4)), "dewatering")
        self.assertEqual(cap.binding_link(dict(even, dewatering=999.5)), "haulage")

    def test_rounding_is_half_up_and_keeps_not_limiting(self):
        self.assertEqual(cap.round_kt(999.5), 1000)
        self.assertEqual(cap.round_kt(1000.5), 1001)
        self.assertEqual(cap.round_kt(999.49), 999)
        self.assertIsNone(cap.round_kt(math.inf))

    def test_next_measure(self):
        state = cap.State()
        knob, after = cap.next_measure(self.model, state, "haulage")
        self.assertEqual((knob, after.m_haul), ("m_haul", 1))
        self.assertEqual(state.m_haul, 0)  # states are immutable
        self.assertIsNone(cap.next_measure(self.model, state, "dewatering"))
        self.assertIsNone(cap.next_measure(self.model, cap.State(m_haul=3), "haulage"))
        self.assertEqual({k: cap.knob_max(self.model, k) for k in cap.KNOBS},
                         {"m_haul": 3, "m_vent": 2, "m_stopes": 3, "m_dev": 1, "m_plant": 3, "m_water": 2,
                          "m_tailings": 1})
        self.assertEqual(set(cap.MEASURE_KNOBS), set(cap.LINKS) - {"dewatering"})


class TestBottleneckSequences(ModelCase):
    """Spec 3.4: expected sequences of binding links from the baseline.

    The loop below is steps 1-3 of the advisor algorithm written with the library alone; the
    advisor package has its own implementation and its own tests.
    """

    FIRST_SIX = ["haulage", "plant", "water", "stopes", "ventilation", "tailings"]
    NEXT_SIX = ["plant", "stopes", "ventilation", "haulage", "water", "development"]
    LAST_THREE = ["plant", "stopes", "haulage"]

    def ladder(self, target):
        state = cap.State()
        links = []
        for _ in range(sum(cap.knob_max(self.model, k) for k in cap.KNOBS) + 1):
            res = cap.evaluate(self.model, state)
            if res.capacity_rounded[res.binding_link] >= target:
                break
            links.append(res.binding_link)
            step = cap.next_measure(self.model, state, res.binding_link)
            if step is None:
                break
            state = step[1]
        return links, res

    def check(self, target, sequence, gold_koz):
        links, res = self.ladder(target)
        self.assertEqual(links, sequence)
        self.assertEqual(res.binding_link, "plant")
        self.assertEqual(res.capacity_rounded["plant"], target)
        self.assertAlmostEqual(res.gold.oz_per_year / 1000, gold_koz, delta=0.05)
        return res

    def test_target_1000(self):
        self.check(1000, ["haulage"], 56.0)

    def test_target_1200(self):
        res = self.check(1200, self.FIRST_SIX, 67.2)
        self.assertEqual(res.state, cap.State(**FULL_1200))

    def test_target_2000(self):
        res = self.check(2000, self.FIRST_SIX + self.NEXT_SIX, 112.0)
        self.assertEqual(res.state, cap.State(**FULL_2000))

    def test_target_2500(self):
        res = self.check(2500, self.FIRST_SIX + self.NEXT_SIX + self.LAST_THREE, 140.0)
        self.assertEqual(res.state, cap.State(**FULL_2500))

    def test_sustainable_baseline(self):
        self.assertWithin(self.base.achievable_ktpa, 926, 1.0)
        self.assertAlmostEqual(self.base.gold.oz_per_year / 1000, 51.9, delta=0.1)
        days = cap.stockpile_days_left(self.model, 36000, self.base.achievable_ktpa, 1000)
        self.assertAlmostEqual(days, 216, delta=3)  # "about 216 days"
        self.assertTrue(math.isinf(cap.stockpile_days_left(self.model, 36000, 1000, 1000)))


class TestScenarioEffects(ModelCase):
    """Spec 3.3: the panel values that follow from the analytic model."""

    def test_step1200_alone(self):
        res = self.evaluate(m_plant=1)
        self.assertEqual(res.capacity_rounded["plant"], 1200)
        self.assertEqual(res.binding_link, "haulage")
        self.assertEqual(res.capacity_rounded["haulage"], 926)
        self.assertAlmostEqual(res.gold.oz_per_year, self.base.gold.oz_per_year)  # gold gain 0

    def test_haulage_measure(self):
        res = self.evaluate(m_plant=1, m_haul=1)
        self.assertWithin(res.capacity_ktpa["haulage"], 1386, 1.0)
        self.assertEqual([c.truck for c in res.haulage.cycles], [f"truck-{n:02d}" for n in range(1, 8)])
        self.assertEqual(res.haulage.trucks_by_decline, {"tu1": 3, "tu2": 4})
        self.assertGreater(res.air.demand_m3s, self.base.air.demand_m3s)

    def test_ventilation_and_stope_measures(self):
        before = self.evaluate(m_plant=1, m_haul=1, m_water=1, m_stopes=1)
        self.assertEqual(before.binding_link, "ventilation")
        self.assertWithin(before.capacity_ktpa["stopes"], 1279, 1.0)
        self.assertEqual((before.stopes.n_producing, before.stopes.lhds, before.stopes.rigs), (5, 5, 3))
        after = self.evaluate(m_plant=1, m_haul=1, m_water=1, m_stopes=1, m_vent=1)
        self.assertEqual(after.air.fans_running, ("fan-vs1", "fan-ug-p320", "fan-vs2", "fan-vpv"))
        self.assertEqual(after.air.supply_m3s, 427)
        self.assertWithin(after.capacity_ktpa["ventilation"], 1665, 1.0)

    def test_water_and_tailings_measures(self):
        self.assertWithin(self.evaluate(m_water=1).capacity_ktpa["water"], 1533, 1.0)
        self.assertWithin(self.evaluate(m_water=2).capacity_ktpa["water"], 2700, 1.0)
        built = self.evaluate(m_tailings=1)
        self.assertWithin(built.capacity_ktpa["tailings"], 3057, 1.0)
        self.assertEqual([d.state for d in built.tailings.dams], ["active", "standby", "standby", "standby"])
        self.assertEqual([d.state for d in self.base.tailings.dams], ["active", "standby", "standby", "planned"])
        self.assertGreater(built.tailings.years_left, self.base.tailings.years_left)

    def test_close_tu2(self):
        res = self.evaluate(tu2_closed=True)
        self.assertWithin(res.capacity_ktpa["haulage"], 833, 1.0)
        self.assertEqual(res.haulage.trucks_by_decline, {"tu1": 5, "tu2": 0})
        self.assertTrue(all(c.decline == "tu1" for c in res.haulage.cycles))
        fall = 1 - res.capacity_ktpa["haulage"] / self.base.capacity_ktpa["haulage"]
        self.assertAlmostEqual(fall, 0.10, delta=0.02)  # "falls about 10 %"

    def test_close_tu1(self):
        res = self.evaluate(tu1_closed=True)
        self.assertEqual(res.haulage.trucks_by_decline, {"tu1": 0, "tu2": 5})
        self.assertLess(res.capacity_ktpa["haulage"], self.base.capacity_ktpa["haulage"])

    def test_fan_vs2_failure(self):
        res = self.evaluate(fan_vs2_off=True)
        self.assertEqual(res.air.supply_m3s, 252)
        self.assertNotIn("fan-vs2", res.air.fans_running)
        self.assertWithin(res.capacity_ktpa["ventilation"], 486, 1.0)
        self.assertEqual(res.binding_link, "ventilation")
        self.assertLess(res.air.margin_pct, 0)
        self.assertAlmostEqual(res.air.demand_m3s, self.base.air.demand_m3s)

    def test_one_pump_failed_changes_no_bar(self):
        res = self.evaluate(pumps_failed_p150=1)
        self.assertEqual(res.capacity_rounded, self.base.capacity_rounded)
        self.assertEqual(res.dewatering.margin, self.base.dewatering.margin)
        self.assertAlmostEqual(self.base.dewatering.margin, 600 / (197 * 24 / 20))

    def test_pump_station_failure_binds_when_a_production_level_floods(self):
        failed = self.evaluate(pumps_failed_p150=3)
        self.assertEqual(failed.dewatering.margin, 0)
        self.assertAlmostEqual(failed.dewatering.flood_rate_m3h, 197)
        self.assertFalse(failed.dewatering.limiting)
        self.assertEqual(failed.binding_link, "haulage")
        lower = self.evaluate(pumps_failed_p150=3, flooded_levels=("lvl-m050",))
        self.assertTrue(lower.dewatering.limiting)
        self.assertEqual(lower.binding_link, "haulage")  # no producing stope on the -50 m level
        self.assertEqual(lower.capacity_rounded["dewatering"], lower.capacity_rounded["stopes"])
        flooded = self.evaluate(pumps_failed_p150=3, flooded_levels=("kz.sekis:lvl-m050", "lvl-000"))
        self.assertEqual(flooded.binding_link, "dewatering")
        self.assertAlmostEqual(flooded.capacity_ktpa["dewatering"], 3 * 255.875)
        self.assertAlmostEqual(flooded.capacity_ktpa["stopes"], 4 * 255.875)  # the stopes row keeps its value

    def test_flood_inflow(self):
        res = self.evaluate(inflow_factor=2.18)
        self.assertWithin(res.dewatering.inflow_m3h, 430, 0.5)
        self.assertEqual(res.dewatering.flood_rate_m3h, 0)  # the pumps carry the design inflow
        self.assertGreater(res.dewatering.margin, 1)
        self.assertEqual(res.capacity_rounded, self.base.capacity_rounded)
        self.assertEqual(res.water.permit_state, "exceeded")
        self.assertEqual(res.water.state, "discharge_over_permit")
        # the live value of the spec: the mine hoists 926 kt/yr while the plant mills 1000 kt/yr
        live = cap.water_balance(self.model, self.tph(926.4), self.tph(1000), res.dewatering.pumped_m3h)
        self.assertWithin(live.discharge_m3h, 238, 1.0)
        self.assertGreater(live.permit_use_pct, 100)

    def test_grade_drop(self):
        self.assertAlmostEqual(cap.gold_oz(self.model, 1_000_000, 2.05) / 1000, 56.0, delta=0.05)
        self.assertAlmostEqual(cap.gold_oz(self.model, 1_000_000, 1.76) / 1000, 47.8, delta=0.05)
        res = self.evaluate(grade_gpt=1.76)
        self.assertEqual(res.capacity_rounded, self.base.capacity_rounded)
        self.assertAlmostEqual(res.gold.recovery_pct, 81.616 + 1.637 * 1.76)
        self.assertLess(res.gold.oz_per_year, self.base.gold.oz_per_year)
        self.assertAlmostEqual(res.stopes.mean_grade_gpt, 1.76)  # stope grades scale with the feed grade
        self.assertAlmostEqual(self.base.stopes.mean_grade_gpt, 2.05)

    def test_line_2_down(self):
        res = self.evaluate(line_down=2)
        self.assertEqual(res.capacity_rounded["plant"], 667)
        self.assertEqual(res.binding_link, "plant")
        self.assertEqual([line.state for line in res.plant.lines],
                         ["running", "off", "running", "planned", "planned", "planned"])


class TestLadders(ModelCase):
    """Spec 3.1: the measure ladders agree with the parameters of spec 2.8 and with the registry."""

    def test_trucks_stopes_lhds_rigs(self):
        p = self.model.p
        self.assertEqual(p("ladder.m_haul.trucks"), [5, 7, 10, 12])
        self.assertEqual(p("ladder.m_stopes.producing"), [4, 5, 8, 10])
        self.assertEqual(p("ladder.m_stopes.lhds"), [4, 5, 8, 10])
        self.assertEqual(p("ladder.m_stopes.rigs"), [2, 3, 4, 5])
        self.assertEqual(p("ladder.m_haul.trucks")[0], p("fleet.base.trucks_ad30") + p("fleet.base.trucks_ad45"))
        self.assertEqual(p("ladder.m_stopes.producing")[0], p("stope.producing_base"))
        self.assertEqual(p("ladder.m_stopes.lhds")[0], p("fleet.base.lhd_r1300") + p("fleet.base.lhd_r1700"))
        self.assertEqual(p("ladder.m_stopes.rigs")[0], p("fleet.base.rigs"))
        for producing, lhds, rigs in zip(p("ladder.m_stopes.producing"), p("ladder.m_stopes.lhds"),
                                         p("ladder.m_stopes.rigs")):
            self.assertLessEqual(producing, lhds)
            self.assertLessEqual(producing, p("stope.stopes_per_rig") * rigs)

    def test_ventilation_totals(self):
        totals = [cap.air_supply_m3s(self.model, fans) for fans in self.model.p("ladder.m_vent.fans")]
        self.assertEqual(totals, [322, 427, 667])
        p = self.model.p
        self.assertEqual(totals[0], p("vent.supply_base"))
        self.assertEqual(totals[1] - totals[0], p("vent.measure_V1.delta_m3s"))
        self.assertEqual(totals[2] - totals[1], p("vent.measure_V2.delta_m3s"))
        self.assertEqual(totals[0] - self.model.fans["fan-vs2"].duty_m3s, p("vent.supply_2022"))

    def test_plant_stages_and_line_rates(self):
        p = self.model.p
        self.assertEqual(p("ladder.m_plant.capacity_ktpa"), [p("plant.nameplate_ktpa")] + p("plant.stages_ktpa"))
        self.assertEqual(p("ladder.m_plant.lines"), [3, 3, 5, 6])
        self.assertEqual(p("ladder.m_plant.lines")[0], p("plant.lines"))
        rates = {0: [41.36] * 3, 1: [49.63] * 3, 2: [49.63] * 5, 3: [49.63] * 5 + [62.04]}
        for stage, want in rates.items():
            mill = cap.plant(self.model, stage)
            running = [line for line in mill.lines if line.state == "running"]
            self.assertEqual([round(line.rated_tph, 2) for line in running], want)
            self.assertAlmostEqual(mill.capacity_ktpa, p("ladder.m_plant.capacity_ktpa")[stage])
            for line in running:  # rate x availability x hours of the year is the annual capacity
                self.assertAlmostEqual(line.rated_tph * p("plant.availability") * 8760 / 1000, line.capacity_ktpa)
        full = cap.plant(self.model, 3).lines
        self.assertEqual([line.capacity_ktpa for line in full[3:]],
                         [p("plant.line45_ktpa"), p("plant.line45_ktpa"), p("plant.line6_ktpa")])

    def test_development_water_tailings(self):
        p = self.model.p
        self.assertEqual(p("ladder.m_dev.advance_vm_per_year"), [p("dev.advance_vm_per_year"), p("dev.advance_boosted")])
        w1 = p("water.measure_W1.reclaim_m3_per_t")
        self.assertEqual(p("ladder.m_water.reclaim_m3_per_t"), [0, w1, w1])
        self.assertEqual(p("ladder.m_water.extra_intake_m3h"), [0, 0, p("water.measure_W2.extra_intake_m3h")])
        self.assertEqual(p("ladder.m_tailings.dams"),
                         [["tsf-dam4", "tsf-dam2", "tsf-dam3"], ["tsf-dam4", "tsf-dam2", "tsf-dam3", "tsf-cell5"]])
        free0 = p("tsf.dam4_capacity_t") * (1 - p("tsf.dam4_fill_start")) + 2 * p("tsf.dam23_free_t")
        self.assertAlmostEqual(cap.tailings(self.model, 0).free_t, free0)
        self.assertAlmostEqual(cap.tailings(self.model, 1).free_t, free0 + p("tsf.measure_X1_t"))

    def test_activation_order_of_stopes(self):
        names = [s.name for s in self.model.stopes]
        self.assertEqual(names[:5], ["stp-p150-1", "stp-p100-1", "stp-p050-1", "stp-000-1", "stp-p150-2"])
        self.assertEqual(names[8:12], ["stp-p150-3", "stp-p100-3", "stp-p050-3", "stp-000-3"])
        self.assertEqual(names[12:], ["stp-m050-1", "stp-m050-2", "stp-m050-3"])
        self.assertEqual(self.base.stopes.producing, tuple(names[:4]))


class TestFormulas(ModelCase):
    """Spec 2.3-2.7: the single formulas against values worked out by hand."""

    def test_haul_cycle_of_the_baseline_ad45(self):
        (cycle,) = [c for c in self.base.haulage.cycles if c.truck == "truck-05"]
        length = (430 - 75) / math.sin(math.radians(8)) * 1.15 / 1000
        self.assertAlmostEqual(cycle.ramp_km, length)
        self.assertAlmostEqual(length, (430 - 75) * 7.185 * 1.15 / 1000, places=3)
        minutes = 5 + 1.5 + 1.5 + 60 * length / 9 + 60 * length / 16 + 60 * 0.8 / 15 + 60 * 0.8 / 20
        self.assertAlmostEqual(cycle.cycle_min, minutes)
        self.assertEqual(cycle.bay_min, 0)
        self.assertAlmostEqual(cycle.capacity_ktpa, 45 * 60 / minutes * 7920 * (8.5 / 11) * 0.80
                               * self.model.p("haul.K_HAUL") / 1000)
        (ad30, *_) = self.base.haulage.cycles
        self.assertEqual((ad30.decline, ad30.trucks_on_decline), ("tu2", 4))
        self.assertAlmostEqual(ad30.bay_min, 0.75 * 3)
        self.assertAlmostEqual(sum(c.capacity_ktpa for c in self.base.haulage.cycles),
                               self.base.capacity_ktpa["haulage"])

    def test_stopes_and_development(self):
        self.assertAlmostEqual(self.base.stopes.per_stope_ktpa, 255.875)
        self.assertAlmostEqual(self.base.capacity_ktpa["development"], 34 * 51462 / 1000)
        self.assertEqual(self.base.dev_advance_vm_per_year, 34)
        self.assertAlmostEqual(cap.centroid_after(self.model, 75, 926400), 75 - 926400 / 51462)
        # fewer rigs or LHDs in service than the producing set needs cut the capacity
        self.assertEqual(self.evaluate(active_rigs=1).stopes.n_producing, 2)
        self.assertEqual(self.evaluate(active_lhds=("lhd-01", "lhd-02", "lhd-03")).stopes.n_producing, 3)

    def test_ventilation(self):
        air = self.base.air
        self.assertEqual(air.supply_m3s, 322)
        self.assertEqual(air.fleet_kw, 4 * 304 + 439 + 3 * 123 + 263)
        self.assertAlmostEqual(air.allowed_kw, (322 - 180) / 0.06)
        self.assertAlmostEqual(air.capacity_ktpa, air.allowed_kw * self.base.capacity_ktpa["haulage"] / air.fleet_kw)
        self.assertAlmostEqual(air.margin_pct, (322 - 317.22) / 322 * 100)
        self.assertAlmostEqual(cap.fan_power_kw(self.model, 150, 2500), 500.0)
        split = cap.level_air(self.model, 322, {"lvl-p150": 439, "lvl-000": 123})
        self.assertEqual(len(split), 8)  # the levels that are not planned
        self.assertAlmostEqual(sum(v.flow_m3s for v in split.values()), 322)
        self.assertAlmostEqual(split["lvl-p150"].required_m3s, 180 / 8 + 0.06 * 439)
        self.assertAlmostEqual(split["lvl-p100"].required_m3s, 180 / 8)
        # held units lower the demand: the simulator passes the units it lets work
        fewer = self.evaluate(active_trucks=("truck-01", "truck-05"), active_lhds=("lhd-04",))
        self.assertAlmostEqual(fewer.air.demand_m3s, 180 + 0.06 * (304 + 439 + 263))

    def test_water_and_ponds(self):
        self.assertAlmostEqual(self.base.capacity_ktpa["water"], 1725.72 / (0.603 + 1.123))
        self.assertAlmostEqual(self.evaluate(m_water=2).capacity_ktpa["water"],
                               (1725.72 + 8.76 * 150) / (0.603 + 1.123 - 0.6))
        short = cap.water_balance(self.model, self.tph(1200), self.tph(1200), 197)
        self.assertAlmostEqual(short.demand_m3h, 1.726 * self.tph(1200))
        self.assertAlmostEqual(short.deficit_m3h, short.demand_m3h - 197)
        self.assertEqual((short.state, short.discharge_m3h, short.extra_intake_m3h), ("deficit", 0, 0))
        self.assertAlmostEqual(short.feed_limit_tph, (197 - 0.603 * self.tph(1200)) / 1.123)
        reclaim = cap.water_balance(self.model, self.tph(1200), self.tph(1200), 197, m_water=1)
        self.assertAlmostEqual(reclaim.reclaim_m3h, 0.6 * self.tph(1200))
        self.assertEqual(reclaim.deficit_m3h, 0)
        intake = cap.water_balance(self.model, self.tph(2000), self.tph(2000), 197, m_water=2)
        self.assertEqual(intake.deficit_m3h, 0)
        self.assertGreater(intake.extra_intake_m3h, 0)
        self.assertLess(intake.extra_intake_m3h, 150)  # only what is missing is taken
        calm = cap.water_balance(self.model, self.tph(926.4), self.tph(1000), 197)
        self.assertEqual((calm.state, calm.permit_state), ("balanced", "normal"))
        self.assertAlmostEqual(calm.permit_use_pct, calm.discharge_m3h / 218.8 * 100)
        ponds = cap.pond_treatment(self.model, 197)
        self.assertEqual(len(ponds.retention_h), 2)
        self.assertAlmostEqual(ponds.retention_h[0], 2265 / 197)
        self.assertAlmostEqual(ponds.tss_out_mgl, 39.563 * (1 - 0.949))
        fast = cap.pond_treatment(self.model, 4530 / 3)  # 3 h of retention: half of the settling time
        self.assertAlmostEqual(fast.tss_out_mgl, 39.563 * (1 - 0.949 * 0.5))
        self.assertAlmostEqual(cap.pump_power_kw(self.model, 300, 280),
                               1000 * 9.81 * 300 / 3600 * 280 * 1.1 / 0.70 / 1000)

    def test_dewatering_cascade(self):
        dw = self.base.dewatering
        self.assertAlmostEqual(dw.inflow_upper_m3h + dw.inflow_lower_m3h, 197)
        self.assertAlmostEqual(dw.inflow_upper_m3h, 0.6 * 197)
        self.assertEqual((dw.capacity_main_m3h, dw.capacity_lower_m3h), (600, 300))
        self.assertAlmostEqual(dw.pumped_m3h, 197)
        design = self.evaluate(inflow_factor=430 / 197).dewatering
        self.assertAlmostEqual(design.margin, 600 / 516)  # two pumps clear the design inflow in 20 h
        two_failed = self.evaluate(pumps_failed_p150=2).dewatering
        self.assertEqual(two_failed.capacity_main_m3h, 300)
        self.assertEqual(two_failed.flood_rate_m3h, 0)
        self.assertEqual(self.evaluate(pumps_failed_p150=2, inflow_factor=2.18).dewatering.pumped_m3h, 300)

    def test_tailings_fill_order_and_years(self):
        base = self.base.tailings
        self.assertEqual(base.active_dam, "tsf-dam4")
        self.assertAlmostEqual(base.free_t, 3172095)
        self.assertAlmostEqual(base.capacity_ktpa, 3172.095 / 3.0)
        self.assertAlmostEqual(base.years_left, 3172.095 / self.base.achievable_ktpa)
        self.assertEqual(base.state, "ok")
        later = cap.tailings(self.model, 0, placed_t=400000, rate_ktpa=1000)
        self.assertEqual([(d.name, d.state) for d in later.dams][:3],
                         [("tsf-dam4", "full"), ("tsf-dam2", "active"), ("tsf-dam3", "standby")])
        self.assertAlmostEqual(later.free_t, 3172095 - 400000)
        self.assertEqual(later.state, "short_horizon")  # 2.77 years at 1000 kt/yr
        full = cap.tailings(self.model, 0, placed_t=4_000_000, rate_ktpa=1000)
        self.assertEqual((full.state, full.free_t, full.active_dam), ("full", 0, None))
        self.assertAlmostEqual(full.overflow_t, 4_000_000 - 3172095)
        self.assertEqual(self.evaluate(tailings_placed_t=4_000_000).capacity_rounded["tailings"], 0)
        with_cell = cap.tailings(self.model, 1, placed_t=3172095 + 1, rate_ktpa=1000)
        self.assertEqual(with_cell.active_dam, "tsf-cell5")


class TestStateAndApi(ModelCase):
    def test_from_knobs_reads_the_scenario_thing(self):
        registry = json.loads((TEAM / "model" / "registry.json").read_text(encoding="utf-8"))
        (scenario,) = [t for t in registry["things"] if t["thingId"] == "kz.sekis:scenario"]
        self.assertEqual(cap.State.from_knobs(scenario["features"]), cap.State(grade_gpt=2.05))
        state = cap.State.from_knobs({"m_haul": 2.0, "tu2_closed": 1.0, "inflow_factor": 2.18, "line_down": 2.0,
                                      "target_ktpa": 2000.0, "revision": 7.0, "label": "x"}, centroid_m=40.0)
        self.assertEqual(state, cap.State(m_haul=2, tu2_closed=True, inflow_factor=2.18, line_down=2,
                                          centroid_m=40.0))
        self.assertIs(type(state.m_haul), int)
        self.assertIs(type(state.tu2_closed), bool)

    def test_default_state_is_the_baseline(self):
        explicit = cap.evaluate(self.model, cap.State(grade_gpt=2.05, centroid_m=75.0))
        self.assertEqual(explicit.capacity_ktpa, self.base.capacity_ktpa)
        self.assertEqual(explicit.gold.oz_per_year, self.base.gold.oz_per_year)

    def test_invalid_states_are_rejected(self):
        bad = [dict(tu1_closed=True, tu2_closed=True), dict(m_haul=4), dict(m_vent=-1), dict(m_dev=2),
               dict(m_haul=1.0), dict(pumps_failed_p150=4), dict(line_down=4), dict(m_plant=2, line_down=6),
               dict(inflow_factor=-1.0), dict(grade_gpt=0.0), dict(tailings_placed_t=-1.0),
               dict(active_trucks=("truck-99",)), dict(flooded_levels=("lvl-p999",)),
               dict(producing_set=("stp-m100-1",))]
        for changes in bad:
            with self.subTest(**changes):
                with self.assertRaises(ValueError):
                    self.evaluate(**changes)
        self.evaluate(m_plant=2, line_down=5)  # a built line may be stopped

    def test_result_is_json_ready(self):
        text = json.dumps(self.base.to_dict(), allow_nan=False)
        data = json.loads(text)
        self.assertIsNone(data["capacity_ktpa"]["dewatering"])
        self.assertEqual(data["binding_link"], "haulage")
        self.assertEqual(len(data["haulage"]["cycles"]), 5)

    def test_public_names_exist(self):
        for name in cap.__all__:
            self.assertTrue(hasattr(cap, name), name)


class TestLibrarySource(unittest.TestCase):
    """Spec 0.3: a parameter enters code only through params.json."""

    ALLOWED = {0, 1, 0.5}  # neutral elements, indices and the half of half-up rounding

    @classmethod
    def setUpClass(cls):
        cls.source = LIBRARY.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)
        cls.params = json.loads(PARAMS.read_text(encoding="utf-8"))

    def test_no_model_number_in_the_library(self):
        conversions = set()
        for node in self.tree.body:  # module-level UPPER_CASE = number: unit conversions
            if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
                    and all(isinstance(t, ast.Name) and t.id.isupper() for t in node.targets)):
                conversions.add(id(node.value))
        found = []
        for node in ast.walk(self.tree):
            if (isinstance(node, ast.Constant) and isinstance(node.value, (int, float))
                    and not isinstance(node.value, bool) and id(node) not in conversions
                    and node.value not in self.ALLOWED):
                found.append((node.lineno, node.value))
        self.assertEqual(found, [], "numeric literals in capacity.py (line, value)")

    def test_unit_conversions_are_only_conversions(self):
        constants = {node.targets[0].id: node.value.value for node in self.tree.body
                     if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
                     and isinstance(node.value.value, (int, float)) and not isinstance(node.value.value, bool)}
        self.assertEqual(constants, {"HOURS_PER_DAY": 24.0, "MINUTES_PER_HOUR": 60.0, "SECONDS_PER_HOUR": 3600.0,
                                     "KILO": 1000.0, "PERCENT": 100.0, "GRAMS_PER_TONNE": 1.0e6})

    def test_every_parameter_id_used_exists(self):
        ids = set(re.findall(r'"((?:[a-z0-9_]+\.)+[A-Za-z0-9_]+)"', self.source))
        ids = {i for i in ids if i.split(".")[0] in {pid.split(".")[0] for pid in self.params}}
        self.assertGreater(len(ids), 50)
        # an id is a parameter, or the stem of ids completed in an f-string ("calib.c1" + ".milled_t")
        missing = sorted(i for i in ids
                         if i not in self.params and not any(pid.startswith(i + ".") for pid in self.params))
        self.assertEqual(missing, [])

    def test_standard_library_only(self):
        imported = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module.split(".")[0])
        self.assertLessEqual(imported, {"__future__", "json", "math", "dataclasses", "pathlib", "typing"})

    def test_files_utf8_lf_no_bom(self):
        for path in (LIBRARY, Path(__file__), PARAMS):
            raw = path.read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), path.name)
            self.assertNotIn(b"\r", raw, path.name)
            raw.decode("utf-8")
            self.assertTrue(raw.endswith(b"\n"), path.name)


if __name__ == "__main__":
    unittest.main()
