"""Analytic capacity library of the Sekisovskoye digital twin (spec sections 2.3-2.7 and 3.4).

One parameter file and this one function library serve both the simulator and the
Expansion Advisor, so that the live numbers and the analytic capacities agree by
construction. Everything here is a pure function of a ``Model`` (the two JSON files)
and a ``State`` (measure knobs, disturbances and a few live values). The only I/O is
``load_model()``. Standard library only.

Typical use::

    from sekis import capacity as cap

    model = cap.load_model()                       # reads model/params.json, model/registry.json
    state = cap.State(m_haul=1, grade_gpt=1.76)    # or cap.State.from_knobs(scenario_features)
    res = cap.evaluate(model, state)

    res.capacity_ktpa["haulage"]     # kt/yr, unrounded; math.inf means "not limiting"
    res.capacity_rounded["haulage"]  # kt/yr rounded to 1; None means "not limiting"
    res.binding_link                 # smallest rounded capacity, ties broken in LINKS order
    res.achievable_ktpa              # smallest unrounded capacity
    res.air.demand_m3s, res.water.deficit_m3h, res.tailings.years_left, res.gold.oz_per_year
    cap.next_measure(model, state, res.binding_link)   # (knob, state with one more stage) or None

Conventions

* Capacities are in kt of ore per year. The eight links and their tie-break order are ``LINKS``.
* Things are named without the namespace, as in the string features of the twins:
  ``"truck-07"``, ``"lvl-000"``, ``"fan-vs2"``. A leading ``"kz.sekis:"`` is accepted and dropped.
* Declines are named by their parameter key: ``"tu1"``, ``"tu2"``.
* No model number lives in this file. Every value comes from ``params.json`` (``Model.p``) or
  from the attributes of the things in ``registry.json``. The upper-case constants below are
  unit conversions only.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

__all__ = [
    "LINKS", "MEASURE_KNOBS", "KNOBS",
    "Model", "load_model", "State", "Result", "evaluate", "next_measure", "knob_max", "binding_link",
    "round_kt", "validate_state",
    "Truck", "Lhd", "Fan", "Level", "Stope", "Dam",
    "active_trucks", "active_lhds", "active_rigs", "producing_stopes", "truck_decline", "fleet_power_kw",
    "ramp_length_km", "haul_cycle", "haulage", "HaulCycle", "Haulage",
    "stopes", "Stopes", "development_capacity_ktpa", "centroid_after",
    "fans_running", "air_supply_m3s", "air_demand_m3s", "air", "Air", "level_air", "LevelAir", "fan_power_kw",
    "dewatering", "Dewatering", "pump_power_kw", "pond_treatment", "PondTreatment",
    "plant", "Plant", "PlantLine", "water_capacity_ktpa", "water_balance", "WaterBalance",
    "tailings", "Tailings", "DamFill", "recovery_pct", "gold_oz", "Gold", "stockpile_days_left",
    "calibration_checks", "CalibrationCheck",
]

# --- unit conversions (not model parameters) ---------------------------------------------------
HOURS_PER_DAY = 24.0
MINUTES_PER_HOUR = 60.0
SECONDS_PER_HOUR = 3600.0
KILO = 1000.0            # t per kt, m per km, W per kW, m3 per thousand m3
PERCENT = 100.0
GRAMS_PER_TONNE = 1.0e6  # also mg/l x m3 = g

# --- links and knobs ---------------------------------------------------------------------------
#: The eight ranked links, in the tie-break order of spec 3.4 step 2.
LINKS: Tuple[str, ...] = (
    "haulage", "ventilation", "stopes", "development", "dewatering", "plant", "water", "tailings",
)

#: Link -> scenario knob that adds one stage of capacity (spec 3.4 step 3).
#: Dewatering has no knob: its measure is "restore the pumps".
MEASURE_KNOBS: Dict[str, str] = {
    "haulage": "m_haul",
    "ventilation": "m_vent",
    "stopes": "m_stopes",
    "development": "m_dev",
    "plant": "m_plant",
    "water": "m_water",
    "tailings": "m_tailings",
}

#: Measure knob -> id of a ladder parameter (a list with one entry per stage, stage 0 first).
_KNOB_LADDER: Dict[str, str] = {
    "m_haul": "ladder.m_haul.trucks",
    "m_vent": "ladder.m_vent.fans",
    "m_stopes": "ladder.m_stopes.producing",
    "m_dev": "ladder.m_dev.advance_vm_per_year",
    "m_plant": "ladder.m_plant.capacity_ktpa",
    "m_water": "ladder.m_water.reclaim_m3_per_t",
    "m_tailings": "ladder.m_tailings.dams",
}

#: The seven measure knobs.
KNOBS: Tuple[str, ...] = tuple(_KNOB_LADDER)

# State tokens of the twins that this library reads or reports (spec 1.2).
_ROLE_PRODUCTION = "production"
_ROLE_DEVELOPMENT = "development"
_ROLE_PLANNED = "planned"


def _short(thing_id: str) -> str:
    """Thing name without the namespace: ``kz.sekis:truck-01`` -> ``truck-01``."""
    return str(thing_id).split(":", 1)[-1]


def _number(name: str) -> int:
    """Trailing number of a thing name: ``truck-07`` -> 7."""
    return int(name.rsplit("-", 1)[-1])


def _feature(thing: Mapping[str, Any], feature_id: str) -> Any:
    return thing["features"][feature_id]["properties"]["value"]


def round_kt(value: float) -> Optional[int]:
    """Round a capacity to 1 kt/yr, halves up (spec 3.4 step 1). ``math.inf`` gives ``None``."""
    if math.isinf(value):
        return None
    return int(math.floor(value + 0.5))


# --- model: parameters and unit attributes -----------------------------------------------------

@dataclass(frozen=True)
class Truck:
    """A haul truck of the registry. ``home_decline`` is ``"tu1"`` or ``"tu2"``."""
    name: str
    number: int
    payload_t: float
    engine_kw: float
    home_decline: str


@dataclass(frozen=True)
class Lhd:
    """A load-haul-dump machine of the registry."""
    name: str
    number: int
    engine_kw: float


@dataclass(frozen=True)
class Fan:
    """A main fan of the registry."""
    name: str
    duty_m3s: float
    pressure_pa: float


@dataclass(frozen=True)
class Level:
    """A mine level of the registry. ``role`` is the registry attribute (production, planned, ...)."""
    name: str
    elevation_m: float
    role: str


@dataclass(frozen=True)
class Stope:
    """A stope of the registry. ``grade_gpt`` is the grade at the baseline feed grade."""
    name: str
    number: int
    level: str
    elevation_m: float
    grade_gpt: float


@dataclass(frozen=True)
class Dam:
    """A tailings dam of the registry with its state at the simulation epoch."""
    name: str
    capacity_t: float
    stored_start_t: float


class Model:
    """Parameters and unit attributes, read once and never changed.

    ``params`` is the content of ``params.json`` (id -> ``{value, unit, source}``),
    ``registry`` the content of ``registry.json``. Build it with ``load_model()``.

    Attributes (all tuples are sorted by unit number unless stated):
        trucks, lhds   every truck and LHD of the registry
        rigs           names of the drill rigs
        fans           name -> Fan
        levels         every level, top down
        stopes         stopes that can produce, in the activation order of spec 2.5
        dams           name -> Dam
        pond_volumes_m3  volume of each settling pond, in flow order
        plant_lines    names of the plant lines, by line number
        declines       decline keys ("tu1", "tu2")
    """

    def __init__(self, params: Mapping[str, Any], registry: Mapping[str, Any]):
        self._values: Dict[str, Any] = {pid: entry["value"] for pid, entry in params.items()}
        by_kind: Dict[str, list] = {}
        for thing in registry["things"]:
            by_kind.setdefault(thing["attributes"]["kind"], []).append(thing)

        def decline_key(thing_id: str) -> str:
            return _short(thing_id).split("decline-", 1)[-1]

        self.declines: Tuple[str, ...] = tuple(sorted(decline_key(t["thingId"]) for t in by_kind["decline"]))
        self.trucks: Tuple[Truck, ...] = tuple(sorted(
            (Truck(_short(t["thingId"]), _number(_short(t["thingId"])), float(t["attributes"]["payload_t"]),
                   float(t["attributes"]["engine_kw"]), decline_key(t["attributes"]["link_home_decline"]))
             for t in by_kind["haul_truck"]), key=lambda u: u.number))
        self.lhds: Tuple[Lhd, ...] = tuple(sorted(
            (Lhd(_short(t["thingId"]), _number(_short(t["thingId"])), float(t["attributes"]["engine_kw"]))
             for t in by_kind["lhd"]), key=lambda u: u.number))
        self.rigs: Tuple[str, ...] = tuple(sorted((_short(t["thingId"]) for t in by_kind["drill_rig"]), key=_number))
        self.fans: Dict[str, Fan] = {
            _short(t["thingId"]): Fan(_short(t["thingId"]), float(t["attributes"]["duty_m3s"]),
                                      float(t["attributes"]["pressure_pa"]))
            for t in by_kind["main_fan"]}
        self.levels: Tuple[Level, ...] = tuple(sorted(
            (Level(_short(t["thingId"]), float(t["attributes"]["elevation_m"]), t["attributes"]["role"])
             for t in by_kind["level"]), key=lambda lv: -lv.elevation_m))
        level_by_name = {lv.name: lv for lv in self.levels}
        all_stopes = []
        for t in by_kind["stope"]:
            name = _short(t["thingId"])
            level = level_by_name[_short(t["attributes"]["link_level"])]
            all_stopes.append(Stope(name, _number(name), level.name, level.elevation_m,
                                    float(t["attributes"]["grade_gpt"])))
        # Activation order (spec 2.5): the "-1" stopes of the production levels top down, then the
        # "-2" stopes, then "-3"; after them the stopes of the level under development.
        first = sorted((s for s in all_stopes if level_by_name[s.level].role == _ROLE_PRODUCTION),
                       key=lambda s: (s.number, -s.elevation_m))
        later = sorted((s for s in all_stopes if level_by_name[s.level].role == _ROLE_DEVELOPMENT),
                       key=lambda s: (-s.elevation_m, s.number))
        self.stopes: Tuple[Stope, ...] = tuple(first + later)
        self.dams: Dict[str, Dam] = {
            _short(t["thingId"]): Dam(_short(t["thingId"]), float(t["attributes"]["capacity_t"]),
                                      float(_feature(t, "stored_t")))
            for t in by_kind["tailings_dam"]}
        self.pond_volumes_m3: Tuple[float, ...] = tuple(float(t["attributes"]["volume_m3"])
                                                        for t in by_kind["settling_pond"])
        self.plant_lines: Tuple[str, ...] = tuple(sorted((_short(t["thingId"]) for t in by_kind["plant_line"]),
                                                         key=_number))
        self._check()

    def p(self, param_id: str) -> Any:
        """Value of a parameter of ``params.json``; ``KeyError`` names a missing id."""
        try:
            return self._values[param_id]
        except KeyError:
            raise KeyError(f"parameter {param_id!r} is not in params.json") from None

    # derived time bases ------------------------------------------------------------------------
    @property
    def mine_hours_per_year(self) -> float:
        """Shift hours of the mine per year, ``H`` of spec 2.3 (working days x shifts x shift length)."""
        return self.p("regime.working_days") * self.p("regime.shifts") * self.p("regime.shift_h")

    @property
    def hours_per_year(self) -> float:
        """Hours per year of the continuous processes (plant, water, ponds)."""
        return self.p("regime.plant_days") * HOURS_PER_DAY

    def _check(self) -> None:
        """Fail early when the ladders and the registry do not fit together."""
        def need(condition: bool, message: str) -> None:
            if not condition:
                raise ValueError(f"inconsistent model files: {message}")

        need(len(self.p("ladder.m_haul.trucks")) > 0 and max(self.p("ladder.m_haul.trucks")) <= len(self.trucks),
             "ladder.m_haul.trucks asks for more trucks than the registry has")
        n_stages = len(self.p("ladder.m_stopes.producing"))
        need(len(self.p("ladder.m_stopes.lhds")) == n_stages and len(self.p("ladder.m_stopes.rigs")) == n_stages,
             "the three ladder.m_stopes lists differ in length")
        need(max(self.p("ladder.m_stopes.producing")) <= len(self.stopes),
             "ladder.m_stopes.producing asks for more stopes than can produce")
        need(max(self.p("ladder.m_stopes.lhds")) <= len(self.lhds), "ladder.m_stopes.lhds exceeds the registry")
        need(max(self.p("ladder.m_stopes.rigs")) <= len(self.rigs), "ladder.m_stopes.rigs exceeds the registry")
        for stage in self.p("ladder.m_vent.fans"):
            need(all(name in self.fans for name in stage), "ladder.m_vent.fans names an unknown fan")
        need(len(self.p("ladder.m_plant.lines")) == len(self.p("ladder.m_plant.capacity_ktpa")),
             "the two ladder.m_plant lists differ in length")
        need(max(self.p("ladder.m_plant.lines")) <= len(self.plant_lines), "ladder.m_plant.lines exceeds the registry")
        need(len(self.p("ladder.m_water.extra_intake_m3h")) == len(self.p("ladder.m_water.reclaim_m3_per_t")),
             "the two ladder.m_water lists differ in length")
        for stage in self.p("ladder.m_tailings.dams"):
            need(all(name in self.dams for name in stage), "ladder.m_tailings.dams names an unknown dam")
        for key in self.declines:
            self.p(f"decline.{key}.portal_m")
            self.p(f"decline.{key}.surface_km")


def load_model(params_path: Optional[Path] = None, registry_path: Optional[Path] = None) -> Model:
    """Read ``params.json`` and ``registry.json`` and return the ``Model``.

    Defaults to ``team/model/`` next to the ``sekis`` package. This is the only I/O of the module.
    """
    model_dir = Path(__file__).resolve().parent.parent / "model"
    with open(params_path or model_dir / "params.json", encoding="utf-8") as handle:
        params = json.load(handle)
    with open(registry_path or model_dir / "registry.json", encoding="utf-8") as handle:
        registry = json.load(handle)
    return Model(params, registry)


def knob_max(model: Model, knob: str) -> int:
    """Highest stage of a measure knob (``"m_haul"`` -> 3 with the ladders of spec 3.1)."""
    return len(model.p(_KNOB_LADDER[knob])) - 1


# --- state -------------------------------------------------------------------------------------

@dataclass(frozen=True)
class State:
    """What the capacities are computed for. Immutable; change it with ``replace()``.

    Measure knobs (spec 3.1), each a stage number starting at 0:
        m_plant, m_haul, m_stopes, m_vent, m_dev, m_water, m_tailings

    Disturbances (spec 3.1):
        tu1_closed, tu2_closed   decline closed; its trucks use the other decline
        fan_vs2_off              fan-vs2 failed
        pumps_failed_p150        failed pumps at ps-p150
        inflow_factor            multiplier of the mean mine inflow
        grade_gpt                mean feed grade, g/t; None = plant.grade_base
        line_down                number of the plant line stopped for repair; 0 = none

    Live values (defaults describe the simulation epoch):
        centroid_m          elevation of the production centroid, m; None = stope.centroid_baseline_m
        flooded_levels      names of the flooded levels, e.g. ("lvl-m050", "lvl-000")
        tailings_placed_t   tailings placed since the epoch, t

    Active units; None derives them from the knobs (trucks 01..N, LHDs 01..N, the first N stopes of
    the activation order). Pass a unit that is in service even when it is momentarily held,
    in maintenance or on a shift break: availability is already inside the haulage formula.
        active_trucks       names of the trucks in service
        active_lhds         names of the LHDs in service
        active_rigs         number of drill rigs in service
        producing_set       names of the stopes in the producing set
    """

    m_plant: int = 0
    m_haul: int = 0
    m_stopes: int = 0
    m_vent: int = 0
    m_dev: int = 0
    m_water: int = 0
    m_tailings: int = 0
    tu1_closed: bool = False
    tu2_closed: bool = False
    fan_vs2_off: bool = False
    pumps_failed_p150: int = 0
    inflow_factor: float = 1.0
    grade_gpt: Optional[float] = None
    line_down: int = 0
    centroid_m: Optional[float] = None
    flooded_levels: Tuple[str, ...] = ()
    tailings_placed_t: float = 0.0
    active_trucks: Optional[Tuple[str, ...]] = None
    active_lhds: Optional[Tuple[str, ...]] = None
    active_rigs: Optional[int] = None
    producing_set: Optional[Tuple[str, ...]] = None

    def replace(self, **changes: Any) -> "State":
        """Copy of the state with some fields changed."""
        return replace(self, **changes)

    @classmethod
    def from_knobs(cls, knobs: Mapping[str, Any], **live: Any) -> "State":
        """Build a state from the features of ``kz.sekis:scenario``.

        ``knobs`` maps a knob name to its value, either plain (``{"m_haul": 1.0}``) or in the Ditto
        shape (``{"m_haul": {"properties": {"value": 1.0}}}``). Floats are converted to the field
        types. Names that are not fields of ``State`` (``target_ktpa``, ``revision``, ``label``)
        are ignored. ``live`` sets further fields, e.g. ``centroid_m=40.0``.
        """
        types = {f.name: f.type for f in fields(cls)}
        values: Dict[str, Any] = {}
        for name, raw in knobs.items():
            if name not in types:
                continue
            if isinstance(raw, Mapping):
                raw = raw["properties"]["value"]
            kind = types[name]
            if kind == "int":
                values[name] = int(round(float(raw)))
            elif kind == "bool":
                values[name] = bool(round(float(raw)))
            elif kind in ("float", "Optional[float]"):
                values[name] = None if raw is None else float(raw)
            else:
                values[name] = raw
        values.update(live)
        return cls(**values)


def _names(names: Iterable[str]) -> Tuple[str, ...]:
    return tuple(_short(name) for name in names)


def validate_state(model: Model, state: State) -> None:
    """Raise ``ValueError`` for a state the model has no answer for.

    Checked: every measure knob is a stage of its ladder; at least one decline is open (the Stand
    rejects closing both); failed pumps do not exceed the pumps of ps-p150; ``line_down`` is 0 or a
    line in service at this plant stage; factors and tonnages are not negative; unit, stope and
    level names exist in the registry.
    """
    for knob in KNOBS:
        stage = getattr(state, knob)
        if not isinstance(stage, int) or isinstance(stage, bool) or not 0 <= stage <= knob_max(model, knob):
            raise ValueError(f"{knob}={stage!r} is not an integer stage 0..{knob_max(model, knob)}")
    if all(getattr(state, f"{key}_closed") for key in model.declines):
        raise ValueError("every decline is closed; at least one must stay open")
    if not 0 <= state.pumps_failed_p150 <= model.p("water.ps_p150.pumps"):
        raise ValueError(f"pumps_failed_p150={state.pumps_failed_p150!r} is outside "
                         f"0..{model.p('water.ps_p150.pumps')}")
    lines_in_service = model.p("ladder.m_plant.lines")[state.m_plant]
    if not 0 <= state.line_down <= lines_in_service:
        raise ValueError(f"line_down={state.line_down!r} is outside 0..{lines_in_service}")
    if state.inflow_factor < 0:
        raise ValueError("inflow_factor is negative")
    if state.grade_gpt is not None and state.grade_gpt <= 0:
        raise ValueError("grade_gpt must be positive")
    if state.tailings_placed_t < 0:
        raise ValueError("tailings_placed_t is negative")
    if state.active_rigs is not None and state.active_rigs < 0:
        raise ValueError("active_rigs is negative")
    known = {
        "active_trucks": {u.name for u in model.trucks},
        "active_lhds": {u.name for u in model.lhds},
        "producing_set": {s.name for s in model.stopes},
        "flooded_levels": {lv.name for lv in model.levels},
    }
    for field_name, names in known.items():
        given = getattr(state, field_name)
        for name in _names(given or ()):
            if name not in names:
                raise ValueError(f"{field_name}: unknown name {name!r}")


# --- fleet -------------------------------------------------------------------------------------

def active_trucks(model: Model, state: State) -> Tuple[Truck, ...]:
    """Trucks in service: ``state.active_trucks``, else trucks 01..N of the ``m_haul`` stage."""
    if state.active_trucks is not None:
        wanted = set(_names(state.active_trucks))
        return tuple(u for u in model.trucks if u.name in wanted)
    return model.trucks[:model.p("ladder.m_haul.trucks")[state.m_haul]]


def active_lhds(model: Model, state: State) -> Tuple[Lhd, ...]:
    """LHDs in service: ``state.active_lhds``, else LHDs 01..N of the ``m_stopes`` stage."""
    if state.active_lhds is not None:
        wanted = set(_names(state.active_lhds))
        return tuple(u for u in model.lhds if u.name in wanted)
    return model.lhds[:model.p("ladder.m_stopes.lhds")[state.m_stopes]]


def active_rigs(model: Model, state: State) -> int:
    """Number of drill rigs in service: ``state.active_rigs``, else the ``m_stopes`` stage."""
    if state.active_rigs is not None:
        return state.active_rigs
    return model.p("ladder.m_stopes.rigs")[state.m_stopes]


def producing_stopes(model: Model, state: State) -> Tuple[Stope, ...]:
    """The producing set: ``state.producing_set``, else the first N stopes of the activation order."""
    if state.producing_set is not None:
        wanted = set(_names(state.producing_set))
        return tuple(s for s in model.stopes if s.name in wanted)
    return model.stopes[:model.p("ladder.m_stopes.producing")[state.m_stopes]]


def truck_decline(model: Model, state: State, truck: Truck) -> str:
    """Decline a truck uses: its home decline, or the open one while its home is closed (spec 2.4)."""
    if not getattr(state, f"{truck.home_decline}_closed"):
        return truck.home_decline
    for key in model.declines:
        if not getattr(state, f"{key}_closed"):
            return key
    raise ValueError("every decline is closed; at least one must stay open")


def fleet_power_kw(model: Model, state: State) -> float:
    """``P_fleet`` of spec 2.3: engine kW of all active trucks and LHDs."""
    return (sum(u.engine_kw for u in active_trucks(model, state))
            + sum(u.engine_kw for u in active_lhds(model, state)))


# --- haulage -----------------------------------------------------------------------------------

@dataclass(frozen=True)
class HaulCycle:
    """One truck's analytic cycle (spec 2.3 item 1). Times in minutes, lengths in km."""
    truck: str
    decline: str
    payload_t: float
    trucks_on_decline: int
    ramp_km: float
    surface_km: float
    load_min: float
    dump_min: float
    manoeuvre_min: float
    ramp_up_min: float
    ramp_down_min: float
    surface_loaded_min: float
    surface_empty_min: float
    bay_min: float
    cycle_min: float
    capacity_ktpa: float


