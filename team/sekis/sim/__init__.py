"""Headless simulator core of the Sekisovskoye digital twin (spec section 2).

The package turns the model files into moving twins: trucks on two single-lane declines, stopes
through their production cycle, LHDs and rigs, ventilation, the dewatering cascade, settling
ponds, plant lines, ROM stockpile and tailings dams. It is deterministic for a given seed, uses
the standard library only and does no I/O except loading the model files. Formulas and numbers
come from ``sekis.capacity`` and ``model/params.json``, so the live numbers and the analytic
capacities of the advisor are computed by the same code.

Typical use (this is all the service needs)::

    from sekis.sim import Simulator, PublishPlanner, ditto_modify, telemetry_topic

    sim = Simulator.from_files(seed=53)                 # epoch and seed default to params.json
    planner = PublishPlanner(sim, scale=1.0)            # PUBLISH_SCALE
    while True:                                         # every 0.5 real seconds
        sim.step(0.5)                                   # 0.5 real s = 30 simulated s = 3 steps
        if new_revision:                                # the scenario thing changed in Ditto
            sim.apply_scenario(scenario_features)       # Ditto shape or plain values
        for name in planner.due(time.monotonic()):      # at most 20 names per second
            publish(telemetry_topic(name), ditto_modify(sim.namespace, name, sim.features(name)))

Public API

``Simulator(model, geometry, registry=None, seed=None, epoch=None)``
    ``model`` is a ``capacity.Model``, ``geometry`` a ``geometry.Geometry``, ``registry`` the
    content of registry.json (read from ``model/`` when omitted). ``seed`` defaults to
    ``sim.seed``, ``epoch`` (ISO 8601 string or ``datetime``) to ``sim.epoch``.
``Simulator.from_files(seed=None, epoch=None, model_dir=None)``
    The same, reading params.json, registry.json and geometry.json.

Time
    ``step(real_seconds)``      advance at the compression ``sim.speedup`` (60); the attribute
                                ``speedup`` may be reassigned
    ``advance(sim_minutes)``    advance by simulated minutes
    ``run_days(days)``          advance by simulated days
    ``sim_days``, ``sim_time``  simulated days since the epoch; ISO 8601 clock
    The internal step is ``sim.step_s`` (10 simulated seconds). A fraction of a step is carried
    over to the next call. Trucks move on every step; stopes, pumps, ponds, plant and the
    ventilation rule are integrated once per simulated minute.
    The epoch of ``sim.epoch`` lies 45 minutes into the first productive block of shift A, and
    the run opens on a working mine: the trucks are spread along their cycles (see
    ``Haulage.warm_start``), the LHDs muck, the rigs drill, every producing stope holds one ring
    of broken ore. The state at the epoch is the same for every seed; the totals start at zero.
    An epoch outside productive time opens with the trucks at the ROM pad.

Ventilation (spec 2.6)
    Which units wait for air is decided by ``capacity.hold_units``, the function behind the
    analytic ventilation capacity, so ``mine.units_held_vent``, the trucks in ``held_vent`` and
    the advisor's bar tell the same story. ``held_trucks`` and ``held_lhds`` name the units held.
    A held truck is not counted among the trucks working its decline (``trucks_on_decline``).

Scenario (spec 3.1, 3.3)
    ``apply_scenario(knobs) -> list of changed knob names``
        ``knobs`` maps knob names to plain values or to the Ditto shape
        ``{"properties": {"value": v}}``; the whole feature object of ``kz.sekis:scenario`` can be
        passed as it is. Knobs left out keep their value; unknown names are ignored. Raises
        ``ValueError`` and changes nothing when the set is invalid (both declines closed, a stage
        outside its ladder, a line that is not built). Planned units enter service and leave it
        again as the knobs say; a truck taken out of service finishes its trip first.
    ``reset_scenario()``        back to the baseline knobs
    ``default_knobs()``, ``knobs``, ``cap_state`` (the ``capacity.State`` of the knobs)

Twins
    ``snapshot(names=None) -> {thing_name: {feature_id: value}}``
        Every thing of the registry except ``advisor`` (95 things), with exactly the feature ids of
        the registry. Numbers are floats, the eight string features are strings, references are
        thing names without namespace or ``"none"``. Cached per step; do not modify it.
    ``features(name)``          one thing of the snapshot
    ``validate_snapshot() -> list of problems``   empty when ids and types match the registry
    ``changed_since(token=None) -> (new_token, {thing_name: features})``
        Things whose features changed since ``token`` was issued; ``None`` returns everything.
    ``tier(name) -> "S" | "M" | "L" | "on_change"``   publishing tier now (planned and parked
        units publish in tier L)
    ``PublishPlanner(sim, scale=None).due(now_s) -> list of names``   which things to publish at
        real time ``now_s``; keeps to the tier periods and to ``publish.max_msg_per_s``.
        ``periods()`` gives the present period of each tier.
    ``ditto_modify(namespace, name, features)``, ``ditto_features(features)``,
    ``telemetry_topic(name)``   message helpers of spec 1.1
    The scenario thing is in the snapshot with the knobs the simulator has applied (tier
    ``on_change``); the planner never returns it, because the Stand writes that thing.

Totals and calibration
    ``totals() -> dict``        since the epoch: ``ore_blasted_t``, ``ore_loaded_t``,
        ``ore_hoisted_t``, ``ore_milled_t``, ``gold_oz``, ``tailings_placed_t``, the water volumes
        ``water_inflow_m3``, ``water_pumped_m3``, ``water_site_use_m3``, ``water_plant_supply_m3``,
        ``water_reclaim_m3``, ``water_extra_intake_m3``, ``water_discharge_m3``,
        ``water_deficit_m3``; present stocks ``ore_broken_t``, ``ore_on_trucks_t``,
        ``stockpile_t``, ``tailings_stored_t``, ``water_in_ponds_m3``, ``water_in_sumps_m3``,
        ``flood_volume_m3``; air ``air_supply_m3s``, ``air_demand_m3s``, ``air_demand_peak_m3s``;
        traffic ``truck_trips``, ``truck_cycle_mean_min``, ``bay_wait_min_per_trip``,
        ``max_bay_wait_min``, ``traffic_conflicts``; the lowest stocks seen ``min_stockpile_t``,
        ``min_ponds_m3``, ``min_sump_m3``.
    ``annualised() -> dict``    mine totals x 360 / days, plant and water totals x 365 / days
    ``calibration_checks()``    rows C3, C8, C11 as ``capacity.CalibrationCheck``
    ``analytic``                ``capacity.evaluate`` for the live state (knobs, flooded levels,
        tailings placed): the source of ``enterprise.binding_link`` and ``annual_rate_ktpa``

What the displayed values mean
    * "now" rates (``mine.ore_hoisted_tph``, ``mine.pumped_m3h``, ``rom-stockpile.inflow_tph``,
      ``plant.gold_poured_oz_day``) are rolling means over ``sim.rate_window_h``; the water balance
      and the discharge at the outfall are rolling means over ``water.rolling_window_h`` (24 h),
      which hides pump cycling and also delays their answer to a scenario by up to a day; the
      enterprise day figures are rolling 24-hour totals. The 24-hour windows start from the
      analytic baseline. ``..._today`` values reset at the start of shift A.
    * ``mine.air_demand_m3s`` is the demand of the units in service that are not held;
      ``diesel_kw_active`` is the engine power running at this moment.
    * ``haul_truck.decline`` is the decline the truck works through (``none`` when parked);
      ``chainage_m`` is metres from the portal along the drawn decline, 0 off the decline.
    * ``pump_station.hours_to_overflow`` is 0 when the sump is not rising or already full.
    * ``settling_pond.retention_h`` is the water held in the pond over the flow through it: with
      ps-p150 failed it counts the reserve down in hours.
    * Unbounded hours and years are published as 999.

Constants that params.json does not carry yet are in ``MISSING_PARAMS``; the tuned value of
``sim.op_delay_factor`` is in ``TUNED_PARAMS`` (both in ``sekis.sim.params``).
"""

from .params import MISSING_PARAMS, TUNED_PARAMS, Params
from .publish import PublishPlanner, ditto_features, ditto_modify, telemetry_topic
from .simulator import ADVISOR_THING, SCENARIO_THING, STRING_FEATURES, Simulator, load_registry

__all__ = [
    "Simulator", "PublishPlanner", "MISSING_PARAMS", "TUNED_PARAMS", "Params", "STRING_FEATURES",
    "SCENARIO_THING", "ADVISOR_THING", "load_registry", "ditto_features", "ditto_modify", "telemetry_topic",
]
