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

#: Every level the water reaches below the TU2 portal, lowest first (capacity.flood_order).
FLOOD_ORDER = ("lvl-m050", "lvl-000", "lvl-p050", "lvl-p100", "lvl-p150", "lvl-p200", "lvl-p250")

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
             "cap_before_ktpa", "cap_after_ktpa", "lead_years", "in_service_year", "in_service_when",
             "in_service_text", "deferred_from", "deferred_when", "in_horizon"}
KPI_KEYS = {
    "gold_koz_year", "gold_gain_koz_year", "grade_gpt", "recovery_pct", "air_demand_m3s", "air_supply_m3s",
    "air_margin_pct", "air_used_m3s", "air_spare_m3s", "units_held_vent", "water_deficit_m3h", "discharge_m3h", "permit_m3h", "permit_use_pct", "tailings_free_kt",
    "tailings_years_left", "stockpile_t", "stockpile_days_left", "stockpile_mine_tpd", "stockpile_plant_tpd",
    "stockpile_net_tpd", "stockpile_trend", "dewatering_margin", "dewatering_margin_next_failure", "pumps_standby",
    "dewatering_reserve", "water_deficit_all_lines_m3h", "discharge_all_lines_m3h", "permit_use_all_lines_pct",
    "water_basis",
}
# The opening ROM stockpile (params.json stockpile.start_t, derivation in its source) and the days it
# lasts at the baseline draw: 1000 kt/yr over 365 days less 926.1 kt/yr over 360 days = 167 t/day.
STOCKPILE_T, STOCKPILE_DAYS = 94264, 564
CALIBRATION_ROW_KEYS = {
    "id", "case", "title", "kind", "kind_name", "basis", "basis_name", "basis_note", "unit", "reported",
    "reported_max", "model", "deviation", "deviation_unit", "tolerance", "passed", "reference", "source",
    "source_urls",
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
            # water at the rates of the twins (decision 11.4): for 1000 the mine hoists 1024 kt/yr against the
            # 1000 the plant mills, and the site water of the extra ore is 2.6 m3/h more than the mine gives
            if target == 1000:
                self.assertWithin(row["water_deficit_m3h"], 2.6, 0.1)
            else:
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


PROJECTION_ROW_KEYS = {
    "year", "achievable_ktpa", "mined_ktpa", "binding_link", "binding_link_name", "mine_link", "mine_link_name",
    "mine_ktpa", "target_met", "centroid_m", "gold_oz", "gold_koz", "gold_total_koz", "tailings_stored_kt",
    "tailings_free_kt", "tailings_years_left", "water_deficit_m3h", "stockpile_kt", "trucks", "halves", "measures",
    "storage_short_kt", "note",
}
HORIZON_KEYS = {
    "first_year", "last_year", "target_ktpa", "schedule", "sequence_schedule", "rows", "binding_runs", "trucks_end",
    "depth_trucks", "trucks_beyond_registry", "storage_runs_out_year", "target_missed_year", "gold_total_koz",
    "depth_rule", "storage_short_kt", "storage_note", "reached_year", "held_to_year", "holds", "lost_year",
    "again_year", "lost_link", "lost_link_name", "failure_year", "failure_link", "failure_ktpa", "best_year",
    "best_ktpa", "label", "text",
}
# The horizon of the four targets from the baseline (spec 3.4, section 11 items 3 and 5): the first year
# the target is met, the last year of that run, the link that ends it (for a target never met: the link of
# the year that came closest) and the link with no stage left (2.0 Mtpa: in 2036, the stockpile makes it up).
HOLD = {1000: (2027, 2036, None, None), 1200: (2028, 2036, None, None),
        2000: (2030, 2036, None, "ventilation"), 2500: (None, None, "haulage", "ventilation")}
BINDING_BY_YEAR = {
    1000: ["plant"] * 10,
    1200: ["plant"] * 10,
    2000: ["plant", "plant", "haulage"] + ["plant"] * 7,
    2500: ["plant", "plant"] + ["haulage"] * 8,
}
# Ore milled by year (kt), 2027-2036: no year below the mine as it is (1000, 883, ... 712 kt).
MILLED = {2000: [1004, 1200, 1712] + [2000] * 7,
          2500: [1004, 1200, 1962, 2479, 2286, 2151, 2038, 1941, 1857, 1783]}


class TestProjection(AdvisorCase):
    """Spec 3.4 step 5: the horizon of the current state, 2027-2036, with lead times."""

    def rows(self, **knobs):
        projection = self.report(**knobs)["projection"]
        return projection, projection["rows"]

    def test_ten_rows_2027_to_2036(self):
        projection, rows = self.rows()
        self.assertEqual([row["year"] for row in rows], list(range(2027, 2037)))
        self.assertEqual((projection["first_year"], projection["last_year"]), (2027, 2036))
        self.assertEqual(set(projection), HORIZON_KEYS | {"economics"})
        for row in rows:
            self.assertEqual(set(row), PROJECTION_ROW_KEYS)
            self.assertEqual(len(row["halves"]), 2)

    def test_first_year_draws_the_stockpile(self):
        # trucks 06-07 come into service with the VPV fan in 2028; the plant mills 1000 kt from 926 kt
        # hoisted and the opening stockpile (94.3 kt) falls by the difference
        _, rows = self.rows()
        first = rows[0]
        self.assertEqual((first["achievable_ktpa"], first["binding_link"], first["target_met"]), (1000, "plant", True))
        # the five trucks of the baseline hoist it, a little below 926 kt as the centroid drops 18 m in the year
        reference = self.advisor.horizon.reference(cap.State(), STOCKPILE_T)["rows"][0]
        self.assertEqual(first["mined_ktpa"], reference["mined_ktpa"])
        self.assertAlmostEqual(first["mined_ktpa"], BASELINE_KTPA - 16, delta=3)
        self.assertAlmostEqual(first["stockpile_kt"], STOCKPILE_T / 1000 - (1000 - first["mined_ktpa"]), delta=1.5)
        self.assertAlmostEqual(first["gold_koz"], GOLD_KOZ[1000], delta=0.05)

    def test_tailings_fill_with_the_ore_milled(self):
        for knobs in ({}, dict(target_ktpa=1200, **FULL[1200]), dict(target_ktpa=2500, **FULL[2500])):
            projection, rows = self.rows(**knobs)
            stored = [row["tailings_stored_kt"] for row in rows]
            self.assertEqual(stored, sorted(stored))
            free_start = 3172 + 2863.755   # dam 4 at 90 %, dams 2 and 3 empty: stored + free at the epoch
            self.assertAlmostEqual(stored[0] - rows[0]["achievable_ktpa"], 2863.755, delta=1.5)
            for before, row in zip(rows, rows[1:]):   # what is milled in a year is what the dams take
                self.assertAlmostEqual(row["tailings_stored_kt"] - before["tailings_stored_kt"], row["achievable_ktpa"],
                                       delta=1.5)
            for row in rows:
                self.assertGreaterEqual(row["tailings_free_kt"], 0)
            added = sum(e["storage_kt"] for e in projection["schedule"])
            self.assertAlmostEqual(stored[-1] + rows[-1]["tailings_free_kt"], free_start + added, delta=1.5)

    def test_measures_enter_service_after_their_lead_time(self):
        for row in self.advisor.report(self.base)["ladder"]:
            last, last_ready = {}, {}
            for entry in row["horizon"]["schedule"]:
                self.assertGreaterEqual(entry["time"] + 1e-9, 2027 + entry["lead_years"], entry)
                self.assertAlmostEqual(entry["time"] * 2, round(entry["time"] * 2), msg=entry)   # half-year grid
                self.assertAlmostEqual(entry["decided"], entry["time"] - entry["lead_years"])
                self.assertGreaterEqual(entry["decided"], 2027)
                ready = entry["time"] if entry["deferred_from"] is None else entry["deferred_from"]
                if entry["origin"] == "ladder" and entry["kind"] == "measure":   # decided at the epoch
                    self.assertEqual(ready, max(2027 + entry["lead_years"], last_ready.get(entry["knob"], 2027)))
                if entry["deferred_from"] is not None:   # trucks and LHDs that wait for their air
                    self.assertIn(entry["knob"] or entry["kind"], ("m_haul", "m_stopes", "depth_truck"))
                    self.assertGreater(entry["time"], entry["deferred_from"])
                if entry["knob"]:
                    self.assertGreaterEqual(entry["time"], last.get(entry["knob"], 2027))
                    last[entry["knob"]], last_ready[entry["knob"]] = entry["time"], ready
            for step in row["steps"]:      # the ladder text says when each step would really be available
                self.assertIn("в работе с", step["in_service_text"])
                self.assertTrue(step["in_horizon"])
                ready = step["in_service_year"] if step["deferred_from"] is None else step["deferred_from"]
                self.assertEqual(ready, 2027 + step["lead_years"])
        params = json.loads((TEAM / "model" / "params.json").read_text(encoding="utf-8"))
        self.assertEqual(params["ladder.m_plant.lead_years"]["value"], [0, 0.5, 2.0, 2.0])
        self.assertIn("'within 24 months'", params["ladder.m_plant.lead_years"]["source"])
        self.assertEqual(params["ladder.m_vent.lead_years"]["value"], [0, 1.0, 2.5])

    def test_lead_times_shift_the_projection(self):
        params = json.loads((TEAM / "model" / "params.json").read_text(encoding="utf-8"))

        def hold_of(changes, target=2000):
            changed = json.loads(json.dumps(params))
            for pid, value in changes.items():
                changed[pid]["value"] = value
            adv = Advisor(params=changed)
            inputs = replace(adv.default_inputs().with_knobs({"target_ktpa": target}), revision=1)
            return adv.report(inputs)["projection"]

        default = hold_of({})
        late = hold_of({"ladder.m_plant.lead_years": [0, 0.5, 3.5, 3.5]})
        zero = hold_of({f"ladder.{knob}.lead_years": [0] * len(params[f"ladder.{knob}.lead_years"]["value"])
                        for knob in cap.KNOBS})
        self.assertEqual(default["reached_year"], 2030)
        self.assertEqual(late["reached_year"], 2031)            # lines 4-5 in mid-2030 instead of 2029
        self.assertEqual(zero["reached_year"], 2027)            # every measure at once, as on the Stand
        self.assertLess(late["gold_total_koz"], default["gold_total_koz"] + 1e-9)
        plant = [e for e in late["schedule"] if e["knob"] == "m_plant" and e["stage"] == 2][0]
        self.assertEqual(plant["time"], 2030.5)
        self.assertEqual([r["achievable_ktpa"] for r in zero["rows"]][:2], [2000, 2000])

    def test_depth_lowers_haulage_and_trucks_keep_pace(self):
        reference = self.advisor.horizon.reference(cap.State(), STOCKPILE_T)["rows"]
        centroids = [row["centroid_m"] for row in reference]
        self.assertEqual(centroids, sorted(centroids, reverse=True))
        rates = [row["achievable_ktpa"] for row in reference[1:]]
        self.assertEqual(rates, sorted(rates, reverse=True))           # the five trucks of the baseline
        self.assertTrue(all(row["binding_link"] == "haulage" for row in reference[1:]))
        self.assertEqual(rates, [883, 852, 827, 804, 782, 763, 744, 728, 712])
        for before, row in zip(reference, reference[1:]):              # ore / 51 462 t per metre
            self.assertAlmostEqual(before["centroid_m"] - row["centroid_m"], row["mined_ktpa"] * 1000 / 51462, delta=0.2)
        # spec 2.3: 926 -> 841 -> 770 kt/yr at +75, +25, -25 m
        self.assertLess(reference[-1]["achievable_ktpa"], 770)
        horizon = {row["target_ktpa"]: row["horizon"] for row in self.advisor.report(self.base)["ladder"]}
        trucks = [row["trucks"] for row in horizon[2000]["rows"]]
        self.assertEqual(trucks, sorted(trucks))
        # the five of the baseline until the VPV fan, ten with shaft VS-3 in mid-2029, then one at a time
        self.assertEqual(trucks, [5, 7, 11, 12, 13, 13, 14, 15, 15, 15])
        rule = horizon[2000]["depth_rule"]
        self.assertEqual((rule["fleet_trucks"], rule["model"]), (10, "AD45"))
        self.assertAlmostEqual(rule["metres_per_truck"], 58, delta=2)
        self.assertIn("≈58 м понижения центра добычи", rule["text"])

    def test_the_projection_of_a_full_set_is_its_ladder_row(self):
        for target in (1000, 2500):
            knobs = {} if target == 1000 else FULL[2500]
            report = self.report(target_ktpa=target, **knobs)
            row = next(r for r in self.advisor.report(self.base)["ladder"] if r["target_ktpa"] == target)
            def plain(rows):
                return [{k: v for k, v in r.items() if k != "measures"} for r in rows]

            def when(rows):
                return [sorted((m["time"], m["kind"], m["link"], m["stage"]) for m in r["measures"]) for r in rows]
            self.assertEqual(plain(report["projection"]["rows"]), plain(row["horizon"]["rows"]), target)
            self.assertEqual(when(report["projection"]["rows"]), when(row["horizon"]["rows"]))
            self.assertEqual(report["projection"]["label"], row["horizon"]["label"])
            self.assertEqual(report["projection"]["economics"]["variants"], row["economics"]["variants"])

    def test_gold_accumulates(self):
        projection, rows = self.rows(target_ktpa=1200, **FULL[1200])
        self.assertAlmostEqual(rows[-1]["gold_total_koz"], sum(row["gold_koz"] for row in rows), delta=0.1)
        self.assertEqual(projection["gold_total_koz"], rows[-1]["gold_total_koz"])
        totals = [row["gold_total_koz"] for row in rows]
        self.assertEqual(totals, sorted(totals))


class TestHorizon(AdvisorCase):
    """Spec section 11 items 3 and 5: each target held over 2027-2036, or why it is not."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ladder = {row["target_ktpa"]: row for row in cls.advisor.report(cls.base)["ladder"]}

    def test_hold_years_of_the_four_targets(self):
        for target, (reached, held_to, lost_link, failure) in HOLD.items():
            horizon = self.ladder[target]["horizon"]
            self.assertEqual(set(horizon), HORIZON_KEYS, target)
            self.assertEqual((horizon["reached_year"], horizon["held_to_year"]), (reached, held_to), target)
            self.assertEqual(horizon["holds"], held_to == 2036, target)
            self.assertEqual((horizon["lost_link"], horizon["failure_link"]), (lost_link, failure), target)
            if reached is None:
                self.assertEqual(horizon["label"], "не достигается до 2036 г.")
            else:
                self.assertEqual(horizon["label"], f"держится до {held_to} г.")
                self.assertTrue(horizon["text"].startswith(f"Цель {wording.num(target)} тыс. т/год достигается в "
                                                           f"{reached} г. и держится до {held_to} г."), target)
        # 2.0 Mtpa holds, but in 2036 a sixth AD45 would wait for air and the ROM stockpile makes up the feed
        horizon = self.ladder[2000]["horizon"]
        self.assertEqual((horizon["failure_year"], horizon["failure_ktpa"]), (2036, 1965))
        self.assertTrue(horizon["text"].endswith(
            f"С 2036 г. рудник выдаёт меньше цели, {wording.num(1965)} тыс. т/год: воздуха на новые самосвалы не "
            f"хватает, а все ступени вентиляции уже введены (ствол ВС-3); в 2036 г. фабрику добирает рудный склад."),
            horizon["text"])
        self.assertEqual(horizon["rows"][-1]["mined_ktpa"], 1944)
        for target in (1000, 1200):
            self.assertIsNone(self.ladder[target]["horizon"]["failure_year"])
        # 2.5 Mtpa comes closest in 2030: haulage at depth needs a third AD45 that shaft VS-3 cannot ventilate
        horizon = self.ladder[2500]["horizon"]
        self.assertEqual((horizon["best_year"], horizon["best_ktpa"], horizon["failure_year"]), (2030, 2479, 2030))
        self.assertEqual(horizon["text"], f"Цель {wording.num(2500)} тыс. т/год не достигается до 2036 г.: ближе всего "
                                          f"в 2030 г., узкое место — откатка ({wording.num(2479)} тыс. т за год): "
                                          f"воздуха на новые самосвалы не хватает, а все ступени вентиляции уже "
                                          f"введены (ствол ВС-3).")

    def test_binding_link_by_year(self):
        for target, links in BINDING_BY_YEAR.items():
            rows = self.ladder[target]["horizon"]["rows"]
            self.assertEqual([row["binding_link"] for row in rows], links, target)
            reached, held_to = HOLD[target][:2]
            self.assertEqual([row["target_met"] for row in rows],
                             [reached is not None and reached <= row["year"] <= held_to for row in rows], target)
        for target, milled in MILLED.items():
            self.assertEqual([row["achievable_ktpa"] for row in self.ladder[target]["horizon"]["rows"]], milled, target)
        self.assertEqual(self.ladder[2000]["horizon"]["binding_runs"]["text"],
                         "2027–2028: фабрика; 2029: откатка; 2030–2036: фабрика")
        self.assertEqual(self.ladder[2500]["horizon"]["binding_runs"]["text"], "2027–2028: фабрика; 2029–2036: откатка")

    def test_no_year_below_the_mine_as_it_is(self):
        # spec 3.4 step 5.3: no measure cuts the output of the mine and no year mills nothing; checked for
        # the ladder from the baseline and from disturbed states and for the projection of each full set
        cases = [{}, dict(fan_vs2_off=1), dict(line_down=2), dict(tu2_closed=1), dict(grade_gpt=1.76),
                 dict(inflow_factor=2.18), dict(pumps_failed_p150=1), dict(m_haul=2, m_stopes=2)]
        cases += [dict(target_ktpa=target, **knobs) for target, knobs in FULL.items()]
        for knobs in cases:
            with self.subTest(**knobs):
                inputs = self.inputs(**knobs)
                report = self.advisor.report(inputs)
                reference = self.advisor.horizon.reference(self.advisor.state(inputs), inputs.stockpile_t)["rows"]
                for horizon in [row["horizon"] for row in report["ladder"]] + [report["projection"]]:
                    for row, ref in zip(horizon["rows"], reference):
                        self.assertGreaterEqual(row["achievable_ktpa"], ref["achievable_ktpa"] - 1,
                                                (horizon["target_ktpa"], row["year"]))
                        self.assertGreater(row["achievable_ktpa"], 0, (horizon["target_ktpa"], row["year"]))
        reference = self.advisor.horizon.reference(cap.State(), STOCKPILE_T)["rows"]
        self.assertEqual([row["achievable_ktpa"] for row in reference][:2], [1000, 883])
        for target in (2000, 2500):   # the defect: 937 and 809 kt in 2027 while trucks and stopes waited for air
            self.assertEqual(MILLED[target][0], 1004)

    def test_trucks_and_lhds_wait_for_the_air_they_need(self):
        # spec 3.4 step 5.3: a unit measure enters service only when the air admits its units, so in no
        # half-year of a plan does a unit wait for air, and ventilation never limits the mine
        for target, row in self.ladder.items():
            for year in row["horizon"]["rows"]:
                for half in year["halves"]:
                    self.assertNotIn("ventilation", (half["binding_link"], half["mine_link"]), (target, half))
        steps = {(s["link"], s["to_stage"]): s for s in self.ladder[2500]["steps"]}
        when = {key: (s["in_service_year"], s["deferred_from"]) for key, s in steps.items()}
        self.assertEqual((when[("haulage", 1)], when[("stopes", 1)]), ((2028.0, 2027.5), (2028.0, 2027.5)))
        self.assertEqual(when[("ventilation", 1)], (2028.0, None))      # trucks 06-07 come with the VPV fan
        self.assertEqual((when[("haulage", 2)], when[("haulage", 3)]), ((2029.5, 2027.5), (2029.5, 2027.5)))
        self.assertEqual((when[("stopes", 2)], when[("stopes", 3)]), ((2029.5, 2028.0), (2029.5, 2028.0)))
        self.assertEqual(when[("ventilation", 2)], (2029.5, None))      # the rest with shaft VS-3
        self.assertEqual((when[("plant", 1)], when[("development", 1)]), ((2027.5, None), (2027.5, None)))
        first = steps[("haulage", 1)]
        self.assertEqual(first["deferred_when"], "II пол. 2027")
        self.assertIn("по сроку ввода — с середины 2027 г., но до начала 2028 г. её техника ждала бы воздуха",
                      first["in_service_text"])
        self.assertIn("вместе с ней в работу вводится: вентилятор ВПВ", first["in_service_text"])
        self.assertIn("вместе с ней в работу вводится: вентилятор ВС-3", steps[("haulage", 2)]["in_service_text"])
        # depth trucks come after every truck of the m_haul stages
        depth = [e for e in self.ladder[2000]["horizon"]["schedule"] if e["kind"] == "depth_truck"]
        self.assertEqual((depth[0]["time"], depth[0]["deferred_from"]), (2029.5, 2029.0))
        # trucks are bought when they can work: the assumed capex follows the time in service
        items = [i for i in self.ladder[1000]["economics"]["capex_items"] if i["entry"]["knob"] == "m_haul"]
        self.assertEqual([(i["entry"]["time"], i["entry"]["decided"], i["usd_m"]) for i in items],
                         [(2028.0, 2027.5, 3.0)])

    def test_a_unit_measure_the_air_never_admits_is_not_bought(self):
        projection = self.report(m_haul=2, m_stopes=2)["projection"]   # target 1000: the plan stops at fan VPV
        out = [e for e in projection["schedule"] if not e["in_horizon"]]
        self.assertEqual(sorted((e["knob"], e["stage"]) for e in out), [("m_haul", 2), ("m_stopes", 2)])
        for entry in out:
            self.assertTrue(entry["in_service_text"].startswith("в 2027–2036 гг. не вводится: её техника ждала бы "
                                                                "воздуха"), entry["in_service_text"])
        trucks = [i["entry"]["stage"] for i in projection["economics"]["capex_items"] if i["entry"]["knob"] == "m_haul"]
        self.assertEqual(trucks, [1])
        self.assertNotIn(("m_stopes", 2), [(e["knob"], e["stage"]) for e in projection["economics"]["not_costed"]])
        self.assertEqual(projection["label"], "держится до 2036 г.")

    def test_schedules_are_deterministic(self):
        again = Advisor().report(self.base)["ladder"]
        self.assertEqual(json.dumps(again, sort_keys=True), json.dumps(list(self.ladder.values()), sort_keys=True))
        when = {t: [(e["time"], e["kind"], e["link"], e["stage"]) for e in self.ladder[t]["horizon"]["schedule"]
                    if e["origin"] == "horizon"] for t in self.ladder}
        self.assertEqual(when[1000], [(2030.0, "measure", "tailings", 1), (2036.0, "storage", "tailings", 1)])
        self.assertEqual(when[1200], [(2030.5, "depth_truck", "haulage", 1), (2034.5, "storage", "tailings", 1),
                                      (2034.5, "depth_truck", "haulage", 2), (2034.5, "measure", "ventilation", 2)])
        self.assertEqual(when[2000], [(2029.5, "depth_truck", "haulage", 1), (2030.0, "depth_truck", "haulage", 2),
                                      (2031.5, "depth_truck", "haulage", 3), (2032.5, "storage", "tailings", 1),
                                      (2033.0, "depth_truck", "haulage", 4), (2034.5, "depth_truck", "haulage", 5),
                                      (2035.5, "storage", "tailings", 2)])
        self.assertEqual(when[2500], [(2029.5, "depth_truck", "haulage", 1), (2029.5, "depth_truck", "haulage", 2),
                                      (2032.0, "storage", "tailings", 1), (2035.0, "storage", "tailings", 2)])

    def test_trucks_are_added_one_at_a_time(self):
        horizon = self.ladder[2000]["horizon"]
        trucks = [e for e in horizon["schedule"] if e["kind"] == "depth_truck"]
        self.assertEqual([e["trucks"] for e in trucks], [1] * 5)
        self.assertTrue(trucks[0]["text"].startswith("ввод самосвала № 11 (парк: 10 → 11 машин)"))
        self.assertTrue(trucks[2]["text"].startswith("ввод самосвала AD45 № 13 на уклоне ТУ-1 сверх парка реестра"))
        self.assertEqual((horizon["trucks_end"], horizon["depth_trucks"], horizon["trucks_beyond_registry"]), (15, 5, 3))
        self.assertEqual(self.ladder[2500]["horizon"]["trucks_beyond_registry"], 2)

    def test_a_third_tailings_stage_keeps_the_plant_running(self):
        for target, count in ((1000, 2), (1200, 2), (2000, 3), (2500, 3)):
            horizon = self.ladder[target]["horizon"]
            self.assertIsNone(horizon["storage_runs_out_year"], target)
            self.assertEqual(horizon["storage_short_kt"], 0, target)
            stages = [e for e in horizon["schedule"] if e["link"] == "tailings"]
            self.assertEqual([(e["kind"], e["stage"], e["storage_kt"]) for e in stages],
                             [("measure", 1, 6000), ("storage", 1, 6000), ("storage", 2, 6000)][:count], target)
            self.assertTrue(all(row["achievable_ktpa"] > 0 and row["storage_short_kt"] == 0 for row in horizon["rows"]))
            self.assertTrue(horizon["storage_note"].endswith("Ёмкости хватает до 2036 г."), target)
            self.assertIn("вторая ступень (допущение, проект не опубликован)", horizon["storage_note"])
        horizon = self.ladder[2000]["horizon"]
        third = [e for e in horizon["schedule"] if e["kind"] == "storage" and e["stage"] == 2][0]
        self.assertEqual((third["time"], third["decided"], third["lead_years"]), (2035.5, 2033.5, 2.0))
        self.assertTrue(third["text"].startswith(f"третья ступень хвостохранилища после второй: {wording.num(6000)} "
                                                 f"тыс. т (допущение, проект не опубликован"), third["text"])
        self.assertIn("третья ступень (допущение, проект не опубликован) — в работе с середины 2035 г.",
                      horizon["storage_note"])
        self.assertTrue(horizon["rows"][2035 - 2027]["note"].startswith(
            "нужна третья ступень хвостохранилища: в работе с середины 2035 г., решение не позднее середины 2033 г. "
            "(допущение, проект не опубликован)"))
        # the 18 Mt beyond the epoch's dams (cell, second and third stage) less the 6 Mt the mine as it is needs
        econ = self.ladder[2000]["economics"]
        storage_kt = sum(i["entry"]["storage_kt"] for i in econ["capex_items"] if i["basis"] == "assumed")
        self.assertEqual(storage_kt, 18000)
        params = json.loads((TEAM / "model" / "params.json").read_text(encoding="utf-8"))
        self.assertTrue(params["tsf.measure_X3_t"]["source"].startswith("ASSUMPTION: NOT PUBLISHED: "))
        self.assertTrue(params["tsf.measure_X3_lead_years"]["source"].startswith("ASSUMPTION: "))
        self.assertEqual((params["tsf.measure_X3_t"]["value"], params["tsf.measure_X3_lead_years"]["value"]),
                         (6000000, 2.0))

    def test_without_a_third_stage_the_year_says_what_is_missing(self):
        params = json.loads((TEAM / "model" / "params.json").read_text(encoding="utf-8"))
        params["tsf.measure_X3_t"]["value"] = 0          # no third stage: the storage runs out in 2035
        advisor = Advisor(params=params)
        horizon = advisor.horizon.plan(advisor.ladder_start(advisor.default_inputs()), 2000, STOCKPILE_T)
        self.assertEqual((horizon["storage_runs_out_year"], horizon["held_to_year"]), (2035, 2034))
        self.assertEqual((horizon["lost_link"], horizon["failure_link"]), ("tailings", "tailings"))
        self.assertIn("ёмкость хвостохранилища исчерпана, нужна третья ступень хвостохранилища", horizon["text"])
        self.assertIn("В 2035 г. ёмкость кончается: нужна третья ступень хвостохранилища (до 2036 г. ещё ≈",
                      horizon["storage_note"])
        short = [row for row in horizon["rows"] if row["binding_link"] == "tailings"]
        self.assertEqual([row["year"] for row in short], [2035, 2036])
        for row in short:   # never a bare zero: the year names the missing stage and the ore it kept back
            self.assertIn("нужна третья ступень хвостохранилища (не хватило места для хвостов ≈", row["note"])
            self.assertGreater(row["storage_short_kt"], 0)
        self.assertEqual(short[-1]["achievable_ktpa"], 0)
        self.assertTrue(short[-1]["note"].startswith(
            "фабрика стоит: нет ёмкости хвостохранилища, нужна третья ступень"))
        self.assertAlmostEqual(sum(row["storage_short_kt"] for row in short), horizon["storage_short_kt"], delta=1)

    def test_the_ladder_and_its_effects_say_the_same(self):
        for target, row in self.ladder.items():
            econ, horizon = row["economics"], row["horizon"]
            self.assertEqual(econ["holds"], horizon["holds"])
            if target == 1000:     # the default target: no change, no item
                continue
            item = self.advisor.effects(self.inputs(revision=1),
                                        self.inputs(revision=2, target_ktpa=target))["items"][-1]
            self.assertEqual(item["id"], "economics")
            self.assertIn(horizon["label"], item["text"])
            if not horizon["holds"]:
                self.assertIn("окупаемость не указывается", item["text"])
                self.assertNotIn("окупается в", item["text"])


# The Stand at simulated day 8 (2027-01-09 09:30, seed of params.json): the ROM stockpile and the
# tailings placed since the epoch have moved; the ladder must not.
DAY8_STOCKPILE_T, DAY8_PLACED_T = 91383.6, 22830.0
# A stockpile drawn a little lower: in a horizon from it the stockpile runs out in 2027 and the 2027
# binding link turns to haulage (what the cards showed when they followed the running Stand).
LOW_STOCKPILE_T, LOW_PLACED_T = 90000.0, 25000.0
# The ladder of SUBMISSION.md («Цели от базового режима»): target -> (reached, held to, binding link
# by year, gold over ten years and its gain, koz, margin after tax, capex disclosed and assumed,
# NPV disclosed and with the assumed costs, M$, payback disclosed and with the assumed costs).
EPOCH_LADDER = {
    1000: (2027, 2036, "2027–2036: фабрика", 560.0, 106.7, 223.6, 0.0, 9.0, 162.71, 155.72, None, 2028),
    1200: (2028, 2036, "2027–2036: фабрика", 661.1, 207.8, 435.5, 0.0, 12.0, 322.23, 312.34, None, 2028),
    2000: (2030, 2036, "2027–2028: фабрика; 2029: откатка; 2030–2036: фабрика", 1003.4, 550.1, 1153.0,
           125.0, 27.0, 727.38, 705.44, 2029, 2029),
    2500: (None, None, "2027–2028: фабрика; 2029–2036: откатка", 1047.3, 594.0, 1245.1, 125.0, 25.5,
           810.47, 789.04, None, None),
}


class TestLadderFromTheEpoch(AdvisorCase):
    """The four ladder cards start on 1 January 2027, whatever the stockpile and the tailings of the
    running Stand; only the projection («Прогноз … из текущего состояния») follows them."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.day8 = replace(cls.base, stockpile_t=DAY8_STOCKPILE_T, tailings_placed_t=DAY8_PLACED_T,
                           sim_time="2027-01-09T09:30:00")
        cls.low = replace(cls.base, stockpile_t=LOW_STOCKPILE_T, tailings_placed_t=LOW_PLACED_T,
                          sim_time="2027-01-12T00:00:00")

    @staticmethod
    def card(row):
        """The figures of a card: a ladder row, or the projection (a horizon with its economics)."""
        h, e = row.get("horizon", row), row["economics"]
        t, d, w = e["totals"], e["variants"]["disclosed"], e["variants"]["with_assumed"]
        return (h["reached_year"], h["held_to_year"], h["binding_runs"]["text"], t["gold_koz"], t["gain_koz"],
                t["margin_after_tax_usd_m"], t["capex_published_usd_m"], t["capex_assumed_usd_m"],
                d["npv_usd_m"], w["npv_usd_m"], d["payback_year"], w["payback_year"])

    def test_the_epoch_is_what_a_fresh_stand_holds(self):
        self.assertEqual((self.base.stockpile_t, self.base.tailings_placed_t), (STOCKPILE_T, 0.0))
        self.assertEqual(self.advisor.epoch_stockpile_t, STOCKPILE_T)
        self.assertEqual(self.advisor.at_epoch(self.day8), replace(self.base, sim_time=self.day8.sim_time))

    def test_the_ladder_is_the_submission_table(self):
        for inputs in (self.base, self.day8, self.low):
            cards = {row["target_ktpa"]: self.card(row) for row in self.advisor.ladder(inputs)}
            self.assertEqual(cards, EPOCH_LADDER, inputs.sim_time)
        closest = self.advisor.ladder(self.day8)[-1]["horizon"]
        self.assertEqual((closest["best_year"], closest["best_ktpa"]), (2030, 2479))

    def test_the_ladder_does_not_drift_with_the_stand(self):
        fresh, day8 = self.advisor.report(self.base), self.advisor.report(self.day8)
        self.assertEqual(json.dumps(fresh["ladder"], sort_keys=True), json.dumps(day8["ladder"], sort_keys=True))
        nearly_full = replace(self.base, stockpile_t=1000.0, tailings_placed_t=2.5e6)
        self.assertEqual(json.dumps(self.advisor.ladder(nearly_full), sort_keys=True),
                         json.dumps(fresh["ladder"], sort_keys=True))

    def test_the_knobs_still_change_the_ladder(self):
        for knobs in (dict(fan_vs2_off=1), dict(tu2_closed=1), dict(m_haul=2, m_plant=3)):
            fresh = self.advisor.ladder(self.base.with_knobs(knobs))
            day8 = self.advisor.ladder(self.day8.with_knobs(knobs))
            self.assertEqual(json.dumps(fresh, sort_keys=True), json.dumps(day8, sort_keys=True), knobs)
        disturbed = {row["target_ktpa"]: row for row in self.advisor.ladder(self.day8.with_knobs(dict(fan_vs2_off=1)))}
        self.assertEqual(disturbed[1000]["steps"][0]["measure"], "restore_fan_vs2")   # a repair comes first
        low_grade = self.advisor.ladder(self.day8.with_knobs(dict(grade_gpt=1.76)))[0]
        self.assertLess(low_grade["economics"]["totals"]["gold_koz"], EPOCH_LADDER[1000][3])

    def test_the_projection_follows_the_current_state(self):
        fresh, day8 = self.advisor.projection(self.base), self.advisor.projection(self.day8)
        low = self.advisor.projection(self.low)
        # in the base mode the projection at the epoch is the 1.0 Mtpa card
        self.assertEqual(self.card(fresh), EPOCH_LADDER[1000])
        self.assertNotEqual(fresh["economics"]["totals"], day8["economics"]["totals"])
        self.assertAlmostEqual(day8["rows"][0]["stockpile_kt"], fresh["rows"][0]["stockpile_kt"]
                               - (STOCKPILE_T - DAY8_STOCKPILE_T) / 1000, delta=0.2)
        self.assertEqual(low["binding_runs"]["text"], "2027: откатка; 2028–2036: фабрика")

    def test_a_change_of_target_names_the_economics_of_its_card(self):
        before = replace(self.day8, revision=1)
        after = replace(self.day8.with_knobs(dict(target_ktpa=2000)), revision=2)
        item = self.advisor.effects(before, after)["items"][-1]
        fresh = self.advisor.effects(replace(self.base, revision=1),
                                     replace(self.base.with_knobs(dict(target_ktpa=2000)), revision=2))["items"][-1]
        self.assertEqual(item["id"], "economics")
        self.assertEqual(item, fresh)


