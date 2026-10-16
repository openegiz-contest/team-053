"""The simulator: wiring of the processes, scenario knobs, snapshot and totals.

See the package docstring (``sekis.sim``) for the public API.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from .. import capacity as cap
from .. import geometry as geometry_module
from .mining import Mining
from .params import Params
from .surface import Dewatering, Plant, UNBOUNDED, Water
from .timebase import Calendar, SECONDS_PER_DAY, SECONDS_PER_HOUR, parse_epoch
from .traffic import Haulage, P_MAINT, P_TO_PAD
from .vod import Vod

PERCENT = 100.0
SECONDS_PER_MINUTE = 60

SCENARIO_THING = "scenario"
ADVISOR_THING = "advisor"
#: Feature ids whose value is a string; every other feature is a float (spec 1.1).
STRING_FEATURES = frozenset(("state", "shift", "decline", "stope", "binding_link", "next_measure", "label",
                             "sim_time", "vod_state"))
#: Scenario features that are not knobs of the model.
_SCENARIO_META = ("revision", "label")


def load_registry(path: Optional[Path] = None) -> Dict[str, Any]:
    """Read ``model/registry.json`` (next to the ``sekis`` package by default)."""
    path = path or Path(__file__).resolve().parent.parent.parent / "model" / "registry.json"
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _short(thing_id: str) -> str:
    return str(thing_id).split(":", 1)[-1]


def _finite(value: float, limit: float = UNBOUNDED) -> float:
    return limit if math.isinf(value) or math.isnan(value) or value > limit else value


class Simulator:
    """Headless, deterministic simulator of the Sekisovskoye twin. See ``sekis.sim``."""

    def __init__(self, model: cap.Model, geometry: Any, registry: Optional[Mapping[str, Any]] = None,
                 seed: Optional[int] = None, epoch: Any = None):
        self.model = model
        self.geo = geometry
        self.p = Params(model)
        registry = registry if registry is not None else load_registry()
        self.namespace: str = registry["namespace"]
        #: thing name -> {"kind", "attributes", "features" (baseline values), "tier"}
        self.things: Dict[str, Dict[str, Any]] = {}
        tiers = {_short(t["thingId"]): t.get("_meta", {}).get("tier", "L") for t in registry["types"]}
        for thing in registry["things"]:
            kind = thing["attributes"]["kind"]
            self.things[_short(thing["thingId"])] = {
                "kind": kind, "attributes": thing["attributes"], "tier": tiers.get(kind, "L"),
                "features": {fid: body["properties"]["value"] for fid, body in thing.get("features", {}).items()}}
        self.names_by_kind: Dict[str, List[str]] = {}
        for name, thing in self.things.items():
            self.names_by_kind.setdefault(thing["kind"], []).append(name)

        #: Seed of every random stream (truck breakdowns and operational delays, one pair per truck).
        self.seed = int(self.p("sim.seed") if seed is None else seed)
        self.cal = Calendar(self.p, parse_epoch(self.p("sim.epoch") if epoch is None else epoch))
        self.step_s = self.cal.step_s
        #: Simulated seconds per real second in ``step()``; may be reassigned (SIM_SPEEDUP).
        self.speedup = float(self.p("sim.speedup"))
        self.steps_per_minute = SECONDS_PER_MINUTE // self.step_s
        if self.steps_per_minute * self.step_s != SECONDS_PER_MINUTE:
            raise ValueError("sim.step_s does not divide a minute")

        # clock
        self.tick = 0
        self.t = 0
        self._carry = 0.0
        self._i = self.cal.index(0)
        self._day_t0 = -self._i * self.step_s
        self.productive = self.cal.productive[self._i]
        self.block_end_t = self._day_t0 + self.cal.block_end_s[self._i]
        self.in_blast = self.cal.in_blast[self._i]
        self.blast_end_t = float("-inf")
        self.shift = self.cal.shift[self._i]
        self.blast_w = 0

        # scenario
        self.knobs: Dict[str, Any] = dict(self.things[SCENARIO_THING]["features"])
        self.cap_state = cap.State.from_knobs(self.knobs)
        cap.validate_state(model, self.cap_state)
        self.baseline = cap.evaluate(model)
        self.grade_gpt = float(self.cap_state.grade_gpt or self.p("plant.grade_base"))

        # totals
        self.ore_blasted_t = 0.0
        self.ore_loaded_t = 0.0
        self.ore_hoisted_t = 0.0
        self.ore_hoisted_today_t = 0.0
        self.ore_broken_start_t = 0.0
        self.air_demand_peak = 0.0
        #: Simulated second of the last restart of the rate windows (a scenario change).
        self.rates_since_t = 0
        self.last_blast: Tuple[str, ...] = ()

        # processes
        self.decline_of: Dict[str, str] = {}
        self.trucks_on_decline: Dict[str, int] = {}
        self.haul = Haulage(self)
        self.mining = Mining(self)
        self.dewater = Dewatering(self)
        self.water = Water(self)
        self.plant = Plant(self)
        self.dewater_spec = cap.dewatering(model, self.cap_state)
        #: Ventilation on demand (spec 3.5): the duty of the main fans and their energy.
        self.vod = Vod(self)
        self._vod_waiting_lhds: Tuple[str, ...] = ()
        self.fans_installed: Tuple[str, ...] = ()
        self.fans_running: Tuple[str, ...] = ()
        self.air_supply = 0.0
        self.air_demand = 0.0
        self.held_trucks: Tuple[str, ...] = ()
        self.held_lhds: Tuple[str, ...] = ()
        self._vent_key: Any = None
        self._flooded: Tuple[str, ...] = ()
        self._level_air: Any = None
        self.analytic = self.baseline
        self.dev_rate_m_per_s = 0.0

        self._configure(first=True)
        # The run opens on a working mine: the trucks are already spread along their cycles.
        self.haul.warm_start(float(self.t), float(self.cal.worked_s(self._i)[0]))
        self.vod.prime()

        # publishing support
        self._snapshot_tick = -1
        self._snapshot: Dict[str, Dict[str, Any]] = {}
        self._version = 0
        self._seen: Dict[str, Dict[str, Any]] = {}
        self._changed_at: Dict[str, int] = {}

    @classmethod
    def from_files(cls, seed: Optional[int] = None, epoch: Any = None, model_dir: Optional[Path] = None) -> "Simulator":
        """Simulator built from ``model/params.json``, ``registry.json`` and ``geometry.json``."""
        if model_dir is None:
            return cls(cap.load_model(), geometry_module.load(), load_registry(), seed=seed, epoch=epoch)
        model_dir = Path(model_dir)
        return cls(cap.load_model(model_dir / "params.json", model_dir / "registry.json"),
                   geometry_module.load(model_dir / "geometry.json"), load_registry(model_dir / "registry.json"),
                   seed=seed, epoch=epoch)

    # ---------------------------------------------------------------------------------------
    # time
    # ---------------------------------------------------------------------------------------

    def advance(self, sim_minutes: float) -> None:
        """Advance the simulation by simulated minutes (in whole steps; the rest is carried)."""
        self._carry += sim_minutes * SECONDS_PER_MINUTE / self.step_s
        steps = int(self._carry + 1e-9)
        self._carry -= steps
        tick = self._tick
        for _ in range(steps):
            tick()

    def step(self, real_seconds: float) -> None:
        """Advance by real seconds at the compression ``sim.speedup`` (60: one real second is one
        simulated minute)."""
        self.advance(real_seconds * self.speedup / SECONDS_PER_MINUTE)

    def run_days(self, days: float) -> None:
        """Advance by simulated days."""
        self.advance(days * SECONDS_PER_DAY / SECONDS_PER_MINUTE)

    @property
    def sim_days(self) -> float:
        return self.t / SECONDS_PER_DAY

    @property
    def sim_time(self) -> str:
        return self.cal.iso(self.t)

    def _tick(self) -> None:
        cal = self.cal
        self.tick += 1
        t = self.t = self.tick * self.step_s
        i = self._i + 1
        if i == cal.steps_per_day:
            i = 0
            self._day_t0 = t
            self._new_day()
        self._i = i
        productive = self.productive = cal.productive[i]
        if productive:
            self.block_end_t = self._day_t0 + cal.block_end_s[i]
        in_blast = cal.in_blast[i]
        if in_blast != self.in_blast:
            if not in_blast:
                self.blast_end_t = float(t)
            self.in_blast = in_blast
        if i in cal.fire_steps:
            self.blast_w += 1
            self.last_blast = tuple(self.mining.blast(t, self.blast_w))
        self.shift = cal.shift[i]
        self.haul.step(t)
        if self.tick % self.steps_per_minute == 0:
            self._minute(t, i)

    def _new_day(self) -> None:
        """Daily totals reset at the start of shift A (08:00)."""
        self.ore_hoisted_today_t = 0.0
        self.haul.reset_day()
        self.mining.reset_day()
        self.plant.reset_day()
        self.vod.reset_day()
        self._refresh_analytic()

    def _minute(self, t: int, i: int) -> None:
        cal = self.cal
        dt = float(SECONDS_PER_MINUTE)
        # The minute that just ended is productive if its middle was.
        productive = cal.productive[(i - self.steps_per_minute // 2) % cal.steps_per_day]
        self.mining.minute(t, dt, productive)
        pumped = self.dewater.minute(dt)
        flooded = self.dewater.flooded_levels()
        if flooded != self._flooded:
            self._flooded = flooded
            self.mining.set_flooded(flooded)
            self._refresh_analytic()
        self.plant.minute(t, dt, pumped, self.dewater.levelled_m3)
        self._ventilation_rule()
        self._vod_minute(t, dt)
        if productive and self.dev_rate_m_per_s > 0.0:
            for ramp in self.haul.ramps.values():       # decline development advances the face
                if ramp.bottom_elevation > ramp.design_bottom:
                    ramp.bottom_elevation = max(ramp.design_bottom, ramp.bottom_elevation - self.dev_rate_m_per_s * dt)

    def on_dump(self, tonnes: float, grade: float) -> None:
        """A truck tipped its load on the ROM pad."""
        self.ore_hoisted_t += tonnes
        self.ore_hoisted_today_t += tonnes
        self.plant.add_ore(tonnes, grade)

    # ---------------------------------------------------------------------------------------
    # scenario
    # ---------------------------------------------------------------------------------------

    def default_knobs(self) -> Dict[str, Any]:
        """The knob values of the baseline (the scenario thing of the registry)."""
        return dict(self.things[SCENARIO_THING]["features"])

    def apply_scenario(self, knobs: Mapping[str, Any]) -> List[str]:
        """Apply scenario knobs (spec 3.1). See ``sekis.sim`` for the contract."""
        merged = dict(self.knobs)
        for name, raw in knobs.items():
            if name not in merged:
                continue
            if isinstance(raw, Mapping):
                raw = raw["properties"]["value"] if "properties" in raw else raw["value"]
            if isinstance(merged[name], str):
                merged[name] = str(raw)
            else:
                value = float(raw)
                if math.isnan(value) or math.isinf(value):
                    raise ValueError(f"knob {name} is not a finite number")
                merged[name] = value
        state = cap.State.from_knobs(merged)
        cap.validate_state(self.model, state)
        changed = [name for name in merged if merged[name] != self.knobs[name]]
        if not changed:
            return []
        self.knobs = merged
        self.cap_state = state
        self._configure(first=False)
        self.haul.step(self.t)          # units waiting at the surface take their new state at once
        if any(name not in _SCENARIO_META for name in changed):
            self.restart_rates()
        self._snapshot_tick = -1
        return changed

    def mine_rate_tph(self, result: Optional[cap.Result] = None) -> float:
        """The analytic mine rate of a state as a mean over the day, t/h: the smallest of the
        haulage, ventilation, stopes and dewatering capacities spread over the working days (the
        simulator runs every day as a working day, spec 2.1)."""
        result = result or self.analytic
        ktpa = min(result.capacity_ktpa[link] for link in ("haulage", "ventilation", "stopes", "dewatering"))
        return ktpa * cap.KILO / (self.p("regime.working_days") * cap.HOURS_PER_DAY)

    def restart_rates(self) -> None:
        """Restart the rate and per-day windows so that they describe the new regime only (see
        ``Plant.restart_rates``). The water means are short and are not restarted."""
        self.plant.restart_rates(self.mine_rate_tph())
        self.rates_since_t = self.t

    def reset_scenario(self) -> List[str]:
        """Back to the baseline knobs; ``revision`` and ``label`` are kept."""
        defaults = {name: value for name, value in self.default_knobs().items() if name not in _SCENARIO_META}
        return self.apply_scenario(defaults)

    def _configure(self, first: bool) -> None:
        """Bring every process in line with ``self.cap_state``. Safe to call again."""
        model, state, p = self.model, self.cap_state, self.p
        now = self.t
        # haulage: which trucks are in service and which decline each one uses
        self.decline_of = {truck.name: cap.truck_decline(model, state, truck) for truck in model.trucks}
        for key, ramp in self.haul.ramps.items():
            ramp.closed = bool(getattr(state, f"{key}_closed"))
        self.haul.set_in_service([truck.name for truck in cap.active_trucks(model, state)], now)
        self.haul.rehome(float(now))
        # stopes, LHDs, rigs
        self.mining.configure(len(cap.producing_stopes(model, state)),
                              [lhd.name for lhd in cap.active_lhds(model, state)],
                              cap.active_rigs(model, state), now, first)
        # feed grade: a what-if on the ore itself, so ore already broken, loaded or stockpiled
        # follows the knob (the stopes are rescaled as decision 9.3 says)
        grade = float(state.grade_gpt or p("plant.grade_base"))
        if grade != self.grade_gpt:
            ratio = grade / self.grade_gpt
            self.plant.stock_grade *= ratio
            for truck in self.haul.trucks:
                truck.grade *= ratio
            self.grade_gpt = grade
        self.mining.rescale_grades(grade)
        # ventilation
        self.fans_installed = tuple(p("ladder.m_vent.fans")[state.m_vent])
        self.fans_running = cap.fans_running(model, state)
        self.air_supply = cap.air_supply_m3s(model, self.fans_running)
        self.vod.configure(bool(round(float(self.knobs.get("vod_enabled", 1.0)))), self.fans_running)
        # water, plant, tailings, development
        self.dewater_spec = cap.dewatering(model, state)
        self.plant.configure()
        self.dev_rate_m_per_s = (p("ladder.m_dev.advance_vm_per_year")[state.m_dev]
                                 / (p("regime.working_days") * p("regime.shifts") * p("regime.productive_h")
                                    * SECONDS_PER_HOUR))
        self.on_fleet_change()
        self._refresh_analytic()

    def on_fleet_change(self) -> None:
        """The units in service changed: the ventilation rule is evaluated again, and with it the
        counts that follow the units left working."""
        self._vent_key = None
        self._ventilation_rule()

    def _count_working_trucks(self) -> None:
        """Trucks working each decline and the smallest of them. A truck held for air waits at
        the surface, so it is not one of the ``n`` trucks on its decline (spec 2.3 item 1)."""
        counts: Dict[str, int] = {key: 0 for key in self.model.declines}
        smallest: Dict[str, float] = {}
        for truck in self.haul.trucks:
            if truck.in_service and not truck.retiring and not truck.held:
                key = self.decline_of[truck.name]
                counts[key] += 1
                smallest[key] = min(smallest.get(key, truck.payload_t), truck.payload_t)
        self.trucks_on_decline = counts
        self.mining.set_min_payloads(smallest)

    def _refresh_analytic(self) -> None:
        """The analytic picture for the live state: the same call the advisor makes."""
        live = self.cap_state.replace(flooded_levels=tuple(self._flooded),
                                      tailings_placed_t=self.plant.tailings_t)
        self.analytic = cap.evaluate(self.model, live)

    # ---------------------------------------------------------------------------------------
    # ventilation (spec 2.6)
    # ---------------------------------------------------------------------------------------

    def _ventilation_rule(self) -> None:
        """Hold units until the air demand fits the supply. The rule itself is
        ``capacity.hold_units``, the function behind the analytic ventilation capacity, so the
        twins and the advisor hold the same units."""
        model = self.model
        trucks = [t for t in self.haul.trucks if t.in_service and not t.retiring]
        lhds = [u for u in self.mining.lhds if u.in_service]
        key = (self.air_supply, tuple(t.name for t in trucks), tuple(u.name for u in lhds))
        if key == self._vent_key:
            return
        self._vent_key = key
        hold = cap.hold_units(model, trucks, lhds, self.air_supply)
        self.air_demand = cap.air_demand_m3s(model, hold.working_kw)
        self.held_trucks = hold.trucks
        self.held_lhds = hold.lhds
        held = set(self.held_trucks)
        for truck in self.haul.trucks:
            truck.held = truck.name in held
        self._count_working_trucks()
        self.mining.set_held_lhds(self.held_lhds + self._vod_waiting_lhds)
        if self.air_demand > self.air_demand_peak:
            self.air_demand_peak = self.air_demand

    def _vod_minute(self, t: int, dt: float) -> None:
        """Ventilation on demand (spec 3.5): set the fans for the units in work and admit units
        only while the delivered air covers them. An LHD that waits for the fans to ramp up idles
        its stope like an LHD held by the hold rule."""
        vod = self.vod
        vod.minute(float(t), dt, self.productive)
        if vod.waiting_lhds != self._vod_waiting_lhds:
            self._vod_waiting_lhds = vod.waiting_lhds
            self.mining.set_held_lhds(self.held_lhds + self._vod_waiting_lhds)

    def stand_minutes(self, mine_hours: float) -> float:
        """Hours of the mine clock as minutes of the real clock at the compression ``speedup``
        (the minutes a viewer of the Stand waits), rounded to 0.1 and kept between 0.1 and 999;
        0 stands for "nothing to wait for"."""
        if mine_hours <= 0.0 or self.speedup <= 0.0:
            return 0.0
        minutes = mine_hours * SECONDS_PER_HOUR / self.speedup / SECONDS_PER_MINUTE
        return round(min(UNBOUNDED, max(0.1, minutes)), 1)

    def mine_state(self) -> str:
        if self.air_supply < self.p("vent.q_base"):
            return "evacuation"                 # the fans cannot carry even the base demand
        if self.held_trucks or self.held_lhds:
            return "restricted_air"
        if self.in_blast:
            return "blast_window"
        return "production"

    # ---------------------------------------------------------------------------------------
    # snapshot
    # ---------------------------------------------------------------------------------------

    def snapshot(self, names: Optional[Iterable[str]] = None) -> Dict[str, Dict[str, Any]]:
        """Feature values of the twins: ``{thing_name: {feature_id: value}}``.

        Without ``names``: every thing of the registry except the advisor. The result is cached
        per simulation step; treat it as read-only.
        """
        self._level_air = None
        if names is not None:
            return {name: self._features(_short(name)) for name in names}
        if self._snapshot_tick != self.tick:
            self._snapshot = {name: self._features(name) for name in self.things if name != ADVISOR_THING}
            self._snapshot_tick = self.tick
        return self._snapshot

    def features(self, name: str) -> Dict[str, Any]:
        """Feature values of one thing (from the cached snapshot)."""
        return self.snapshot()[_short(name)]

    def _features(self, name: str) -> Dict[str, Any]:
        kind = self.things[name]["kind"]
        return getattr(self, f"_f_{kind}")(name)

    def _f_enterprise(self, name: str) -> Dict[str, Any]:
        plant = self.plant
        return {"sim_time": self.sim_time, "sim_day": round(self.sim_days, 4), "shift": self.shift,
                "ore_mined_tpd": round(plant.r_hoist_day.total(), 0),
                "ore_milled_tpd": round(plant.r_feed_day.total(), 0),
                "gold_poured_oz_day": round(plant.r_gold_day.total(), 1),
                "gold_poured_total_oz": round(plant.gold_oz, 1),
                "annual_rate_ktpa": round(_finite(self.analytic.achievable_ktpa, 1e9), 1),
                "binding_link": self.analytic.binding_link}

    def _f_mine(self, name: str) -> Dict[str, Any]:
        haul, mining = self.haul, self.mining
        available = sum(1 for t in haul.active if not t.held and t.phase != P_MAINT and not t.retiring)
        running_kw = haul.running_kw() + mining.running_lhd_kw(self.t, self.productive)
        margin = (self.air_supply - self.air_demand) / self.air_supply * PERCENT if self.air_supply > 0 else -PERCENT
        return {"state": self.mine_state(),
                "ore_hoisted_tph": round(self.plant.r_hoist_day.per_hour(), 1),
                "ore_hoisted_today_t": round(self.ore_hoisted_today_t, 1),
                "ore_hoisted_total_t": round(self.ore_hoisted_t, 1),
                "trucks_active": float(available), "diesel_kw_active": round(float(running_kw), 1),
                "air_supply_m3s": round(self.air_supply, 1), "air_demand_m3s": round(self.air_demand, 1),
                "air_margin_pct": round(margin, 1),
                "units_held_vent": float(len(self.held_trucks) + len(self.held_lhds)),
                "inflow_m3h": round(self.dewater_spec.inflow_m3h, 1),
                "pumped_m3h": round(self.water.r_mine.per_hour(), 1),
                "flood_volume_m3": round(self.dewater.flood, 1),
                **self.vod.mine_features(),
                "flood_eta_min": self.stand_minutes(self.dewater.hours_to_next_flooded_level())}

    def _air_by_level(self) -> Tuple[Dict[str, cap.LevelAir], Dict[str, float]]:
        """Air of the levels (``capacity.level_air``): the units working on each level now, the
        LHDs held for air at their stope's level, the air delivered and the requirement it is
        set against (the demand of the units in work)."""
        cached = self._level_air
        if cached is None:
            kw: Dict[str, float] = {}
            self.haul.kw_on_levels(kw)
            self.mining.kw_on_levels(kw, self.t, self.productive)
            held: Dict[str, float] = {}
            for lhd in self.mining.lhds:
                if lhd.held and lhd.in_service and lhd.stope is not None:
                    name = lhd.stope.level.name
                    held[name] = held.get(name, 0.0) + lhd.engine_kw
            air = cap.level_air(self.model, self.vod.delivered(), self.vod.demand, kw, self._flooded, held)
            cached = self._level_air = (air, kw)
        return cached

    def _f_level(self, name: str) -> Dict[str, Any]:
        level = self.mining.levels[name]
        air, kw = self._air_by_level()
        mine_air = air.get(name)
        attrs = self.things[name]["attributes"]
        inflow = 0.0
        if level.role != "planned":
            station = _short(attrs.get("link_drains_to", ""))
            sharing = [n for n in self.names_by_kind["level"]
                       if self.mining.levels[n].role != "planned"
                       and _short(self.things[n]["attributes"].get("link_drains_to", "")) == station]
            spec = self.dewater_spec
            total = spec.inflow_upper_m3h if station == "ps-p150" else spec.inflow_lower_m3h
            inflow = total / len(sharing) if sharing else 0.0
        active = sum(1 for st in self.mining.producing if st.level is level and not st.suspended())
        return {"state": "flooded" if level.flooded else level.role,
                "air_flow_m3s": round(mine_air.flow_m3s, 1) if mine_air else 0.0,
                "air_required_m3s": round(mine_air.required_m3s, 1) if mine_air else 0.0,
                "diesel_kw": round(kw.get(name, 0.0), 1), "water_inflow_m3h": round(inflow, 1),
                "active_stopes": float(active), "ore_today_t": round(level.ore_today, 1)}

    def _f_stope(self, name: str) -> Dict[str, Any]:
        return self.mining.stope_features(self.mining.by_name[name], self.t)

    def _f_decline(self, name: str) -> Dict[str, Any]:
        ramp = self.haul.ramps[name.split("decline-", 1)[-1]]
        cycles = ramp.cycles
        mean_cycle = sum(cycles) / len(cycles) / SECONDS_PER_MINUTE if cycles else 0.0
        return {"state": "closed" if ramp.closed else "open",
                "bottom_elevation": round(ramp.bottom_elevation, 2),
                "trucks_on_ramp": float(self.haul.on_ramp(ramp)),
                "trucks_waiting_in_bays": float(self.haul.waiting_in_bays(ramp)),
                "loaded_trips_today": float(ramp.loaded_trips_today),
                "ore_today_t": round(ramp.ore_today, 1), "avg_cycle_min": round(mean_cycle, 1)}

    def _fan_flow(self, fan: str) -> float:
        """Air a fan delivers now: its ventilation-on-demand flow, 0 when it does not run."""
        return self.vod.flow.get(fan, 0.0) if fan in self.fans_running else 0.0

    def _airway(self, name: str) -> Dict[str, Any]:
        attrs = self.things[name]["attributes"]
        fan = _short(attrs["link_fan"]) if "link_fan" in attrs else None
        in_service = True
        if fan is not None:                     # an airway with its own fan carries that fan's flow
            flow = self._fan_flow(fan)
            in_service = fan in self.fans_installed
        elif attrs.get("direction") == "exhaust":   # all return air leaves through the exhaust raises
            flow = self.vod.delivered()
        else:                                   # a raise alongside a decline: its share of the decline air
            key = name.rsplit("-", 1)[-1]
            flow = 0.0
            for fan_name in self.fans_running:
                airways = self.things[fan_name]["attributes"].get("link_airway", [])
                airways = airways if isinstance(airways, list) else [airways]
                if f"decline-{key}" in [_short(a) for a in airways]:
                    share = self.p("vent.split_decline_raise_tu1_share")
                    flow += self._fan_flow(fan_name) * (share if key == self.model.declines[0] else 1.0 - share)
        section = float(attrs["section_m2"])
        return {"state": "in_service" if in_service else "planned", "air_flow_m3s": round(flow, 1),
                "air_velocity_ms": round(flow / section, 2) if section > 0 else 0.0}

    _f_shaft = _airway
    _f_raise = _airway

    def _f_main_fan(self, name: str) -> Dict[str, Any]:
        """A main fan: its flow and setpoint under ventilation on demand, the pressure on the fixed
        system curve (square of the flow) and the shaft power (cube of the flow), spec 3.5."""
        if name in self.fans_running:
            state = "running"
            flow, setpoint, pressure, power = self.vod.fan(name)
        else:
            state = "failed" if name in self.fans_installed else "planned"
            flow = setpoint = pressure = power = 0.0
        return {"state": state, "air_flow_m3s": round(flow, 1), "duty_setpoint_m3s": round(setpoint, 1),
                "pressure": round(pressure, 1), "power_kw": round(power, 1)}

    def _f_pump_station(self, name: str) -> Dict[str, Any]:
        return self.dewater.station_features(name)

    def _f_settling_pond(self, name: str) -> Dict[str, Any]:
        ponds = self.names_by_kind["settling_pond"]
        return self.water.pond_features()[ponds.index(name)]

    def _f_monitoring_point(self, name: str) -> Dict[str, Any]:
        if "permit_m3h" in self.things[name]["attributes"]:     # the outfall
            permit = self.water.permit()
            tss = self.water.pond_features()[-1]["tss_out_mgl"] if permit.discharge_m3h > 0 else 0.0
            return {"state": self.water.outfall_state, "discharge_m3h": round(permit.discharge_m3h, 1),
                    "intake_m3h": 0.0, "tss_mgl": round(tss, 3),
                    "permit_use_pct": round(permit.permit_use_pct, 1),
                    "minutes_to_permit": self.stand_minutes(self.water.hours_to_permit())}
        return {"state": "normal", "discharge_m3h": 0.0,
                "intake_m3h": round(self.water.r_intake.per_hour(), 1), "tss_mgl": 0.0, "permit_use_pct": 0.0,
                "minutes_to_permit": 0.0}

    def _f_haul_truck(self, name: str) -> Dict[str, Any]:
        truck = self.haul.by_name[name]
        x, y, z, chainage, speed = self.haul.locate(truck, self.t)
        on_decline = chainage > 0.0 or truck.state in ("descending", "hauling_up", "waiting_bay")
        decline = truck.ramp.key if truck.in_service and truck.ramp is not None else "none"
        if decline != "none" and truck.phase == P_TO_PAD and truck.load_t <= 0.0:
            decline = self.decline_of[name]     # empty on the way to the pad: the decline of its next trip
        return {"state": truck.state, "payload": round(truck.load_t, 1),
                "grade": round(truck.grade if truck.load_t > 0 else 0.0, 3), "speed": round(speed, 1),
                "decline": decline,
                "chainage_m": round(chainage, 1) if on_decline else 0.0, "elevation": round(y, 1),
                "pos_x": round(x, 1), "pos_y": round(y, 1), "pos_z": round(z, 1),
                "trips_today": float(truck.trips_today), "tonnes_today": round(truck.tonnes_today, 1)}

    def _f_lhd(self, name: str) -> Dict[str, Any]:
        lhd = next(unit for unit in self.mining.lhds if unit.name == name)
        return self.mining.lhd_features(lhd, self.t, self.productive)

    def _f_drill_rig(self, name: str) -> Dict[str, Any]:
        rig = next(unit for unit in self.mining.rigs if unit.name == name)
        return self.mining.rig_features(rig, self.productive)

    def _f_rom_stockpile(self, name: str) -> Dict[str, Any]:
        return self.plant.stockpile_features()

    def _f_plant(self, name: str) -> Dict[str, Any]:
        return self.plant.plant_features()

    def _f_plant_line(self, name: str) -> Dict[str, Any]:
        return self.plant.line_features(self.plant.lines[self.model.plant_lines.index(name)])

    def _storage(self) -> cap.Tailings:
        return self.plant.tailings(self.analytic.achievable_ktpa)

    def _f_tailings_facility(self, name: str) -> Dict[str, Any]:
        storage = self._storage()
        return {"state": storage.state, "stored_t": round(storage.stored_t, 0),
                "free_capacity_t": round(storage.free_t, 0),
                "inflow_tpd": round(self.plant.r_feed_day.total(), 0),
                "years_left": round(_finite(storage.years_left), 2),
                "reclaim_m3h": round(self.water.r_reclaim.per_hour(), 1)}

    def _f_tailings_dam(self, name: str) -> Dict[str, Any]:
        storage = self._storage()
        dam = next(d for d in storage.dams if d.name == name)
        return {"state": dam.state, "stored_t": round(dam.stored_t, 0), "fill_pct": round(dam.fill_pct, 2),
                "free_capacity_t": round(dam.free_t, 0),
                "inflow_tph": round(self.plant.feed_tph if storage.active_dam == name else 0.0, 1)}

    def _f_water_system(self, name: str) -> Dict[str, Any]:
        return self.water.water_features()

    def _f_scenario_control(self, name: str) -> Dict[str, Any]:
        return {fid: (str(value) if fid in STRING_FEATURES else float(value)) for fid, value in self.knobs.items()}

    def _f_advisor(self, name: str) -> Dict[str, Any]:
        raise KeyError("the advisor twin is published by the advisor service")

    # ---------------------------------------------------------------------------------------
    # publishing support
    # ---------------------------------------------------------------------------------------

    def changed_since(self, token: Optional[int] = None) -> Tuple[int, Dict[str, Dict[str, Any]]]:
        """Things whose features changed after ``token`` was issued.

        Returns ``(new_token, {thing_name: features})``. ``token=None`` (or 0) returns every thing.
        Each call compares the current snapshot with the one of the previous call, so tokens from
        several consumers stay valid.
        """
        snap = self.snapshot()
        self._version += 1
        version = self._version
        seen, changed_at = self._seen, self._changed_at
        for name, features in snap.items():
            if seen.get(name) != features:
                seen[name] = features
                changed_at[name] = version
        since = token or 0
        return version, {name: snap[name] for name in snap if changed_at[name] > since}

    def tier(self, name: str) -> str:
        """Publishing tier of a thing now: ``S``, ``M``, ``L`` or ``on_change`` (spec 1.2).

        A unit in state ``planned`` or ``parked`` publishes in tier L.
        """
        name = _short(name)
        tier = self.things[name]["tier"]
        if tier in ("S", "M") and self.features(name).get("state") in ("planned", "parked"):
            return "L"
        return tier

    def validate_snapshot(self) -> List[str]:
        """Differences between the snapshot and the registry (feature ids, value types). Empty
        when the snapshot can be published as it is."""
        problems = []
        snap = self.snapshot()
        for name, thing in self.things.items():
            if name == ADVISOR_THING:
                continue
            features = snap.get(name)
            if features is None:
                problems.append(f"{name}: missing")
                continue
            if list(features) != list(thing["features"]):
                odd = sorted(set(features) ^ set(thing["features"]))
                problems.append(f"{name}: feature ids differ or are out of order {odd}")
            for fid, value in features.items():
                want = str if fid in STRING_FEATURES else float
                if type(value) is not want:
                    problems.append(f"{name}.{fid}: {type(value).__name__}, expected {want.__name__}")
                elif want is float and not math.isfinite(value):
                    problems.append(f"{name}.{fid}: not finite")
        return problems

    # ---------------------------------------------------------------------------------------
    # totals and calibration
    # ---------------------------------------------------------------------------------------

    def totals(self) -> Dict[str, float]:
        """Totals since the epoch and present stocks; see ``sekis.sim`` for the keys."""
        water, dewater, plant, haul = self.water, self.dewater, self.plant, self.haul
        storage = self._storage()
        start_stored = sum(dam.stored_start_t for name, dam in self.model.dams.items())
        return {
            "sim_days": self.sim_days,
            "ore_blasted_t": self.ore_blasted_t,
            "ore_broken_start_t": self.ore_broken_start_t,
            "ore_broken_t": self.mining.broken_ore_t(),
            "ore_loaded_t": self.ore_loaded_t,
            "ore_on_trucks_t": haul.ore_on_trucks(),
            "ore_hoisted_t": self.ore_hoisted_t,
            "stockpile_start_t": plant.stock_start_t,
            "stockpile_t": plant.stock_t,
            "ore_milled_t": plant.milled_t,
            "gold_oz": plant.gold_oz,
            "tailings_placed_t": plant.tailings_t,
            "tailings_stored_start_t": start_stored,
            "tailings_stored_t": storage.stored_t,
            "tailings_free_t": storage.free_t,
            "water_inflow_m3": dewater.inflow_total,
            "water_pumped_m3": dewater.pumped_total,
            "water_in_sumps_m3": dewater.v_main + dewater.v_lower,
            "flood_volume_m3": dewater.flood,
            "water_site_use_m3": water.total["site"],
            "water_plant_supply_m3": water.total["plant"],
            "water_reclaim_m3": water.total["reclaim"],
            "water_extra_intake_m3": water.total["intake"],
            "water_deficit_m3": water.total["deficit"],
            "water_discharge_m3": water.total["discharge"],
            "water_in_ponds_m3": water.stored[0] + water.stored[1],
            "pond_reserve_h": water.reserve_hours(),
            "air_supply_m3s": self.air_supply,
            "air_demand_m3s": self.air_demand,
            "air_demand_peak_m3s": self.air_demand_peak,
            "air_delivered_m3s": self.vod.delivered(),
            "fan_energy_kwh": self.vod.energy_total,
            "fan_energy_fixed_kwh": self.vod.fixed_total,
            "vod_min_margin_m3s": self.vod.min_margin_m3s if self.vod.minutes else 0.0,
            "truck_trips": float(haul.trips),
            "truck_trips_aborted": float(haul.aborted_trips),
            "truck_maintenance_h": haul.maintenance_s / SECONDS_PER_HOUR,
            "blasts": float(self.mining.blasts),
            "truck_cycle_mean_min": haul.cycle_time_s / haul.trips / SECONDS_PER_MINUTE if haul.trips else 0.0,
            "bay_wait_min_per_trip": haul.bay_wait_s / haul.trips / SECONDS_PER_MINUTE if haul.trips else 0.0,
            "up_hold_min_per_trip": haul.up_wait_s / haul.trips / SECONDS_PER_MINUTE if haul.trips else 0.0,
            "load_wait_min_per_trip": haul.queue_wait_s / haul.trips / SECONDS_PER_MINUTE if haul.trips else 0.0,
            "max_bay_wait_min": haul.longest_bay_wait_s(self.t) / SECONDS_PER_MINUTE,
            "traffic_conflicts": float(haul.conflicts),
            "min_stockpile_t": plant.min_stock_seen,
            "min_ponds_m3": water.min_stored,
            "min_sump_m3": dewater.min_sump,
        }

    def annualised(self) -> Dict[str, float]:
        """Run totals scaled to a year: mine totals x working days, plant and water totals x
        plant days, over the simulated days (spec 2.1)."""
        days = self.sim_days
        if days <= 0:
            return {}
        mine = self.p("regime.working_days") / days
        plant = self.p("regime.plant_days") / days
        totals = self.totals()
        return {
            "ore_hoisted_t": totals["ore_hoisted_t"] * mine,
            "ore_blasted_t": totals["ore_blasted_t"] * mine,
            "ore_milled_t": totals["ore_milled_t"] * plant,
            "gold_oz": totals["gold_oz"] * plant,
            "tailings_placed_t": totals["tailings_placed_t"] * plant,
            "water_inflow_m3": totals["water_inflow_m3"] * plant,
            "water_pumped_m3": totals["water_pumped_m3"] * plant,
            "water_site_use_m3": totals["water_site_use_m3"] * plant,
            "water_plant_supply_m3": totals["water_plant_supply_m3"] * plant,
            "water_reclaim_m3": totals["water_reclaim_m3"] * plant,
            "water_extra_intake_m3": totals["water_extra_intake_m3"] * plant,
            "water_discharge_m3": totals["water_discharge_m3"] * plant,
        }

    def calibration_checks(self) -> Tuple[cap.CalibrationCheck, ...]:
        """The simulator rows of the calibration table (spec 2.9): C3, C8 and C11 for the run so
        far. Meaningful for a baseline run of ``calib.run_days``."""
        p = self.p
        totals, year = self.totals(), self.annualised()
        rows = []

        def relative(check_id: str, case: str, quantity: str, unit: str, reported: float, value: float,
                     tolerance: float) -> None:
            deviation = (value / reported - 1.0) * PERCENT if reported else 0.0
            rows.append(cap.CalibrationCheck(check_id, case, quantity, unit, reported, value, deviation, "%",
                                             f"+-{tolerance:g} %", abs(deviation) <= tolerance))

        case = f"{self.sim_days:.0f} simulated days"
        relative("C3", case, "ore hoisted, annualised", "t/yr", p("calib.c3.reported_t"),
                 year.get("ore_hoisted_t", 0.0), p("calib.c3.tol_pct"))
        relative("C8", case, "plant feed, annualised", "t/yr", p("calib.c8.reported_t"),
                 year.get("ore_milled_t", 0.0), p("calib.c8.tol_pct"))
        relative("C11", case, "hoisted = stockpile change + milled", "t", totals["ore_hoisted_t"],
                 totals["stockpile_t"] - totals["stockpile_start_t"] + totals["ore_milled_t"],
                 p("calib.c11.tol_pct"))
        relative("C11", case, "milled = tailings added", "t", totals["ore_milled_t"],
                 totals["tailings_stored_t"] - totals["tailings_stored_start_t"], p("calib.c11.tol_pct"))
        return tuple(rows)
