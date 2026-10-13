"""Stopes, drill rigs and LHDs (spec 2.5).

A producing stope prepares one ring at a time: a rig drills it (``stope.drilling_shifts``
productive shifts), it is charged (``stope.charging_shifts``), and it is fired in a blast window.
Firing needs three things: the ring is charged, ``stope.cycle_shifts`` shifts have passed since the
stope's last blast (this keeps the stoping capacity at the analytic 255.875 kt/yr per stope), and
no more than ``stope.blast_max_broken_rings`` of broken ore is left in the stope. The broken ore is
the buffer between stoping and haulage: when trucks are the slower side the stock holds the next
blast back, when stopes are the slower side trucks wait for ore.

With ``stope.ring_prep_during_mucking`` = 1 the next ring is prepared while the previous one is
mucked; with 0 preparation starts only after the broken ore is hauled away (the strictly
sequential cycle).
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

from .. import capacity as cap
from .traffic import Polyline

SECONDS_PER_HOUR = 3600.0
SECONDS_PER_DAY = 86400.0
PERCENT = 100.0
MS_PER_KMH = 1000.0 / 3600.0

# Status of a stope outside and inside the producing set; equal to the state tokens of spec 2.5.
PLANNED, PREPARATION, STANDBY, PRODUCING, BACKFILLING = "planned", "preparation", "standby", "producing", "backfilling"

# Ring preparation of a producing stope.
R_WAIT, R_DRILL, R_CHARGE, R_READY, R_DONE = range(5)

# Rig phases.
RIG_PARKED, RIG_IDLE, RIG_TRAM, RIG_DRILL = range(4)


class Level:
    __slots__ = ("name", "elevation", "role", "ore_today", "flooded")

    def __init__(self, name: str, elevation: float, role: str):
        self.name = name
        self.elevation = elevation
        self.role = role
        self.ore_today = 0.0
        self.flooded = False


class Stope:
    __slots__ = ("name", "order", "level", "elevation", "grade_base", "grade", "ore_initial", "ore_remaining",
                 "broken", "committed", "assigned", "block_no", "status", "timer", "timer_span", "ring",
                 "drill_s", "charge_s", "last_blast_w", "reentry_end", "lhd", "rig", "vent_hold", "queued",
                 "queue", "loading", "loader_free_t", "mucked_today", "ramps", "draw_point", "junction",
                 "anchor", "min_payload")

    def __init__(self, name: str, level: Level, grade: float, ore_t: float, status: str, block_no: int):
        self.name = name
        self.order = -1                 # place in the activation order; -1: cannot produce
        self.level = level
        self.elevation = level.elevation
        self.grade_base = grade
        self.grade = grade
        self.ore_initial = ore_t
        self.ore_remaining = ore_t
        self.broken = 0.0
        self.committed = 0.0            # broken ore promised to trucks on their way
        self.assigned = 0               # trucks on their way or loading
        self.block_no = block_no
        self.status = status
        self.timer = -1.0               # end of backfilling or preparation
        self.timer_span = 0.0
        self.ring = R_WAIT
        self.drill_s = 0.0
        self.charge_s = 0.0
        self.last_blast_w = 0
        self.reentry_end = float("-inf")
        self.lhd: Optional["Lhd"] = None
        self.rig: Optional["Rig"] = None
        self.vent_hold = False
        self.queued = False
        self.queue: List[Any] = []
        self.loading: Any = None
        self.loader_free_t = float("-inf")
        self.mucked_today = 0.0
        self.ramps: Tuple[str, ...] = ()
        self.draw_point = (0.0, 0.0, 0.0)
        self.junction = (0.0, 0.0, 0.0)
        self.anchor = (0.0, 0.0, 0.0)
        self.min_payload = 0.0

    def suspended(self) -> bool:
        return self.vent_hold or self.level.flooded

    def open_for_loading(self) -> bool:
        return self.status == PRODUCING and not self.vent_hold and not self.level.flooded


class Lhd:
    __slots__ = ("name", "number", "engine_kw", "in_service", "held", "stope", "tonnes_today", "parking")

    def __init__(self, spec: cap.Lhd, parking: Tuple[float, float, float]):
        self.name = spec.name
        self.number = spec.number
        self.engine_kw = spec.engine_kw
        self.in_service = False
        self.held = False
        self.stope: Optional[Stope] = None
        self.tonnes_today = 0.0
        self.parking = parking


class Rig:
    __slots__ = ("name", "number", "in_service", "phase", "stope", "at", "route", "tram_total", "tram_left",
                 "metres_today", "parking")

    def __init__(self, name: str, number: int, parking: Tuple[float, float, float]):
        self.name = name
        self.number = number
        self.in_service = False
        self.phase = RIG_PARKED
        self.stope: Optional[Stope] = None
        self.at: Optional[Stope] = None     # stope the rig stands at
        self.route: Optional[Polyline] = None
        self.tram_total = 0.0
        self.tram_left = 0.0
        self.metres_today = 0.0
        self.parking = parking


class Mining:
    """All stopes, LHDs and rigs. ``sim`` is the owning ``Simulator``."""

    def __init__(self, sim: Any):
        self.sim = sim
        p, model, geo = sim.p, sim.model, sim.geo
        productive_shift_s = p("regime.productive_h") * SECONDS_PER_HOUR
        self.productive_shift_s = productive_shift_s
        self.blast_t = float(p("stope.blast_t"))
        self.drill_total_s = p("stope.drilling_shifts") * productive_shift_s
        self.charge_total_s = p("stope.charging_shifts") * productive_shift_s
        self.cycle_shifts = int(p("stope.cycle_shifts"))
        self.reentry_s = p("vent.reentry_min") * 60.0
        self.backfill_s = p("stope.backfill_days") * SECONDS_PER_DAY
        self.preparation_s = p("stope.preparation_days") * SECONDS_PER_DAY
        self.max_broken_t = p("stope.blast_max_broken_rings") * self.blast_t
        self.prep_during_mucking = bool(p("stope.ring_prep_during_mucking"))
        self.start_broken_t = p("stope.start_broken_rings") * self.blast_t
        self.metres_per_s = p("rig.drill_m_per_ring") / self.drill_total_s
        self.rig_speed = p("rig.tram_kmh") * MS_PER_KMH
        self.shuttle_s = p("lhd.shuttle_period_min") * 60.0
        self.smallest_payload = min(trk.payload_t for trk in model.trucks)

        self.levels: Dict[str, Level] = {lv.name: Level(lv.name, lv.elevation_m, lv.role) for lv in model.levels}
        order = {st.name: i for i, st in enumerate(model.stopes)}
        self.stopes: List[Stope] = []
        for name, thing in sim.things.items():
            if thing["kind"] != "stope":
                continue
            attrs, feats = thing["attributes"], thing["features"]
            level = self.levels[attrs["link_level"].split(":", 1)[-1]]
            status = feats["state"] if feats["state"] in (PLANNED, PREPARATION) else STANDBY
            stope = Stope(name, level, float(attrs["grade_gpt"]), float(attrs["ore_initial_t"]), status,
                          int(feats["block_no"]))
            stope.order = order.get(name, -1)
            entry = geo.obj(name)
            stope.draw_point = tuple(float(c) for c in entry["draw_point"])
            stope.anchor = tuple(float(c) for c in entry["anchor"])
            stope.junction = (stope.draw_point[0], stope.draw_point[1], stope.draw_point[2])
            reach = []
            for key in model.declines:
                ramp = sim.haul.ramps[key]
                if f"{geo.namespace}:{ramp.name}" in entry["routes"] and ramp.reaches(level.elevation):
                    reach.append(key)
                    leg = geo.stope_route(name, key).leg("level").points
                    if len(leg) > 1:
                        stope.junction = tuple(float(c) for c in leg[1])
            stope.ramps = tuple(reach)
            stope.min_payload = self.smallest_payload
            self.stopes.append(stope)
        self.by_name: Dict[str, Stope] = {st.name: st for st in self.stopes}
        self.candidates: List[Stope] = sorted((st for st in self.stopes if st.order >= 0), key=lambda st: st.order)
        self.producing: List[Stope] = []
        self.lhds: List[Lhd] = [Lhd(spec, geo.position(spec.name)) for spec in model.lhds]
        self.rigs: List[Rig] = [Rig(name, i + 1, geo.position(name)) for i, name in enumerate(model.rigs)]
        self.rig_queue: List[Stope] = []
        self.target_n = 0
        self.blasts = 0
        self.blocks_mined = 0

    # -- configuration --------------------------------------------------------------------------

    def configure(self, n_producing: int, lhd_names: Iterable[str], n_rigs: int, now: float, first: bool) -> None:
        """Set the producing set size and the LHDs and rigs in service (knob ``m_stopes``)."""
        wanted = set(lhd_names)
        for lhd in self.lhds:
            if lhd.name in wanted:
                lhd.in_service = True
            elif lhd.in_service:
                lhd.in_service = False
                lhd.held = False
                if lhd.stope is not None:
                    lhd.stope.lhd = None
                    lhd.stope.vent_hold = False
                    lhd.stope = None
        for rig in self.rigs:
            if rig.number <= n_rigs:
                if not rig.in_service:
                    rig.in_service = True
                    rig.phase = RIG_IDLE
            elif rig.in_service:
                self._release_rig(rig)
                rig.in_service = False
                rig.phase = RIG_PARKED
                rig.at = None
        self.target_n = n_producing
        while len(self.producing) > self.target_n:
            self._retire(max(self.producing, key=lambda st: st.order))
        self._fill_set(now)
        if first:
            self._warm_start()
        self._pair_lhds()

    def _warm_start(self) -> None:
        """Steady operation at the epoch: one ring of broken ore in every producing stope and the
        rings staggered one shift apart. The next ring of each stope is as far prepared as the
        whole shifts since its last blast and the part of the running shift already worked allow."""
        rigs = [rig for rig in self.rigs if rig.in_service]
        prep_total = self.drill_total_s + self.charge_total_s
        worked_s = float(self.sim.cal.worked_s(self.sim.cal.index(0))[1])
        for i, stope in enumerate(self.producing):
            shifts_ago = i % self.cycle_shifts
            stope.last_blast_w = -shifts_ago
            stope.broken = min(self.start_broken_t, stope.ore_remaining)
            stope.ore_remaining -= stope.broken
            done = shifts_ago * self.productive_shift_s + worked_s
            if done >= prep_total:
                stope.ring, stope.drill_s, stope.charge_s = R_READY, self.drill_total_s, self.charge_total_s
            elif done >= self.drill_total_s:
                stope.ring, stope.drill_s, stope.charge_s = R_CHARGE, self.drill_total_s, done - self.drill_total_s
            else:
                stope.ring, stope.drill_s, stope.charge_s = R_WAIT, done, 0.0
                if rigs:
                    rig = rigs.pop(0)
                    rig.stope = rig.at = stope
                    rig.phase = RIG_DRILL
                    stope.rig = rig
                    stope.ring = R_DRILL
        self.sim.ore_broken_start_t = sum(st.broken for st in self.stopes)

    def _fill_set(self, now: float) -> None:
        """Bring stopes into the producing set in the activation order of spec 2.5."""
        changed = False
        while len(self.producing) < self.target_n:
            stope = next((st for st in self.candidates if st.status == STANDBY), None)
            if stope is None:           # then the stopes of the level under development
                stope = next((st for st in self.candidates if st.status == PREPARATION and st.timer < 0), None)
            if stope is None:
                break
            stope.status = PRODUCING
            stope.ring = R_WAIT if stope.ore_remaining > 0 else R_DONE
            stope.drill_s = stope.charge_s = 0.0
            stope.queued = False
            stope.last_blast_w = self.sim.blast_w - self.cycle_shifts
            self.producing.append(stope)
            changed = True
        if changed:
            self.producing.sort(key=lambda st: st.order)

    def _retire(self, stope: Stope, status: str = STANDBY) -> None:
        """Take a stope out of the producing set; its broken ore stays where it is."""
        self.producing.remove(stope)
        stope.status = status
        if stope.rig is not None:
            self._release_rig(stope.rig)
        if stope in self.rig_queue:
            self.rig_queue.remove(stope)
        stope.queued = False
        stope.ring = R_WAIT
        stope.drill_s = stope.charge_s = 0.0
        stope.vent_hold = False
        if stope.lhd is not None:
            stope.lhd.stope = None
            stope.lhd = None

    def _release_rig(self, rig: Rig) -> None:
        stope = rig.stope
        if stope is not None:
            stope.rig = None
            if stope.ring == R_DRILL:
                stope.ring = R_WAIT
            rig.stope = None
        if rig.phase in (RIG_TRAM, RIG_DRILL):
            rig.phase = RIG_IDLE

    def _pair_lhds(self) -> None:
        """One LHD per producing stope; an LHD keeps its stope while both stay in service."""
        free = [lhd for lhd in self.lhds if lhd.in_service and lhd.stope is None]
        for stope in self.producing:
            if stope.lhd is None and free:
                lhd = free.pop(0)
                lhd.stope = stope
                stope.lhd = lhd
            if stope.lhd is not None:
                stope.vent_hold = stope.lhd.held

    def set_min_payloads(self, payload_by_decline: Dict[str, float]) -> None:
        """Smallest truck in service that can reach each stope: ore below it counts as hauled away."""
        for stope in self.stopes:
            reachable = [payload_by_decline[key] for key in stope.ramps if key in payload_by_decline]
            stope.min_payload = min(reachable) if reachable else self.smallest_payload

    def rescale_grades(self, grade_gpt: float) -> None:
        """Grades of the producing stopes are scaled so that their mean equals the feed grade
        (decision 9.3); the other stopes keep the ratio of spec 3.1."""
        model = self.sim.model
        base = model.p("plant.grade_base")
        for stope in self.stopes:
            stope.grade = stope.grade_base * grade_gpt / base
        if self.producing:
            state = cap.State(producing_set=tuple(st.name for st in self.producing))
            unscaled_mean = cap.stopes(model, state).mean_grade_gpt
            if unscaled_mean > 0:
                for stope in self.producing:
                    stope.grade = stope.grade_base * grade_gpt / unscaled_mean

    def set_held_lhds(self, names: Iterable[str]) -> None:
        held = set(names)
        for lhd in self.lhds:
            lhd.held = lhd.in_service and lhd.name in held
            if lhd.stope is not None:
                self._suspend(lhd.stope, vent_hold=lhd.held)

    def set_flooded(self, level_names: Iterable[str]) -> None:
        flooded = set(level_names)
        for level in self.levels.values():
            level.flooded = level.name in flooded
        for stope in self.producing:
            if stope.level.flooded:
                self._suspend(stope, vent_hold=stope.vent_hold)

    def _suspend(self, stope: Stope, vent_hold: bool) -> None:
        stope.vent_hold = vent_hold
        if stope.suspended():
            if stope.rig is not None:
                self._release_rig(stope.rig)
            if stope in self.rig_queue:
                self.rig_queue.remove(stope)
            stope.queued = False

    # -- dispatch -------------------------------------------------------------------------------

    def dispatch(self, payload_t: float, ramp: Any) -> Optional[Stope]:
        """Stope with the most free broken ore per truck assigned, among those the decline reaches."""
        best = None
        best_score = 0.0
        key = ramp.key
        for stope in self.producing:
            if stope.vent_hold or stope.level.flooded or stope.lhd is None or key not in stope.ramps:
                continue
            free = stope.broken - stope.committed
            if free < payload_t:
                continue
            score = free / (stope.assigned + 1)
            if score > best_score:
                best, best_score = stope, score
        return best

    # -- time -----------------------------------------------------------------------------------

    def minute(self, now: float, dt: float, productive: bool) -> None:
        if productive:
            for rig in self.rigs:
                phase = rig.phase
                if phase == RIG_TRAM:
                    rig.tram_left -= dt
                    if rig.tram_left <= 0.0:
                        rig.phase = RIG_DRILL
                        rig.at = rig.stope
                elif phase == RIG_DRILL:
                    stope = rig.stope
                    stope.drill_s += dt
                    rig.metres_today += self.metres_per_s * dt
                    if stope.drill_s >= self.drill_total_s:
                        stope.drill_s = self.drill_total_s
                        stope.ring = R_CHARGE
                        stope.rig = None
                        rig.stope = None
                        rig.phase = RIG_IDLE
            for stope in self.producing:
                if stope.ring == R_CHARGE and not stope.vent_hold and not stope.level.flooded:
                    stope.charge_s += dt
                    if stope.charge_s >= self.charge_total_s:
                        stope.charge_s = self.charge_total_s
                        stope.ring = R_READY
        depleted = None
        for stope in self.producing:
            if stope.ring == R_WAIT:
                if (not stope.queued and not stope.vent_hold and not stope.level.flooded
                        and (self.prep_during_mucking or stope.broken < stope.min_payload)):
                    self.rig_queue.append(stope)
                    stope.queued = True
            elif (stope.ring == R_DONE and stope.assigned == 0 and stope.broken < stope.min_payload
                  and now >= stope.reentry_end):
                depleted = stope
        if self.rig_queue:
            for rig in self.rigs:
                if rig.phase == RIG_IDLE and self.rig_queue:
                    self._send_rig(rig, self.rig_queue.pop(0))
        if depleted is not None:
            self._retire(depleted, BACKFILLING)
            depleted.timer = now + self.backfill_s
            depleted.timer_span = self.backfill_s
            self.blocks_mined += 1
            self._after_set_change(now)
        for stope in self.candidates:
            if stope.timer >= 0.0 and now >= stope.timer:
                if stope.status == BACKFILLING:
                    stope.status = PREPARATION
                    stope.timer = now + self.preparation_s
                    stope.timer_span = self.preparation_s
                elif stope.status == PREPARATION:     # the next block of the stope
                    stope.status = STANDBY
                    stope.timer = -1.0
                    stope.block_no += 1
                    stope.ore_remaining = stope.ore_initial
                    self._after_set_change(now)

    def _after_set_change(self, now: float) -> None:
        self._fill_set(now)
        self._pair_lhds()
        self.rescale_grades(self.sim.grade_gpt)
        self.sim.on_fleet_change()

    def _send_rig(self, rig: Rig, stope: Stope) -> None:
        stope.queued = False
        stope.rig = rig
        stope.ring = R_DRILL
        rig.stope = stope
        origin = rig.at
        if origin is stope:
            rig.phase = RIG_DRILL
            return
        geo = self.sim.geo
        if origin is None:
            points = [rig.parking] + list(geo.stope_route(stope.name).reversed().points) + [stope.anchor]
        else:
            points = [origin.anchor] + list(geo.stopes_route(origin.name, stope.name).points) + [stope.anchor]
        rig.route = Polyline(points)
        rig.tram_total = rig.route.length / self.rig_speed
        rig.tram_left = rig.tram_total
        rig.phase = RIG_TRAM

    def blast(self, now: float, window: int) -> List[str]:
        """Fire every ring that is ready. Returns the names of the stopes fired."""
        fired = []
        for stope in self.producing:
            if (stope.ring == R_READY and not stope.vent_hold and not stope.level.flooded
                    and window - stope.last_blast_w >= self.cycle_shifts
                    and stope.broken < self.max_broken_t + stope.min_payload
                    and not stope.queue and stope.loading is None):
                amount = min(self.blast_t, stope.ore_remaining)
                stope.ore_remaining -= amount
                stope.broken += amount
                stope.last_blast_w = window
                stope.reentry_end = now + self.reentry_s
                stope.drill_s = stope.charge_s = 0.0
                stope.ring = R_WAIT if stope.ore_remaining > 0.0 else R_DONE
                self.sim.ore_blasted_t += amount
                self.blasts += 1
                fired.append(stope.name)
        return fired

    def reset_day(self) -> None:
        for stope in self.stopes:
            stope.mucked_today = 0.0
        for level in self.levels.values():
            level.ore_today = 0.0
        for lhd in self.lhds:
            lhd.tonnes_today = 0.0
        for rig in self.rigs:
            rig.metres_today = 0.0

    # -- reporting ------------------------------------------------------------------------------

    def stope_state(self, stope: Stope, now: float) -> str:
        if stope.level.flooded and stope.status != PLANNED:
            return "flooded"
        if stope.status != PRODUCING:
            return stope.status
        if stope.vent_hold:
            return "standby"
        if now < stope.reentry_end:
            return "ventilating"
        if stope.ring == R_DRILL and stope.rig is not None and stope.rig.phase == RIG_DRILL:
            return "drilling"
        if stope.ring == R_CHARGE:
            return "charging"
        if stope.broken >= stope.min_payload:
            return "mucking"
        if stope.ring == R_READY:
            return "awaiting_blast"
        return "drilling" if stope.ring != R_DONE else "mucking"

    def stope_features(self, stope: Stope, now: float) -> Dict[str, Any]:
        if stope.ring in (R_CHARGE, R_READY):
            drilled = PERCENT
        else:
            drilled = stope.drill_s / self.drill_total_s * PERCENT
        if stope.status == BACKFILLING:
            backfill = (1.0 - (stope.timer - now) / stope.timer_span) * PERCENT
        elif stope.status == PREPARATION and stope.timer >= 0.0:
            backfill = PERCENT
        else:
            backfill = 0.0
        return {
            "state": self.stope_state(stope, now),
            "ore_remaining_t": round(stope.ore_remaining, 1),
            "broken_ore_t": round(stope.broken, 1),
            "drilled_pct": round(drilled if stope.status == PRODUCING else 0.0, 1),
            "backfill_pct": round(min(PERCENT, max(0.0, backfill)), 1),
            "grade": round(stope.grade, 3),
            "mucked_today_t": round(stope.mucked_today, 1),
            "block_no": float(stope.block_no),
        }

    def lhd_state(self, lhd: Lhd, now: float, productive: bool) -> str:
        if not lhd.in_service:
            return "parked"
        if lhd.held:
            return "standby_vent"
        stope = lhd.stope
        if stope is not None and stope.loading is not None:
            return "loading_truck"
        if not productive:
            return "shift_break"
        if (stope is not None and not stope.level.flooded and stope.broken >= stope.min_payload
                and now >= stope.reentry_end):
            return "mucking"
        return "idle"

    def lhd_features(self, lhd: Lhd, now: float, productive: bool) -> Dict[str, Any]:
        state = self.lhd_state(lhd, now, productive)
        stope = lhd.stope
        if stope is None or state == "parked":
            x, y, z = lhd.parking
        elif state == "mucking":            # runs between the draw point and the drive
            phase = (now % self.shuttle_s) / self.shuttle_s
            f = 2.0 * phase if phase < 0.5 else 2.0 * (1.0 - phase)
            a, b = stope.draw_point, stope.junction
            x, y, z = a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f
        elif state == "loading_truck":
            x, y, z = stope.junction
        else:
            x, y, z = stope.draw_point
        return {"state": state, "stope": stope.name if stope is not None and state != "parked" else "none",
                "tonnes_today": round(lhd.tonnes_today, 1),
                "pos_x": round(x, 1), "pos_y": round(y, 1), "pos_z": round(z, 1)}

    def rig_features(self, rig: Rig, productive: bool) -> Dict[str, Any]:
        if not rig.in_service:
            state = "parked"
        elif not productive:
            state = "shift_break"
        elif rig.phase == RIG_DRILL:
            state = "drilling"
        else:
            state = "tramming"              # on its way, or standing by for the next ring
        if rig.phase == RIG_TRAM and rig.route is not None and rig.tram_total > 0:
            x, y, z = rig.route.at(1.0 - max(0.0, rig.tram_left) / rig.tram_total)
        elif rig.at is not None and rig.in_service:
            x, y, z = rig.at.anchor
        else:
            x, y, z = rig.parking
        target = rig.stope if rig.stope is not None else None
        return {"state": state, "stope": target.name if target is not None and rig.in_service else "none",
                "metres_today": round(rig.metres_today, 1),
                "pos_x": round(x, 1), "pos_y": round(y, 1), "pos_z": round(z, 1)}

    def running_lhd_kw(self, now: float, productive: bool) -> float:
        return sum(lhd.engine_kw for lhd in self.lhds
                   if self.lhd_state(lhd, now, productive) in ("mucking", "loading_truck"))

    def kw_on_levels(self, kw: Dict[str, float], now: float, productive: bool) -> None:
        for lhd in self.lhds:
            if lhd.stope is not None and self.lhd_state(lhd, now, productive) in ("mucking", "loading_truck"):
                name = lhd.stope.level.name
                kw[name] = kw.get(name, 0.0) + lhd.engine_kw

    def broken_ore_t(self) -> float:
        return sum(stope.broken for stope in self.stopes)
