"""Fixture engine of the Stand: a deterministic stand-in for Ditto, the simulator
and the advisor, used only with STAND_FIXTURE=1 (standard library only).

It is not the simulator and not the Expansion Advisor. It turns a knob set and a
clock into (a) a full 96-thing state in the shape of GET /api/state and (b) an
advisor report in the shape of GET /api/advisor, so that every scenario button
changes something visible on the page without the stack.

The eight link capacities, the binding link and the units held for air are not
re-implemented here: they come from sekis.capacity.evaluate, the library the
simulator and the advisor use, so the fixture cannot drift from them. The
advisor report and the knob changes of "advisor_next" / "advisor_all" are those
of sekis.advisor (the advisor service runs the same code). The layout of the
state and its time-dependent values are this module's own.

Regenerate the two committed files from the registry and the parameter file:

    python stand/fixtures/engine.py --write
"""

import collections
import copy
import dataclasses
import datetime
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TEAM_DIR = os.path.normpath(os.path.join(HERE, "..", ".."))
MODEL_DIR = os.path.join(TEAM_DIR, "model")
STATE_FILE = os.path.join(HERE, "state.json")
ADVISOR_FILE = os.path.join(HERE, "advisor.json")

if TEAM_DIR not in sys.path:    # the server loads this file by path, from any directory
    sys.path.insert(0, TEAM_DIR)

from sekis import capacity  # noqa: E402
from sekis.advisor import Advisor, wording  # noqa: E402
from sekis.sim.timebase import Calendar, parse_epoch  # noqa: E402
from sekis.sim.vod import FanControl, mine_features as vod_mine_features  # noqa: E402

NS = "kz.sekis:"
LEVEL_AIR = capacity.level_air   # build_state has a local named capacity
_ADVISOR = None   # the Expansion Advisor, built on first use

# Simulated seconds after the epoch at which the fixture clock starts
# (12 days and 54 minutes after the 09:30 epoch: day 12, 10:24 in shift A, so
# that a first look shows a working mine).
FIXTURE_START_S = 12 * 86400 + 54 * 60

DEFAULT_KNOBS = {
    "target_ktpa": 1000.0, "m_plant": 0.0, "m_haul": 0.0, "m_stopes": 0.0,
    "m_vent": 0.0, "m_dev": 0.0, "m_water": 0.0, "m_tailings": 0.0,
    "tu1_closed": 0.0, "tu2_closed": 0.0, "fan_vs2_off": 0.0,
    "pumps_failed_p150": 0.0, "inflow_factor": 1.0, "grade_gpt": 2.05,
    "line_down": 0.0, "vod_enabled": 1.0,
}

LINKS = ["haulage", "ventilation", "stopes", "development", "dewatering",
         "plant", "water", "tailings"]
# Trucks, LHDs, rigs and producing stopes by measure stage (spec 3.1).
TRUCKS_BY_STAGE = [5, 7, 10, 12]
LHDS_BY_STAGE = [4, 5, 8, 10]
RIGS_BY_STAGE = [2, 3, 4, 5]
STOPES_BY_STAGE = [4, 5, 8, 10]
STOPE_ORDER = ([f"stp-{lv}-1" for lv in ("p150", "p100", "p050", "000")]
               + [f"stp-{lv}-2" for lv in ("p150", "p100", "p050", "000")]
               + [f"stp-{lv}-3" for lv in ("p150", "p100", "p050", "000")]
               + [f"stp-m050-{i}" for i in (1, 2, 3)])
DAM_ORDER = ["tsf-dam4", "tsf-dam2", "tsf-dam3", "tsf-cell5"]

# Schematic plan positions of spec 4.2, used when model/geometry.json is absent.
# X of a decline at even and at odd multiples of 50 m of elevation.
DECLINE_X = {"tu1": (-330.0, 25.8), "tu2": (30.0, 385.8)}
DECLINE_Z = {"tu1": 120.0, "tu2": 150.0}
ROM_PAD = (-305.0, 430.0, -215.0)
STOPE_X = {"1": -200.0, "2": 0.0, "3": 200.0}
DRIVE_Z, DRAW_Z = 40.0, 10.0


def load_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


class Model:
    """Registry and parameters, read once."""

    def __init__(self, model_dir=MODEL_DIR):
        self.registry = load_json(os.path.join(model_dir, "registry.json"))
        self.params = load_json(os.path.join(model_dir, "params.json"))
        # The same two files as the model of the analytic library.
        self.cap = capacity.Model(self.params, self.registry)
        self.attrs = {t["thingId"][len(NS):]: t["attributes"]
                      for t in self.registry["things"]}
        # Baseline features of every thing, as the registry gives them.
        self.baseline = {t["thingId"]: {fid: body["properties"]["value"]
                                        for fid, body in t["features"].items()}
                         for t in self.registry["things"]}

    def p(self, key):
        return self.params[key]["value"]


# --------------------------------------------------------------- capacities

def stage(knobs, knob):
    return int(round(knobs.get(knob, 0)))


def active_trucks(knobs):
    return [f"truck-{i:02d}" for i in range(1, TRUCKS_BY_STAGE[stage(knobs, "m_haul")] + 1)]


def active_lhds(knobs):
    return [f"lhd-{i:02d}" for i in range(1, LHDS_BY_STAGE[stage(knobs, "m_stopes")] + 1)]


def active_rigs(knobs):
    return [f"rig-{i:02d}" for i in range(1, RIGS_BY_STAGE[stage(knobs, "m_stopes")] + 1)]


def producing_stopes(knobs):
    return STOPE_ORDER[:STOPES_BY_STAGE[stage(knobs, "m_stopes")]]


def flooded_levels(knobs):
    """The fixture shows the end state of a dead +150 m station at once: the water has risen to
    the TU2 portal at +320 m and every level of capacity.flood_order is flooded (-50 m up to
    +250 m), as in the simulator about 43 minutes of the Stand after the failure."""
    if stage(knobs, "pumps_failed_p150") < 3:
        return []
    return [name for name, _ in capacity.flood_order(_flood_model())]


_FLOOD_MODEL = None


def _flood_model():
    """sekis.capacity's model, for the flood order (built once)."""
    global _FLOOD_MODEL
    if _FLOOD_MODEL is None:
        _FLOOD_MODEL = capacity.load_model()
    return _FLOOD_MODEL


