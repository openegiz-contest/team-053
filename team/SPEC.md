# SPEC: Sekisovskoye digital twin on OpenEgiz (team-053)

Status: decided on 13 October 2026. Freeze: 25 October 2026, 23:59 Astana time.
This file is the single source every sub-agent reads. It is written in English; all text shown on the Stand, README.md, SUBMISSION.md and presentation.pdf are Russian.

Inputs this spec is built on: `SUBMISSION.md` (Concept, fixed), `team/research/sekisovskoye-facts.md` (the "facts file"), the OpenEgiz v1.0.4 template in this repository.

## 0. Summary, rubric mapping, conventions

### 0.1 What is built

A twin of the whole Sekisovskoye production chain in Eclipse Ditto (96 things of 22 types), driven by a time-compressed simulator, with one decision module (the Expansion Advisor) and a web Stand that shows the mine as a 3D scene and a 2D long section. The user picks a processing target (1.0 / 1.2 / 2.0 / 2.5 Mtpa), sees which link binds, removes it with one click, and sees the next one. Disturbances (decline closure, fan failure, pump station failure, flood inflow, grade drop, plant line stop) run from the same panel. Every scenario has an undo.

Eight capacities are ranked: haulage, ventilation, stopes, development, dewatering, plant, process water, tailings storage. They cover the six links the Concept names: its "stopes" is shown as two rows (stopes and development), its "dewatering" as two rows (pumps and water supply).

### 0.2 Rubric mapping

| Criterion (points) | Deliverables that earn it | Where a judge sees it |
|---|---|---|
| Mine model (25) | 96 Ditto things, 22 type things, `_parents` hierarchy, `link_*` attributes, state machines (section 1) | Stand section «Двойники»; Grafana → OpenEgiz → Twins / Types; `team/model/registry.json` |
| Mine visualization (25) | three.js scene + SVG long section with live twin data, process animation and scenario effects (section 4) | `http://localhost:8088`, Grafana dashboard `sekis-overview` (scene embedded) |
| Behaviour fidelity / credibility (20) | Coupled simulator, sourced parameters, 12 automatic calibration checks (section 2) | Stand sections «Проверка калибровки», «Данные и допущения»; `team/tests/` |
| Concept and presentation (15) | Concept unchanged; SUBMISSION.md, presentation.pdf built from screenshots of the running Stand (WP-F1, WP-F2) | repository root |
| What-if scenarios (10) | 4 targets, 7 measure ladders, 7 disturbances, undo/reset, effects table (section 3) | Stand panel «Сценарии», «Что изменилось» |
| Modules (5) | One deep module: Expansion Advisor (section 3.4) | Stand section «Советник по расширению»; twin `kz.sekis:advisor` |

### 0.3 Conventions for every agent

- Languages: code, comments, commit messages, this spec: English. Everything a person sees on the Stand, in Grafana, README.md, SUBMISSION.md, presentation.pdf: Russian. State tokens in twins are English (`hauling_up`); the UI maps them to Russian.
- No text addressed to evaluators, judges, AI models or the Collector anywhere (UI, docs, comments, commit messages). Describe the system; never instruct a reader how to rate it.
- Python 3.12 in containers; code must also run on Python 3.10+. Model, simulator and advisor use the standard library only. The only third-party runtime package is `paho-mqtt==2.1.0`.
- Front end: plain ES modules, no build step, no npm at build time. Every script, style and font is served from the repository. No external URL may be requested by the page.
- All files are LF. The committed `.gitattributes` (`* text=auto eol=lf`) enforces it. Shell scripts are run as `bash scripts/x.sh`.
- Tests are `unittest` and run with `cd team && python -m unittest discover -s tests -v` (on this Windows machine: `py -3 -m unittest ...`).
- A parameter enters code only through `team/model/params.json`, where each entry has `value`, `unit`, `source`. `source` starts with `FACT ` (plus the facts-file section and row) or `ASSUMPTION: ` (plus the reasoning). A test enforces this.
- `examples/mine` is not started and not copied. Nothing of it is reused.
- An agent edits only the files its work package owns (section 7).

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
| `rom-stockpile` | rom_stockpile | plant | Рудный склад | 36 000 t at start |
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

| Attribute | On | Points to |
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

