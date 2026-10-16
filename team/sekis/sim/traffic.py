"""Haul trucks and the traffic on the two single-lane declines (spec 2.4).

A decline is a chain of nodes (the portal, every passing bay, the level accesses) joined by
single-lane segments. The rules, as in the spec:

* an up-going truck enters the segment above it when no down-going truck is inside; it never
  uses a waiting slot and holds on the lane at the node until the segment is clear;
* a down-going truck enters the segment below it only when no up-going truck is inside and the
  waiting slot of the node at its lower end is free; it reserves that slot when it enters;
* trucks in the same direction may follow each other.

Why this cannot deadlock: a down-going truck inside a segment always owns the slot at its lower
end, so it always completes the segment and leaves the lane. An up-going truck therefore waits
only for trucks that are moving and will clear. A down-going truck in a slot waits for up-going
trucks, which never wait for it. Up-going trucks are served first in every step, which gives
loaded trucks the priority.

Trucks are advanced by events on the fixed simulation step: every timed leg has an exact end
time, and a truck that finds its way free continues from that exact time, so the 10 s step adds
no rounding to cycle times. A wait ends at the exact time the blocking truck cleared.
"""

from __future__ import annotations

import math
import random
from collections import deque
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .. import capacity as cap

INF = float("inf")
SECONDS_PER_HOUR = 3600.0
SECONDS_PER_MINUTE = 60.0
MS_PER_KMH = 1000.0 / 3600.0

# Internal phases of a truck. The public state tokens of spec 2.4 are in ``Truck.state``.
(P_PARKED, P_PAD, P_MAINT, P_TO_PORTAL, P_DOWN_WAIT, P_DOWN, P_LEVEL_IN, P_QUEUE_DELAY, P_QUEUE,
 P_LOADING, P_LEVEL_OUT, P_UP_WAIT, P_UP, P_TO_PAD, P_DUMP) = range(15)

_UP_PHASES = frozenset((P_UP_WAIT, P_UP, P_LEVEL_OUT))
_ON_RAMP = frozenset((P_DOWN_WAIT, P_DOWN, P_UP_WAIT, P_UP))
_ON_LEVEL = frozenset((P_LEVEL_IN, P_QUEUE_DELAY, P_QUEUE, P_LOADING, P_LEVEL_OUT))
_ENGINE_OFF = frozenset((P_PARKED, P_PAD, P_MAINT))

# Spacing of trucks standing in a line on the surface, metres (drawing only, not a model number).
_LINE_SPACING_M = 12.0


class Polyline:
    """A polyline with lookup by distance or by fraction of its length."""

    __slots__ = ("points", "cum", "length")

    def __init__(self, points: Sequence[Sequence[float]]):
        self.points = [tuple(float(c) for c in pt) for pt in points]
        self.cum = [0.0]
        for a, b in zip(self.points, self.points[1:]):
            self.cum.append(self.cum[-1] + ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5)
        self.length = self.cum[-1]

    def at_distance(self, distance: float) -> Tuple[float, float, float]:
        pts, cum = self.points, self.cum
        if distance <= 0.0 or len(pts) == 1:
            return pts[0]
        if distance >= self.length:
            return pts[-1]
        for k in range(1, len(cum)):
            if distance <= cum[k]:
                span = cum[k] - cum[k - 1]
                f = (distance - cum[k - 1]) / span if span > 0 else 0.0
                a, b = pts[k - 1], pts[k]
                return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f)
        return pts[-1]

    def at(self, fraction: float) -> Tuple[float, float, float]:
        return self.at_distance(self.length * fraction)