def truck_decline(model, knobs, truck):
    """Decline a truck uses: its home one, or the other while home is closed."""
    home = model.attrs[truck]["link_home_decline"].rsplit("-", 1)[1]
    if stage(knobs, f"{home}_closed"):
        return "tu1" if home == "tu2" else "tu2"
    return home


def ramp_km(model, decline, elevation):
    k = 1.0 / math.sin(math.radians(model.p("decline.slope_deg")))
    portal = model.p(f"decline.{decline}.portal_m")
    return (portal - elevation) * k * model.p("decline.length_factor") / 1000.0


def fleet_kw(model, knobs):
    return sum(model.attrs[name]["engine_kw"]
               for name in active_trucks(knobs) + active_lhds(knobs))


def line_rated_tph(model, knobs, number):
    """Rated feed of plant line `number` for the current plant stage, 0 if not built."""
    return capacity.plant(model.cap, stage(knobs, "m_plant")).lines[number - 1].rated_tph


def tailings_free_kt(model, knobs):
    p = model.p
    free = p("tsf.dam4_capacity_t") * (1 - p("tsf.dam4_fill_start")) + 2 * p("tsf.dam23_free_t")
    if stage(knobs, "m_tailings"):
        free += p("tsf.measure_X1_t")
    return free / 1000.0


def recovery_pct(model, grade):
    p = model.p
    value = p("plant.recovery.intercept_pct") + p("plant.recovery.slope_pct_per_gpt") * grade
    return max(p("plant.recovery.min_pct"), min(p("plant.recovery.max_pct"), value))


def capacity_state(model, knobs, centroid=None, free_kt=None):
    """State of sekis.capacity for a knob set. `free_kt` (the storage still free,
    for the projection) is passed as the tailings placed since the epoch."""
    placed_t = 0.0
    if free_kt is not None:
        placed_t = max(0.0, tailings_free_kt(model, knobs) - free_kt) * 1000.0
    return capacity.State.from_knobs(knobs, centroid_m=centroid, tailings_placed_t=placed_t,
                                     flooded_levels=tuple(flooded_levels(knobs)))


def capacities(model, knobs, centroid=None, free_kt=None):
    """The eight link capacities, kt/yr, and the quantities they are built from:
    sekis.capacity.evaluate in the shape this module works with."""
    res = capacity.evaluate(model.cap, capacity_state(model, knobs, centroid, free_kt))
    flooded = flooded_levels(knobs)
    # A link that does not limit (dewatering while the pumps keep up) is shown as 0.
    caps = {link: float(res.capacity_rounded[link] or 0) for link in LINKS}
    binding = res.binding_link
    air = res.air
    return {
        "caps": caps, "binding": binding, "achievable": caps[binding],
        "dewatering_limiting": res.dewatering.limiting, "dewatering_margin": round(res.dewatering.margin, 2),
        "air_supply": float(air.supply_m3s), "air_demand": round(air.demand_m3s, 1),
        "air_used": round(air.used_m3s, 1), "air_spare": round(air.spare_m3s, 1),
        # Units the hold rule of spec 2.6 keeps waiting for air, in holding order.
        "held_trucks": list(air.held_trucks), "held_lhds": list(air.held_lhds),
        "kw_working": air.working_kw, "air": air,
        "vent_detail": wording.link_detail(model.cap, {}, "ventilation", res),
        "inflow_m3h": res.dewatering.inflow_m3h,
        "free_kt": tailings_free_kt(model, knobs) if free_kt is None else free_kt,
        "flooded": flooded,
    }


def water_balance(model, knobs, mine_ktpa, feed_tph):
    """Water flows in m3/h at the rates the twins run at (decision 11.4): the mine hoists
    `mine_ktpa` over the working days, 24 h a day; the plant wants `feed_tph` (the lines that
    run now). Mine water is what the pumps deliver in steady state (none while the +150 m
    station is dead: the fixture shows the end state, with the ponds empty)."""
    p = model.p
    res = capacity.evaluate(model.cap, capacity_state(model, knobs))
    hoist_tph = mine_ktpa * 1000.0 / (p("regime.working_days") * 24.0)
    balance = capacity.water_balance(model.cap, hoist_tph, feed_tph, res.dewatering.pumped_m3h,
                                     stage(knobs, "m_water"))
    return {
        "mine_water": balance.mine_water_m3h, "site_use": balance.site_use_m3h,
        "plant_supply": balance.plant_supply_m3h, "reclaim": balance.reclaim_m3h,
        "extra_intake": balance.extra_intake_m3h, "deficit": balance.deficit_m3h,
        "discharge": balance.discharge_m3h, "feed_limit": balance.feed_limit_tph,
        "permit_use": balance.permit_use_pct, "permit_state": balance.permit_state,
    }


def plant_running(model, knobs, cap, mine_ktpa):
    """(plant feed in t/h after the water limit, water balance, water factor). The water is
    balanced at the plant's mean feed (its capacity with the planned line stops), the basis of the
    advisor's water KPIs, because the fixture has no ponds to carry the hours with every line
    running; the lines run at their rated feed times the factor the water allows."""
    wanted = cap["caps"]["plant"] * 1000.0 / model.cap.hours_per_year
    balance = water_balance(model, knobs, mine_ktpa, wanted)
    feed = min(wanted, balance["feed_limit"]) if balance["deficit"] > 0 else wanted
    factor = 1.0 if wanted <= 0 else max(0.0, feed / wanted)
    return feed, balance, factor


def advisor():
    """The Expansion Advisor of sekis.advisor, built once per process."""
    global _ADVISOR
    if _ADVISOR is None:
        _ADVISOR = Advisor()
    return _ADVISOR


def advisor_inputs(knobs, revision=0, label="", sim_time=None):
    """Inputs of the advisor for a knob set: the epoch tonnages and the levels the fixture
    shows flooded."""
    adv = advisor()
    inputs = adv.default_inputs().with_knobs({k: v for k, v in knobs.items() if k in DEFAULT_KNOBS})
    return dataclasses.replace(inputs, revision=int(revision), label=label, sim_time=sim_time,
                               flooded_levels=tuple(flooded_levels(knobs)))


