"""Tests for the Expansion Advisor (team/sekis/advisor/), spec 3.4.

Covers the constraint loop and the four bottleneck sequences, the ten-year projection, the
scenario effects of spec 3.3 as the report shows them, the action ``/apply``, the Russian
effects list, the service loop with a fake source, publisher and clock, the HTTP interface on
a free port against a fixture state, the Ditto-protocol message for ``kz.sekis:advisor``, and
the service as a process in fixture mode. Expected numbers are those of the spec.
"""

import ast
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from dataclasses import replace
from pathlib import Path

TEAM = Path(__file__).resolve().parent.parent
if str(TEAM) not in sys.path:
    sys.path.insert(0, str(TEAM))

from sekis import capacity as cap  # noqa: E402
from sekis.advisor import Advisor, engine, service, wording  # noqa: E402

PACKAGE = TEAM / "sekis" / "advisor"
REGISTRY = TEAM / "model" / "registry.json"

# Sequences of binding links from the baseline (spec 3.4).
FIRST_SIX = ["haulage", "ventilation", "plant", "water", "stopes", "tailings"]
NEXT_SIX = ["plant", "stopes", "ventilation", "haulage", "water", "development"]
LAST_THREE = ["plant", "stopes", "haulage"]
SEQUENCES = {1000: ["haulage", "ventilation"], 1200: FIRST_SIX, 2000: FIRST_SIX + NEXT_SIX,
             2500: FIRST_SIX + NEXT_SIX + LAST_THREE}
GOLD_KOZ = {1000: 56.0, 1200: 67.2, 2000: 112.0, 2500: 140.0}
# Full measure sets and their air demand (spec 2.3).
FULL = {
    1000: dict(m_haul=1, m_vent=1),
    1200: dict(m_haul=1, m_stopes=1, m_vent=1, m_plant=1, m_water=1, m_tailings=1),
    2000: dict(m_haul=2, m_stopes=2, m_vent=2, m_plant=2, m_water=2, m_tailings=1, m_dev=1),
    2500: dict(m_haul=3, m_stopes=3, m_vent=2, m_plant=3, m_water=2, m_tailings=1, m_dev=1),
}
AIR_DEMAND = {1200: 385.7, 2000: 512.0, 2500: 596.3}
BASELINE_KTPA, BASELINE_GOLD_KOZ = 926, 51.9

REPORT_KEYS = {
    "schema", "report_revision", "label", "sim_time", "knobs", "target_ktpa", "achievable_ktpa",
    "achievable_exact_ktpa", "binding_link", "binding_link_name", "target_reached", "links", "next_measure",
    "measures_needed", "sequence", "sequence_outcome", "conditions", "kpi", "sustainable_baseline", "ladder",
    "projection", "effects", "calibration",
}
STEP_KEYS = {"kind", "link", "link_name", "measure", "knob", "from_stage", "to_stage", "set", "text",
             "cap_before_ktpa", "cap_after_ktpa"}
KPI_KEYS = {
    "gold_koz_year", "gold_gain_koz_year", "grade_gpt", "recovery_pct", "air_demand_m3s", "air_supply_m3s",
    "air_margin_pct", "air_used_m3s", "air_spare_m3s", "units_held_vent", "water_deficit_m3h", "discharge_m3h", "permit_m3h", "permit_use_pct", "tailings_free_kt",
    "tailings_years_left", "stockpile_t", "stockpile_days_left", "stockpile_mine_tpd", "stockpile_plant_tpd",
    "stockpile_net_tpd", "stockpile_trend", "dewatering_margin",
}
# The opening ROM stockpile (params.json stockpile.start_t, derivation in its source) and the days it
# lasts at the baseline draw: 1000 kt/yr over 365 days less 926.1 kt/yr over 360 days = 167 t/day.
STOCKPILE_T, STOCKPILE_DAYS = 94264, 564
CALIBRATION_ROW_KEYS = {
    "id", "case", "title", "kind", "kind_name", "basis", "basis_name", "basis_note", "unit", "reported",
    "reported_max", "model", "deviation", "deviation_unit", "tolerance", "passed", "source", "source_urls",
}
CYRILLIC = re.compile("[а-яё]")
LATIN = re.compile("[A-Za-z]")


class AdvisorCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.advisor = Advisor()
        cls.base = cls.advisor.default_inputs()

    def inputs(self, revision=1, label="проверка", **knobs):
        return replace(self.base.with_knobs(knobs), revision=revision, label=label)

    def report(self, before=None, **knobs):
        return self.advisor.report(self.inputs(**knobs), before=before)

    def assertWithin(self, value, expected, pct):
        self.assertAlmostEqual(value, expected, delta=abs(expected) * pct / 100,
                               msg=f"{value} is not within {pct} % of {expected}")