@dataclass(frozen=True)
class Haulage:
    """Haulage link: one ``HaulCycle`` per active truck and their sum."""
    cycles: Tuple[HaulCycle, ...]
    trucks_by_decline: Dict[str, int]
    centroid_m: float
    capacity_ktpa: float


def ramp_length_km(model: Model, decline: str, elevation_m: float) -> float:
    """Ramp length from the portal of ``decline`` down to ``elevation_m``.

    ``L = (portal - z) / sin(slope) x length_factor`` (spec 2.3). Not capped at the decline bottom:
    the formula treats the centroid as reachable. Zero at or above the portal.
    """
    drop_m = max(0.0, model.p(f"decline.{decline}.portal_m") - elevation_m)
    slope = math.radians(model.p("decline.slope_deg"))
    return drop_m / math.sin(slope) * model.p("decline.length_factor") / KILO


def haul_cycle(model: Model, truck: Truck, decline: str, centroid_m: float, trucks_on_decline: int) -> HaulCycle:
    """Cycle time ``T`` and annual capacity of one truck (spec 2.3 item 1).

    ``T = load + dump + manoeuvre + ramp up loaded + ramp down empty + surface loaded
    + surface empty + K_BAY x (n - 1)`` and
    ``capacity = payload x 60 / T x H x (productive_h / shift_h) x availability x K_HAUL``.
    """
    p = model.p
    ramp_km = ramp_length_km(model, decline, centroid_m)
    surface_km = p(f"decline.{decline}.surface_km")
    ramp_up = MINUTES_PER_HOUR * ramp_km / p("truck.speed_up_loaded_kmh")
    ramp_down = MINUTES_PER_HOUR * ramp_km / p("truck.speed_down_empty_kmh")
    flat_loaded = MINUTES_PER_HOUR * surface_km / p("truck.speed_flat_loaded_kmh")
    flat_empty = MINUTES_PER_HOUR * surface_km / p("truck.speed_flat_empty_kmh")
    bay = p("haul.K_BAY") * max(0, trucks_on_decline - 1)
    cycle = (p("truck.load_min") + p("truck.dump_min") + p("truck.manoeuvre_min")
             + ramp_up + ramp_down + flat_loaded + flat_empty + bay)
    tonnes_per_shift_hour = truck.payload_t * MINUTES_PER_HOUR / cycle
    capacity = (tonnes_per_shift_hour * model.mine_hours_per_year
                * (p("regime.productive_h") / p("regime.shift_h"))
                * p("truck.availability") * p("haul.K_HAUL") / KILO)
    return HaulCycle(
        truck=truck.name, decline=decline, payload_t=truck.payload_t, trucks_on_decline=trucks_on_decline,
        ramp_km=ramp_km, surface_km=surface_km, load_min=p("truck.load_min"), dump_min=p("truck.dump_min"),
        manoeuvre_min=p("truck.manoeuvre_min"), ramp_up_min=ramp_up, ramp_down_min=ramp_down,
        surface_loaded_min=flat_loaded, surface_empty_min=flat_empty, bay_min=bay, cycle_min=cycle,
        capacity_ktpa=capacity)


