"""Ventilation on demand (spec 3.5): the main fans follow the air demand of the units in work.

Every simulated minute the controller works out which diesel units are in work and what air
they need by the norm of the hold rule (``capacity.air_demand_m3s``: ``vent.q_base`` plus
``vent.q_diesel`` per kW), adds the margin ``vod.margin_pct`` and sets the total duty of the fans
in service between their lowest duty (``duty_min_m3s``) and their design duty (``duty_m3s``,
the supply of the hold rule and of the advisor, which ventilation on demand never exceeds):

* Units in work. During a productive block every truck and LHD in service that is not held for
  air and not under repair is in work (a truck waiting at the ROM pad for ore can leave any
  moment, so its air is reserved). Outside the productive blocks only the units still out on a
  trip and an LHD loading a truck are.
* Raising. A higher setpoint is approached at once, but no fan changes its flow by more than
  ``vod.ramp_pct_per_min`` of its design duty per minute. ``vod.pre_vent_min`` before a
  productive block starts the setpoint already covers every unit that will work in it.
* Admission. A unit is admitted to work only when the air delivered covers it: the demand of
  the admitted units never exceeds the delivered air. A truck that does not fit waits at the
  ROM pad (``held_vent``) and an LHD at its stope until the fans have ramped up; with the
  pre-ventilation this happens only when units are added during a block (a truck back from
  repair, a scenario change). The hold rule of spec 2.6, on the design duty, stays the last
  resort.
* Lowering. The setpoint comes down only when the demand has stayed below the delivered air
  for ``vod.min_on_min`` minutes (minimum on-time), and then at the ramp rate.
* Several fans: all run at the same fraction of their design duty; a fan at its lowest duty
  stays there and the others take the rest (``capacity.vod_split``).

Power follows the fan laws on a fixed system curve: pressure with the square, power with the
cube of the flow (``capacity.fan_power_at_kw``). The energy of the fans and the saving against
the fans at their design duty are integrated per minute: since 08:00 (``today``), since the
start of the shift (``shift``) and over the last 24 hours (``day``), the saving also in tenge
at ``vod.tariff_kzt_kwh``. With the knob ``vod_enabled`` at 0 the fans run at their design duty,
the saving is 0, and the units in work are admitted against that supply.

``FanControl`` is the control law alone (setpoint, minimum on-time, ramp); ``Vod`` adds the units,
the admission and the energy account of the simulator. The Stand's fixture engine runs
``FanControl`` over a day profile of the demand.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from .. import capacity as cap
from .timebase import Rolling, SECONDS_PER_DAY, SECONDS_PER_HOUR, bucket_for
from .traffic import P_MAINT, P_PAD, P_PARKED

PERCENT = 100.0
EPS = 1e-6
#: Flows closer than this (m3/s) count as equal when the state is named.
STATE_TOLERANCE_M3S = 0.05

#: ``mine.vod_state``: switched off (design duty), following the demand, raising ahead of the
#: demand, at the design duty because the demand needs it.
OFF, DEMAND, RAMP, FULL = "off", "demand", "ramp", "full"


class FanControl:
    """The control law of spec 3.5 for a set of running fans: setpoint from the demand, minimum
    on-time before it comes down, ramp-rate limit per fan. ``model`` is a ``capacity.Model``."""

    def __init__(self, model: cap.Model):
        p = model.p
        self.model = model
        self.ramp_share = float(p("vod.ramp_pct_per_min")) / PERCENT
        self.min_on_s = float(p("vod.min_on_min")) * 60.0
        self.enabled = True
        self.fans: Tuple[str, ...] = ()
        #: Flow of each running fan now (m3/s) and the setpoint it moves to.
        self.flow: Dict[str, float] = {}
        self.setpoint: Dict[str, float] = {}
        self.target = 0.0                  # total setpoint for the demand, m3/s
        self.state = FULL
        self.below_since: Optional[float] = None
        self._split_cache: Dict[Tuple[Tuple[str, ...], float], Dict[str, float]] = {}

    def configure(self, enabled: bool, fans: Iterable[str], first: bool = False) -> None:
        """The switch and the fans in service. A fan that stops drops out at once; a fan that
        starts takes its share of the delivered air. Switched off (or at ``first``), every fan
        runs at its design duty; switched on, the fans start from the air they deliver."""
        fans = tuple(fans)
        total = sum(self.flow.get(name, 0.0) for name in fans)
        changed = fans != self.fans or bool(enabled) != self.enabled
        self.enabled = bool(enabled)
        self.fans = fans
        self._split_cache.clear()
        if not self.enabled or first:
            self.flow = {name: self.model.fans[name].duty_m3s for name in fans}
        elif changed:
            self.flow = dict(self.split(total))
        if changed or first:
            self.setpoint = dict(self.flow)
            self.target = self.delivered()
            self.below_since = None
            self.state = (OFF if not self.enabled
                          else FULL if self.target >= self.capacity() - STATE_TOLERANCE_M3S else DEMAND)

    def capacity(self) -> float:
        """The design duty of the fans in service: the supply of the hold rule."""
        return sum(self.model.fans[name].duty_m3s for name in self.fans)

    def delivered(self) -> float:
        """The air the fans deliver now, m3/s."""
        return sum(self.flow.values())

    def split(self, total: float) -> Dict[str, float]:
        key = (self.fans, round(total, 3))
        split = self._split_cache.get(key)
        if split is None:
            if len(self._split_cache) > 4096:
                self._split_cache.clear()
            split = self._split_cache[key] = cap.vod_split(self.model, total, self.fans)
        return split

    def step(self, t: float, need_m3s: float, dt_s: float) -> None:
        """One step of ``dt_s`` at simulated second ``t`` for an air demand of ``need_m3s``."""
        model = self.model
        capacity = self.capacity()
        if not self.enabled:
            self.flow = {name: model.fans[name].duty_m3s for name in self.fans}
            self.setpoint = dict(self.flow)
            self.target = capacity
            self.state = OFF
            return
        target = cap.vod_setpoint_m3s(model, need_m3s, self.fans)
        now = self.delivered()
        if target >= now - EPS:
            self.below_since = None
            goal = target
        else:
            if self.below_since is None:
                self.below_since = t
            # minimum on-time: hold the delivered air until the demand has stayed lower
            goal = target if t - self.below_since >= self.min_on_s else now
        self.target = target
        self.setpoint = dict(self.split(goal))
        for name in self.fans:
            fan = model.fans[name]
            limit = self.ramp_share * fan.duty_m3s * dt_s / 60.0
            flow = self.flow.get(name, 0.0)
            aim = self.setpoint[name]
            self.flow[name] = min(aim, flow + limit) if aim >= flow else max(aim, flow - limit)
        delivered = self.delivered()
        if delivered < goal - STATE_TOLERANCE_M3S:
            self.state = RAMP
        elif delivered >= capacity - STATE_TOLERANCE_M3S and target >= capacity - STATE_TOLERANCE_M3S:
            self.state = FULL
        else:
            self.state = DEMAND

    def power_kw(self) -> float:
        """Shaft power of the running fans now (cube law)."""
        return sum(cap.fan_power_at_kw(self.model, self.model.fans[name], flow) for name, flow in self.flow.items())

    def fixed_power_kw(self) -> float:
        """Shaft power of the same fans at their design duty."""
        return sum(cap.fan_power_at_kw(self.model, self.model.fans[name], self.model.fans[name].duty_m3s)
                   for name in self.fans)

    def fan(self, name: str) -> Tuple[float, float, float, float]:
        """(flow, setpoint, pressure, power) of a running fan."""
        fan = self.model.fans[name]
        flow = self.flow.get(name, 0.0)
        return (flow, self.setpoint.get(name, flow), cap.fan_pressure_pa(fan, flow),
                cap.fan_power_at_kw(self.model, fan, flow))


class Vod(FanControl):
    """The controller of the main fans in the simulator and its energy account. ``sim`` is the
    ``Simulator``."""

    def __init__(self, sim: Any):
        super().__init__(sim.model)
        p = sim.p
        self.sim = sim
        self.pre_vent_s = float(p("vod.pre_vent_min")) * 60.0
        self.tariff = float(p("vod.tariff_kzt_kwh"))
        # Units: names wanting work, admitted ones, their demand.
        self.wanted_kw = 0.0
        self.admitted: Set[str] = set()
        self.admitted_kw = 0.0
        self.waiting_lhds: Tuple[str, ...] = ()
        self.waiting = 0
        self.demand = 0.0                  # demand of the admitted units, m3/s
        self.wanted_demand = 0.0           # demand of every unit wanting work, m3/s
        # Day starts of the productive blocks (seconds after the start of shift A).
        self.block_starts = tuple(start for start, _ in sim.cal.blocks)
        # Energy account, kWh.
        self.energy_today = self.fixed_today = 0.0
        self.energy_shift = self.fixed_shift = 0.0
        self.energy_total = self.fixed_total = 0.0
        # 24-hour windows, started on the first configure() as if the day before the epoch had
        # run at the design duty (no saving yet).
        self.r_energy: Optional[Rolling] = None
        self.r_fixed: Optional[Rolling] = None
        self._shift_token = sim.shift
        # The 7-day check of spec 3.5: the lowest air margin over the requirement seen so far.
        self.min_margin_m3s = float("inf")
        self.minutes = 0

    def configure(self, enabled: bool, fans: Iterable[str], first: bool = False) -> None:
        first = first or self.r_energy is None
        super().configure(enabled, fans, first)
        if self.r_energy is None:
            day_s = float(SECONDS_PER_DAY)
            fixed = self.fixed_power_kw()
            self.r_energy = Rolling(day_s, bucket_for(day_s), fixed)
            self.r_fixed = Rolling(day_s, bucket_for(day_s), fixed)

    # -- units ----------------------------------------------------------------------------------

    def _units(self, productive: bool) -> Tuple[List[Any], List[Any], float]:
        """(trucks wanting work, LHDs wanting work, kW of every unit that will work in the next
        productive block). Units held by the hold rule are not counted."""
        sim = self.sim
        trucks, lhds = [], []
        planned_kw = 0.0
        for truck in sim.haul.trucks:
            if not truck.in_service or truck.held:
                continue
            phase = truck.phase
            if phase == P_PARKED or phase == P_MAINT:
                continue
            if not (truck.retiring and phase == P_PAD):
                planned_kw += truck.engine_kw
            if phase != P_PAD or (productive and not truck.retiring):
                trucks.append(truck)
        held = set(sim.held_lhds)
        for lhd in sim.mining.lhds:
            if not lhd.in_service or lhd.name in held:
                continue
            planned_kw += lhd.engine_kw
            stope = lhd.stope
            loading = stope is not None and stope.loading is not None
            if productive or loading:
                lhds.append(lhd)
        return trucks, lhds, planned_kw

    def _admit(self, trucks: List[Any], lhds: List[Any], supply: float) -> None:
        """Admit units while the delivered air covers them: units out on a trip first (they are
        underground already), then the units admitted before, then the LHDs and the trucks at the
        pad by number."""
        demand = cap.air_demand_m3s
        kw = 0.0
        admitted: Set[str] = set()
        rest = []
        for truck in trucks:
            if truck.phase != P_PAD:
                admitted.add(truck.name)
                kw += truck.engine_kw
            else:
                rest.append(truck)
        previous = self.admitted
        order = ([u for u in lhds if u.name in previous] + [t for t in rest if t.name in previous]
                 + sorted((u for u in lhds if u.name not in previous), key=lambda u: u.number)
                 + sorted((t for t in rest if t.name not in previous), key=lambda t: t.number))
        lhd_names = {u.name for u in lhds}
        waiting_lhds = []
        for unit in order:
            if demand(self.model, kw + unit.engine_kw) <= supply + EPS:
                admitted.add(unit.name)
                kw += unit.engine_kw
            elif unit.name in lhd_names:
                waiting_lhds.append(unit.name)
        self.admitted = admitted
        self.admitted_kw = kw
        self.waiting_lhds = tuple(sorted(waiting_lhds))
        self.waiting = len(trucks) + len(lhds) - len(admitted)
        self.demand = demand(self.model, kw)

    def admits(self, truck: Any) -> bool:
        """Called by a truck at the ROM pad in a productive block before it leaves: True when its
        air is there (it is admitted now if the delivered air covers it)."""
        if truck.name in self.admitted:
            return True
        if cap.air_demand_m3s(self.model, self.admitted_kw + truck.engine_kw) <= self.delivered() + EPS:
            self.admitted.add(truck.name)
            self.admitted_kw += truck.engine_kw
            self.demand = cap.air_demand_m3s(self.model, self.admitted_kw)
            self.waiting = max(0, self.waiting - 1)
            return True
        return False

    def prime(self) -> None:
        """The units in work at the epoch, admitted against the air delivered then."""
        trucks, lhds, _ = self._units(self.sim.productive)
        self.wanted_kw = sum(u.engine_kw for u in trucks) + sum(u.engine_kw for u in lhds)
        self.wanted_demand = cap.air_demand_m3s(self.model, self.wanted_kw)
        self._admit(trucks, lhds, self.delivered())

    def _next_block_in_s(self, t: float) -> float:
        """Seconds until the next productive block starts."""
        second = (t - self.sim._day_t0) % SECONDS_PER_DAY
        return min((start - second) % SECONDS_PER_DAY for start in self.block_starts)

    # -- the minute -----------------------------------------------------------------------------

    def minute(self, t: float, dt_s: float, productive: bool) -> None:
        """One simulated minute: units, setpoint, ramp, admission, energy."""
        trucks, lhds, planned_kw = self._units(productive)
        self.wanted_kw = sum(u.engine_kw for u in trucks) + sum(u.engine_kw for u in lhds)
        self.wanted_demand = cap.air_demand_m3s(self.model, self.wanted_kw)
        need = self.wanted_demand
        if not productive and self._next_block_in_s(t) <= self.pre_vent_s:
            need = max(need, cap.air_demand_m3s(self.model, planned_kw))
        self.step(t, need, dt_s)
        self._admit(trucks, lhds, self.delivered())
        self.minutes += 1
        margin = self.delivered() - self.demand
        if margin < self.min_margin_m3s:
            self.min_margin_m3s = margin
        self._account(dt_s)

    def _account(self, dt_s: float) -> None:
        hours = dt_s / SECONDS_PER_HOUR
        sim = self.sim
        if sim.shift != self._shift_token:
            if sim.shift != "blast":           # a shift starts; its blast window stays with it
                self.energy_shift = self.fixed_shift = 0.0
            self._shift_token = sim.shift
        power, fixed = self.power_kw(), self.fixed_power_kw()
        self.energy_today += power * hours
        self.fixed_today += fixed * hours
        self.energy_shift += power * hours
        self.fixed_shift += fixed * hours
        self.energy_total += power * hours
        self.fixed_total += fixed * hours
        self.r_energy.add(power * hours)
        self.r_fixed.add(fixed * hours)
        self.r_energy.tick(dt_s)
        self.r_fixed.tick(dt_s)

    def reset_day(self) -> None:
        self.energy_today = self.fixed_today = 0.0

    # -- reporting ------------------------------------------------------------------------------

    def mine_features(self) -> Dict[str, Any]:
        day_energy = self.r_energy.total()
        day_fixed = self.r_fixed.total()
        return mine_features(self.state, self.delivered(), self.demand, self.waiting, self.power_kw(),
                             (self.energy_today, self.fixed_today), (self.energy_shift, self.fixed_shift),
                             (day_energy, day_fixed), self.tariff)


def mine_features(state: str, delivered: float, demand: float, waiting: int, power: float,
                  today: Tuple[float, float], shift: Tuple[float, float], day: Tuple[float, float],
                  tariff: float) -> Dict[str, Any]:
    """The twelve ventilation-on-demand features of the mine (spec 3.5) from the energy of the fans
    and the energy at their design duty, kWh, over today, the shift and the last 24 hours."""
    saving_today = max(0.0, today[1] - today[0])
    return {
        "vod_state": state,
        "air_delivered_m3s": round(delivered, 1),
        "vod_demand_m3s": round(demand, 1),
        "vod_units_waiting": float(waiting),
        "fan_power_kw": round(power, 1),
        "fan_energy_today_kwh": round(today[0], 1),
        "fan_saving_today_kwh": round(saving_today, 1),
        "fan_saving_today_kzt": round(saving_today * tariff, 0),
        "fan_energy_shift_kwh": round(shift[0], 1),
        "fan_saving_shift_kwh": round(max(0.0, shift[1] - shift[0]), 1),
        "fan_energy_day_kwh": round(day[0], 1),
        "fan_saving_day_kwh": round(max(0.0, day[1] - day[0]), 1),
    }