class TestConstraintLoop(AdvisorCase):
    """Spec 3.4 steps 1-4: ranking, tie-break, measures, the ladder for the four targets."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ladder = {row["target_ktpa"]: row for row in cls.advisor.report(cls.base)["ladder"]}

    def test_ladder_has_the_four_targets(self):
        self.assertEqual(list(self.ladder), [1000, 1200, 2000, 2500])

    def test_sequences_of_binding_links(self):
        for target, sequence in SEQUENCES.items():
            row = self.ladder[target]
            self.assertEqual(row["sequence"], sequence, target)
            self.assertEqual([step["link"] for step in row["steps"]], sequence, target)
            self.assertEqual(row["measures_count"], len(sequence))

    def test_achieved_rate_is_the_plant_at_the_target(self):
        for target, row in self.ladder.items():
            self.assertEqual((row["achievable_ktpa"], row["binding_link"], row["reached"]),
                             (target, "plant", True))
            self.assertEqual(row["stop_reason"], "target_reached")
            self.assertEqual(row["capacities"]["plant"], target)

    def test_gold_and_gain_against_the_sustainable_baseline(self):
        for target, koz in GOLD_KOZ.items():
            row = self.ladder[target]
            self.assertAlmostEqual(row["gold_koz_year"], koz, delta=0.05)
            self.assertAlmostEqual(row["gold_gain_koz_year"], koz - BASELINE_GOLD_KOZ, delta=0.1)

    def test_measure_sets_reached(self):
        for target, knobs in FULL.items():
            expected = dict({knob: 0 for knob in cap.KNOBS}, **knobs)
            self.assertEqual(self.ladder[target]["measures"], expected, target)

    def test_ladder_figures(self):
        for target, demand in AIR_DEMAND.items():
            row = self.ladder[target]
            self.assertWithin(row["air_demand_m3s"], demand, 1.0)
            self.assertEqual(row["water_deficit_m3h"], 0.0)
            self.assertGreater(row["tailings_years_left"], 3.0)
            self.assertGreaterEqual(row["discharge_m3h"], 0.0)
            self.assertLessEqual(set(KPI_KEYS), set(row))

    def test_steps_name_the_knob_and_the_capacity_before(self):
        steps = self.ladder[2500]["steps"]
        self.assertEqual(steps[0]["cap_before_ktpa"], BASELINE_KTPA)
        for step in steps:
            self.assertEqual(set(step), STEP_KEYS)
            self.assertEqual(step["knob"], cap.MEASURE_KNOBS[step["link"]])
            self.assertEqual(step["to_stage"], step["from_stage"] + 1)
            self.assertEqual(step["set"], {step["knob"]: float(step["to_stage"])})
            self.assertGreater(step["cap_after_ktpa"], step["cap_before_ktpa"])
            self.assertRegex(step["text"], CYRILLIC)
        self.assertEqual([s["cap_before_ktpa"] for s in steps if s["link"] == "plant"], [1000, 1200, 2000])

    def test_every_capacity_is_the_library_value(self):
        for knobs in ({}, FULL[1200], FULL[2500], dict(tu2_closed=1), dict(fan_vs2_off=1, m_haul=2)):
            report = self.report(**knobs)
            res = cap.evaluate(self.advisor.model, cap.State.from_knobs(self.inputs(**knobs).knobs))
            self.assertEqual({row["id"]: row["cap_ktpa"] for row in report["links"]}, res.capacity_rounded)
            self.assertEqual(report["binding_link"], res.binding_link)
            self.assertAlmostEqual(report["kpi"]["gold_koz_year"], res.gold.oz_per_year / 1000, delta=0.006)
            self.assertAlmostEqual(report["achievable_exact_ktpa"], res.achievable_ktpa, delta=0.006)

    def test_remaining_sequence_from_the_current_state(self):
        report = self.report(target_ktpa=1200, m_plant=1, m_haul=1)
        self.assertEqual([s["link"] for s in report["sequence"]], ["ventilation", "water", "stopes", "tailings"])
        self.assertEqual(report["measures_needed"], 4)
        self.assertEqual(report["next_measure"], report["sequence"][0])
        self.assertEqual(report["sequence_outcome"]["achievable_ktpa"], 1200)

    def test_target_reached_needs_no_measure(self):
        report = self.report(target_ktpa=1200, **FULL[1200])
        self.assertTrue(report["target_reached"])
        self.assertIsNone(report["next_measure"])
        self.assertEqual((report["measures_needed"], report["sequence"]), (0, []))

    def test_no_stage_left_reports_the_achievable_rate(self):
        plan = self.advisor.plan(cap.State(), 3000)
        self.assertEqual(plan.stop_reason, "no_stage_left")
        self.assertFalse(plan.reached)
        self.assertEqual(plan.links, SEQUENCES[2500])
        self.assertEqual(engine.achievable_rounded(plan.result), 2500)
        self.assertEqual(plan.result.binding_link, "plant")

    def test_ladder_keeps_the_current_disturbances(self):
        ladder = {row["target_ktpa"]: row for row in self.report(fan_vs2_off=1, m_haul=2, m_plant=3)["ladder"]}
        first = ladder[1000]["steps"][0]
        self.assertEqual((first["kind"], first["link"], first["measure"]), ("disturbance", "ventilation",
                                                                            "restore_fan_vs2"))
        self.assertEqual((first["cap_before_ktpa"], first["set"]), (374, {"fan_vs2_off": 0.0}))
        self.assertEqual(ladder[1000]["sequence"], ["ventilation", "haulage", "ventilation"])
        self.assertEqual((ladder[1000]["achievable_ktpa"], ladder[1000]["reached"]), (1000, True))
        for row in ladder.values():     # every target starts with the repair
            self.assertEqual(row["steps"][0]["measure"], "restore_fan_vs2")
        low_grade = {row["target_ktpa"]: row for row in self.report(grade_gpt=1.76)["ladder"]}
        self.assertEqual(low_grade[1000]["sequence"], ["haulage", "ventilation"])
        self.assertAlmostEqual(low_grade[1000]["gold_koz_year"], 47.8, delta=0.05)


class TestReport(AdvisorCase):
    """The document served at GET /report."""

    def test_keys(self):
        report = self.advisor.report(self.base)
        self.assertEqual(set(report), REPORT_KEYS)
        self.assertEqual(set(report["kpi"]), KPI_KEYS)
        self.assertEqual([row["id"] for row in report["links"]], list(cap.LINKS))
        for row in report["links"]:
            self.assertEqual(set(row), {"id", "name", "cap_ktpa", "limiting", "binding", "knob", "stage",
                                        "stage_max", "detail"})
        self.assertEqual(set(report["sequence_outcome"]),
                         {"achievable_ktpa", "binding_link", "binding_link_name", "reached", "stop_reason"})
        self.assertEqual(set(report["effects"]), {"revision", "label", "before_revision", "before_label", "items"})

    def test_baseline(self):
        report = self.advisor.report(self.base)
        self.assertEqual((report["binding_link"], report["binding_link_name"]), ("haulage", "Откатка"))
        self.assertEqual((report["achievable_ktpa"], report["target_ktpa"]), (926, 1000))
        self.assertFalse(report["target_reached"])
        self.assertEqual([row["binding"] for row in report["links"]], [True] + [False] * 7)
        dewatering = report["links"][4]
        self.assertEqual((dewatering["cap_ktpa"], dewatering["limiting"], dewatering["knob"]), (None, False, None))
        self.assertEqual(report["next_measure"]["measure"], "m_haul")
        self.assertEqual(report["kpi"]["gold_gain_koz_year"], 0.0)
        self.assertAlmostEqual(report["kpi"]["air_demand_m3s"], 317.2, delta=0.05)
        self.assertAlmostEqual(report["kpi"]["dewatering_margin"], 2.54, delta=0.005)

    def test_sustainable_baseline(self):
        baseline = self.report(grade_gpt=1.76, m_haul=3)["sustainable_baseline"]
        self.assertEqual(baseline["ktpa"], BASELINE_KTPA)
        self.assertAlmostEqual(baseline["gold_koz_year"], BASELINE_GOLD_KOZ, delta=0.05)
        self.assertAlmostEqual(baseline["stockpile_days_left"], STOCKPILE_DAYS, delta=3)
        self.assertEqual((baseline["stockpile_t"], baseline["plant_ktpa"]), (STOCKPILE_T, 1000))
        self.assertAlmostEqual(baseline["stockpile_net_tpd"], -167, delta=1)
        self.assertIn("хватит на 564 сут", baseline["text"])

    def test_stockpile_days(self):
        self.assertAlmostEqual(self.advisor.report(self.base)["kpi"]["stockpile_days_left"], STOCKPILE_DAYS, delta=3)
        half = replace(self.base, stockpile_t=STOCKPILE_T / 2)
        self.assertAlmostEqual(self.advisor.report(half)["kpi"]["stockpile_days_left"], STOCKPILE_DAYS / 2, delta=2)
        # trucks 06 and 07 wait for air: the mine hoists what it did, the stockpile falls as before
        self.assertAlmostEqual(self.report(m_haul=1)["kpi"]["stockpile_days_left"], STOCKPILE_DAYS, delta=3)
        self.assertIsNone(self.report(m_haul=1, m_vent=1)["kpi"]["stockpile_days_left"])  # the mine keeps up

    def test_is_strict_json_for_every_scenario(self):
        for knobs in ({}, FULL[2500], dict(pumps_failed_p150=3), dict(inflow_factor=2.18), dict(line_down=2)):
            text = json.dumps(self.report(before=self.base, **knobs), allow_nan=False, ensure_ascii=False)
            self.assertEqual(set(json.loads(text)), REPORT_KEYS)

    def test_calibration_table_is_the_library_table(self):
        rows = self.advisor.report(self.base)["calibration"]
        self.assertEqual([row["id"] for row in rows],
                         ["C1", "C2", "C3", "C4", "C4", "C5", "C5", "C5", "C5", "C6", "C7", "C8", "C9", "C10",
                          "C11", "C11", "C12", "C13", "C14", "C15", "C16"])
        analytic = [row for row in rows if row["kind"] == "analytic"]
        checks = cap.calibration_checks(self.advisor.model)
        self.assertEqual([row["id"] for row in analytic], [check.id for check in checks])
        for row, check in zip(analytic, checks):
            self.assertEqual(row["reported"], check.reported)
            self.assertAlmostEqual(row["model"], check.model, delta=0.006)
            self.assertAlmostEqual(row["deviation"], check.deviation, delta=0.006)
            self.assertIs(row["passed"], check.ok)
            self.assertTrue(row["passed"], row["id"])
        for row in rows:
            self.assertEqual(set(row) - {"run"}, CALIBRATION_ROW_KEYS)
            self.assertIn(row["kind"], ("analytic", "simulator", "out_of_sample"))
            self.assertRegex(row["title"], CYRILLIC)
            self.assertNotRegex(row["title"] + row["tolerance"] + row["unit"], LATIN)

    def test_invalid_scenario_is_rejected(self):
        with self.assertRaises(ValueError):
            self.report(tu1_closed=1, tu2_closed=1)


class TestProjection(AdvisorCase):
    """Spec 3.4 step 5: ten years of the current measure set."""

    def rows(self, **knobs):
        projection = self.report(**knobs)["projection"]
        return projection, projection["rows"]

    def test_ten_rows_2027_to_2036(self):
        projection, rows = self.rows()
        self.assertEqual([row["year"] for row in rows], list(range(2027, 2037)))
        self.assertEqual((projection["first_year"], projection["last_year"]), (2027, 2036))
        for row in rows:
            self.assertEqual(set(row), {
                "year", "achievable_ktpa", "binding_link", "binding_link_name", "target_met", "centroid_m",
                "gold_oz", "gold_koz", "gold_total_koz", "tailings_stored_kt", "tailings_free_kt",
                "tailings_years_left", "water_deficit_m3h", "note"})

    def test_first_year_is_the_current_state(self):
        _, rows = self.rows()
        self.assertEqual((rows[0]["achievable_ktpa"], rows[0]["binding_link"], rows[0]["centroid_m"]),
                         (926, "haulage", 75.0))
        self.assertAlmostEqual(rows[0]["gold_koz"], BASELINE_GOLD_KOZ, delta=0.05)

    def test_tailings_fill_is_monotonic_and_conserved(self):
        for knobs in ({}, FULL[1200], FULL[2500]):
            _, rows = self.rows(**knobs)
            stored = [row["tailings_stored_kt"] for row in rows]
            free = [row["tailings_free_kt"] for row in rows]
            self.assertEqual(stored, sorted(stored))
            self.assertEqual(free, sorted(free, reverse=True))
            self.assertGreater(stored[1], stored[0])
            for row in rows:
                self.assertAlmostEqual(row["tailings_stored_kt"] + row["tailings_free_kt"], stored[0] + free[0],
                                       delta=1.5)
            added = [b - a for a, b in zip(stored, stored[1:])]
            for row, tonnes in zip(rows[1:], added):  # what is milled in a year is what the dams take
                self.assertAlmostEqual(tonnes, row["achievable_ktpa"], delta=1.5)

    def test_year_storage_runs_out(self):
        # 3 172 kt free at the epoch (dam 4 at 90 %, dams 2 and 3 empty), about 0.9 Mt a year: full in 2030
        projection, rows = self.rows()
        free_start = sum(d.capacity_t - d.stored_start_t for name, d in self.advisor.model.dams.items()
                         if name != "tsf-cell5") / 1000
        self.assertAlmostEqual(free_start, 3172, delta=1)
        self.assertEqual(projection["storage_runs_out_year"], 2030)
        by_year = {row["year"]: row for row in rows}
        self.assertGreater(by_year[2029]["tailings_free_kt"], 0)
        self.assertEqual(by_year[2030]["tailings_free_kt"], 0)
        self.assertEqual(by_year[2030]["binding_link"], "tailings")
        self.assertAlmostEqual(sum(by_year[y]["achievable_ktpa"] for y in (2027, 2028, 2029, 2030)), free_start,
                               delta=2)
        self.assertEqual((by_year[2031]["achievable_ktpa"], by_year[2031]["gold_oz"]), (0, 0))
        self.assertTrue(all(row["binding_link"] != "tailings" for row in rows[:3]))

    def test_new_cell_moves_the_year_out_of_the_horizon(self):
        projection, rows = self.rows(m_tailings=1)
        self.assertIsNone(projection["storage_runs_out_year"])
        self.assertGreater(rows[-1]["tailings_free_kt"], 0)

    def test_depth_lowers_haulage_year_by_year(self):
        _, rows = self.rows(m_tailings=1)
        rates = [row["achievable_ktpa"] for row in rows]
        centroids = [row["centroid_m"] for row in rows]
        self.assertTrue(all(row["binding_link"] == "haulage" for row in rows))
        self.assertEqual(rates, sorted(rates, reverse=True))
        self.assertEqual(centroids, sorted(centroids, reverse=True))
        # the centroid drops by ore / 51 462 t per metre: 926 kt lowers it by 18 m
        self.assertAlmostEqual(centroids[0] - centroids[1], 926110 / 51462, delta=0.1)
        # spec 2.3: 926 -> 840 kt/yr between +75 m and +25 m; the model passes +25 m between 2029 and 2030
        self.assertGreater(rates[2], 840)
        self.assertLess(rates[4], 840)

    def test_first_year_the_target_is_missed(self):
        self.assertEqual(self.rows()[0]["target_missed_year"], 2027)             # 926 against 1000
        met, rows = self.rows(m_haul=1, m_vent=1)                                # plant 1000 until the dams are full
        self.assertEqual((met["target_missed_year"], met["storage_runs_out_year"]), (2030, 2030))
        self.assertEqual([row["target_met"] for row in rows[:4]], [True, True, True, False])
        self.assertEqual([row["binding_link"] for row in rows[:4]], ["plant", "plant", "plant", "tailings"])
        thin, rows = self.rows(m_haul=1)      # without the fan trucks 06 and 07 wait for air from the first year
        self.assertEqual((thin["target_missed_year"], rows[0]["binding_link"], rows[0]["achievable_ktpa"]),
                         (2027, "ventilation", 926))
        base_rows = self.rows()[1]
        self.assertEqual([row["achievable_ktpa"] for row in rows], [row["achievable_ktpa"] for row in base_rows])
        deep, _ = self.rows(target_ktpa=2500, **FULL[2500])                      # depth takes haulage below 2500
        self.assertEqual(deep["target_missed_year"], 2028)

    def test_gold_accumulates(self):
        projection, rows = self.rows(**FULL[1200])
        self.assertAlmostEqual(rows[-1]["gold_total_koz"], sum(row["gold_koz"] for row in rows), delta=0.1)
        self.assertEqual(projection["gold_total_koz"], rows[-1]["gold_total_koz"])
        totals = [row["gold_total_koz"] for row in rows]
        self.assertEqual(totals, sorted(totals))


class TestDisturbances(AdvisorCase):
    """Spec 3.2 and 3.3: what each scenario button does to the report."""

    def caps(self, report):
        return {row["id"]: row["cap_ktpa"] for row in report["links"]}

    def test_step1200_alone(self):
        report = self.report(target_ktpa=1200, m_plant=1)
        self.assertEqual(self.caps(report)["plant"], 1200)
        self.assertEqual((report["binding_link"], report["achievable_ktpa"]), ("haulage", 926))
        self.assertEqual(report["kpi"]["gold_gain_koz_year"], 0.0)

    def test_close_tu2(self):
        report = self.report(tu2_closed=1)
        self.assertWithin(self.caps(report)["haulage"], 833, 1.0)
        self.assertEqual(report["binding_link"], "haulage")
        self.assertEqual(report["next_measure"]["measure"], "open_tu2")      # the decline is opened first
        self.assertEqual(report["next_measure"]["set"], {"tu2_closed": 0.0})
        self.assertEqual(report["sequence"][1]["measure"], "m_haul")
        self.assertLess(report["kpi"]["stockpile_days_left"], STOCKPILE_DAYS - 3)

    def test_close_tu1(self):
        self.assertLess(self.caps(self.report(tu1_closed=1))["haulage"], 926)

    def test_fan_vs2_fail(self):
        report = self.report(fan_vs2_off=1)
        self.assertEqual(report["binding_link"], "ventilation")
        self.assertWithin(report["achievable_ktpa"], 374, 1.0)
        self.assertEqual(report["kpi"]["air_supply_m3s"], 252.0)
        self.assertLess(report["kpi"]["air_margin_pct"], 0)
        self.assertEqual(report["kpi"]["units_held_vent"], 4)            # trucks 03-05 and LHD 04
        self.assertAlmostEqual(report["kpi"]["air_used_m3s"], 238.6, delta=0.05)
        self.assertAlmostEqual(report["kpi"]["air_spare_m3s"], 13.4, delta=0.05)
        self.assertEqual(report["next_measure"]["measure"], "restore_fan_vs2")   # the fan, not a new airway
        self.assertEqual([s["measure"] for s in report["sequence"]], ["restore_fan_vs2", "m_haul", "m_vent"])

    def test_pump_one_fail_changes_no_bar(self):
        self.assertEqual(self.caps(self.report(pumps_failed_p150=1)), self.caps(self.advisor.report(self.base)))

    def test_pump_station_fail_binds_when_a_production_level_floods(self):
        failed = self.inputs(pumps_failed_p150=3)
        report = self.advisor.report(failed)
        self.assertEqual(report["binding_link"], "haulage")
        self.assertEqual(report["kpi"]["dewatering_margin"], 0.0)
        flooded = self.advisor.report(replace(failed, flooded_levels=("lvl-000", "lvl-m050")))
        self.assertEqual((flooded["binding_link"], flooded["achievable_ktpa"]), ("dewatering", 768))
        self.assertEqual(self.caps(flooded)["stopes"], 1024)
        self.assertEqual(flooded["next_measure"]["measure"], "restore_pumps")
        self.assertEqual(flooded["next_measure"]["set"], {"pumps_failed_p150": 0.0})
        self.assertEqual(flooded["sequence_outcome"]["reached"], True)
        self.assertEqual([s["link"] for s in flooded["sequence"]], ["dewatering", "haulage", "ventilation"])

    def test_flood_inflow(self):
        report = self.report(inflow_factor=2.18)
        self.assertEqual(self.caps(report), self.caps(self.advisor.report(self.base)))
        self.assertGreater(report["kpi"]["discharge_m3h"], report["kpi"]["permit_m3h"])
        self.assertGreater(report["kpi"]["permit_use_pct"], 100)
        self.assertEqual(report["kpi"]["permit_m3h"], 218.8)

    def test_grade_drop(self):
        report = self.report(grade_gpt=1.76)
        self.assertEqual(self.caps(report), self.caps(self.advisor.report(self.base)))
        self.assertEqual(report["kpi"]["grade_gpt"], 1.76)
        self.assertLess(report["kpi"]["gold_koz_year"], BASELINE_GOLD_KOZ - 5)
        self.assertLess(report["kpi"]["gold_gain_koz_year"], 0)

    def test_line2_down(self):
        report = self.report(line_down=2)
        self.assertEqual((report["binding_link"], report["achievable_ktpa"]), ("plant", 667))
        self.assertEqual(report["next_measure"]["measure"], "restart_line")   # not the capex of stage 1
        self.assertIsNone(report["kpi"]["stockpile_days_left"])  # the stockpile grows
        self.assertEqual(report["kpi"]["stockpile_trend"], "grows")

    def test_live_tonnages_enter_the_report(self):
        things = {"scenario": {"m_haul": 1.0, "revision": 4.0, "label": "ход"},
                  "tsf-dam4": {"stored_t": self.advisor.model.dams["tsf-dam4"].stored_start_t + 100000.0},
                  "rom-stockpile": {"tonnes": 12000.0}, "lvl-m050": {"state": "flooded"},
                  "enterprise": {"sim_time": "2027-02-01T08:00:00"}}
        inputs = self.advisor.inputs_from_things(things)
        self.assertEqual((inputs.revision, inputs.label, inputs.flooded_levels), (4, "ход", ("lvl-m050",)))
        self.assertEqual((inputs.tailings_placed_t, inputs.stockpile_t), (100000.0, 12000.0))
        self.assertEqual(inputs.knobs["m_haul"], 1.0)
        self.assertEqual(inputs.knobs["grade_gpt"], 2.05)  # left out: the default of the scenario thing
        report = self.advisor.report(inputs)
        self.assertEqual(report["sim_time"], "2027-02-01T08:00:00")
        self.assertEqual(report["kpi"]["tailings_free_kt"], 3072.0)
        self.assertEqual(self.caps(report)["tailings"], 1024)   # (3172 - 100) / 3 years


class TestApply(AdvisorCase):
    """Spec 3.4: POST /apply returns the knob changes for the Stand."""

    def test_next_raises_exactly_the_knob_of_the_binding_link_by_one(self):
        for knobs in ({}, dict(target_ktpa=1200, m_plant=1, m_haul=1),
                      dict(target_ktpa=2500, m_plant=3, m_haul=2, m_water=1, m_stopes=1)):
            inputs = self.inputs(**knobs)
            answer = self.advisor.apply(inputs, "next")
            binding = self.advisor.report(inputs)["binding_link"]
            knob = cap.MEASURE_KNOBS[binding]
            self.assertEqual(answer["changes"], {knob: inputs.knobs[knob] + 1.0}, knobs)
            self.assertEqual((answer["mode"], answer["reason"], answer["binding_link"]), ("next", "applied", binding))
            self.assertEqual(len(answer["steps"]), 1)

    def test_answer_keys(self):
        answer = self.advisor.apply(self.base, "next")
        self.assertEqual(set(answer), {"mode", "revision", "target_ktpa", "binding_link", "changes", "steps",
                                       "reason", "message"})
        self.assertEqual(set(answer["steps"][0]), STEP_KEYS)
        self.assertEqual(answer["steps"][0]["kind"], "measure")
        self.assertRegex(answer["message"], CYRILLIC)
        self.assertIsInstance(answer["changes"]["m_haul"], float)

    def test_all_returns_the_full_remaining_sequence(self):
        inputs = self.inputs(target_ktpa=1200, m_plant=1)
        answer = self.advisor.apply(inputs, "all")
        self.assertEqual([s["link"] for s in answer["steps"]], ["haulage", "ventilation", "water", "stopes", "tailings"])
        self.assertEqual(answer["changes"], {"m_haul": 1.0, "m_water": 1.0, "m_stopes": 1.0, "m_vent": 1.0,
                                             "m_tailings": 1.0})
        after = self.advisor.report(inputs.with_knobs(answer["changes"]))
        self.assertTrue(after["target_reached"])
        self.assertEqual((after["achievable_ktpa"], after["binding_link"], after["measures_needed"]),
                         (1200, "plant", 0))

    def test_all_from_the_baseline_gives_the_final_stage_of_every_knob(self):
        answer = self.advisor.apply(self.inputs(target_ktpa=2500), "all")
        self.assertEqual(answer["changes"], {knob: float(stage) for knob, stage in FULL[2500].items()})
        self.assertEqual([s["link"] for s in answer["steps"]], SEQUENCES[2500])

    def test_repeating_next_walks_the_sequence(self):
        inputs, links = self.inputs(target_ktpa=2500), []
        for _ in range(20):
            answer = self.advisor.apply(inputs, "next")
            if not answer["changes"]:
                break
            links.append(answer["binding_link"])
            inputs = inputs.with_knobs(answer["changes"])
        self.assertEqual(links, SEQUENCES[2500])
        self.assertEqual(answer["reason"], "target_reached")
        self.assertEqual({k: v for k, v in inputs.knobs.items() if k in FULL[2500]},
                         {k: float(v) for k, v in FULL[2500].items()})

    def test_nothing_to_apply(self):
        reached = self.advisor.apply(self.inputs(m_haul=1, m_vent=1), "all")
        self.assertEqual((reached["changes"], reached["steps"], reached["reason"]), ({}, [], "target_reached"))
        exhausted = self.advisor.apply(self.inputs(target_ktpa=3000, **FULL[2500]), "next")
        self.assertEqual((exhausted["changes"], exhausted["reason"]), ({}, "no_stage_left"))

    def test_dewatering(self):
        flooded = replace(self.inputs(pumps_failed_p150=3), flooded_levels=("lvl-000", "lvl-m050"))
        self.assertEqual(self.advisor.apply(flooded, "next")["changes"], {"pumps_failed_p150": 0.0})
        self.assertEqual(self.advisor.apply(flooded, "all")["changes"],
                         {"pumps_failed_p150": 0.0, "m_haul": 1.0, "m_vent": 1.0})
        pumping = self.advisor.apply(flooded.with_knobs({"pumps_failed_p150": 0}), "next")
        self.assertEqual((pumping["changes"], pumping["reason"]), ({}, "pumping_out"))

    def test_unknown_mode(self):
        with self.assertRaises(ValueError):
            self.advisor.apply(self.base, "everything")


class TestEffects(AdvisorCase):
    """Spec 3.4 step 6: the list for the panel «Что изменилось»."""

    def items(self, before_knobs, after_knobs):
        before = self.inputs(revision=1, **before_knobs)
        after = self.inputs(revision=2, label="после", **after_knobs)
        return self.advisor.effects(before, after)

    def by_id(self, effects):
        return {item["id"]: item for item in effects["items"]}

    def test_empty_without_a_previous_state(self):
        self.assertEqual(self.advisor.report(self.base)["effects"]["items"], [])

    def test_empty_when_nothing_changed(self):
        effects = self.items({}, {})
        self.assertEqual(effects["items"], [])
        self.assertEqual((effects["before_revision"], effects["revision"], effects["label"]), (1, 2, "после"))
        drift = self.advisor.effects(self.base, replace(self.base, stockpile_t=20000.0, tailings_placed_t=5e5,
                                                        revision=3))
        self.assertEqual(drift["items"], [])  # tonnages of the running mine are not a change of the scenario

    def test_haulage_measure(self):
        items = self.by_id(self.items({}, dict(m_haul=1)))
        haul = items["cap_haulage_ktpa"]
        self.assertEqual(set(haul), {"id", "name", "unit", "before", "after", "trend", "text"})
        self.assertEqual((haul["before"], haul["trend"], haul["unit"]), (926, "better", "тыс. т/год"))
        self.assertWithin(haul["after"], 1388, 1.0)
        self.assertEqual(haul["text"], f"Мощность звена «откатка» выросла: 926 → {wording.num(haul['after'])} тыс. т/год.")
        self.assertIn("1\u00a03", haul["text"])  # thousands are separated by a no-break space
        # the two new trucks wait for air: the chain stays at 926 kt/yr and the list says why
        self.assertEqual(items["binding_link"]["text"], "Узкое место сместилось: откатка → вентиляция.")
        self.assertEqual(items["cap_ventilation_ktpa"]["text"],
                         "Мощность звена «вентиляция» снизилась: 958 → 926 тыс. т/год.")
        self.assertEqual(items["air_demand_m3s"]["text"], "Потребность в воздухе выросла: 317,2 → 369,9 м³/с.")
        self.assertEqual(items["air_demand_m3s"]["trend"], "worse")
        held = items["units_held_vent"]
        self.assertEqual(held["text"], "Воздуха не хватает на весь парк, в ожидании воздуха: самосвалы №\u00a06–7.")
        self.assertEqual((held["before"], held["after"], held["trend"], held["unit"]), (0, 2, "worse", "ед."))
        self.assertEqual(items["measures_needed"]["text"], "Число мер до цели снизилось: 2 → 1.")
        for unchanged in ("achievable_ktpa", "gold_koz_year", "stockpile_days_left", "cap_plant_ktpa"):
            self.assertNotIn(unchanged, items)  # unchanged values are not listed

    def test_ventilation_measure_returns_the_held_trucks(self):
        items = self.by_id(self.items(dict(m_haul=1), dict(m_haul=1, m_vent=1)))
        self.assertEqual(items["binding_link"]["text"], "Узкое место сместилось: вентиляция → фабрика.")
        self.assertEqual(items["achievable_ktpa"]["text"],
                         "Достижимая производительность цепочки выросла: 926 → 1\u00a0000 тыс. т/год.")
        self.assertEqual(items["cap_ventilation_ktpa"]["text"],
                         "Мощность звена «вентиляция» выросла: 926 → 1\u00a0805 тыс. т/год.")
        self.assertEqual(items["gold_koz_year"]["text"], "Выпуск золота вырос: 51,9 → 56,0 тыс. унц./год.")
        self.assertEqual(items["air_supply_m3s"]["text"], "Подача воздуха выросла: 322 → 427 м³/с.")
        held = items["units_held_vent"]
        self.assertEqual(held["text"],
                         "Воздуха снова хватает на весь парк, в работу возвращаются: самосвалы №\u00a06–7.")
        self.assertEqual((held["before"], held["after"], held["trend"]), (2, 0, "better"))
        self.assertIn("stockpile_days_left", items)
        self.assertNotIn("air_demand_m3s", items)   # the fleet in service is the same

    def test_held_units_are_named_in_the_link_row_and_in_the_next_measure(self):
        base = self.advisor.report(self.base)
        self.assertEqual(base["links"][1]["detail"],
                         "подача воздуха 322 м³/с, потребность парка 317,2 м³/с, запас 4,8 м³/с")
        self.assertEqual(base["next_measure"]["text"],
                         "ввод самосвалов №\u00a06–7 (парк: 5 → 7 машин); воздуха на весь парк не хватит, "
                         "до меры по вентиляции в ожидании: самосвалы №\u00a06–7")
        held = self.report(m_haul=1)
        self.assertEqual(held["links"][1]["detail"],
                         "подача воздуха 322 м³/с, потребность парка 369,9 м³/с; в ожидании воздуха: "
                         "самосвалы №\u00a06–7; работающей технике нужно 317,2 м³/с")
        self.assertEqual((held["binding_link"], held["links"][1]["binding"]), ("ventilation", True))
        self.assertEqual(held["next_measure"]["text"],
                         "ввод в работу: вентилятор ВПВ (подача воздуха 322 → 427 м³/с); "
                         "в работу возвращаются: самосвалы №\u00a06–7")
        self.assertEqual(self.advisor.apply(self.inputs(m_haul=1), "next")["message"],
                         "Узкое место — вентиляция. Мера: " + held["next_measure"]["text"] + ".")
        fan = self.report(fan_vs2_off=1)
        self.assertIn("в ожидании воздуха: самосвалы №\u00a03–5 и ПДМ №\u00a04", fan["links"][1]["detail"])
        self.assertIn("в работу возвращаются: самосвалы №\u00a03–5 и ПДМ №\u00a04", fan["next_measure"]["text"])
        # a stage that does not free every unit says which ones still wait
        many = self.report(m_haul=2)
        self.assertEqual((many["binding_link"], many["achievable_ktpa"]), ("ventilation", 512))
        self.assertTrue(many["next_measure"]["text"].endswith(
            "в работу возвращаются: самосвалы №\u00a07–9 и ПДМ №\u00a03–4; "
            "в ожидании воздуха остаются: самосвал №\u00a010"))
        # a stage of another link that brings in more diesel than the air carries says who will wait
        stopes = self.report(target_ktpa=2000, m_haul=1, m_vent=1, m_plant=2, m_water=1, m_stopes=1, m_tailings=1)
        self.assertEqual(stopes["binding_link"], "stopes")
        self.assertTrue(stopes["next_measure"]["text"].endswith(
            "воздуха на весь парк не хватит, до меры по вентиляции в ожидании: самосвал №\u00a07"))

    def test_held_phrase(self):
        self.assertEqual(wording.held_phrase((), ()), "")
        self.assertEqual(wording.held_phrase(("truck-07",), ()), "самосвал №\u00a07")
        self.assertEqual(wording.held_phrase(("truck-07", "truck-06"), ()), "самосвалы №\u00a06–7")
        self.assertEqual(wording.held_phrase(("truck-10", "truck-07"), ("lhd-04",)),
                         "самосвалы №\u00a07, 10 и ПДМ №\u00a04")
        self.assertEqual(wording.held_phrase((), ("kz.sekis:lhd-04", "lhd-03")), "ПДМ №\u00a03–4")

    def test_every_text_is_russian_with_units(self):
        cases = [dict(m_haul=1), dict(target_ktpa=1200, m_plant=1), dict(tu2_closed=1), dict(fan_vs2_off=1),
                 dict(pumps_failed_p150=1), dict(pumps_failed_p150=3), dict(inflow_factor=2.18),
                 dict(grade_gpt=1.76), dict(line_down=2), dict(m_water=2), dict(m_tailings=1), dict(m_dev=1),
                 dict(target_ktpa=2500, **FULL[2500])]
        for knobs in cases:
            effects = self.items({}, knobs)
            self.assertTrue(effects["items"], knobs)
            for item in effects["items"]:
                text = item["text"]
                self.assertRegex(text, CYRILLIC)
                self.assertNotRegex(text, LATIN, text)
                self.assertTrue(text.endswith("."), text)
                self.assertIn(item["trend"], ("better", "worse", "neutral"))
                self.assertNotRegex(text, r"\d\.\d", text)       # decimals are written with a comma
                self.assertNotRegex(text, r"\d{5,}", text)       # thousands are separated
                for word in ("жюри", "эксперт", "оцен", "обратите", "посмотрите"):
                    self.assertNotIn(word, text.lower())

    def test_scenario_sentences(self):
        fan = self.by_id(self.items({}, dict(fan_vs2_off=1)))
        self.assertEqual(fan["air_supply_m3s"]["text"], "Подача воздуха снизилась: 322 → 252 м³/с.")
        self.assertEqual(fan["binding_link"]["text"], "Узкое место сместилось: откатка → вентиляция.")
        self.assertEqual(fan["units_held_vent"]["text"],
                         "Воздуха не хватает на весь парк, в ожидании воздуха: самосвалы №\u00a03–5 и ПДМ №\u00a04.")
        self.assertEqual(fan["achievable_ktpa"]["text"],
                         "Достижимая производительность цепочки снизилась: 926 → 374 тыс. т/год.")
        grade = self.by_id(self.items({}, dict(grade_gpt=1.76)))
        self.assertEqual(grade["grade_gpt"]["text"], "Содержание золота в руде снизилось: 2,05 → 1,76 г/т.")
        self.assertEqual(set(grade), {"grade_gpt", "recovery_pct", "gold_koz_year"})
        line = self.by_id(self.items({}, dict(line_down=2)))
        self.assertEqual(line["cap_plant_ktpa"]["text"], "Мощность звена «фабрика» снизилась: 1\u00a0000 → 667 тыс. т/год.")
        pump = self.by_id(self.items({}, dict(pumps_failed_p150=1)))
        # no bar changes (redundancy); the repair of the pump becomes the first step
        self.assertEqual(set(pump), {"pumps_available", "measures_needed"})
        self.assertIn("исправных насосов 3 → 2 из 3", pump["pumps_available"]["text"])
        self.assertEqual(pump["measures_needed"]["text"], "Число мер до цели выросло: 2 → 3.")
        flood = self.by_id(self.items({}, dict(inflow_factor=2.18)))
        self.assertIn("разрешённый сброс 218,8 м³/ч превышен", flood["discharge_m3h"]["text"])
        target = self.by_id(self.items({}, dict(target_ktpa=2500)))
        self.assertEqual(target["target_ktpa"]["text"], "Цель по переработке повышена: 1\u00a0000 → 2\u00a0500 тыс. т/год.")
        self.assertEqual(target["measures_needed"]["text"], "Число мер до цели выросло: 2 → 15.")
        self.assertEqual(target["economics"]["text"],
                         "Цель 2\u00a0500 тыс. т/год: золота +88,1 тыс. унц./год к устойчивой базе 51,9; по цене "
                         "4\u00a0615 долл./унц. это 406,8 млн долл. в год, при полных затратах 1\u00a0995 долл./унц. "
                         "операционная маржа 230,9 млн долл. в год; капитальные затраты ≈125 млн долл. (по расчёту "
                         "компании, 3-й кв. 2025 г.), простая окупаемость 0,5 года.")

    def test_flooding_and_recovery(self):
        failed = self.inputs(revision=2, pumps_failed_p150=3)
        flooded = replace(failed, flooded_levels=("lvl-000", "lvl-m050"))
        items = self.by_id(self.advisor.effects(self.base, flooded))
        self.assertEqual(items["cap_dewatering_ktpa"]["text"],
                         "Водоотлив: затоплены горизонты 0 м, −50 м, добыча из оставшихся блоков "
                         "ограничена 768 тыс. т/год.")
        self.assertEqual((items["cap_dewatering_ktpa"]["before"], items["cap_dewatering_ktpa"]["after"]), (None, 768))
        dry = replace(self.base, revision=3)
        back = self.by_id(self.advisor.effects(flooded, dry))
        self.assertEqual(back["cap_dewatering_ktpa"]["text"], "Водоотлив: затопление снято, звено не ограничивает добычу.")
        self.assertEqual(back["cap_dewatering_ktpa"]["trend"], "better")

    def test_number_format(self):
        self.assertEqual(wording.num(1386.4), "1\u00a0386")
        self.assertEqual(wording.num(51.87, 1), "51,9")
        self.assertEqual(wording.num(-50), "−50")
        self.assertEqual(wording.num(12345678.5, 1), "12\u00a0345\u00a0678,5")
        self.assertEqual(wording.num(0.004, 2), "0,00")
        self.assertEqual(wording.num(None), "—")


class TestTwinMessage(AdvisorCase):
    """Spec 1.1, 5.2: the Ditto-protocol message for kz.sekis:advisor."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
        thing = next(t for t in registry["things"] if t["thingId"] == "kz.sekis:advisor")
        cls.registry_features = {fid: body["properties"]["value"] for fid, body in thing["features"].items()}

    def check(self, envelope):
        self.assertEqual(set(envelope), {"topic", "path", "value"})
        self.assertEqual(envelope["topic"], "kz.sekis/advisor/things/twin/commands/modify")
        self.assertEqual(envelope["path"], "/features")
        self.assertEqual(set(envelope["value"]), set(self.registry_features))
        for feature_id, default in self.registry_features.items():
            body = envelope["value"][feature_id]
            self.assertEqual(set(body), {"properties"})
            self.assertEqual(set(body["properties"]), {"value"})
            value = body["properties"]["value"]
            self.assertIs(type(value), str if isinstance(default, str) else float, feature_id)
        return {fid: body["properties"]["value"] for fid, body in envelope["value"].items()}

    def test_features_listed_in_the_spec(self):
        self.assertEqual(set(self.registry_features), {
            "binding_link", "next_measure", "measures_needed", "target_ktpa", "achievable_ktpa",
            "cap_haulage_ktpa", "cap_ventilation_ktpa", "cap_stopes_ktpa", "cap_development_ktpa",
            "cap_dewatering_ktpa", "dewatering_margin", "cap_plant_ktpa", "cap_water_ktpa", "cap_tailings_ktpa",
            "gold_koz_year", "gold_gain_koz_year", "air_demand_m3s", "water_deficit_m3h", "discharge_m3h",
            "tailings_years_left", "stockpile_days_left", "report_revision"})

    def test_baseline_message(self):
        values = self.check(self.advisor.envelope(self.advisor.report(replace(self.base, revision=7))))
        self.assertEqual((values["binding_link"], values["next_measure"]), ("haulage", "m_haul"))
        self.assertEqual((values["measures_needed"], values["target_ktpa"], values["achievable_ktpa"]),
                         (2.0, 1000.0, 926.0))
        self.assertEqual([values[f"cap_{link}_ktpa"] for link in cap.LINKS],
                         [926.0, 958.0, 1024.0, 1750.0, 0.0, 1000.0, 1000.0, 1057.0])  # dewatering: 0 = not limiting
        self.assertAlmostEqual(values["gold_koz_year"], 51.9, delta=0.05)
        self.assertEqual((values["gold_gain_koz_year"], values["report_revision"]), (0.0, 7.0))
        self.assertAlmostEqual(values["stockpile_days_left"], STOCKPILE_DAYS, delta=3)
        self.assertAlmostEqual(values["dewatering_margin"], 2.54, delta=0.005)

    def test_tokens_and_unbounded_values(self):
        done = self.check(self.advisor.envelope(self.report(m_haul=1, m_vent=1)))
        self.assertEqual((done["next_measure"], done["measures_needed"]), ("none", 0.0))
        self.assertEqual(done["stockpile_days_left"], 0.0)  # the stockpile does not fall
        flooded = replace(self.inputs(pumps_failed_p150=3), flooded_levels=("lvl-000", "lvl-m050"))
        wet = self.check(self.advisor.envelope(self.advisor.report(flooded)))
        self.assertEqual((wet["binding_link"], wet["next_measure"], wet["cap_dewatering_ktpa"]),
                         ("dewatering", "restore_pumps", 768.0))
        for knobs in (FULL[2500], dict(fan_vs2_off=1), dict(line_down=2), dict(grade_gpt=1.76, inflow_factor=2.18)):
            self.check(self.advisor.envelope(self.report(**knobs)))