def build_report(model, knobs, before_knobs=None, revision=0, label="Базовый режим",
                 sim_time=None):
    """Advisor report in the shape served by GET /api/advisor: the report of sekis.advisor
    for this knob set (the same code the advisor service runs)."""
    after = advisor_inputs(knobs, revision, label, sim_time)
    before = None if before_knobs is None else advisor_inputs(before_knobs, max(0, int(revision) - 1))
    return advisor().report(after, before)


def apply_changes(model, knobs, mode):
    """Knob changes the advisor proposes: one step ('next') or the whole sequence."""
    return advisor().apply(advisor_inputs(knobs), mode)


def advisor_features(report):
    """Features of kz.sekis:advisor (spec 3.4) taken from a report."""
    return advisor().features(report)


# ----------------------------------------------------------------- the state

def base_state(model):
    """State skeleton from the registry: static part and baseline features."""
    things = {}
    for thing in model.registry["things"]:
        attrs = thing["attributes"]
        things[thing["thingId"]] = {
            "kind": attrs["kind"], "name": attrs["name"], "parent": attrs.get("_parents"),
            "attrs": attrs, "f": dict(model.baseline[thing["thingId"]]),
        }
    return {"sim_time": model.p("sim.epoch"), "revision": 0, "things": things}


def sim_clock(model, sim_s):
    epoch = datetime.datetime.fromisoformat(model.p("sim.epoch"))
    now = epoch + datetime.timedelta(seconds=sim_s)
    hour = now.hour + now.minute / 60.0
    p = model.p
    if p("regime.shift_a_start_h") <= hour < p("regime.shift_a_end_h"):
        shift = "A"
    elif hour >= p("regime.shift_b_start_h") or hour < p("regime.shift_b_end_h"):
        shift = "B"
    else:
        shift = "blast"
    # Hours worked since the day started at 08:00, without the blast windows.
    since = (hour - 8.0) % 24.0
    worked = min(since, 11.0) + max(0.0, min(since, 23.0) - 12.0)
    return now.replace(microsecond=0).isoformat(), shift, hour, worked