class Ramp:
    """Traffic state of one decline. Node 0 is the portal; segment ``i`` joins nodes ``i`` and ``i + 1``."""

    def __init__(self, key: str, geo: Any, p: Any):
        self.key = key
        self.name = f"decline-{key}"
        nodes = geo.passing_bays(key)
        self.elevation: List[float] = [float(node["elevation"]) for node in nodes]
        self.chainage: List[float] = [float(node["chainage"]) for node in nodes]
        self.pos: List[Tuple[float, float, float]] = [tuple(float(c) for c in node["at"]) for node in nodes]
        self.node_of: Dict[float, int] = {elev: i for i, elev in enumerate(self.elevation)}
        factor = p("decline.length_factor")
        v_up = p("truck.speed_up_loaded_kmh") * MS_PER_KMH
        v_down = p("truck.speed_down_empty_kmh") * MS_PER_KMH
        spans = [(b - a) * factor for a, b in zip(self.chainage, self.chainage[1:])]
        self.t_up: List[float] = [span / v_up for span in spans]
        self.t_down: List[float] = [span / v_down for span in spans]
        n = len(nodes)
        self.up_count = [0] * (n - 1)
        self.down_count = [0] * (n - 1)
        self.up_clear = [-INF] * (n - 1)      # when the last up-going truck left the segment
        self.down_clear = [-INF] * (n - 1)    # when the last down-going truck left the segment
        self.slot: List[Optional["Truck"]] = [None] * n   # waiting slot of each node
        self.slot_free = [-INF] * n
        self.road = Polyline(geo.surface_road(key))       # portal -> ROM pad
        surface_km = p(f"decline.{key}.surface_km")
        self.surface_loaded_s = surface_km / p("truck.speed_flat_loaded_kmh") * SECONDS_PER_HOUR
        self.surface_empty_s = surface_km / p("truck.speed_flat_empty_kmh") * SECONDS_PER_HOUR
        self.closed = False
        self.bottom_elevation = float(p(f"decline.{key}.bottom_m"))
        self.design_bottom = float(p(f"decline.{key}.design_bottom_m"))
        self.loaded_trips_today = 0
        self.ore_today = 0.0
        self.cycles: deque = deque(maxlen=int(p("sim.cycle_stats_trips")))

    def reaches(self, elevation: float) -> bool:
        return elevation in self.node_of and self.node_of[elevation] > 0


class Truck:
    """One haul truck. ``spec`` is the ``capacity.Truck`` of the registry."""

    __slots__ = ("spec", "name", "number", "payload_t", "engine_kw", "parking", "in_service", "retiring",
                 "held", "phase", "state", "waiting", "t_next", "t_ready", "t0", "ramp", "node", "seg",
                 "target", "stope", "path", "load_t", "grade", "delay_half", "t_fail", "cycle_start",
                 "trips_today", "tonnes_today", "wait_since")

    def __init__(self, spec: cap.Truck, parking: Tuple[float, float, float]):
        self.spec = spec
        self.name = spec.name
        self.number = spec.number
        self.payload_t = spec.payload_t
        self.engine_kw = spec.engine_kw
        self.parking = parking
        self.in_service = False
        self.retiring = False
        self.held = False
        self.phase = P_PARKED
        self.state = "parked"
        self.waiting = False
        self.t_next = INF
        self.t_ready = 0.0
        self.t0 = 0.0
        self.ramp: Optional[Ramp] = None
        self.node = 0
        self.seg = -1
        self.target = 0
        self.stope: Any = None
        self.path: Optional[Polyline] = None
        self.load_t = 0.0
        self.grade = 0.0
        self.delay_half = 0.0
        self.t_fail = INF
        self.cycle_start = 0.0
        self.trips_today = 0
        self.tonnes_today = 0.0
        self.wait_since = -1.0


