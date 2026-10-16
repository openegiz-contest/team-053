# Sekisovskoye digital twin: design

This document is the design of the Sekisovskoye digital twin built on the OpenEgiz platform v1.0.4: the twin model, the simulation model with its parameters and calibration, the what-if scenarios and the decision module, the visualization, the runtime architecture and the repository layout. Later design decisions are collected in sections 9–11 and override the earlier sections where they differ. The document is in English; all text shown on the Stand, README.md, SUBMISSION.md and presentation.pdf is Russian.

Inputs: `SUBMISSION.md` (the Concept), `team/research/sekisovskoye-facts.md` (the "facts file"), the OpenEgiz v1.0.4 template in this repository.

## 0. Summary and conventions

### 0.1 What is built

A twin of the whole Sekisovskoye production chain in Eclipse Ditto (96 things of 22 types), driven by a time-compressed simulator, with one decision module (the Expansion Advisor) and a web Stand that shows the mine as a 3D scene and a 2D long section. The user picks a processing target (1.0 / 1.2 / 2.0 / 2.5 Mtpa), sees which link binds, removes it with one click, and sees the next one. Disturbances (decline closure, fan failure, pump station failure, flood inflow, grade drop, plant line stop) run from the same panel. Every scenario has an undo.

Eight capacities are ranked: haulage, ventilation, stopes, development, dewatering, plant, process water, tailings storage. They cover the six links the Concept names: its "stopes" is shown as two rows (stopes and development), its "dewatering" as two rows (pumps and water supply).

### 0.3 Conventions

- Languages: code, comments, commit messages, this document: English. Everything a person sees on the Stand, in Grafana, README.md, SUBMISSION.md, presentation.pdf: Russian. State tokens in twins are English (`hauling_up`); the UI maps them to Russian.
- Python 3.12 in containers; code must also run on Python 3.10+. Model, simulator and advisor use the standard library only. The only third-party runtime dependency is `paho-mqtt==2.1.0`.
- Front end: plain ES modules, no build step, no npm at build time. Every script, style and font is served from the repository. No external URL may be requested by the page.
- All files are LF. The committed `.gitattributes` (`* text=auto eol=lf`) enforces it. Shell scripts are run as `bash scripts/x.sh`.
- Tests are `unittest` and run with `cd team && python -m unittest discover -s tests -v` (on Windows: `py -3 -m unittest ...`).
- A parameter enters code only through `team/model/params.json`, where each entry has `value`, `unit`, `source`. `source` starts with `FACT ` (plus the facts-file section and row) or `ASSUMPTION: ` (plus the reasoning). A test enforces this.
- `examples/mine` is not started and not copied. Nothing of it is reused.

## 1. Twin model

### 1.1 Identifiers and Ditto conventions

- Namespace `kz.sekis`. Thing ID `kz.sekis:<name>`. Policy `default:basic_policy`.
- Type things: `kz.sekis.type:<kind>` with `attributes._isType = true`, `attributes.name` (Russian), `attributes.description`, and the type's features with default values.
- Every instance has attributes: `name` (Russian), `_isType: false`, `kind` (the type token), `type` (`kz.sekis.type:<kind>`), `_parents` (one parent thing ID as a string; absent on the root), `units` (object: feature id → unit string), plus the type's own attributes and `link_*` attributes (thing ID, or array of thing IDs).
- Feature shape: `features.<feature_id>.properties.value` only. Units live in `attributes.units`, not in telemetry.
- Feature ids are snake_case. A feature id has one value type everywhere (InfluxDB rejects a field that changes type): `state`, `shift`, `decline`, `stope`, `binding_link`, `next_measure`, `label`, `sim_time` are strings; every other feature is a number. No booleans, no null, no arrays or objects in features. Flags are 0/1.
- Telemetry: Ditto-protocol `modify` on path `/features` carrying all features of the thing, published to MQTT topic `telemetry/sekis/<name>`:

```json
{"topic": "kz.sekis/truck-01/things/twin/commands/modify", "path": "/features",
 "value": {"state": {"properties": {"value": "hauling_up"}}, "payload": {"properties": {"value": 30.0}}}}
```