class TestDisturbancesFirst(AdvisorCase):
    """Fix round 2, item 1: a disturbance an action removes comes before any expansion measure."""

    def test_the_largest_gain_leads_and_apply_next_removes_it(self):
        cases = {   # knobs -> (token, knob change, link, capacity before -> after)
            "line": (dict(line_down=2), "restart_line", {"line_down": 0.0}, "plant", (667, 1000)),
            "tu2": (dict(tu2_closed=1), "open_tu2", {"tu2_closed": 0.0}, "haulage", (834, 926)),
            "tu1": (dict(tu1_closed=1), "open_tu1", {"tu1_closed": 0.0}, "haulage", None),
            "fan": (dict(fan_vs2_off=1), "restore_fan_vs2", {"fan_vs2_off": 0.0}, "ventilation", (374, 958)),
            "pumps": (dict(pumps_failed_p150=1), "restore_pumps", {"pumps_failed_p150": 0.0}, "dewatering", None),
        }
        for name, (knobs, token, change, link, caps) in cases.items():
            with self.subTest(name):
                inputs = self.inputs(**knobs)
                report = self.advisor.report(inputs)
                step = report["next_measure"]
                self.assertEqual((step["kind"], step["measure"], step["set"], step["link"]),
                                 ("disturbance", token, change, link))
                if caps:
                    self.assertEqual((step["cap_before_ktpa"], step["cap_after_ktpa"]), caps)
                self.assertTrue(all(s["kind"] == "measure" for s in report["sequence"][1:]))
                answer = self.advisor.apply(inputs, "next")
                self.assertEqual((answer["changes"], answer["reason"]), (change, "applied"))
                self.assertTrue(answer["message"].startswith("Сначала устраняется нарушение: "), answer["message"])
                features = self.advisor.features(report)
                self.assertEqual(features["next_measure"], token)

    def test_operational_wording(self):
        self.assertEqual(self.report(line_down=2)["next_measure"]["text"],
                         "запустить технологическую линию №\u00a02 после ремонта "
                         "(мощность фабрики 667 → 1\u00a0000 тыс. т/год)")
        self.assertEqual(self.report(tu2_closed=1)["next_measure"]["text"],
                         "открыть уклон ТУ-2 (самосвалы №\u00a01–4 возвращаются на свой уклон; "
                         "откатка 834 → 926 тыс. т/год)")
        self.assertEqual(self.report(fan_vs2_off=1)["next_measure"]["text"],
                         "восстановить вентилятор ВС-2 (подача воздуха 252 → 322 м³/с); "
                         "в работу возвращаются: самосвалы №\u00a03–5 и ПДМ №\u00a04")
        flooded = replace(self.inputs(pumps_failed_p150=3), flooded_levels=("lvl-000", "lvl-m050"))
        text = self.advisor.report(flooded)["next_measure"]["text"]
        self.assertTrue(text.startswith("восстановить отказавшие насосы главной водоотливной станции"), text)
        self.assertIn("(исправных 0 → 3 из 3) и откачать воду (затоплены горизонты 0 м, −50 м)", text)

    def test_the_removal_with_the_largest_gain_comes_first(self):
        # line 2 stopped (667) and TU2 closed (834): restarting the line gains nothing while haulage
        # holds the chain at 834, opening TU2 gains 667 -> 667; the plant line binds, so it leads
        report = self.report(line_down=2, tu2_closed=1)
        self.assertEqual([s["measure"] for s in report["sequence"][:2]], ["restart_line", "open_tu2"])
        # the fan failure (374) and a closed decline: restoring the fan gains most
        report = self.report(fan_vs2_off=1, tu1_closed=1)
        self.assertEqual(report["sequence"][0]["measure"], "restore_fan_vs2")
        self.assertEqual({s["measure"] for s in report["sequence"][:2]}, {"restore_fan_vs2", "open_tu1"})

    def test_all_holds_the_removals_and_the_measures(self):
        inputs = self.inputs(target_ktpa=1200, m_plant=1, line_down=2, fan_vs2_off=1)
        answer = self.advisor.apply(inputs, "all")
        self.assertEqual(answer["changes"]["line_down"], 0.0)
        self.assertEqual(answer["changes"]["fan_vs2_off"], 0.0)
        after = self.advisor.report(inputs.with_knobs(answer["changes"]))
        self.assertTrue(after["target_reached"])

    def test_conditions_are_stated_not_proposed(self):
        report = self.report(grade_gpt=1.76, inflow_factor=2.18)
        self.assertEqual([c["knob"] for c in report["conditions"]], ["grade_gpt", "inflow_factor"])
        self.assertTrue(all(step["kind"] == "measure" for step in report["sequence"]))
        self.assertNotIn("grade_gpt", json.dumps([s["set"] for s in report["sequence"]]))
        grade, flood = report["conditions"]
        self.assertIn("1,76 г/т вместо 2,05 г/т", grade["text"])
        self.assertIn("мерами не снимается", grade["text"])
        self.assertIn("(паводок) — мерами не снимается", flood["text"])
        self.assertIn("в установившемся режиме", flood["text"])
        self.assertEqual(self.advisor.report(self.base)["conditions"], [])

    def test_a_reached_target_needs_no_repair(self):
        report = self.report(pumps_failed_p150=1, **FULL[1000])
        self.assertTrue(report["target_reached"])
        self.assertIsNone(report["next_measure"])


