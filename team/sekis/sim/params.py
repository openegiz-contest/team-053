"""Parameter access of the simulator.

Every model number is read from ``model/params.json`` through ``Params``. Constants the simulator
needs and the file does not carry yet are kept in ``MISSING_PARAMS`` below, in the shape of the
file (value, unit, source), so that they can be merged into it. A value present in the file always
wins over the table.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

#: id -> (value, unit, source). Not in params.json at the time of writing.
MISSING_PARAMS: Dict[str, Tuple[Any, str, str]] = {
    "regime.shift_end_allowance_h": (
        0.75, "h",
        "ASSUMPTION: travel and inspection at each end of a shift (spec 2.1 names the figure; "
        "params.json carries only the resulting regime.productive_h)"),
    "regime.meal_h": (
        1.0, "h",
        "ASSUMPTION: meal break in the middle of a shift (spec 2.1); 11 - 2 x 0.75 - 1 = 8.5 "
        "productive hours, taken as two blocks of 4.25 h"),
    "sim.last_trip_min_fraction": (
        0.5, "share of a truck cycle",
        "ASSUMPTION: a truck starts a trip while at least half of its expected cycle fits into the "
        "productive time left and finishes it in the end-of-shift allowance; on average the trips "
        "of a block then equal productive time / cycle time, as the haulage formula assumes"),
    "sim.cycle_stats_trips": (
        20, "trips",
        "ASSUMPTION: decline.avg_cycle_min is the mean over the last 20 completed trips"),
    "stope.ring_prep_during_mucking": (
        1, "flag 0/1",
        "ASSUMPTION: the next ring is drilled and charged while the broken ore of the previous one "
        "is mucked (drilling and extraction are on different sublevels); 0 restores the strictly "
        "sequential cycle of spec 2.5"),
    "stope.blast_max_broken_rings": (
        1.0, "rings of stope.blast_t",
        "ASSUMPTION: a ring is fired only when no more than one ring of broken ore is left in the "
        "stope; this stock is the buffer between stoping and haulage"),
    "stope.start_broken_rings": (
        1.0, "rings of stope.blast_t",
        "ASSUMPTION: at the epoch the mine is in steady operation: each producing stope holds one "
        "ring of broken ore and the rings are staggered one shift apart"),
    "rig.drill_m_per_ring": (
        180, "m",
        "ASSUMPTION: about 8 t of ore per drilled metre in ring drilling: 1421.5 t / 8 t/m"),
    "rig.tram_kmh": (
        5.0, "km/h",
        "ASSUMPTION: tramming speed of a drill rig between stopes"),
    "lhd.shuttle_period_min": (
        2.0, "min",
        "ASSUMPTION: one LHD run between the draw point and the level drive, there and back "
        "(position display only)"),
    "vent.split_decline_raise_tu1_share": (
        0.5, "share",
        "ASSUMPTION: the air of the underground fan is split evenly between the raises that run "
        "alongside the two declines (airflow display of raise-vhv-tu1 and raise-vhv-tu2)"),
    "water.sump_start_pct": (
        40, "% sump level",
        "ASSUMPTION: both sumps are 40 % full at the epoch, inside their pumping band"),
    "water.sump_alarm_pct": (
        95, "% sump level",
        "ASSUMPTION: a pump station reports alarm_high from 95 % sump level"),
    "pond.start_fill": (
        1.0, "share of pond.volume_m3",
        "ASSUMPTION: the settling ponds are full at the epoch (flow-through ponds)"),
    "water.intake_pond_fill": (
        0.5, "share of pond.volume_m3",
        "ASSUMPTION: the extra river intake (measure W2) runs, up to its capacity, while the ponds "
        "are less than half full; with fuller ponds no river water is taken"),
    "water.pond_reserve_fill": (
        0.25, "share of pond.volume_m3",
        "ASSUMPTION: with the ponds less than a quarter full the plant is throttled to the feed "
        "the water sources sustain (cap.water_balance feed limit at the steady pump yield), so a "
        "lasting deficit shows as water-limited lines and not as stop-and-go with the pump cycle"),
    "stockpile.low_days_of_feed": (
        1.0, "days",
        "ASSUMPTION: the ROM stockpile reports low below one day of plant feed"),
}

#: id -> (tuned value, unit, source, value in params.json that it replaces). The spec leaves one
#: constant to be tuned by the simulator: ``sim.op_delay_factor``, inside the range given by
#: ``sim.op_delay_factor_min`` and ``_max``. The tuned value is used while params.json still holds
#: the value it replaces; any other value in the file wins.
TUNED_PARAMS: Dict[str, Tuple[Any, str, str, Any]] = {
    "sim.op_delay_factor": (
        0.785, "-",
        "ASSUMPTION: simulator-only calibration knob for check C3, tuned from the starting value "
        "0.81: with the bay rules of spec 2.4 a truck waits about 0.5 min per trip for opposing "
        "traffic, while the haulage formula books K_BAY x (n - 1) = 2.25 min on TU2; 0.785 puts the "
        "mean of 60-day baseline runs over many seeds on the analytic haulage capacity",
        0.81),
}


class Params:
    """``params(id)`` gives the value from params.json, else from ``MISSING_PARAMS``; a value of
    ``TUNED_PARAMS`` replaces the untuned value of the file."""

    def __init__(self, model: Any):
        self._model = model
        self._cache: Dict[str, Any] = {}

    def __call__(self, param_id: str) -> Any:
        try:
            return self._cache[param_id]
        except KeyError:
            pass
        try:
            value = self._model.p(param_id)
        except KeyError:
            if param_id not in MISSING_PARAMS:
                raise
            value = MISSING_PARAMS[param_id][0]
        tuned = TUNED_PARAMS.get(param_id)
        if tuned is not None and value == tuned[3]:
            value = tuned[0]
        self._cache[param_id] = value
        return value