def lerp3(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def along(points, t):
    """Point at fraction t (0..1) of the length of a polyline."""
    lengths = [math.dist(points[i], points[i + 1]) for i in range(len(points) - 1)]
    left = max(0.0, min(1.0, t)) * sum(lengths)
    for i, length in enumerate(lengths):
        if left <= length or i == len(lengths) - 1:
            return lerp3(points[i], points[i + 1], left / length if length else 0.0)
        left -= length
    return tuple(points[-1])


class Paths:
    """Where mobile units are drawn: from model/geometry.json when it is there and
    has the expected shape, otherwise from the schematic constants above."""

    def __init__(self, model, model_dir=MODEL_DIR):
        self.model = model
        self.declines, self.roads, self.objects = {}, {}, {}
        try:
            geometry = load_json(os.path.join(model_dir, "geometry.json"))
            self.objects = geometry["objects"]
            for token in ("tu1", "tu2"):
                self.declines[token] = [tuple(pt) for pt in
                                        self.objects[f"{NS}decline-{token}"]["points"]]
                self.roads[token] = [tuple(pt) for pt in
                                     geometry["scenery"][f"road-{token}"]["points"]]
        except (OSError, ValueError, KeyError, TypeError):
            self.declines, self.roads, self.objects = {}, {}, {}

    def decline(self, token, elevation):
        """Point of a decline at an elevation: (x, y, z)."""
        points = self.declines.get(token)
        if points:
            for a, b in zip(points, points[1:]):
                if a[1] >= elevation >= b[1] and a[1] != b[1]:
                    return lerp3(a, b, (a[1] - elevation) / (a[1] - b[1]))
        even, odd = DECLINE_X[token]
        k = math.floor(elevation / 50.0)
        frac = elevation / 50.0 - k
        a, b = (even, odd) if k % 2 == 0 else (odd, even)
        return (a + (b - a) * frac, elevation, DECLINE_Z[token])

    def road(self, token, t):
        """Point of the surface haul road, t = 0 at the portal, 1 at the ROM pad."""
        points = self.roads.get(token)
        if points:
            return along(points, t)
        portal = self.decline(token, self.model.p(f"decline.{token}.portal_m"))
        return lerp3(portal, ROM_PAD, t)

    def level_route(self, token, stope, t):
        """Point between the decline access (t = 0) and the stope draw point (t = 1)."""
        attrs = self.model.attrs
        level_name = attrs[stope]["link_level"][len(NS):]
        level = float(attrs[level_name]["elevation_m"])
        access = self.decline(token, level)
        x = STOPE_X[stope[-1]]
        draw = (self.objects.get(NS + stope) or {}).get("draw_point") or (x, level, DRAW_Z)
        drive = (self.objects.get(NS + level_name) or {}).get("points")
        drive_z = drive[0][2] if drive else DRIVE_Z
        return along([access, (access[0], level, drive_z), (draw[0], level, drive_z),
                      tuple(draw)], t)

    def stope(self, stope):
        return self.level_route("tu1", stope, 1.0)

    def parking(self, name, fallback):
        centre = (self.objects.get(NS + name) or {}).get("center")
        return tuple(centre) if centre else fallback


def sawtooth(sim_h, inflow, pump, low, high, volume):
    """Sump level, pumping flag and hours to the next start for a fill/drain cycle."""
    if inflow <= 0:
        return low, False, 0.0
    span = (high - low) / 100.0 * volume
    fill_h = span / inflow
    drain_h = span / max(1.0, pump - inflow)
    t = sim_h % (fill_h + drain_h)
    if t < fill_h:
        return low + (high - low) * t / fill_h, False, (100.0 - low) / 100.0 * volume / inflow - t
    return high - (high - low) * (t - fill_h) / drain_h, True, 0.0


class FanRun:
    """The main fans of one knob set under ventilation on demand, stepped minute by minute and kept
    between requests (the fixture clock only moves forward). Starts `WARM_MIN` minutes before the
    first minute asked for, from the design duty, and keeps the energy of the last 24 hours."""

    WARM_MIN = 1440 + 120

    def __init__(self, model, knobs, truck_kw, lhd_kw):
        p = model.p
        self.calendar = Calendar(model.cap.p, parse_epoch(p("sim.epoch")))
        self.control = FanControl(model.cap)
        state = capacity_state(model, knobs)
        self.control.configure(bool(round(knobs.get("vod_enabled", 1.0))),
                               capacity.fans_running(model.cap, state), first=True)
        self.q_base = p("vent.q_base")
        self.work = self.q_base + p("vent.q_diesel") * (truck_kw * p("truck.availability") + lhd_kw)
        self.pre_s = p("vod.pre_vent_min") * 60.0
        self.block_starts = [first for first, _ in self.calendar.blocks]
        self.shift_starts = [first for _, first, _ in self.calendar.shifts]
        self.minute = None
        self.history = collections.deque(maxlen=1440)   # (minute, kWh of the fans, kWh at design duty)

    def second_of_day(self, minute):
        step_s = self.calendar.step_s
        return self.calendar.index(int(minute * 60 // step_s)) * step_s

    def productive(self, minute):
        return self.calendar.productive[self.second_of_day(minute) // self.calendar.step_s]

    def advance(self, minute_now):
        if self.minute is None or minute_now < self.minute:
            self.minute = minute_now - self.WARM_MIN
        control = self.control
        while self.minute < minute_now:
            self.minute += 1
            sod = self.second_of_day(self.minute)
            soon = min((first - sod) % 86400 for first in self.block_starts) <= self.pre_s
            need = self.work if self.productive(self.minute) or soon else self.q_base
            control.step(self.minute * 60.0, need, 60.0)
            self.history.append((self.minute, control.power_kw() / 60.0, control.fixed_power_kw() / 60.0))

    def report(self, minute_now):
        self.advance(minute_now)
        sod_now = self.second_of_day(minute_now)
        today_from = minute_now - sod_now // 60
        shift_from = minute_now - min((sod_now - first) % 86400 for first in self.shift_starts) // 60
        today, shift, day = [0.0, 0.0], [0.0, 0.0], [0.0, 0.0]
        for minute, energy, fixed in self.history:
            for account, first in ((today, today_from), (shift, shift_from), (day, minute_now - 1440)):
                if minute > first:
                    account[0] += energy
                    account[1] += fixed
        return {"control": self.control, "demand": self.work if self.productive(minute_now) else self.q_base,
                "today": tuple(today), "shift": tuple(shift), "day": tuple(day)}


_FAN_RUNS = {}


def vod_day(model, knobs, truck_kw, lhd_kw, sim_s):
    """The main fans under ventilation on demand at the fixture clock (spec 3.5): the control law
    of the simulator (sekis.sim.vod.FanControl) run minute by minute (`FanRun`). In the productive
    blocks of the shift calendar (sekis.sim.timebase.Calendar) the units in work need
    `vent.q_base + vent.q_diesel x kW`, the trucks at their availability (`truck.availability`: on
    average one truck in five is under repair; the fixture has no breakdowns of its own); outside
    them `vent.q_base`. The duty reaches the demand of a block `vod.pre_vent_min` before it starts.
    Returns the controller, the demand now and the energy of the fans and at their design duty,
    kWh, over today (since 08:00), the shift and the last 24 hours."""
    key = (tuple(sorted(knobs.items())), round(truck_kw, 3), round(lhd_kw, 3))
    run = _FAN_RUNS.get(key)
    if run is None:
        if len(_FAN_RUNS) > 16:
            _FAN_RUNS.clear()
        run = _FAN_RUNS[key] = FanRun(model, knobs, truck_kw, lhd_kw)
    return run.report(int(sim_s // 60))


def held_by_ventilation(cap):
    """Units held by the ventilation rule of spec 2.6 (sekis.capacity.hold_units)
    and the engine power of the units left working."""
    return cap["held_trucks"] + cap["held_lhds"], cap["kw_working"]


def build_state(model, base, knobs, revision=0, label="Базовый режим", sim_s=FIXTURE_START_S,
                report=None, paths=None):
    """Full state for GET /api/state at a knob set and a simulated time."""
    p = model.p
    paths = paths or Paths(model)
    attrs = model.attrs
    report = report or build_report(model, knobs, revision=revision, label=label)
    cap = capacities(model, knobs)
    # The static part comes from the base state; every feature starts from its
    # registry baseline, so nothing of an earlier moment leaks into this one.
    things = {tid: {"kind": t["kind"], "name": t["name"], "parent": t["parent"],
                    "attrs": t["attrs"], "f": dict(model.baseline.get(tid, t["f"]))}
              for tid, t in base["things"].items()}

    def f(name):
        return things[NS + name]["f"]

    sim_time, shift, hour, worked_h = sim_clock(model, sim_s)
    sim_h = sim_s / 3600.0
    sim_min = sim_s / 60.0
    sim_day = sim_s / 86400.0
    working = shift != "blast"
    flooded = cap["flooded"]
    grade_factor = knobs["grade_gpt"] / p("plant.grade_base")
    held, kw_running = held_by_ventilation(cap)

    # ---- stopes
    producing = producing_stopes(knobs)
    stope_state = {}
    for name in [n for n in attrs if n.startswith("stp-")]:
        level = "lvl-" + name.split("-")[1]
        st = f(name)
        st["grade"] = round(attrs[name]["grade_gpt"] * grade_factor, 2)
        if level in flooded:
            state = "flooded"
        elif name in producing:
            index = producing.index(name)
            since_blast = (sim_h - 8.0 - 12.0 * index) % 48.0
            blasts = int((sim_h - 8.0 - 12.0 * index) // 48.0) + 1
            st["ore_remaining_t"] = round(max(0.0, attrs[name]["ore_initial_t"]
                                              - max(0, blasts) * p("stope.blast_t")), 1)
            st["broken_ore_t"], st["drilled_pct"] = 0.0, 0.0
            if since_blast < 0.5:
                state, st["broken_ore_t"] = "ventilating", p("stope.blast_t")
            elif since_blast < 24.0:
                state = "mucking"
                st["broken_ore_t"] = round(p("stope.blast_t") * (24.0 - since_blast) / 23.5, 1)
                st["mucked_today_t"] = round(p("stope.blast_t") - st["broken_ore_t"], 1)
            elif since_blast < 40.0:
                state, st["drilled_pct"] = "drilling", round((since_blast - 24.0) / 16.0 * 100.0, 1)
            elif since_blast < 45.0:
                state, st["drilled_pct"] = "charging", 100.0
            else:
                state, st["drilled_pct"] = "awaiting_blast", 100.0
        elif name.startswith("stp-m050"):
            state = "preparation"
        elif name.startswith("stp-m100"):
            state = "planned"
        else:
            state = "standby"
        st["state"] = state
        stope_state[name] = state

    # ---- LHDs and rigs
    lhd_stope = {}
    for index, name in enumerate(sorted(n for n in attrs if n.startswith("lhd-"))):
        unit = f(name)
        active = name in active_lhds(knobs) or name in held
        stope = producing[index] if index < len(producing) else None
        if not active or stope is None:
            x, y, z = paths.parking(name, (-300.0 + 12.0 * index, 430.0, -200.0))
            unit.update(state="parked", stope="none", pos_x=x, pos_y=y, pos_z=z)
            continue
        x, y, z = paths.stope(stope)
        unit.update(stope=stope, pos_x=x, pos_y=y, pos_z=z)
        if stope_state[stope] == "flooded":      # pulled back to the level drive, engine off
            x, y, z = paths.level_route("tu1", stope, 0.6)
            unit.update(state="idle", pos_x=x, pos_y=y, pos_z=z)
        elif name in held:
            unit["state"] = "standby_vent"
            things[NS + stope]["f"]["state"] = stope_state[stope] = "standby"
        elif not working:
            unit.update(state="shift_break", tonnes_today=round(140.0 * worked_h, 1))
        else:
            unit.update(state="mucking" if stope_state[stope] == "mucking" else "idle",
                        tonnes_today=round(140.0 * worked_h, 1))
            lhd_stope[stope] = name
    drilling = [s for s in producing if stope_state[s] == "drilling"]
    for index, name in enumerate(sorted(n for n in attrs if n.startswith("rig-"))):
        unit = f(name)
        x, y, z = paths.parking(name, (-300.0 + 12.0 * index, 430.0, -180.0))
        if name not in active_rigs(knobs):
            unit.update(state="parked", stope="none", pos_x=x, pos_y=y, pos_z=z)
        elif index < len(drilling):
            x, y, z = paths.stope(drilling[index])
            unit.update(state="drilling" if working else "shift_break", stope=drilling[index],
                        pos_x=x + 30.0, pos_y=y, pos_z=z, metres_today=round(22.0 * worked_h, 1))
        else:   # between stopes, on the drive of the level of the next block
            home = producing[index % len(producing)]
            x, y, z = paths.level_route("tu1", home, 0.5)
            unit.update(state="tramming" if working else "shift_break", stope="none",
                        pos_x=x, pos_y=y, pos_z=z, metres_today=round(9.0 * worked_h, 1))

    # ---- trucks
    running = [t for t in active_trucks(knobs)]
    by_decline = {"tu1": [], "tu2": []}
    for name in running:
        by_decline[truck_decline(model, knobs, name)].append(name)
    stats = {d: {"on_ramp": 0, "waiting": 0, "trips": 0.0, "tonnes": 0.0, "cycles": []}
             for d in by_decline}
    level_kw = {}
    mucking = [s for s in producing if stope_state[s] == "mucking"] or \
              [s for s in producing if stope_state[s] != "flooded"]
    for index, name in enumerate(sorted(n for n in attrs if n.startswith("truck-"))):
        unit = f(name)
        info = attrs[name]
        if name not in running and name not in held:
            x, y, z = paths.parking(name, (-320.0 + 14.0 * index, 430.0, -220.0))
            unit.update(state="parked", payload=0.0, grade=0.0, speed=0.0, decline="none",
                        chainage_m=0.0, elevation=y, pos_x=x, pos_y=y, pos_z=z)
            continue
        decline = truck_decline(model, knobs, name)
        portal = p(f"decline.{decline}.portal_m")
        bottom = p(f"decline.{decline}.bottom_m")
        reachable = [s for s in mucking if attrs[attrs[s]["link_level"][len(NS):]]["elevation_m"] >= bottom]
        peers = by_decline[decline]
        slot = peers.index(name) if name in peers else 0
        if name in held or not working or not reachable:
            # Waiting on the haul road just outside the portal, one behind another.
            x, y, z = paths.road(decline, 0.03 + 0.03 * index)
            unit.update(state="held_vent" if name in held else "shift_break", payload=0.0,
                        grade=0.0, speed=0.0, decline="none", chainage_m=0.0, elevation=round(y, 1),
                        pos_x=round(x, 1), pos_y=round(y, 1), pos_z=round(z, 1))
            continue
        stope = reachable[slot % len(reachable)]
        level_z = float(attrs[attrs[stope]["link_level"][len(NS):]]["elevation_m"])
        length = ramp_km(model, decline, level_z)
        surface = p(f"decline.{decline}.surface_km")
        payload = float(info["payload_t"])
        ore_grade = things[NS + stope]["f"]["grade"]
        v = {k: p(f"truck.speed_{k}_kmh") for k in ("up_loaded", "down_empty", "flat_loaded", "flat_empty")}
        segments = [
            ("surface_haul", 60 * surface / v["flat_empty"], False, v["flat_empty"]),
            ("descending", 60 * length / v["down_empty"], False, v["down_empty"]),
            ("tram_level", 0.75, False, 8.0),
            ("queue_load", 0.5, False, 0.0),
            ("loading", p("truck.load_min"), True, 0.0),
            ("tram_level", 0.75, True, 8.0),
            ("hauling_up", 60 * length / v["up_loaded"], True, v["up_loaded"]),
            ("surface_haul", 60 * surface / v["flat_loaded"], True, v["flat_loaded"]),
            ("dumping", p("truck.dump_min"), True, 0.0),
        ]
        total = sum(seg[1] for seg in segments)
        phase = (sim_min + total * slot / max(1, len(peers))) % total
        number = 0
        for number, seg in enumerate(segments):
            if phase < seg[1]:
                break
            phase -= seg[1]
        state, duration, loaded, speed = segments[number]
        frac = phase / duration if duration else 0.0
        elevation, chainage = portal, 0.0
        if number == 0:
            pos = paths.road(decline, 1.0 - frac)
        elif number == 1:
            elevation = portal - (portal - level_z) * frac
            pos = paths.decline(decline, elevation)
            if len(peers) >= 4 and 0.45 < frac < 0.55:
                state, speed = "waiting_bay", 0.0
                stats[decline]["waiting"] += 1
        elif number in (2, 3, 4, 5):
            elevation = level_z
            t = frac if number == 2 else 1.0 - frac if number == 5 else 1.0
            pos = paths.level_route(decline, stope, t)
        elif number == 6:
            elevation = level_z + (portal - level_z) * frac
            pos = paths.decline(decline, elevation)
        elif number == 7:
            pos = paths.road(decline, frac)
        else:
            pos = paths.road(decline, 1.0)
        if number in (0, 7, 8):
            elevation = pos[1]
        if number in (1, 6):
            stats[decline]["on_ramp"] += 1
        if 1 <= number <= 6:
            chainage = ramp_km(model, decline, elevation) * 1000.0
        if 2 <= number <= 5:      # on the level drive: its air is the level's (on the ramp: the decline's)
            level = attrs[stope]["link_level"][len(NS):]
            level_kw[level] = level_kw.get(level, 0.0) + info["engine_kw"]
        trips = math.floor(worked_h * 60.0 / (total / 0.81))
        stats[decline]["trips"] += trips
        stats[decline]["tonnes"] += trips * payload
        stats[decline]["cycles"].append(total / 0.81)
        if state == "loading" and stope in lhd_stope:
            f(lhd_stope[stope])["state"] = "loading_truck"
        unit.update(state=state, payload=payload if loaded and number != 4 else
                    round(payload * frac, 1) if number == 4 else 0.0,
                    grade=ore_grade if loaded else 0.0, speed=speed,
                    decline=decline if 1 <= number <= 6 else "none",
                    chainage_m=round(chainage, 1), elevation=round(elevation, 1),
                    pos_x=round(pos[0], 1), pos_y=round(pos[1], 1), pos_z=round(pos[2], 1),
                    trips_today=float(trips), tonnes_today=trips * payload)
    for decline, data in stats.items():
        d = f(f"decline-{decline}")
        d.update(state="closed" if stage(knobs, f"{decline}_closed") else "open",
                 trucks_on_ramp=float(data["on_ramp"]), trucks_waiting_in_bays=float(data["waiting"]),
                 loaded_trips_today=float(data["trips"]), ore_today_t=float(data["tonnes"]),
                 avg_cycle_min=round(sum(data["cycles"]) / len(data["cycles"]), 1) if data["cycles"] else 0.0)

    # ---- throughput
    rate = cap["achievable"]                      # the chain, kt/yr
    # The mine hoists what its own links allow, whatever the plant takes (the simulator does the
    # same); the stockpile takes up the difference.
    mine_links = ["haulage", "ventilation", "stopes", "development"] + (
        ["dewatering"] if cap["dewatering_limiting"] else [])
    mine_rate = min(cap["caps"][link] for link in mine_links)
    mined_tpd = mine_rate * 1000.0 / p("regime.working_days")
    productive_h = p("regime.shifts") * p("regime.productive_h")
    hoisted_tph = mined_tpd / productive_h if working else 0.0

    # ---- ventilation: the fans under ventilation on demand (spec 3.5)
    supply = cap["air_supply"]
    demand = p("vent.q_base") + p("vent.q_diesel") * kw_running
    truck_kw = sum(attrs[n]["engine_kw"] for n in active_trucks(knobs) if n not in held)
    lhd_kw = sum(attrs[n]["engine_kw"] for n in active_lhds(knobs) if n not in held)
    vod = vod_day(model, knobs, truck_kw, lhd_kw, sim_s)
    control = vod["control"]
    m_vent = stage(knobs, "m_vent")
    fan_state = {
        "fan-vs1": "running", "fan-ug-p320": "running",
        "fan-vs2": "failed" if stage(knobs, "fan_vs2_off") else "running",
        "fan-vpv": "running" if m_vent >= 1 else "planned",
        "fan-vs3": "running" if m_vent >= 2 else "planned",
    }
    for name, state in fan_state.items():
        flow, setpoint, pressure, power = control.fan(name) if state == "running" else (0.0, 0.0, 0.0, 0.0)
        f(name).update(state=state, air_flow_m3s=round(flow, 1), duty_setpoint_m3s=round(setpoint, 1),
                       pressure=round(pressure, 1), power_kw=round(power, 1))
    delivered = control.delivered()
    airway_flow = {
        "shaft-vs1": f("fan-vs1")["air_flow_m3s"], "shaft-vs2": f("fan-vs2")["air_flow_m3s"],
        "shaft-vs3": f("fan-vs3")["air_flow_m3s"], "raise-vpv": f("fan-vpv")["air_flow_m3s"],
        "raise-vhv-tu1": f("fan-ug-p320")["air_flow_m3s"] / 2.0,
        "raise-vhv-tu2": f("fan-ug-p320")["air_flow_m3s"] / 2.0,
        "raise-vhv-exhaust": delivered,
    }
    for name, flow in airway_flow.items():
        planned = (name == "shaft-vs3" and m_vent < 2) or (name == "raise-vpv" and m_vent < 1)
        f(name).update(state="planned" if planned else "in_service", air_flow_m3s=round(flow, 1),
                       air_velocity_ms=round(flow / attrs[name]["section_m2"], 1))
    levels = sorted(n for n in attrs if n.startswith("lvl-"))
    open_levels = [n for n in levels if attrs[n]["role"] != "planned"]
    for stope, lhd in lhd_stope.items():
        level = attrs[stope]["link_level"][len(NS):]
        level_kw[level] = level_kw.get(level, 0.0) + attrs[lhd]["engine_kw"]
    held_kw = {}
    for index, name in enumerate(sorted(n for n in attrs if n.startswith("lhd-"))):
        if name in held and index < len(producing):
            level = attrs[producing[index]]["link_level"][len(NS):]
            held_kw[level] = held_kw.get(level, 0.0) + attrs[name]["engine_kw"]
    level_air = LEVEL_AIR(model.cap, delivered, vod["demand"], level_kw, flooded, held_kw)
    inflow = cap["inflow_m3h"]
    upper = [n for n in open_levels if attrs[n]["elevation_m"] >= 150]
    for name in levels:
        lv = f(name)
        own = [s for s in producing if attrs[s]["link_level"] == NS + name]
        lv["state"] = "flooded" if name in flooded else attrs[name]["role"]
        if name in open_levels:
            share = p("water.upper_share") / len(upper) if name in upper else \
                (1 - p("water.upper_share")) / (len(open_levels) - len(upper))
            lv.update(air_required_m3s=round(level_air[name].required_m3s, 1),
                      air_flow_m3s=round(level_air[name].flow_m3s, 1),
                      diesel_kw=float(level_kw.get(name, 0.0)),
                      water_inflow_m3h=round(inflow * share, 1),
                      active_stopes=float(sum(1 for s in own if stope_state[s] not in ("flooded", "standby"))),
                      ore_today_t=round(sum(things[NS + s]["f"]["mucked_today_t"] for s in own), 1))

    # ---- dewatering
    failed = stage(knobs, "pumps_failed_p150")
    low_inflow = inflow * (1 - p("water.upper_share"))
    high_inflow = inflow * p("water.upper_share") + low_inflow
    dead = failed >= 3

    def pump_kw(flow, head):
        return round(1000 * 9.81 * flow / 3600.0 * head * p("water.pump_head_factor")
                     / p("water.pump_efficiency") / 1000.0, 1)

    m050 = f("ps-m050")
    if dead:
        m050.update(state="alarm_high", inflow_m3h=round(low_inflow, 1), pumped_m3h=0.0,
                    sump_level_pct=100.0, pumps_running=0.0, pumps_available=2.0, power_kw=0.0,
                    hours_to_overflow=0.0)
    else:
        unit = p("water.ps_m050.pump_m3h")
        pump = unit if low_inflow < unit else 2 * unit
        level, on, hours = sawtooth(sim_h, low_inflow, pump, p("water.ps_m050.stop_pct"),
                                    p("water.ps_m050.start1_pct"), p("water.ps_m050.sump_m3"))
        m050.update(state="pumping" if on else "idle", inflow_m3h=round(low_inflow, 1),
                    pumped_m3h=float(pump) if on else 0.0, sump_level_pct=round(level, 1),
                    pumps_running=float(pump / unit) if on else 0.0, pumps_available=2.0,
                    power_kw=pump_kw(pump, p("water.head_ps_m050_m")) if on else 0.0,
                    hours_to_overflow=round(hours, 1))
    p150 = f("ps-p150")
    if dead:
        p150.update(state="failed", inflow_m3h=round(high_inflow, 1), pumped_m3h=0.0,
                    sump_level_pct=100.0, pumps_running=0.0, pumps_available=0.0, power_kw=0.0,
                    hours_to_overflow=0.0)
    else:
        unit = p("water.ps_p150.pump_m3h")
        two = high_inflow >= unit
        pump = 2 * unit if two else unit
        high = p("water.ps_p150.start2_pct") if two else p("water.ps_p150.start1_pct")
        level, on, hours = sawtooth(sim_h + 0.7, high_inflow, pump, p("water.ps_p150.stop_pct"),
                                    high, p("water.ps_p150.sump_m3"))
        p150.update(state="pumping" if on else "idle", inflow_m3h=round(high_inflow, 1),
                    pumped_m3h=float(pump) if on else 0.0, sump_level_pct=round(level, 1),
                    pumps_running=float(pump / unit) if on else 0.0,
                    pumps_available=float(p("water.ps_p150.pumps") - failed),
                    power_kw=pump_kw(pump, p("water.head_ps_p150_m")) if on else 0.0,
                    hours_to_overflow=round(hours, 1))
    f("ps-m200")["state"] = "planned"
    # the end state of a dead station: the workings full to the TU2 portal at +320 m
    # (params water.flood_outlet_m3); nothing more floods, so mine.flood_eta_min stays 0
    flood_volume = float(p("water.flood_outlet_m3")) if dead else 0.0

    # ---- plant, stockpile, tailings
    down = stage(knobs, "line_down")
    plant_cap = cap["caps"]["plant"]
    _, balance, water_factor = plant_running(model, knobs, cap, mine_rate)
    feed = 0.0
    lines_running = 0
    for number in range(1, 7):
        line = f(f"plant-line-{number}")
        rated = line_rated_tph(model, knobs, number)
        if rated <= 0:
            line.update(state="planned", feed_tph=0.0, utilisation_pct=0.0, milled_today_t=0.0)
        elif number == down:
            line.update(state="off", feed_tph=0.0, utilisation_pct=0.0, milled_today_t=0.0)
        else:
            tph = rated * water_factor
            line.update(state="water_limited" if water_factor < 0.999 else "running",
                        feed_tph=round(tph, 2), utilisation_pct=round(100.0 * water_factor, 1),
                        milled_today_t=round(tph * ((hour - 8.0) % 24.0), 1))
            feed += tph
            lines_running += 1
    feed_grade = round(knobs["grade_gpt"], 2)
    recovery = recovery_pct(model, feed_grade)
    gold_day = (feed * 24.0 * p("plant.availability") * feed_grade * recovery / 100.0
                / p("gold.g_per_oz"))
    f("plant").update(state="water_limited" if water_factor < 0.999 else "running",
                      feed_tph=round(feed, 1), feed_grade=feed_grade,
                      recovery_pct=round(recovery, 2), gold_poured_oz_day=round(gold_day, 1),
                      capacity_ktpa=plant_cap, lines_running=float(lines_running),
                      water_demand_m3h=round(p("water.plant_m3_per_t") * feed, 1),
                      tailings_tph=round(feed, 1))
    milled_tpd = feed * 24.0 * p("plant.availability")   # planned maintenance averaged
    stock = max(0.0, p("stockpile.start_t") + (mined_tpd - milled_tpd) * sim_day)
    # days of plant feed without any ore from the mine, as the simulator publishes it
    plant_tpd = plant_cap * 1000.0 / p("regime.plant_days")
    days_of_feed = min(999.0, stock / plant_tpd) if plant_tpd > 0 else 0.0
    f("rom-stockpile").update(
        state="empty" if stock < p("plant.min_stockpile_t") else "low" if days_of_feed < p("stockpile.low_days_of_feed")
        else "normal",
        tonnes=round(stock), grade=feed_grade, inflow_tph=round(hoisted_tph, 1),
        outflow_tph=round(feed, 1), days_of_feed=round(days_of_feed, 2))
    milled_total = milled_tpd * sim_day
    remaining = milled_total
    free_total = 0.0
    stored_total = 0.0
    active_dam = None
    for name in DAM_ORDER:
        dam = f(name)
        capacity = float(attrs[name]["capacity_t"])
        start = capacity * p("tsf.dam4_fill_start") if name == "tsf-dam4" else \
            capacity - p("tsf.dam23_free_t") if name in ("tsf-dam2", "tsf-dam3") else 0.0
        built = name != "tsf-cell5" or stage(knobs, "m_tailings")
        added = min(remaining, capacity - start) if built else 0.0
        remaining -= added
        stored = start + added
        is_full = stored >= capacity - 1.0
        if not built:
            state = "planned"
        elif is_full:
            state = "full"
        elif active_dam is None:
            state, active_dam = "active", name
        else:
            state = "standby"
        dam.update(state=state, stored_t=round(stored), fill_pct=round(100.0 * stored / capacity, 1),
                   free_capacity_t=round(capacity - stored) if built else 0.0,
                   inflow_tph=round(feed, 1) if state == "active" else 0.0)
        if built:
            free_total += capacity - stored
        stored_total += stored
    years_left = free_total / (milled_tpd * p("regime.plant_days")) if milled_tpd else 0.0
    f("tailings").update(
        state="full" if free_total <= 0 else "short_horizon" if years_left < p("tsf.min_years") else "ok",
        stored_t=round(stored_total), free_capacity_t=round(free_total), inflow_tpd=round(milled_tpd),
        years_left=round(years_left, 1), reclaim_m3h=round(balance["reclaim"], 1))

    # ---- water
    f("water").update(
        state="deficit" if balance["deficit"] > 0.5 else
        "discharge_over_permit" if balance["permit_state"] == "exceeded" else "balanced",
        mine_water_m3h=round(balance["mine_water"], 1), site_use_m3h=round(balance["site_use"], 1),
        plant_supply_m3h=round(balance["plant_supply"] - balance["deficit"], 1),
        reclaim_m3h=round(balance["reclaim"], 1), extra_intake_m3h=round(balance["extra_intake"], 1),
        deficit_m3h=round(balance["deficit"], 1), discharge_m3h=round(balance["discharge"], 1))
    flow = balance["mine_water"]
    retention = p("pond.volume_m3") / 2.0 / flow if flow else 0.0
    tss_out = p("pond.tss_in_mgl") * (1 - p("pond.efficiency") * min(1.0, 2 * retention / p("pond.settling_h")))
    for name in ("pond-upper", "pond-lower"):
        f(name).update(state="in_service", inflow_m3h=round(flow, 1), retention_h=round(retention, 1),
                       tss_in_mgl=p("pond.tss_in_mgl"), tss_out_mgl=round(tss_out, 2),
                       sludge_t_year=round(flow * 8760 * p("pond.tss_in_mgl") * p("pond.efficiency") / 1e6 / 2.0, 1))
    use = 100.0 * balance["discharge"] / p("water.permit_m3h")
    f("mon-volchevka").update(
        state="exceeded" if use > 100 else "warning" if use > p("water.permit_warning_pct") else "normal",
        discharge_m3h=round(balance["discharge"], 1), intake_m3h=0.0, tss_mgl=round(tss_out, 2),
        permit_use_pct=round(use, 1))
    f("mon-sekisovka").update(state="normal", discharge_m3h=0.0,
                              intake_m3h=round(balance["extra_intake"], 1), tss_mgl=0.0,
                              permit_use_pct=0.0)

    # ---- mine, enterprise, scenario, advisor
    pumped_now = p150["pumped_m3h"]
    f("mine").update(
        state="blast_window" if not working else "restricted_air" if held else "production",
        ore_hoisted_tph=round(mined_tpd / 24.0, 1), ore_hoisted_today_t=round(mined_tpd * worked_h / 22.0),
        ore_hoisted_total_t=round(mined_tpd * sim_day),
        trucks_active=float(len([t for t in running if t not in held])),
        diesel_kw_active=float(kw_running),
        air_supply_m3s=supply, air_demand_m3s=round(demand, 1),
        air_margin_pct=round(100.0 * (supply - demand) / supply, 1),
        units_held_vent=float(len(held)), inflow_m3h=round(inflow, 1), pumped_m3h=pumped_now,
        flood_volume_m3=flood_volume)
    f("mine").update(vod_mine_features(control.state, delivered, vod["demand"], 0, control.power_kw(),
                                       vod["today"], vod["shift"], vod["day"], p("vod.tariff_kzt_kwh")))
    f("enterprise").update(
        sim_time=sim_time, sim_day=round(sim_day, 3), shift=shift,
        ore_mined_tpd=round(mined_tpd), ore_milled_tpd=round(milled_tpd),
        gold_poured_oz_day=round(gold_day, 1), gold_poured_total_oz=round(gold_day * sim_day),
        annual_rate_ktpa=rate, binding_link=cap["binding"])
    scenario = f("scenario")
    scenario.update({knob: float(value) for knob, value in knobs.items()})
    scenario.update(revision=float(revision), label=label)
    f("advisor").update(advisor_features(report))
    for thing in things.values():   # every number in features is a JSON float
        for key, value in thing["f"].items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                thing["f"][key] = float(value)
    return {"sim_time": sim_time, "revision": int(revision), "label": label, "things": things}


def write_files():
    model = Model()
    base = base_state(model)
    report = build_report(model, DEFAULT_KNOBS, sim_time=sim_clock(model, FIXTURE_START_S)[0])
    state = build_state(model, base, DEFAULT_KNOBS, report=report)
    print("positions from model/geometry.json" if Paths(model).declines
          else "positions from the built-in schematic (model/geometry.json not usable)")
    for path, data in ((STATE_FILE, state), (ADVISOR_FILE, report)):
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=1)
            handle.write("\n")
        print(f"written {path}")


if __name__ == "__main__":
    if "--write" in sys.argv:
        write_files()
    else:
        print(__doc__)