class TestProjectionNotes(AdvisorCase):
    """Fix round 2, item 2: years without tailings storage say why the plant stands."""

    def test_rows_carry_the_reason(self):
        projection = self.report(target_ktpa=2500, **FULL[2500])["projection"]
        by_year = {row["year"]: row for row in projection["rows"]}
        self.assertEqual(projection["storage_runs_out_year"], 2031)
        self.assertEqual(by_year[2030]["note"], "")
        self.assertTrue(by_year[2031]["note"].startswith("хвостохранилище заполнено в этом году: переработано 230 из "))
        for year in range(2032, 2037):
            self.assertEqual((by_year[year]["achievable_ktpa"], by_year[year]["gold_oz"]), (0, 0))
            self.assertEqual(by_year[year]["note"], "фабрика стоит: нет ёмкости хвостохранилища")

    def test_the_measure_that_prevents_it(self):
        projection = self.report()["projection"]
        measure = projection["storage_measure"]
        self.assertEqual((measure["knob"], measure["to_stage"], measure["storage_runs_out_year"]),
                         ("m_tailings", 1, None))
        self.assertIn("новая карта хвостохранилища", measure["text"])
        self.assertEqual(projection["storage_note"],
                         "Ёмкость хвостохранилища закончится в 2030 г.; после этого фабрика стоит. Мера: "
                         + measure["text"] + "; с ней ёмкости хватит до конца прогноза (2036 г.).")
        full = self.report(target_ktpa=2500, **FULL[2500])["projection"]   # the new cell is already built
        self.assertIsNone(full["storage_measure"]["knob"])
        self.assertIn("нужна ёмкость сверх новой карты", full["storage_note"])
        self.assertIsNone(self.report(m_tailings=1)["projection"]["storage_note"])