class TestHorizonDisturbed(AdvisorCase):
    """The horizon starts from the current disturbances: repairs at once, conditions all along."""

    def test_repairs_come_first_and_at_once(self):
        report = self.report(fan_vs2_off=1, line_down=2)
        schedule = report["projection"]["schedule"]
        repairs = [e for e in schedule if e["kind"] == "disturbance"]
        self.assertEqual({e["knob"] for e in repairs}, {"fan_vs2_off", "line_down"})
        self.assertTrue(all(e["time"] == 2027.0 and e["lead_years"] == 0 for e in repairs))
        self.assertTrue(report["next_measure"]["in_service_text"].startswith("сразу"))
        self.assertEqual(report["projection"]["rows"][0]["achievable_ktpa"], 1000)

    def test_a_disturbance_is_repaired_at_once_even_when_the_target_is_met(self):
        report = self.report(target_ktpa=2500, pumps_failed_p150=1, **FULL[2500])
        self.assertIsNone(report["next_measure"])          # the target is met at the epoch: no step
        repairs = [e for e in report["projection"]["schedule"] if e["kind"] == "disturbance"]
        self.assertEqual([(e["knob"], e["time"]) for e in repairs], [("pumps_failed_p150", 2027.0)])
        flooded = replace(self.inputs(m_haul=1, m_vent=1), flooded_levels=("lvl-m050",))
        pumped = [e for e in self.advisor.report(flooded)["projection"]["schedule"] if e["kind"] == "disturbance"]
        self.assertEqual([(e["knob"], e["time"], e["set"]) for e in pumped], [("pumps_failed_p150", 2027.0, {})])

    def test_a_lower_grade_lasts_the_horizon(self):
        low = self.report(grade_gpt=1.76)["projection"]
        base = self.advisor.report(self.base)["projection"]
        self.assertEqual([r["achievable_ktpa"] for r in low["rows"]], [r["achievable_ktpa"] for r in base["rows"]])
        self.assertAlmostEqual(low["rows"][0]["gold_koz"], 47.8, delta=0.05)
        # the reference has the same grade, so the gain is the extra ore at the lower grade
        self.assertLess(low["economics"]["totals"]["gain_koz"], base["economics"]["totals"]["gain_koz"])

    def test_every_disturbance_gives_a_strict_json_horizon(self):
        for knobs in (dict(pumps_failed_p150=3), dict(tu1_closed=1), dict(tu2_closed=1), dict(inflow_factor=2.18),
                      dict(target_ktpa=2500, m_plant=3, line_down=2), dict(target_ktpa=2000, m_haul=3, fan_vs2_off=1)):
            with self.subTest(**knobs):
                report = self.report(**knobs)
                text = json.dumps(report["projection"], allow_nan=False, ensure_ascii=False)
                self.assertEqual(len(json.loads(text)["rows"]), 10)


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

    def test_pump_station_fail_binds_at_once(self):
        # 0 of 3 pumps: the water rises to the TU2 portal at +320 m over every production level, so
        # dewatering binds from the first minute at 0 kt/yr, not only once a level has flooded
        failed = self.inputs(pumps_failed_p150=3)
        report = self.advisor.report(failed)
        self.assertEqual((report["binding_link"], report["achievable_ktpa"]), ("dewatering", 0))
        self.assertEqual(report["kpi"]["dewatering_margin"], 0.0)
        self.assertEqual(report["kpi"]["gold_koz_year"], 0.0)
        self.assertEqual(report["next_measure"]["measure"], "restore_pumps")
        self.assertEqual(report["next_measure"]["set"], {"pumps_failed_p150": 0.0})
        self.assertEqual(report["sequence_outcome"]["reached"], True)
        self.assertEqual([s["link"] for s in report["sequence"]], ["dewatering", "haulage", "ventilation"])
        detail = report["links"][4]["detail"]
        self.assertIn("исправных насосов нет", detail)
        self.assertIn("ТУ-2 (+320\u00a0м)", detail)
        self.assertIn("следующим затопит гор. −50 м", detail)      # no countdown read: the level only
        flooded = self.advisor.report(replace(failed, flooded_levels=("lvl-000", "lvl-m050")))
        self.assertEqual((flooded["binding_link"], flooded["achievable_ktpa"]), ("dewatering", 0))
        self.assertEqual(self.caps(flooded)["stopes"], 1024)
        self.assertEqual(flooded["next_measure"]["measure"], "restore_pumps")
        self.assertEqual(flooded["sequence_outcome"]["reached"], True)
        self.assertIn("следующим затопит гор. +50 м", flooded["links"][4]["detail"])
        # the pumps back, two levels still under water: the stopes left dry bind while they are pumped out
        pumping = self.advisor.report(replace(self.inputs(), flooded_levels=("lvl-000", "lvl-m050")))
        self.assertEqual((pumping["binding_link"], pumping["achievable_ktpa"]), ("dewatering", 768))
        # the standby covers one failure, and one pump of two left carries the mean inflow
        for count in (1, 2):
            self.assertEqual(self.report(pumps_failed_p150=count)["binding_link"], "haulage", count)

    def test_the_wait_to_the_next_flooded_level_is_named(self):
        things = {"scenario": {"pumps_failed_p150": 3.0, "revision": 1.0}, "mine": {"flood_eta_min": 6.3},
                  "lvl-m050": {"state": "flooded"}}
        inputs = self.advisor.inputs_from_things(things)
        self.assertEqual(inputs.flood_eta_min, 6.3)
        report = self.advisor.report(inputs)
        self.assertTrue(report["links"][4]["detail"].endswith("гор. 0 м затопит через ≈6 мин стенда"))
        self.assertTrue(report["next_measure"]["text"].endswith("; пока насосы стоят, гор. 0 м затопит через ≈6 мин стенда"))
        # the countdown drifting does not make a new report; it starting or ending does
        later = self.advisor.inputs_from_things(dict(things, mine={"flood_eta_min": 2.0}))
        self.assertEqual(later.key(), inputs.key())
        done = self.advisor.inputs_from_things(dict(things, mine={"flood_eta_min": 0.0}))
        self.assertNotEqual(done.key(), inputs.key())
        # with every level below the portal flooded nothing more floods: no wait is named
        wet = self.advisor.report(replace(inputs, flood_eta_min=0.0, flooded_levels=FLOOD_ORDER))
        self.assertIn("выработки залиты до портала ТУ-2", wet["links"][4]["detail"])
        self.assertNotIn("затопит", wet["links"][4]["detail"])

    def test_the_ladder_of_the_base_knobs_is_unchanged(self):
        # the four target cards from 1 January 2027 are those of the committed fixture of the Stand
        fixture = json.loads((TEAM / "stand" / "fixtures" / "advisor.json").read_text(encoding="utf-8"))
        ladder = json.loads(json.dumps(self.advisor.report(self.advisor.default_inputs())["ladder"]))
        self.assertEqual([row["target_ktpa"] for row in ladder], [1000.0, 1200.0, 2000.0, 2500.0])
        self.assertEqual(ladder, fixture["ladder"])

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
        self.assertEqual(items["air_demand_m3s"]["text"], "Потребность всего парка в воздухе выросла: 317,2 → 369,9 м³/с.")
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
                         "Цель 2 500 тыс. т/год: не достигается до 2036 г.; за 2027–2036 гг. золота +594,0 тыс. "
                         "унц. к базе, маржа после налога 1 245,1 млн долл., капитальные затраты ≈125 млн "
                         "долл. (по расчёту компании, 3-й кв. 2025 г.), чистая приведённая стоимость 810,5 млн долл. "
                         "при 5 %; окупаемость не указывается: цель не удерживается до 2036 г.")
        held = self.by_id(self.items({}, dict(target_ktpa=2000)))["economics"]["text"]
        self.assertTrue(held.startswith("Цель 2 000 тыс. т/год: держится до 2036 г.;"), held)
        self.assertTrue(held.endswith("при 5 %; окупается в 2029 г."), held)

    def test_flooding_and_recovery(self):
        failed = self.inputs(revision=2, pumps_failed_p150=3)
        rising = self.by_id(self.advisor.effects(self.base, failed))
        self.assertEqual(rising["cap_dewatering_ktpa"]["text"],
                         "Водоотлив: насосы не откачивают приток, вода поднимается до портала ТУ-2 (+320\u00a0м); "
                         "рудник затопит, добыча не обеспечена (0 тыс. т/год).")
        self.assertEqual((rising["cap_dewatering_ktpa"]["before"], rising["cap_dewatering_ktpa"]["after"]), (None, 0))
        flooded = replace(failed, flooded_levels=("lvl-000", "lvl-m050"))
        items = self.by_id(self.advisor.effects(self.base, flooded))
        self.assertEqual(items["cap_dewatering_ktpa"]["text"],
                         "Водоотлив: насосы не откачивают приток, вода поднимается до портала ТУ-2 (+320\u00a0м); "
                         "затоплены горизонты 0 м, −50 м; рудник затопит, добыча не обеспечена (0 тыс. т/год).")
        # the pumps back with the levels under water: the stopes left dry while the water is pumped out
        pumping = replace(self.base, revision=3, flooded_levels=("lvl-000", "lvl-m050"))
        items = self.by_id(self.advisor.effects(self.base, pumping))
        self.assertEqual(items["cap_dewatering_ktpa"]["text"],
                         "Водоотлив: затоплены горизонты 0 м, −50 м, добыча из оставшихся блоков "
                         "ограничена 768 тыс. т/год.")
        self.assertEqual((items["cap_dewatering_ktpa"]["before"], items["cap_dewatering_ktpa"]["after"]), (None, 768))
        dry = replace(self.base, revision=4)
        back = self.by_id(self.advisor.effects(flooded, dry))
        self.assertEqual(back["cap_dewatering_ktpa"]["text"], "Водоотлив: затопление снято, звено не ограничивает добычу.")
        self.assertEqual(back["cap_dewatering_ktpa"]["trend"], "better")
        back = self.by_id(self.advisor.effects(failed, dry))
        self.assertEqual(back["cap_dewatering_ktpa"]["text"],
                         "Водоотлив: насосы снова откачивают приток, звено не ограничивает добычу.")

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
                         ("dewatering", "restore_pumps", 0.0))
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
    """Spec section 11 item 3: ten-year economics of each target against the mine as it is, after tax."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ladder = {row["target_ktpa"]: row for row in cls.advisor.report(cls.base)["ladder"]}

    def test_keys_and_published_figures(self):
        for target, row in self.ladder.items():
            econ = row["economics"]
            self.assertEqual((econ["gold_price_usd_oz"], econ["aisc_usd_oz"], econ["margin_usd_oz"]), (4615, 1995, 2620))
            self.assertEqual((econ["cit_rate_pct"], econ["discount_rate_pct"]), (20, 5))
            self.assertEqual([y["year"] for y in econ["years"]], list(range(2027, 2037)))
            self.assertEqual(set(econ["variants"]), {"disclosed", "with_assumed"})
            self.assertEqual(econ["capex_disclosed"], target >= 2000)
            self.assertEqual(econ["capex_usd_m"], 125 if target >= 2000 else None)
            self.assertNotIn("payback_years", json.dumps(econ))          # no one-year payback any more
            for key in ("price_basis", "aisc_basis", "tax_basis", "discount_basis", "capex_note", "assumed_note",
                        "reference_text", "caveats", "summary"):
                self.assertRegex(econ[key], CYRILLIC, key)
        self.assertTrue(self.ladder[1200]["economics"]["capex_note"].startswith("не раскрыто: "))
        self.assertIn("дробильное и мельничное оборудование", self.ladder[1200]["economics"]["capex_note"])
        self.assertIn("пересчитанной базе", self.ladder[2000]["economics"]["aisc_basis"])
        self.assertIn("НДПИ входит в AISC", self.ladder[2000]["economics"]["aisc_basis"])
        self.assertIn("ст. 357", self.ladder[2000]["economics"]["tax_basis"])
        self.assertIn("цена золота и AISC постоянны; без финансирования", self.ladder[2000]["economics"]["caveats"])

    def test_cash_and_npv_follow_the_yearly_rows(self):
        for target, row in self.ladder.items():
            econ = row["economics"]
            rows = row["horizon"]["rows"]
            cumulative = {"cash_usd_m": 0.0, "cash_with_assumed_usd_m": 0.0, "cash_pre_tax_usd_m": 0.0}
            npv = dict.fromkeys(cumulative, 0.0)
            for y, horizon_row in zip(econ["years"], rows):
                # the economics take the gold of the row in whole ounces, so the two koz figures can part by
                # one unit of the last digit and a rounding error
                self.assertAlmostEqual(y["gold_koz"], horizon_row["gold_koz"], delta=0.015)
                self.assertAlmostEqual(y["gain_koz"], y["gold_koz"] - y["reference_gold_koz"], delta=0.02)
                self.assertAlmostEqual(y["margin_usd_m"], y["gain_koz"] * 2.620, delta=0.05)
                self.assertAlmostEqual(y["tax_usd_m"], y["margin_usd_m"] * 0.20, delta=0.02)
                self.assertAlmostEqual(y["margin_after_tax_usd_m"], y["margin_usd_m"] - y["tax_usd_m"], delta=0.02)
                self.assertAlmostEqual(y["cash_usd_m"], y["margin_after_tax_usd_m"] - y["capex_published_usd_m"], delta=0.02)
                self.assertAlmostEqual(y["cash_with_assumed_usd_m"], y["cash_usd_m"] - y["capex_assumed_usd_m"], delta=0.02)
                self.assertAlmostEqual(y["cash_pre_tax_usd_m"], y["margin_usd_m"] - y["capex_published_usd_m"], delta=0.02)
                self.assertAlmostEqual(y["discount_factor"], 1.05 ** -(y["year"] - 2026), delta=1e-4)
                for key in cumulative:
                    cumulative[key] += y[key]
                    npv[key] += y[key] * 1.05 ** -(y["year"] - 2026)
                self.assertAlmostEqual(y["cumulative_usd_m"], cumulative["cash_usd_m"], delta=0.05)
                self.assertAlmostEqual(y["cumulative_with_assumed_usd_m"], cumulative["cash_with_assumed_usd_m"], delta=0.05)
            disclosed, assumed = econ["variants"]["disclosed"], econ["variants"]["with_assumed"]
            self.assertAlmostEqual(disclosed["cash_usd_m"], cumulative["cash_usd_m"], delta=0.05)
            self.assertAlmostEqual(assumed["cash_usd_m"], cumulative["cash_with_assumed_usd_m"], delta=0.05)
            self.assertAlmostEqual(disclosed["pre_tax"]["cash_usd_m"], cumulative["cash_pre_tax_usd_m"], delta=0.05)
            self.assertAlmostEqual(disclosed["npv_usd_m"], npv["cash_usd_m"], delta=0.05)
            self.assertAlmostEqual(assumed["npv_usd_m"], npv["cash_with_assumed_usd_m"], delta=0.05)
            self.assertAlmostEqual(disclosed["pre_tax"]["npv_usd_m"], npv["cash_pre_tax_usd_m"], delta=0.05)
            self.assertAlmostEqual(econ["totals"]["gain_koz"], sum(y["gain_koz"] for y in econ["years"]), delta=0.1)
            self.assertAlmostEqual(econ["totals"]["capex_published_usd_m"], 125 if target >= 2000 else 0, delta=0.01)
            self.assertAlmostEqual(disclosed["capex_usd_m"], econ["totals"]["capex_published_usd_m"], delta=0.01)
            self.assertLess(disclosed["npv_usd_m"], disclosed["pre_tax"]["npv_usd_m"])

    def test_capex_schedule(self):
        econ = self.ladder[2000]["economics"]
        published = {y["year"]: y["capex_published_usd_m"] for y in econ["years"]}
        self.assertEqual((published[2027], published[2028]), (62.5, 62.5))   # US$125m over the 24 months
        self.assertEqual(sum(published.values()), 125)
        items = econ["capex_items"]
        self.assertEqual([i["basis"] for i in items].count("published"), 1)
        trucks = sum(i["entry"]["trucks"] for i in items if i["basis"] == "assumed")
        storage_kt = sum(i["entry"]["storage_kt"] for i in items if i["basis"] == "assumed")
        reference_kt = sum(i["entry"]["storage_kt"] for i in econ["reference_capex_items"])
        self.assertEqual((trucks, storage_kt, reference_kt), (10, 18000, 6000))
        # 10 trucks x US$1.5m + (18 Mt: cell, second and third stage - the 6 Mt the mine needs anyway) x US$1/t
        self.assertAlmostEqual(econ["totals"]["capex_assumed_usd_m"], 10 * 1.5 + 12.0, delta=0.01)
        not_costed = {e["knob"] for e in econ["not_costed"]}
        self.assertEqual(not_costed, {"m_plant", "m_water", "m_stopes", "m_vent", "m_dev"})
        self.assertEqual([e["stage"] for e in econ["not_costed"] if e["knob"] == "m_plant"], [1])

    def test_never_a_payback_for_a_target_it_cannot_hold(self):
        for knobs in ({}, dict(fan_vs2_off=1), dict(grade_gpt=1.76), dict(tu2_closed=1, line_down=2)):
            for row in self.report(**knobs)["ladder"]:
                econ, horizon = row["economics"], row["horizon"]
                for variant in econ["variants"].values():
                    if not horizon["holds"]:
                        self.assertIsNone(variant["payback_year"], (knobs, row["target_ktpa"]))
                        self.assertIsNone(variant["pre_tax"]["payback_year"])
                        self.assertEqual(variant["payback_reason"], "not_held")
                        self.assertEqual(variant["payback_text"], "не указывается: цель не удерживается до 2036 г.")
                    elif variant["payback_year"] is not None:
                        self.assertGreaterEqual(variant["payback_year"], 2027)
        self.assertTrue(self.ladder[2000]["horizon"]["holds"])
        self.assertFalse(self.ladder[2500]["horizon"]["holds"])
        self.assertEqual(self.ladder[2500]["economics"]["variants"]["disclosed"]["payback_text"],
                         "не указывается: цель не удерживается до 2036 г.")

    def test_payback_years_of_the_held_targets(self):
        # 2.0 Mtpa, held to 2036: the published US$125m in 2027-2028 is paid back in 2029, before tax and after
        econ = self.ladder[2000]["economics"]
        for variant in econ["variants"].values():
            self.assertEqual((variant["payback_year"], variant["payback_reason"]), (2029, "paid_back"))
            self.assertEqual(variant["pre_tax"]["payback_year"], 2029)
            self.assertEqual(variant["payback_text"], "окупается в 2029 г.")
        cumulative = [y["cumulative_usd_m"] for y in econ["years"]]
        self.assertTrue(cumulative[0] < 0 and cumulative[1] < 0 and all(value >= 0 for value in cumulative[2:]))
        for target in (1000, 1200):
            econ = self.ladder[target]["economics"]
            disclosed, assumed = econ["variants"]["disclosed"], econ["variants"]["with_assumed"]
            self.assertEqual((disclosed["payback_year"], disclosed["payback_reason"]), (None, "no_outlay"))
            self.assertEqual(disclosed["payback_text"], "не считается: капзатраты не раскрыты")
            self.assertEqual((assumed["payback_year"], assumed["payback_text"]), (2028, "окупается в 2028 г."))
            cumulative = [y["cumulative_with_assumed_usd_m"] for y in econ["years"]]
            self.assertLess(cumulative[0], 0)
            self.assertTrue(all(value >= 0 for value in cumulative[1:]))

    def test_every_figure_is_sourced_in_params(self):
        params = json.loads((TEAM / "model" / "params.json").read_text(encoding="utf-8"))
        for pid in ("econ.gold_price_usd_oz", "econ.aisc_usd_oz", "econ.capex_expansion_usd_m"):
            self.assertTrue(params[pid]["source"].startswith("FACT D1 '"), pid)
            self.assertIn("https://", params[pid]["source"])
        self.assertEqual(params["econ.gold_price_usd_oz"]["value"], 4615)
        self.assertEqual(params["econ.aisc_usd_oz"]["value"], 1995)
        self.assertEqual(params["econ.capex_expansion_usd_m"]["value"], 125)
        cit = params["econ.cit_rate"]
        self.assertEqual(cit["value"], 20)
        for text in ("Article 357", "adilet.zan.kz", "against the Kazakhstan corporate income tax rate of 20%",
                     "mineral extraction tax"):
            self.assertIn(text, cit["source"])
        for pid in ("econ.truck_capex_usd_m", "econ.tsf_capex_usd_per_t", "tsf.measure_X2_t"):
            self.assertTrue(params[pid]["source"].startswith("ASSUMPTION: NOT PUBLISHED: "), pid)
        self.assertTrue(params["econ.discount_rate_pct"]["source"].startswith("ASSUMPTION: "))

    def test_wording_describes_and_does_not_advise(self):
        report = self.advisor.report(self.base)
        texts = [row["economics"][key] for row in report["ladder"]
                 for key in ("price_basis", "aisc_basis", "tax_basis", "capex_note", "assumed_note", "caveats",
                             "summary")]
        texts += [row["horizon"]["text"] for row in report["ladder"]]
        texts += [self.advisor.effects(self.inputs(revision=1), self.inputs(revision=2, target_ktpa=t))["items"][-1]["text"]
                  for t in (1200, 2000, 2500)]
        for text in texts:
            for word in ("рекоменд", "стоит купить", "инвестир", "выгодн", "советуем", "покуп"):
                self.assertNotIn(word, text.lower(), text)

    def test_effects_of_a_new_target(self):
        items = self.advisor.effects(self.inputs(revision=1), self.inputs(revision=2, target_ktpa=1200))["items"]
        self.assertEqual(items[-1]["id"], "economics")
        self.assertIn("держится до 2036 г.", items[-1]["text"])
        self.assertIn("капитальные затраты не раскрыты", items[-1]["text"])
        same = self.advisor.effects(self.inputs(revision=1), self.inputs(revision=2, m_haul=1))["items"]
        self.assertNotIn("economics", [item["id"] for item in same])


class TestDewateringReserve(AdvisorCase):
    """The pump margin and the standby, so that a single pump failure shows on the bar."""

    def test_margin_now_and_after_the_next_failure(self):
        base = self.advisor.report(self.base)
        one = self.report(pumps_failed_p150=1)
        self.assertEqual((base["kpi"]["dewatering_margin"], base["kpi"]["dewatering_margin_next_failure"],
                          base["kpi"]["pumps_standby"]), (2.54, 2.54, 1))
        self.assertEqual((one["kpi"]["dewatering_margin"], one["kpi"]["dewatering_margin_next_failure"],
                          one["kpi"]["pumps_standby"]), (2.54, 1.27, 0))
        self.assertEqual(base["kpi"]["dewatering_reserve"], "резерв: 1 насос")
        self.assertEqual(one["kpi"]["dewatering_reserve"], "резерва нет: при отказе ещё одного насоса ×1,27")
        self.assertEqual(base["links"][4]["detail"], "запас производительности насосов ×2,54; резерв: 1 насос")
        self.assertIn("резерва нет", one["links"][4]["detail"])
        stopped = self.report(pumps_failed_p150=3)["kpi"]
        self.assertEqual((stopped["dewatering_margin"], stopped["dewatering_margin_next_failure"]), (0.0, 0.0))


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
        # the guidance is a range: 52-55 koz against 47.8 koz at 1.76 g/t; a reference row, not a failure
        self.assertEqual((c14["reported"], c14["reported_max"]), (52000, 55000))
        self.assertAlmostEqual(c14["model"], 47813, delta=1)
        self.assertAlmostEqual(c14["deviation"], -8.05, delta=0.01)
        self.assertIsNone(c14["passed"])
        self.assertIs(c14["reference"], True)
        self.assertEqual(c14["tolerance"], "справочно, без допуска")
        self.assertEqual(c14["basis_note"],
                         "прогноз компании соответствует содержанию 1,91–2,01 г/т при 1 млн т; модель при "
                         "содержании первого полугодия 2026 г. (1,76 г/т) даёт 47,8 тыс. унц.")
        # two lines in 2024: 666.7 kt/yr in the model against 593.6 kt milled, outside 5 %
        self.assertAlmostEqual(c15["model"], 666666.67, delta=0.01)
        self.assertFalse(c15["passed"])
        self.assertIs(c15["reference"], False)
        self.assertEqual(c15["basis_note"],
                         "в 2024 г. фабрика работала ниже паспортной мощности двух линий (89 %); модель принимает "
                         "паспортную мощность — это допущение завышает переработку на 3–11 % (2025 г.: 96,7 %)")
        self.assertEqual([row["reference"] for row in self.rows if row["id"] not in ("C14",)].count(True), 0)
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
        self.assertEqual(self.service.report["binding_link"], "dewatering")     # binds at once
        self.assertNotIn("затоплены", self.service.report["links"][4]["detail"])
        self.source.things = dict(self.source.things, **{"lvl-m050": {"state": "flooded"},
                                                         "lvl-000": {"state": "flooded"}})
        self.clock.now += 1
        self.service.tick()
        self.assertEqual(self.service.report["binding_link"], "dewatering")
        self.assertIn("затоплены горизонты 0 м, −50 м", self.service.report["links"][4]["detail"])
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
        self.assertEqual(len(names), 4 + 12 + 4)   # scenario, stockpile, clock, mine, the levels, the dams
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
    STDLIB = {"__future__", "argparse", "dataclasses", "datetime", "http", "itertools", "json", "math", "os",
              "pathlib", "re", "signal", "sys", "threading", "time", "typing", "urllib"}

    def test_package_files(self):
        self.assertEqual({path.name for path in PACKAGE.glob("*.py")},
                         {"__init__.py", "engine.py", "horizon.py", "service.py", "wording.py"})

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
        for name in ("engine.py", "horizon.py", "wording.py"):
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