def _centroid(model: Model, state: State) -> float:
    return model.p("stope.centroid_baseline_m") if state.centroid_m is None else state.centroid_m


def haulage(model: Model, state: State) -> Haulage:
    """Haulage capacity ``C_haul``: the sum over the active trucks on the declines they use."""
    trucks = active_trucks(model, state)
    decline_of = {u.name: truck_decline(model, state, u) for u in trucks}
    count: Dict[str, int] = {key: 0 for key in model.declines}
    for key in decline_of.values():
        count[key] += 1
    centroid = _centroid(model, state)
    cycles = tuple(haul_cycle(model, u, decline_of[u.name], centroid, count[decline_of[u.name]]) for u in trucks)
    return Haulage(cycles=cycles, trucks_by_decline=count, centroid_m=centroid,
                   capacity_ktpa=sum(c.capacity_ktpa for c in cycles))


# --- stopes and development --------------------------------------------------------------------

@dataclass(frozen=True)
class Stopes:
    """Stopes link (spec 2.3 item 2, 2.5).

    ``n_producing`` is the producing set limited by the rigs (``stope.stopes_per_rig`` each) and by
    one LHD per stope. ``mean_grade_gpt`` is the mean grade of the producing set at the state's
    feed grade; gold is computed from ``state.grade_gpt``, this value is for comparison.
    """
    producing: Tuple[str, ...]
    n_producing: int
    lhds: int
    rigs: int
    per_stope_ktpa: float
    mean_grade_gpt: float
    capacity_ktpa: float