class TestStockpileDirection(AdvisorCase):
    """Fix round 2, item 3: the stockpile falls when the plant takes more than the mine delivers."""

    def test_step1200_draws_the_stockpile_faster(self):
        base = self.advisor.report(self.base)["kpi"]
        step = self.report(target_ktpa=1200, m_plant=1)["kpi"]
        self.assertEqual((base["stockpile_trend"], step["stockpile_trend"]), ("falls", "falls"))
        self.assertLess(step["stockpile_days_left"], base["stockpile_days_left"] - 100)
        # the plant mills 1200 kt/yr only as long as the water lasts: the water sources carry 1033 kt/yr
        # at the hoisting rate of 926 kt/yr (the simulator throttles to the same feed)
        self.assertAlmostEqual(step["stockpile_plant_tpd"], 2830, delta=5)
        self.assertAlmostEqual(step["stockpile_mine_tpd"], 2573, delta=2)
        self.assertAlmostEqual(step["stockpile_net_tpd"], step["stockpile_mine_tpd"] - step["stockpile_plant_tpd"],
                               delta=1)
        self.assertAlmostEqual(step["stockpile_days_left"], STOCKPILE_T / -step["stockpile_net_tpd"], delta=1)

    def test_signs(self):
        for knobs, trend in ((dict(), "falls"), (dict(tu2_closed=1), "falls"), (dict(fan_vs2_off=1), "falls"),
                             (dict(line_down=2), "grows"), (FULL[1000], "grows"),
                             (dict(target_ktpa=2500, **FULL[2500]), "grows")):
            with self.subTest(**knobs):
                kpi = self.report(**knobs)["kpi"]
                self.assertEqual(kpi["stockpile_trend"], trend)
                if trend == "falls":
                    self.assertLess(kpi["stockpile_net_tpd"], 0)
                    self.assertIsNotNone(kpi["stockpile_days_left"])
                else:
                    self.assertGreater(kpi["stockpile_net_tpd"], 0)
                    self.assertIsNone(kpi["stockpile_days_left"])

    def test_full_2500_set_is_close_to_balance(self):
        # 2515 kt/yr hoisted over 360 days against 2500 kt/yr milled over 365 days: +137 t/day
        kpi = self.report(target_ktpa=2500, **FULL[2500])["kpi"]
        self.assertAlmostEqual(kpi["stockpile_mine_tpd"], 6986, delta=5)
        self.assertAlmostEqual(kpi["stockpile_plant_tpd"], 6849, delta=5)
        self.assertAlmostEqual(kpi["stockpile_net_tpd"], 137, delta=5)

    def test_effects_say_the_stockpile_falls_faster(self):
        before = self.inputs(revision=1)
        after = self.inputs(revision=2, target_ktpa=1200, m_plant=1)
        items = {item["id"]: item for item in self.advisor.effects(before, after)["items"]}
        self.assertEqual(items["stockpile_days_left"]["trend"], "worse")
        self.assertIn("564 → 368 сут", items["stockpile_days_left"]["text"])


