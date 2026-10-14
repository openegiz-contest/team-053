"""Expansion Advisor: the decision logic of spec 3.4. Pure, no network, standard library only.

The advisor ranks the eight link capacities of ``sekis.capacity``, names the binding link and
removes it one measure at a time until the processing target is met. A disturbance that an
operational action can remove (a stopped plant line, a closed decline, a failed fan or pumps)
is removed first, the one whose removal raises the achievable rate most leading; the expansion
measures follow. Disturbances no action removes (a lower ore grade, a flood inflow) are
reported as conditions. Every number in the output is a value ``sekis.capacity`` computed for
some state, or a parameter of ``params.json``, rounded for display; this module adds no
formula of its own beyond sums, differences, products with prices and the choice of states.

Typical use::

    from sekis.advisor import Advisor, Inputs

    advisor = Advisor()                                   # reads model/params.json, registry.json
    inputs = advisor.inputs_from_things(things)           # {"scenario": {"m_haul": 1.0, ...}, ...}
    report = advisor.report(inputs, before=previous)      # the JSON document of GET /report
    advisor.apply(inputs, "next")["changes"]              # {"m_haul": 2.0}: knobs for the Stand
    advisor.envelope(report)                              # Ditto-protocol message for the twin

Report keys are listed in ``Advisor.report``.

Steady state. The KPIs of the report (water deficit and discharge, stockpile flow, gold) are
long-run values of the selected regime: the rate the chain sustains, with the water the pumps
deliver on average. The twins show live values (1-hour water means, rates restarted on a knob
change, see ``sekis.sim``), which approach these values after the transient.
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

__all__ = ["Advisor", "Inputs", "Plan", "Step", "MODES", "RESTORE_PUMPS", "NO_MEASURE", "DISTURBANCES",
           "CONDITIONS", "MEASURE", "DISTURBANCE", "ADVISOR_THING", "SCENARIO_THING", "TELEMETRY_TOPIC"]

SCHEMA = "sekis.advisor.report/2"
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

#: Kinds of step: an expansion measure (one more stage of a measure knob) or the removal of a
#: disturbance (the knob back to its default).
MEASURE = "measure"
DISTURBANCE = "disturbance"

#: Disturbance knob that an operational action removes -> (the link the removal relieves, token of
#: the twin feature ``next_measure``). The order breaks ties between equal gains.
DISTURBANCES: Dict[str, Tuple[str, str]] = {
    "line_down": ("plant", "restart_line"),
    "tu2_closed": ("haulage", "open_tu2"),
    "tu1_closed": ("haulage", "open_tu1"),
    "fan_vs2_off": ("ventilation", "restore_fan_vs2"),
    PUMPS_KNOB: ("dewatering", RESTORE_PUMPS),
}
#: Disturbance knobs that no action of the mine removes; reported as conditions.
CONDITIONS = ("grade_gpt", "inflow_factor")

#: Why the constraint loop stopped.
TARGET_REACHED = "target_reached"
NO_STAGE_LEFT = "no_stage_left"

#: Links on each side of the ROM stockpile: the mine fills it, the plant draws it down.
MINE_LINKS = ("haulage", "ventilation", "stopes", "development", "dewatering")
PROCESS_LINKS = ("plant", "water")

#: Direction of the ROM stockpile in the steady state.
FALLS, GROWS, STEADY = "falls", "grows", "steady"

PROJECTION_YEARS = 10   # horizon of the projection, counted from the year of the simulation epoch
FLOODED = "flooded"     # state token of a level (spec 2.5)
MILLION = 1.0e6         # US$ per US$m, oz per Moz (a unit conversion)

#: Calibration tables already computed, by the content of params.json (the simulator run of
#: C3, C8 and C11 takes a few seconds and is done once per process).
_CALIBRATION_CACHE: Dict[str, List[Dict[str, Any]]] = {}


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
    """One step of the sequence: the binding link and what relieves it.

    ``kind`` is ``measure`` (one more stage of the measure knob ``knob``) or ``disturbance``
    (``knob`` back to its default: restart a line, open a decline, restore a fan or pumps).
    ``measure`` is the token of the twin feature ``next_measure``: the knob name for a measure,
    ``restart_line``, ``open_tu1``, ``open_tu2``, ``restore_fan_vs2`` or ``restore_pumps`` for a
    disturbance. ``changes`` maps scenario knobs to their new values; it is empty when the pumps
    already run and the flooded levels only have to be pumped out.
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
    kind: str = MEASURE

    def to_dict(self) -> Dict[str, Any]:
        return {"kind": self.kind, "link": self.link, "link_name": wording.link_name(self.link),
                "measure": self.measure, "knob": self.knob, "from_stage": self.from_stage,
                "to_stage": self.to_stage, "set": dict(self.changes), "text": self.text,
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

    def __init__(self, model: Optional[cap.Model] = None, registry: Optional[Mapping[str, Any]] = None,
                 params: Optional[Mapping[str, Any]] = None):
        model_dir = Path(cap.__file__).resolve().parent.parent / "model"
        if params is None:
            with open(model_dir / "params.json", encoding="utf-8") as handle:
                params = json.load(handle)
        if registry is None:
            with open(model_dir / "registry.json", encoding="utf-8") as handle:
                registry = json.load(handle)
        self.model = model or cap.Model(params, registry)
        #: Parameter id -> its ``source`` in params.json (the references of the calibration rows).
        self.sources: Dict[str, str] = {pid: str(entry.get("source", "")) for pid, entry in params.items()}
        self._params_key = json.dumps(params, sort_keys=True)
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

    def disturbance_step(self, res: cap.Result) -> Optional[Tuple[Step, cap.Result]]:
        """Removal of the active disturbance that raises the achievable rate most, applied virtually.

        ``None`` when no removable disturbance is active. Ties go to the order of
        ``DISTURBANCES``. Restored pumps are taken to pump the flooded levels out.
        """
        state = res.state
        best = None
        for knob, (link, token) in DISTURBANCES.items():
            value = getattr(state, knob)
            if not value:
                continue
            cleared = state.replace(**{knob: type(value)(0)})
            if knob == PUMPS_KNOB:
                cleared = cleared.replace(flooded_levels=())
            after = cap.evaluate(self.model, cleared)
            gain = achievable_rounded(after) - achievable_rounded(res)
            if best is None or gain > best[0]:
                best = (gain, knob, link, token, int(value), after)
        if best is None:
            return None
        _, knob, link, token, value, after = best
        step = Step(link=link, measure=token, knob=knob, from_stage=value, to_stage=0,
                    changes={knob: self.knob_defaults[knob]}, cap_before_ktpa=res.capacity_rounded[link],
                    cap_after_ktpa=after.capacity_rounded[link],
                    text=wording.disturbance_text(self.model, self.names, knob, res, after), kind=DISTURBANCE)
        return step, after

    def next_step(self, res: cap.Result) -> Optional[Tuple[Step, cap.Result]]:
        """One more stage on the knob of the binding link, applied virtually.

        Returns the step and the evaluated state after it, or ``None`` when the link has no
        stage left. Dewatering binds only while a level is flooded; with the pumps failed its
        step is the disturbance step (restore the pumps), with the pumps running it is pumping
        the levels out (no knob changes), after which the levels are taken as pumped out.
        """
        state, link = res.state, res.binding_link
        if link == "dewatering":
            if state.pumps_failed_p150:
                return self.disturbance_step(res)
            after = cap.evaluate(self.model, state.replace(flooded_levels=()))
            measure, knob, stages, changes = RESTORE_PUMPS, PUMPS_KNOB, (0, 0), {}
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
        """Remove the binding constraint, one step at a time, until the target is met.

        Active disturbances are removed first (``disturbance_step``), then the binding link gets
        one more measure stage at a time. The loop stops when the binding capacity, rounded to
        1 kt/yr, is at or above the target, or when the binding link has no stage left.
        """
        start = res = cap.evaluate(self.model, state)
        steps: List[Step] = []
        most = sum(cap.knob_max(self.model, knob) for knob in cap.KNOBS) + len(DISTURBANCES) + 1
        while True:
            if achievable_rounded(res) >= target_ktpa:
                return Plan(target_ktpa, tuple(steps), start, res, TARGET_REACHED)
            move = None
            if len(steps) < most:
                move = self.disturbance_step(res) or self.next_step(res)
            if move is None:
                return Plan(target_ktpa, tuple(steps), start, res, NO_STAGE_LEFT)
            step, res = move
            steps.append(step)

    def conditions(self, res: cap.Result) -> List[Dict[str, Any]]:
        """Disturbances no action of the mine removes (spec 3.1): stated, not proposed as measures."""
        state, p = res.state, self.model.p
        rows = []
        base_grade = p("plant.grade_base")
        if state.grade_gpt is not None and state.grade_gpt < base_grade:
            rows.append({"knob": "grade_gpt", "value": state.grade_gpt, "base": base_grade,
                         "text": wording.grade_condition(state.grade_gpt, base_grade, res)})
        if state.inflow_factor > 1:
            rows.append({"knob": "inflow_factor", "value": state.inflow_factor, "base": 1.0,
                         "text": wording.inflow_condition(self.model, self.names, res)})
        return rows

    # --- figures of one state ----------------------------------------------------------------

    def stockpile_flow(self, res: cap.Result, stockpile_t: float) -> Dict[str, Any]:
        """ROM stockpile in the steady state of ``res``.

        The mine delivers the smallest of the mine links over its working days. The plant mills
        its capacity unless the water the sources sustain at that hoisting rate carries less
        (``WaterBalance.feed_limit_tph``, the throttle of the simulator once the ponds run low),
        and nothing once the tailings storage is full. Both are per simulated day (the simulator
        runs working days only), as ``capacity.stockpile_days_left`` counts them.
        """
        model, p = self.model, self.model.p
        mine_ktpa = min(res.capacity_ktpa[link] for link in MINE_LINKS)
        hoist_tph = mine_ktpa * cap.KILO / (p("regime.working_days") * cap.HOURS_PER_DAY)
        plant_tph = res.capacity_ktpa["plant"] * cap.KILO / model.hours_per_year
        water = cap.water_balance(model, hoist_tph, plant_tph, res.dewatering.pumped_m3h, res.state.m_water)
        feed_tph = min(plant_tph, water.feed_limit_tph)
        if res.tailings.free_t <= 0:
            feed_tph = 0.0
        feed_ktpa = feed_tph * model.hours_per_year / cap.KILO
        mine_tpd = mine_ktpa * cap.KILO / p("regime.working_days")
        plant_tpd = feed_ktpa * cap.KILO / p("regime.plant_days")
        days = cap.stockpile_days_left(model, stockpile_t, mine_ktpa, feed_ktpa)
        net = mine_tpd - plant_tpd
        trend = FALLS if math.isfinite(days) else GROWS if net > 0 else STEADY
        return {"mine_tpd": mine_tpd, "plant_tpd": plant_tpd, "net_tpd": net, "days": days, "trend": trend,
                "water_limited": feed_tph < plant_tph}

    def kpi(self, res: cap.Result, stockpile_t: float) -> Dict[str, Any]:
        """KPI values of an evaluated state, rounded for display; ``None`` marks "no limit"."""
        stock = self.stockpile_flow(res, stockpile_t)
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
            "stockpile_days_left": _finite(stock["days"], 0),
            "stockpile_mine_tpd": _finite(stock["mine_tpd"], 0),
            "stockpile_plant_tpd": _finite(stock["plant_tpd"], 0),
            "stockpile_net_tpd": _finite(stock["net_tpd"], 0),
            "stockpile_trend": stock["trend"],
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

    # --- economics (decision 11.1) -------------------------------------------------------------

    def economics(self, gold_oz_year: float, target_ktpa: float) -> Dict[str, Any]:
        """What the gold a target adds over the sustainable baseline is worth, and the payback.

        Value at the realised gold price; operating margin per ounce = price less the published
        AISC (H1 2026, restated basis), taken as unchanged by the extra output; capex the company
        estimate where one is published for the target, otherwise ``None`` (not disclosed);
        payback = capex / extra margin per year. A description of the mine's economics, not advice.
        """
        p = self.model.p
        price, aisc = p("econ.gold_price_usd_oz"), p("econ.aisc_usd_oz")
        gain_oz = gold_oz_year - self.baseline.gold.oz_per_year
        margin_usd_m = gain_oz * (price - aisc) / MILLION
        capex = p("econ.capex_expansion_usd_m") if target_ktpa in p("econ.capex_expansion_targets_ktpa") else None
        payback = capex / margin_usd_m if capex is not None and margin_usd_m > 0 else None
        row = {
            "target_ktpa": target_ktpa,
            "baseline_gold_koz_year": _finite(self.baseline.gold.oz_per_year / cap.KILO, 1),
            "gold_gain_koz_year": _finite(gain_oz / cap.KILO, 1),
            "gold_price_usd_oz": price,
            "value_usd_m_year": _finite(gain_oz * price / MILLION, 1),
            "aisc_usd_oz": aisc,
            "margin_usd_oz": price - aisc,
            "margin_usd_m_year": _finite(margin_usd_m, 1),
            "capex_usd_m": capex,
            "capex_disclosed": capex is not None,
            "payback_years": _finite(payback, 1),
            "sources": {"gold_price_usd_oz": "econ.gold_price_usd_oz", "aisc_usd_oz": "econ.aisc_usd_oz",
                        "capex_usd_m": "econ.capex_expansion_usd_m"},
        }
        row.update(wording.economics_notes(self.model, row))
        return row

    # --- ladder (step 4) ---------------------------------------------------------------------

    def ladder_start(self, inputs: Inputs) -> cap.State:
        """The baseline measure set under the current disturbances."""
        return self.state(inputs).replace(**{knob: 0 for knob in cap.KNOBS})

    def ladder_row(self, start: cap.State, target: float, stockpile_t: float) -> Dict[str, Any]:
        """The sequence for one target from ``start`` and the figures of the state it ends in."""
        plan = self.plan(start, target)
        row: Dict[str, Any] = {"target_ktpa": target,
                               "steps": [step.to_dict() for step in plan.steps],
                               "sequence": plan.links,
                               "measures_count": len(plan.steps)}
        row.update(self._outcome(plan))
        row["measures"] = {knob: getattr(plan.result.state, knob) for knob in cap.KNOBS}
        row["capacities"] = dict(plan.result.capacity_rounded)
        row.update(self.kpi(plan.result, stockpile_t))
        row["economics"] = self.economics(plan.result.gold.oz_per_year, target)
        return row

    def ladder(self, inputs: Inputs) -> List[Dict[str, Any]]:
        """For each target: the sequence from the baseline measure set under the current
        disturbances, the figures of the state it ends in and the economics of the target."""
        start = self.ladder_start(inputs)
        return [self.ladder_row(start, target, inputs.stockpile_t) for target in self.targets]

    # --- projection (step 5) -----------------------------------------------------------------

    def _project(self, state: cap.State, target_ktpa: float) -> Dict[str, Any]:
        """Ten years of one state: rows, the year storage runs out, the first year the target is missed."""
        model = self.model
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
            rate_kt = physical_kt = min(physical.values())
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
            met = shown >= target_ktpa
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
                "note": wording.projection_note(link, shown, cap.round_kt(physical_kt)),
            })
            centroid = cap.centroid_after(model, centroid, ore_t)
        return {"rows": rows, "storage_runs_out_year": runs_out, "target_missed_year": missed,
                "gold_total_koz": _finite(gold_total / cap.KILO, 2)}

    def projection(self, inputs: Inputs) -> Dict[str, Any]:
        """Ten years of the current measure set and disturbances.

        Each year the seven links other than tailings are evaluated at the depth the production
        centroid has reached; the year's ore is the smallest of them, or what the tailings
        storage can still take. The ore then lowers the centroid, fills the dams and pours gold.
        The storage link itself (the rate that keeps a reserve of years) is a planning rule and
        does not cap the tonnage of a year; the free volume does. A year in which storage runs
        out, and every year after it, carries a ``note``; ``storage_measure`` names the stage of
        the tailings measure that would prevent it and the year storage then runs out.
        """
        state = self.state(inputs)
        result = self._project(state, inputs.target_ktpa)
        measure = None
        if result["storage_runs_out_year"] is not None:
            measure = self._storage_measure(state, inputs.target_ktpa)
        result.update({"first_year": self.first_year, "last_year": self.first_year + PROJECTION_YEARS - 1,
                       "target_ktpa": inputs.target_ktpa, "storage_measure": measure,
                       "storage_note": wording.storage_note(self.first_year + PROJECTION_YEARS - 1,
                                                            result["storage_runs_out_year"], measure)})
        return result

    def _storage_measure(self, state: cap.State, target_ktpa: float) -> Dict[str, Any]:
        """The next stage of the tailings measure and the year storage runs out with it."""
        before = cap.evaluate(self.model, state)
        move = cap.next_measure(self.model, state, "tailings")
        if move is None:
            return {"knob": None, "to_stage": None, "text": None, "storage_runs_out_year": None}
        knob, new_state = move
        after = cap.evaluate(self.model, new_state)
        with_measure = self._project(new_state, target_ktpa)
        return {"knob": knob, "to_stage": getattr(new_state, knob),
                "text": wording.measure_text(self.model, self.names, "tailings", before, after),
                "storage_runs_out_year": with_measure["storage_runs_out_year"]}

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
        shows the change and not the drift of the running mine. With no ``before`` the list is
        empty. A change of the target adds the economics of the new target.
        """
        head = {"revision": after.revision, "label": after.label,
                "before_revision": before.revision if before else None,
                "before_label": before.label if before else None}
        if before is None:
            return dict(head, items=[])
        same_tonnages = replace(before, tailings_placed_t=after.tailings_placed_t, stockpile_t=after.stockpile_t)
        items = wording.effect_items(self.names, self._snapshot(same_tonnages), self._snapshot(after))
        if before.target_ktpa != after.target_ktpa:
            row = self.ladder_row(self.ladder_start(after), after.target_ktpa, after.stockpile_t)
            items.append(wording.economics_item(row))
        return dict(head, items=items)

    # --- calibration table (spec 2.9, decision 11.3) -------------------------------------------

    def calibration(self) -> List[Dict[str, Any]]:
        """Rows of «Проверка калибровки»: analytic checks, the simulator checks C3, C8, C11 of a
        headless baseline run of ``calib.run_days`` days (seed ``sim.seed``), and the
        out-of-sample checks C13-C16, in the order of their ids. Computed once per process."""
        cached = _CALIBRATION_CACHE.get(self._params_key)
        if cached is None:
            rows = [wording.calibration_row(self.model, self.sources, check, "analytic")
                    for check in cap.calibration_checks(self.model)]
            rows += self._simulator_rows()
            rows += [wording.calibration_row(self.model, self.sources, check, "out_of_sample")
                     for check in cap.out_of_sample_checks(self.model)]
            rows.sort(key=lambda row: int(row["id"][1:]))     # stable: rows of one id keep their order
            cached = _CALIBRATION_CACHE[self._params_key] = rows
        return [dict(row) for row in cached]

    def _simulator_rows(self) -> List[Dict[str, Any]]:
        """C3, C8 and C11 from a headless simulator run; rows without a value if it cannot run."""
        days = self.model.p("calib.run_days")
        try:
            from ..sim import Simulator  # here: the simulator is needed for this table only
            sim = Simulator.from_files()
            sim.run_days(days)
            checks = [cap.calibration_basis(check) for check in sim.calibration_checks()]
            run = wording.simulator_run(days, sim.p("sim.seed"))
        except Exception as exc:  # the table still lists the checks, without a value
            run = wording.simulator_run_failed(exc)
            checks = []
        if not checks:
            return [wording.calibration_row(self.model, self.sources, None, "simulator", check_id=check_id,
                                            run=run) for check_id in ("C3", "C8", "C11")]
        return [wording.calibration_row(self.model, self.sources, check, "simulator", run=run) for check in checks]

    # --- report ------------------------------------------------------------------------------

    def report(self, inputs: Inputs, before: Optional[Inputs] = None) -> Dict[str, Any]:
        """The full report, a JSON-ready dict. Raises ``ValueError`` for a knob set the model rejects.

        Keys: ``schema``, ``report_revision``, ``label``, ``sim_time``, ``knobs``, ``target_ktpa``,
        ``achievable_ktpa``, ``achievable_exact_ktpa``, ``binding_link``, ``binding_link_name``,
        ``target_reached``, ``links`` (eight rows), ``next_measure`` (a step or ``None``),
        ``measures_needed``, ``sequence`` (steps from the current state to the target),
        ``sequence_outcome``, ``conditions`` (disturbances no action removes), ``kpi`` (steady
        state), ``sustainable_baseline``, ``ladder`` (one row per target, with ``economics``),
        ``projection``, ``effects``, ``calibration``.
        """
        state = self.state(inputs)
        plan = self.plan(state, inputs.target_ktpa)
        res = plan.start
        steps = [step.to_dict() for step in plan.steps]
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
            "conditions": self.conditions(res),
            "kpi": self.kpi(res, inputs.stockpile_t),
            "sustainable_baseline": self.sustainable_baseline(),
            "ladder": self.ladder(inputs),
            "projection": self.projection(inputs),
            "effects": self.effects(before, inputs),
            "calibration": self.calibration(),
        }

    def sustainable_baseline(self) -> Dict[str, Any]:
        """The undisturbed baseline: what the mine sustains, and the plant while the stockpile lasts."""
        base = self.baseline
        start_t = self.model.p("stockpile.start_t")
        stock = self.stockpile_flow(base, start_t)
        row = {
            "ktpa": achievable_rounded(base),
            "binding_link": base.binding_link,
            "grade_gpt": _finite(base.gold.grade_gpt, 2),
            "gold_koz_year": _finite(base.gold.oz_per_year / cap.KILO, 2),
            "plant_ktpa": cap.round_kt(base.capacity_ktpa["plant"]),
            "stockpile_t": start_t,
            "stockpile_days_left": _finite(stock["days"], 0),
            "stockpile_net_tpd": _finite(stock["net_tpd"], 0),
        }
        row["text"] = wording.baseline_text(row)
        return row

    # --- action ------------------------------------------------------------------------------

    def apply(self, inputs: Inputs, mode: str) -> Dict[str, Any]:
        """Knob changes for the Stand to write: the next step, or the whole remaining sequence.

        ``changes`` maps knob -> new value (absolute, so writing it twice is harmless). In mode
        ``next`` it removes the leading disturbance, or raises the knob of the binding link by one
        stage; in mode ``all`` it holds every removal and the final stage of every knob of the
        sequence. It is empty when the target is reached, when the binding link has no stage
        left, or when flooded levels are being pumped out with the pumps already restored.
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