def _grade(model: Model, state: State) -> float:
    return model.p("plant.grade_base") if state.grade_gpt is None else state.grade_gpt


def stopes(model: Model, state: State) -> Stopes:
    """Stoping capacity ``C_stopes = N_producing x capacity_design / producing_base``."""
    p = model.p
    producing = producing_stopes(model, state)
    lhds = len(active_lhds(model, state))
    rigs = active_rigs(model, state)
    n_producing = min(len(producing), p("stope.stopes_per_rig") * rigs, lhds)
    per_stope = p("stope.capacity_design_ktpa") / p("stope.producing_base")
    scale = _grade(model, state) / p("plant.grade_base")
    mean_grade = scale * sum(s.grade_gpt for s in producing) / len(producing) if producing else 0.0
    return Stopes(producing=tuple(s.name for s in producing), n_producing=n_producing, lhds=lhds, rigs=rigs,
                  per_stope_ktpa=per_stope, mean_grade_gpt=mean_grade, capacity_ktpa=n_producing * per_stope)


def development_capacity_ktpa(model: Model, m_dev: int) -> float:
    """``C_dev = advance x t_per_vm``: the ore that a year of decline advance opens (spec 2.3 item 2)."""
    return model.p("ladder.m_dev.advance_vm_per_year")[m_dev] * model.p("dev.t_per_vm") / KILO