class TestEconomics(AdvisorCase):
    """Fix round 2, item 6: the value of the extra gold of each target, from published figures."""

    def test_each_target(self):
        ladder = {row["target_ktpa"]: row["economics"] for row in self.advisor.report(self.base)["ladder"]}
        expected = {1000: (4.1, None), 1200: (15.3, None), 2000: (60.1, 0.8), 2500: (88.1, 0.5)}
        for target, (gain, payback) in expected.items():
            econ = ladder[target]
            self.assertAlmostEqual(econ["gold_gain_koz_year"], gain, delta=0.05)
            self.assertEqual((econ["gold_price_usd_oz"], econ["aisc_usd_oz"], econ["margin_usd_oz"]),
                             (4615, 1995, 2620))
            self.assertAlmostEqual(econ["value_usd_m_year"], gain * 4.615, delta=0.3)
            self.assertAlmostEqual(econ["margin_usd_m_year"], gain * 2.620, delta=0.2)
            self.assertEqual(econ["payback_years"], payback)
            self.assertEqual(econ["capex_disclosed"], payback is not None)
            self.assertEqual(econ["capex_usd_m"], 125 if payback is not None else None)
            for key in ("price_basis", "aisc_basis", "capex_note", "summary"):
                self.assertRegex(econ[key], CYRILLIC)
        self.assertTrue(ladder[1200]["capex_note"].startswith("не раскрыто: "))
        self.assertIn("дробильное и мельничное оборудование", ladder[1200]["capex_note"])
        self.assertTrue(ladder[1000]["capex_note"].startswith("не раскрыто"))
        self.assertIn("пересчитанной базе", ladder[2000]["aisc_basis"])

    def test_every_figure_is_a_fact_of_params(self):
        params = json.loads((TEAM / "model" / "params.json").read_text(encoding="utf-8"))
        for pid in ("econ.gold_price_usd_oz", "econ.aisc_usd_oz", "econ.capex_expansion_usd_m"):
            self.assertTrue(params[pid]["source"].startswith("FACT D1 '"), pid)
            self.assertIn("https://", params[pid]["source"])
        self.assertEqual(params["econ.gold_price_usd_oz"]["value"], 4615)
        self.assertEqual(params["econ.aisc_usd_oz"]["value"], 1995)
        self.assertEqual(params["econ.capex_expansion_usd_m"]["value"], 125)

    def test_wording_describes_and_does_not_advise(self):
        report = self.advisor.report(self.base)
        texts = [row["economics"][key] for row in report["ladder"]
                 for key in ("price_basis", "aisc_basis", "capex_note", "summary")]
        texts += [self.advisor.effects(self.inputs(revision=1), self.inputs(revision=2, target_ktpa=t))["items"][-1]["text"]
                  for t in (1200, 2000)]
        for text in texts:
            for word in ("рекоменд", "стоит купить", "инвестир", "выгодн", "советуем", "покуп"):
                self.assertNotIn(word, text.lower(), text)

    def test_effects_of_a_new_target(self):
        items = self.advisor.effects(self.inputs(revision=1), self.inputs(revision=2, target_ktpa=1200))["items"]
        self.assertEqual(items[-1]["id"], "economics")
        self.assertIn("капитальные затраты не раскрыты", items[-1]["text"])
        same = self.advisor.effects(self.inputs(revision=1), self.inputs(revision=2, m_haul=1))["items"]
        self.assertNotIn("economics", [item["id"] for item in same])


