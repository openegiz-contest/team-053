"""Expansion Advisor: the decision logic of spec 3.4. Pure, no network, standard library only.

The advisor ranks the eight link capacities of ``sekis.capacity``, names the binding link and
removes it one measure at a time until the processing target is met. Every number in its
output is a value ``sekis.capacity`` computed for some state, rounded for display; this
module adds no formula of its own beyond sums, differences and the choice of states.

Typical use::

    from sekis.advisor import Advisor, Inputs

    advisor = Advisor()                                   # reads model/params.json, registry.json
    inputs = advisor.inputs_from_things(things)           # {"scenario": {"m_haul": 1.0, ...}, ...}
    report = advisor.report(inputs, before=previous)      # the JSON document of GET /report
    advisor.apply(inputs, "next")["changes"]              # {"m_haul": 2.0}: knobs for the Stand
    advisor.envelope(report)                              # Ditto-protocol message for the twin

Report keys are listed in ``Advisor.report``.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .. import capacity as cap
from . import wording

__all__ = ["Advisor", "Inputs", "Plan", "Step", "MODES", "RESTORE_PUMPS", "NO_MEASURE",
           "ADVISOR_THING", "SCENARIO_THING", "TELEMETRY_TOPIC"]

SCHEMA = "sekis.advisor.report/1"
NAMESPACE = "kz.sekis"
ADVISOR_THING = "advisor"
SCENARIO_THING = "scenario"
STOCKPILE_THING = "rom-stockpile"
CLOCK_THING = "enterprise"
OUTFALL_THING = "mon-volchevka"
TELEMETRY_TOPIC = f"telemetry/sekis/{ADVISOR_THING}"

#: Values of the twin feature ``next_measure`` besides a knob name.
RESTORE_PUMPS = "restore_pumps"
NO_MEASURE = "none"
PUMPS_KNOB = "pumps_failed_p150"
MODES = ("next", "all")

#: Why the constraint loop stopped.
TARGET_REACHED = "target_reached"
NO_STAGE_LEFT = "no_stage_left"

#: Links on each side of the ROM stockpile: the mine fills it, the plant draws it down.
MINE_LINKS = ("haulage", "ventilation", "stopes", "development", "dewatering")
PROCESS_LINKS = ("plant", "water")

PROJECTION_YEARS = 10   # horizon of the projection, counted from the year of the simulation epoch
FLOODED = "flooded"     # state token of a level (spec 2.5)


def _finite(value: Optional[float], digits: int) -> Optional[float]:
    """Round for display; an unbounded value becomes ``None``."""
    if value is None or math.isinf(value) or math.isnan(value):
        return None
    return round(float(value), digits)


@dataclass(frozen=True)
class Inputs:
    """What the advisor reads from the twins for one report.

    knobs              numeric features of ``kz.sekis:scenario`` except ``revision``:
                       ``target_ktpa``, the measure knobs and the disturbances
    revision, label    the scenario revision and its name
    flooded_levels     names of the levels whose state is ``flooded``
    tailings_placed_t  tailings placed since the epoch, t (stored now less stored at the epoch)
    stockpile_t        ROM stockpile, t
    sim_time           simulator clock, ISO 8601, or ``None``
    """
    knobs: Mapping[str, float]
    revision: int = 0
    label: str = ""
    flooded_levels: Tuple[str, ...] = ()
    tailings_placed_t: float = 0.0
    stockpile_t: float = 0.0
    sim_time: Optional[str] = None

    @property
    def target_ktpa(self) -> float:
        return float(self.knobs["target_ktpa"])

    def key(self) -> Tuple[Any, ...]:
        """What a report depends on apart from slowly drifting tonnages: a new key means a new report."""
        return (tuple(sorted((k, float(v)) for k, v in self.knobs.items())), self.revision, self.label,
                tuple(sorted(self.flooded_levels)))

    def with_knobs(self, changes: Mapping[str, Any]) -> "Inputs":
        """Copy with some knobs replaced; names that are not knobs are ignored."""
        knobs = dict(self.knobs)
        knobs.update({k: float(v) for k, v in changes.items() if k in knobs})
        return replace(self, knobs=knobs)


@dataclass(frozen=True)
class Step:
    """One measure of the sequence: the binding link and the stage that relieves it.

    ``measure`` is the knob name, or ``restore_pumps`` for dewatering. ``changes`` maps scenario
    knobs to their new values; it is empty when the pumps already run and the flooded levels
    only have to be pumped out.
    """
    link: str
    measure: str
    knob: str
    from_stage: int
    to_stage: int
    changes: Mapping[str, float]
    cap_before_ktpa: Optional[int]
    cap_after_ktpa: Optional[int]
    text: str

    def to_dict(self) -> Dict[str, Any]:
        return {"link": self.link, "link_name": wording.link_name(self.link), "measure": self.measure,
                "knob": self.knob, "from_stage": self.from_stage, "to_stage": self.to_stage,
                "set": dict(self.changes), "text": self.text,
                "cap_before_ktpa": self.cap_before_ktpa, "cap_after_ktpa": self.cap_after_ktpa}


@dataclass(frozen=True)
class Plan:
    """Result of the constraint loop: the steps taken and the state they lead to."""
    target_ktpa: float
    steps: Tuple[Step, ...]
    start: cap.Result     # the state the loop began in
    result: cap.Result    # the state after the last step
    stop_reason: str

    @property
    def reached(self) -> bool:
        return self.stop_reason == TARGET_REACHED

    @property
    def links(self) -> List[str]:
        return [step.link for step in self.steps]


def achievable_rounded(res: cap.Result) -> int:
    """Rate of the chain as it is shown: the capacity of the binding link rounded to 1 kt/yr."""
    return res.capacity_rounded[res.binding_link]


class Advisor:
    """The decision module. Holds the model; every method is a pure function of its arguments."""

    def __init__(self, model: Optional[cap.Model] = None, registry: Optional[Mapping[str, Any]] = None):
        self.model = model or cap.load_model()
        if registry is None:
            path = Path(cap.__file__).resolve().parent.parent / "model" / "registry.json"
            with open(path, encoding="utf-8") as handle:
                registry = json.load(handle)
        things = {t["thingId"].split(":", 1)[-1]: t for t in registry["things"]}
        #: Thing name -> Russian name, plus the receiving water body of the mine-water outfall.
        self.names: Dict[str, str] = {name: t["attributes"]["name"] for name, t in things.items()}
        self.names["water_body"] = things[OUTFALL_THING]["attributes"]["water_body"]
        #: Feature id -> default value of the advisor twin; fixes the ids and the value types.
        self.feature_defaults: Dict[str, Any] = _plain(things[ADVISOR_THING]["features"])
        scenario = _plain(things[SCENARIO_THING]["features"])
        #: Knob -> default: every numeric feature of the scenario thing except the revision.
        self.knob_defaults: Dict[str, float] = {
            k: float(v) for k, v in scenario.items()
            if k != "revision" and isinstance(v, (int, float)) and not isinstance(v, bool)}
        self.default_label: str = str(scenario.get("label", ""))
        self.targets: Tuple[float, ...] = tuple(float(v) for v in self.model.p("ladder.m_plant.capacity_ktpa"))
        self.first_year: int = datetime.fromisoformat(self.model.p("sim.epoch")).year
        self.baseline: cap.Result = cap.evaluate(self.model, cap.State())
        self._calibration = [wording.calibration_row(self.model, check)
                             for check in cap.calibration_checks(self.model)]

    # --- inputs ------------------------------------------------------------------------------

    def thing_names(self) -> List[str]:
        """Things the advisor reads: the scenario, the levels, the dams, the stockpile, the clock."""
        return ([SCENARIO_THING, STOCKPILE_THING, CLOCK_THING]
                + [level.name for level in self.model.levels] + list(self.model.dams))

    def inputs_from_things(self, things: Mapping[str, Mapping[str, Any]]) -> Inputs:
        """Build ``Inputs`` from thing name -> ``{feature id: value}``.

        A missing thing or feature falls back to the state at the epoch (registry defaults), so
        a file that holds only the scenario is a complete input.
        """
        scenario = things.get(SCENARIO_THING, {})
        knobs = dict(self.knob_defaults)
        for knob in knobs:
            value = scenario.get(knob)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                knobs[knob] = float(value)
        revision = scenario.get("revision", 0)
        flooded = tuple(level.name for level in self.model.levels
                        if things.get(level.name, {}).get("state") == FLOODED)
        placed = 0.0
        for name, dam in self.model.dams.items():
            stored = things.get(name, {}).get("stored_t")
            if isinstance(stored, (int, float)):
                placed += float(stored) - dam.stored_start_t
        stock = things.get(STOCKPILE_THING, {}).get("tonnes")
        sim_time = things.get(CLOCK_THING, {}).get("sim_time")
        return Inputs(
            knobs=knobs,
            revision=int(revision) if isinstance(revision, (int, float)) else 0,
            label=str(scenario.get("label", self.default_label)),
            flooded_levels=flooded,
            tailings_placed_t=max(0.0, placed),
            stockpile_t=float(stock) if isinstance(stock, (int, float)) else float(self.model.p("stockpile.start_t")),
            sim_time=sim_time if isinstance(sim_time, str) else None)

    def default_inputs(self) -> Inputs:
        """The state at the epoch: default knobs, nothing flooded, the opening stockpile."""
        return self.inputs_from_things({})

    def state(self, inputs: Inputs) -> cap.State:
        """State of the capacity library for these inputs. Active units follow from the knobs."""
        return cap.State.from_knobs(inputs.knobs, flooded_levels=tuple(inputs.flooded_levels),
                                    tailings_placed_t=inputs.tailings_placed_t)

    # --- the constraint loop (spec 3.4 steps 1-3) ----------------------------------------------

    def next_step(self, res: cap.Result) -> Optional[Tuple[Step, cap.Result]]:
        """One more stage on the knob of the binding link, applied virtually.

        Returns the step and the evaluated state after it, or ``None`` when the link has no
        stage left. Dewatering binds only while a level is flooded; its measure restores the
        pumps of ps-p150, after which the levels are taken as pumped out.
        """
        state, link = res.state, res.binding_link
        if link == "dewatering":
            failed = state.pumps_failed_p150
            after = cap.evaluate(self.model, state.replace(pumps_failed_p150=0, flooded_levels=()))
            measure, knob, stages = RESTORE_PUMPS, PUMPS_KNOB, (failed, 0)
            changes = {PUMPS_KNOB: 0.0} if failed else {}
        else:
            move = cap.next_measure(self.model, state, link)
            if move is None:
                return None
            knob, new_state = move
            after = cap.evaluate(self.model, new_state)
            measure, stages = knob, (getattr(state, knob), getattr(new_state, knob))
            changes = {knob: float(stages[1])}
        step = Step(link=link, measure=measure, knob=knob, from_stage=stages[0], to_stage=stages[1],
                    changes=changes, cap_before_ktpa=res.capacity_rounded[link],
                    cap_after_ktpa=after.capacity_rounded[link],
                    text=wording.measure_text(self.model, self.names, link, res, after))
        return step, after

    def plan(self, state: cap.State, target_ktpa: float) -> Plan:
        """Remove the binding link, one measure at a time, until the target is met.

        The loop stops when the binding capacity, rounded to 1 kt/yr, is at or above the
        target, or when the binding link has no stage left.
        """
        start = res = cap.evaluate(self.model, state)
        steps: List[Step] = []
        most = sum(cap.knob_max(self.model, knob) for knob in cap.KNOBS) + 1  # every stage, and the pumps
        while True:
            if achievable_rounded(res) >= target_ktpa:
                return Plan(target_ktpa, tuple(steps), start, res, TARGET_REACHED)
            move = self.next_step(res) if len(steps) < most else None
            if move is None:
                return Plan(target_ktpa, tuple(steps), start, res, NO_STAGE_LEFT)
            step, res = move
            steps.append(step)

    # --- figures of one state ----------------------------------------------------------------

    def kpi(self, res: cap.Result, stockpile_t: float) -> Dict[str, Any]:
        """KPI values of an evaluated state, rounded for display; ``None`` marks "no limit"."""
        mine = min(res.capacity_ktpa[link] for link in MINE_LINKS)
        process = min(res.capacity_ktpa[link] for link in PROCESS_LINKS)
        days = cap.stockpile_days_left(self.model, stockpile_t, mine, process)
        return {
            "gold_koz_year": _finite(res.gold.oz_per_year / cap.KILO, 2),
            "gold_gain_koz_year": _finite((res.gold.oz_per_year - self.baseline.gold.oz_per_year) / cap.KILO, 2),
            "grade_gpt": _finite(res.gold.grade_gpt, 2),
            "recovery_pct": _finite(res.gold.recovery_pct, 2),
            "air_demand_m3s": _finite(res.air.demand_m3s, 1),
            "air_supply_m3s": _finite(res.air.supply_m3s, 1),
            "air_margin_pct": _finite(res.air.margin_pct, 1),
            "air_used_m3s": _finite(res.air.used_m3s, 1),
            "air_spare_m3s": _finite(res.air.spare_m3s, 1),
            "units_held_vent": len(res.air.held_trucks) + len(res.air.held_lhds),
            "water_deficit_m3h": _finite(res.water.deficit_m3h, 1),
            "discharge_m3h": _finite(res.water.discharge_m3h, 1),
            "permit_m3h": self.model.p("water.permit_m3h"),
            "permit_use_pct": _finite(res.water.permit_use_pct, 1),
            "tailings_free_kt": _finite(res.tailings.free_t / cap.KILO, 0),
            "tailings_years_left": _finite(res.tailings.years_left, 1),
            "stockpile_t": _finite(stockpile_t, 0),
            "stockpile_days_left": _finite(days, 0),
            "dewatering_margin": _finite(res.dewatering.margin, 2),
        }

    def links(self, res: cap.Result) -> List[Dict[str, Any]]:
        """The eight links in ranking order with their capacity, knob stage and a line of detail."""
        rows = []
        for link in cap.LINKS:
            knob = cap.MEASURE_KNOBS.get(link)
            row = {"id": link, "name": wording.link_name(link), "cap_ktpa": res.capacity_rounded[link],
                   "limiting": res.capacity_rounded[link] is not None, "binding": link == res.binding_link,
                   "knob": knob,
                   "stage": getattr(res.state, knob) if knob else None,
                   "stage_max": cap.knob_max(self.model, knob) if knob else None,
                   "detail": wording.link_detail(self.model, self.names, link, res)}
            rows.append(row)
        return rows

    def _outcome(self, plan: Plan) -> Dict[str, Any]:
        res = plan.result
        return {"achievable_ktpa": achievable_rounded(res), "binding_link": res.binding_link,
                "binding_link_name": wording.link_name(res.binding_link), "reached": plan.reached,
                "stop_reason": plan.stop_reason}

    # --- ladder (step 4) ---------------------------------------------------------------------

    def ladder(self, inputs: Inputs) -> List[Dict[str, Any]]:
        """For each target: the sequence from the baseline measure set under the current
        disturbances, and the figures of the state it ends in."""
        start = self.state(inputs).replace(**{knob: 0 for knob in cap.KNOBS})
        rows = []
        for target in self.targets:
            plan = self.plan(start, target)
            row: Dict[str, Any] = {"target_ktpa": target,
                                   "steps": [step.to_dict() for step in plan.steps],
                                   "sequence": plan.links,
                                   "measures_count": len(plan.steps)}
            row.update(self._outcome(plan))
            row["measures"] = {knob: getattr(plan.result.state, knob) for knob in cap.KNOBS}
            row["capacities"] = dict(plan.result.capacity_rounded)
            row.update(self.kpi(plan.result, inputs.stockpile_t))
            rows.append(row)
        return rows

    # --- projection (step 5) -----------------------------------------------------------------

    def projection(self, inputs: Inputs) -> Dict[str, Any]:
        """Ten years of the current measure set and disturbances.

        Each year the seven links other than tailings are evaluated at the depth the production
        centroid has reached; the year's ore is the smallest of them, or what the tailings
        storage can still take. The ore then lowers the centroid, fills the dams and pours gold.
        The storage link itself (the rate that keeps a reserve of years) is a planning rule and
        does not cap the tonnage of a year; the free volume does.
        """
        model = self.model
        state = self.state(inputs)
        centroid = model.p("stope.centroid_baseline_m") if state.centroid_m is None else state.centroid_m
        placed = state.tailings_placed_t
        grade = model.p("plant.grade_base") if state.grade_gpt is None else state.grade_gpt
        rows: List[Dict[str, Any]] = []
        runs_out: Optional[int] = None
        missed: Optional[int] = None
        gold_total = 0.0
        for year in range(self.first_year, self.first_year + PROJECTION_YEARS):
            res = cap.evaluate(model, state.replace(centroid_m=centroid, tailings_placed_t=placed))
            physical = dict(res.capacity_ktpa, tailings=math.inf)
            link = cap.binding_link(physical)
            rate_kt = min(physical.values())
            free_kt = res.tailings.free_t / cap.KILO
            if free_kt <= rate_kt:
                rate_kt, link = free_kt, "tailings"
                runs_out = runs_out or year
            ore_t = rate_kt * cap.KILO
            gold_oz = cap.gold_oz(model, ore_t, grade)
            gold_total += gold_oz
            without_water = min(min(v for k, v in physical.items() if k != "water"), free_kt)
            tph = without_water * cap.KILO / model.hours_per_year
            water = cap.water_balance(model, tph, tph, res.dewatering.pumped_m3h, state.m_water)
            placed += ore_t
            storage = cap.tailings(model, state.m_tailings, placed, rate_kt)
            shown = cap.round_kt(rate_kt)
            met = shown >= inputs.target_ktpa
            if not met and missed is None:
                missed = year
            rows.append({
                "year": year,
                "achievable_ktpa": shown,
                "binding_link": link,
                "binding_link_name": wording.link_name(link),
                "target_met": met,
                "centroid_m": _finite(centroid, 1),
                "gold_oz": _finite(gold_oz, 0),
                "gold_koz": _finite(gold_oz / cap.KILO, 2),
                "gold_total_koz": _finite(gold_total / cap.KILO, 2),
                "tailings_stored_kt": _finite(storage.stored_t / cap.KILO, 0),
                "tailings_free_kt": _finite(storage.free_t / cap.KILO, 0),
                "tailings_years_left": _finite(storage.years_left, 1),
                "water_deficit_m3h": _finite(water.deficit_m3h, 1),
            })
            centroid = cap.centroid_after(model, centroid, ore_t)
        return {"first_year": self.first_year, "last_year": self.first_year + PROJECTION_YEARS - 1,
                "target_ktpa": inputs.target_ktpa, "rows": rows,
                "storage_runs_out_year": runs_out, "target_missed_year": missed,
                "gold_total_koz": _finite(gold_total / cap.KILO, 2)}

    # --- effects (step 6) --------------------------------------------------------------------

    def _snapshot(self, inputs: Inputs) -> Dict[str, Any]:
        state = self.state(inputs)
        plan = self.plan(state, inputs.target_ktpa)
        res = plan.start
        pumps_total = self.model.p("water.ps_p150.pumps")
        return {"target_ktpa": inputs.target_ktpa, "binding_link": res.binding_link,
                "achievable_ktpa": achievable_rounded(res), "capacities": dict(res.capacity_rounded),
                "measures_needed": len(plan.steps), "flooded_levels": tuple(res.dewatering.flooded_levels),
                "held_trucks": tuple(res.air.held_trucks), "held_lhds": tuple(res.air.held_lhds),
                "pumps_total": pumps_total, "pumps_available": pumps_total - state.pumps_failed_p150,
                "permit_exceeded": res.water.permit_state == "exceeded",
                "kpi": self.kpi(res, inputs.stockpile_t)}

    def effects(self, before: Optional[Inputs], after: Inputs) -> Dict[str, Any]:
        """What the last change of the scenario did: before -> after of every capacity and KPI.

        ``before`` holds the knobs and the flooded levels before the change. Both sides are
        evaluated with the tonnages of ``after`` (stockpile, tailings placed), so that the list
        shows the change and not the drift of the running mine. With no ``before`` the list is empty.
        """
        head = {"revision": after.revision, "label": after.label,
                "before_revision": before.revision if before else None,
                "before_label": before.label if before else None}
        if before is None:
            return dict(head, items=[])
        same_tonnages = replace(before, tailings_placed_t=after.tailings_placed_t, stockpile_t=after.stockpile_t)
        items = wording.effect_items(self.names, self._snapshot(same_tonnages), self._snapshot(after))
        return dict(head, items=items)

    # --- report ------------------------------------------------------------------------------

    def report(self, inputs: Inputs, before: Optional[Inputs] = None) -> Dict[str, Any]:
        """The full report, a JSON-ready dict. Raises ``ValueError`` for a knob set the model rejects.

        Keys: ``schema``, ``report_revision``, ``label``, ``sim_time``, ``knobs``, ``target_ktpa``,
        ``achievable_ktpa``, ``achievable_exact_ktpa``, ``binding_link``, ``binding_link_name``,
        ``target_reached``, ``links`` (eight rows), ``next_measure`` (a step or ``None``),
        ``measures_needed``, ``sequence`` (steps from the current state to the target),
        ``sequence_outcome``, ``kpi``, ``sustainable_baseline``, ``ladder`` (one row per target),
        ``projection``, ``effects``, ``calibration``.
        """
        state = self.state(inputs)
        plan = self.plan(state, inputs.target_ktpa)
        res = plan.start
        steps = [step.to_dict() for step in plan.steps]
        base = self.baseline
        return {
            "schema": SCHEMA,
            "report_revision": inputs.revision,
            "label": inputs.label,
            "sim_time": inputs.sim_time,
            "knobs": dict(inputs.knobs),
            "target_ktpa": inputs.target_ktpa,
            "achievable_ktpa": achievable_rounded(res),
            "achievable_exact_ktpa": _finite(res.achievable_ktpa, 2),
            "binding_link": res.binding_link,
            "binding_link_name": wording.link_name(res.binding_link),
            "target_reached": achievable_rounded(res) >= inputs.target_ktpa,
            "links": self.links(res),
            "next_measure": steps[0] if steps else None,
            "measures_needed": len(steps),
            "sequence": steps,
            "sequence_outcome": self._outcome(plan),
            "kpi": self.kpi(res, inputs.stockpile_t),
            "sustainable_baseline": {
                "ktpa": achievable_rounded(base),
                "binding_link": base.binding_link,
                "grade_gpt": _finite(base.gold.grade_gpt, 2),
                "gold_koz_year": _finite(base.gold.oz_per_year / cap.KILO, 2),
                "stockpile_t": self.model.p("stockpile.start_t"),
                "stockpile_days_left": self.kpi(base, self.model.p("stockpile.start_t"))["stockpile_days_left"],
            },
            "ladder": self.ladder(inputs),
            "projection": self.projection(inputs),
            "effects": self.effects(before, inputs),
            "calibration": [dict(row) for row in self._calibration],
        }

    # --- action ------------------------------------------------------------------------------

    def apply(self, inputs: Inputs, mode: str) -> Dict[str, Any]:
        """Knob changes for the Stand to write: the next measure, or the whole remaining sequence.

        ``changes`` maps knob -> new value (absolute, so writing it twice is harmless). In mode
        ``next`` it raises the knob of the binding link by one stage; in mode ``all`` it holds
        the final stage of every knob of the sequence. It is empty when the target is reached,
        when the binding link has no stage left, or when flooded levels are being pumped out
        with the pumps already restored.
        """
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
        plan = self.plan(self.state(inputs), inputs.target_ktpa)
        steps = plan.steps[:1] if mode == "next" else plan.steps
        changes: Dict[str, float] = {}
        for step in steps:
            changes.update(step.changes)
        if changes:
            reason = "applied"
        elif steps:
            reason = "pumping_out"
        else:
            reason = plan.stop_reason
        binding = plan.start.binding_link
        return {"mode": mode, "revision": inputs.revision, "target_ktpa": inputs.target_ktpa,
                "binding_link": binding, "changes": changes,
                "steps": [step.to_dict() for step in steps], "reason": reason,
                "message": wording.apply_message(reason, binding, steps)}

    # --- the twin ----------------------------------------------------------------------------

    def features(self, report: Mapping[str, Any]) -> Dict[str, Any]:
        """Features of ``kz.sekis:advisor`` from a report: strings for the two tokens, floats for
        the rest. A value with no limit (a capacity that does not bind, a stockpile that does
        not fall) is published as 0."""
        step = report["next_measure"]
        kpi = report["kpi"]
        values: Dict[str, Any] = {
            "binding_link": report["binding_link"],
            "next_measure": step["measure"] if step else NO_MEASURE,
            "measures_needed": report["measures_needed"],
            "target_ktpa": report["target_ktpa"],
            "achievable_ktpa": report["achievable_ktpa"],
            "report_revision": report["report_revision"],
        }
        for row in report["links"]:
            values[f"cap_{row['id']}_ktpa"] = row["cap_ktpa"]
        for key in ("dewatering_margin", "gold_koz_year", "gold_gain_koz_year", "air_demand_m3s",
                    "water_deficit_m3h", "discharge_m3h", "tailings_years_left", "stockpile_days_left"):
            values[key] = kpi[key]
        missing = set(self.feature_defaults) - set(values)
        if missing:
            raise KeyError(f"advisor features without a value: {sorted(missing)}")
        features: Dict[str, Any] = {}
        for feature_id, default in self.feature_defaults.items():
            value = values[feature_id]
            features[feature_id] = str(value) if isinstance(default, str) else float(value or 0.0)
        return features

    def envelope(self, report: Mapping[str, Any]) -> Dict[str, Any]:
        """Ditto-protocol ``modify`` of all features of the advisor twin (spec 1.1, 5.2)."""
        return {"topic": f"{NAMESPACE}/{ADVISOR_THING}/things/twin/commands/modify",
                "path": "/features",
                "value": {feature_id: {"properties": {"value": value}}
                          for feature_id, value in self.features(report).items()}}


def _plain(features: Mapping[str, Any]) -> Dict[str, Any]:
    """``{id: {"properties": {"value": v}}}`` -> ``{id: v}``."""
    return {feature_id: body["properties"]["value"] for feature_id, body in features.items()}