def centroid_after(model: Model, centroid_m: float, ore_t: float) -> float:
    """Production centroid after mining ``ore_t``: it drops by ``ore / dev.t_per_vm`` metres (spec 3.4 step 5)."""
    return centroid_m - ore_t / model.p("dev.t_per_vm")


# --- ventilation -------------------------------------------------------------------------------

@dataclass(frozen=True)
class Air:
    """Ventilation (spec 2.3 item 3, 2.6). Flows in m3/s, power in kW.

    ``margin_pct = (supply - demand) / supply x 100``; negative when the fleet needs more air than
    the fans supply. ``capacity_ktpa`` is ``C_vent``; ``math.inf`` with no diesel unit active.
    """
    fans_running: Tuple[str, ...]
    supply_m3s: float
    demand_m3s: float
    fleet_kw: float
    allowed_kw: float
    margin_pct: float
    capacity_ktpa: float


def fans_running(model: Model, state: State) -> Tuple[str, ...]:
    """Fans in service at the ``m_vent`` stage, without ``fan-vs2`` while it is failed."""
    failed = {"fan-vs2"} if state.fan_vs2_off else set()
    return tuple(name for name in model.p("ladder.m_vent.fans")[state.m_vent] if name not in failed)


def air_supply_m3s(model: Model, fans: Iterable[str]) -> float:
    """Supply: the sum of ``duty_m3s`` of the given running fans (spec 2.6)."""
    return sum(model.fans[_short(name)].duty_m3s for name in fans)


def air_demand_m3s(model: Model, diesel_kw: float) -> float:
    """Demand: ``vent.q_base + vent.q_diesel x diesel kW`` (spec 2.6)."""
    return model.p("vent.q_base") + model.p("vent.q_diesel") * diesel_kw


def air(model: Model, state: State, haul_capacity_ktpa: Optional[float] = None) -> Air:
    """Air supply, demand and ``C_vent = P_allowed x C_haul / P_fleet``.

    ``P_allowed = (supply - q_base) / q_diesel`` is the diesel power the supply permits; the
    capacity is the ore that power moves at the fleet's specific power. ``haul_capacity_ktpa``
    defaults to ``haulage(model, state).capacity_ktpa``.
    """
    running = fans_running(model, state)
    supply = air_supply_m3s(model, running)
    fleet_kw = fleet_power_kw(model, state)
    demand = air_demand_m3s(model, fleet_kw)
    allowed_kw = max(0.0, (supply - model.p("vent.q_base")) / model.p("vent.q_diesel"))
    if haul_capacity_ktpa is None:
        haul_capacity_ktpa = haulage(model, state).capacity_ktpa
    capacity = allowed_kw * haul_capacity_ktpa / fleet_kw if fleet_kw > 0 else math.inf
    margin = (supply - demand) / supply * PERCENT if supply > 0 else -math.inf
    return Air(fans_running=running, supply_m3s=supply, demand_m3s=demand, fleet_kw=fleet_kw,
               allowed_kw=allowed_kw, margin_pct=margin, capacity_ktpa=capacity)


@dataclass(frozen=True)
class LevelAir:
    """Air of one level (spec 2.6), m3/s."""
    required_m3s: float
    flow_m3s: float


def level_air(model: Model, supply_m3s: float, kw_by_level: Optional[Mapping[str, float]] = None) -> Dict[str, LevelAir]:
    """Split the supply over the levels that are not planned (spec 2.6).

    ``required = q_base / number of such levels + q_diesel x kW of the units on the level``;
    ``flow = supply x share of the total requirement``. ``kw_by_level`` maps a level name to the
    diesel kW on it; levels left out carry none.
    """
    kw = {_short(name): value for name, value in (kw_by_level or {}).items()}
    open_levels = [lv.name for lv in model.levels if lv.role != _ROLE_PLANNED]
    base = model.p("vent.q_base") / len(open_levels)
    required = {name: base + model.p("vent.q_diesel") * kw.get(name, 0.0) for name in open_levels}
    total = sum(required.values())
    return {name: LevelAir(required_m3s=need, flow_m3s=supply_m3s * need / total)
            for name, need in required.items()}


def fan_power_kw(model: Model, air_flow_m3s: float, pressure_pa: float) -> float:
    """Fan shaft power: ``flow x pressure / efficiency`` (spec 2.6)."""
    return air_flow_m3s * pressure_pa / model.p("vent.fan_efficiency") / KILO


# --- dewatering and ponds ----------------------------------------------------------------------

@dataclass(frozen=True)
class Dewatering:
    """Dewatering link (spec 2.3 item 4, 2.7). Flows in m3/h.

    ``margin`` is the working pump capacity of ps-p150 over the whole inflow scaled by
    ``24 / water.pumping_norm_h``; ``margin_lower`` the same for ps-m050 and its share of the
    inflow. ``pumped_m3h`` and ``flood_rate_m3h`` are the steady state of the cascade with every
    pump that is allowed to run: what reaches the ponds and what stays underground.
    ``limiting`` is true while a level is flooded; only then ``capacity_ktpa`` is finite: the
    stoping capacity of the producing stopes on levels that are not flooded.
    """
    inflow_m3h: float
    inflow_upper_m3h: float
    inflow_lower_m3h: float
    capacity_main_m3h: float
    capacity_lower_m3h: float
    margin: float
    margin_lower: float
    pumped_m3h: float
    flood_rate_m3h: float
    flooded_levels: Tuple[str, ...]
    limiting: bool
    capacity_ktpa: float


def dewatering(model: Model, state: State) -> Dewatering:
    """Pumping margin, steady-state cascade flows and ``C_dewatering``."""
    p = model.p
    inflow = p("water.inflow_m3h") * state.inflow_factor
    upper = inflow * p("water.upper_share")
    lower = inflow - upper
    # ps-p150: the standby pump only replaces a failed one, so at most `pumps_working` run.
    main_pumps = max(0, min(p("water.ps_p150.pumps_working"), p("water.ps_p150.pumps") - state.pumps_failed_p150))
    capacity_main = main_pumps * p("water.ps_p150.pump_m3h")
    # ps-m050: the standby pump joins at a high sump level, so every pump can run.
    capacity_lower_norm = p("water.ps_m050.pumps_working") * p("water.ps_m050.pump_m3h")
    capacity_lower = p("water.ps_m050.pumps") * p("water.ps_m050.pump_m3h")
    norm = HOURS_PER_DAY / p("water.pumping_norm_h")
    margin = capacity_main / (inflow * norm) if inflow > 0 else math.inf
    margin_lower = capacity_lower_norm / (lower * norm) if lower > 0 else math.inf
    # Water leaves the mine only through ps-p150; the lower share must first pass ps-m050.
    pumped = min(capacity_main, upper + min(capacity_lower, lower))
    flooded = _names(state.flooded_levels)
    limiting = bool(flooded)
    capacity = math.inf
    if limiting:
        st = stopes(model, state)
        dry = [s for s in producing_stopes(model, state) if s.level not in flooded]
        capacity = min(len(dry), st.n_producing) * st.per_stope_ktpa
    return Dewatering(
        inflow_m3h=inflow, inflow_upper_m3h=upper, inflow_lower_m3h=lower, capacity_main_m3h=capacity_main,
        capacity_lower_m3h=capacity_lower, margin=margin, margin_lower=margin_lower, pumped_m3h=pumped,
        flood_rate_m3h=inflow - pumped, flooded_levels=flooded, limiting=limiting, capacity_ktpa=capacity)