class TestCalibrationHonesty(AdvisorCase):
    """Fix round 2, item 5: basis and source of every row, simulator values, out-of-sample checks."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.rows = cls.advisor.report(cls.base)["calibration"]

    def by_id(self, check_id):
        return [row for row in self.rows if row["id"] == check_id]

    def test_basis_of_each_row(self):
        fit = {"C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C10"}
        independent = {"C9", "C12", "C13", "C14", "C15", "C16"}
        for row in self.rows:
            want = "fit" if row["id"] in fit else "independent" if row["id"] in independent else "identity"
            self.assertEqual(row["basis"], want, row["id"])
            self.assertEqual(row["basis_name"], {"fit": "подгонка", "independent": "независимая",
                                                 "identity": "тождество"}[want])
            self.assertRegex(row["basis_note"], CYRILLIC)
        self.assertIn("норма Онтарио (Reg. 854, s.183.1(1))", self.by_id("C6")[0]["basis_note"])
        self.assertIn("приложение 25-1", self.by_id("C7")[0]["basis_note"])

    def test_every_row_has_a_source(self):
        for row in self.rows:
            self.assertTrue(row["source"], row["id"])
            if row["basis"] != "identity":
                self.assertTrue(row["source"].startswith("факты "), row)
                self.assertTrue(row["source_urls"] and all(u.startswith("https://") for u in row["source_urls"]),
                                row["id"])
        self.assertEqual(self.by_id("C1")[0]["source_urls"],
                         ["https://www.investegate.co.uk/announcement/bzw/altyngold--altn/annual-financial-report/9542769"])
        self.assertIn("«Fresh air, planned»", self.by_id("C6")[0]["source"])

    def test_simulator_rows_have_values_from_a_run(self):
        sim = [row for row in self.rows if row["kind"] == "simulator"]
        self.assertEqual([row["id"] for row in sim], ["C3", "C8", "C11", "C11"])
        for row in sim:
            self.assertIsNotNone(row["model"], row["id"])
            self.assertTrue(row["passed"], row)
            self.assertIn("прогон симулятора 60 сут базового режима (зерно 53)", row["run"])
        self.assertWithin(self.by_id("C3")[0]["model"], 926422, 3.0)
        self.assertWithin(self.by_id("C8")[0]["model"], 1000000, 3.0)

    def test_out_of_sample_checks(self):
        c13, c14, c15, c16 = (self.by_id(f"C{n}")[0] for n in (13, 14, 15, 16))
        self.assertEqual((c13["reported"], c13["kind"]), (916402, "out_of_sample"))
        self.assertAlmostEqual(c13["deviation"], 1.06, delta=0.01)
        self.assertTrue(c13["passed"])
        # the guidance is a range: 52-55 koz against 47.8 koz at 1.76 g/t, outside it
        self.assertEqual((c14["reported"], c14["reported_max"]), (52000, 55000))
        self.assertAlmostEqual(c14["model"], 47813, delta=1)
        self.assertAlmostEqual(c14["deviation"], -8.05, delta=0.01)
        self.assertFalse(c14["passed"])
        self.assertIn("1,91–2,01 г/т", c14["basis_note"])
        # two lines in 2024: 666.7 kt/yr in the model against 593.6 kt milled, outside 5 %
        self.assertAlmostEqual(c15["model"], 666666.67, delta=0.01)
        self.assertFalse(c15["passed"])
        self.assertAlmostEqual(c16["deviation"], 0.33, delta=0.01)
        self.assertTrue(c16["passed"])

    def test_air_coefficient_has_a_source(self):
        params = json.loads((TEAM / "model" / "params.json").read_text(encoding="utf-8"))
        source = params["vent.q_diesel"]["source"]
        self.assertIn("Ontario Reg. 854 s.183.1(1)", source)
        self.assertIn("Order No. 352, point 1063", source)
        self.assertIn("Appendix 25-1", source)


class TestStartingStockpile(AdvisorCase):
    """Fix round 2, item 4: the opening stockpile is the sum of the published flows."""

    def test_derivation(self):
        params = json.loads((TEAM / "model" / "params.json").read_text(encoding="utf-8"))
        entry = params["stockpile.start_t"]
        flows = [506050 - 420256, 571035 - 541576, 527231 - 584223, 0, 750045 - 593612, 926422 - 966592,
                 458201 - 498331, 458201 - 498331]   # 2020 ... 2025, H1 2026, H2 2026 at the H1 rate
        self.assertEqual(entry["value"], sum(flows))
        self.assertEqual(sum(flows[:-1]), 134394)       # 30 June 2026
        for text in ("+85,794", "+29,459", "-56,992", "2023 taken as 0", "+156,433", "-40,170",
                     "H2 2026 -40,130 t assumed", "US$24.48m", "lower bound"):
            self.assertIn(text, entry["source"])
        self.assertEqual(self.base.stockpile_t, entry["value"])


# --- the service -----------------------------------------------------------------------------

class FakeSource:
    mode = "test"

    def __init__(self, things=None):
        self.things = things or {}
        self.error = None
        self.reads = 0

    def scenario(self, **features):
        self.things = dict(self.things, scenario=dict(self.things.get("scenario", {}), **features))

    def read(self):
        self.reads += 1
        if self.error:
            raise self.error
        return self.things


class FakePublisher:
    enabled = True

    def __init__(self):
        self.messages = []
        self.accept = True

    def publish(self, topic, payload):
        if not self.accept:
            return False
        self.messages.append((topic, payload))
        return True

    def close(self):
        pass


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class ServiceCase(AdvisorCase):
    def setUp(self):
        self.source = FakeSource({"scenario": {"revision": 0.0, "label": "Базовый режим"}})
        self.publisher = FakePublisher()
        self.clock = FakeClock()
        self.log = []
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.alive = os.path.join(self.tmp.name, "alive")
        self.service = service.AdvisorService(self.advisor, self.source, self.publisher, alive_file=self.alive,
                                              clock=self.clock, log=self.log.append)


class TestServiceLoop(ServiceCase):
    def test_first_pass_computes_publishes_and_logs(self):
        self.assertIsNone(self.service.report)
        self.assertEqual(self.service.tick(), service.POLL_S)
        self.assertEqual(self.service.report["binding_link"], "haulage")
        self.assertEqual(len(self.publisher.messages), 1)
        self.assertEqual(len(self.log), 1)
        self.assertRegex(self.log[0], CYRILLIC)
        self.assertIn("ревизия 0", self.log[0])
        self.assertIn("откатка", self.log[0])
        self.assertTrue(os.path.exists(self.alive))

    def test_published_payload_is_the_ditto_envelope(self):
        self.service.tick()
        topic, payload = self.publisher.messages[0]
        self.assertEqual(topic, "telemetry/sekis/advisor")
        self.assertIsInstance(payload, str)
        envelope = json.loads(payload)
        self.assertEqual(envelope, self.service.envelope)
        TestTwinMessage.setUpClass()
        checker = TestTwinMessage("check")
        values = checker.check(envelope)
        self.assertEqual(values["binding_link"], "haulage")
        self.assertIn('"cap_haulage_ktpa": {"properties": {"value": 926.0}}', payload)  # numbers stay floats
        self.assertIn('"report_revision": {"properties": {"value": 0.0}}', payload)

    def test_recomputes_on_a_new_revision_and_every_30_s(self):
        self.service.tick()
        for _ in range(5):
            self.clock.now += 1
            self.service.tick()
        self.assertEqual(len(self.publisher.messages), 1)       # nothing changed: nothing published
        self.source.scenario(m_haul=1.0, revision=1.0, label="Снято узкое место")
        self.clock.now += 1
        self.service.tick()
        self.assertEqual(len(self.publisher.messages), 2)       # new revision: at once
        self.assertEqual(self.service.report["report_revision"], 1)
        self.assertEqual(self.service.report["binding_link"], "ventilation")   # trucks 06, 07 wait for air
        self.clock.now += 29
        self.service.tick()
        self.assertEqual(len(self.publisher.messages), 2)
        self.clock.now += 1
        self.service.tick()
        self.assertEqual(len(self.publisher.messages), 3)       # 30 s later: refreshed
        self.assertEqual(len(self.log), 3)                      # one line per recomputation

    def test_effects_follow_the_last_scenario_change(self):
        self.service.tick()
        self.assertEqual(self.service.report["effects"]["items"], [])
        self.source.scenario(m_haul=1.0, revision=1.0, label="Снято узкое место")
        self.service.tick()
        effects = self.service.report["effects"]
        self.assertEqual((effects["before_revision"], effects["revision"], effects["before_label"]),
                         (0, 1, "Базовый режим"))
        ids = [item["id"] for item in effects["items"]]
        self.assertIn("cap_haulage_ktpa", ids)
        self.clock.now += 31                                     # a refresh keeps the list of the last change
        self.service.tick()
        self.assertEqual([item["id"] for item in self.service.report["effects"]["items"]], ids)
        self.source.scenario(revision=2.0, label="Без изменений")
        self.service.tick()
        self.assertEqual(self.service.report["effects"]["items"], [])   # a revision that changed nothing

    def test_flooded_level_is_reported_without_a_new_revision(self):
        self.source.scenario(pumps_failed_p150=3.0, revision=1.0)
        self.service.tick()
        self.assertEqual(self.service.report["binding_link"], "haulage")
        self.source.things = dict(self.source.things, **{"lvl-m050": {"state": "flooded"},
                                                         "lvl-000": {"state": "flooded"}})
        self.clock.now += 1
        self.service.tick()
        self.assertEqual(self.service.report["binding_link"], "dewatering")
        self.assertEqual(len(self.publisher.messages), 2)

    def test_survives_a_source_that_does_not_answer(self):
        self.service.tick()
        self.source.error = service.SourceError("нет ответа")
        pauses = [self.service.tick() for _ in range(8)]
        self.assertEqual(pauses[:5], [1.0, 2.0, 4.0, 8.0, 15.0])
        self.assertEqual(max(pauses), service.BACKOFF_MAX_S)
        self.assertLess(service.BACKOFF_MAX_S, 30)               # the health file stays fresh
        self.assertEqual(self.service.report["binding_link"], "haulage")   # the last report stays
        self.assertEqual(sum("не прочитаны" in line for line in self.log), 1)   # the failure is logged once
        self.source.error = RuntimeError("defect in the source")
        self.assertGreater(self.service.tick(), 0)               # no exception leaves the loop
        self.source.error = None
        self.source.scenario(m_haul=1.0, revision=1.0)
        self.assertEqual(self.service.tick(), service.POLL_S)
        self.assertEqual(self.service.report["report_revision"], 1)
        self.assertTrue(any("восстановлено" in line for line in self.log))

    def test_survives_a_broker_that_does_not_answer(self):
        self.publisher.accept = False
        self.service.tick()
        self.assertEqual(self.publisher.messages, [])
        self.assertEqual(self.service.report["binding_link"], "haulage")   # the report is served anyway
        self.assertIn("брокер недоступен", self.log[0])
        self.clock.now += 1
        self.service.tick()
        self.publisher.accept = True
        self.clock.now += 1
        self.service.tick()                                       # sent as soon as the broker is back
        self.assertEqual(len(self.publisher.messages), 1)
        self.clock.now += 1
        self.service.tick()
        self.assertEqual(len(self.publisher.messages), 1)
        self.assertEqual(len(self.log), 1)

        def broken(topic, payload):
            raise OSError("socket closed")
        self.publisher.publish = broken
        self.clock.now += 30
        self.service.tick()                                       # an exception in the client is contained

    def test_rejected_scenario_keeps_the_last_report(self):
        self.service.tick()
        self.source.scenario(tu1_closed=1.0, tu2_closed=1.0, revision=1.0)
        self.assertEqual(self.service.tick(), service.POLL_S)
        self.assertEqual(self.service.report["report_revision"], 0)
        self.assertIn("отклонён", self.log[-1])
        self.assertEqual(len(self.publisher.messages), 1)

    def test_apply_reads_the_scenario_afresh(self):
        self.service.tick()
        self.source.scenario(m_haul=1.0, target_ktpa=1200.0, m_plant=1.0, revision=1.0)   # not yet seen by tick()
        self.assertEqual(self.service.apply("next")["changes"], {"m_vent": 1.0})
        self.source.error = service.SourceError("нет ответа")
        self.assertEqual(self.service.apply("next")["changes"], {"m_haul": 1.0})   # falls back to the report's inputs
        given = self.service.apply("next", knobs={"fan_vs2_off": {"properties": {"value": 1.0}}})
        self.assertEqual(given["changes"], {"fan_vs2_off": 0.0})          # the failed fan is restored first

    def test_apply_before_any_reading(self):
        self.source.error = service.SourceError("нет ответа")
        with self.assertRaises(service.NotReady):
            self.service.apply("next")

    def test_run_stops_on_the_event(self):
        stop = threading.Event()
        runner = service.AdvisorService(self.advisor, self.source, self.publisher, alive_file=self.alive,
                                        log=self.log.append)
        thread = threading.Thread(target=runner.run, args=(stop,))
        thread.start()
        deadline = time.monotonic() + 10
        while runner.report is None and time.monotonic() < deadline:
            time.sleep(0.02)
        stop.set()
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertIsNotNone(runner.report)


class TestSources(AdvisorCase):
    def test_accepted_documents_give_the_same_things(self):
        ditto = [{"thingId": "kz.sekis:scenario", "features": {"m_haul": {"properties": {"value": 2.0}},
                                                               "revision": {"properties": {"value": 5.0}}}},
                 {"thingId": "kz.sekis:lvl-000", "features": {"state": {"properties": {"value": "flooded"}}}}]
        stand = {"sim_time": "x", "things": {"kz.sekis:scenario": {"kind": "scenario_control",
                                                                    "f": {"m_haul": 2.0, "revision": 5.0}},
                                              "kz.sekis:lvl-000": {"f": {"state": "flooded"}}}}
        expected = {"scenario": {"m_haul": 2.0, "revision": 5.0}, "lvl-000": {"state": "flooded"}}
        self.assertEqual(service.plain_things(ditto), expected)
        self.assertEqual(service.plain_things({"things": ditto}), expected)
        self.assertEqual(service.plain_things(stand), expected)
        inputs = self.advisor.inputs_from_things(expected)
        self.assertEqual((inputs.knobs["m_haul"], inputs.revision, inputs.flooded_levels), (2.0, 5, ("lvl-000",)))

    def test_registry_is_a_fixture_of_the_epoch(self):
        things = service.plain_things(json.loads(REGISTRY.read_text(encoding="utf-8")))
        inputs = self.advisor.inputs_from_things(things)
        self.assertEqual(inputs.sim_time, "2027-01-01T09:30:00")
        self.assertEqual(replace(inputs, sim_time=None), self.base)

    def test_fixture_file_is_reread_when_it_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "state.json")
            Path(path).write_text(json.dumps({"things": {"kz.sekis:scenario": {"f": {"revision": 1}}}}),
                                  encoding="utf-8")
            source = service.FixtureSource(path)
            self.assertEqual(source.read()["scenario"], {"revision": 1})
            Path(path).write_text(json.dumps({"things": {"kz.sekis:scenario": {"f": {"revision": 2, "m_haul": 1}}}}),
                                  encoding="utf-8")
            self.assertEqual(source.read()["scenario"], {"revision": 2, "m_haul": 1})
            Path(path).write_text("{not json", encoding="utf-8")
            with self.assertRaises(service.SourceError):
                source.read()
            with self.assertRaises(service.SourceError):
                service.FixtureSource(os.path.join(folder, "missing.json")).read()
        self.assertEqual(service.FixtureSource(None).read(), {})

    def test_ditto_source_asks_for_the_things_it_needs_in_one_request(self):
        calls = []

        class Client:
            def request(self, method, path, body=None, allow_404=False):
                calls.append((method, path))
                return 200, [{"thingId": "kz.sekis:scenario",
                              "features": {"revision": {"properties": {"value": 3.0}}}}]

        names = self.advisor.thing_names()
        self.assertEqual(len(names), 3 + 12 + 4)   # scenario, stockpile, clock, the levels, the dams
        source = service.DittoSource(names, client=Client())
        self.assertEqual(source.read(), {"scenario": {"revision": 3.0}})
        self.assertEqual(len(calls), 1)
        method, path = calls[0]
        self.assertEqual(method, "GET")
        self.assertTrue(path.startswith("things?ids=kz.sekis:scenario,"))
        self.assertIn("kz.sekis:rom-stockpile", path)
        self.assertIn("kz.sekis:lvl-m050", path)
        self.assertIn("kz.sekis:tsf-cell5", path)
        self.assertTrue(path.endswith("&fields=thingId,features"))

    def test_ditto_source_failures_are_source_errors(self):
        from sekis import ditto

        class Down:
            def request(self, *args, **kwargs):
                raise ditto.DittoError("GET things: нет ответа")

        class Empty:
            def request(self, *args, **kwargs):
                return 200, []

        for client in (Down(), Empty()):
            with self.assertRaises(service.SourceError):
                service.DittoSource(["scenario"], client=client).read()
        with self.assertRaises(service.SourceError) as caught:
            service.DittoSource(["scenario"], client=Down()).read()
        self.assertEqual(str(caught.exception), "Ditto: нет ответа")
        saved = os.environ.pop("DITTO_PASSWORD", None)
        try:
            with self.assertRaises(service.SourceError):     # no credentials: an error to retry, not a crash
                service.DittoSource(["scenario"]).read()
        finally:
            if saved is not None:
                os.environ["DITTO_PASSWORD"] = saved

    def test_mqtt_publisher_without_a_broker(self):
        need_paho(self)
        log = []
        publisher = service.MqttPublisher("127.0.0.1", free_port(), log.append)   # nothing listens there
        try:
            self.assertFalse(publisher.publish("telemetry/sekis/advisor", "{}"))
        finally:
            publisher.close()

    def test_mqtt_publisher_delivers_the_message_to_a_broker(self):
        need_paho(self)
        broker = OneClientBroker()
        self.addCleanup(broker.close)
        log = []
        publisher = service.MqttPublisher("127.0.0.1", broker.port, log.append)
        self.addCleanup(publisher.close)
        source = FakeSource({"scenario": {"revision": 2.0, "label": "ход"}})
        runner = service.AdvisorService(self.advisor, source, publisher, log=log.append)
        deadline = time.monotonic() + 10
        while not broker.messages and time.monotonic() < deadline:
            runner.tick()                      # the first passes may come before the connection is up
            time.sleep(0.05)
        self.assertTrue(broker.messages, log)
        topic, payload = broker.messages[0]
        self.assertEqual(topic, "telemetry/sekis/advisor")
        envelope = json.loads(payload.decode("utf-8"))
        self.assertEqual(envelope, runner.envelope)
        self.assertEqual(envelope["topic"], "kz.sekis/advisor/things/twin/commands/modify")
        self.assertEqual(envelope["value"]["report_revision"]["properties"]["value"], 2.0)
        self.assertEqual(len(broker.messages), 1)   # the message is sent once, not on every pass
        self.assertTrue(any("подключено" in line for line in log))


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def need_paho(test):
    try:
        import paho.mqtt.client  # noqa: F401
    except ImportError:
        test.skipTest("paho-mqtt is not installed")


class OneClientBroker:
    """The part of an MQTT 3.1.1 broker one publishing client needs: CONNACK, PUBLISH at QoS 0, PINGRESP."""

    def __init__(self):
        self.messages = []
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self.serve, daemon=True).start()

    def close(self):
        self.sock.close()

    @staticmethod
    def packet(conn):
        head = conn.recv(1)
        if not head:
            return None, b""
        length, shift = 0, 0
        while True:
            byte = conn.recv(1)[0]
            length |= (byte & 0x7F) << shift
            shift += 7
            if not byte & 0x80:
                break
        body = b""
        while len(body) < length:
            chunk = conn.recv(length - len(body))
            if not chunk:
                return None, b""
            body += chunk
        return head[0] >> 4, body

    def serve(self):
        try:
            conn, _ = self.sock.accept()
            with conn:
                conn.settimeout(15)
                while True:
                    kind, body = self.packet(conn)
                    if kind == 1:        # CONNECT
                        conn.sendall(bytes([0x20, 0x02, 0x00, 0x00]))
                    elif kind == 3:      # PUBLISH, QoS 0: topic length, topic, payload
                        size = int.from_bytes(body[:2], "big")
                        self.messages.append((body[2:2 + size].decode("utf-8"), body[2 + size:]))
                    elif kind == 12:     # PINGREQ
                        conn.sendall(bytes([0xD0, 0x00]))
                    else:                # DISCONNECT or a closed socket
                        return
        except OSError:
            pass


def http(method, url, body=None, timeout=10):
    """(status, parsed JSON, content type) of a real HTTP request."""
    data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode("utf-8"))
    request = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8")), response.headers["Content-Type"]
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8")), exc.headers["Content-Type"]


def write_fixture(path, **scenario):
    features = dict({"revision": 0, "label": "Базовый режим"}, **scenario)
    Path(path).write_text(json.dumps({"things": {"kz.sekis:scenario": {"f": features}}}, ensure_ascii=False),
                          encoding="utf-8")


class TestHttp(AdvisorCase):
    """GET /report and POST /apply over real HTTP on a free port against a fixture state."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.fixture = os.path.join(self.tmp.name, "state.json")
        write_fixture(self.fixture, target_ktpa=1200, m_plant=1, revision=3, label="Цель 1,2 млн т/год")
        self.service = service.AdvisorService(self.advisor, service.FixtureSource(self.fixture),
                                              service.NullPublisher(), log=lambda message: None)
        self.server = service.make_server(self.service, "127.0.0.1", 0)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def test_not_ready_before_the_first_pass(self):
        status, body, _ = http("GET", self.url + "/report")
        self.assertEqual((status, body["error"]), (503, "report_not_ready"))
        self.assertEqual(http("GET", self.url + "/healthz")[0], 503)

    def test_report(self):
        self.service.tick()
        status, report, content_type = http("GET", self.url + "/report")
        self.assertEqual(status, 200)
        self.assertEqual(content_type, "application/json; charset=utf-8")
        self.assertEqual(set(report), REPORT_KEYS)
        self.assertEqual((report["report_revision"], report["label"]), (3, "Цель 1,2 млн т/год"))
        self.assertEqual((report["target_ktpa"], report["binding_link"], report["achievable_ktpa"]),
                         (1200, "haulage", 926))
        self.assertEqual([row["target_ktpa"] for row in report["ladder"]], [1000, 1200, 2000, 2500])
        self.assertEqual([row["sequence"] for row in report["ladder"]], list(SEQUENCES.values()))
        self.assertEqual(len(report["projection"]["rows"]), 10)
        self.assertEqual(len(report["links"]), 8)
        self.assertTrue(all(row["passed"] for row in report["calibration"] if row["kind"] != "out_of_sample"))
        self.assertEqual(report["links"][0]["name"], "Откатка")   # UTF-8 on the wire
        self.assertEqual(report, json.loads(json.dumps(self.service.report)))

    def test_apply(self):
        self.service.tick()
        status, answer, _ = http("POST", self.url + "/apply", {"mode": "next"})
        self.assertEqual((status, answer["changes"], answer["mode"]), (200, {"m_haul": 1.0}, "next"))
        status, answer, _ = http("POST", self.url + "/apply", {"mode": "all"})
        self.assertEqual(status, 200)
        self.assertEqual(answer["changes"], {"m_haul": 1.0, "m_water": 1.0, "m_stopes": 1.0, "m_vent": 1.0,
                                             "m_tailings": 1.0})
        self.assertEqual(len(answer["steps"]), 5)
        status, answer, _ = http("POST", self.url + "/apply", {"mode": "next", "knobs": {"m_haul": 1}})
        self.assertEqual((status, answer["changes"]), (200, {"m_vent": 1.0}))

    def test_apply_sees_a_scenario_written_just_before(self):
        self.service.tick()
        write_fixture(self.fixture, target_ktpa=1200, m_plant=1, m_haul=1, m_vent=1, m_water=1, revision=5)
        status, answer, _ = http("POST", self.url + "/apply", {"mode": "next"})
        self.assertEqual((status, answer["changes"], answer["revision"]), (200, {"m_stopes": 1.0}, 5))

    def test_bad_requests(self):
        self.service.tick()
        self.assertEqual(http("POST", self.url + "/apply", {"mode": "some"})[0], 400)
        self.assertEqual(http("POST", self.url + "/apply", {})[0], 400)
        self.assertEqual(http("POST", self.url + "/apply", b"{not json")[0], 400)
        self.assertEqual(http("POST", self.url + "/apply", [1, 2])[0], 400)
        status, body, _ = http("POST", self.url + "/apply", {"mode": "next", "knobs": {"tu1_closed": 1,
                                                                                       "tu2_closed": 1}})
        self.assertEqual((status, body["error"]), (409, "scenario_rejected"))
        self.assertEqual(http("GET", self.url + "/nothing")[0], 404)
        self.assertEqual(http("POST", self.url + "/report", {})[0], 404)
        for _, body, _ in (http("GET", self.url + "/nothing"), http("POST", self.url + "/apply", {})):
            self.assertRegex(body["message"], CYRILLIC)

    def test_features_and_health(self):
        self.service.tick()
        status, envelope, _ = http("GET", self.url + "/features")
        self.assertEqual((status, envelope["path"]), (200, "/features"))
        self.assertEqual(envelope["value"]["binding_link"]["properties"]["value"], "haulage")
        status, health, _ = http("GET", self.url + "/healthz")
        self.assertEqual((status, health["status"], health["mode"], health["report_revision"]),
                         (200, "ok", "fixture", 3))