class Haulage:
    """The truck fleet and both ramps. ``sim`` is the owning ``Simulator``."""

    def __init__(self, sim: Any):
        self.sim = sim
        p = sim.p
        self.step_s = float(sim.step_s)
        self.load_s = p("truck.load_min") * SECONDS_PER_MINUTE
        self.dump_s = p("truck.dump_min") * SECONDS_PER_MINUTE
        # The manoeuvre time of the haulage formula is spent on the level, half each way.
        self.level_s = p("truck.manoeuvre_min") * SECONDS_PER_MINUTE / 2.0
        self.mtbf_s = p("truck.mtbf_h") * SECONDS_PER_HOUR
        self.mttr_s = p("truck.mttr_h") * SECONDS_PER_HOUR
        self.k_delay = p("sim.op_delay_factor")
        if not p("sim.op_delay_factor_min") <= self.k_delay <= p("sim.op_delay_factor_max"):
            raise ValueError("sim.op_delay_factor is outside its tuning range")
        self.trip_fraction = p("sim.last_trip_min_fraction")
        self.v_up = float(p("truck.speed_up_loaded_kmh"))
        self.v_down = float(p("truck.speed_down_empty_kmh"))
        self.v_flat_loaded = float(p("truck.speed_flat_loaded_kmh"))
        self.v_flat_empty = float(p("truck.speed_flat_empty_kmh"))
        self.ramps: Dict[str, Ramp] = {key: Ramp(key, sim.geo, p) for key in sim.model.declines}
        self.trucks: List[Truck] = [Truck(spec, sim.geo.position(spec.name)) for spec in sim.model.trucks]
        self.by_name: Dict[str, Truck] = {trk.name: trk for trk in self.trucks}
        # Every truck draws its breakdowns and its operational delays from its own streams, all
        # derived from the one seed. A truck's breakdown history then does not depend on what the
        # other units do, so a scenario and the baseline differ by the scenario, not by luck.
        self._rng_failure = {trk.name: random.Random(f"{sim.seed}:{trk.name}:breakdown") for trk in self.trucks}
        self._rng_delay = {trk.name: random.Random(f"{sim.seed}:{trk.name}:delay") for trk in self.trucks}
        self.active: List[Truck] = []
        self._warming = False        # True only inside warm_start()
        self._cycle_cache: Dict[Tuple[str, float, int], float] = {}
        self._paths: Dict[Tuple[str, str], Polyline] = {}
        self.conflicts = 0           # entries into a segment against opposing traffic; stays 0
        self.max_bay_wait_s = 0.0
        self.bay_wait_s = 0.0        # all waits in bays and at the portals
        self.up_wait_s = 0.0         # all holds of up-going trucks at a node
        self.queue_wait_s = 0.0      # all waits for the LHD, re-entry or the end of a blast window
        self.cycle_time_s = 0.0      # sum of completed loaded cycles
        self.trips = 0
        self.aborted_trips = 0
        self.maintenance_s = 0.0

    # -- fleet ----------------------------------------------------------------------------------

    def set_in_service(self, names: Sequence[str], now: float) -> None:
        """Bring the named trucks into service and retire the others at the end of their trip."""
        wanted = set(names)
        for trk in self.trucks:
            if trk.name in wanted:
                trk.retiring = False
                if not trk.in_service:
                    trk.in_service = True
                    trk.phase = P_PAD
                    trk.state = "shift_break"
                    trk.waiting = True
                    trk.t_ready = float(now)
                    trk.t_next = INF
                    trk.t_fail = now + self._rng_failure[trk.name].expovariate(1.0 / self.mtbf_s)
                    trk.ramp = self.ramps[self.sim.decline_of[trk.name]]
            elif trk.in_service:
                trk.retiring = True
        self.active = [trk for trk in self.trucks if trk.in_service]

    def warm_start(self, now: float, worked_s: float) -> None:
        """Open the run with the trucks at work: ``worked_s`` seconds of the productive block
        have already passed at ``now``, the epoch.

        The working trucks of each decline are spread evenly along the shortest cycle that
        decline offers, the analytic ``T`` of spec 2.3 item 1 for its highest producing stope:
        truck ``j`` of ``m``, by number, left the ROM pad ``T x (m - j) / (m + 1)`` before the
        epoch, but not before the block began. From there every truck is advanced to the epoch by
        the ordinary rules, so its dispatch, bay reservations and loading are those of a normal
        trip and the state at the epoch is one the rules can reach. These opening trips carry no
        random operational delay: the state at the epoch is the same for every seed, and the
        random streams start at the epoch. With the baseline fleet no truck is back at the pad
        before the epoch, so the totals start at zero; ore already loaded is booked as usual
        (as a tip before the epoch would be), which keeps the mass balances exact. Nothing
        happens when the epoch lies outside a productive block: the trucks then start from the pad.
        """
        sim = self.sim
        if worked_s <= 0.0 or not sim.productive:
            return
        fleet = self.active
        release: Dict[str, float] = {}
        for key, ramp in self.ramps.items():
            group = [trk for trk in fleet if trk.ramp is ramp and trk.phase == P_PAD and not trk.held]
            levels = [stope.elevation for stope in sim.mining.producing
                      if key in stope.ramps and stope.lhd is not None and not stope.suspended()]
            if not group or not levels:
                continue
            cycle_s = self.cycle_s(key, max(levels))
            for j, trk in enumerate(group):
                lead = min(float(worked_s), cycle_s * (len(group) - j) / (len(group) + 1))
                release[trk.name] = trk.t_ready = now - lead
        if not release:
            return
        self._warming = True
        t = now - self.step_s * math.ceil((now - min(release.values())) / self.step_s)
        while t <= now:
            self.active = [trk for trk in fleet if release.get(trk.name, t) <= t]
            self.step(t)
            t += self.step_s
        self.active = fleet
        self._warming = False

    def rehome(self) -> None:
        """Trucks standing at the surface take the decline the scenario gives them at once; a
        truck on a trip keeps its decline until it is back at the pad."""
        for trk in self.trucks:
            if trk.phase in (P_PARKED, P_PAD, P_MAINT):
                trk.ramp = self.ramps[self.sim.decline_of[trk.name]]

    def _park(self, trk: Truck) -> None:
        trk.in_service = False
        trk.retiring = False
        trk.held = False
        trk.phase = P_PARKED
        trk.state = "parked"
        trk.waiting = False
        trk.t_next = INF
        self.active = [other for other in self.trucks if other.in_service]

    def reset_day(self) -> None:
        for trk in self.trucks:
            trk.trips_today = 0
            trk.tonnes_today = 0.0
        for ramp in self.ramps.values():
            ramp.loaded_trips_today = 0
            ramp.ore_today = 0.0

    # -- stepping -------------------------------------------------------------------------------

    def step(self, now: float) -> None:
        """Advance every truck in service to ``now``; up-going trucks first."""
        run = self._run
        active = self.active
        for trk in active:
            if trk.phase in _UP_PHASES and (trk.waiting or trk.t_next <= now):
                run(trk, now)
        for trk in active:
            if trk.waiting or trk.t_next <= now:
                run(trk, now)

    def _run(self, trk: Truck, now: float) -> None:
        while True:
            phase = trk.phase
            if phase == P_PAD:
                if not self._pad(trk, now):
                    return
            elif phase == P_DOWN_WAIT:
                if not self._enter_down(trk, now):
                    return
            elif phase == P_UP_WAIT:
                if not self._enter_up(trk, now):
                    return
            elif phase == P_QUEUE:
                if not self._start_loading(trk, now):
                    return
            elif phase == P_PARKED:
                return
            else:
                if trk.t_next > now:
                    return
                self._finish(trk, phase)

    def _fresh(self, trk: Truck, now: float) -> float:
        """Start time of an action taken now: the exact arrival time if the truck arrived in
        this step, else the step time (it had been waiting for a condition)."""
        return trk.t_ready if trk.t_ready > now - self.step_s else float(now)

    def cycle_s(self, decline: str, elevation: float) -> float:
        """Analytic cycle time ``T`` of spec 2.3 for a haul from ``elevation``, seconds."""
        n = self.sim.trucks_on_decline.get(decline, 1) or 1
        key = (decline, elevation, n)
        value = self._cycle_cache.get(key)
        if value is None:
            cycle = cap.haul_cycle(self.sim.model, self.trucks[0].spec, decline, elevation, n)
            value = cycle.cycle_min * SECONDS_PER_MINUTE
            self._cycle_cache[key] = value
        return value

    def _path(self, stope: Any, ramp: Ramp) -> Polyline:
        """Level drive from the decline access to the loading point at the stope's crosscut."""
        key = (stope.name, ramp.key)
        path = self._paths.get(key)
        if path is None:
            leg = self.sim.geo.stope_route(stope.name, ramp.key).leg("level").points
            path = Polyline(list(reversed(leg[1:])) if len(leg) > 2 else list(reversed(leg)))
            self._paths[key] = path
        return path

    def _pad(self, trk: Truck, now: float) -> bool:
        """Decision point at the ROM pad. Returns True when the truck moved on."""
        sim = self.sim
        ramp = trk.ramp = self.ramps[sim.decline_of[trk.name]]   # re-homed while its decline is closed
        if trk.retiring:
            self._park(trk)
            return False
        if now >= trk.t_fail:
            start = max(trk.t_ready, trk.t_fail)
            trk.phase = P_MAINT
            trk.state = "maintenance"
            trk.waiting = False
            trk.t0 = start
            trk.t_next = start + self.mttr_s
            self.maintenance_s += self.mttr_s
            return True
        if trk.held:
            trk.state = "held_vent"
            return False
        if not sim.productive:
            trk.state = "shift_break"
            return False
        if not sim.vod.admits(trk):        # ventilation on demand: wait until the fans have ramped up
            trk.state = "held_vent"
            return False
        stope = sim.mining.dispatch(trk.payload_t, ramp)
        if stope is None:
            trk.state = "queue_load"       # waits at the pad for broken ore
            return False
        start = self._fresh(trk, now)
        cycle_s = self.cycle_s(ramp.key, stope.elevation)
        if sim.block_end_t - start < self.trip_fraction * cycle_s / self.k_delay:
            trk.state = "shift_break"
            return False
        mean_delay = cycle_s * (1.0 / self.k_delay - 1.0)
        if self._warming or mean_delay <= 0:
            delay = 0.0
        else:
            delay = self._rng_delay[trk.name].expovariate(1.0 / mean_delay)
        trk.delay_half = delay / 2.0
        stope.committed += trk.payload_t
        stope.assigned += 1
        trk.stope = stope
        trk.target = ramp.node_of[stope.elevation]
        trk.path = self._path(stope, ramp)
        trk.cycle_start = start
        trk.phase = P_TO_PORTAL
        trk.state = "surface_haul"
        trk.waiting = False
        trk.t0 = start
        trk.t_next = start + ramp.surface_empty_s
        return True

    def _enter_down(self, trk: Truck, now: float) -> bool:
        ramp = trk.ramp
        i = trk.node
        if ramp.up_count[i] == 0 and ramp.slot[i + 1] is None:
            entered = max(trk.t_ready, ramp.up_clear[i], ramp.slot_free[i + 1])
            if i > 0:
                ramp.slot[i] = None
                ramp.slot_free[i] = entered
            ramp.slot[i + 1] = trk
            ramp.down_count[i] += 1
            if trk.wait_since >= 0.0:
                waited = entered - trk.wait_since
                self.bay_wait_s += waited
                if waited > self.max_bay_wait_s:
                    self.max_bay_wait_s = waited
                trk.wait_since = -1.0
            trk.seg = i
            trk.phase = P_DOWN
            trk.state = "descending"
            trk.waiting = False
            trk.t0 = entered
            trk.t_next = entered + ramp.t_down[i]
            return True
        if trk.wait_since < 0.0:
            trk.wait_since = trk.t_ready
        trk.state = "waiting_bay"
        return False

    def _enter_up(self, trk: Truck, now: float) -> bool:
        ramp = trk.ramp
        s = trk.node - 1
        if ramp.down_count[s] == 0:
            entered = max(trk.t_ready, ramp.down_clear[s])
            self.up_wait_s += entered - trk.t_ready
            if trk.seg >= 0:                 # leaves the segment it climbed before
                ramp.up_count[trk.seg] -= 1
                ramp.up_clear[trk.seg] = entered
            ramp.up_count[s] += 1
            trk.seg = s
            trk.phase = P_UP
            trk.state = "hauling_up"
            trk.waiting = False
            trk.t0 = entered
            trk.t_next = entered + ramp.t_up[s]
            return True
        trk.state = "hauling_up"             # holds on the lane; speed 0
        return False

    def _start_loading(self, trk: Truck, now: float) -> bool:
        stope = trk.stope
        sim = self.sim
        if not stope.open_for_loading():
            self._abort(trk, now)
            return True
        if stope.queue[0] is not trk or stope.loading is not None:
            return False
        lhd = stope.lhd
        if lhd is None or lhd.held or now < stope.reentry_end or sim.in_blast:
            return False
        start = max(trk.t_ready, stope.loader_free_t, stope.reentry_end, sim.blast_end_t)
        self.queue_wait_s += start - trk.t_ready
        stope.loading = trk
        trk.phase = P_LOADING
        trk.state = "loading"
        trk.waiting = False
        trk.t0 = start
        trk.t_next = start + self.load_s
        return True

    def _abort(self, trk: Truck, now: float) -> None:
        """The stope closed (air hold, flood, retired): the truck returns empty."""
        stope = trk.stope
        if trk in stope.queue:
            stope.queue.remove(trk)
        stope.committed -= trk.payload_t
        stope.assigned -= 1
        self.aborted_trips += 1
        start = self._fresh(trk, now)
        trk.load_t = 0.0
        trk.grade = 0.0
        trk.phase = P_LEVEL_OUT
        trk.state = "tram_level"
        trk.waiting = False
        trk.t0 = start
        trk.t_next = start + self.level_s

    def _finish(self, trk: Truck, phase: int) -> None:
        """A timed leg ends at ``trk.t_next``."""
        t = trk.t_next
        trk.t_ready = t
        ramp = trk.ramp
        if phase == P_DOWN:
            i = trk.seg
            ramp.down_count[i] -= 1
            ramp.down_clear[i] = t
            if ramp.up_count[i]:
                self.conflicts += 1
            trk.node = i + 1
            trk.seg = -1
            if trk.node == trk.target:
                ramp.slot[trk.node] = None
                ramp.slot_free[trk.node] = t
                trk.phase = P_LEVEL_IN
                trk.state = "tram_level"
                trk.t0 = t
                trk.t_next = t + self.level_s
            else:
                trk.phase = P_DOWN_WAIT
                trk.waiting = True
        elif phase == P_UP:
            s = trk.seg
            if ramp.down_count[s]:
                self.conflicts += 1
            trk.node = s
            if s == 0:
                ramp.up_count[0] -= 1
                ramp.up_clear[0] = t
                trk.seg = -1
                trk.phase = P_TO_PAD
                trk.state = "surface_haul"
                trk.t0 = t
                trk.t_next = t + (ramp.surface_loaded_s if trk.load_t > 0 else ramp.surface_empty_s)
            else:
                trk.phase = P_UP_WAIT
                trk.waiting = True
        elif phase == P_TO_PORTAL:
            trk.node = 0
            trk.seg = -1
            trk.phase = P_DOWN_WAIT
            trk.waiting = True
        elif phase == P_LEVEL_IN:
            trk.phase = P_QUEUE_DELAY
            trk.state = "queue_load"
            trk.t0 = t
            trk.t_next = t + trk.delay_half
        elif phase == P_QUEUE_DELAY:
            trk.phase = P_QUEUE
            trk.waiting = True
            trk.stope.queue.append(trk)
        elif phase == P_LOADING:
            stope = trk.stope
            amount = min(trk.payload_t, stope.broken)
            stope.broken -= amount
            stope.committed -= trk.payload_t
            stope.assigned -= 1
            stope.queue.remove(trk)
            stope.loading = None
            stope.loader_free_t = t
            stope.mucked_today += amount
            stope.level.ore_today += amount
            if stope.lhd is not None:
                stope.lhd.tonnes_today += amount
            self.sim.ore_loaded_t += amount
            trk.load_t = amount
            trk.grade = stope.grade
            trk.phase = P_LEVEL_OUT
            trk.state = "tram_level"
            trk.t0 = t
            trk.t_next = t + self.level_s
        elif phase == P_LEVEL_OUT:
            trk.node = trk.target
            trk.seg = -1
            trk.phase = P_UP_WAIT
            trk.waiting = True
        elif phase == P_TO_PAD:
            if trk.load_t > 0:
                trk.phase = P_DUMP
                trk.state = "dumping"
                trk.t0 = t
                trk.t_next = t + trk.delay_half + self.dump_s
            else:
                trk.phase = P_PAD
                trk.waiting = True
        elif phase == P_DUMP:
            amount = trk.load_t
            self.sim.on_dump(amount, trk.grade)
            trk.trips_today += 1
            trk.tonnes_today += amount
            ramp.loaded_trips_today += 1
            ramp.ore_today += amount
            ramp.cycles.append(t - trk.cycle_start)
            self.cycle_time_s += t - trk.cycle_start
            self.trips += 1
            trk.load_t = 0.0
            trk.grade = 0.0
            trk.phase = P_PAD
            trk.waiting = True
        elif phase == P_MAINT:
            trk.t_fail = t + self._rng_failure[trk.name].expovariate(1.0 / self.mtbf_s)
            trk.phase = P_PAD
            trk.waiting = True

    # -- reporting ------------------------------------------------------------------------------

    def locate(self, trk: Truck, now: float) -> Tuple[float, float, float, float, float]:
        """Position (x, y, z), chainage on the decline (m, 0 off it) and speed (km/h)."""
        phase = trk.phase
        if phase == P_PARKED or phase == P_MAINT or trk.ramp is None:
            x, y, z = trk.parking
            return x, y, z, 0.0, 0.0
        ramp = trk.ramp
        if phase == P_PAD:
            road = ramp.road
            if trk.state == "held_vent":     # held trucks line up at the portal
                distance = min(road.length, _LINE_SPACING_M * (trk.number + 1))
            else:
                distance = max(0.0, road.length - _LINE_SPACING_M * trk.number)
            x, y, z = road.at_distance(distance)
            return x, y, z, 0.0, 0.0
        span = trk.t_next - trk.t0
        f = (now - trk.t0) / span if span > 0 and trk.t_next < INF else 1.0
        f = 0.0 if f < 0.0 else (1.0 if f > 1.0 else f)
        if phase == P_TO_PORTAL:
            x, y, z = ramp.road.at(1.0 - f)
            return x, y, z, 0.0, self.v_flat_empty
        if phase == P_TO_PAD:
            x, y, z = ramp.road.at(f)
            return x, y, z, 0.0, self.v_flat_loaded if trk.load_t > 0 else self.v_flat_empty
        if phase == P_DUMP:
            x, y, z = ramp.road.points[-1]
            return x, y, z, 0.0, 0.0
        if phase == P_DOWN or phase == P_UP:
            i = trk.seg
            a, b = (i, i + 1) if phase == P_DOWN else (i + 1, i)
            pa, pb = ramp.pos[a], ramp.pos[b]
            ch = ramp.chainage[a] + (ramp.chainage[b] - ramp.chainage[a]) * f
            return (pa[0] + (pb[0] - pa[0]) * f, pa[1] + (pb[1] - pa[1]) * f, pa[2] + (pb[2] - pa[2]) * f,
                    ch, self.v_down if phase == P_DOWN else self.v_up)
        if phase == P_DOWN_WAIT or phase == P_UP_WAIT:
            x, y, z = ramp.pos[trk.node]
            return x, y, z, ramp.chainage[trk.node], 0.0
        path = trk.path
        if phase == P_LEVEL_IN:
            x, y, z = path.at(f)
            return x, y, z, 0.0, self.v_flat_empty
        if phase == P_LEVEL_OUT:
            x, y, z = path.at(1.0 - f)
            return x, y, z, 0.0, self.v_flat_loaded if trk.load_t > 0 else self.v_flat_empty
        x, y, z = path.points[-1]            # queueing or loading at the stope
        return x, y, z, 0.0, 0.0

    def on_ramp(self, ramp: Ramp) -> int:
        return sum(1 for trk in self.active if trk.ramp is ramp and trk.phase in _ON_RAMP
                   and not (trk.phase == P_DOWN_WAIT and trk.node == 0))

    def waiting_in_bays(self, ramp: Ramp) -> int:
        return sum(1 for trk in self.active if trk.ramp is ramp and trk.state == "waiting_bay")

    def running_kw(self) -> float:
        return sum(trk.engine_kw for trk in self.active if trk.phase not in _ENGINE_OFF)

    def kw_on_levels(self, kw: Dict[str, float]) -> None:
        for trk in self.active:
            if trk.phase in _ON_LEVEL:
                name = trk.stope.level.name
                kw[name] = kw.get(name, 0.0) + trk.engine_kw

    def ore_on_trucks(self) -> float:
        return sum(trk.load_t for trk in self.trucks)

    def longest_bay_wait_s(self, now: float) -> float:
        """Longest wait in a bay or at a portal so far, including waits still running."""
        longest = self.max_bay_wait_s
        for trk in self.active:
            if trk.wait_since >= 0.0 and now - trk.wait_since > longest:
                longest = now - trk.wait_since
        return longest