def pump_power_kw(model: Model, flow_m3h: float, head_m: float) -> float:
    """Pump power: ``density x g x Q x head x head factor / efficiency`` (spec 2.7)."""
    p = model.p
    return (p("phys.water_density_kg_m3") * p("phys.gravity_m_s2") * flow_m3h / SECONDS_PER_HOUR
            * head_m * p("water.pump_head_factor") / p("water.pump_efficiency") / KILO)


@dataclass(frozen=True)
class PondTreatment:
    """Settling ponds at a given flow (spec 2.7)."""
    flow_m3h: float
    retention_h: Tuple[float, ...]
    total_retention_h: float
    tss_out_mgl: float
    sludge_t_year: float


def pond_treatment(model: Model, flow_m3h: float) -> PondTreatment:
    """Retention per pond, suspended solids after the ponds and sludge per year (spec 2.7).

    ``tss_out = tss_in x (1 - efficiency x min(1, total retention / settling_h))`` and
    ``sludge = flow x hours per year x tss_in x efficiency``.
    """
    p = model.p
    retention = tuple(volume / flow_m3h if flow_m3h > 0 else math.inf for volume in model.pond_volumes_m3)
    total = sum(retention)
    tss_out = p("pond.tss_in_mgl") * (1 - p("pond.efficiency") * min(1.0, total / p("pond.settling_h")))
    sludge = flow_m3h * model.hours_per_year * p("pond.tss_in_mgl") * p("pond.efficiency") / GRAMS_PER_TONNE
    return PondTreatment(flow_m3h=flow_m3h, retention_h=retention, total_retention_h=total,
                         tss_out_mgl=tss_out, sludge_t_year=sludge)


# --- plant -------------------------------------------------------------------------------------

@dataclass(frozen=True)
class PlantLine:
    """A plant line at a plant stage. ``state`` is ``running``, ``off`` (stopped for repair) or
    ``planned`` (not built at this stage). ``rated_tph`` is the rate while it runs; with
    ``plant.availability`` it gives ``capacity_ktpa`` over a year."""
    name: str
    number: int
    state: str
    capacity_ktpa: float
    rated_tph: float


@dataclass(frozen=True)
class Plant:
    """Plant link (spec 2.3 item 5): the lines and the sum of the running ones."""
    lines: Tuple[PlantLine, ...]
    capacity_ktpa: float


def _line_capacities(model: Model, m_plant: int) -> Tuple[float, ...]:
    """Annual capacity of each built line. A stage that adds lines gives its gain to the new
    lines in equal parts; a stage that adds none raises every existing line equally."""
    totals = model.p("ladder.m_plant.capacity_ktpa")
    counts = model.p("ladder.m_plant.lines")
    per_line = [totals[0] / counts[0]] * counts[0]
    for stage in range(1, m_plant + 1):
        gain = totals[stage] - totals[stage - 1]
        new_lines = counts[stage] - counts[stage - 1]
        if new_lines > 0:
            per_line += [gain / new_lines] * new_lines
        else:
            per_line = [capacity + gain / len(per_line) for capacity in per_line]
    return tuple(per_line)


def plant(model: Model, m_plant: int, line_down: int = 0) -> Plant:
    """Lines and capacity ``C_plant`` at a plant stage, less the line stopped for repair."""
    built = _line_capacities(model, m_plant)
    lines = []
    for index, name in enumerate(model.plant_lines):
        number = index + 1
        if index >= len(built):
            lines.append(PlantLine(name=name, number=number, state="planned", capacity_ktpa=0.0, rated_tph=0.0))
            continue
        rated = built[index] * KILO / model.hours_per_year / model.p("plant.availability")
        if number == line_down:
            lines.append(PlantLine(name=name, number=number, state="off", capacity_ktpa=0.0, rated_tph=rated))
        else:
            lines.append(PlantLine(name=name, number=number, state="running", capacity_ktpa=built[index],
                                   rated_tph=rated))
    return Plant(lines=tuple(lines), capacity_ktpa=sum(line.capacity_ktpa for line in lines))


# --- process water -----------------------------------------------------------------------------

@dataclass(frozen=True)
class WaterBalance:
    """Water balance at given ore and feed rates (spec 2.7). Flows in m3/h.

    ``deficit_m3h`` is the demand left uncovered after reclaim and the extra intake;
    ``discharge_m3h`` the surplus sent to the Volchevka. ``feed_limit_tph`` is the plant feed the
    supply can carry at this ore rate (``math.inf`` if reclaim covers the plant).
    ``state`` is ``balanced``, ``deficit`` or ``discharge_over_permit``;
    ``permit_state`` is ``normal``, ``warning`` or ``exceeded``.
    """
    mine_water_m3h: float
    site_use_m3h: float
    plant_supply_m3h: float
    demand_m3h: float
    reclaim_m3h: float
    extra_intake_m3h: float
    supply_m3h: float
    deficit_m3h: float
    discharge_m3h: float
    permit_use_pct: float
    feed_limit_tph: float
    state: str
    permit_state: str


def water_capacity_ktpa(model: Model, m_water: int) -> float:
    """``C_water = (mine water + extra intake) / (site + plant - reclaim)`` per tonne (spec 2.3 item 6).

    Mine water is the constant ``water.mine_water_kth_m3yr`` of the water balance; the extra
    intake runs all year.
    """
    p = model.p
    supply_kth_m3 = (p("water.mine_water_kth_m3yr")
                     + model.hours_per_year / KILO * p("ladder.m_water.extra_intake_m3h")[m_water])
    net_m3_per_t = (p("water.site_m3_per_t") + p("water.plant_m3_per_t")
                    - p("ladder.m_water.reclaim_m3_per_t")[m_water])
    return supply_kth_m3 / net_m3_per_t if net_m3_per_t > 0 else math.inf


