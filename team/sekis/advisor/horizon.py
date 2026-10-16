"""Ten-year horizon of the Expansion Advisor (spec 3.4 steps 4 and 5, section 11 item 3).

The ladder of ``engine`` removes the binding links at the depth and with the storage of the
epoch. The horizon asks whether a target can be *held* over 2027-2036 and in which steps:

1. The measures of the ladder are decided on 1 January 2027 (``sim.epoch``) and come into
   service after their lead times (``capacity.lead_years``); a repair of a disturbance at once.
   The stages of the current knob set (the projection) are treated the same way: the Stand
   switches knobs at once, the horizon builds them.
2. The mine is stepped half a year at a time (``ladder.horizon.steps_per_year``). Before each
   step the planner looks ahead: with every measure decided so far taken as built, does the
   chain carry what the plant in service can take (at most the target), at the depth of the step
   and with the storage left? If not, it runs the constraint loop again at those conditions and
   decides further measures so that each is in service at the start of the step, never before
   its lead time after the epoch. Beyond the stages of the knobs the loop has one more truck at
   a time (``State.extra_trucks``: the haulage that keeps pace with depth) and the second and
   third tailings stages (``State.tailings_extra_t``, ``tsf.measure_X2_t``, ``tsf.measure_X3_t``).
   When the loop runs out of stages, the target cannot be held from that step on, and the
   measures that would not raise the rate are not bought.
3. Admission of units. A measure that brings diesel units into service (a stage of ``m_haul``
   or ``m_stopes``, a depth truck) enters service at its time only if the air in service admits
   its units: the hold rule of spec 2.6 parks whole units in a fixed order, so trucks or LHDs
   that came before the fan they need would wait for air and park units of the base fleet, and
   the chain would hoist less. Of the unit measures due in a step the planner brings in the set
   (stages in order) with which the hold rule parks no further unit and the mine hoists no less,
   choosing the most ore the plant in service can take, then the most measures; the others wait
   for the next step (``Entry.earliest`` keeps the time their lead time allowed, ``Entry.waits``
   the fans that came with them). So no step of a plan hoists less than the same mine without
   those measures, and a measure whose units would wait for air to the end is not bought.
4. In each step the mine hoists what its links allow (at the mid depth of the step), the plant
   mills what its links, the storage left and the ROM stockpile allow, the stockpile takes the
   difference (it is not refilled beyond its opening tonnage), the centroid drops by the ore
   hoisted (``capacity.centroid_after``) and the dams fill with the ore milled.
5. ``economics`` values the extra gold against a reference, the mine as it is (no expansion
   measure, no disturbance) with only the storage it needs to keep running, at the price and
   AISC of ``params.json``, less the corporate income tax on the extra margin, with the
   published capex and, apart, the assumed costs of trucks and storage.

Every number is a value of ``sekis.capacity`` for some state or a parameter of ``params.json``;
this module adds sums, products with prices, discounting and the choice of states and times.
Standard library only.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .. import capacity as cap
from . import wording
from .engine import (DISTURBANCE, MEASURE, MINE_LINKS, PUMPS_KNOB, RESTORE_PUMPS, achievable_rounded)

__all__ = ["Horizon", "Entry", "DEPTH_TRUCK", "STORAGE", "ORIGIN_LADDER", "ORIGIN_CURRENT", "ORIGIN_HORIZON"]

#: Kinds of schedule entry beyond the ``measure`` and ``disturbance`` of ``engine``.
DEPTH_TRUCK = "depth_truck"   # one more truck beyond the m_haul stage (State.extra_trucks)
STORAGE = "storage"           # a tailings stage beyond the new cell (State.tailings_extra_t)

#: Measure knobs whose stages bring diesel units (trucks, LHDs) into service; with the depth
#: trucks they are admitted only when the air admits their units (module docstring, item 3).
UNIT_KNOBS = ("m_haul", "m_stopes")

#: Parameters of the tailings stages beyond the new cell, in the order they are built:
#: (storage, lead time). ``Entry.stage`` of a storage entry is its position here, from 1.
STORAGE_STAGES = (("tsf.measure_X2_t", "tsf.measure_X2_lead_years"),
                  ("tsf.measure_X3_t", "tsf.measure_X3_lead_years"))
TONNE_EPS = 1.0   # comparison of storage tonnages, t; not a model number

#: Why an entry is on the schedule.
ORIGIN_CURRENT = "current"    # a stage of the current knob set
ORIGIN_LADDER = "ladder"      # a step of the sequence to the target, decided at the epoch
ORIGIN_HORIZON = "horizon"    # added later because depth or storage requires it

PLANT_LINKS = ("plant", "water")
MILLION = 1.0e6
EPS = 1.0e-9      # comparison of times and tonnages, not a model number
MAX_MOVES = 64    # guard of one run of the constraint loop, not a model number


@dataclass(frozen=True)
class Entry:
    """One measure of the schedule: what comes into service when.

    ``time`` is the start of service in years (2027.5 = 1 July 2027), ``lead_years`` the time
    from the decision to service, so ``decided = time - lead_years``. ``stage`` is the new stage
    of ``knob`` (a measure), the count of extra trucks after the entry (a depth truck) or the
    position of the storage stage in ``STORAGE_STAGES`` (1: the second tailings stage, 2: the
    third). ``trucks`` and ``storage_t`` are the trucks and the storage it adds (for the capex).
    ``changes`` are the knob changes of the Stand, empty for the horizon measures.

    ``earliest`` is set for a unit measure that waited beyond its lead time because its units
    would have waited for air (module docstring, item 3): the time its lead time allowed.
    ``waits`` names, in Russian, the ventilation stage that came into service with it, if any.
    """
    time: float
    lead_years: float
    kind: str
    link: str
    knob: Optional[str]
    stage: int
    changes: Mapping[str, float]
    origin: str
    text: str
    trucks: int = 0
    storage_t: float = 0.0
    earliest: Optional[float] = None
    waits: str = ""

    @property
    def decided(self) -> float:
        return self.time - self.lead_years

    @property
    def units(self) -> bool:
        """True for a measure that brings diesel units into service (module docstring, item 3)."""
        return self.kind == DEPTH_TRUCK or (self.kind == MEASURE and self.knob in UNIT_KNOBS)

    @property
    def group(self) -> str:
        """Entries of one group come into service in the order of their stages."""
        return self.knob if self.kind == MEASURE else self.kind


@dataclass(frozen=True)
class _Move:
    """A step of the horizon's constraint loop with the evaluated state after it."""
    kind: str
    link: str
    knob: Optional[str]
    stage: int
    changes: Mapping[str, float]
    text: str
    lead_years: float
    result: cap.Result
    trucks: int = 0
    storage_t: float = 0.0