- Compression 60: one real second is one simulated minute (`SIM_SPEEDUP=60`). A shift lasts 11 real minutes, a truck cycle about 40 real seconds.
- Internal step 10 simulated seconds; the service loop runs every 0.5 real seconds (3 steps).
- Simulation epoch: 1 January 2027, 08:00 (first year of the decision). A year is 360 working days (FACT A10 "Shift regime"); the five non-working days are not simulated. Mine totals are annualised with × 360, plant totals with × 365 (the plant runs every day).
- Day: shift A 08:00–19:00, blast window 19:00–20:00, shift B 20:00–07:00, blast window 07:00–08:00. ASSUMPTION: the 2 hours left by 2 × 11 h are used for blasting and clearing.
- Productive time inside a shift: 8.5 h (ASSUMPTION: 0.75 h travel and inspection at each end, 1 h meal).
- Random numbers come from one generator seeded with `SIM_SEED=53`. The core runs headless (no MQTT) at full speed for tests: 60 simulated days in at most 60 s.
- Displayed rates: "now" values are rolling 2-simulated-hour means; daily totals reset at 08:00; annual capacity comes from the advisor (analytic, instant).

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
3. Ventilation. `P_allowed = (Q_supply − 180) / 0.06` kW. `P_fleet` = engine kW of all active trucks and LHDs. `C_vent = P_allowed × C_haul / P_fleet` (the ore the permitted diesel power can move at the fleet's specific power).
4. Dewatering. `margin = working pump capacity / (inflow × 24/20)`. It caps throughput only when a level is flooded: then `C_dewatering = C_stopes` of the non-flooded producing stopes; otherwise it is reported as not limiting.
5. Plant. `C_plant` = 1000 / 1200 / 2000 / 2500 by stage, reduced by a stopped line.
6. Water. `C_water = (1725.72 + 8.76 × extra_intake_m3h) / (0.603 + 1.123 − reclaim_m3_per_t)`.
7. Tailings. `C_tailings = free_capacity_kt / 3.0` (the rate that keeps three years of storage); `years_left = free_capacity / rate`.

Gold: `oz = milled_t × grade × R(grade) / 31.1035`, `R(g) = 81.616 + 1.637·g` percent, clamped to 80–88.

Reference values with the parameters of 2.8 (tests use them with ±1 % tolerance):

| Measure set | haulage | stopes | development | ventilation | plant | water | tailings | air demand m³/s |
|---|---|---|---|---|---|---|---|---|
| Baseline | 926 | 1024 | 1750 | 958 | 1000 | 1000 | 1057 | 317.2 |
| Full set for 1.2 Mtpa | 1386 | 1279 | 1750 | 1665 | 1200 | 1533 | 3057 | 385.7 |
| Full set for 2.0 Mtpa | 2076 | 2047 | 2573 | 3045 | 2000 | 2700 | 3057 | 512.0 |
| Full set for 2.5 Mtpa | 2512 | 2559 | 2573 | 2938 | 2500 | 2700 | 3057 | 596.3 |

Depth effect: every 50 m the production centroid goes down costs about 8.5 % of haul capacity (baseline fleet: 926 → 840 → 769 → 709 kt/yr at +75, +25, −25, −75 m).

### 2.4 Trucks and decline traffic (state machine)

States: `parked`, `descending`, `waiting_bay`, `tram_level`, `queue_load`, `loading`, `hauling_up`, `surface_haul`, `dumping`, `held_vent`, `maintenance`, `shift_break`.

Cycle: `surface_haul` (empty, ROM pad → portal) → `descending` → `tram_level` → `queue_load` → `loading` (5 min, needs `broken_ore_t` ≥ payload and the stope's LHD) → `tram_level` → `hauling_up` → `surface_haul` (loaded) → `dumping` (1.5 min, adds payload and grade to `rom-stockpile`) → repeat.

- Dispatch: an empty truck at the portal is sent to the stope with the largest `broken_ore_t` per truck already assigned, among stopes its decline reaches.
- Decline geometry for traffic: nodes at the portal, at every multiple of 25 m of elevation below it, and at the current bottom; level accesses are the nodes at multiples of 50 m. Each node is a passing bay with one waiting slot. Segments between nodes are single lane.
- Traffic rules (deadlock-free; loaded trucks have priority): an up-going truck enters the segment above it when no down-going truck is inside; it never uses a waiting slot. A down-going truck enters the segment below it only when no up-going truck is inside and the waiting slot of the node at its lower end is free and not reserved; it reserves that slot. Trucks in the same direction may follow each other.
- Operational delay: each cycle gets an extra delay drawn from an exponential distribution with mean `T × (1/k − 1)`, where `k = sim.op_delay_factor` (start at 0.81; the simulator builder tunes it in 0.70–0.95 so that check C3 passes).
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

- Supply: sum of `duty_m3s` of fans in state `running`. Baseline 150 + 102 + 70 = 322 m³/s.
- Demand: `180 + 0.06 × P_fleet` m³/s.
- Rule (every simulated minute): if demand exceeds supply, units are held in this order until it fits: the active truck with the highest number, the next truck, then the LHD with the highest number (its stope becomes `standby`), and repeat; never below one truck and one LHD. A held truck finishes its trip and waits at the surface in `held_vent`; a held LHD is `standby_vent`. Units are released in reverse order. `mine.state` is `restricted_air` while anything is held.
- Level air: each level gets `air_required = 180 / (number of non-planned levels) + 0.06 × kW of units on it`, and `air_flow = supply × its share of the total requirement`.
- Airways: `air_velocity_ms = air_flow / section_m2`. Split of the 252 m³/s group: 150 through `shaft-vs1`, 102 through the two declines (ASSUMPTION). `shaft-vs2` carries the `fan-vs2` flow, `raise-vpv` the `fan-vpv` flow, `shaft-vs3` the `fan-vs3` flow; all return air leaves through `raise-vhv-exhaust`.
- Fan power: `power_kw = air_flow × pressure_pa / 0.75 / 1000`.
- After a blast the stope is `ventilating` for 30 min before re-entry (ASSUMPTION).

### 2.7 Water, plant, tailings

Dewatering cascade (FACT A6 "Mine water route"):

- Inflow `197 × inflow_factor` m³/h; 60 % reports to the `ps-p150` sump, 40 % to the `ps-m050` sump.
- `ps-m050`: one pump starts at 70 % sump level and stops at 20 %; the standby starts at 90 %. It discharges into the `ps-p150` sump.
- `ps-p150`: first pump starts at 60 %, stops at 20 %; second starts at 80 %; the standby runs only in place of a failed pump. It discharges to `pond-upper`.
- Overflow: a full `ps-p150` sump spills down to the `ps-m050` sump; a full `ps-m050` sump adds to `mine.flood_volume_m3`. Above 300 m³ `lvl-m050` is `flooded`; above 1500 m³ `lvl-000` is `flooded` and its stopes go to `flooded`. Spare pump capacity removes the flood volume after recovery.
- `hours_to_overflow` = free sump volume / net inflow while the sump is rising.
- Pump power: `1000 × 9.81 × Q/3600 × head × 1.1 / 0.70 / 1000` kW; head 280 m for `ps-p150` (+150 to +430), 200 m for `ps-m050`.

Ponds and water balance (rolling 24-hour means, to hide pump cycling):

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
| `decline.length_factor` | 1.15 | A: curves and passing bays; decline lengths are not published (facts C) |
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
| `vent.q_base`, `vent.q_diesel` | 180 m³/s; 0.06 m³/s per kW | A: 0.06 is common design practice; the pair reproduces 252 m³/s at half the fleet and 322 m³/s at the full fleet (checks C6, C7) |
| `vent.measure_V1` | +105 m³/s (fan on raise VPV, 7.0 m² × 15 m/s) | section: F A2 "Ventilation raise VPV"; velocity limit and fan: A |
| `vent.measure_V2` | +240 m³/s (new shaft VS3, 16 m² × 15 m/s) | A |
| `vent.fan_efficiency`, `pressure_vs1_pa` | 0.75; 2500 | A |
| `vent.reentry_min` | 30 | A |
| `water.inflow_m3h` | 197 | F A6 "Average mine inflow" (2021); equals 1725.72 thousand m³/yr ÷ 8760 h (F A6 "Water balance") |
| `water.inflow_design_m3h` | 430 | F A6 "Design inflow" |
| `water.upper_share` | 0.60 | A; F A6 gives at most 25 m³/h at the +320 m horizon |
| `water.ps_p150` | 3 × 300 m³/h, sump 1800 m³ | A: two working pumps clear the design inflow in 20 h (430 × 24/20 = 516 ≤ 600); sump about 4 h of design inflow. Station and elevation: F A6 "Pumping stations", F B3 |
| `water.ps_m050` | 2 × 150 m³/h, sump 600 m³ | A; unit size from F A6 "Pumps at quarry sump" |
| `water.flood_thresholds_m3` | 300, 1500 | A |
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
| `stockpile.start_t` | 36 000 | A from F B, D1: +156 433 t in 2024, −40 170 t in 2025, −40 130 t in H1 2026, −40 000 t assumed for H2 2026 |
| `tsf.dam4_capacity_t`, `capacity_m3`, `bulk` | 3 181 950; 2 357 000; 1.35 | F A9 |
| `tsf.dam4_fill_start` | 0.90 | A: fill state is not published (facts C) |
| `tsf.dam23_free_t` | 1 426 950 each | A: same as the increment of the dam 4 reconstruction (3 181 950 − 1 755 000, F A9); F D1 reports the expansion of dams 2 and 3 as started |
| `tsf.measure_X1_t` | 6 000 000 | A |
| `tsf.min_years` | 3.0 | A: lead time to permit and build storage |
| `gold.g_per_oz` | 31.1035 | definition |

### 2.9 Calibration checks (automatic)

Analytic checks run in `team/tests/test_calibration.py`; simulator checks in `team/tests/test_sim.py`. The Stand shows the same table («Проверка калибровки»: показатель, отчёт, модель, отклонение).

| Id | Check | Reported value | Tolerance |
|---|---|---|---|
| C1 | Gold FY2025: 966 592 t × 2.05 g/t × R | 53 852 oz (F B) | ±1.5 % |
| C2 | Gold FY2024: 593 612 t × 2.29 g/t × R | 37 279 oz (F B) | ±1.5 % |
| C3 | Simulator, baseline, 60 days, annualised ore hoisted (× 360/60) | 926 422 t (F B) | ±3 % |
| C4 | Gold H1 2026: 498 331 t × 1.76 g/t × R; and H1 2025: 452 593 t × 2.04 g/t × R | 23 906 oz; 25 081 oz (F D1) | ±1.5 % |
| C5 | Recovery model at 2.29, 2.05, 2.04, 1.76 g/t | 85.42, 85.07, 84.75, 84.55 % | ±0.25 points |
| C6 | Air demand of the baseline fleet (peak) | 322 m³/s (F A5) | 95–100 % of it |
| C7 | Air demand at half the baseline fleet power | 252 m³/s (F A5) | ±3 % |
| C8 | Simulator, baseline, 60 days: plant feed annualised (× 365/60) with stockpile available | 1 000 000 t nameplate (F B2; F D1: 498 331 t in H1 2026) | ±3 % |
| C9 | Sludge from the ponds at 197 m³/h | 64.3 t/yr (F A6) | ±2 % |
| C10 | Water balance at 1000 kt/yr: site + plant demand | 1725.72 thousand m³/yr (F A6) | ±0.5 % |
| C11 | Mass balance over a 60-day run: hoisted = stockpile change + milled; milled = tailings added | identity | ±0.1 % |
| C12 | Gold at 2.0 Mtpa and 2.05 g/t | over 100 000 oz (F B2, CEO statement) | must hold |

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
| `advisor_next` on haulage | `truck-06`, `truck-07` leave `parked`; `decline-tu1.trucks_on_ramp`; `mine.air_demand_m3s` | two more trucks enter TU1; bays show waiting trucks | haulage bar 1386; next binding link named |
| measure on ventilation | `fan-vpv`, `raise-vpv` (`running`, `in_service`), `mine.air_supply_m3s`, level `air_flow_m3s` | new airflow arrows down the VPV raise; level tint from amber to normal | ventilation bar 1665 |
| measure on stopes | next stope leaves `standby`; `lhd-05`, `rig-03` active | stope box changes colour through its cycle; blast flash at the shift change | stopes bar 1279 |
| measure on water / tailings | `water.reclaim_m3h`, `water.deficit_m3h`; `tsf-cell5.state`, `tailings.years_left` | reclaim pipe from tailings to plant animates; new cell appears | water bar; years of storage |
| `close_tu2` | `decline-tu2.state = closed`; trucks 01–04 `decline = tu1`; `ore_hoisted_tph` falls about 10 % (baseline) | TU2 turns red and empties; all trucks on TU1, queues in bays | haulage 833; stockpile days fall |
| `fan_vs2_fail` | `fan-vs2.state = failed`; `mine.air_supply_m3s = 252`; trucks `held_vent`, LHD `standby_vent`, stope `standby`; `mine.state = restricted_air` | VS2 arrow disappears; levels amber; held trucks line up at the portal | ventilation bar about 486, binding |
| `pump_one_fail` | `ps-p150.pumps_available = 2` | one pump icon red, station still green | no change in bars (redundancy) |
| `pump_station_fail` | `ps-p150.state = failed`, `sump_level_pct` rises, `hours_to_overflow` counts down; later `mine.flood_volume_m3`, `lvl-m050` then `lvl-000` `flooded`, their stopes `flooded` | sump bar fills, water plane rises on the lower levels, flooded stopes blue | dewatering row turns binding when a production level floods |
| `flood` | `mine.inflow_m3h = 430`, pumps run together, `mon-volchevka.discharge_m3h` about 238, state `exceeded` | thicker water flow in the cascade; outfall marker red | water row: discharge above the permit |
| `grade_drop` | stope `grade`, `rom-stockpile.grade`, `plant.feed_grade`, `recovery_pct`, `gold_poured_oz_day` | stope grade colouring shifts | gold falls from about 56 to 47.8 koz/yr at 1000 kt/yr |
| `line2_down` | `plant-line-2.state = off`, `plant.feed_tph` falls by a third, stockpile grows | line 2 grey | plant bar 667, binding |

The advisor recomputes within 3 seconds of a knob change, so bars and the «Что изменилось» list respond at once; the moving objects follow within one truck cycle (about 40 real seconds).

### 3.4 The module: Expansion Advisor (`sekis-advisor`)

Inputs, read from Ditto every second: attributes of fleet, fans, pumps, plant lines, dams (payloads, kW, duties, capacities); live features (which units are active, failed pumps, flooded levels, stockpile, stored tailings, decline bottoms); the scenario thing. Norms come from `params.json`.

Algorithm (theory of constraints, deterministic):

1. Compute the eight capacities (section 2.3) for the current state. Round each to 1 kt/yr.
2. The binding link is the smallest; ties are broken in the order haulage, ventilation, stopes, development, dewatering, plant, water, tailings.
3. If the binding capacity is at or above `target_ktpa`, stop. Otherwise the next measure is one more stage on that link's knob (haulage → `m_haul`, ventilation → `m_vent`, stopes → `m_stopes`, development → `m_dev`, plant → `m_plant`, water → `m_water`, tailings → `m_tailings`; dewatering → restore pumps). Apply it virtually and repeat. If the link has no stage left, stop and report the achievable rate.
4. Ladder: for each target 1000, 1200, 2000, 2500, starting from the baseline measure set (all `m_*` = 0) with the current disturbances, report: the sequence of (binding link, measure, capacity before), the achievable rate, gold per year at the current grade, gold gained against the sustainable baseline (926 kt/yr), air demand, water deficit and discharge, tailings years left.
5. Projection 2027–2036 for the current measure set: each year the production centroid drops by `ore / 51 462` m, haul capacity is recomputed for that depth, tailings fill, gold accumulates. Output per year: achievable kt, binding link, gold oz, tailings stored and free, water deficit; plus the year storage runs out and the first year the target is missed.
6. Effects list: for the last knob change, the difference in each link capacity and KPI (before → after), in Russian sentences for «Что изменилось».

Expected sequences with the parameters of 2.8 (unit-tested):

| Target | Sequence of binding links from the baseline | Achieved | Gold at 2.05 g/t |
|---|---|---|---|
| 1000 | haulage | 1000 (plant) | 56.0 koz |
| 1200 | haulage, plant, water, stopes, ventilation, tailings | 1200 (plant) | 67.2 koz |
| 2000 | the six above, then plant, stopes, ventilation, haulage, water, development | 2000 (plant) | 112.0 koz |
| 2500 | the twelve above, then plant, stopes, haulage | 2500 (plant) | 140.0 koz |

Sustainable baseline: 926 kt/yr, 51.9 koz (the plant mills 1000 kt/yr only while the 36 000 t stockpile lasts, about 216 days).

Outputs:

- Features of `kz.sekis:advisor` (published to MQTT on change and every 30 s): `binding_link`, `next_measure`, `measures_needed`, `target_ktpa`, `achievable_ktpa`, `cap_haulage_ktpa`, `cap_ventilation_ktpa`, `cap_stopes_ktpa`, `cap_development_ktpa`, `cap_dewatering_ktpa` (0 when not limiting), `dewatering_margin`, `cap_plant_ktpa`, `cap_water_ktpa`, `cap_tailings_ktpa`, `gold_koz_year`, `gold_gain_koz_year`, `air_demand_m3s`, `water_deficit_m3h`, `discharge_m3h`, `tailings_years_left`, `stockpile_days_left`, `report_revision`.
- Full report as JSON at `http://sekis-advisor:8089/report` (ladder for the four targets, projection, effects, calibration table), proxied by the Stand as `/api/advisor`.
- Action: `POST /apply` with `{"mode": "next" | "all"}` returns the knob changes; the Stand writes them to the scenario thing. This is how the module changes the operation of the mine.

## 4. Mine visualization

### 4.1 Technology

A three.js scene and an SVG long section, both in the Stand page served by `sekis-stand` on port 8088, and the 3D scene embedded in the Grafana dashboard `sekis-overview` through an iframe.

Reasons: no GPU in the Judge Environment, so the scene must be small and under our control (a Unity build is neither buildable by agents nor small); three.js is one vendored file with no build step; the SVG section is the fallback when WebGL is unavailable and puts every label and value into the DOM as text, where a reader that does not see canvas pixels still finds them.

- Vendored in `team/stand/web/vendor/three/`: `three.module.min.js`, `OrbitControls.js`, `CSS2DRenderer.js` (three.js r160, MIT, with its LICENSE file), loaded through an import map. System fonts only.
- The page shows both views side by side on wide screens (3D left, section under it or in a tab on narrow screens). If the WebGL context cannot be created, the 3D area shows the section instead.

### 4.2 Geometry: sourced and schematic

`team/model/geometry.json` is generated by `sekis/geometry.py` from `params.json` and `registry.json`. Scene frame: X east, Y up = elevation in metres above sea level, Z south; origin on the axis of shaft VS1; 1 unit = 1 m; vertical scale equals horizontal scale.

Sourced (facts file): every elevation (portals +430 and +320; shaft bottoms +325 and +340; raise ranges; levels at +320, +150, +100 and the 50 m floor height; decline bottoms −50 and −34; design bottoms −200, −300; pump stations at +150, −200); decline slope 8° and section 18 m²; airway sections; pond area 755 m²; the bearing from the mine to the tailings facility (1257 m north, 830 m east from the two coordinate pairs).

Schematic (no mine plan is published): all plan positions. The file marks each object with `"sourced": true|false`, and the Stand shows the legend «Отметки и сечения — по опубликованным данным; расположение в плане — схема».

- Ore zone along X from −300 to +300 at Z = 0; three stopes per level at X = −200, 0, +200; stope box 120 × 40 × 20 m.
- Level drive along X at Z = +40 with crosscuts to the stopes.
- TU1: zigzag in the plane Z = +120 between X = −330 and X = +26, turning at every 50 m of elevation; TU2: zigzag in the plane Z = +150 between X = +30 and X = +386. Horizontal run per 25 m of depth is 25 / tan 8° = 177.9 m. Level accesses join the level drive at the turns.
- VS1 at (0, −60), VS2 at (+250, −60), VS3 at (−250, −60), VPV at (−100, −40), VHV TU1 at (−250, +100), VHV TU2 at (+250, +100), exhaust raises at (+330, −20). Coordinates are (X, Z).
- Surface at Y = +430: old pit as an inverted frustum centred on the TU2 portal, floor at +320, floor radius 90 m, rim radius 230 m; ROM pad at (−350, −250); plant as six boxes at (−500, −350); two ponds at (+100, −200); tailings dams on the true bearing N 33° E, drawn 900 m away (distance shortened); Volchevka stream south of the pit and Sekisovka river to the south-west as lines.
- Truck positions: the simulator computes `pos_x`, `pos_y`, `pos_z` from the same `geometry.json`, so the views only place and interpolate.

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

At most 20 000 triangles and 150 draw calls (static geometry merged into at most 10 meshes); no textures, shadows or post-processing; at most 5 translucent meshes; `antialias: false`, pixel ratio 1, canvas at most 1280 × 720 CSS pixels; rendering only while something moves, capped at 12 frames per second; three.js files under 1.5 MB. Target on software rendering (Chromium with `--disable-gpu --enable-unsafe-swiftshader`): at least 8 frames per second and under one CPU core.

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

Expected cold start in the Judge Environment: 8–20 minutes (image pulls about 2.5 GB, the platform's extended-api build, Ditto start, our image build about 1 minute). The sum of all script timeouts is under 45 minutes, against the 75-minute limit. Memory: container limits total about 7.0 GiB (platform 6.5 GiB, ours 0.5 GiB), measured use about 4 GiB, leaving 8 GiB or more for the browser. Disk: under 5 GB.

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

| | Example Mine | This Submission |
|---|---|---|
| Object | generic open pit, copper | real underground gold mine with plant, water and tailings |
| Twins | 5 things, 4 kinds, one parent link | 96 things, 22 type things, tree plus process links |
| Behaviour | one haul loop, random-walk grade | eight coupled capacities, sourced parameters, 12 calibration checks |
| Control | none | scenario twin, 15 knobs, undo |
| Module | none | Expansion Advisor writing decisions back into a twin |
| View | Grafana charts | 3D scene, long section, three dashboards |
| Code | 1 script | simulator, advisor, Stand, tests under `team/` |

## 7. Work packages and schedule

### 7.1 Work packages

Each package gets this spec plus the listed inputs. Packages in the same phase run in parallel; file sets are disjoint.

| Id | Tier | Deliverables | Owns | Inputs | Completion check |
|---|---|---|---|---|---|
| A1 | worker | Parameter file and twin registry | `team/model/params.json`, `team/model/registry.json`, `team/tests/test_model_files.py` | sections 1, 2.8 | test passes: 96 things, 22 types, every parent and `link_*` resolves, feature ids keep one type, every parameter has a `FACT`/`ASSUMPTION` source |
| A2 | worker | Runtime skeleton and twin setup | `team/Dockerfile`, `team/requirements.txt`, `team/compose.yml`, `team/sekis/__init__.py`, `team/sekis/ditto.py`, `team/sekis/setup_twins.py`, `Makefile`, `.gitignore`, `scripts/stand-wait.sh`, `scripts/stand-urls.sh` | section 5; A1 registry (a 3-thing stub until A1 lands) | `make stand-twins` in WSL, then Ditto search returns 96 + 22 things and Grafana → OpenEgiz → Twins shows the tree under «Предприятие „Секисовское“»; Telegraf log has no parse errors |
| B1 | builder | Capacity library and analytic calibration | `team/sekis/capacity.py`, `team/tests/test_calibration.py` | A1; sections 2.3, 2.9 | tests pass: C1, C2, C4–C7, C9, C10, C12 and the reference table of 2.3 within ±1 % |
| B2 | builder | Geometry generator | `team/sekis/geometry.py`, `team/model/geometry.json`, `team/tests/test_geometry.py` | A1; section 4.2 | test passes: decline polylines keep 8° ± 0.2°, every thing with a position is present, regenerating gives the same file |
| C1 | builder | Simulator core (headless) | `team/sekis/sim/`, `team/tests/test_sim.py` | A1, B1, B2; sections 2.4–2.7 | tests pass: C3, C8, C11, the consistency checks of 2.9; 60 simulated days in 60 s or less |
| C2 | builder | Expansion Advisor | `team/sekis/advisor/`, `team/tests/test_advisor.py` | A1, B1; section 3.4 | tests pass: the four sequences of 3.4, projection has 10 rows, `/report` and `/apply` answer on port 8089 against a fixture state |
| C3 | builder | Stand server and page (panels, scenario controls, twin table, calibration, assumptions) | `team/stand/server.py`, `team/stand/fixtures/`, `team/stand/web/index.html`, `team/stand/web/css/`, `team/stand/web/js/app.js`, `team/stand/web/js/panels/`, `team/tests/test_stand_api.py` | sections 3.2, 3.3, 5.2; view contract below | `STAND_FIXTURE=1 python stand/server.py` serves the page; `test_stand_api.py` passes; all buttons of 3.2 present with Russian labels |
| D1 | builder | 3D scene | `team/stand/web/js/scene3d/`, `team/stand/web/vendor/three/` | B2, C3 fixture; section 4 | page in fixture mode shows the scene under `--disable-gpu --enable-unsafe-swiftshader` at 8 fps or more; triangle and draw-call counts printed by `?debug=1` are inside the budget; a screenshot is attached to the report |
| D2 | builder | 2D long section | `team/stand/web/js/section2d/` | B2, C3 fixture; section 4 | fixture page shows the section; the DOM contains the Russian label and a live value for every level, stope, fan and pump station |
| D3 | worker | Simulator service | `team/sekis/sim_service.py`, `team/tests/test_publish.py` | C1, A2 | `make stand`: `/api/state` shows `enterprise.sim_day` growing; message rate measured on `telemetry/sekis/#` is 20 per second or less |
| D4 | builder | Grafana dashboards | `deploy/compose/grafana/dashboards/Sekisovskoye/*.json` | running stack (D3); section 5.3 | the three uids load without login; no panel shows "No data" after 5 minutes of running |
| E1 | worker | Smoke and soak scripts | `scripts/stand-smoke.sh`, `scripts/stand-soak.sh` (the Makefile target `stand-smoke` already exists from A2 and calls the script) | section 5.5 | `make stand-smoke` exits 0 on a fresh stack; soak passes once |
| E2 | judge | Review against the rubric and this spec | none (report only) | running Stand, repository | ranked findings with file and line; each must-level gap named |
| E3 | worker / builder | Fix rounds (one batch of notes per round) | files named in the notes | E2 report, human notes | named checks pass again; `make stand-smoke` exits 0 |
| F1 | builder | README.md and SUBMISSION.md (Russian) | `README.md`, `SUBMISSION.md` | this spec, `params.json`, running Stand | README procedure equals 5.4 and passes the clean run; every row of the SUBMISSION table names where it is seen and how it is undone; "Data and Assumptions" lists every source URL (facts file section D) and every `ASSUMPTION`; no sentence addresses a reader who evaluates |
| F2 | builder | presentation.pdf (Russian, 10–14 pages) | `presentation.pdf`, `team/presentation/` | screenshots from the clean run | PDF opens, every screenshot is from the clean-run Stand, each claim names the Stand place that shows it, file under 20 MB |
| F3 | worker | Clean-run rehearsal | none (report only) | README.md | fresh clone in WSL, Docker pruned, WSL limited to 8 CPUs and 16 GB: the three README commands succeed with no other input; elapsed time and peak memory reported |

View contract for C3, D1, D2: each view module exports `mount(container, geometry)` returning `{update(state), focus(thingId), dispose()}`; `app.js` owns fetching and calls `update` every 2 s. If `scene3d.mount` throws, `app.js` mounts the section in its place.

A scout verifies the H1 2026 figures (facts file D1, tagged UNCONFIRMED) against the primary RNS text before F1; corrected values go into `params.json` and the tests.

Development loop on this machine: unit tests run on Windows with `py -3`; anything needing Docker runs in WSL from a clone in the Linux home directory (not under `/mnt/c`), updated from the Windows repository by `git pull`.

### 7.2 Schedule (Astana dates)

| Date | Agents | The human looks at (up to 1 hour) |
|---|---|---|
| Wed 14 Oct | A1, A2 in parallel; `git fetch origin` for Organizer updates (every day) | finishes WSL2 + Docker; runs `make up && make smoke` on the template once; answers the open questions of 8.4; skims the assumptions in `params.json` |
| Thu 15 Oct | B1, B2 in parallel | reads the capacity table and the four bottleneck sequences printed by the B1 tests: does the story match the Concept? |
| Fri 16 Oct | C1 (two days), C2, C3 in parallel | opens the Stand page in fixture mode; comments on layout and Russian wording |
| Sat 17 Oct | C1 continues; D1, D2 in parallel | looks at the 3D scene and the section in fixture mode |
| Sun 18 Oct | D3, then first full `make stand`; D4 | first live look: trucks move, twins update, advisor answers |
| Mon 19 Oct | E1; fix round 1; push | runs every scenario and its undo once; notes what is unclear |
| Tue 20 Oct | E2 review; fix round 2 | reads the review, decides what to cut (8.1) |
| Wed 21 Oct | fixes; software-rendering test; 60-minute soak. Feature freeze at 23:59 | checks the page in a browser with the GPU disabled |
| Thu 22 Oct | buffer for slipped packages; F1 draft; push | reads README.md |
| Fri 23 Oct | F3 rehearsal 1; F1 final | reads SUBMISSION.md; sees the rehearsal report |
| Sat 24 Oct | F2; fixes from rehearsal 1; F3 rehearsal 2 | reads presentation.pdf against the Stand |
| Sun 25 Oct | F3 rehearsal 3 on the final commit; wording scan; final push by 20:00; fresh clone from GitHub compared with the local commit | approves the push; last look. Four hours of buffer remain |

## 8. Scope control

### 8.1 Must, should, cut first

| Rank | Item | Rubric it serves |
|---|---|---|
| Must | README procedure runs clean; Stand on 8088 | cap of 40/100 otherwise |
| Must | 96 things, types, hierarchy, links; twin table on the Stand | Mine model 25 |
| Must | Simulator: haulage with bay traffic, stopes, ventilation rule, cascade, plant, tailings, water balance; checks C1–C12 | Behaviour 20 |
| Must | 3D scene and 2D section with live data and scenario effects | Visualization 25 |
| Must | Targets, «Снять узкое место», `close_tu2`, `fan_vs2_fail`, `pump_station_fail`, `grade_drop`, undo and reset | What-if 10 |
| Must | Advisor: ranking, sequences for four targets, gold, water, tailings years | Modules 5, Concept 15 |
| Must | SUBMISSION.md, presentation.pdf, LICENSE | Concept 15; required files |
| Should | Grafana dashboards `sekis-overview`, `sekis-underground` with the embedded scene | Visualization, built on OpenEgiz |
| Should | Ten-year projection; «Что изменилось» list; «Проверка калибровки» and «Данные и допущения» on the Stand | Modules, Behaviour |
| Should | `flood`, `close_tu1`, `pump_one_fail`, `line2_down` | What-if |
| Cut first | Dashboard `sekis-eco`; fan and pump `power_kw`; level air distribution; rigs as moving objects; camera presets; stope grade colouring; soak script | small |

If C1 slips past 18 October: drop the bay traffic rules (use the `K_BAY` delay per trip instead) before anything else. If D1 slips past 20 October: ship the section as the main view and the 3D scene with static geometry and moving trucks only.

### 8.2 Top risks

| Risk | Mitigation |
|---|---|
| Docker in WSL is late or agents cannot reach it | pure-Python tests and fixture mode keep A1–D2 moving; integration starts 18 October at the latest |
| CRLF line endings from Windows break shell scripts in Linux | `.gitattributes` with `* text=auto eol=lf` is committed; Docker runs and rehearsals use a clone, never the Windows working tree |
| Ditto unstable at 15–20 messages per second on 8 vCPUs with a software-rendered browser | publishing budget, `PUBLISH_SCALE`, soak test on 21 October; raise the `things` heap only if the soak fails |
| WebGL missing or too slow in the judging browser | SVG section as automatic fallback; all values also in the DOM; 12 fps cap |
| Simulator does not match the analytic capacities | tolerances of 2.9; one tuning knob with a range; fallback in 8.1 |
| Results rest on assumptions (tailings free capacity, water per tonne, ventilation stages) | each is labelled on the Stand and in SUBMISSION.md; calibration table shows what is checked against reports and what is not |
| Platform build of extended-api from GitHub fails during the run | `make stand` tries the platform start twice |
| Grafana anonymous access or iframe settings do not take | the Stand on 8088 is the primary address and does not depend on Grafana |
| One reviewer, 12 days | cut list above; feature freeze on 21 October |
| Wording read as addressed to evaluators | wording scan on 25 October over README, SUBMISSION, presentation, UI strings, comments |

### 8.3 Known limits to state in SUBMISSION.md

No mine plan is public, so plan positions are schematic. Fleet size in 2026, pump ratings, tailings fill state and plant water demand are assumptions. JORC 2019 reserve grade (3.53 g/t) is not used; the model uses reported production grades. Energy is shown only as computed fan and pump power. The work is independent of AltynGold and SATREPS.

### 8.4 Open questions for the human

1. README title: default «Секисовское: цифровой двойник рудника на OpenEgiz». Confirm or give the team name to put in front of it.
2. Docker for agents: is `wsl -d Ubuntu-24.04 -- docker version` usable from the agent shell, and may rehearsals run `docker system prune -af --volumes` there?
3. Three load-bearing assumptions are accepted as written unless a better public source is known: tailings free capacity (about 3.2 Mt at the epoch), plant water 1.123 m³/t, baseline air supply 322 m³/s.
4. Who pushes to `origin/main`: default is the orchestrator after the human's daily look, with pushes on 19, 22, 24 and 25 October.