def water_balance(model: Model, ore_hoisted_tph: float, feed_tph: float, mine_water_m3h: float,
                  m_water: int = 0) -> WaterBalance:
    """Supply against demand (spec 2.7).

    Supply = mine water reaching the surface + reclaim (per tonne of feed) + extra intake (only as
    much as is missing, up to its limit). Demand = site use per tonne hoisted + plant supply per
    tonne of feed. Rates are averages in t/h over the same period as the flows.
    """
    p = model.p
    site_use = p("water.site_m3_per_t") * ore_hoisted_tph
    plant_supply = p("water.plant_m3_per_t") * feed_tph
    demand = site_use + plant_supply
    reclaim_per_t = p("ladder.m_water.reclaim_m3_per_t")[m_water]
    intake_limit = p("ladder.m_water.extra_intake_m3h")[m_water]
    reclaim = reclaim_per_t * feed_tph
    short = demand - mine_water_m3h - reclaim
    intake = min(max(short, 0.0), intake_limit)
    deficit = max(0.0, short - intake)
    discharge = max(0.0, -short)
    permit_use = discharge / p("water.permit_m3h") * PERCENT
    net_plant = p("water.plant_m3_per_t") - reclaim_per_t
    feed_limit = max(0.0, mine_water_m3h + intake_limit - site_use) / net_plant if net_plant > 0 else math.inf
    if permit_use > PERCENT:
        permit_state = "exceeded"
    elif permit_use > p("water.permit_warning_pct"):
        permit_state = "warning"
    else:
        permit_state = "normal"
    if deficit > 0:
        state = "deficit"
    elif permit_state == "exceeded":
        state = "discharge_over_permit"
    else:
        state = "balanced"
    return WaterBalance(
        mine_water_m3h=mine_water_m3h, site_use_m3h=site_use, plant_supply_m3h=plant_supply, demand_m3h=demand,
        reclaim_m3h=reclaim, extra_intake_m3h=intake, supply_m3h=mine_water_m3h + reclaim + intake,
        deficit_m3h=deficit, discharge_m3h=discharge, permit_use_pct=permit_use, feed_limit_tph=feed_limit,
        state=state, permit_state=permit_state)


# --- tailings ----------------------------------------------------------------------------------

@dataclass(frozen=True)
class DamFill:
    """One dam after ``placed_t`` of tailings. ``state`` is ``full``, ``active``, ``standby`` or
    ``planned`` (not built at this stage)."""
    name: str
    state: str
    stored_t: float
    free_t: float
    fill_pct: float


@dataclass(frozen=True)
class Tailings:
    """Tailings link (spec 2.3 item 7, 2.7).

    ``capacity_ktpa`` is the rate that keeps ``tsf.min_years`` of storage: free capacity over that
    many years. ``years_left`` is the free capacity over ``rate_ktpa``. ``state`` is ``ok``,
    ``short_horizon`` (fewer years left than ``tsf.min_years``) or ``full``. ``overflow_t`` is the
    part of ``placed_t`` that no built dam could take.
    """
    dams: Tuple[DamFill, ...]
    active_dam: Optional[str]
    free_t: float
    stored_t: float
    overflow_t: float
    rate_ktpa: float
    years_left: float
    state: str
    capacity_ktpa: float


def tailings(model: Model, m_tailings: int = 0, placed_t: float = 0.0, rate_ktpa: float = 0.0) -> Tailings:
    """Fill the built dams in their order with ``placed_t`` and rank the storage that is left."""
    stages = model.p("ladder.m_tailings.dams")
    built = stages[m_tailings]
    remaining = placed_t
    dams = []
    active = None
    for name in built:
        dam = model.dams[name]
        added = min(dam.capacity_t - dam.stored_start_t, remaining)
        remaining -= added
        stored = dam.stored_start_t + added
        free = dam.capacity_t - stored
        if free <= 0:
            token = "full"
        elif active is None:
            token, active = "active", name
        else:
            token = "standby"
        dams.append(DamFill(name=name, state=token, stored_t=stored, free_t=free,
                            fill_pct=stored / dam.capacity_t * PERCENT))
    for name in stages[-1]:
        if name not in built:
            dams.append(DamFill(name=name, state="planned", stored_t=0.0, free_t=0.0, fill_pct=0.0))
    free_t = sum(d.free_t for d in dams)
    years_left = free_t / (rate_ktpa * KILO) if rate_ktpa > 0 else math.inf
    if free_t <= 0:
        state = "full"
    elif years_left < model.p("tsf.min_years"):
        state = "short_horizon"
    else:
        state = "ok"
    return Tailings(dams=tuple(dams), active_dam=active, free_t=free_t, stored_t=sum(d.stored_t for d in dams),
                    overflow_t=remaining, rate_ktpa=rate_ktpa, years_left=years_left, state=state,
                    capacity_ktpa=free_t / KILO / model.p("tsf.min_years"))


# --- gold and stockpile ------------------------------------------------------------------------

@dataclass(frozen=True)
class Gold:
    """Gold at a throughput and feed grade (spec 2.3)."""
    milled_ktpa: float
    grade_gpt: float
    recovery_pct: float
    oz_per_year: float


def recovery_pct(model: Model, grade_gpt: float) -> float:
    """Recovery ``R(g) = intercept + slope x g`` percent, clamped to its limits (spec 2.3)."""
    p = model.p
    raw = p("plant.recovery.intercept_pct") + p("plant.recovery.slope_pct_per_gpt") * grade_gpt
    return min(p("plant.recovery.max_pct"), max(p("plant.recovery.min_pct"), raw))


def gold_oz(model: Model, milled_t: float, grade_gpt: float) -> float:
    """Gold poured: ``milled_t x grade x R(grade) / g per troy ounce`` (spec 2.3)."""
    return milled_t * grade_gpt * recovery_pct(model, grade_gpt) / PERCENT / model.p("gold.g_per_oz")


def stockpile_days_left(model: Model, stock_t: float, mine_ktpa: float, plant_ktpa: float) -> float:
    """Days until the ROM stockpile is drawn down while the plant mills more than the mine hoists.

    The mine total is spread over ``regime.working_days``, the plant total over
    ``regime.plant_days`` (spec 2.1). ``math.inf`` when the stockpile does not fall.
    """
    draw_t_per_day = (plant_ktpa * KILO / model.p("regime.plant_days")
                      - mine_ktpa * KILO / model.p("regime.working_days"))
    return stock_t / draw_t_per_day if draw_t_per_day > 0 else math.inf


# --- the eight links together ------------------------------------------------------------------

@dataclass(frozen=True)
class Result:
    """Everything ``evaluate()`` computes for one state.

    capacity_ktpa      link -> capacity in kt/yr, unrounded, for the eight ``LINKS``; dewatering
                       is ``math.inf`` unless a level is flooded
    capacity_rounded   link -> capacity rounded to 1 kt/yr; ``None`` for a link that does not limit
    binding_link       link with the smallest rounded capacity; ties go to the earlier link of ``LINKS``
    achievable_ktpa    smallest unrounded capacity: the sustainable throughput of the chain
    haulage, air, stopes, dewatering, plant, tailings   detail of the link
    dev_advance_vm_per_year   decline advance behind the development capacity
    water              balance at the throughput the other seven links allow, with the mine water
                       the pumps deliver in steady state; a deficit here means water binds
    gold               gold per year at ``achievable_ktpa`` and the state's feed grade
    """
    state: State
    capacity_ktpa: Dict[str, float]
    capacity_rounded: Dict[str, Optional[int]]
    binding_link: str
    achievable_ktpa: float
    haulage: Haulage
    air: Air
    stopes: Stopes
    dev_advance_vm_per_year: float
    dewatering: Dewatering
    plant: Plant
    water: WaterBalance
    tailings: Tailings
    gold: Gold

    def to_dict(self) -> Dict[str, Any]:
        """Nested plain dict for JSON; ``math.inf`` becomes ``None``."""
        def clean(value: Any) -> Any:
            if isinstance(value, float) and math.isinf(value):
                return None
            if isinstance(value, dict):
                return {key: clean(item) for key, item in value.items()}
            if isinstance(value, (list, tuple)):
                return [clean(item) for item in value]
            return value
        return clean(asdict(self))


