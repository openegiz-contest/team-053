"""Dewatering cascade, settling ponds and water balance, plant, ROM stockpile and tailings
(spec 2.7 with decisions 9.2 and 9.4).

These processes are integrated once per simulated minute. Formulas and thresholds come from
``capacity.py`` and ``params.json``: the inflow split and pump counts from ``cap.dewatering``,
the water demand, reclaim, extra intake and feed limit from ``cap.water_balance``, the line rates
from ``cap.plant``, the dams from ``cap.tailings``, gold from ``cap.gold_oz``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .. import capacity as cap
from .timebase import Rolling, bucket_for

SECONDS_PER_MINUTE = 60.0
SECONDS_PER_HOUR = 3600.0
SECONDS_PER_DAY = 86400.0
PERCENT = 100.0
EPS = 1e-9
#: Published instead of an unbounded number of hours or years (features carry no null).
UNBOUNDED = 999.0


class Dewatering:
    """Sumps and pumps of ps-p150 (main) and ps-m050 (lower), and the flood volume."""

    def __init__(self, sim: Any):
        self.sim = sim
        p = sim.p
        self.sump_main = float(p("water.ps_p150.sump_m3"))
        self.sump_lower = float(p("water.ps_m050.sump_m3"))
        start = p("water.sump_start_pct") / PERCENT
        self.v_main = self.sump_main * start
        self.v_lower = self.sump_lower * start
        self.run_main = 0
        self.run_lower = 0
        self.flood = 0.0
        # rates of the last minute, m3/h
        self.in_main = self.in_lower = self.out_main = self.out_lower = 0.0
        self.net_main = self.net_lower = 0.0
        self.inflow_total = 0.0
        self.pumped_total = 0.0
        self.min_sump = min(self.v_main, self.v_lower)
        # Levels flood upward in order of elevation at the volumes of their workings
        # (``capacity.flood_order``): -50, 0, +50, +100, +150 m (the level of ps-p150 itself; the
        # dead station does not stop the water), then the mined-out +200 and +250 m. Nothing stops
        # the water below the lowest way out by gravity, the TU2 portal on the old pit floor at
        # +320 m: once the workings hold ``flood_outlet`` (filled to +320 m) the further inflow
        # runs out into the pit (``to_pit``), whose volume would take years to fill, so the flood
        # volume stops there and the ventilation level +320 m stays dry.
        self.flood_thresholds: Tuple[Tuple[str, float], ...] = cap.flood_order(sim.model)
        self.flood_outlet = cap.flood_outlet_m3(sim.model)
        #: Water that left the full workings through the TU2 portal into the old pit, m3.
        self.to_pit = 0.0
        # Pumping bands of the two sumps (m3): from the stop level up to the level at which the last
        # pump of the cycle joins. Water inside the bands is what the pump cycle holds back for a
        # few hours; see ``levelled_m3``.
        self.band_main = (self.sump_main * p("water.ps_p150.stop_pct") / PERCENT,
                          self.sump_main * p("water.ps_p150.start2_pct") / PERCENT)
        self.band_lower = (self.sump_lower * p("water.ps_m050.stop_pct") / PERCENT,
                           self.sump_lower * p("water.ps_m050.start_standby_pct") / PERCENT)
        self.in_band = self._in_band()
        self._was_available = True
        #: Water delivered to the ponds in the last minute, levelled over the pump cycle (m3).
        self.levelled_m3 = 0.0
        #: Time compression of the water stored underground during a flood episode (spec 2.7).
        self.flood_compression = float(p("water.flood_compression"))

    def available_main(self) -> int:
        p = self.sim.p
        return max(0, int(p("water.ps_p150.pumps")) - self.sim.cap_state.pumps_failed_p150)

    def compression(self) -> float:
        """How much faster than the mine clock the water stored underground (both sumps and the
        flooded workings) changes: ``water.flood_compression`` while ps-p150 is out of action or
        water stands in the workings, else 1 (spec 2.7). Flows stay on the mine clock."""
        if self.available_main() == 0 or self.flood > 0.0:
            return self.flood_compression
        return 1.0

    def _in_band(self) -> float:
        """Water held in the pumping bands of both sumps, m3."""
        low, high = self.band_main
        main = min(max(self.v_main - low, 0.0), high - low)
        low, high = self.band_lower
        lower = min(max(self.v_lower - low, 0.0), high - low)
        return main + lower

    def minute(self, dt_s: float) -> float:
        """Advance the cascade by ``dt_s``; returns the water delivered to the ponds, m3.

        During a flood episode (``compression() > 1``) the volumes stored underground move by
        the inflow and pumping of ``compression()`` minutes in this one; the water delivered to
        the ponds, the totals and the published flows stay those of one minute (m3/h on the mine
        clock), and the hours to overflow count on the mine clock."""
        p = self.sim.p
        spec = self.sim.dewater_spec          # cap.Dewatering for the current knobs
        clock_hours = dt_s / SECONDS_PER_HOUR
        k = self.compression()
        hours = clock_hours * k               # hours of inflow and pumping the storage sees

        # Lead and lag control. ps-m050: one pump from start1 down to stop; the standby joins at
        # start_standby and drops out when the level is back under start1.
        level = self.v_lower / self.sump_lower * PERCENT
        lead = int(p("water.ps_m050.pumps_working"))
        if level >= p("water.ps_m050.start_standby_pct"):
            self.run_lower = int(p("water.ps_m050.pumps"))
        elif level >= p("water.ps_m050.start1_pct"):
            self.run_lower = max(self.run_lower, lead)
        elif level > p("water.ps_m050.stop_pct"):
            self.run_lower = min(self.run_lower, lead)
        else:
            self.run_lower = 0
        # ps-p150: the first pump from start1 down to stop, the second from start2 until the level
        # is back under start1. The standby only replaces a failed pump, so at most pumps_working
        # run and never more than are available.
        level = self.v_main / self.sump_main * PERCENT
        working = int(p("water.ps_p150.pumps_working"))
        if level >= p("water.ps_p150.start2_pct"):
            self.run_main = working
        elif level >= p("water.ps_p150.start1_pct"):
            self.run_main = max(self.run_main, 1)
        elif level > p("water.ps_p150.stop_pct"):
            self.run_main = min(self.run_main, 1)
        else:
            self.run_main = 0
        self.run_main = min(self.run_main, working, self.available_main())

        before_main, before_lower = self.v_main, self.v_lower
        lower_in = spec.inflow_lower_m3h * hours
        upper_in = spec.inflow_upper_m3h * hours
        self.v_lower += lower_in
        out_lower = min(self.run_lower * p("water.ps_m050.pump_m3h") * hours, self.v_lower)
        self.v_lower -= out_lower
        self.v_main += upper_in + out_lower
        out_main = min(self.run_main * p("water.ps_p150.pump_m3h") * hours, self.v_main)
        self.v_main -= out_main
        spill = max(0.0, self.v_main - self.sump_main)       # a full main sump spills down
        self.v_main -= spill
        self.v_lower += spill
        over = max(0.0, self.v_lower - self.sump_lower)      # a full lower sump floods the mine
        self.v_lower -= over
        self.flood += over
        if self.flood > self.flood_outlet:                  # filled to +320 m: out through the TU2 portal
            self.to_pit += (self.flood - self.flood_outlet) / k
            self.flood = self.flood_outlet
        if self.flood > 0.0 and self.v_lower < self.sump_lower:   # flood water drains back to the sump
            back = min(self.flood, self.sump_lower - self.v_lower)
            self.v_lower += back
            self.flood -= back

        # Delivery to the ponds levelled over the pump cycle: what the pumps sent up plus the change
        # of the water held in the pumping bands of the sumps, which the next pump runs send up.
        # While the station works this is the mine water reaching the sumps (the inflow, less what
        # floods the mine), so the 300 / 600 m3/h cycle of the pumps does not show. While ps-p150
        # cannot pump, nothing is delivered; the water then rising in the sumps is counted when it
        # is pumped (the bands are taken as they are when the station is back).
        band = self._in_band()
        available = self.available_main() > 0
        delivered = out_main / k               # what reaches the ponds in this minute of the mine clock
        if available and self._was_available and k == 1.0:
            self.levelled_m3 = max(0.0, out_main + band - self.in_band)
        else:
            self.levelled_m3 = delivered
        self.in_band = band
        self._was_available = available

        self.in_main = (upper_in + out_lower) / hours
        self.in_lower = (lower_in + spill) / hours
        self.out_main = out_main / hours
        self.out_lower = out_lower / hours
        self.net_main = (self.v_main - before_main) / clock_hours
        self.net_lower = (self.v_lower - before_lower) / clock_hours
        self.inflow_total += (lower_in + upper_in) / k
        self.pumped_total += delivered
        low = self.v_main if self.v_main < self.v_lower else self.v_lower
        if low < self.min_sump:
            self.min_sump = low
        return delivered

    def flooded_levels(self) -> Tuple[str, ...]:
        return tuple(name for name, threshold in self.flood_thresholds if self.flood > threshold)

    def hours_to_next_flooded_level(self) -> float:
        """Hours of the mine clock until the next level floods (``flood_thresholds`` in order),
        0 when no level is threatened (the pumps keep up, or every level below the outlet is
        flooded already). A level is threatened while the inflow exceeds what the
        pumps can send up (``capacity.Dewatering.flood_rate_m3h``); the free volume of both sumps
        and the flood volume still missing to the next threshold fill at that surplus. The
        storage moves ``flood_compression`` times faster than the mine clock once the episode is
        on (``compression()``); before that only the sumps fill, at the mine clock, since water
        in the workings starts the episode."""
        threshold = next((volume for _, volume in self.flood_thresholds if self.flood <= volume), None)
        if threshold is None:
            return 0.0
        surplus = self.sim.dewater_spec.flood_rate_m3h     # inflow the pumps cannot send up
        if surplus <= EPS:
            return 0.0
        sumps_free = max(0.0, self.sump_main - self.v_main) + max(0.0, self.sump_lower - self.v_lower)
        to_threshold = max(0.0, threshold - self.flood)
        k = self.flood_compression
        if self.compression() > 1.0:
            return (sumps_free + to_threshold) / surplus / k
        return sumps_free / surplus + to_threshold / surplus / k


    def station_features(self, name: str) -> Dict[str, Any]:
        sim = self.sim
        p = sim.p
        if name == "ps-p150":
            volume, sump, running = self.v_main, self.sump_main, self.run_main
            available = self.available_main()
            inflow, pumped, net = self.in_main, self.out_main, self.net_main
            head = p("water.head_ps_p150_m")
        elif name == "ps-m050":
            volume, sump, running = self.v_lower, self.sump_lower, self.run_lower
            available = int(p("water.ps_m050.pumps"))
            inflow, pumped, net = self.in_lower, self.out_lower, self.net_lower
            head = p("water.head_ps_m050_m")
        else:                                   # a station that is not built
            return {"state": "planned", "inflow_m3h": 0.0, "pumped_m3h": 0.0, "sump_level_pct": 0.0,
                    "pumps_running": 0.0, "pumps_available": 0.0, "power_kw": 0.0, "hours_to_overflow": 0.0}
        level = volume / sump * PERCENT
        if available == 0:
            state = "failed"
        elif level >= p("water.sump_alarm_pct"):
            state = "alarm_high"
        elif running > 0:
            state = "pumping"
        else:
            state = "idle"
        # Hours until the sump is full while it is rising; 0 when it is not rising or already full.
        to_overflow = (sump - volume) / net if net > EPS and volume < sump else 0.0
        return {"state": state, "inflow_m3h": round(inflow, 1), "pumped_m3h": round(pumped, 1),
                "sump_level_pct": round(level, 1), "pumps_running": float(running if pumped > 0 else 0),
                "pumps_available": float(available),
                "power_kw": round(cap.pump_power_kw(sim.model, pumped, head), 1),
                "hours_to_overflow": round(min(to_overflow, UNBOUNDED), 2)}


class Water:
    """Settling ponds (two in series) and the water balance (decision 9.2).

    Pumped mine water enters the upper pond and passes to the lower one; site use and the plant
    draw from the ponds; what the full ponds cannot hold is discharged to the Volchevka. With the
    ponds empty the plant feed is limited to what the remaining sources carry.
    """

    def __init__(self, sim: Any):
        self.sim = sim
        p, model = sim.p, sim.model
        self.volumes = [float(v) for v in model.pond_volumes_m3]
        self.stored = [v * p("pond.start_fill") for v in self.volumes]
        self.intake_fill = float(p("water.intake_pond_fill"))
        self.reserve_fill = float(p("water.pond_reserve_fill"))
        window_s = p("water.rolling_window_h") * SECONDS_PER_HOUR
        bucket_s = bucket_for(window_s)
        # Start the means from the analytic baseline, as if the hour before was normal.
        base = sim.baseline
        hoist_tph = sim.mine_rate_tph(base)
        feed_tph = base.plant.capacity_ktpa * cap.KILO / model.hours_per_year
        balance = cap.water_balance(model, hoist_tph, feed_tph, base.dewatering.pumped_m3h)
        self.r_mine = Rolling(window_s, bucket_s, balance.mine_water_m3h)
        self.r_site = Rolling(window_s, bucket_s, balance.site_use_m3h)
        self.r_plant = Rolling(window_s, bucket_s, balance.plant_supply_m3h)
        self.r_reclaim = Rolling(window_s, bucket_s, balance.reclaim_m3h)
        self.r_intake = Rolling(window_s, bucket_s, balance.extra_intake_m3h)
        self.r_deficit = Rolling(window_s, bucket_s, balance.deficit_m3h)
        self.r_discharge = Rolling(window_s, bucket_s, balance.discharge_m3h)
        self.r_draw = Rolling(window_s, bucket_s, balance.demand_m3h)
        self._rolls = (self.r_mine, self.r_site, self.r_plant, self.r_reclaim, self.r_intake, self.r_deficit,
                       self.r_discharge, self.r_draw)
        self.deadband_pct = float(p("water.permit_deadband_pct"))
        self.outfall_state = self.permit().permit_state
        self.limited = False
        self.total = {"site": 0.0, "plant": 0.0, "reclaim": 0.0, "intake": 0.0, "deficit": 0.0,
                      "discharge": 0.0, "into_ponds": 0.0}
        self.min_stored = sum(self.stored)

    def minute(self, dt_s: float, pumped_m3: float, levelled_m3: float, feed_wanted_tph: float) -> float:
        """Book one minute of water. Returns the plant feed the water supply allows, t/h.

        ``pumped_m3`` is what ps-p150 sent to the ponds this minute, ``levelled_m3`` the same
        delivery levelled over the pump cycle (``Dewatering.levelled_m3``), used for the published
        flows only.
        """
        sim = self.sim
        model = sim.model
        hours = dt_s / SECONDS_PER_HOUR
        m_water = sim.cap_state.m_water
        stored = self.stored[0] + self.stored[1]
        available_m3h = (stored + pumped_m3) / hours
        # Site water (dust suppression, drilling, washing) follows the day's production, not each
        # truck that tips: it is drawn at the 24-hour hoisting rate.
        ore_tph = sim.plant.r_hoist_day.per_hour()
        wanted = cap.water_balance(model, ore_tph, feed_wanted_tph, available_m3h, m_water)
        feed = feed_wanted_tph
        if feed > EPS:
            # What is physically there: the ponds and what the pumps deliver this minute.
            if wanted.deficit_m3h > EPS and wanted.feed_limit_tph < feed:
                feed = wanted.feed_limit_tph
            # While mine water keeps coming, the last part of the ponds is kept as the reserve for
            # the pump cycle: below it the plant runs at the rate the sources sustain (the steady
            # yield of the pumps, reclaim, extra intake). With ps-p150 failed nothing is coming and
            # the ponds are used up to the end.
            if (sim.dewater_spec.pumped_m3h > EPS
                    and stored < self.reserve_fill * (self.volumes[0] + self.volumes[1])):
                sustained = cap.water_balance(model, sim.plant.r_hoist_day.per_hour(), feed,
                                              sim.dewater_spec.pumped_m3h, m_water)
                if sustained.feed_limit_tph < feed:
                    feed = sustained.feed_limit_tph
        self.limited = feed < feed_wanted_tph - EPS
        balance = cap.water_balance(model, ore_tph, feed, available_m3h, m_water) if self.limited else wanted
        # Deficit: the plant water that the feed given up would have needed, plus site use not met.
        deficit_m3 = ((wanted.plant_supply_m3h - wanted.reclaim_m3h)
                      - (balance.plant_supply_m3h - balance.reclaim_m3h) + balance.deficit_m3h) * hours
        site = balance.site_use_m3h * hours
        plant = balance.plant_supply_m3h * hours
        reclaim = balance.reclaim_m3h * hours
        intake = balance.extra_intake_m3h * hours
        draw = site + plant - reclaim - intake

        upper = self.stored[0] + pumped_m3
        passed = max(0.0, upper - self.volumes[0])
        upper -= passed
        lower = self.stored[1] + passed - draw
        if lower < 0.0:                       # the lower pond is empty: take from the upper one
            upper += lower
            lower = 0.0
            if upper < 0.0:                   # site use alone exceeded what was there
                upper = 0.0
        # The extra intake (measure W2) also keeps a reserve: it tops the ponds up to the fill it
        # is run for, with whatever of its capacity the minute has left.
        spare = sim.p("ladder.m_water.extra_intake_m3h")[m_water] * hours - intake
        if spare > EPS:
            missing = self.intake_fill * (self.volumes[0] + self.volumes[1]) - upper - lower
            if missing > 0.0:
                top_up = min(spare, missing)
                intake += top_up
                lower += top_up
                if lower > self.volumes[1]:
                    upper += lower - self.volumes[1]
                    lower = self.volumes[1]
        discharge = max(0.0, lower - self.volumes[1])
        lower -= discharge
        self.stored[0], self.stored[1] = upper, lower
        # The outfall as published: while the full ponds overflow, the water the pump cycle holds
        # back in the sumps (or releases from them) belongs to this overflow too, so the outfall
        # carries the levelled delivery less the draw and not the 300 / 600 m3/h pump steps.
        outfall = max(0.0, discharge + levelled_m3 - pumped_m3) if discharge > EPS else 0.0

        self.r_mine.add(levelled_m3)
        self.r_site.add(site)
        self.r_plant.add(plant)
        self.r_reclaim.add(reclaim)
        self.r_intake.add(intake)
        self.r_deficit.add(deficit_m3)
        self.r_discharge.add(outfall)
        self.r_draw.add(draw)
        for roll in self._rolls:
            roll.tick(dt_s)
        self._classify_outfall()
        total = self.total
        total["site"] += site
        total["plant"] += plant
        total["reclaim"] += reclaim
        total["intake"] += intake
        total["deficit"] += deficit_m3
        total["discharge"] += discharge
        total["into_ponds"] += pumped_m3
        stored = upper + lower
        if stored < self.min_stored:
            self.min_stored = stored
        return feed

    # -- reporting ------------------------------------------------------------------------------

    def permit(self) -> cap.WaterBalance:
        """Discharge against the permit, classified by the library (normal, warning, exceeded)."""
        return cap.water_balance(self.sim.model, 0.0, 0.0, self.r_discharge.per_hour())

    _RANK = {"normal": 0, "warning": 1, "exceeded": 2}

    def _classify_outfall(self) -> None:
        """State of the outfall with a deadband: a higher state is taken at once, a lower one only
        when the use of the permit is ``water.permit_deadband_pct`` below the threshold of the
        state it leaves, so a discharge that sits on a threshold does not blink."""
        permit = self.permit()
        new, old = permit.permit_state, self.outfall_state
        if self._RANK[new] >= self._RANK[old]:
            self.outfall_state = new
            return
        threshold = PERCENT if old == "exceeded" else float(self.sim.p("water.permit_warning_pct"))
        if permit.permit_use_pct < threshold - self.deadband_pct:
            self.outfall_state = new

    def water_features(self) -> Dict[str, Any]:
        if self.limited:
            state = "deficit"
        elif self.outfall_state == "exceeded":
            state = "discharge_over_permit"
        else:
            state = "balanced"
        return {"state": state,
                "mine_water_m3h": round(self.r_mine.per_hour(), 1),
                "site_use_m3h": round(self.r_site.per_hour(), 1),
                "plant_supply_m3h": round(self.r_plant.per_hour(), 1),
                "reclaim_m3h": round(self.r_reclaim.per_hour(), 1),
                "extra_intake_m3h": round(self.r_intake.per_hour(), 1),
                "deficit_m3h": round(self.r_deficit.per_hour(), 1),
                "discharge_m3h": round(self.r_discharge.per_hour(), 1)}

    def pond_features(self) -> List[Dict[str, Any]]:
        """Features of the ponds in flow order.

        ``retention_h`` is the water held in the pond over the flow through it, so it falls as the
        pond is drawn down: the hours of reserve while nothing is pumped in.
        """
        p = self.sim.p
        inflow = self.r_mine.per_hour()
        flow = max(inflow, self.r_draw.per_hour())
        treatment = cap.pond_treatment(self.sim.model, flow)
        tss_in = float(p("pond.tss_in_mgl"))
        efficiency, settling_h = p("pond.efficiency"), p("pond.settling_h")
        hours_per_year = self.sim.model.hours_per_year
        features = []
        concentration = tss_in
        retention_sum = 0.0
        for index, volume in enumerate(self.volumes):
            full_retention = treatment.retention_h[index]
            share = self.stored[index] / volume if volume > 0 else 0.0
            retention = min(UNBOUNDED, full_retention * share) if flow > EPS else (UNBOUNDED if share > 0 else 0.0)
            retention_sum += min(UNBOUNDED, full_retention)
            # Solids left after this pond: the library's formula at the retention reached so far.
            out = tss_in * (1.0 - efficiency * min(1.0, retention_sum / settling_h)) if flow > EPS else concentration
            if index == len(self.volumes) - 1 and flow > EPS:
                out = treatment.tss_out_mgl
            sludge = inflow * hours_per_year * (concentration - out) / cap.GRAMS_PER_TONNE
            features.append({"state": "in_service", "inflow_m3h": round(inflow, 1),
                             "retention_h": round(retention, 2), "tss_in_mgl": round(concentration, 3),
                             "tss_out_mgl": round(out, 3), "sludge_t_year": round(max(0.0, sludge), 2)})
            concentration = out
        return features

    def hours_to_permit(self) -> float:
        """Hours of the mine clock until the outfall exceeds the permit, 0 when it is over the
        permit already or will not get there.

        Once the ponds are full the outfall carries the steady surplus of the mine water the
        pumps sustain (``Dewatering.pumped_m3h`` of ``capacity.dewatering``) over the draw. If
        that surplus is above the permit, the time is the time the ponds take to fill (their free
        volume at the surplus of the pumps' delivery now over the draw, or at the steady surplus
        while the pumps are between runs) plus the time the rolling mean of the outfall
        (``water.rolling_window_h``) takes to climb from its value now to the permit."""
        sim = self.sim
        p = sim.p
        if self.outfall_state == "exceeded":
            return 0.0
        draw = self.r_draw.per_hour()
        steady = sim.dewater_spec.pumped_m3h - draw
        permit = float(p("water.permit_m3h"))
        if steady <= permit + EPS:
            return 0.0
        fill_h = 0.0
        free = self.volumes[0] + self.volumes[1] - self.stored[0] - self.stored[1]
        if free > EPS:
            filling = sim.dewater.out_main - draw     # delivery now, m3 per hour of the mine clock
            fill_h = free / (filling if filling > EPS else steady)
        climb_h = float(p("water.rolling_window_h")) * max(0.0, permit - self.r_discharge.per_hour()) / steady
        return fill_h + climb_h

    def reserve_hours(self) -> float:
        """Hours the stored pond water covers the present draw."""
        draw = self.r_draw.per_hour()
        return min(UNBOUNDED, (self.stored[0] + self.stored[1]) / draw) if draw > EPS else UNBOUNDED


class PlantLine:
    __slots__ = ("name", "number", "rated_tph", "built", "state", "feed_tph", "milled_today", "first_stop_day")

    def __init__(self, name: str, number: int, first_stop_day: float):
        self.name = name
        self.number = number
        self.rated_tph = 0.0
        self.built = "planned"          # running / off / planned, from cap.plant
        self.state = "planned"
        self.feed_tph = 0.0
        self.milled_today = 0.0
        self.first_stop_day = first_stop_day


class Plant:
    """ROM stockpile, plant lines with planned maintenance, gold and tailings."""

    def __init__(self, sim: Any):
        self.sim = sim
        p, model = sim.p, sim.model
        self.period_days = float(p("plant.maintenance_period_days"))
        self.stop_days = float(p("plant.maintenance_duration_days"))
        stagger = float(p("plant.maintenance_stagger_days"))
        # Line n stops first on day n x stagger, then every period; folded into one period so that
        # lines added later are staggered too.
        self.lines: List[PlantLine] = [
            PlantLine(name, i + 1, ((i + 1) * stagger) % self.period_days or self.period_days)
            for i, name in enumerate(model.plant_lines)]
        self.min_stock_t = float(p("plant.min_stockpile_t"))
        self.low_days = float(p("stockpile.low_days_of_feed"))
        stock = sim.things["rom-stockpile"]["features"]
        self.stock_t = float(stock["tonnes"])
        self.stock_start_t = self.stock_t
        self.stock_grade = float(stock["grade"])
        self.min_stock_seen = self.stock_t
        self.capacity_ktpa = 0.0
        self.feed_tph = 0.0
        self.state = "running"
        self.milled_t = 0.0
        self.gold_oz = 0.0
        self.tailings_t = 0.0           # placed since the epoch
        self.tailings_free_t = 0.0
        self.tailings_full = False
        window_s = p("sim.rate_window_h") * SECONDS_PER_HOUR
        day_s = SECONDS_PER_DAY
        base = sim.baseline
        hoist_tph = sim.mine_rate_tph(base)
        feed_tph = base.plant.capacity_ktpa * cap.KILO / model.hours_per_year
        gold_per_h = cap.gold_oz(model, feed_tph, self.stock_grade)
        self.r_hoist_now = Rolling(window_s, bucket_for(window_s, 24), hoist_tph)
        self.r_hoist_day = Rolling(day_s, bucket_for(day_s), hoist_tph)
        self.r_feed_day = Rolling(day_s, bucket_for(day_s), feed_tph)
        self.r_gold_now = Rolling(window_s, bucket_for(window_s, 24), gold_per_h)
        self.r_gold_day = Rolling(day_s, bucket_for(day_s), gold_per_h)
        self._rolls = (self.r_hoist_now, self.r_hoist_day, self.r_feed_day, self.r_gold_now, self.r_gold_day)

    def restart_rates(self, hoist_tph: float) -> None:
        """A new scenario: the rate windows describe the new regime only.

        Hoisting comes in truck loads and stops in the blast windows and between the productive
        blocks, so its windows restart from ``hoist_tph`` (the analytic mine rate of the new
        state), which the measured minutes replace one by one. Feed and gold run evenly while the
        lines run, so their windows are extrapolated from the time since the change (until the
        first minute is measured they count at the rated feed of the lines ready to run).
        """
        tick_s = float(SECONDS_PER_MINUTE)
        day = self.sim.t / SECONDS_PER_DAY
        feed_tph = sum(line.rated_tph for line in self.lines
                       if line.built == "running" and not self.in_maintenance(line, day))
        gold_per_h = cap.gold_oz(self.sim.model, feed_tph, self.stock_grade)
        self.r_hoist_now.restart(hoist_tph)
        self.r_hoist_day.restart(hoist_tph)
        self.r_feed_day.restart(feed_tph, tick_s)
        self.r_gold_now.restart(gold_per_h, tick_s)
        self.r_gold_day.restart(gold_per_h, tick_s)

    def configure(self) -> None:
        """Line rates for the plant stage and the line stopped for repair (decision 9.4)."""
        sim = self.sim
        spec = cap.plant(sim.model, sim.cap_state.m_plant, sim.cap_state.line_down)
        self.capacity_ktpa = spec.capacity_ktpa
        day = sim.t / SECONDS_PER_DAY
        for line, built in zip(self.lines, spec.lines):
            line.built = built.state
            line.rated_tph = built.rated_tph
            if built.state != "running":            # off or planned: at once
                line.state = built.state
                line.feed_tph = 0.0
            elif line.state in ("planned", "off"):  # built or restarted; feeds from the next minute
                line.state = "maintenance" if self.in_maintenance(line, day) else "running"
        storage = cap.tailings(sim.model, sim.cap_state.m_tailings, self.tailings_t)
        self.tailings_free_t = storage.free_t

    def in_maintenance(self, line: PlantLine, day: float) -> bool:
        if day < line.first_stop_day:
            return False
        return (day - line.first_stop_day) % self.period_days < self.stop_days

    def add_ore(self, tonnes: float, grade: float) -> None:
        """A load of ``tonnes`` at ``grade`` tipped on the pad. The pile is taken as well mixed:
        its grade is the mass-weighted blend ``(M x G + t x g) / (M + t)`` of everything tipped
        on it, and the plant reclaims at that grade (``minute``), so a change of the ore grade
        reaches the feed, the recovery and the gold only as the pile turns over."""
        total = self.stock_t + tonnes
        if total > 0:
            self.stock_grade = (self.stock_t * self.stock_grade + tonnes * grade) / total
        self.stock_t = total
        self.r_hoist_now.add(tonnes)
        self.r_hoist_day.add(tonnes)

    def minute(self, now: float, dt_s: float, pumped_m3: float, levelled_m3: float) -> None:
        sim = self.sim
        hours = dt_s / SECONDS_PER_HOUR
        day = now / SECONDS_PER_DAY
        ready: List[PlantLine] = []
        for line in self.lines:
            line.feed_tph = 0.0
            if line.built != "running":
                line.state = line.built
            elif self.in_maintenance(line, day):
                line.state = "maintenance"
            else:
                ready.append(line)
        rated = sum(line.rated_tph for line in ready)
        # Ore: above the minimum stock every line runs; below it the plant takes what the mine
        # delivers on average, and never more than is on the pad.
        ore_limit = rated
        if self.stock_t <= self.min_stock_t:
            ore_limit = min(rated, self.r_hoist_day.per_hour())
        ore_limit = min(ore_limit, self.stock_t / hours)
        storage_limit = self.tailings_free_t / hours
        self.tailings_full = self.tailings_free_t <= EPS
        wanted = max(0.0, min(ore_limit, storage_limit))
        feed = sim.water.minute(dt_s, pumped_m3, levelled_m3, wanted)
        if feed > wanted:
            feed = wanted
        if feed < wanted - EPS:
            short_state = "water_limited"
        elif self.tailings_full or storage_limit < ore_limit:
            short_state = "off"
        else:
            short_state = "starved"
        left = feed
        for line in ready:                      # lines fill in order; the last ones go short
            take = line.rated_tph if left >= line.rated_tph else max(0.0, left)
            left -= take
            line.feed_tph = take
            line.state = "running" if take >= line.rated_tph - EPS else short_state
            line.milled_today += take * hours
        milled = feed * hours
        if milled > 0.0:
            self.stock_t -= milled
            if self.stock_t < 0.0:
                self.stock_t = 0.0
            gold = cap.gold_oz(sim.model, milled, self.stock_grade)
            self.milled_t += milled
            self.gold_oz += gold
            self.tailings_t += milled
            self.tailings_free_t -= milled
            self.r_feed_day.add(milled)
            self.r_gold_now.add(gold)
            self.r_gold_day.add(gold)
        for roll in self._rolls:
            roll.tick(dt_s)
        self.feed_tph = feed
        if any(line.state == "water_limited" for line in ready):
            self.state = "water_limited"
        elif any(line.state in ("starved", "off") for line in ready):
            self.state = "starved"
        else:
            self.state = "running"
        if self.stock_t < self.min_stock_seen:
            self.min_stock_seen = self.stock_t

    def reset_day(self) -> None:
        for line in self.lines:
            line.milled_today = 0.0

    # -- reporting ------------------------------------------------------------------------------

    def days_of_feed(self) -> float:
        per_day = self.capacity_ktpa * cap.KILO / self.sim.model.p("regime.plant_days")
        return min(UNBOUNDED, self.stock_t / per_day) if per_day > 0 else 0.0

    def stockpile_features(self) -> Dict[str, Any]:
        days = self.days_of_feed()
        if self.stock_t < 1.0:
            state = "empty"
        elif days < self.low_days:
            state = "low"
        else:
            state = "normal"
        return {"state": state, "tonnes": round(self.stock_t, 1), "grade": round(self.stock_grade, 3),
                "inflow_tph": round(self.r_hoist_now.per_hour(), 1), "outflow_tph": round(self.feed_tph, 1),
                "days_of_feed": round(days, 2)}

    def plant_features(self) -> Dict[str, Any]:
        model = self.sim.model
        demand = cap.water_balance(model, 0.0, self.feed_tph, 0.0).plant_supply_m3h
        return {"state": self.state, "feed_tph": round(self.feed_tph, 1),
                "feed_grade": round(self.stock_grade, 3),
                "recovery_pct": round(cap.recovery_pct(model, self.stock_grade), 2),
                "gold_poured_oz_day": round(self.r_gold_now.per_hour() * cap.HOURS_PER_DAY, 1),
                "capacity_ktpa": round(self.capacity_ktpa, 1),
                "lines_running": float(sum(1 for line in self.lines if line.feed_tph > 0.0)),
                "water_demand_m3h": round(demand, 1), "tailings_tph": round(self.feed_tph, 1)}

    def line_features(self, line: PlantLine) -> Dict[str, Any]:
        used = line.feed_tph / line.rated_tph * PERCENT if line.rated_tph > 0 else 0.0
        return {"state": line.state, "feed_tph": round(line.feed_tph, 2), "utilisation_pct": round(used, 1),
                "milled_today_t": round(line.milled_today, 1)}

    def tailings(self, rate_ktpa: float) -> cap.Tailings:
        return cap.tailings(self.sim.model, self.sim.cap_state.m_tailings, self.tailings_t, rate_ktpa)