- InfluxDB (written by the platform's Telegraf): bucket `default`, measurement `mqtt_consumer`, field `value_<feature_id>_properties_value`, tags `thingId`, `parent`.

### 1.2 Types and their features

`S` marks the fast publishing tier (every 2 s), `M` every 6 s, `L` every 20 s. A unit in state `planned` or `parked` publishes in tier L.

| Kind | Tier | Attributes (besides the common ones) | Features |
|---|---|---|---|
| `enterprise` | M | `operator`, `location`, `coordinates` | `sim_time` (ISO string), `sim_day`, `shift` (`A`/`B`/`blast`), `ore_mined_tpd`, `ore_milled_tpd`, `gold_poured_oz_day`, `gold_poured_total_oz`, `annual_rate_ktpa`, `binding_link` |
| `mine` | M | `design_capacity_ktpa`, `working_days`, `shifts`, `shift_h` | `state` (`production`/`blast_window`/`restricted_air`/`evacuation`), `ore_hoisted_tph`, `ore_hoisted_today_t`, `ore_hoisted_total_t`, `trucks_active`, `diesel_kw_active`, `air_supply_m3s`, `air_demand_m3s`, `air_margin_pct`, `units_held_vent`, `inflow_m3h`, `pumped_m3h`, `flood_volume_m3` |
| `level` | L | `elevation_m`, `role`, `link_declines`, `link_drains_to`, `link_air_intake`, `link_air_exhaust` | `state` (`ventilation`/`mined_out`/`production`/`development`/`planned`/`flooded`), `air_flow_m3s`, `air_required_m3s`, `diesel_kw`, `water_inflow_m3h`, `active_stopes`, `ore_today_t` |
| `stope` | M | `block`, `ore_initial_t`, `grade_gpt`, `sublevel_m`, `link_level`, `link_ore_route` | `state` (see 2.5), `ore_remaining_t`, `broken_ore_t`, `drilled_pct`, `backfill_pct`, `grade`, `mucked_today_t`, `block_no` |
| `decline` | M | `portal_elevation_m`, `design_bottom_m`, `slope_deg`, `section_m2`, `length_m`, `link_levels`, `link_portal_to` | `state` (`open`/`closed`), `bottom_elevation`, `trucks_on_ramp`, `trucks_waiting_in_bays`, `loaded_trips_today`, `ore_today_t`, `avg_cycle_min` |
| `shaft` | L | `section_m2`, `top_elevation_m`, `bottom_elevation_m`, `direction`, `link_fan` | `state` (`in_service`/`planned`), `air_flow_m3s`, `air_velocity_ms` |
| `raise` | L | same as `shaft` | same as `shaft` |
| `main_fan` | M | `model`, `duty_m3s`, `duty_max_m3s`, `pressure_pa`, `link_airway` | `state` (`running`/`failed`/`planned`), `air_flow_m3s`, `pressure`, `power_kw` |
| `pump_station` | M | `elevation_m`, `pumps_total`, `pumps_working`, `pump_capacity_m3h`, `sump_volume_m3`, `link_discharges_to` | `state` (`idle`/`pumping`/`alarm_high`/`failed`/`planned`), `inflow_m3h`, `pumped_m3h`, `sump_level_pct`, `pumps_running`, `pumps_available`, `power_kw`, `hours_to_overflow` |
| `settling_pond` | L | `volume_m3`, `area_m2`, `depth_m`, `link_overflows_to` | `state` (`in_service`), `inflow_m3h`, `retention_h`, `tss_in_mgl`, `tss_out_mgl`, `sludge_t_year` |
| `monitoring_point` | L | `water_body`, `permit_m3h`, `permit_ref` | `state` (`normal`/`warning`/`exceeded`), `discharge_m3h`, `intake_m3h`, `tss_mgl`, `permit_use_pct` |
| `haul_truck` | S | `model`, `payload_t`, `engine_kw`, `link_home_decline` | `state` (see 2.4), `payload`, `grade`, `speed`, `decline` (`tu1`/`tu2`/`none`), `chainage_m`, `elevation`, `pos_x`, `pos_y`, `pos_z`, `trips_today`, `tonnes_today` |
| `lhd` | S | `model`, `bucket_t`, `engine_kw` | `state` (`parked`/`idle`/`mucking`/`loading_truck`/`standby_vent`/`shift_break`), `stope`, `tonnes_today`, `pos_x`, `pos_y`, `pos_z` |
| `drill_rig` | M | `model` | `state` (`parked`/`drilling`/`tramming`/`shift_break`), `stope`, `metres_today`, `pos_x`, `pos_y`, `pos_z` |
| `rom_stockpile` | M | `link_feeds` | `state` (`normal`/`low`/`empty`), `tonnes`, `grade`, `inflow_tph`, `outflow_tph`, `days_of_feed` |
| `plant` | M | `nameplate_ktpa`, `link_tailings_to`, `link_water_from` | `state` (`running`/`starved`/`water_limited`), `feed_tph`, `feed_grade`, `recovery_pct`, `gold_poured_oz_day`, `capacity_ktpa`, `lines_running`, `water_demand_m3h`, `tailings_tph` |
| `plant_line` | M | `rated_tph`, `commissioned` | `state` (`running`/`starved`/`maintenance`/`water_limited`/`off`/`planned`), `feed_tph`, `utilisation_pct`, `milled_today_t` |
| `tailings_facility` | L | `coordinates`, `area_km2`, `link_active_dam` | `state` (`ok`/`short_horizon`/`full`), `stored_t`, `free_capacity_t`, `inflow_tpd`, `years_left`, `reclaim_m3h` |
| `tailings_dam` | L | `capacity_t`, `capacity_m3`, `bulk_density` | `state` (`active`/`standby`/`full`/`planned`), `stored_t`, `fill_pct`, `free_capacity_t`, `inflow_tph` |
| `water_system` | M | `link_ponds`, `link_points` | `state` (`balanced`/`deficit`/`discharge_over_permit`), `mine_water_m3h`, `site_use_m3h`, `plant_supply_m3h`, `reclaim_m3h`, `extra_intake_m3h`, `deficit_m3h`, `discharge_m3h` |
| `scenario_control` | on change | none | the knobs of section 3.1, plus `revision`, `label` |
| `advisor` | on change + every 30 s | none | section 3.4 |

Publishing budget: at most 20 MQTT messages per second in total. If the active fast-tier units exceed 14, the fast tier period becomes 3 s. Environment variable `PUBLISH_SCALE` (default 1.0) multiplies all periods.

### 1.3 Things

Parent is given as the name without the namespace. "Baseline" is the state at simulation start with all scenario knobs at their defaults.

| Thing name | Kind | Parent | `name` attribute (Russian) | Key attributes and baseline |
|---|---|---|---|---|
| `enterprise` | enterprise | (root) | Предприятие «Секисовское» | operator «ДТОО „ГРП BAURGOLD“ (AltynGold PLC)», coordinates 50°19'43" N, 82°35'48" E |
| `mine` | mine | enterprise | Подземный рудник | design 1000 kt/yr; 360 d, 2 shifts, 11 h |
| `lvl-p320` | level | mine | Горизонт +320 м (вентиляционный) | elevation 320; role `ventilation` |
| `lvl-p250`, `lvl-p200` | level | mine | Горизонт +250 м, Горизонт +200 м | role `mined_out` (backfilled) |
| `lvl-p150`, `lvl-p100`, `lvl-p050`, `lvl-000` | level | mine | Горизонт +150 м … Горизонт 0 м | role `production` |
| `lvl-m050` | level | mine | Горизонт −50 м | role `development` (TU1 bottom) |
| `lvl-m100`, `lvl-m150`, `lvl-m200`, `lvl-m300` | level | mine | Горизонт −100 м … −300 м (проект) | role `planned` |
| `stp-p150-1..3`, `stp-p100-1..3`, `stp-p050-1..3`, `stp-000-1..3` | stope | its level | Блок 150-1 … Блок 0-3 | 90 000 t each; grade by level 1.75 / 1.95 / 2.15 / 2.35 g/t; baseline: stope `-1` of each level in the producing set, `-2` `standby`, `-3` `standby` |
| `stp-m050-1..3`, `stp-m100-1..3` | stope | its level | Блок −50-1 … Блок −100-3 | grade 2.45 / 2.55; baseline `preparation` (−50) and `planned` (−100) |
| `decline-tu1` | decline | mine | Транспортный уклон ТУ-1 | portal +430, design bottom −300, 8°, 18 m², current bottom −50; levels +300 … −50 |
| `decline-tu2` | decline | mine | Транспортный уклон ТУ-2 | portal +320, design bottom −200, 8°, 18 m², current bottom −34; levels +300 … 0 |
| `shaft-vs1` | shaft | mine | Вентиляционный ствол ВС-1 (ствол «Секисовская») | 10.86 m², +430 to +325, intake |
| `shaft-vs2` | shaft | mine | Вентиляционный ствол ВС-2 | 10.8 m², +430 to +340, intake |
| `shaft-vs3` | shaft | mine | Вентиляционный ствол ВС-3 (мера В2, допущение) | 16 m², +430 to −200, `planned` |
| `raise-vpv` | raise | mine | Восстающий ВПВ | 7.0 m², +324 to −200, intake; baseline `planned` |
| `raise-vhv-tu1` | raise | mine | Восстающий ВХВ ТУ-1 | 5.6 m², +200 to −300 |
| `raise-vhv-tu2` | raise | mine | Восстающий ВХВ ТУ-2 | 5.6 m², +250 to −200 |
| `raise-vhv-exhaust` | raise | mine | Вытяжные восстающие ВХВ 7, 8, 10 | 10.75 m², exhaust |
| `fan-vs1` | main_fan | shaft-vs1 | Вентилятор ВОД-16П (ВС-1) | duty 150 m³/s, 2500 Pa |
| `fan-ug-p320` | main_fan | lvl-p320 | Подземная вентиляторная установка AL18-4500V | duty 102 m³/s, 2500 Pa |
| `fan-vs2` | main_fan | shaft-vs2 | Вентилятор Korfmann AL17-2000 (ВС-2) | duty 70 m³/s (range 63–88), 3000 Pa |
| `fan-vpv` | main_fan | raise-vpv | Вентилятор ВПВ (мера В1) | duty 105 m³/s, `planned` |
| `fan-vs3` | main_fan | shaft-vs3 | Вентилятор ВС-3 (мера В2) | duty 240 m³/s, `planned` |
| `ps-p150` | pump_station | lvl-p150 | Главная водоотливная станция, гор. +150 м | 3 × 300 m³/h (2 working, 1 standby), sump 1800 m³, discharges to `pond-upper` |
| `ps-m050` | pump_station | lvl-m050 | Участковая насосная, гор. −50 м | 2 × 150 m³/h (1 + 1), sump 600 m³, discharges to `ps-p150` |
| `ps-m200` | pump_station | lvl-m200 | Главная водоотливная станция, гор. −200 м (проект) | 3 × 300 m³/h, `planned` |
| `truck-01..04` | haul_truck | mine | Самосвал CAT AD30 № 1 … № 4 | 30 t, 304 kW, home `decline-tu2`; active |
| `truck-05` | haul_truck | mine | Самосвал CAT AD45 № 5 | 45 t, 439 kW, home `decline-tu1`; active |
| `truck-06..12` | haul_truck | mine | Самосвал CAT AD45 № 6 … № 12 | `parked`; home TU1 for 06, 07, 08, 11; TU2 for 09, 10, 12 |
| `lhd-01..03` | lhd | mine | ПДМ CAT R1300 № 1 … № 3 | 6.8 t, 123 kW; active |
| `lhd-04` | lhd | mine | ПДМ CAT R1700 № 4 | 15 t, 263 kW; active |
| `lhd-05..10` | lhd | mine | ПДМ CAT R1700 № 5 … № 10 | `parked` |
| `rig-01`, `rig-02` | drill_rig | mine | Буровая установка Boomer S1D № 1, Boomer T1D № 2 | active |
| `rig-03..05` | drill_rig | mine | Буровая установка Boomer S1D № 3 … № 5 | `parked` |
| `water` | water_system | enterprise | Водное хозяйство | |
| `pond-upper`, `pond-lower` | settling_pond | water | Илоотстойник верхний, Илоотстойник нижний | 2265 m³ and 377.5 m² each, 3 m deep, in series |
| `mon-volchevka` | monitoring_point | water | Выпуск № 1 в ручей Волчевка | permit 218.8 m³/h |
| `mon-sekisovka` | monitoring_point | water | Пост на реке Секисовка | water body «р. Секисовка»; shows `intake_m3h` |
| `plant` | plant | enterprise | Обогатительная фабрика | nameplate 1000 kt/yr |
| `rom-stockpile` | rom_stockpile | plant | Рудный склад | 94 264 t at start (`stockpile.start_t`, 2.8) |
| `plant-line-1..3` | plant_line | plant | Технологическая линия № 1 … № 3 | 41.36 t/h each; line 3 commissioned December 2024 |
| `plant-line-4..6` | plant_line | plant | Технологическая линия № 4 … № 6 (проект) | `planned` |
| `tailings` | tailings_facility | enterprise | Хвостовое хозяйство | 50°20'24" N, 82°36'30" E; 1.53 km² |
| `tsf-dam4` | tailings_dam | tailings | Хвостохранилище, дамба № 4 | 3 181 950 t / 2 357 000 m³; 90 % full at start; `active` |
| `tsf-dam2`, `tsf-dam3` | tailings_dam | tailings | Хвостохранилище, дамба № 2, дамба № 3 | free 1 426 950 t each; `standby` |
| `tsf-cell5` | tailings_dam | tailings | Новая карта хвостохранилища (мера Х1, допущение) | 6 000 000 t; `planned` |
| `scenario` | scenario_control | enterprise | Сценарий (управляющий двойник) | |
| `advisor` | advisor | enterprise | Советник по расширению | |

Count: 1 + 1 + 12 + 18 + 2 + 3 + 4 + 5 + 3 + 12 + 10 + 5 + 1 + 2 + 2 + 1 + 1 + 6 + 1 + 4 + 1 + 1 = 96 things, and 22 type things (one per kind in 1.2).

### 1.4 Links

Hierarchy is `_parents` (tree above). Process links are attributes:

| Attribute | On | Refers to |
|---|---|---|
| `link_level` | stope | its level |
| `link_ore_route` | stope | the declines that reach its level |
| `link_declines` | level | `decline-tu1` and, for +300 … 0, `decline-tu2` |
| `link_drains_to` | level | `ps-p150` for levels at or above +150; `ps-m050` below |
| `link_air_intake`, `link_air_exhaust` | level | `shaft-vs1` for levels at or above +150, `shaft-vs2` below (ASSUMPTION); `raise-vhv-exhaust` |
| `link_levels`, `link_portal_to` | decline | levels served; `rom-stockpile` |
| `link_fan` / `link_airway` | shaft, raise / main_fan | each other |
| `link_discharges_to` | pump_station | next station or `pond-upper` |
| `link_overflows_to` | settling_pond | `pond-lower`; then `water` |
| `link_home_decline` | haul_truck | its decline |
| `link_feeds` | rom_stockpile | plant lines |
| `link_tailings_to`, `link_water_from` | plant | `tailings`; `water` |
| `link_active_dam` | tailings_facility | the dam being filled |
| `link_ponds`, `link_points` | water_system | ponds; monitoring points |

Dynamic assignments (which LHD or rig works which stope, which decline a truck is on) are string features `stope` and `decline`.

## 2. Simulation model

### 2.1 Time base

- Compression 60: one real second is one simulated minute (`SIM_SPEEDUP=60`). A shift lasts 11 real minutes; a truck cycle takes 52–58 real seconds (measured in the simulator at baseline).
- Internal step 10 simulated seconds; the service loop runs every 0.5 real seconds (3 steps).
- Simulation epoch: 1 January 2027, 09:30, 45 minutes into the first productive block (first year of the decision); the run opens with trucks spread along their cycles. A year is 360 working days (FACT A10 "Shift regime"); the five non-working days are not simulated. Mine totals are annualised with × 360, plant totals with × 365 (the plant runs every day).
- Day: shift A 08:00–19:00, blast window 19:00–20:00, shift B 20:00–07:00, blast window 07:00–08:00. ASSUMPTION: the 2 hours left by 2 × 11 h are used for blasting and clearing.
- Productive time inside a shift: 8.5 h (ASSUMPTION: 0.75 h travel and inspection at each end, 1 h meal).
- Random numbers come from one generator seeded with `SIM_SEED=53`. The core runs headless (no MQTT) at full speed for tests: 60 simulated days in at most 60 s.
- Displayed values (the docstring "What the displayed values mean" in `team/sekis/sim/__init__.py` is authoritative):
  - Mine rate: `mine.ore_hoisted_tph` is the ore hoisted over the last 24 simulated hours, `enterprise.ore_mined_tpd` the same per day; the Stand header shows this 24-hour mine rate beside the plant feed. `rom-stockpile.inflow_tph` is a rolling 2-hour mean (`sim.rate_window_h`).
  - Plant: `plant.gold_poured_oz_day` is the gold of the last 2 hours × 12; `enterprise.ore_milled_tpd`, `enterprise.gold_poured_oz_day` and `tailings.inflow_tpd` are 24-hour totals; `plant.feed_tph` and the line feeds are the present minute.
  - Restart on a knob change: when `apply_scenario` changes a knob (not `revision` or `label` alone), the windows of these six rates start again. The hoisting windows restart from the analytic mine rate of the new state and are replaced by measurement minute by minute; the feed and gold windows are extrapolated from the time since the change.
  - Water: the flows of `water`, `mine.pumped_m3h`, the ponds, `tailings.reclaim_m3h` and the two monitoring points are rolling 1-hour means (`water.rolling_window_h`), not restarted; mine water is levelled over the pump cycle, the permit state has a deadband (`water.permit_deadband_pct`).
  - `..._today` values are totals since 08:00 and are not restarted. Annual capacities and the advisor's KPIs are analytic and steady-state (3.4).

### 2.2 Processes and couplings

```
stopes (drill → blast → muck) ──ore──▶ trucks on TU1/TU2 ──▶ rom-stockpile ──▶ plant lines ──▶ gold
   ▲ rigs, LHDs (diesel kW)             ▲ diesel kW                                 │ tailings ▶ dams
   │                                    │                                           │ water demand
ventilation: supply (fans) vs demand (180 m³/s + 0.06 m³/s per active diesel kW) ── holds units when short
dewatering: inflow ▶ ps-m050 ▶ ps-p150 ▶ ponds ▶ water system ▶ site use, plant, discharge to Volchevka
flooded level ▶ its stopes stop;  water deficit ▶ plant lines water-limited;  dams full ▶ plant stops
```

One parameter file and one function library (`sekis/capacity.py`) serve both the simulator and the advisor, so the live numbers and the analytic capacities agree by construction; tests check it.

### 2.3 Link capacities (analytic, kt/yr)

Used by the advisor and by tests. `H = 7920` shift hours per year (360 × 2 × 11, FACT A10).

1. Haulage. For truck i on decline d with n trucks on that decline, hauling from elevation z (baseline production centroid z = +75 m):
   `L = (portal_d − z) × 7.185 × 1.15 / 1000` km (7.185 = 1 / sin 8°, FACT A2 slope; 1.15 ASSUMPTION for curves and bays);
   `T = 5 + 1.5 + 1.5 + 60·L/9 + 60·L/16 + 60·S_d/15 + 60·S_d/20 + K_BAY·(n − 1)` minutes;
   `C_haul = Σ payload_i × 60 / T_i × H × (8.5/11) × 0.80 × K_HAUL / 1000`.
2. Stopes. `C_stopes = N_producing × 255.875`. Development: `C_dev = advance_vm_per_year × 51 462 / 1000`. The row "stopes" shows `C_stopes`; "development" is its own row.
3. Ventilation. A diesel unit either works or waits for air; the air is not shared out over a fleet. The hold rule of 2.6 is applied to the fleet in service (`capacity.hold_units`, the function the simulator calls every simulated minute). `P_fleet` = engine kW of all trucks and LHDs in service; the fleet needs `180 + 0.06 × P_fleet` m³/s.
   - The fleet needs more than is supplied: whole units are held in the order of 2.6 until the demand of the rest fits. `C_vent = min(C_haul of the trucks left working, C_stopes of the stopes whose LHD is left working)`, with the formulas of items 1 and 2; `n` in item 1 counts the working trucks only. A held LHD idles its stope, the last of the producing set, so the working trucks haul from the mean elevation of the stopes left working (with `fan-vs2` failed at baseline: +100 m instead of +75 m).
   - The supply covers the fleet: nothing is held and the air does not limit the fleet in service. The bar then shows headroom, `C_vent = C_haul × P_allowed / P_fleet` with `P_allowed = (Q_supply − 180) / 0.06` kW. It is never below `C_haul`, so ventilation is the binding link only while units are held (a tie goes to haulage). The headroom is not a promise that one more unit fits: at baseline 4.8 m³/s are spare and the smallest LHD needs 7.4 m³/s.

   The result names the held units, the air the working units use and the spare air (`Air.held_trucks`, `held_lhds`, `used_m3s`, `spare_m3s`); the advisor puts them into its texts.
4. Dewatering. `margin = working pump capacity / (inflow × 24/20)`. It caps throughput only when a level is flooded: then `C_dewatering = C_stopes` of the non-flooded producing stopes; otherwise it is reported as not limiting.
5. Plant. `C_plant` = 1000 / 1200 / 2000 / 2500 by stage, reduced by a stopped line.
6. Water. `C_water = (1725.72 + 8.76 × extra_intake_m3h) / (0.603 + 1.123 − reclaim_m3_per_t)`.
7. Tailings. `C_tailings = free_capacity_kt / 3.0` (the rate that keeps three years of storage); `years_left = free_capacity / rate`.

Gold: `oz = milled_t × grade × R(grade) / 31.1035`, `R(g) = 81.616 + 1.637·g` percent, clamped to 80–88.

Reference values with the parameters of 2.8 (tests use them with ±1 % tolerance):

| Measure set | haulage | stopes | development | ventilation | plant | water | tailings | air demand m³/s |
|---|---|---|---|---|---|---|---|---|
| Baseline | 926 | 1024 | 1750 | 958 | 1000 | 1000 | 1057 | 317.2 |
| Full set for 1.2 Mtpa | 1388 | 1279 | 1750 | 1667 | 1200 | 1533 | 3057 | 385.7 |
| Full set for 2.0 Mtpa | 2078 | 2047 | 2573 | 3049 | 2000 | 2700 | 3057 | 512.0 |
| Full set for 2.5 Mtpa | 2515 | 2559 | 2573 | 2942 | 2500 | 2700 | 3057 | 596.3 |

No unit is held in these four sets, so their ventilation column is headroom. States in which units are held (the simulator column is the 60-day run of 2.9, annualised; tests keep it within ±7 % of `C_vent`):

| State | Air needed / supplied, m³/s | Units held | Working units use, m³/s | haulage | ventilation | Simulator |
|---|---|---|---|---|---|---|
| Baseline + `m_haul = 1` | 369.9 / 322 | trucks 07, 06 | 317.2 | 1388 | 926 | 931 |
| Baseline + `m_haul = 2` | 448.9 / 322 | trucks 10, 09, 08, 07; LHDs 04, 03 | 320.4 | 2078 | 512 (two stopes left) | 521 |
| Baseline + `m_stopes = 1` | 333.0 / 322 | truck 05 | 306.7 | 926 | 683 | 726 |
| Baseline, `fan-vs2` failed | 317.2 / 252 | trucks 05, 04, 03; LHD 04 | 238.6 | 926 | 374 | 378 |
| Full set for 1.2 Mtpa, `fan-vs2` failed | 385.7 / 357 | trucks 07, 06 | 333.0 | 1388 | 926 | 968 |

The rule holds trucks first, so a fleet measure taken without air can lower the output: five more trucks at 322 m³/s cost two LHDs and nearly half the tonnage, one more LHD costs the only AD45. In the two rows with five producing stopes the simulator is 6.3 % and 4.5 % above `C_vent`. About 3 % of each belong to item 1, not to the air rule: item 1 hauls from the +75 m centroid whatever the producing set, while the fifth stope lies at +150 m (at the mean of +90 m item 1 gives 705 and 955 kt/yr), and the same 968 kt/yr are hoisted against a haulage of 926 with no unit held (`m_stopes = 1`, `m_vent = 1`). The rest is the simulator's spread around item 1, 0.6 % at baseline.

Depth effect: every 50 m the production centroid goes down costs about 8.5 % of haul capacity (baseline fleet: 926 → 841 → 770 → 710 kt/yr at +75, +25, −25, −75 m).

### 2.4 Trucks and decline traffic (state machine)

States: `parked`, `descending`, `waiting_bay`, `tram_level`, `queue_load`, `loading`, `hauling_up`, `surface_haul`, `dumping`, `held_vent`, `maintenance`, `shift_break`.

Cycle: `surface_haul` (empty, ROM pad → portal) → `descending` → `tram_level` → `queue_load` → `loading` (5 min, needs `broken_ore_t` ≥ payload and the stope's LHD) → `tram_level` → `hauling_up` → `surface_haul` (loaded) → `dumping` (1.5 min, adds payload and grade to `rom-stockpile`) → repeat.

- Dispatch: an empty truck at the portal is sent to the stope with the largest `broken_ore_t` per truck already assigned, among stopes its decline reaches.
- Decline geometry for traffic: nodes at the portal, at every multiple of 25 m of elevation below it, and at the current bottom; level accesses are the nodes at multiples of 50 m. Each node is a passing bay with one waiting slot. Segments between nodes are single lane.
- Traffic rules (deadlock-free; loaded trucks have priority): an up-going truck enters the segment above it when no down-going truck is inside; it never uses a waiting slot. A down-going truck enters the segment below it only when no up-going truck is inside and the waiting slot of the node at its lower end is free and not reserved; it reserves that slot. Trucks in the same direction may follow each other.
- Operational delay: each cycle gets an extra delay drawn from an exponential distribution with mean `T × (1/k − 1)`, where `k = sim.op_delay_factor` (start at 0.81; tuned within 0.70–0.95 so that check C3 passes).
- Breakdowns: time to failure exponential with mean 40 h, repair 10 h (availability 0.80); a broken truck finishes its trip to the surface and goes to `maintenance`.
- Shift end: trucks finish the current trip and wait at the surface in `shift_break` through the blast window and the unproductive part of the shift.
- Closed decline: its trucks leave it, re-home to the other decline at the surface and use it until the closure ends. Stopes below −34 m are reachable only by TU1.

### 2.5 Stopes, rigs, LHDs

Stope states: `planned`, `preparation`, `standby`, `drilling`, `charging`, `awaiting_blast`, `ventilating`, `mucking`, `backfilling`, `flooded`.

- The producing set has `N_producing` stopes (4 at baseline). Order of activation: `-1` stopes of +150, +100, +50, 0; then `-2` stopes in the same level order; then `-3`; then `stp-m050-*`.
- Cycle of a producing stope: `drilling` 1.5 productive shifts with a rig → `charging` 0.5 shift → `awaiting_blast` → blast in the next blast window (adds 1421.5 t to `broken_ore_t`) → `ventilating` 30 min → `mucking` until `broken_ore_t` is hauled away → next ring. A rig serves one stope at a time, so `N_producing ≤ 2 × rigs`. One LHD per producing stope.
- A stope with `ore_remaining_t = 0` goes to `backfilling` for 20 days (waste backfill, FACT A1), then reopens as the next block (`block_no + 1`, 90 000 t), after 5 days of `preparation`. The next stope in the activation order takes its place in the producing set.
- LHD states follow the stope: `loading_truck` while a truck loads, `mucking` during `mucking` with no truck present, `idle` otherwise. Rigs: `drilling` or `tramming` between stopes.

### 2.6 Ventilation

- Supply: sum of `duty_m3s` of fans in state `running`. Baseline 150 + 102 + 70 = 322 m³/s. This is the design supply of the fans in service (`mine.air_supply_m3s`, the supply of the hold rule and of the advisor). With ventilation on demand (3.5) the fans deliver less when fewer units work: `mine.air_delivered_m3s`, never more than the design supply.
- Demand: `180 + 0.06 × P_fleet` m³/s.
- Rule (every simulated minute): if demand exceeds supply, units are held in this order until it fits: the active truck with the highest number, the next truck, then the LHD with the highest number (its stope becomes `standby`), and repeat; never below one truck and one LHD. A held truck finishes its trip and waits at the surface in `held_vent`; a held LHD is `standby_vent`. Units are released in reverse order. `mine.state` is `restricted_air` while anything is held. The rule works on the design supply; ventilation on demand never lowers it.
- Level air (as decided on 17 October, `capacity.level_air`, decision 11.4): only the levels in use get air for work: those in production or development that are not flooded, and any other open level with units on it. Their requirement follows the units working there now: `air_required = 180 × (1 − 0.2) / (levels in use) + 0.06 × kW of the units on the level` (`vent.leakage_share` = 0.2, ASSUMPTION), plus the kW of an LHD held for air at its stope, which gets no air. The open levels not in use (the ventilation level +320, the backfilled +250 and +200) need nothing (`air_required = 0`) and carry the leakage, `180 × 0.2 / 3 = 12` m³/s each at the requirement; planned and flooded levels get none. Every level gets its requirement for the working units times `delivered / demand of the units in work`, so with nothing held a level in use gets at least its requirement (5 % more under ventilation on demand), and a level whose LHD waits for air shows short. Units on the declines take the rest of the delivered air: the levels do not add up to it. Example: a production level with an R1300 mucking and an AD30 loading needs 28.8 + 0.06 × (123 + 304) = 54.4 m³/s; the backfilled +250 m carries about 12 m³/s of leakage and needs nothing.
- Airways: `air_velocity_ms = air_flow / section_m2`. Split of the 252 m³/s group: 150 through `shaft-vs1`, 102 through the two declines (ASSUMPTION). `shaft-vs2` carries the `fan-vs2` flow, `raise-vpv` the `fan-vpv` flow, `shaft-vs3` the `fan-vs3` flow (the flows the fans deliver now); all delivered air leaves through `raise-vhv-exhaust`.
- Fan pressure and power (3.5): each fan works on the fixed resistance of its airway, `p = p_design × (Q / duty)²`, and `power_kw = Q × p / 0.75 / 1000`, so the power follows the cube of the flow: `P = P_design × (Q / duty)³`. At the design duty 500 + 340 + 280 = 1 120 kW.
- After a blast the stope is `ventilating` for 30 min before re-entry (ASSUMPTION).

### 2.7 Water, plant, tailings

Dewatering cascade (FACT A6 "Mine water route"):

- Inflow `197 × inflow_factor` m³/h; 60 % reports to the `ps-p150` sump, 40 % to the `ps-m050` sump.
- `ps-m050`: one pump starts at 70 % sump level and stops at 20 %; the standby starts at 90 %. It discharges into the `ps-p150` sump.
- `ps-p150`: first pump starts at 60 %, stops at 20 %; second starts at 80 %; the standby runs only in place of a failed pump. It discharges to `pond-upper`.
- Overflow: a full `ps-p150` sump spills down to the `ps-m050` sump; a full `ps-m050` sump adds to `mine.flood_volume_m3`. Spare pump capacity removes the flood volume after recovery.
- Flood thresholds (as decided on 17 October, decision 11.4), from the volume of the workings at the section of the declines, 18 m² (`water.flood_section_m2`; the level drives are taken with it), and the schematic layout of 4.2: `lvl-m050` is `flooded` when its workings are full, (drive 640 m + access from TU1 80 m + three crosscuts of 37 m) × 18 m² = 14 958 m³, threshold 14 960 m³ (its stopes are in preparation, no open void); `lvl-000` is `flooded` (and its stopes `flooded`) when the water has also filled the declines between −50 m and 0 m (TU1 50 m and TU2 34 m of depth at 8.26 m of ramp per vertical metre: 694 m × 18 m² = 12 494 m³) and the 0 m workings (drive 670 m + accesses 80 m and 110 m + three crosscuts of 37 m = 971 m × 18 m² = 17 478 m³): threshold 44 930 m³. The voids of the open 0 m stopes lie above the level floor and fill only after it. At the mean inflow of 197 m³/h with the station dead, the two sumps overflow after 7.3 h of inflow (1 440 m³ free at 40 % fill), `lvl-m050` floods after 83 h and `lvl-000` after 235 h.
- Time compression of a flood episode (`water.flood_compression` = 24, ASSUMPTION for display): while `ps-p150` is out of action or water stands in the workings, the water stored underground (both sumps and the flood volume) changes 24 times faster than the mine clock: an hour on the Stand is a day of inflow. On the Stand's 60× clock the sumps overflow after 18 s, −50 m floods after 3.5 min and 0 m after 9.8 min. Flows (inflow, pumping, delivery to the ponds), the plant and the ponds keep the mine clock, so the ponds still run dry about 20 h after the failure, after both levels have flooded (in real time they would run dry first). The scenarios panel states the factor and the thresholds while the episode lasts. Outside an episode the factor is 1.
- `hours_to_overflow` = free sump volume / net inflow while the sump is rising, in hours of the mine clock (compressed during a flood episode).
- Pump power: `1000 × 9.81 × Q/3600 × head × 1.1 / 0.70 / 1000` kW; head 280 m for `ps-p150` (+150 to +430), 200 m for `ps-m050`.

Ponds and water balance (rolling 1-hour means, `water.rolling_window_h`; the mine water reaching the ponds is levelled over the pump cycle by the water held in the pumping bands of the sumps, so a scenario shows within the hour and the 300 / 600 m³/h pump steps do not reach the permit state):

- `retention_h = 2265 / flow` per pond; `tss_out = 39.563 × (1 − 0.949 × min(1, total retention / 6))` mg/l; `sludge_t_year = flow × 8760 × 39.563 × 0.949 / 10⁶`.
- Supply = pumped mine water + reclaim (`0.6 × feed_tph` when `m_water ≥ 1`) + extra intake (up to 150 m³/h when `m_water = 2`, shown on `mon-sekisovka`).
- Demand = `0.603 × ore hoisted t/h` (site) + `1.123 × feed t/h` (plant).
- Deficit reduces plant feed in proportion (lines go `water_limited`, last line first). Surplus is discharged at `mon-volchevka`: `permit_use_pct = discharge / 218.8`, state `warning` above 80 %, `exceeded` above 100 %.

Plant:

- A line runs at `rated_tph` while `rom-stockpile.tonnes` > 500 t and water is available. Planned maintenance: each line is down one day in every 12.5 days, staggered by 4 days (availability 0.92).
- With a low stockpile, lines starve one by one (highest number first) so that feed does not exceed what the mine delivers.
- Gold poured accumulates with the formula of 2.3. Tailings tonnes equal feed tonnes.

Tailings: the active dam fills; when full the next one becomes active in the order dam 4, dam 2, dam 3, cell 5 (if built). With nothing free the plant stops (`tailings.state = full`).

### 2.8 Parameters

`F` = FACT with facts-file section and row; `A` = ASSUMPTION with reasoning. `team/model/params.json` holds exactly these.

| Id | Value | Source |
|---|---|---|
| `regime.working_days`, `shifts`, `shift_h` | 360, 2, 11 | F A10 "Shift regime" |
| `regime.productive_h` | 8.5 | A: travel, inspection and meal inside an 11 h shift |
| `decline.tu1.portal_m`, `design_bottom_m` | +430, −300 | F A2 "Transport decline TU1" |
| `decline.tu2.portal_m`, `design_bottom_m` | +320, −200 | F A2 "Transport decline TU2" |
| `decline.slope_deg`, `section_m2` | 8, 18.0 | F A2 |
| `decline.tu1.bottom_m` | −50 | F D1 "Declines" (H1 2026; tagged UNCONFIRMED in the facts file) |
| `decline.tu2.bottom_m` | −34 | A: D1 says −34 masl is planned for H2 2026; taken as reached at the epoch |
| `decline.length_factor` | 1.15 | A: curves and passing bays; decline lengths are not published (facts C). It gives 7.185 × 1.15 = 8.26 m of ramp per vertical metre. F D1 "Decline No.1, advance" reports 230 linear metres from −34 to −50 masl, 14.4 m of decline per vertical metre: the reported development metres also count turnouts, passing bays, stubs (sumps, electrical cut-outs, remuck bays) and the access to the new level, which add length but no depth (the 16 m of depth take 132 m of ramp; the other 98 m are such development), and the same report counts 100 m on Decline No.2 with no change of depth. Not changed (decision 11.4): the haulage formula and `K_HAUL` are calibrated with it (C3), and a truck drives the ramp, not the stubs |
| `decline.bay_spacing_vm` | 25 | A: a bay about every 200 m of ramp |
| `decline.surface_km` | TU1 0.8, TU2 1.5 | A: portal to ROM pad; TU2 portal assumed on the old pit floor |
| `level.floor_height_m` | 50 | F A1 "Floor height" |
| `stope.sublevel_m` | 13–16 | F A1 "Sublevel height" |
| `stope.capacity_design_ktpa` | 1023.5 | F A3 "Calculated capacity from mining conditions" |
| `stope.producing_base` | 4 | A: gives 255.875 kt/yr per producing stope |
| `stope.cycle_shifts`, `blast_t` | 4, 1421.5 | A: 255 875 t / 360 d × 2 d |
| `stope.ore_initial_t` | 90 000 | A: one block; stope dimensions are not published (facts C) |
| `stope.backfill_days`, `preparation_days` | 20, 5 | A; waste backfill itself is F A1 |
| `stope.grade_by_level` | 1.75, 1.95, 2.15, 2.35, 2.45, 2.55 | A: mean of the four production levels is 2.05 (F B "Milled gold grade" FY2025); lower grade on upper horizons follows F D1 (Q1 2026 dip during upper-horizon mining) |
| `ore.density` | 2.83 t/m³ | F A3 "Ore density" |
| `dev.advance_vm_per_year` | 34 | F B3: decline 1 from 0 to −34 masl and decline 2 from +34 to 0 during 2025 |
| `dev.advance_boosted` | 50 | A: second development crew |
| `dev.t_per_vm` | 51 462 | A from F D2: 33.45 Mt of Ore Reserves over +250 … −400 m, spread evenly |
| `truck.AD30` | 30 t, 304 kW | A: manufacturer data sheet (model named in F A4) |
| `truck.AD45` | 45 t, 439 kW | A: manufacturer data sheet (model named in F A4) |
| `lhd.R1300`, `lhd.R1700` | 6.8 t, 123 kW; 15 t, 263 kW | A: manufacturer data sheets (models in F A4) |
| `fleet.base` | 4 AD30 on TU2; 1 AD45 on TU1; 3 R1300 + 1 R1700; 2 rigs | 4 AD30 on TU2: F A4. 3 R1300: F D3. The AD45, the R1700 and the rig count: A (F A4 names AD45 and Cat 1700 as intended; F D1 "additional transport equipment purchased") |
| `truck.speed_kmh` | up loaded 9, down empty 16, flat loaded 15, flat empty 20 | A: typical for a 1:7 ramp and a 20 km/h underground limit |
| `truck.load_min`, `dump_min`, `manoeuvre_min` | 5, 1.5, 1.5 | A |
| `truck.availability` (MTBF, MTTR) | 0.80 (40 h, 10 h) | A |
| `haul.K_HAUL` | about 0.811 | A: calibration constant, set so that `C_haul(baseline) = 926.4` kt/yr (F B "Ore mined" FY2025) |
| `haul.K_BAY` | 0.75 min per extra truck on the decline | A: congestion term of the analytic formula |
| `sim.op_delay_factor` | 0.81 (tunable 0.70–0.95) | A: simulator-only calibration knob for check C3 |
| `vent.supply_2022` | 252 m³/s | F A5 "Fresh air, current" |
| `vent.supply_base` | 322 m³/s | F A5 "Fresh air, planned"; A: upgrade taken as complete (F B3 reports ventilation improvements completed in FY2025) |
| `vent.fan_vs2` | 70 m³/s, range 63–88, 3000 Pa | F A5 "Surface fan at VS2"; duty 70 = 322 − 252 is A |
| `vent.split` | fan-vs1 150, fan-ug-p320 102 | A |
| `vent.q_base`, `vent.q_diesel` | 180 m³/s; 0.06 m³/s per kW | A: 0.06 m³/s per kW is the norm of Ontario Reg. 854 s.183.1(1) (`research/norms-and-equipment.md` Q1); the Kazakh rule (Order 352, point 1063) refers to its Appendix 25-1, which is not in the public copies. 180 is fitted so that the pair reproduces 252 m³/s at half the fleet and 322 m³/s at the full fleet (checks C6, C7) |
| `vent.measure_V1` | +105 m³/s (fan on raise VPV, 7.0 m² × 15 m/s) | section: F A2 "Ventilation raise VPV"; velocity limit and fan: A |
| `vent.measure_V2` | +240 m³/s (new shaft VS3, 16 m² × 15 m/s) | A |
| `vent.fan_efficiency`, `pressure_vs1_pa` | 0.75; 2500 | A |
| `vent.reentry_min` | 30 | A |
| `water.inflow_m3h` | 197 | F A6 "Average mine inflow" (2021); equals 1725.72 thousand m³/yr ÷ 8760 h (F A6 "Water balance") |
| `water.inflow_design_m3h` | 430 | F A6 "Design inflow" |
| `water.upper_share` | 0.60 | A; F A6 gives at most 25 m³/h at the +320 m horizon |
| `water.ps_p150` | 3 × 300 m³/h, sump 1800 m³ | A: two working pumps clear the design inflow in 20 h (430 × 24/20 = 516 ≤ 600); sump about 4 h of design inflow. Station and elevation: F A6 "Pumping stations", F B3 |
| `water.ps_m050` | 2 × 150 m³/h, sump 600 m³ | A; unit size from F A6 "Pumps at quarry sump" |
| `water.flood_threshold_m050_m3`, `water.flood_threshold_000_m3` | 14 960, 44 930 | A: the volume of the workings at 18 m² (2.7, decision 11.4); were 300 and 1 500 |
| `water.pump_efficiency`, heads | 0.70; 280 m, 200 m | A; elevations F A2, A6 |
| `pond.volume_m3`, `area_m2`, `depth_m`, `settling_h` | 4530, 755, 3, 6 | F A6 "Settling ponds" |
| `pond.tss_in_mgl`, `efficiency` | 39.563; 0.949 | F A6 "Sludge yield" |
| `water.site_use`, `water.plant_supply` | 602.688; 1123.032 thousand m³/yr | F A6 "Reused on site", "Transferred to Altyn MM concentrator" |
| `water.site_m3_per_t`, `water.plant_m3_per_t` | 0.603; 1.123 | A: the two volumes divided by the 1000 kt/yr design output (F A3) and scaled linearly |
| `water.permit_m3h` | 218.8 | F A6 "Discharge to Volchevka" (1917.1123 thousand m³/yr ÷ 8760) |
| `water.measure_W1`, `W2` | reclaim 0.6 m³/t milled; extra intake 150 m³/h | A: about half of the slurry water at 45 % solids; intake sized for 2.5 Mtpa |
| `plant.nameplate_ktpa`, `lines` | 1000; 3 | F B2 (third line, +50 % to 1 Mtpa) |
| `plant.availability` | 0.92 | A; gives 41.36 t/h per line |
| `plant.stages_ktpa` | 1200; 2000; 2500 | F D1 "+≈200 kt per annum"; F B2 "2–2.5 Mtpa". Split into lines 4–5 at 400 kt/yr and line 6 at 500 kt/yr: A |
| `plant.recovery` | 81.616 + 1.637·g %, 80–88 | A: least-squares fit to F B (FY2024, FY2025) and F D1 (H1 2025, H1 2026) |
| `plant.grade_base` | 2.05 g/t | F B "Milled gold grade" FY2025 |
| `plant.grade_h1_2026` | 1.76 g/t | F D1 "Gold grade, processed" |
| `stockpile.start_t` | 94 264 | A: mined minus milled from 1 Jan 2020 (opening 0): 2020 +85 794, 2021 +29 459 (FY2021 results), 2022 −56 992 (secondary; sign confirmed by H1 2022 −29 201), 2023 taken as 0 (milled not published), 2024 +156 433, 2025 −40 170 (F B), H1 2026 −40 130 (F D1), H2 2026 −40 130 assumed at the H1 rate. 134 394 t at 30 June 2026 against a carrying value of US$24.48 m (F D1): US$182/t, while US$71–111/t would mean 220–346 kt, so the value is a lower bound |
| `econ.gold_price_usd_oz`, `econ.aisc_usd_oz` | 4 615; 1 995 US$/oz | F D1 (H1 2026; AISC on the restated basis) |
| `econ.capex_expansion_usd_m` | 125 US$m for 2.0 and 2.5 Mtpa | F D1 (Q3 2025 results); the cost of the +200 kt step is not published |
| `tsf.dam4_capacity_t`, `capacity_m3`, `bulk` | 3 181 950; 2 357 000; 1.35 | F A9 |
| `tsf.dam4_fill_start` | 0.90 | A: fill state is not published (facts C) |
| `tsf.dam23_free_t` | 1 426 950 each | A: same as the increment of the dam 4 reconstruction (3 181 950 − 1 755 000, F A9); F D1 reports the expansion of dams 2 and 3 as started |
| `tsf.measure_X1_t` | 6 000 000 | A |
| `tsf.min_years` | 3.0 | A: lead time to permit and build storage |
| `gold.g_per_oz` | 31.1035 | definition |

### 2.9 Calibration checks (automatic)

Analytic checks run in `team/tests/test_calibration.py`; simulator checks in `team/tests/test_sim.py`. The Stand shows the same table («Проверка калибровки»: показатель, основа, отчёт, модель, отклонение, допуск, результат, источник). The simulator rows C3, C8, C11 carry the values of a headless 60-day baseline run (seed 53) that the advisor makes once at start. Every row has a basis: «подгонка» (a parameter was set from the figure, or the figure defines one), «независимая» (not used to set any parameter) or «тождество» (holds by construction), and a source (facts-file section and row, and the document URL, from the sources of the parameters in `params.json`).

| Id | Check | Reported value | Tolerance | Basis |
|---|---|---|---|---|
| C1 | Gold FY2025: 966 592 t × 2.05 g/t × R | 53 852 oz (F B) | ±1.5 % | fit (recovery fit) |
| C2 | Gold FY2024: 593 612 t × 2.29 g/t × R | 37 279 oz (F B) | ±1.5 % | fit (recovery fit) |
| C3 | Simulator, baseline, 60 days, annualised ore hoisted (× 360/60) | 926 422 t (F B) | ±3 % | fit (`K_HAUL`, `sim.op_delay_factor`) |
| C4 | Gold H1 2026: 498 331 t × 1.76 g/t × R; and H1 2025: 452 593 t × 2.04 g/t × R | 23 906 oz; 25 081 oz (F D1) | ±1.5 % | fit (recovery fit) |
| C5 | Recovery model at 2.29, 2.05, 2.04, 1.76 g/t | 85.42, 85.07, 84.75, 84.55 % | ±0.25 % absolute | fit |
| C6 | Air demand of the baseline fleet (peak) | 322 m³/s (F A5) | 95–100 % of it | fit (`vent.q_base`) |
| C7 | Air demand at half the baseline fleet power | 252 m³/s (F A5) | ±3 % | fit (`vent.q_base`) |
| C8 | Simulator, baseline, 60 days: plant feed annualised (× 365/60) with stockpile available | 1 000 000 t nameplate (F B2; F D1: 498 331 t in H1 2026) | ±3 % | fit (line rates from the nameplate) |
| C9 | Sludge from the ponds at 197 m³/h | 64.3 t/yr (F A6) | ±2 % | independent |
| C10 | Water balance at 1000 kt/yr: site + plant demand | 1725.72 thousand m³/yr (F A6) | ±0.5 % | fit (water per tonne from these volumes) |
| C11 | Mass balance over a 60-day run: hoisted = stockpile change + milled; milled = tailings added | identity | ±0.1 % | identity |
| C12 | Gold at 2.0 Mtpa and 2.05 g/t | over 100 000 oz (F B2, CEO statement) | must hold | independent |
| C13 | H1 2026 ore mined × 2 against the sustainable rate (926 kt/yr) | 916 402 t (F D1) | ±3 % | independent |
| C14 | FY2026 gold guidance against the gold of 1 000 kt at the H1 2026 grade (1.76 g/t): 47.8 koz | 52–55 koz (F D1) | inside the range | independent; fails (−8.1 %): the guidance implies an annual grade of 1.91–2.01 g/t |
| C15 | FY2024 ore milled with two lines (750 045 t mined) against the two-line capacity, 666.7 kt | 593 612 t (F B) | ±5 % | independent; fails (+12.3 %): the plant ran below the two-line nameplate in 2024 |
| C16 | H1 2026 ore processed × 2 against the plant capacity | 996 662 t (F D1) | ±3 % | independent |

C13–C16 are out-of-sample rows (`capacity.out_of_sample_checks`, kind `out_of_sample` in the report). They are shown with their result; the Stand's `/api/calibration` summary and the smoke check count the analytic rows only.

Simulator consistency checks: with the full measure set for 2.0 Mtpa, 60-day annualised ore hoisted is within ±7 % of the analytic minimum of haulage and stopes; no two trucks in opposite directions ever share a decline segment; no truck waits longer than 2 simulated hours in a bay over a 30-day run with 12 trucks.

## 3. What-if scenarios and the decision module

### 3.1 Knobs (features of `kz.sekis:scenario`)

| Knob | Values (default first) | Meaning |
|---|---|---|
| `target_ktpa` | 1000, 1200, 2000, 2500 | processing target |
| `m_plant` | 0, 1, 2, 3 | 1000 → 1200 (lines 1–3 at 49.63 t/h) → 2000 (lines 4, 5) → 2500 (line 6, 62.04 t/h) |
| `m_haul` | 0, 1, 2, 3 | active trucks 01–05 → 01–07 → 01–10 → 01–12 |
| `m_stopes` | 0, 1, 2, 3 | producing stopes 4 / 5 / 8 / 10, LHDs 01–04 / –05 / –08 / –10, rigs 2 / 3 / 4 / 5 |
| `m_vent` | 0, 1, 2 | 322 → 427 (`fan-vpv`, `raise-vpv` in service) → 667 m³/s (`fan-vs3`, `shaft-vs3`) |
| `m_dev` | 0, 1 | decline advance 34 → 50 m of depth per year |
| `m_water` | 0, 1, 2 | none → tailings reclaim → reclaim + extra intake |
| `m_tailings` | 0, 1 | `tsf-cell5` built |
| `tu1_closed`, `tu2_closed` | 0, 1 | decline closed (both at once is rejected) |
| `fan_vs2_off` | 0, 1 | `fan-vs2` failed |
| `pumps_failed_p150` | 0, 1, 3 | failed pumps at `ps-p150` |
| `inflow_factor` | 1.0, 2.18 | 2.18 gives the design inflow 430 m³/h |
| `grade_gpt` | 2.05, 1.76 | mean feed grade (stope grades are scaled by `grade_gpt / 2.05`) |
| `line_down` | 0, 1, 2, 3 | number of the plant line stopped for repair |
| `revision`, `label` | integer, string | incremented and named by the Stand on every change |

The Stand writes all knobs with one `PUT /api/2/things/kz.sekis:scenario/features`. The simulator and the advisor read the thing every second and act on a new `revision`. No code or container change is involved. `sekis-setup` resets the thing to defaults on every `make stand`.

### 3.2 Presets and actions (Stand panel «Сценарии»)

| Button (Russian) | Id | Effect on knobs |
|---|---|---|
| Базовый режим | `base` | all defaults; clears the undo stack |
| Цель 1,2 млн т/год (ступень +200 тыс. т) | `step1200` | `target_ktpa = 1200`, `m_plant = max(m_plant, 1)` |
| Цель 2,0 млн т/год | `step2000` | `target_ktpa = 2000`, `m_plant = max(m_plant, 2)` |
| Цель 2,5 млн т/год | `step2500` | `target_ktpa = 2500`, `m_plant = 3` |
| Снять узкое место | `advisor_next` | applies the advisor's next measure (one knob +1) |
| Применить все меры | `advisor_all` | applies the whole remaining sequence |
| Закрыть уклон ТУ-2 / Открыть | `close_tu2` | toggles `tu2_closed` |
| Закрыть уклон ТУ-1 / Открыть | `close_tu1` | toggles `tu1_closed` |
| Отказ вентилятора ВС-2 / Восстановить | `fan_vs2_fail` | toggles `fan_vs2_off` |
| Отказ одного насоса +150 / Восстановить | `pump_one_fail` | `pumps_failed_p150` 0 ↔ 1 |
| Обесточена насосная +150 / Восстановить | `pump_station_fail` | `pumps_failed_p150` 0 ↔ 3 |
| Паводок: приток 430 м³/ч / Отменить | `flood` | `inflow_factor` 1.0 ↔ 2.18 |
| Содержание 1,76 г/т / Вернуть 2,05 | `grade_drop` | `grade_gpt` 2.05 ↔ 1.76 |
| Остановить линию № 2 / Запустить | `line2_down` | `line_down` 0 ↔ 2 |
| Шаг назад | `undo` | restores the knob set before the last change |
| Сброс | `reset` | same as `base` |

Undo: every toggle is its own undo; «Шаг назад» pops a stack of previous knob sets kept by the Stand service (50 deep); «Сброс» restores the baseline. Each measure knob also has − and + buttons in the panel.

### 3.3 What changes, and where it is seen

| Scenario | Twins that change | In the 3D scene and section | In panels |
|---|---|---|---|
| `step1200` alone | `plant-line-1..3.rated`, `plant.capacity_ktpa`, `advisor.*` | plant lines brighten; nothing else moves | bars: plant 1200, haulage 926 binding; gold gain 0; stockpile days fall |
| `advisor_next` on haulage | `truck-06`, `truck-07` leave `parked` and are `held_vent` (369.9 m³/s needed, 322 supplied); `mine.state = restricted_air`, `mine.units_held_vent = 2`; `mine.air_demand_m3s` stays 317.2 (the working units) | the two new trucks line up at the TU1 portal | haulage bar 1388; ventilation bar 958 → 926, binding; achievable stays 926; next measure: ventilation, naming trucks 06 and 07 |
| measure on ventilation | `fan-vpv`, `raise-vpv` (`running`, `in_service`), `mine.air_supply_m3s = 427`, level `air_flow_m3s`; held trucks return to work, `decline-tu1.trucks_on_ramp` | new airflow arrows down the VPV raise; level tint from amber to normal; two more trucks enter TU1, bays show waiting trucks | ventilation bar 1805 (1667 with the full set for 1.2 Mtpa); plant 1000 binding, target reached |
| measure on stopes | next stope leaves `standby`; `lhd-05`, `rig-03` active | stope box changes colour through its cycle; blast flash at the shift change | stopes bar 1279 |
| measure on water / tailings | `water.reclaim_m3h`, `water.deficit_m3h`; `tsf-cell5.state`, `tailings.years_left` | reclaim pipe from tailings to plant animates; new cell appears | water bar; years of storage |
| `close_tu2` | `decline-tu2.state = closed`; trucks 01–04 `decline = tu1`; `ore_hoisted_tph` falls about 10 % (baseline) | TU2 turns red and empties; all trucks on TU1, queues in bays | haulage 834; stockpile days fall |
| `fan_vs2_fail` | `fan-vs2.state = failed`; `mine.air_supply_m3s = 252`; `truck-03..05` `held_vent`, `lhd-04` `standby_vent`, `stp-000-1` `standby`; `mine.state = restricted_air`, `mine.air_demand_m3s = 238.6` | VS2 arrow disappears; levels amber; held trucks line up at the portal | ventilation bar 374, binding (trucks 01 and 02 on three stopes); the simulator hoists 378 kt/yr |
| `pump_one_fail` | `ps-p150.pumps_available = 2` | one pump icon red, station still green | no change in bars (redundancy) |
| `pump_station_fail` | `ps-p150.state = failed`, `sump_level_pct` rises, `hours_to_overflow` counts down; later `mine.flood_volume_m3`, `lvl-m050` then `lvl-000` `flooded`, their stopes `flooded` | sump bar fills, water plane rises on the lower levels, flooded stopes blue | dewatering row turns binding when a production level floods |
| `flood` | `mine.inflow_m3h = 430`, pumps run together, `mon-volchevka.discharge_m3h` about 238, state `exceeded` | thicker water flow in the cascade; outfall marker red | water row: discharge above the permit |
| `grade_drop` | stope `grade`, `rom-stockpile.grade`, `plant.feed_grade`, `recovery_pct`, `gold_poured_oz_day` | stope grade colouring shifts | gold falls from about 56 to 47.8 koz/yr at 1000 kt/yr |
| `line2_down` | `plant-line-2.state = off`, `plant.feed_tph` falls by a third, stockpile grows | line 2 grey | plant bar 667, binding; next step «запустить технологическую линию № 2 после ремонта» (`line_down` → 0), expansion measures after it |

The advisor recomputes within 3 seconds of a knob change, so bars and the «Что изменилось» list respond at once; the moving objects follow within one truck cycle (52–58 real seconds).

### 3.4 The module: Expansion Advisor (`sekis-advisor`)

Inputs, read from Ditto every second: attributes of fleet, fans, pumps, plant lines, dams (payloads, kW, duties, capacities); live features (which units are active, failed pumps, flooded levels, stockpile, stored tailings, decline bottoms); the scenario thing. Norms come from `params.json`.

The module answers the question of the Concept over the horizon 2027–2036, not for one year: whether, and in which steps, processing can be raised from 1 Mtpa to 1.2, 2.0 or 2.5 Mtpa, which link limits each step, and how long each target holds. Code: `sekis/advisor/engine.py` (constraint loop, report), `sekis/advisor/horizon.py` (horizon and economics), `sekis/advisor/wording.py` (Russian text).

Algorithm (theory of constraints, deterministic):

1. Compute the eight capacities (section 2.3) for the current state. Round each to 1 kt/yr.
2. The binding link is the smallest; ties are broken in the order haulage, ventilation, stopes, development, dewatering, plant, water, tailings.
3. If the binding capacity is at or above `target_ktpa`, stop. Otherwise, if a disturbance that an operational action removes is active (`line_down`, `tu1_closed`, `tu2_closed`, `fan_vs2_off`, `pumps_failed_p150`), the next step removes the one whose removal raises the achievable rate most (ties in that order), through its own knob: «запустить линию № 2 после ремонта», «открыть уклон ТУ-2», «восстановить вентилятор ВС-2», «восстановить насосы … и откачать воду». Otherwise the next measure is one more stage on that link's knob (haulage → `m_haul`, ventilation → `m_vent`, stopes → `m_stopes`, development → `m_dev`, plant → `m_plant`, water → `m_water`, tailings → `m_tailings`; dewatering → restore pumps). Apply it virtually and repeat. If the link has no stage left, stop and report the achievable rate. A lower grade (`grade_gpt` below `plant.grade_base`) and a flood inflow (`inflow_factor` > 1) are not removed by any action: the report states them under `conditions` and the gold and water figures use them. This sequence, at the depth and with the storage of the epoch, is the ladder of step 4 and the «Следующая мера».
4. Ladder: for each target 1000, 1200, 2000, 2500, starting from the baseline measure set (all `m_*` = 0) with the current disturbances: the sequence of (binding link, step, capacity before) of step 3, the figures of the state it ends in at the epoch (achievable rate, gold, air, water, tailings years, KPIs), its `horizon` (step 5) and its ten-year `economics` (step 6). Every step carries the time it would really be in service (`lead_years`, `in_service_year`, `in_service_when`, `in_service_text`, e.g. «в работе с середины 2027 г. (срок ввода 0,5 года, решение не позднее начала 2027 г.)»).
5. Horizon (`horizon.Horizon.plan`), for a target from a start state, in half-year steps (`ladder.horizon.steps_per_year`) from 1 January 2027:
   1. *Lead times.* The measures of the sequence of step 3, and the stages of the current knob set in the projection, are decided on 1 January 2027 and come into service after their lead times (`ladder.<knob>.lead_years`, one per stage; a stage never before the stage below it). A repair of a disturbance is an operational action and takes effect at once; every removable disturbance of the start state is repaired then, and flooded levels with sound pumps are pumped out. Conditions (grade, inflow) last the whole horizon. Times are rounded up to the half-year grid. The Stand still switches knobs at once (a what-if); the horizon is what the plan would really do.
   2. *Look-ahead.* Before each step the planner takes every measure decided so far as built and evaluates the chain at the mid depth of the step (the centroid less half a step of ore at the needed rate) with the storage left. The needed rate is what the plant in service can take (plant and water links), at most the target, so mine-side measures are not bought before the plant can use them. The tailings link over the horizon is the storage left for one step (the free volume over half a year), not the three-year rule of 2.3 item 7: the lead time of each storage stage is explicit. If the chain falls short, the constraint loop of step 3 runs again at these conditions and each further measure is scheduled to be in service at the start of the step, never before its lead time after the epoch: its latest decision is `time − lead_years`.
   3. *Measures beyond the knobs* (analytic only; they have no twin and the simulator never sees them, `capacity` module docstring): haulage over the horizon adds one truck at a time, `State.extra_trucks` — the next truck of the registry, and beyond the twelve of the registry one more truck of model `ladder.depth_trucks.model` (AD45) on the decline with fewer trucks, a tie to the deeper design bottom (TU1); and when the new cell is full, the second tailings stage `State.tailings_extra_t` = `tsf.measure_X2_t` (6 Mt, lead `tsf.measure_X2_lead_years`; sized like the new cell, not published). The rule that keeps haulage up with depth is therefore: one more truck whenever the haulage of the fleet at the step's depth falls below what the plant needs. From the haulage formula of 2.3 the report states the equivalent «one truck per N metres» (`depth_rule`): the tonnage of one more truck over the loss of fleet tonnage per metre over one floor (`level.floor_height_m`); at +75 m: 88 m with the 7 trucks of 1.2 Mtpa, 58 m with the 10 of 2.0 Mtpa, 47 m with the 12 of 2.5 Mtpa.
   4. *No stage left.* When the loop runs out of stages, the target cannot be held from that step on; the moves after the best rate reached are dropped, so nothing is bought that would not raise the rate (a truck that would wait for air). The step and the link with no stage left are recorded (`failure_year`, `failure_link`).
   5. *Flows of a step.* The mine hoists the smallest of its links (haulage, ventilation, stopes, development, dewatering) at the mid depth of the step (a second pass at the depth the first pass implies). The plant mills the smallest of its capacity, the water link, the storage left and the ore available (hoisted plus the ROM stockpile). The stockpile takes the difference; the mine hoists no more than the plant mills plus what restores the stockpile to its opening tonnage. The centroid drops by the ore hoisted (`capacity.centroid_after`), the dams fill with the ore milled in their order and then the second stage, gold is poured from the ore milled at the grade of the state. The binding link of a step is the plant side (plant or water) when the plant is full, the mine's binding link when the mine and stockpile limit, tailings when storage does.
   6. *Year rows* (`rows`): ore milled (`achievable_ktpa`) and hoisted, the binding link of the half-year with the larger shortfall, the mine's own binding link and capacity, `target_met`, centroid, trucks in service, gold by year and cumulative, tailings stored and free, stockpile, the measures entering service that year, the two halves, and a `note` for a year without storage and for the year the centroid passes the design bottom of a decline (the haulage formula treats the centroid as reachable, decision 9.5).
   7. *Hold analysis*: `reached_year` (first year the target is met), `held_to_year` (last year of that run), `holds` (held to 2036), `lost_year`, `lost_link`, `failure_link`, the label «держится до N г.» (or «не достигается до 2036 г.») and the sentence `text` with the reason; `binding_runs` (the binding link by year in runs), `storage_note` (the storage stages with their dates, and the storage still missing to 2036 when it runs out, `storage_short_kt`).
6. Economics over the horizon (section 11 item 3): the extra gold of the plan against a reference, the mine as it is (no measure, no disturbance, the conditions of the start state) with only the storage stages it needs to keep running. By year: gold, reference gold, the gain, its revenue at `econ.gold_price_usd_oz`, its margin at price less `econ.aisc_usd_oz`, the corporate income tax on that margin at `econ.cit_rate` (no deduction for capex; AISC already contains the mineral extraction tax, which the H1 2026 RNS counts in cost of sales), the capex schedule — the published US$125 m (`econ.capex_expansion_usd_m`) spread evenly over the lead time of the first plant stage that reaches 2.0 Mtpa (2027 and 2028), and apart, as an assumption not published, trucks at `econ.truck_capex_usd_m` and storage at `econ.tsf_capex_usd_per_t` net of the reference's storage — cash and cumulative cash, each with and without the assumed costs, before and after tax, and the NPV at `econ.discount_rate_pct` (cash at the end of each year, discounted to 1 January 2027). The payback year is the first year after which the cumulative cash stays at or above zero; it is given only for a target held to 2036 («не указывается: цель не удерживается до 2036 г.»), and not for a variant with no outlay («не считается: капзатраты не раскрыты»). Not costed and listed (`not_costed`): the +200 kt step, the ventilation measures, the stoping front, development, water. Caveats in the text: constant price and AISC; no financing, working capital or depreciation.
7. Projection (`projection`): the horizon of the current target from the current state (step 5 with the current knob stages as decided measures and the remaining sequence after them), with its economics. With the full measure set of a target it equals that target's ladder row; with the baseline knobs and the default target it equals the 1000 row.
8. Effects list: for the last knob change, the difference in each link capacity and KPI (before → after), in Russian sentences for «Что изменилось»; a change of the target adds the target's hold label and ten-year economics after tax.
9. KPIs are steady-state values of the selected regime (water deficit, discharge, permit share, stockpile flow, dewatering margin now and after one more pump failure, `dewatering_margin_next_failure`, `pumps_standby`, `dewatering_reserve`); the Stand labels them «в установившемся режиме». The ROM stockpile flow is the mine rate (smallest mine link over 360 days) against the plant feed (plant capacity, or less when the water sources at that hoisting rate carry less: `WaterBalance.feed_limit_tph`, the simulator's throttle; zero with no tailings storage) over 365 days; `stockpile_days_left` is the stock over the net draw, `None` when the stockpile does not fall.

Expected sequences at the epoch with the parameters of 2.8 (unit-tested):

| Target | Sequence of binding links from the baseline | Achieved at the epoch | Gold at 2.05 g/t |
|---|---|---|---|
| 1000 | haulage, ventilation | 1000 (plant) | 56.0 koz |
| 1200 | haulage, ventilation, plant, water, stopes, tailings | 1200 (plant) | 67.2 koz |
| 2000 | the six above, then plant, stopes, ventilation, haulage, water, development | 2000 (plant) | 112.0 koz |
| 2500 | the twelve above, then plant, stopes, haulage | 2500 (plant) | 140.0 koz |

Two steps of these sequences do not raise the achievable rate by themselves, and the advisor says so in the measure text. The first step (trucks 06 and 07) leaves it at 926 kt/yr: the trucks wait for air until the second step starts `fan-vpv`. The eighth step of the 2000 and 2500 ladders (stopes 5 → 8, three more LHDs) needs 433.0 m³/s against 427, holds truck 07 and lowers the chain from 1279 (stopes) to 1161 kt/yr (ventilation) until the ninth step starts `fan-vs3`.

Sustainable baseline: 926 kt/yr, 51.9 koz (the plant mills 1000 kt/yr only while the 94 264 t stockpile lasts: 167 t/day net draw, about 564 days). With disturbances the sequences start with the repairs, e.g. `fan_vs2_fail` for 1000: restore fan VS2, haulage, ventilation; `line2_down`: restart line 2, then the sequence of the target.

Lead times and horizon measures (parameters added on 16 October; `A` = ASSUMPTION with the reasoning in `params.json`):

| Id | Value | Source |
|---|---|---|
| `ladder.m_haul.lead_years` | 0, 0.5, 0.5, 0.5 | A: trucks are bought; delivery and commissioning take months |
| `ladder.m_stopes.lead_years` | 0, 0.5, 1.0, 1.0 | A: equipment half a year; further stopes need access and preparation |
| `ladder.m_vent.lead_years` | 0, 1.0, 2.5 | A: fan on the proposed raise VPV (F A2) about a year; a new shaft VS3 2–3 years |
| `ladder.m_dev.lead_years` | 0, 0.5 | A: a second development crew |
| `ladder.m_plant.lead_years` | 0, 0.5, 2.0, 2.0 | A for stage 1 (equipment ordered in H1 2026, F D1); stages 2–3 the company's "within 24 months" (F D1, Q3 2025 RNS) |
| `ladder.m_water.lead_years` | 0, 0.5, 1.0 | A: reclaim pipeline; a new intake also needs a water-use permit |
| `ladder.m_tailings.lead_years` | 0, 1.5 | A: a new cell takes 1–2 years |
| `ladder.depth_trucks.model`, `.lead_years` | AD45, 0.5 | A: the model of trucks 05–12, bought like them |
| `ladder.horizon.steps_per_year` | 2 | A: half-year planning steps |
| `tsf.measure_X2_t`, `tsf.measure_X2_lead_years` | 6 000 000 t, 2.0 | A, not published: a second cell or a raise, sized like the new cell |
| `econ.cit_rate` | 20 % | A tagged only for want of a facts-file row: Tax Code of the RK of 18.07.2025 No. 214-VIII, art. 357 p. 2 sp. 5; the H1 2026 RNS: "the Kazakhstan corporate income tax rate of 20%" |
| `econ.discount_rate_pct` | 5 % real | A: the rate most often quoted for gold projects; none published |
| `econ.truck_capex_usd_m` | 1.5 US$m | A, not published: a 45 t underground truck |
| `econ.tsf_capex_usd_per_t` | 1.0 US$/t | A, not published: new tailings storage |

The horizon with these parameters (unit-tested, from the baseline):

| Target | Reached | Held to | Binding link by year | Ends because | Gold 2027–36 (gain) | Margin after tax | Capex published / assumed | NPV 5 % after tax, published / with assumed | Payback |
|---|---|---|---|---|---|---|---|---|---|
| 1000 | 2027 | 2036 | plant all years | — | 560.0 koz (+106.7) | US$223.6 m | — / 9.0 | 162.7 / 155.7 | 2028 with assumed costs |
| 1200 | 2028 | 2036 | plant (2027 short: lead times) | — | 661.1 koz (+207.8) | US$435.5 m | — / 12.0 | 322.2 / 312.3 | 2028 with assumed costs |
| 2000 | 2030 | 2034 | 2027 ventilation; 2028 plant; 2029 ventilation; 2030–34 plant; 2035–36 tailings | storage: the second stage is full in 2035 (2.7 Mt more needed to 2036) | 849.7 koz (+396.4) | US$830.9 m | 125 / 21.0 | 525.2 / 506.9 | not given (not held) |
| 2500 | 2030 | 2030 | 2027–29 ventilation; 2030 plant; 2031–34 haulage; 2035–36 tailings | haulage at depth: two AD45 beyond the registry fit the 667 m³/s of VS3, a third would wait for air | 849.7 koz (+396.4) | US$830.9 m | 125 / 19.5 | 539.7 / 521.6 | not given (not held) |

Above 1.2 Mtpa the storage of the model (3.2 Mt free at the epoch, the new cell and the second stage, 15.2 Mt) bounds the ore of the ten years: 2.0 and 2.5 Mtpa mill the same 15.2 Mt, the higher target only earlier. Shaft VS3 (2.5 years) is the critical path of both: until mid-2029 the trucks and stopes of the plan wait for air.

Outputs:

- Features of `kz.sekis:advisor` (published to MQTT on change and every 30 s): `binding_link`, `next_measure` (a knob name, or `restart_line`, `open_tu1`, `open_tu2`, `restore_fan_vs2`, `restore_pumps` for a repair, or `none`), `measures_needed`, `target_ktpa`, `achievable_ktpa`, `cap_haulage_ktpa`, `cap_ventilation_ktpa`, `cap_stopes_ktpa`, `cap_development_ktpa`, `cap_dewatering_ktpa` (0 when not limiting), `dewatering_margin`, `cap_plant_ktpa`, `cap_water_ktpa`, `cap_tailings_ktpa`, `gold_koz_year`, `gold_gain_koz_year`, `air_demand_m3s`, `water_deficit_m3h`, `discharge_m3h`, `tailings_years_left`, `stockpile_days_left`, `report_revision`.
- Full report as JSON at `http://sekis-advisor:8089/report` (ladder for the four targets, projection, effects, calibration table), proxied by the Stand as `/api/advisor`. Schema `sekis.advisor.report/2`: steps carry `kind` (`measure` | `disturbance`) and `lead_years`, `in_service_year`, `in_service_when`, `in_service_text`; keys `conditions`; KPIs `stockpile_mine_tpd`, `stockpile_plant_tpd`, `stockpile_net_tpd`, `stockpile_trend`, `dewatering_margin_next_failure`, `pumps_standby`, `dewatering_reserve`; `sustainable_baseline.plant_ktpa`, `stockpile_net_tpd`, `text`; ladder rows `horizon` and `economics`; the horizon (ladder rows and `projection`): `schedule` (entries `time`, `year`, `kind` = `measure` | `disturbance` | `depth_truck` | `storage`, `link`, `knob`, `stage`, `set`, `origin` = `current` | `ladder` | `horizon`, `lead_years`, `decided`, `text`, `trucks`, `storage_kt`, `when`, `when_short`, `in_service_text`), `sequence_schedule`, `rows`, `binding_runs`, `reached_year`, `held_to_year`, `holds`, `lost_year`, `again_year`, `lost_link`, `failure_year`, `failure_link`, `label`, `text`, `depth_rule`, `trucks_end`, `depth_trucks`, `trucks_beyond_registry`, `storage_runs_out_year`, `storage_short_kt`, `storage_note`, `target_missed_year`, `gold_total_koz`; `economics`: `years`, `totals`, `variants` (`disclosed`, `with_assumed`, each with `capex_usd_m`, `cash_usd_m`, `npv_usd_m`, `payback_year`, `payback_reason`, `payback_text`, `pre_tax`), `capex_items`, `reference_capex_items`, `not_costed`, `capex_disclosed`, `capex_usd_m`, the bases (`price_basis`, `aisc_basis`, `tax_basis`, `discount_basis`, `capex_note`, `assumed_note`, `reference_text`, `caveats`, `summary`); calibration rows `kind_name`, `basis`, `basis_name`, `basis_note`, `reported_max`, `source`, `source_urls`, `run` (simulator rows). The one-year `payback_years` and the projection's `storage_measure` are gone. In fixture mode the Stand builds the same report with `sekis.advisor`.
- Action: `POST /apply` with `{"mode": "next" | "all"}` returns the knob changes; the Stand writes them to the scenario thing. This is how the module changes the operation of the mine.

### 3.5 Ventilation on demand (second decision module, 17 October)

Before 17 October the main fans always ran at their design duty, 322 m³/s and 1 120 kW, whatever the mine did. Ventilation on demand (VOD) is a real-time control function in the simulator (`sekis/sim/vod.py`): every simulated minute it sets the duty of the main fans in service from the air demand of the units actually in work, so the fans deliver less in the shift changes, the meal hours, the blast windows and while trucks are under repair, and it decides when a unit may enter work. It changes the operation of the mine (fan duties, the air of every level, the energy, and when units are admitted); it does not change the maximum supply, so the hold rule of 2.6, the advisor's ventilation capacity and the calibration stay as they are.

Knob: `vod_enabled` on `kz.sekis:scenario` (number, 1 = on, 0 = off), **on by default**. Reasons: it is the decision module, so the Stand should show it working from the first minute; it costs no production (the units are admitted before they enter, the hold rule still works on the design supply, and the 60-day baseline hoists 933 kt/yr with it against 931 kt/yr without, the spread of the run); and the comparison stays easy without switching, because the panel carries the energy at the design duty beside the energy with VOD. The Stand button «Вентиляция по потребности: вкл/выкл» (preset `vod_toggle`) toggles it; it is a scenario change like the others, with «Шаг назад» and «Сброс». The preset needs two entries in `team/stand/server.py` (`KNOB_VALUES["vod_enabled"] = (1.0, 0.0)` and `TOGGLES["vod_toggle"] = ("vod_enabled", 0.0, "Вентиляция по потребности выключена", "Вентиляция по потребности включена")`); without them the knob stays at its default and the button reports the server's answer.

The rule (parameters below):

1. Units in work. During a productive block every truck and LHD in service that is not held by the hold rule and not under repair is in work (a truck waiting at the ROM pad for ore can leave at any moment, so its air is reserved). Outside the blocks only the units still out on a trip and an LHD loading a truck are. Demand = `vent.q_base + vent.q_diesel × kW of the units in work` (the norm of 2.6), shown per level by `level.air_required_m3s` (units on the level) and on the mine by `vod_demand_m3s`.
2. Setpoint = demand × (1 + `vod.margin_pct`), between the lowest duty of the fans in service (`duty_min_m3s`: the published 63 m³/s of the VS2 fan, half the design duty of the others) and their design duty `duty_m3s`. VOD never sets a fan above its design duty, even where the rating `duty_max_m3s` is higher (VS2: 88 m³/s), so the supply of the hold rule is the ceiling. With several fans every fan runs at the same fraction of its design duty; a fan at its lowest duty stays there and the others take the rest (`capacity.vod_split`). The lowest total at baseline is 75 + 51 + 63 = 189 m³/s, 309 kW.
3. Raising: towards the setpoint at once, at most `vod.ramp_pct_per_min` of the design duty per minute for each fan. `vod.pre_vent_min` before a productive block starts the setpoint already covers every unit that will work in it.
4. Admission: a unit enters work only when the air delivered covers it, so the delivered air never falls below the demand of the units in work. A truck that does not fit waits at the ROM pad (`held_vent`), an LHD at its stope (`standby_vent`), until the fans have ramped up (`mine.vod_units_waiting`). With the pre-ventilation this happens only when units are added during a block: a truck back from repair, a scenario change. The hold rule stays the last resort.
5. Lowering: only after the demand has stayed below the delivered air for `vod.min_on_min` (minimum on-time), then at the ramp rate, never below the setpoint.
6. Fan laws: pressure with the square and power with the cube of the flow on the fixed airway resistance of the design point (`capacity.fan_pressure_pa`, `fan_power_at_kw`; efficiency held at `vent.fan_efficiency`). Energy and the saving against the fans at their design duty are integrated per minute: since 08:00, since the start of the shift and over the last 24 hours; the saving also in tenge at `vod.tariff_kzt_kwh`.

Switched off, the fans run at their design duty and the saving is 0. A fan that fails drops out at once; a fan that starts (`m_vent`) takes its share of the delivered air.

Calibration and figures (unit-tested in `tests/test_vod.py`):

- Full work of the baseline fleet needs 317.2 m³/s, + 5 % is 333 m³/s, above the design duty: the fans run at 322 m³/s (`vod_state = full`), so checks C6 and C7, the advisor's 322 m³/s and the hold rule are unchanged. With one truck of five under repair the demand is 299.0 m³/s and the fans run at 313.9 m³/s (1 038 kW).
- In the blast windows and the shift changes the demand is the base 180 m³/s and the fans come down to their lowest duty, 189 m³/s (309 kW); the duty is back before the next block.
- Over seven days the delivered air is at or above the demand of the units in work in every minute; no unit waits at a block start.
- Baseline, 60 simulated days: the fans use 21 214 kWh/day against 26 880 kWh/day at the design duty, a saving of 5 666 kWh/day (21 %), about 2.07 GWh/yr and 72 million tenge/yr at 35 ₸/kWh (365 days; the fans run every day).

Twins (registry, decision 11.4): `main_fan` attribute `duty_min_m3s` and feature `duty_setpoint_m3s` (the setpoint the flow moves to); `air_flow_m3s`, `pressure` and `power_kw` are the values now. `mine` features `vod_state` (string: `off`, `demand`, `ramp`, `full`), `air_delivered_m3s`, `vod_demand_m3s`, `vod_units_waiting`, `fan_power_kw`, `fan_energy_today_kwh`, `fan_saving_today_kwh`, `fan_saving_today_kzt`, `fan_energy_shift_kwh`, `fan_saving_shift_kwh`, `fan_energy_day_kwh`, `fan_saving_day_kwh`. Scenario knob `vod_enabled`. `mine.air_supply_m3s` stays the design supply of the fans in service; `mine.air_margin_pct` stays its margin over the demand of the units not held.

Stand: the panel «Вентиляция по потребности» (`stand/web/js/panels/vod.js`, section `#vod`): the switch, the state, the delivered air against the demand, the fan power against the design duty, the energy and the saving since 08:00 and over 24 hours with a yearly estimate (24 hours × 365), the air of every open level (bar: delivered, tick: needed; leakage levels apart), the fans (flow, setpoint, share of the design duty, pressure, power), and the rule in one paragraph. In fixture mode the Stand runs the same control law (`FanControl`) over the shift calendar with the trucks at their availability.

| Id | Value | Source |
|---|---|---|
| `vod.margin_pct` | 5 % | A: control margin over the demand for measurement error and leakage variation |
| `vod.ramp_pct_per_min` | 5 % of the design duty per minute | A: the network pressure settles; floor to full in about 10 min |
| `vod.min_on_min` | 30 min | A: the fans do not hunt with every trip or pause |
| `vod.pre_vent_min` | 15 min | A: fresh air reaches the far faces (2–3 km at 2–4 m/s) before a block starts |
| `vod.tariff_kzt_kwh` | 35 ₸/kWh excl. VAT | A: no 2025–2027 tariff of the East Kazakhstan supplier found; 2024 tariffs for legal entities were 32.60 (Zhetysu) and 40.56 ₸/kWh excl. VAT (Akmola), bizmedia.kz 24.05.2024 |
| `vent.vsd_min_share` | 0.5 of the design duty | A: lowest duty of a fan without a published range under variable-speed control; VS2 keeps its published 63 m³/s (F A5) |
| `vent.leakage_share` | 0.2 of `vent.q_base` | A: leakage and through-flow over the levels not in use (2.6) |

## 4. Mine visualization

### 4.1 Technology

A three.js scene and an SVG long section, both in the Stand page served by `sekis-stand` on port 8088, and the 3D scene embedded in the Grafana dashboard `sekis-overview` through an iframe.

Reasons: the target machine is a clean Ubuntu 24.04 amd64 machine with 8 vCPU, 16 GiB and no GPU, so the scene must be small and under our control (a Unity build is not small enough); three.js is one vendored file with no build step; the SVG section is the fallback when WebGL is unavailable and puts every label and value into the DOM as text, which also makes them available to assistive technology.

- Vendored in `team/stand/web/vendor/three/`: `three.module.min.js`, `OrbitControls.js`, `CSS2DRenderer.js` (three.js r160, MIT, with its LICENSE file), loaded through an import map. System fonts only.
- The page shows both views side by side on wide screens (3D left, section under it or in a tab on narrow screens). If the WebGL context cannot be created, the 3D area shows the section instead.

### 4.2 Geometry: sourced and schematic

`team/model/geometry.json` is generated by `sekis/geometry.py` from `params.json`, `registry.json` and the terrain assets in `team/model/terrain/` (`heightmap.json`, `texture.jpg`, `features.json`), which the offline tool `team/tools/build_terrain.py` builds from downloaded open data; the tool is not run at build or run time, and `team/model/terrain/ATTRIBUTION.md` carries the sources, licences and notices. Scene frame: X east, Y up = elevation in metres above sea level, Z south; 1 unit = 1 m; vertical scale equals horizontal scale. The horizontal origin is the mine point 50°19'43.17" N, 82°35'47.81" E: X = UTM 44N easting − 613 640.00, Z = 5 576 392.36 − northing (EPSG:32644; grid north is 1.23° east of true north). Every object carries `"sourced": true|false` and a `source` string that says what its position and size rest on.

Sourced, the surface (real, from open data):

- Ground: Copernicus DEM GLO-30 (TanDEM-X, acquired about 2011–2015), 65 × 65 vertices at 62.5 m over the 4 × 4 km square around the mine point (cell means), with a 25 × 25 inset at 15.625 m over the old pit; `terrain` block of `geometry.json`.
- Image: Sentinel-2C L2A true colour of 30 September 2026 (scene S2C_44UPA_20260930_0_L2A, 10 m), one 512 × 512 north-up texture of the same square.
- Positions from OpenStreetMap (extract of 16 October 2026) checked against the image: the old pit outline, the two settling ponds, the five tailings cells (dams 4, 2, 3 on the north and the two middle cells; which cell carries which number is not published and is assumed), the industrial zone and the building cluster taken as the plant site, the stream taken as the Volchevka (65 m from the pit's south edge, 796 m long; the facts give 60 m and 735 m), the Sekisovka river (157 m from the pit; facts: about 150 m), the village, and the road graph the truck roads follow. The tailings facility is anchored at its registry coordinates (bearing N 33° E, 1.51 km).
- Ground line of the long section: `profile`, the terrain every 10 m of X in the plane of the ore zone.

Carved from the documents: the DEM predates the end of open-pit mining (2016) and shows the pit floor at 389.7 m. Inside the OSM pit outline the ground is the designed final pit: floor at +320 m (the TU2 portal elevation, the portal standing on the pit floor), wall at the overall slope (50.3°) of 15 m benches with 70° faces and 7 m berms (`pit.*` in `params.json`), carved ground = min(DEM, shell). The TU2 portal is the centre of the carved floor; the pit ramp (8°) and the bench crest lines lie on the carved ground.

Sourced, underground (facts file): every elevation (portals +430 and +320; shaft bottoms +325 and +340; raise ranges; levels at +320, +150, +100 and the 50 m floor height; decline bottoms −50 and −34; design bottoms −200, −300; pump stations at +150, −200); decline slope 8° and section 18 m²; airway sections; pond area 755 m² and depth (the boxes keep the documented area inside the larger mapped ponds); dam capacities (each prism's crest holds its capacity above the ground). Shaft collars stand on the DEM ground of their position; the registry collar +430 is kept as `documented_top` (VS1 ground 441.3 m, VS2 439.2 m, VS3 429.7 m). The TU1 portal (+430) stands where the ground is 431.1 m.

Stopes: vertical tabular blocks (the ore dips 70–90°), 50 m high (the floor), 6 m thick (`stope.thickness_m`, inside the 1.5–15 m of the ore bodies) and 106 m along strike, from the stope's 90 000 t at 2.83 t/m³.

Schematic (no mine plan is published; marked `plan position schematic` in `source`): all underground plan positions. The underground mine continues the ore body below the old open pit: the mine layout below is given in its own frame, whose origin `frame.layout_shift` (0, 62.5) is the centre of the carved pit floor, where the TU2 portal stands. The strike runs east–west (`frame.strike_azimuth_deg` 90, grid; about 91° true), along the long axis of the OSM pit outline (357 m east–west against 306 m north–south); no azimuth is published, so it remains schematic. The middle stope column lies under the pit centre and the outer columns run on along the strike beyond the rim at depth, as ore bodies do. Every decline leg keeps its 8° slope and its horizontal run of the earlier layout, so the decline lengths (TU1 5 245.7 m, TU2 3 736.7 m to the design bottom) and every chainage are unchanged, and so are the volumes of the −50 m and 0 m workings within 1 % (the flood thresholds of 2.7). Surface objects that are not identifiable in the 10 m image are placed on free ground and flagged `sourced: false`: ROM pad, parking yard, plant lines (inside the plant site), planned tailings cell 5 (free farmland east of the facility), the outfall on the Volchevka (at the stream's head by the ponds) and the river intake (the river point nearest the plant), the pipelines and the conveyor (schematic routes on the ground; the water supply along the roads). The Stand legend should read «Рельеф, карьер и наземные объекты — по открытым данным (Copernicus, Sentinel-2, OpenStreetMap); отметки и сечения выработок — по опубликованным данным; расположение выработок в плане — схема».

Mine layout (in the layout frame, X east along the strike, Z south; add `layout_shift` for scene coordinates). Cross-section from north to south: shafts and raises, the +320 m ventilation drive, the ore zone, the level drives, the pump chambers, the declines in the footwall.

- Ore zone along X from −300 to +300 at Z = 0, under the pit; three stopes per level centred at X = −200, 0, +200 (stopes at X −253…−147, −53…53, 147…253).
- Level drives along X at Z = +40 with crosscuts north to the stopes. The +320 m ventilation level carries no stopes and joins the shafts: its drive runs at Z = −100, under the pit's north wall with at least 35 m of rock above it (at Z = +40 it would cross the TU2 portal leg 6 m below the pit floor).
- TU2: portal on the pit floor centre (0, 0), portal leg 142.3 m south under the pit's south wall to the first turn at +300 m, then a zigzag in the plane Z = +142.3 between X = 0 and X = +355.8. TU1: the portal of the earlier layout (−288.8, −30) at +430 m, west of the pit; portal leg 85.4 m west and 128.1 m south (bend at +418 m) to the first turn at +400 m, then a zigzag in the plane Z = +98.1 between X = −374.2 and X = −18.4. Each zigzag turns at every 50 m of elevation, one leg running 50 / tan 8° = 355.8 m; level accesses join the level drive at the turns.
- VS1 at (−172.3, −210), VS2 at (+135, −182.5), VS3 at (−472.3, −210), VPV at (−115, −190), VHV TU1 at (−342, +68), VHV TU2 at (+270, +110), exhaust raises at (+320, +7.5); pump chambers at Z = +70, X = +100 (+150 m, −50 m) and +112 (−200 m). Coordinates are (X, Z). Shaft collars stand north of the pit (VS1 111 m, VS2 43 m from its outline), VS3 west of the ore zone and the exhaust raise east of it (149 m from the pit), off the OSM roads, heaps and the northern quarry; level connections that cross the ore zone pass between the stope columns or beyond them, and no vertical airway or pump station overlaps a stope in the long section.
- Mine water: from the +150 m station up a borehole to the +320 m level, along its drive to VS1, up VS1 and over the ground to the upper settling pond.
- Truck positions: the simulator computes `pos_x`, `pos_y`, `pos_z` from the same `geometry.json` (declines, the pit ramp and the surface roads over the terrain), so the views only place and interpolate.

### 4.3 What is drawn

| Object | Encoding |
|---|---|
| Stopes | colour by `state` (drilling grey-blue, awaiting_blast orange, ventilating haze, mucking gold, backfilling brown, standby dim, flooded blue); height of the filled part by `ore_remaining_t`; optional colouring by `grade` |
| Trucks, LHDs, rigs | small boxes moving along declines and drives, tweened between 2 s samples; colour by loaded or empty; red ring for `waiting_bay`, `held_vent`, `maintenance` |
| Declines | green when open, red when closed; bays as widened nodes |
| Airways and fans | arrows whose thickness follows `air_flow_m3s`; fan icon green, red or dashed (planned); levels tinted by air flow against requirement |
| Dewatering | sump as a bar filled to `sump_level_pct`; pipe pulses while `pumped_m3h` > 0; flooded levels get a water plane |
| Plant, stockpile | line boxes by `state`; stockpile cone scaled by `tonnes` |
| Tailings | each dam a prism filled to `fill_pct`; label «осталось N лет» |
| Monitoring points | marker green, amber or red by `state` |
| Shift and blasts | clock in the header; a flash on blasted stopes in the blast window |

Labels are HTML (CSS2DRenderer in 3D, `<text>` in SVG): name, state in Russian and one key value per object; at most 30 visible at once. Clicking an object opens its twin card (all features, attributes, links, the Ditto thing ID). Camera presets: «Рудник», «Уклоны», «Вентиляция», «Водоотлив», «Фабрика и хвосты».

The section projects the same geometry onto the X–Y plane with an elevation ruler, level lines labelled «гор. +150 м», and a surface strip with the plant, ponds and dams.

### 4.4 Data path

`sekis-sim` → MQTT `telemetry/sekis/<name>` → Ditto → `sekis-stand` reads `GET /api/2/things?ids=…` in batches of 40 every second and caches → the page polls `GET /api/state` every 2 s. Delay from simulator to screen is 2–4 s. The browser never holds a Ditto password.

### 4.5 Performance budget

At most 20 000 triangles and 150 draw calls (static geometry merged into at most 10 meshes); no textures except one 512 × 512 texture (the satellite image draped on the terrain, `terrain.texture`), no shadows or post-processing; the terrain mesh takes 8 192 triangles (65 × 65 grid), or 9 272 with the pit inset in place of its 72 coarse triangles; at most 5 translucent meshes; `antialias: false`, pixel ratio 1, canvas at most 1280 × 720 CSS pixels; rendering only while something moves, capped at 12 frames per second; three.js files under 1.5 MB. Target on software rendering (Chromium with `--disable-gpu --enable-unsafe-swiftshader`): at least 8 frames per second and under one CPU core.

### 4.6 View contract

Each view module (`scene3d`, `section2d`) exports `mount(container, geometry)` returning `{update(state), focus(thingId), dispose()}`; `app.js` owns fetching and calls `update` every 2 s. If `scene3d.mount` throws, `app.js` mounts the section in its place.

## 5. Runtime architecture

### 5.1 Services added (overlay `team/compose.yml`)

Paths in the overlay are relative to `deploy/compose/` (the directory of the first compose file), as in `examples/mine/compose.yml`.

| Service | Image | Role | Ports | Memory limit |
|---|---|---|---|---|
| `sekis-setup` | built from `../../team` as `team053/sekis:local` | one-shot: PUT 22 types and 96 things; resets the scenario | none | none |
| `sekis-sim` | `team053/sekis:local`, `pull_policy: never` | simulator; reads the scenario from Ditto, publishes to MQTT | none | 256m |
| `sekis-advisor` | same | the module; HTTP 8089 inside the network | none | 128m |
| `sekis-stand` | same | web Stand and API | `${OPENEGIZ_BIND:-127.0.0.1}:${STAND_PORT:-8088}:8088` | 128m |
| `grafana` (override) | unchanged | environment: `GF_AUTH_ANONYMOUS_ENABLED=true`, `GF_AUTH_ANONYMOUS_ORG_ROLE=Viewer`, `GF_PANELS_DISABLE_SANITIZE_HTML=true`, `GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH=/var/lib/grafana/dashboards/Sekisovskoye/sekis-overview.json` | 3000 | unchanged |

Only `sekis-setup` has `build:`. `sekis-setup` depends on `init` (completed); the other three depend on `sekis-setup` (completed) and have `restart: unless-stopped`. Health checks: `sekis-stand` answers `/healthz`; `sekis-sim` and `sekis-advisor` touch `/tmp/alive` every loop and the check fails when it is older than 30 s.

Dockerfile (`team/Dockerfile`): `python:3.12-slim`, `pip install --no-cache-dir -r requirements.txt` (`paho-mqtt==2.1.0`), copy `sekis/`, `model/`, `stand/`, `tests/` to `/app`, `USER nobody`.

Environment for the three services: `DITTO_URL=http://ditto-nginx:80`, `DITTO_USER=ditto`, `DITTO_PASSWORD`, `MQTT_HOST=mosquitto`, `MQTT_PORT=1883`, `INFLUX_URL=http://influxdb:8086`, `INFLUXDB_TOKEN`, `SIM_SPEEDUP=60`, `SIM_SEED=53`, `PUBLISH_SCALE=1.0`, `ADVISOR_URL=http://sekis-advisor:8089`.

### 5.2 Data paths

| Path | Detail |
|---|---|
| Simulator → twins | MQTT `telemetry/sekis/<name>`, Ditto protocol `modify` on `/features` |
| Advisor → twin | MQTT `telemetry/sekis/advisor` |
| Stand → scenario | `PUT /api/2/things/kz.sekis:scenario/features` (Ditto HTTP) |
| Simulator, advisor ← scenario and twins | `GET /api/2/things/…` (Ditto HTTP), every second |
| Twins → history | platform: Ditto events on MQTT `opentwins/#` → Telegraf → InfluxDB `default` / `mqtt_consumer` / `value_<feature>_properties_value`, tag `thingId` |
| History → dashboards | Grafana datasource `opentwins-influxdb` (Flux) |
| Stand API | `GET /api/state`, `/api/geometry`, `/api/scenario`, `/api/advisor`, `/api/params`, `/api/calibration`, `/healthz`; `POST /api/scenario` with `{"preset": id}`, `{"set": {knob: value}}` or `{"action": id}` where id is `undo`, `reset`, `advisor_next` or `advisor_all`; pages `/`, `/embed/scene`, `/embed/section` |

`GET /api/state` returns `{"sim_time": "...", "revision": n, "things": {"kz.sekis:truck-01": {"kind": "haul_truck", "name": "...", "parent": "kz.sekis:mine", "attrs": {...}, "f": {"state": "hauling_up", "payload": 30.0}}}}`.

With `STAND_FIXTURE=1` the Stand serves `team/stand/fixtures/state.json` and `advisor.json` instead of calling Ditto, so the page and both views can be built without the stack.

### 5.3 Grafana

Dashboards are files in `deploy/compose/grafana/dashboards/Sekisovskoye/` (the template's provider `openegiz` reads this directory with folders from the file structure; no provisioning change is needed):

| File / uid | Title | Content |
|---|---|---|
| `sekis-overview.json` / `sekis-overview` | Секисовское: обзор и решение | Text panel with `<iframe src="http://localhost:8088/embed/scene">`; stats (ore t/day, gold oz/day, air margin, stockpile days, tailings years); bar gauge of the eight `cap_*_ktpa` against `target_ktpa`; time series of ore hoisted, plant feed, gold; scenario `revision` and `label` as annotations |
| `sekis-underground.json` / `sekis-underground` | Секисовское: подземный рудник | truck states table, chainage of trucks on TU1 and TU2, trucks waiting in bays, air supply against demand, units held, sump levels and pumped flow, stope state timeline |
| `sekis-eco.json` / `sekis-eco` | Секисовское: вода и хвосты | water balance (mine water, site, plant, reclaim, deficit, discharge against the permit), pond TSS and sludge, dam fill, years of storage left |

Grafana opens on `sekis-overview` without a login (anonymous Viewer). The twins are also listed in the OpenEgiz app (Twins, Types). The Unity panel and `build/` are not used.

### 5.4 Run sequence (the whole README procedure)

```bash
sudo apt-get update && sudo apt-get install -y make
make stand
make stand-smoke
```

- `make stand`: `scripts/compose-env.sh`, `scripts/compose-preflight.sh`, the platform (`up`, tried twice before failing), then the overlay with `--build --wait --wait-timeout 600`, then `scripts/stand-wait.sh` (until `/api/state` lists 96 things, `enterprise.sim_day` grows and `/api/advisor` answers; 300 s limit), then `scripts/stand-urls.sh`, which prints `http://localhost:8088`, `http://localhost:3000` and the Grafana admin login.
- A marker `deploy/compose/.sekis` makes `make up`, `make down`, `make ps`, `make logs` include the overlay; `make clean` removes it.
- `make stand-test` runs the unit tests in the image. `make stand-twins` starts only the platform and `sekis-setup`.

Expected cold start on a clean Ubuntu 24.04 amd64 machine with 8 vCPU, 16 GiB and no GPU: 8–20 minutes (image pulls about 2.5 GB, the platform's extended-api build, Ditto start, our image build about 1 minute). The sum of all script timeouts is under 45 minutes, against a 75-minute limit. Memory: container limits total about 7.0 GiB (platform 6.5 GiB, ours 0.5 GiB), measured use about 4 GiB, leaving 8 GiB or more for the browser. Disk: under 5 GB.

### 5.5 Smoke check (`scripts/stand-smoke.sh`)

Exit code 0 only if all pass: (1) `scripts/compose-smoke.sh`; (2) Ditto holds 96 things in `kz.sekis` and 22 in `kz.sekis.type`; (3) InfluxDB has `value_chainage_m_properties_value` for `kz.sekis:truck-01` in the last 2 minutes; (4) `kz.sekis:advisor` has a non-empty `binding_link`; (5) scenario round trip: `POST /api/scenario {"preset":"close_tu2"}` → within 30 s `decline-tu2.state` is `closed` in Ditto → `{"action":"undo"}` → `open`; (6) the three dashboards exist and `GET /api/dashboards/uid/sekis-overview` answers 200 without credentials; (7) `/`, `/embed/scene`, `/vendor/three/three.module.min.js` answer 200; (8) no `http://` or `https://` reference other than `localhost` and the `www.w3.org` XML namespace strings in `team/stand/web` outside `vendor/`; (9) `/api/calibration` reports every analytic check as passed; (10) all `sekis-*` containers healthy.

Soak (`scripts/stand-soak.sh`, not in the README): 60 minutes at the 2.5 Mtpa measure set; fails if any container restarts, Ditto health leaves `UP`, or the delay from the simulator clock to `/api/state` exceeds 10 s.

## 6. Repository layout

```
team/
  SPEC.md                      this file
  Dockerfile, requirements.txt, compose.yml
  model/params.json            parameters with sources
  model/registry.json          types and things (section 1)
  model/geometry.json          generated scene geometry
  sekis/__init__.py, ditto.py, setup_twins.py
  sekis/capacity.py            link capacities, gold, water, tailings
  sekis/geometry.py            geometry generator
  sekis/sim/                   core.py, haulage.py, stopes.py, ventilation.py, water.py, plant.py, snapshot.py
  sekis/sim_service.py         MQTT publishing loop
  sekis/advisor/               engine.py, service.py
  stand/server.py              HTTP server and API
  stand/fixtures/              state.json, advisor.json
  stand/web/index.html, css/, js/app.js, js/panels/
  stand/web/js/scene3d/        three.js view
  stand/web/js/section2d/      SVG view
  stand/web/vendor/three/      vendored three.js
  tests/                       unit and calibration tests
  presentation/                deck source and screenshots
  research/sekisovskoye-facts.md
deploy/compose/grafana/dashboards/Sekisovskoye/   three dashboards
scripts/stand-wait.sh, stand-urls.sh, stand-smoke.sh, stand-soak.sh
```

Template files changed: `Makefile` (targets `stand`, `stand-twins`, `stand-test`, `stand-smoke`, `stand-soak`; marker logic), `.gitignore` (marker), `README.md`, `SUBMISSION.md`, new `presentation.pdf`. Already committed: `.gitattributes` and the team's copyright line in `LICENSE` (`Copyright (c) 2026 Nurgazy Tomiris (Tomiyato)`). Platform services, `deploy/compose/docker-compose.yml`, Telegraf, Ditto and Grafana provisioning are not changed.

Difference from `examples/mine`:

| | Example Mine | This twin |
|---|---|---|
| Object | generic open pit, copper | real underground gold mine with plant, water and tailings |
| Twins | 5 things, 4 kinds, one parent link | 96 things, 22 type things, tree plus process links |
| Behaviour | one haul loop, random-walk grade | eight coupled capacities, sourced parameters, 12 calibration checks |
| Control | none | scenario twin, 15 knobs, undo |
| Module | none | Expansion Advisor writing decisions back into a twin |
| View | Grafana charts | 3D scene, long section, three dashboards |
| Code | 1 script | simulator, advisor, Stand, tests under `team/` |

## 9. Decisions taken on 13 October: analytic library and simulator

These decisions settle ambiguities between the analytic library and the simulator. They override sections 2 and 3 where they differ.

1. **Water supply in the analytic library** (`capacity.py`, the advisor's bars): supply is the mine inflow, `water.inflow_m3h × inflow_factor`, as a long-run average. `C_water` is not changed by pump failures and keeps ignoring `inflow_factor` (flood surplus is discharged, not used).
2. **Water supply in the simulator** (the transient the Stand shows): pumped mine water enters the settling ponds; the plant draws from the ponds. While `ps-p150` is failed nothing reaches the ponds, their stored volume falls, and when it is empty the plant feed is limited to `WaterBalance.feed_limit_tph` for the remaining sources (reclaim and extra intake, if the measures are active). The `pump_station_fail` row of 3.3 therefore gains one visible effect: the pond reserve counts down in hours, then the plant slows.
3. **Feed grade**: the simulator rescales the grades of the producing stopes so that their tonnage-weighted mean equals `grade_gpt` (`Stopes.mean_grade_gpt` gives the unscaled mean). The advisor and the simulator then pour the same gold.
4. **Plant line rates** come from `capacity.plant()`; the registry attribute `rated_tph` is static. The simulator publishes the stage-dependent rate as the feature the plant-line type already has for throughput; no new feature is added.
5. **Everything else in the analytic library** (haulage not capped at the decline bottom, the unreachable 80 % recovery floor, sludge without a retention factor, `air_margin_pct = (supply − demand) / supply × 100`, `achievable_ktpa` unrounded) stays as implemented.
6. **Counts in section 0**: the Stand has eight disturbance buttons (section 3.2 is authoritative), not seven.

## 10. Decisions taken on 13 October: simulator behaviour

1. **Stope cycle** (overrides 2.5): the next ring is drilled and charged while the previous one is mucked, and is fired at the first blast window at least four shifts after the stope's last blast if no more than one ring of broken ore is left. The strictly sequential cycle of 2.5 hoists 630 kt/yr at baseline against the reported 926 kt, so it cannot be right for this mine. Stopes start the epoch with one ring of broken ore, staggered a shift apart.
2. **Dispatch** is decided at the ROM pad; breakdowns run on calendar time with a 10 h repair; productive time is two blocks of 4.25 h around a meal hour. As implemented.
3. **`sim.op_delay_factor`** is 0.785 (was 0.81): with the bay rules a truck waits 0.45 min per trip for opposing traffic, less than the 2.25 min the analytic formula books on TU2. The value and the 17 constants of the simulator's `MISSING_PARAMS` table move into `params.json`.
4. **Grade knob** rescales the stockpile and loaded trucks at once (a what-if on the ore), so the plant responds within minutes.
5. **Air rule consistency** (2.3 item 3 is written accordingly). One function, `capacity.hold_units`, decides for the simulator and for the library which units wait for air, and while units are held `C_vent` is the tonnage the units left working can hoist and muck; with nothing held the bar is headroom and cannot bind. In the simulator a held truck no longer counts among the `n` trucks on its decline. The 1000 kt/yr sequence becomes haulage, then ventilation (926 kt/yr until `fan-vpv` runs, where the old formula gave 1038), and `fan_vs2_fail` gives 374 kt/yr against 378 in the simulator (was 486 against 376).

## 11. Decisions taken on 14 October

1. **Economics in the advisor.** Each target of the ladder also reports the gold gained per year in US dollars at the realised gold price and the published expansion capex estimate, with a simple payback, every number sourced in `params.json` (gold price US$4,615/oz, H1 2026; capex about US$125m for 2.0–2.5 Mtpa, Q3 2025 results; AISC from the reports).
2. **Advisor and projection revisions after a run of the live Stand.**
   1. Disturbances first (3.4 step 3): a repair of an active disturbance precedes every expansion measure, the largest gain first; `POST /apply` performs it through the same knob. Grade and flood inflow are conditions.
   2. Projection notes: each year without tailings storage says so; the year storage runs out and the measure that prevents it head the table.
   3. Stockpile direction: the plant side of the stockpile flow is the feed the water sustains at the actual hoisting rate, not `C_water`; with `step1200` the days fall (564 → 368), with the full 2.5 Mtpa set the stockpile grows by 137 t/day, as the simulator does over 20 days.
   4. Starting stockpile: 94 264 t from the published mined/milled pairs since 2020 (2.8), a lower bound against the carrying value. `registry.json` (`rom-stockpile.tonnes`) and `geometry.json` (`reference_t`) follow the parameter.
   5. Calibration honesty: basis and source on every row; simulator rows from a run; out-of-sample rows C13–C16, two of which fail and are shown failing; `vent.q_diesel` sourced to Ontario Reg. 854 s.183.1(1).
3. **Sustained targets over the horizon (16 October).** A review found the module contradicting itself: the ladder and its paybacks (2.0 Mtpa in 0.8 years, 2.5 Mtpa in 0.5 years) were computed at the +75 m centroid for one year with every measure in service at once, while the ten-year projection two panels below, with every measure applied, missed 2.0 and 2.5 Mtpa from 2028 and ran out of tailings storage in 2031–2032. Decided:
   1. The ladder keeps its sequence at the epoch, but every target is judged over 2027–2036 (3.4 steps 5–6): measures come into service after lead times from the decision on 1 January 2027, the planner adds trucks one at a time as the centroid deepens and a second tailings stage when the new cell is full, and the target is labelled «держится до N г.» with the reason. The Stand still switches knobs at once; its texts say when each measure would be in service.
   2. The one-year payback is replaced by ten-year economics against the mine as it is: gold, margin after AISC and corporate income tax (20 %), the published US$125 m over its 24 months, the assumed costs of trucks and storage shown apart (not published), cumulative cash, NPV at 5 % and a payback year, which is never given for a target not held to 2036.
   3. Findings with these parameters: 1.0 and 1.2 Mtpa hold to 2036; 2.0 Mtpa holds 2030–2034 and stops on storage in 2035 (2.7 Mt short to 2036); 2.5 Mtpa holds only in 2030 and falls short from 2031 because haulage at depth needs trucks that shaft VS3 cannot ventilate. No measure in the model holds 2.5 Mtpa to 2036.
   4. The simulator is unchanged: it has no notion of time to service, and lead times stay an analytic matter of the advisor. Were the Stand to replay the horizon, the simulator would need a dated schedule of knob changes (a stage switched on at its `in_service_year` of simulated time) and the two horizon measures as units without twins.
   5. The advisor panel shows the pump margin on the dewatering bar with the standby: «запас насосов ×2,54, резерв 1», after one failed pump «без резерва: при отказе ×1,27» (`Dewatering.margin_next_failure`).
4. **Plausibility fixes and ventilation on demand (17 October).** An independent review of the live Stand found values a mining engineer would not accept and same-screen contradictions. Decided:
   1. *Air to levels that cannot use it.* Backfilled +250/+200 m and a flooded −50 m level each received 27–33 m³/s («отработан, заложен · воздух 33,2 из 22,5») because the base air was shared over every open level and the supply was spread over the requirements; levels tinted amber under restriction showed supply above requirement. Now (2.6) only the levels in production or development, or with units on them, get air for work and carry a requirement that follows the units working there; the levels not in use carry a stated leakage share (20 % of the base air, ASSUMPTION) and need nothing; planned and flooded levels get none; a level whose LHD waits for air shows short. The 3D scene's own rule still tints every level with a requirement amber while units are held, and its label reads «воздух 12,2 из 0,0» on a leakage level (`stand/web/js/scene3d/`, not part of this change).
   2. *Flood thresholds.* 300 and 1 500 m³ were a few hours of inflow; the thresholds are now the volume of the workings (2.7): 14 960 m³ for −50 m and 44 930 m³ for 0 m. The physical times (83 h and 235 h of inflow after a dead station) are shown 24 times faster during the episode (`water.flood_compression`), stated on the Stand; flows and the surface keep the mine clock.
   3. *Decline length factor.* Kept at 1.15 (8.26 m of ramp per vertical metre) against the 14.4 m per vertical metre of the reported advance of Decline No.1; the gap is the development that adds length but no depth (2.8).
   4. *Same-screen contradictions.* (a, b) The advisor's water KPIs are taken at the rates of the twins (`Advisor.regime_rates`, `water_regime`): the mine at its rate over the simulated days, the plant at its capacity as the mean over the planned line stops, and the report also gives the figures with every line running (`water_deficit_all_lines_m3h`, `discharge_all_lines_m3h`, `permit_use_all_lines_pct`, `water_basis`). Flood: 236.6 m³/h on average (108 %), 225.5 m³/h (103 %) with three lines, where the outfall twin shows 223–228; it was 247 m³/h, 113 %, with the plant milling only what the mine hoists. Dead pump station: deficit 192.8 on average, 204.0 with three lines, against the simulator's 201–207 (the simulator keeps hoisting the broken ore of the stopes for some days after two levels flood). Baseline: discharge 4.2 m³/h on average (was 14.5; the registry default of the advisor twin follows). (c) The Grafana overview stat of `rom-stockpile.days_of_feed` is titled «Склад: суток питания без подачи руды»: it is the stock over the plant feed, not the 564 days of the net draw the advisor shows; the fixture publishes the same quantity as the simulator. (d) The scenarios panel names the smallest link («Сейчас ограничивает: откатка (926 тыс. т/год)») and a disturbance the advisor removes first apart («Сначала устранить: водоотлив — …»).
   5. *Ventilation on demand* (3.5): the second decision module, on by default, with the knob `vod_enabled`, the Stand panel and button, twelve mine features and the fan setpoint. Saving at baseline 5 666 kWh/day (21 % of 26 880), about 2.07 GWh and 72 million tenge a year at 35 ₸/kWh (assumed tariff). The Stand's button needs the two entries of 3.5 in `team/stand/server.py`.
