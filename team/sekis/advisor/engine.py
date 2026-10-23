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

Water on the basis of the twins (decision 11.4). The water KPIs (deficit, discharge, share of the
permit) are taken at the rates the simulator runs at: the mine hoists the smallest of its links
over the working days (every simulated day is one), and the plant draws water for the feed it
wants, its capacity (the mean over the planned line stops) or nothing once the tailings storage
is full. ``water_regime`` gives the same balance with every line running, the value the live
1-hour means show between the line stops; the report carries both.
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
MINE_THING = "mine"     # its flood_eta_min counts down to the next flooded level
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
    flood_eta_min      minutes of the Stand until the next level floods, as the simulator counts
                       them (``mine.flood_eta_min``); 0 when nothing is about to flood
    """
    knobs: Mapping[str, float]
    revision: int = 0
    label: str = ""
    flooded_levels: Tuple[str, ...] = ()
    tailings_placed_t: float = 0.0
    stockpile_t: float = 0.0
    sim_time: Optional[str] = None
    flood_eta_min: float = 0.0

    @property
    def target_ktpa(self) -> float:
        return float(self.knobs["target_ktpa"])

    def key(self) -> Tuple[Any, ...]:
        """What a report depends on apart from slowly drifting tonnages and the flood countdown (the
        report is refreshed every 30 s anyway): a new key means a new report. The countdown
        starting or ending is a new key, so the first report of a failure names the wait."""
        return (tuple(sorted((k, float(v)) for k, v in self.knobs.items())), self.revision, self.label,
                tuple(sorted(self.flooded_levels)), self.flood_eta_min > 0)

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
        from .horizon import Horizon  # here: horizon builds on the constants of this module
        #: The ten-year horizon (spec 3.4 steps 4 and 5): schedules with lead times, hold years, economics.
        self.horizon = Horizon(self, PROJECTION_YEARS)

    # --- inputs ------------------------------------------------------------------------------

    def thing_names(self) -> List[str]:
        """Things the advisor reads: the scenario, the levels, the dams, the stockpile, the clock and
        the mine (its flood countdown)."""
        return ([SCENARIO_THING, STOCKPILE_THING, CLOCK_THING, MINE_THING]
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
        eta = things.get(MINE_THING, {}).get("flood_eta_min")
        return Inputs(
            knobs=knobs,
            revision=int(revision) if isinstance(revision, (int, float)) else 0,
            label=str(scenario.get("label", self.default_label)),
            flooded_levels=flooded,
            tailings_placed_t=max(0.0, placed),
            stockpile_t=float(stock) if isinstance(stock, (int, float)) else float(self.model.p("stockpile.start_t")),
            sim_time=sim_time if isinstance(sim_time, str) else None,
            flood_eta_min=float(eta) if isinstance(eta, (int, float)) and not isinstance(eta, bool) else 0.0)

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
                         "text": wording.inflow_condition(self.model, self.names, res, *self.water_regime(res))})
        return rows

    # --- figures of one state ----------------------------------------------------------------

    def regime_rates(self, res: cap.Result) -> Dict[str, float]:
        """The rates the simulator runs a state at, t/h: ``mine_ktpa`` and ``hoist_tph`` (the
        smallest mine link over the working days, 24 h a day; dewatering with the stopes dry now,
        ``capacity.Dewatering.capacity_now_ktpa``, since the mine hoists from the levels the water
        has not reached yet), ``plant_tph`` (the plant capacity
        as a mean over its planned line stops) and ``all_lines_tph`` (every line of that capacity
        running); both plant rates are 0 when the tailings storage is full."""
        model, p = self.model, self.model.p
        mine_ktpa = min(res.dewatering.capacity_now_ktpa if link == "dewatering" else res.capacity_ktpa[link]
                        for link in MINE_LINKS)
        hoist_tph = mine_ktpa * cap.KILO / (p("regime.working_days") * cap.HOURS_PER_DAY)
        plant_tph = res.capacity_ktpa["plant"] * cap.KILO / model.hours_per_year
        if res.tailings.free_t <= 0:
            plant_tph = 0.0
        return {"mine_ktpa": mine_ktpa, "hoist_tph": hoist_tph, "plant_tph": plant_tph,
                "plant_ktpa": plant_tph * model.hours_per_year / cap.KILO,
                "all_lines_tph": plant_tph / p("plant.availability")}

    def water_regime(self, res: cap.Result) -> Tuple[cap.WaterBalance, cap.WaterBalance]:
        """Water balance of the state at the rates of ``regime_rates``: (mean over the line
        stops, every line running). Mine water is what the pumps deliver in steady state; the
        deficit is the water the wanted feed and the site miss, the discharge the surplus."""
        rates = self.regime_rates(res)
        pumped, m_water = res.dewatering.pumped_m3h, res.state.m_water
        mean = cap.water_balance(self.model, rates["hoist_tph"], rates["plant_tph"], pumped, m_water)
        lines = cap.water_balance(self.model, rates["hoist_tph"], rates["all_lines_tph"], pumped, m_water)
        return mean, lines

    def stockpile_flow(self, res: cap.Result, stockpile_t: float) -> Dict[str, Any]:
        """ROM stockpile in the steady state of ``res``.

        The mine delivers the smallest of the mine links over its working days. The plant mills
        its capacity unless the water the sources sustain at that hoisting rate carries less
        (``WaterBalance.feed_limit_tph``, the throttle of the simulator once the ponds run low),
        and nothing once the tailings storage is full. Both are per simulated day (the simulator
        runs working days only), as ``capacity.stockpile_days_left`` counts them.
        """
        model, p = self.model, self.model.p
        rates = self.regime_rates(res)
        mine_ktpa, hoist_tph, plant_tph = rates["mine_ktpa"], rates["hoist_tph"], rates["plant_tph"]
        water = cap.water_balance(model, hoist_tph, plant_tph, res.dewatering.pumped_m3h, res.state.m_water)
        feed_tph = min(plant_tph, water.feed_limit_tph)
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
        water, lines = self.water_regime(res)
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
            "water_deficit_m3h": _finite(water.deficit_m3h, 1),
            "discharge_m3h": _finite(water.discharge_m3h, 1),
            "permit_m3h": self.model.p("water.permit_m3h"),
            "permit_use_pct": _finite(water.permit_use_pct, 1),
            "water_deficit_all_lines_m3h": _finite(lines.deficit_m3h, 1),
            "discharge_all_lines_m3h": _finite(lines.discharge_m3h, 1),
            "permit_use_all_lines_pct": _finite(lines.permit_use_pct, 1),
            "water_basis": wording.water_basis(self.regime_rates(res)),
            "tailings_free_kt": _finite(res.tailings.free_t / cap.KILO, 0),
            "tailings_years_left": _finite(res.tailings.years_left, 1),
            "stockpile_t": _finite(stockpile_t, 0),
            "stockpile_days_left": _finite(stock["days"], 0),
            "stockpile_mine_tpd": _finite(stock["mine_tpd"], 0),
            "stockpile_plant_tpd": _finite(stock["plant_tpd"], 0),
            "stockpile_net_tpd": _finite(stock["net_tpd"], 0),
            "stockpile_trend": stock["trend"],
            "dewatering_margin": _finite(res.dewatering.margin, 2),
            "dewatering_margin_next_failure": _finite(res.dewatering.margin_next_failure, 2),
            "pumps_standby": res.dewatering.standby_pumps,
            "dewatering_reserve": wording.reserve_phrase(res.dewatering),
        }

    def links(self, res: cap.Result, flood_eta_min: Optional[float] = None) -> List[Dict[str, Any]]:
        """The eight links in ranking order with their capacity, knob stage and a line of detail
        (the dewatering line names the next level the rising water reaches, and ``flood_eta_min``)."""
        rows = []
        for link in cap.LINKS:
            knob = cap.MEASURE_KNOBS.get(link)
            row = {"id": link, "name": wording.link_name(link), "cap_ktpa": res.capacity_rounded[link],
                   "limiting": res.capacity_rounded[link] is not None, "binding": link == res.binding_link,
                   "knob": knob,
                   "stage": getattr(res.state, knob) if knob else None,
                   "stage_max": cap.knob_max(self.model, knob) if knob else None,
                   "detail": wording.link_detail(self.model, self.names, link, res, flood_eta_min)}
            rows.append(row)
        return rows

    def _outcome(self, plan: Plan) -> Dict[str, Any]:
        res = plan.result
        return {"achievable_ktpa": achievable_rounded(res), "binding_link": res.binding_link,
                "binding_link_name": wording.link_name(res.binding_link), "reached": plan.reached,
                "stop_reason": plan.stop_reason}

    # --- ladder (step 4) ---------------------------------------------------------------------

    @property
    def epoch_stockpile_t(self) -> float:
        """The ROM stockpile on 1 January 2027 (``stockpile.start_t``): what a fresh Stand holds."""
        return float(self.model.p("stockpile.start_t"))

    def at_epoch(self, inputs: Inputs) -> Inputs:
        """``inputs`` with the tonnages of the epoch: the opening ROM stockpile and no tailings
        placed since 1 January 2027. The knobs (measures, disturbances) and the flooded levels stay."""
        return replace(inputs, tailings_placed_t=0.0, stockpile_t=self.epoch_stockpile_t)

    def ladder_start(self, inputs: Inputs) -> cap.State:
        """The baseline measure set under the current disturbances, with the tonnages of the epoch.

        The ladder and its horizon start on 1 January 2027 (``at_epoch``), not from the stockpile
        and tailings of the running Stand: the four targets read the same whenever they are looked
        at. Only ``projection`` starts from the current tonnages."""
        return self.state(self.at_epoch(inputs)).replace(**{knob: 0 for knob in cap.KNOBS})

    @staticmethod
    def _with_service(steps: List[Dict[str, Any]], schedule: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Step dicts with the time each would really be in service (spec 3.4, section 11 item 3):
        ``lead_years``, ``in_service_year`` (2027.5 = 1 July 2027), ``in_service_when`` («II пол.
        2027») and ``in_service_text``; for a step whose trucks or LHDs wait for the air they need
        (spec 3.4 step 5.3), ``deferred_from`` and ``deferred_when``: the time its lead time
        allowed, else ``None``; ``in_horizon`` false for a step that is not in service by the end
        of the horizon. ``schedule`` lists the entries of the steps in their order."""
        out = []
        for step, entry in zip(steps, schedule):
            out.append(dict(step, lead_years=entry["lead_years"], in_service_year=entry["time"],
                            in_service_when=entry["when_short"], in_service_text=entry["in_service_text"],
                            deferred_from=entry["deferred_from"], deferred_when=entry["deferred_from_short"],
                            in_horizon=entry["in_horizon"]))
        return out

    def _horizon(self, start: cap.State, target: float, stockpile_t: float) -> Dict[str, Any]:
        return self.horizon.plan(start, target, stockpile_t)

    def ladder_row(self, start: cap.State, target: float, stockpile_t: float) -> Dict[str, Any]:
        """The sequence for one target from ``start``, the figures of the state it ends in at the
        epoch, and its horizon: schedule, hold years, binding link by year and the ten-year economics."""
        plan = self.plan(start, target)
        horizon = self._horizon(start, target, stockpile_t)
        steps = self._with_service([step.to_dict() for step in plan.steps], horizon["sequence_schedule"])
        row: Dict[str, Any] = {"target_ktpa": target,
                               "steps": steps,
                               "sequence": plan.links,
                               "measures_count": len(plan.steps)}
        row.update(self._outcome(plan))
        row["measures"] = {knob: getattr(plan.result.state, knob) for knob in cap.KNOBS}
        row["capacities"] = dict(plan.result.capacity_rounded)
        row.update(self.kpi(plan.result, stockpile_t))
        row["horizon"] = {key: value for key, value in horizon.items() if key != "economics"}
        row["economics"] = horizon["economics"]
        return row

    def ladder(self, inputs: Inputs) -> List[Dict[str, Any]]:
        """For each target: the sequence from the baseline measure set under the current
        disturbances, the figures of the state it ends in, its horizon and its economics, all
        from the tonnages of the epoch (``ladder_start``)."""
        start = self.ladder_start(inputs)
        return [self.ladder_row(start, target, self.epoch_stockpile_t) for target in self.targets]

    # --- projection (step 5) -----------------------------------------------------------------

    def projection(self, inputs: Inputs) -> Dict[str, Any]:
        """The horizon of the current target from the current state: the stages of the current
        knob set and the remaining steps of the sequence come into service after their lead
        times from the epoch, the planner adds trucks and storage as depth and fill require, and
        the mine is stepped through 2027-2036. It starts from the current ROM stockpile and
        tailings placed (the Stand's «Прогноз … из текущего состояния»), so it follows the running
        mine. With the full measure set of a target and the tonnages of the epoch it equals that
        target's ladder row (``horizon`` and ``economics``)."""
        return dict(self._horizon(self.state(inputs), inputs.target_ktpa, inputs.stockpile_t))

    # --- effects (step 6) --------------------------------------------------------------------

    def _snapshot(self, inputs: Inputs) -> Dict[str, Any]:
        state = self.state(inputs)
        plan = self.plan(state, inputs.target_ktpa)
        res = plan.start
        pumps_total = self.model.p("water.ps_p150.pumps")
        return {"target_ktpa": inputs.target_ktpa, "binding_link": res.binding_link,
                "achievable_ktpa": achievable_rounded(res), "capacities": dict(res.capacity_rounded),
                "measures_needed": len(plan.steps), "flooded_levels": tuple(res.dewatering.flooded_levels),
                "water_rising": res.dewatering.water_rising,
                "held_trucks": tuple(res.air.held_trucks), "held_lhds": tuple(res.air.held_lhds),
                "pumps_total": pumps_total, "pumps_available": pumps_total - state.pumps_failed_p150,
                "permit_exceeded": self.water_regime(res)[0].permit_state == "exceeded",
                "kpi": self.kpi(res, inputs.stockpile_t)}

    def effects(self, before: Optional[Inputs], after: Inputs) -> Dict[str, Any]:
        """What the last change of the scenario did: before -> after of every capacity and KPI.

        ``before`` holds the knobs and the flooded levels before the change. Both sides are
        evaluated with the tonnages of ``after`` (stockpile, tailings placed), so that the list
        shows the change and not the drift of the running mine. With no ``before`` the list is
        empty. A change of the target adds the economics of the new target: its ladder row, from
        the tonnages of the epoch like the ladder.
        """
        head = {"revision": after.revision, "label": after.label,
                "before_revision": before.revision if before else None,
                "before_label": before.label if before else None}
        if before is None:
            return dict(head, items=[])
        same_tonnages = replace(before, tailings_placed_t=after.tailings_placed_t, stockpile_t=after.stockpile_t)
        items = wording.effect_items(self.names, self._snapshot(same_tonnages), self._snapshot(after))
        if before.target_ktpa != after.target_ktpa:
            row = self.ladder_row(self.ladder_start(after), after.target_ktpa, self.epoch_stockpile_t)
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
        state), ``sustainable_baseline``, ``ladder`` (one row per target, with ``horizon`` and
        ``economics``, from the tonnages of the epoch), ``projection`` (the horizon of the current
        state, with the current tonnages), ``effects``,
        ``calibration``. Every step of ``sequence`` and of the ladder carries the time it would
        really be in service (``lead_years``, ``in_service_year``, ``in_service_text``).
        """
        state = self.state(inputs)
        plan = self.plan(state, inputs.target_ktpa)
        res = plan.start
        projection = self.projection(inputs)
        steps = self._with_service([step.to_dict() for step in plan.steps], projection["sequence_schedule"])
        eta = wording.flood_eta_phrase(self.names, res.dewatering, inputs.flood_eta_min)
        for step in steps:      # restoring the pumps: what happens meanwhile
            if eta and step["knob"] == PUMPS_KNOB and step["kind"] == DISTURBANCE:
                step["text"] += f"; пока насосы стоят, {eta}"
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
            "links": self.links(res, inputs.flood_eta_min),
            "next_measure": steps[0] if steps else None,
            "measures_needed": len(steps),
            "sequence": steps,
            "sequence_outcome": self._outcome(plan),
            "conditions": self.conditions(res),
            "kpi": self.kpi(res, inputs.stockpile_t),
            "sustainable_baseline": self.sustainable_baseline(),
            "ladder": self.ladder(inputs),
            "projection": projection,
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
        schedule = self.projection(inputs)["sequence_schedule"]
        return {"mode": mode, "revision": inputs.revision, "target_ktpa": inputs.target_ktpa,
                "binding_link": binding, "changes": changes,
                "steps": self._with_service([step.to_dict() for step in steps], schedule), "reason": reason,
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