@dataclass(frozen=True)
class _Flow:
    """One step of the mine: what was hoisted and milled and what limited it."""
    time: float
    state: cap.State
    result: cap.Result
    mined_t: float
    milled_t: float
    link: str
    mine_link: str
    mine_ktpa: float
    centroid_m: float       # at the end of the step
    placed_t: float         # at the end of the step
    stock_t: float          # at the end of the step
    storage_short_t: float = 0.0   # ore the plant could have milled but the storage could not take


@dataclass
class _Run:
    """Everything one run of the horizon produced."""
    target_ktpa: float
    reference: bool
    entries: List[Entry]
    flows: List[_Flow]
    sequence: List[Entry] = field(default_factory=list)          # the entries of the epoch's steps, in order
    failures: List[Tuple[float, str, int]] = field(default_factory=list)


class Horizon:
    """The horizon of one ``Advisor``: runs, year rows, hold analysis and economics."""

    def __init__(self, advisor: Any, years: int):
        self.adv = advisor
        self.model: cap.Model = advisor.model
        p = self.model.p
        self.t0 = float(advisor.first_year)
        self.per_year = int(p("ladder.horizon.steps_per_year"))
        self.dt = 1.0 / self.per_year
        self.years = years
        self.last_year = advisor.first_year + years - 1
        self._cache: Dict[Any, Dict[str, Any]] = {}

    # --- times -----------------------------------------------------------------------------

    def on_grid(self, time: float) -> float:
        """The start of the step in which ``time`` falls or the next one: service begins with a step."""
        steps = math.ceil((time - self.t0) / self.dt - EPS)
        return self.t0 + max(0, steps) * self.dt

    # --- states ----------------------------------------------------------------------------

    def _evaluate(self, state: cap.State, centroid: float, placed: float) -> cap.Result:
        return cap.evaluate(self.model, state.replace(centroid_m=centroid, tailings_placed_t=placed))

    def _physical(self, res: cap.Result) -> cap.Result:
        """The result with the tailings link as the storage left for one step, not the 3-year rule.

        Over the horizon the lead time of each storage stage is explicit, so storage binds only
        when the free volume cannot take a step of ore.
        """
        caps = dict(res.capacity_ktpa)
        caps["tailings"] = res.tailings.free_t / cap.KILO / self.dt
        return replace(res, capacity_ktpa=caps, capacity_rounded={k: cap.round_kt(v) for k, v in caps.items()},
                       binding_link=cap.binding_link(caps), achievable_ktpa=min(caps.values()))

    @staticmethod
    def _base(start: cap.State) -> cap.State:
        """The mine as built at the epoch: the start's disturbances and conditions, stage 0 everywhere."""
        return start.replace(**{knob: 0 for knob in cap.KNOBS}, extra_trucks=0, tailings_extra_t=0.0)

    def state_at(self, base: cap.State, entries: Sequence[Entry], time: float) -> cap.State:
        """The state with every entry in service at ``time`` (``math.inf``: everything decided)."""
        knobs = {knob: 0 for knob in cap.KNOBS}
        changes: Dict[str, Any] = {}
        extra, storage = 0, 0.0
        flooded = base.flooded_levels
        for entry in entries:
            if entry.time > time + EPS:
                continue
            if entry.kind == MEASURE:
                knobs[entry.knob] = max(knobs[entry.knob], entry.stage)
            elif entry.kind == DISTURBANCE:
                if entry.changes:
                    value = getattr(base, entry.knob)
                    changes[entry.knob] = type(value)(0)
                if entry.knob == PUMPS_KNOB:
                    flooded = ()
            elif entry.kind == DEPTH_TRUCK:
                extra = max(extra, entry.stage)
            elif entry.kind == STORAGE:
                storage += entry.storage_t
        if changes.get("line_down", base.line_down) > self.model.p("ladder.m_plant.lines")[knobs["m_plant"]]:
            changes["line_down"] = 0     # the line stopped for repair is not built yet at this time
        return base.replace(**knobs, **changes, extra_trucks=extra, tailings_extra_t=storage, flooded_levels=flooded)

    def storage_stages_built(self, extra_t: float) -> int:
        """How many stages of ``STORAGE_STAGES`` the storage beyond the registry, ``extra_t``, holds."""
        built, total = 0, 0.0
        for size_id, _ in STORAGE_STAGES:
            total += float(self.model.p(size_id))
            if extra_t + TONNE_EPS < total:
                break
            built += 1
        return built

    # --- what one stage adds ---------------------------------------------------------------

    def _adds(self, knob: str, from_stage: int, to_stage: int) -> Tuple[int, float]:
        """Trucks and storage (t) that raising ``knob`` from one stage to another adds."""
        p = self.model.p
        if knob == "m_haul":
            trucks = p("ladder.m_haul.trucks")
            return trucks[to_stage] - trucks[from_stage], 0.0
        if knob == "m_tailings":
            stages = p("ladder.m_tailings.dams")
            added = [name for name in stages[to_stage] if name not in stages[from_stage]]
            return 0, sum(self.model.dams[name].capacity_t for name in added)
        return 0, 0.0

    def _entry(self, move: Any, time: float, origin: str, after: Dict[str, float]) -> Entry:
        """Schedule a move (a ``_Move`` or an engine ``Step``): in service at ``time`` at the
        earliest, never before its lead time after the epoch nor before the stage below it."""
        kind = move.kind
        if kind == MEASURE and (move.knob == PUMPS_KNOB or getattr(move, "measure", None) == RESTORE_PUMPS):
            kind = DISTURBANCE           # pumping flooded levels out with sound pumps: operational
        if kind == DISTURBANCE:
            return Entry(time=time, lead_years=0.0, kind=DISTURBANCE, link=move.link, knob=move.knob, stage=0,
                         changes=dict(move.changes), origin=origin, text=move.text)
        if kind == MEASURE:
            stage = move.to_stage if hasattr(move, "to_stage") else move.stage
            lead = cap.lead_years(self.model, move.knob, stage)
            key = move.knob
            trucks, storage = self._adds(move.knob, stage - 1, stage)
        else:
            stage, lead, key = move.stage, move.lead_years, kind
            trucks, storage = move.trucks, move.storage_t
        start = self.on_grid(max(time, self.t0 + lead, after.get(key, self.t0)))
        after[key] = start
        return Entry(time=start, lead_years=lead, kind=kind, link=move.link, knob=move.knob if kind == MEASURE else None,
                     stage=stage, changes=dict(move.changes), origin=origin, text=move.text, trucks=trucks,
                     storage_t=storage)

    def _current_entries(self, start: cap.State, after: Dict[str, float]) -> List[Entry]:
        """The stages of the current knob set, decided at the epoch like the ladder."""
        link_of = {knob: link for link, knob in cap.MEASURE_KNOBS.items()}
        entries = []
        for knob in cap.KNOBS:
            for stage in range(1, getattr(start, knob) + 1):
                before = cap.evaluate(self.model, start.replace(**{knob: stage - 1}, line_down=0))
                now = cap.evaluate(self.model, start.replace(**{knob: stage}, line_down=0))
                text = wording.measure_text(self.model, self.adv.names, link_of[knob], before, now)
                trucks, storage = self._adds(knob, stage - 1, stage)
                lead = cap.lead_years(self.model, knob, stage)
                time = self.on_grid(max(self.t0 + lead, after.get(knob, self.t0)))
                after[knob] = time
                entries.append(Entry(time=time, lead_years=lead, kind=MEASURE, link=link_of[knob], knob=knob,
                                     stage=stage, changes={knob: float(stage)}, origin=ORIGIN_CURRENT, text=text,
                                     trucks=trucks, storage_t=storage))
        return entries

    def _repairs(self, start: cap.State, done: set) -> List[Entry]:
        """Every removable disturbance of ``start`` the sequence does not already remove, repaired at
        the epoch (an operational action, spec 3.4 step 3), and flooded levels pumped out: over ten
        years a failed pump or a closed decline is not left as it is because the target is met."""
        entries = []
        res = cap.evaluate(self.model, start)
        while True:
            found = self.adv.disturbance_step(res)
            if found is None:
                break
            step, res = found
            if step.knob not in done:
                entries.append(self._entry(step, self.t0, ORIGIN_LADDER, {}))
        if res.state.flooded_levels and PUMPS_KNOB not in done:
            entries.append(Entry(time=self.t0, lead_years=0.0, kind=DISTURBANCE, link="dewatering", knob=PUMPS_KNOB,
                                 stage=0, changes={}, origin=ORIGIN_LADDER,
                                 text=wording.measure_text(self.model, self.adv.names, "dewatering", res,
                                                           cap.evaluate(self.model, res.state.replace(flooded_levels=())))))
        return entries

    # --- the constraint loop over the horizon ----------------------------------------------

    def _move(self, res: cap.Result, links: Optional[Sequence[str]]) -> Optional[_Move]:
        """The next step for ``res``: a repair, one more stage, one more truck or the storage stage."""
        p = self.model.p
        if links is None:
            found = self.adv.disturbance_step(res)
            if found is not None:
                step, after = found
                return _Move(kind=DISTURBANCE, link=step.link, knob=step.knob, stage=0, changes=step.changes,
                             text=step.text, lead_years=0.0, result=self._physical(after))
        link, state = res.binding_link, res.state
        if links is not None and link not in links:
            return None
        if link == "haulage":   # over the horizon one truck at a time: the next of the registry, then AD45s
            new = state.replace(extra_trucks=state.extra_trucks + 1)
            after = self._physical(cap.evaluate(self.model, new))
            return _Move(kind=DEPTH_TRUCK, link=link, knob=None, stage=new.extra_trucks, changes={},
                         text=wording.measure_text(self.model, self.adv.names, link, res, after),
                         lead_years=float(p("ladder.depth_trucks.lead_years")), result=after, trucks=1)
        if link == "tailings" and state.m_tailings >= cap.knob_max(self.model, "m_tailings"):
            stage = self.storage_stages_built(state.tailings_extra_t) + 1
            if stage > len(STORAGE_STAGES):
                return None
            size_id, lead_id = STORAGE_STAGES[stage - 1]
            size = float(p(size_id))
            new = state.replace(tailings_extra_t=state.tailings_extra_t + size)
            after = self._physical(cap.evaluate(self.model, new))
            return _Move(kind=STORAGE, link=link, knob=None, stage=stage, changes={},
                         text=wording.storage_stage_text(res, after, size, stage),
                         lead_years=float(p(lead_id)), result=after, storage_t=size)
        found = self.adv.next_step(res)
        if found is None:
            return None
        step, after = found
        return _Move(kind=step.kind, link=step.link, knob=step.knob, stage=step.to_stage, changes=step.changes,
                     text=step.text, lead_years=0.0, result=self._physical(after))

    def _close_gap(self, res: cap.Result, need: float,
                   links: Optional[Sequence[str]] = None) -> Tuple[List[_Move], Optional[cap.Result]]:
        """Moves that bring the chain of ``res`` to ``need``, and the state where no stage was
        left (``None`` when ``need`` is met). Moves after the best rate reached are dropped:
        nothing is bought that does not raise the rate."""
        moves: List[_Move] = []
        best_rate, best_count = achievable_rounded(res), 0
        while achievable_rounded(res) < need and len(moves) < MAX_MOVES:
            move = self._move(res, links)
            if move is None:
                break
            moves.append(move)
            res = move.result
            if achievable_rounded(res) > best_rate:
                best_rate, best_count = achievable_rounded(res), len(moves)
        if achievable_rounded(res) >= need:
            return moves, None
        return moves[:best_count], res

    # --- admission of units (module docstring, item 3) ---------------------------------------

    def _admit(self, base: cap.State, entries: List[Entry], time: float, depth: float, placed: float,
               need: float) -> None:
        """Bring in the unit measures due at ``time`` whose units the air admits; defer the rest.

        Every set of the due unit measures that keeps the stages of each group in order is
        evaluated with the measures already in service, at ``depth`` and ``placed``. A set is
        admissible when the hold rule parks no unit that it does not park without the set and the
        mine hoists no less. Of those, the set kept gives the most ore the plant in service can
        take (the mine links, at most ``need``, rounded to 1 kt/yr), then has the most measures.
        The measures left out move to the next step; ``entries`` is changed in place.
        """
        due = [index for index, entry in enumerate(entries) if entry.units and abs(entry.time - time) < EPS]
        if not due:
            return
        groups: Dict[str, List[int]] = {}
        for index in due:
            groups.setdefault(entries[index].group, []).append(index)
        order = {knob: rank for rank, knob in enumerate(cap.KNOBS)}
        keys = sorted(groups, key=lambda key: order.get(key, len(order)))
        for key in keys:
            groups[key].sort(key=lambda index: entries[index].stage)
        skip = set(due)
        fixed = [entry for index, entry in enumerate(entries) if index not in skip and entry.time <= time + EPS]
        # Depth trucks are trucks beyond the fleet of the m_haul stages: none before every stage is in.
        haul_later = any(e.kind == MEASURE and e.knob == "m_haul" and e.time > time + EPS for e in entries)
        best: Optional[Tuple[Tuple[int, int], Tuple[int, ...]]] = None
        floor: Optional[Tuple[int, int]] = None      # rate and held units without any due measure
        for counts in itertools.product(*(range(len(groups[key]) + 1) for key in keys)):
            size = dict(zip(keys, counts))
            if size.get(DEPTH_TRUCK) and (haul_later or size.get("m_haul", 0) < len(groups.get("m_haul", ()))):
                continue
            chosen = [entries[index] for key, count in zip(keys, counts) for index in groups[key][:count]]
            res = self._evaluate(self.state_at(base, fixed + chosen, time), depth, placed)
            rate = cap.round_kt(min(min(res.capacity_ktpa[link] for link in MINE_LINKS), need))
            held = len(res.air.held_trucks) + len(res.air.held_lhds)
            if floor is None:                        # the first set is the empty one
                floor = (rate, held)
            if held > floor[1] or rate < floor[0]:
                continue
            score = (rate, len(chosen))
            if best is None or score > best[0]:      # ties: the first set in KNOBS order wins
                best = (score, counts)
        admitted = {index for key, count in zip(keys, best[1]) for index in groups[key][:count]}
        for index in due:
            entry = entries[index]
            if index in admitted:
                if entry.earliest is not None:
                    entries[index] = replace(entry, waits=self._air_entering(entries, time))
                continue
            entries[index] = replace(entry, time=time + self.dt,
                                     earliest=entry.time if entry.earliest is None else entry.earliest)

    def _air_entering(self, entries: Sequence[Entry], time: float) -> str:
        """The fans a ventilation stage or repair brings into service at ``time``, in Russian."""
        fans: List[str] = []
        stages = self.model.p("ladder.m_vent.fans")
        for entry in entries:
            if entry.link != "ventilation" or abs(entry.time - time) >= EPS:
                continue
            if entry.kind == MEASURE:
                fans += [fan for fan in stages[entry.stage] if fan not in stages[entry.stage - 1]]
            elif entry.kind == DISTURBANCE and entry.knob == "fan_vs2_off":
                fans.append("fan-vs2")
        return wording.fan_names(self.adv.names, fans)

    # --- one step of the mine ----------------------------------------------------------------

    def _flow(self, time: float, state: cap.State, centroid: float, placed: float, stock: float,
              stock_cap: float) -> _Flow:
        """Hoisting and milling of one step; haulage at the step's mid depth (a second pass)."""
        p = self.model.p
        dt_t = self.dt * cap.KILO
        mid = centroid
        for _ in range(2):   # first at the start depth, then at the mid depth that ore implies
            res = self._evaluate(state, mid, placed)
            caps = res.capacity_ktpa
            mine = min(caps[link] for link in MINE_LINKS)
            plant = min(caps[link] for link in PLANT_LINKS)
            limits = {"mine": mine * dt_t + stock, "plant": plant * dt_t, "storage": max(0.0, res.tailings.free_t)}
            milled = max(0.0, min(limits.values()))
            mined = min(mine * dt_t, milled + max(0.0, stock_cap - stock))
            mid = centroid - mined / 2 / p("dev.t_per_vm")
        mine_caps = {link: (caps[link] if link in MINE_LINKS else math.inf) for link in cap.LINKS}
        mine_link = cap.binding_link(mine_caps)
        unmet = max(0.0, min(limits["mine"], limits["plant"]) - milled)   # what storage alone kept back
        if limits["storage"] < min(limits["mine"], limits["plant"]) - EPS:
            link = "tailings"
        elif limits["mine"] < limits["plant"] - EPS:
            link = mine_link
        else:   # a tie at the shown precision goes to the plant, as in the tie-break order of LINKS
            link = "plant" if cap.round_kt(caps["plant"]) <= cap.round_kt(caps["water"]) else "water"
        return _Flow(time=time, state=state, result=res, mined_t=mined, milled_t=milled, link=link,
                     mine_link=mine_link, mine_ktpa=mine, centroid_m=cap.centroid_after(self.model, centroid, mined),
                     placed_t=placed + milled, stock_t=stock + mined - milled,
                     storage_short_t=unmet if link == "tailings" else 0.0)

    # --- a run -----------------------------------------------------------------------------

    def _run(self, start: cap.State, target: float, stockpile_t: float, reference: bool) -> _Run:
        p = self.model.p
        base = self._base(start)
        after: Dict[str, float] = {}
        entries: List[Entry] = []
        sequence: List[int] = []     # positions in ``entries`` of the steps of the sequence
        if not reference:
            entries += self._current_entries(start, after)
            plan = self.adv.plan(start, target)
            sequence = list(range(len(entries), len(entries) + len(plan.steps)))
            entries += [self._entry(step, self.t0, ORIGIN_LADDER, after) for step in plan.steps]
            entries += self._repairs(start, {entries[i].knob for i in sequence if entries[i].kind == DISTURBANCE})
        run = _Run(target_ktpa=target, reference=reference, entries=entries, flows=[])
        centroid = p("stope.centroid_baseline_m") if start.centroid_m is None else start.centroid_m
        placed, stock = start.tailings_placed_t, stockpile_t
        for index in range(self.years * self.per_year):
            time = self.t0 + index * self.dt
            actual = self.state_at(base, entries, time)
            now = self._physical(self._evaluate(actual, centroid, placed))
            if reference:   # only the storage the mine needs to keep running
                need = min(v for k, v in now.capacity_ktpa.items() if k != "tailings")
                links: Optional[Sequence[str]] = ("tailings",)
            else:           # what the plant in service can take, at most the target
                need = min(target, min(now.capacity_ktpa[link] for link in PLANT_LINKS))
                links = None
            need = cap.round_kt(need)
            look_depth = centroid - need * self.dt * cap.KILO / 2 / p("dev.t_per_vm")
            planned = self._physical(self._evaluate(self.state_at(base, entries, math.inf), look_depth, placed))
            if achievable_rounded(planned) < need:
                moves, failed = self._close_gap(planned, need, links)
                entries += [self._entry(move, time, ORIGIN_HORIZON, after) for move in moves]
                if failed is not None:
                    run.failures.append((time, failed.binding_link, achievable_rounded(failed)))
            self._admit(base, entries, time, look_depth, placed, need)
            actual = self.state_at(base, entries, time)
            flow = self._flow(time, actual, centroid, placed, stock, stockpile_t)
            run.flows.append(flow)
            centroid, placed, stock = flow.centroid_m, flow.placed_t, flow.stock_t
        run.sequence = [entries[i] for i in sequence]
        entries.sort(key=lambda e: e.time)   # stable: entries of one time keep the order they were decided in
        return run

    # --- year rows ---------------------------------------------------------------------------

    def _rows(self, run: _Run) -> List[Dict[str, Any]]:
        model, p = self.model, self.model.p
        names = self.adv.names
        rows: List[Dict[str, Any]] = []
        gold_total = 0.0
        bottoms = {key: p(f"decline.{key}.design_bottom_m") for key in model.declines}
        stages = self._storage_entries(run)
        for year_index in range(self.years):
            year = self.adv.first_year + year_index
            part = run.flows[year_index * self.per_year:(year_index + 1) * self.per_year]
            milled = sum(f.milled_t for f in part)
            mined = sum(f.mined_t for f in part)
            limiting = min(part, key=lambda f: f.milled_t)
            last = part[-1]
            grade = last.result.gold.grade_gpt
            gold = cap.gold_oz(model, milled, grade)
            gold_total += gold
            storage = cap.tailings(model, last.state.m_tailings, last.placed_t, milled / cap.KILO,
                                   last.state.tailings_extra_t)
            shown = cap.round_kt(milled / cap.KILO)
            start_centroid = part[0].centroid_m + part[0].mined_t / p("dev.t_per_vm")
            crossed = [key for key, bottom in bottoms.items() if start_centroid >= bottom > last.centroid_m]
            entering = [e for e in run.entries if year - EPS <= e.time < year + 1 - EPS]
            built = sum(1 for e in stages if e.time <= last.time + EPS)
            new_stages = [(self.storage_position(e), e.time, e.decided, e.kind == STORAGE)
                          for e in stages if year - EPS <= e.time < year + 1 - EPS]
            short_kt = round(sum(f.storage_short_t for f in part) / cap.KILO)
            rows.append({
                "year": year,
                "achievable_ktpa": shown,
                "mined_ktpa": cap.round_kt(mined / cap.KILO),
                "binding_link": limiting.link,
                "binding_link_name": wording.link_name(limiting.link),
                "mine_link": last.mine_link,
                "mine_link_name": wording.link_name(last.mine_link),
                "mine_ktpa": cap.round_kt(last.mine_ktpa),
                "target_met": shown >= run.target_ktpa,
                "centroid_m": round(last.centroid_m, 1),
                "gold_oz": round(gold),
                "gold_koz": round(gold / cap.KILO, 2),
                "gold_total_koz": round(gold_total / cap.KILO, 2),
                "tailings_stored_kt": round(storage.stored_t / cap.KILO),
                "tailings_free_kt": round(storage.free_t / cap.KILO),
                "tailings_years_left": (round(storage.years_left, 1) if math.isfinite(storage.years_left) else None),
                "water_deficit_m3h": round(last.result.water.deficit_m3h, 1),
                "stockpile_kt": round(last.stock_t / cap.KILO, 1),
                "trucks": len(last.result.haulage.cycles),
                "halves": [{"time": f.time, "milled_kt": round(f.milled_t / cap.KILO, 1),
                            "binding_link": f.link, "mine_link": f.mine_link} for f in part],
                "measures": [self.entry_dict(e) for e in entering],
                "storage_short_kt": short_kt,
                "note": wording.horizon_note(limiting.link, shown, cap.round_kt(limiting.mine_ktpa),
                                             [(wording.decline_label(names, key), bottoms[key]) for key in crossed],
                                             storage_next=built + 1, short_kt=short_kt, stages=new_stages),
            })
        return rows

    @staticmethod
    def _storage_entries(run: _Run) -> List[Entry]:
        """The tailings stages of a run (the new cell and the stages beyond it), in time order."""
        return sorted((e for e in run.entries if e.link == "tailings" and e.kind in (MEASURE, STORAGE)),
                      key=lambda e: e.time)

    @staticmethod
    def storage_position(entry: Entry) -> int:
        """Position of a tailings stage counted from the new cell (1): 2 for the second stage."""
        return entry.stage + 1 if entry.kind == STORAGE else entry.stage

    def in_horizon(self, entry: Entry) -> bool:
        """True when the entry comes into service before the end of the horizon."""
        return entry.time < self.t0 + self.years - EPS

    def entry_dict(self, entry: Entry) -> Dict[str, Any]:
        """An entry of the schedule as JSON.

        ``deferred_from`` is the time its lead time allowed when a unit measure waited for air
        (``None`` otherwise), ``waits_for`` the fans that came into service with it, and
        ``in_horizon`` false for a unit measure whose units the air does not admit by the end of
        the horizon (it is not bought)."""
        inside = self.in_horizon(entry)
        return {"time": entry.time, "year": int(math.floor(entry.time + EPS)), "kind": entry.kind,
                "link": entry.link, "link_name": wording.link_name(entry.link), "knob": entry.knob,
                "stage": entry.stage, "set": dict(entry.changes), "origin": entry.origin,
                "lead_years": entry.lead_years, "decided": entry.decided, "text": entry.text,
                "trucks": entry.trucks, "storage_kt": round(entry.storage_t / cap.KILO),
                "when": wording.when_text(entry.time, self.t0),
                "when_short": wording.when_short(entry.time, self.t0),
                "deferred_from": entry.earliest,
                "deferred_from_short": (wording.when_short(entry.earliest, self.t0)
                                        if entry.earliest is not None else None),
                "waits_for": entry.waits or None,
                "in_horizon": inside,
                "in_service_text": wording.in_service_text(entry.time, entry.lead_years, self.t0, entry.earliest,
                                                           entry.waits, inside, self.last_year)}

    # --- hold analysis -------------------------------------------------------------------------

    def _hold(self, run: _Run, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        """The first year the target is met, the last year of that run, and why it ends; for a
        target never met, the year that came closest (``best_year``) and why it fell short."""
        met = [row["target_met"] for row in rows]
        years = [row["year"] for row in rows]
        best = max(rows, key=lambda row: row["achievable_ktpa"])     # the first of equal years
        reached = next((year for year, ok in zip(years, met) if ok), None)
        held_to = None
        if reached is not None:
            held_to = reached
            while held_to + 1 <= self.last_year and met[years.index(held_to + 1)]:
                held_to += 1
        holds = held_to == self.last_year
        lost_year = held_to + 1 if reached is not None and not holds else None
        again = None
        if lost_year is not None:
            again = next((year for year, ok in zip(years, met) if ok and year > lost_year), None)
        check_year = lost_year if lost_year is not None else (None if reached is not None else best["year"])
        failure = None
        if check_year is not None:
            failure = next((f for f in run.failures if f[0] < check_year + 1 - EPS), None)
        elif holds and run.failures:   # held to the end, but the mine fell short and the stockpile made it up
            failure = run.failures[0]
        lost_row = rows[years.index(check_year)] if check_year is not None else None
        pending = []
        if lost_row is not None and failure is None:   # short because a measure is not in service yet
            pending = [e for e in run.entries if check_year + EPS < e.time <= check_year + 1 + EPS]
        hold = {
            "reached_year": reached,
            "held_to_year": held_to,
            "holds": holds,
            "lost_year": lost_year,
            "again_year": again,
            "lost_link": lost_row["binding_link"] if lost_row else None,
            "lost_link_name": lost_row["binding_link_name"] if lost_row else None,
            "failure_year": (int(math.floor(failure[0] + EPS)) if failure else None),
            "failure_link": failure[1] if failure else None,
            "failure_ktpa": failure[2] if failure else None,
            "best_year": best["year"],
            "best_ktpa": best["achievable_ktpa"],
        }
        hold["label"] = wording.hold_label(hold, self.last_year)
        hold["text"] = wording.hold_text(run.target_ktpa, hold, self.last_year, lost_row,
                                         self.entry_dict(pending[0]) if pending else None,
                                         storage_next=len(self._storage_entries(run)) + 1)
        return hold

    # --- public ------------------------------------------------------------------------------

    def plan(self, start: cap.State, target: float, stockpile_t: float) -> Dict[str, Any]:
        """The horizon of a target from a start state (cached): schedule, rows, hold, economics."""
        key = ("plan", start, float(target), round(float(stockpile_t)))
        if key not in self._cache:
            run = self._run(start, target, stockpile_t, reference=False)
            reference = self.reference(start, stockpile_t)
            self._remember(key, self._document(run, reference))
        return self._cache[key]

    def reference(self, start: cap.State, stockpile_t: float) -> Dict[str, Any]:
        """The mine as it is: no measure and no disturbance, the conditions (grade, inflow) of
        ``start``, and only the storage stages it needs to keep running."""
        ref_start = cap.State(grade_gpt=start.grade_gpt, inflow_factor=start.inflow_factor,
                              tailings_placed_t=start.tailings_placed_t, centroid_m=start.centroid_m)
        key = ("reference", ref_start, round(float(stockpile_t)))
        if key not in self._cache:
            run = self._run(ref_start, math.inf, stockpile_t, reference=True)
            rows = self._rows(run)
            self._remember(key, {"run": run, "rows": rows, "schedule": [self.entry_dict(e) for e in run.entries]})
        return self._cache[key]

    def _remember(self, key: Any, value: Dict[str, Any]) -> None:
        if len(self._cache) > 512:     # a bound on memory, not a model number
            self._cache.clear()
        self._cache[key] = value

    def _document(self, run: _Run, reference: Mapping[str, Any]) -> Dict[str, Any]:
        rows = self._rows(run)
        hold = self._hold(run, rows)
        schedule = [self.entry_dict(e) for e in run.entries]
        extra = [e for e in run.entries if e.kind == DEPTH_TRUCK and self.in_horizon(e)]
        stages = self._storage_entries(run)
        runs_out = next((row["year"] for row in rows if row["binding_link"] == "tailings"), None)
        short_kt = sum(f.storage_short_t for f in run.flows) / cap.KILO
        doc = {
            "first_year": self.adv.first_year,
            "last_year": self.last_year,
            "target_ktpa": run.target_ktpa,
            "schedule": schedule,
            "sequence_schedule": [self.entry_dict(e) for e in run.sequence],
            "rows": rows,
            "binding_runs": wording.binding_runs(rows),
            "trucks_end": rows[-1]["trucks"],
            "depth_trucks": len(extra),
            "trucks_beyond_registry": max(0, rows[-1]["trucks"] - len(self.model.trucks)),
            "storage_runs_out_year": runs_out,
            "target_missed_year": next((row["year"] for row in rows if not row["target_met"]), None),
            "gold_total_koz": rows[-1]["gold_total_koz"],
            "depth_rule": self.depth_rule(run),
            "storage_short_kt": round(short_kt),
            "storage_note": wording.storage_horizon_note([self.entry_dict(e) for e in stages], runs_out,
                                                         self.last_year, round(short_kt)),
        }
        doc.update(hold)
        doc["economics"] = self.economics(run, rows, reference, hold)
        return doc

    # --- the depth rule ------------------------------------------------------------------------

    def depth_rule(self, run: _Run) -> Dict[str, Any]:
        """How many metres of deepening cost the fleet one truck, from the haulage formula.

        Taken at the fleet and depth of the first step in which the full plan of the epoch is
        in service: ``tonnes of one more truck / loss of fleet tonnes per metre``, the loss per
        metre over one floor (``level.floor_height_m``).
        """
        p = self.model.p
        flow = run.flows[0]
        state = self.state_at(self._base(flow.state), [e for e in run.entries if e.origin != ORIGIN_HORIZON],
                              math.inf).replace(centroid_m=p("stope.centroid_baseline_m"))
        fleet = cap.haulage(self.model, state).capacity_ktpa
        more = state.replace(extra_trucks=state.extra_trucks + 1)
        one = cap.haulage(self.model, more).capacity_ktpa - fleet
        floor = p("level.floor_height_m")
        deeper = cap.haulage(self.model, state.replace(centroid_m=state.centroid_m - floor)).capacity_ktpa
        per_metre = (fleet - deeper) / floor
        metres = one / per_metre if per_metre > 0 else None
        trucks = len(cap.active_trucks(self.model, state))
        rule = {"fleet_trucks": trucks, "fleet_ktpa": cap.round_kt(fleet), "truck_ktpa": round(one),
                "loss_ktpa_per_m": round(per_metre, 2),
                "metres_per_truck": round(metres) if metres else None,
                "model": p("ladder.depth_trucks.model")}
        rule["text"] = wording.depth_rule_text(rule, p("stope.centroid_baseline_m"))
        return rule

    # --- economics -----------------------------------------------------------------------------

    def _spread(self, entry: Entry, amount: float) -> Dict[int, float]:
        """An amount spread evenly over the lead time of an entry, by calendar year."""
        start, end = entry.decided, entry.time
        if end - start <= EPS:
            return {int(math.floor(start + EPS)): amount}
        out: Dict[int, float] = {}
        year = int(math.floor(start + EPS))
        while year < end - EPS:
            overlap = min(end, year + 1) - max(start, year)
            if overlap > EPS:
                out[year] = out.get(year, 0.0) + amount * overlap / (end - start)
            year += 1
        return out

    def _assumed(self, entries: Sequence[Entry]) -> Tuple[Dict[int, float], List[Dict[str, Any]]]:
        """Assumed capex (not published) of trucks and storage by year, and its items."""
        p = self.model.p
        by_year: Dict[int, float] = {}
        items = []
        for entry in entries:
            amount = (entry.trucks * p("econ.truck_capex_usd_m")
                      + entry.storage_t * p("econ.tsf_capex_usd_per_t") / MILLION)
            if amount <= 0 or not self.in_horizon(entry):   # not in service by the end: not bought
                continue
            for year, value in self._spread(entry, amount).items():
                by_year[year] = by_year.get(year, 0.0) + value
            items.append({"entry": self.entry_dict(entry), "usd_m": round(amount, 2), "basis": "assumed"})
        return by_year, items

    def _published(self, entries: Sequence[Entry]) -> Tuple[Dict[int, float], List[Dict[str, Any]]]:
        """The published expansion capex, spread over the lead time of the first plant stage that
        reaches a target it is stated for (econ.capex_expansion_targets_ktpa)."""
        p = self.model.p
        totals = p("ladder.m_plant.capacity_ktpa")
        for entry in entries:
            if entry.kind == MEASURE and entry.knob == "m_plant" \
                    and totals[entry.stage] in p("econ.capex_expansion_targets_ktpa"):
                amount = float(p("econ.capex_expansion_usd_m"))
                return self._spread(entry, amount), [{"entry": self.entry_dict(entry), "usd_m": amount,
                                                      "basis": "published"}]
        return {}, []

    def economics(self, run: _Run, rows: Sequence[Mapping[str, Any]], reference: Mapping[str, Any],
                  hold: Mapping[str, Any]) -> Dict[str, Any]:
        """Ten years of extra gold against the reference, its margin after AISC and tax, the capex
        schedule, cumulative cash, NPV and payback year, with and without the assumed costs."""
        p = self.model.p
        price, aisc = p("econ.gold_price_usd_oz"), p("econ.aisc_usd_oz")
        rate, tax = p("econ.discount_rate_pct") / cap.PERCENT, p("econ.cit_rate") / cap.PERCENT
        published, published_items = self._published(run.entries)
        assumed, assumed_items = self._assumed(run.entries)
        ref_assumed, ref_items = self._assumed(reference["run"].entries)
        totals = p("ladder.m_plant.capacity_ktpa")
        covered = {entry.stage for entry in run.entries if entry.kind == MEASURE and entry.knob == "m_plant"
                   and totals[entry.stage] in p("econ.capex_expansion_targets_ktpa")} if published_items else set()
        not_costed = [self.entry_dict(e) for e in run.entries
                      if e.kind == MEASURE and e.trucks == 0 and e.storage_t <= 0 and self.in_horizon(e)
                      and not (e.knob == "m_plant" and e.stage in covered)]
        years: List[Dict[str, Any]] = []
        sums = {key: 0.0 for key in ("gold_oz", "reference_oz", "gain_oz", "revenue", "margin", "tax", "margin_after",
                                     "capex_published", "capex_assumed")}
        cumulative = {"disclosed": 0.0, "with_assumed": 0.0, "disclosed_pre": 0.0, "with_assumed_pre": 0.0}
        npv = dict.fromkeys(cumulative, 0.0)
        series = {key: [] for key in cumulative}
        for row, ref in zip(rows, reference["rows"]):
            year = row["year"]
            gain = row["gold_oz"] - ref["gold_oz"]
            margin = gain * (price - aisc) / MILLION
            tax_paid = margin * tax
            capex_pub = published.get(year, 0.0)
            capex_ass = assumed.get(year, 0.0) - ref_assumed.get(year, 0.0)
            cash = {"disclosed": margin - tax_paid - capex_pub, "with_assumed": margin - tax_paid - capex_pub - capex_ass,
                    "disclosed_pre": margin - capex_pub, "with_assumed_pre": margin - capex_pub - capex_ass}
            factor = 1 / (1 + rate) ** (year - self.adv.first_year + 1)
            for key, value in cash.items():
                cumulative[key] += value
                npv[key] += value * factor
                series[key].append((year, cumulative[key]))
            for key, value in (("gold_oz", row["gold_oz"]), ("reference_oz", ref["gold_oz"]), ("gain_oz", gain),
                               ("revenue", gain * price / MILLION), ("margin", margin), ("tax", tax_paid),
                               ("margin_after", margin - tax_paid), ("capex_published", capex_pub),
                               ("capex_assumed", capex_ass)):
                sums[key] += value
            years.append({
                "year": year,
                "gold_koz": round(row["gold_oz"] / cap.KILO, 2),
                "reference_gold_koz": round(ref["gold_oz"] / cap.KILO, 2),
                "gain_koz": round(gain / cap.KILO, 2),
                "revenue_usd_m": round(gain * price / MILLION, 2),
                "margin_usd_m": round(margin, 2),
                "tax_usd_m": round(tax_paid, 2),
                "margin_after_tax_usd_m": round(margin - tax_paid, 2),
                "capex_published_usd_m": round(capex_pub, 2),
                "capex_assumed_usd_m": round(capex_ass, 2),
                "cash_usd_m": round(cash["disclosed"], 2),
                "cash_with_assumed_usd_m": round(cash["with_assumed"], 2),
                "cash_pre_tax_usd_m": round(cash["disclosed_pre"], 2),
                "cash_with_assumed_pre_tax_usd_m": round(cash["with_assumed_pre"], 2),
                "cumulative_usd_m": round(cumulative["disclosed"], 2),
                "cumulative_with_assumed_usd_m": round(cumulative["with_assumed"], 2),
                "cumulative_pre_tax_usd_m": round(cumulative["disclosed_pre"], 2),
                "cumulative_with_assumed_pre_tax_usd_m": round(cumulative["with_assumed_pre"], 2),
                "discount_factor": round(factor, 4),
            })
        capex_assumed_total = sums["capex_assumed"]

        def variant(key: str, capex: float) -> Dict[str, Any]:
            def payback(points: Sequence[Tuple[int, float]]) -> Tuple[Optional[int], str]:
                if not hold["holds"]:
                    return None, "not_held"
                if min(value for _, value in points) >= -EPS:
                    return None, "no_outlay"
                for index, (year, value) in enumerate(points):
                    if value >= -EPS and all(v >= -EPS for _, v in points[index:]):
                        return year, "paid_back"
                return None, "not_paid_back"
            year_after, reason_after = payback(series[key])
            year_pre, reason_pre = payback(series[key + "_pre"])
            out = {"capex_usd_m": round(capex, 2), "cash_usd_m": round(cumulative[key], 2),
                   "npv_usd_m": round(npv[key], 2), "payback_year": year_after, "payback_reason": reason_after,
                   "pre_tax": {"cash_usd_m": round(cumulative[key + "_pre"], 2),
                               "npv_usd_m": round(npv[key + "_pre"], 2), "payback_year": year_pre,
                               "payback_reason": reason_pre}}
            out["payback_text"] = wording.payback_text(out, self.last_year, key == "disclosed")
            return out

        econ = {
            "first_year": self.adv.first_year,
            "last_year": self.last_year,
            "target_ktpa": run.target_ktpa,
            "holds": hold["holds"],
            "gold_price_usd_oz": price,
            "aisc_usd_oz": aisc,
            "margin_usd_oz": price - aisc,
            "cit_rate_pct": p("econ.cit_rate"),
            "discount_rate_pct": p("econ.discount_rate_pct"),
            "years": years,
            "totals": {
                "gold_koz": round(sums["gold_oz"] / cap.KILO, 1),
                "reference_gold_koz": round(sums["reference_oz"] / cap.KILO, 1),
                "gain_koz": round(sums["gain_oz"] / cap.KILO, 1),
                "revenue_usd_m": round(sums["revenue"], 1),
                "margin_usd_m": round(sums["margin"], 1),
                "tax_usd_m": round(sums["tax"], 1),
                "margin_after_tax_usd_m": round(sums["margin_after"], 1),
                "capex_published_usd_m": round(sums["capex_published"], 1),
                "capex_assumed_usd_m": round(capex_assumed_total, 1),
            },
            "variants": {"disclosed": variant("disclosed", sums["capex_published"]),
                         "with_assumed": variant("with_assumed", sums["capex_published"] + capex_assumed_total)},
            "capex_items": published_items + assumed_items,
            "reference_capex_items": ref_items,
            "not_costed": not_costed,
            "capex_disclosed": bool(published_items),
            "capex_usd_m": published_items[0]["usd_m"] if published_items else None,
            "sources": {"gold_price_usd_oz": "econ.gold_price_usd_oz", "aisc_usd_oz": "econ.aisc_usd_oz",
                        "capex_usd_m": "econ.capex_expansion_usd_m", "cit_rate": "econ.cit_rate",
                        "discount_rate_pct": "econ.discount_rate_pct", "truck_capex_usd_m": "econ.truck_capex_usd_m",
                        "tsf_capex_usd_per_t": "econ.tsf_capex_usd_per_t"},
        }
        econ.update(wording.horizon_economics_notes(self.model, econ))
        return econ