def binding_link(capacity_ktpa: Mapping[str, float]) -> str:
    """Link with the smallest capacity after rounding to 1 kt/yr; ties in ``LINKS`` order (spec 3.4)."""
    best = None
    best_value = math.inf
    for link in LINKS:
        rounded = round_kt(capacity_ktpa[link])
        value = math.inf if rounded is None else rounded
        if best is None or value < best_value:
            best, best_value = link, value
    return best


def evaluate(model: Model, state: Optional[State] = None) -> Result:
    """Compute the eight link capacities and what follows from them for ``state``.

    ``state`` defaults to the baseline (all knobs 0, no disturbance). Raises ``ValueError`` for a
    state rejected by ``validate_state``.
    """
    state = State() if state is None else state
    validate_state(model, state)
    haul = haulage(model, state)
    vent = air(model, state, haul.capacity_ktpa)
    stoping = stopes(model, state)
    pumping = dewatering(model, state)
    mill = plant(model, state.m_plant, state.line_down)
    storage = tailings(model, state.m_tailings, state.tailings_placed_t)
    capacity = {
        "haulage": haul.capacity_ktpa,
        "ventilation": vent.capacity_ktpa,
        "stopes": stoping.capacity_ktpa,
        "development": development_capacity_ktpa(model, state.m_dev),
        "dewatering": pumping.capacity_ktpa,
        "plant": mill.capacity_ktpa,
        "water": water_capacity_ktpa(model, state.m_water),
        "tailings": storage.capacity_ktpa,
    }
    achievable = min(capacity.values())
    without_water = min(value for link, value in capacity.items() if link != "water")
    rate_tph = without_water * KILO / model.hours_per_year
    balance = water_balance(model, rate_tph, rate_tph, pumping.pumped_m3h, state.m_water)
    storage = tailings(model, state.m_tailings, state.tailings_placed_t, achievable)
    grade = _grade(model, state)
    gold = Gold(milled_ktpa=achievable, grade_gpt=grade, recovery_pct=recovery_pct(model, grade),
                oz_per_year=gold_oz(model, achievable * KILO, grade))
    return Result(
        state=state, capacity_ktpa=capacity,
        capacity_rounded={link: round_kt(value) for link, value in capacity.items()},
        binding_link=binding_link(capacity), achievable_ktpa=achievable, haulage=haul, air=vent,
        stopes=stoping, dev_advance_vm_per_year=model.p("ladder.m_dev.advance_vm_per_year")[state.m_dev],
        dewatering=pumping, plant=mill, water=balance, tailings=storage, gold=gold)


def next_measure(model: Model, state: State, link: str) -> Optional[Tuple[str, State]]:
    """One more stage on the knob of ``link`` (spec 3.4 step 3).

    Returns ``(knob, new_state)``, or ``None`` when the link has no knob (dewatering: restore the
    pumps) or no stage left.
    """
    knob = MEASURE_KNOBS.get(link)
    if knob is None or getattr(state, knob) >= knob_max(model, knob):
        return None
    return knob, state.replace(**{knob: getattr(state, knob) + 1})


# --- calibration -------------------------------------------------------------------------------

@dataclass(frozen=True)
class CalibrationCheck:
    """One row of the calibration table (spec 2.9), analytic checks only.

    ``deviation`` is in ``deviation_unit``: ``"%"`` of the reported value or ``"points"``.
    ``tolerance`` is the accepted range in words; ``ok`` tells whether the model is inside it.
    """
    id: str
    case: str
    quantity: str
    unit: str
    reported: float
    model: float
    deviation: float
    deviation_unit: str
    tolerance: str
    ok: bool


def calibration_checks(model: Model) -> Tuple[CalibrationCheck, ...]:
    """The analytic calibration checks C1, C2, C4-C7, C9, C10, C12 of spec 2.9.

    Reported values and tolerances are the ``calib.*`` parameters. The simulator checks C3, C8
    and C11 are not part of this library.
    """
    p = model.p
    rows = []

    def relative(check_id: str, case: str, quantity: str, unit: str, reported: float, value: float,
                 tol_pct: float) -> None:
        deviation = (value / reported - 1) * PERCENT
        rows.append(CalibrationCheck(check_id, case, quantity, unit, reported, value, deviation, "%",
                                     f"+-{tol_pct:g} %", abs(deviation) <= tol_pct))

    for check_id, key, case in (("C1", "calib.c1", "FY2025"), ("C2", "calib.c2", "FY2024"),
                                ("C4", "calib.c4.h1_2026", "H1 2026"), ("C4", "calib.c4.h1_2025", "H1 2025")):
        tol = p(f"calib.{check_id.lower()}.tol_pct")
        relative(check_id, case, "gold poured", "oz", p(f"{key}.reported_oz"),
                 gold_oz(model, p(f"{key}.milled_t"), p(f"{key}.grade_gpt")), tol)

    for grade, reported in zip(p("calib.c5.grades_gpt"), p("calib.c5.reported_pct")):
        value = recovery_pct(model, grade)
        deviation = value - reported
        tol = p("calib.c5.tol_points")
        rows.append(CalibrationCheck("C5", f"{grade:g} g/t", "gold recovery", "%", reported, value, deviation,
                                     "points", f"+-{tol:g} points", abs(deviation) <= tol))

    baseline = State()
    fleet_kw = fleet_power_kw(model, baseline)
    demand = air_demand_m3s(model, fleet_kw)
    reported = p("calib.c6.reported_m3s")
    low, high = p("calib.c6.band_pct")
    share = demand / reported * PERCENT
    rows.append(CalibrationCheck("C6", "baseline fleet", "air demand", "m3/s", reported, demand,
                                 share - PERCENT, "%", f"{low:g}-{high:g} % of reported", low <= share <= high))
    relative("C7", "part of the baseline fleet power", "air demand", "m3/s", p("calib.c7.reported_m3s"),
             air_demand_m3s(model, fleet_kw * p("calib.c7.fleet_power_share")), p("calib.c7.tol_pct"))

    relative("C9", "mean inflow", "sludge from the ponds", "t/yr", p("calib.c9.reported_t_yr"),
             pond_treatment(model, p("water.inflow_m3h")).sludge_t_year, p("calib.c9.tol_pct"))

    rate_tph = p("plant.nameplate_ktpa") * KILO / model.hours_per_year
    demand_kth_m3 = (water_balance(model, rate_tph, rate_tph, p("water.inflow_m3h")).demand_m3h
                     * model.hours_per_year / KILO)
    relative("C10", "nameplate throughput", "site and plant water demand", "thousand m3/yr",
             p("calib.c10.reported_kth_m3yr"), demand_kth_m3, p("calib.c10.tol_pct"))

    minimum = p("calib.c12.min_oz")
    gold = gold_oz(model, p("calib.c12.target_ktpa") * KILO, p("plant.grade_base"))
    rows.append(CalibrationCheck("C12", "expansion target at the base grade", "gold per year", "oz", minimum, gold,
                                 (gold / minimum - 1) * PERCENT, "%", "above reported", gold > minimum))
    return tuple(rows)