class TestProcess(unittest.TestCase):
    """``python -m sekis.advisor.service`` in fixture mode: no Ditto, no broker."""

    def test_service_starts_and_answers(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = os.path.join(folder, "state.json")
            alive = os.path.join(folder, "alive")
            write_fixture(fixture, target_ktpa=2000, m_plant=2, revision=9, label="Цель 2,0 млн т/год")
            port = free_port()
            env = dict(os.environ, PYTHONIOENCODING="utf-8", ADVISOR_FIXTURE=fixture, ADVISOR_PORT=str(port),
                       ADVISOR_HOST="127.0.0.1", ALIVE_FILE=alive)
            for name in ("DITTO_URL", "DITTO_PASSWORD", "MQTT_HOST"):
                env.pop(name, None)
            process = subprocess.Popen([sys.executable, "-m", "sekis.advisor.service"], cwd=str(TEAM), env=env,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            try:
                url = f"http://127.0.0.1:{port}"
                report, deadline = None, time.monotonic() + 30
                while report is None and time.monotonic() < deadline:
                    self.assertIsNone(process.poll(), "the service exited")
                    try:
                        status, body, _ = http("GET", url + "/report", timeout=2)
                        report = body if status == 200 else None
                    except OSError:
                        pass
                    if report is None:
                        time.sleep(0.1)
                self.assertIsNotNone(report, "no report within 30 s")
                self.assertEqual((report["report_revision"], report["target_ktpa"], report["binding_link"]),
                                 (9, 2000, "haulage"))
                status, answer, _ = http("POST", url + "/apply", {"mode": "all"})
                self.assertEqual(status, 200)
                self.assertEqual(answer["changes"], {"m_haul": 2.0, "m_water": 2.0, "m_stopes": 2.0, "m_vent": 2.0,
                                                     "m_tailings": 1.0, "m_dev": 1.0})
                write_fixture(fixture, target_ktpa=2000, revision=10, **FULL[2000])   # the Stand writes the knobs
                deadline = time.monotonic() + 10
                while report["report_revision"] != 10 and time.monotonic() < deadline:
                    time.sleep(0.2)
                    report = http("GET", url + "/report")[1]
                self.assertEqual((report["report_revision"], report["target_reached"], report["binding_link"]),
                                 (10, True, "plant"))
                self.assertTrue(report["effects"]["items"])
                self.assertTrue(os.path.exists(alive))
                self.assertLess(time.time() - os.path.getmtime(alive), 30)
            finally:
                process.terminate()
                output = process.communicate(timeout=10)[0].decode("utf-8", "replace")
            self.assertIn("ревизия 9", output)
            self.assertIn("ревизия 10", output)
            self.assertNotIn("Traceback", output)

    def test_once_prints_a_report(self):
        result = subprocess.run([sys.executable, "-m", "sekis.advisor.service", "--once", "--fixture", "1"],
                                cwd=str(TEAM), env=dict(os.environ, PYTHONIOENCODING="utf-8"),
                                capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        report = json.loads(result.stdout.decode("utf-8"))
        self.assertEqual(set(report), REPORT_KEYS)
        self.assertEqual(report["binding_link"], "haulage")


class TestPackageSource(unittest.TestCase):
    """Spec 0.3: standard library plus paho-mqtt, UTF-8, LF."""

    FILES = sorted(PACKAGE.glob("*.py")) + [Path(__file__)]
    STDLIB = {"__future__", "argparse", "dataclasses", "datetime", "http", "json", "math", "os", "pathlib", "re",
              "signal", "sys", "threading", "time", "typing", "urllib"}

    def test_package_files(self):
        self.assertEqual({path.name for path in PACKAGE.glob("*.py")},
                         {"__init__.py", "engine.py", "service.py", "wording.py"})

    def test_imports(self):
        for path in PACKAGE.glob("*.py"):
            imported = set()
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Import):
                    imported.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    imported.add(node.module.split(".")[0])
            allowed = self.STDLIB | ({"paho"} if path.name == "service.py" else set())
            self.assertLessEqual(imported, allowed, path.name)

    def test_engine_and_wording_do_not_touch_the_network(self):
        for name in ("engine.py", "wording.py"):
            source = (PACKAGE / name).read_text(encoding="utf-8")
            for module in ("urllib", "http", "socket", "paho", "ditto"):
                self.assertNotRegex(source, rf"import\s+{module}|from\s+\S*{module}\S*\s+import", name)

    def test_files_utf8_lf_no_bom(self):
        for path in self.FILES:
            raw = path.read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), path.name)
            self.assertNotIn(b"\r", raw, path.name)
            raw.decode("utf-8")
            self.assertTrue(raw.endswith(b"\n"), path.name)


if __name__ == "__main__":
    unittest.main()
