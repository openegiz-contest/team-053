# Sekisovskoye (Секисовское) - sourced facts extraction

Status key: CONFIRMED = read by the scout from the document image or primary RNS text. UNCONFIRMED = from secondary summary, not checked against primary text, or read with a unit/label conflict.

## Source documents

| Code | Document | Local file | Pages | How read |
|---|---|---|---|---|
| D1 | Screening conclusion KZ55VWF00070075, 04.07.2022 (Dept. of Ecology VKO) on the mine plan correction (корректировка плана горных работ), 7 pp. | `sekis/ecoportal_23916.pdf` (ecoportal LoadFile/23916) | 1-7 | CONFIRMED, page images (text layer is garbled, rendered with pdftoppm) |
| D1b | Same screening conclusion, second file version | `sekis/ecoportal_11711.pdf` (LoadFile/11711) | 1-7 | CONFIRMED same header and text as D1 (byte size differs) |
| D2 | Report on possible impacts (Отчет о возможных воздействиях) for the Sekisovskoye mine plan correction, 369 pp., dated 2023 per the text layer (cover not transcribed) | `sekis/ecoportal_23917.pdf` (LoadFile/23917) | selected pp. (listed below) | CONFIRMED on the pages cited; pages not cited were not read |
| D3 | Ecology Dept. conclusion KZ21VVX00219919, 23.05.2023, on the OVOS for the mine plan correction | `sekis/cand/25753.pdf` (ecoportal LoadFile/25753) | p.1 only | Identified only; 13 pp. not read beyond the first page |
| D4 | Public-hearing protocol "Материалы для получения экологического разрешения для ДТОО ГРП BAURGOLD", hearings 24.12.2021 | `sekis/cand/ee075c4288b6f126c2cb99d21ca2915c_original.9488605.pdf` (gov.kz) | p.1 only | Identified only |
| - | ecoportal LoadFile 21043 (2023, 103 pp.), 16851 (2022, 113 pp.), 21274 (2022, 142 pp.), 40800 (2024, "Родниковое", other deposit), gov.kz 6aef30... (2025-12, 27 pp.) | `sekis/cand/` | - | Not opened. No "BAURGOLD"/"Sekis" ASCII hits in text layer (Cyrillic is garbled, so this is not proof of absence). 40800 is a different project |

## A1. Mining method and system (D2)

| Parameter | Value | Unit | Year | Source | Page/section | Status |
|---|---|---|---|---|---|---|
| Deposit is worked underground only; earlier open pit completed 2016 | - | - | 2016 | D1 | p.2 "Краткое описание" | CONFIRMED |
| Mining method: underground, waste backfill, no waste to surface ("без выдачи на поверхность") | - | - | - | D1 p.2; D2 p.41 table 1.11 row 2 | - | CONFIRMED |
| Thickness of ore bodies: small 1.5-3.0 m (m=1.5-2.5 m, 30-50 %), medium 3.5-15 m | 1.5-15 | m | - | D2 | p.30 sec. 1.5.2.3 | CONFIRMED |
| Dip of ore and host rocks | 70-90 | deg | - | D2 | p.30 | CONFIRMED |
| Rock hardness f | 8-10 | Protodyakonov | - | D2 | p.30 | CONFIRMED |
| Interburden between ore bodies (combined mining) | 15-40 | m | - | D2 | p.30 | CONFIRMED |
| Floor (этаж) height, horizontal mining levels | 50 | m | - | D2 | p.25 sec. 1.5.2.1 (end) | CONFIRMED |
| Sublevel (подэтаж) height hn for ore 1.5-2.5 m / 3-3.5 m | 8-10 | m | - | D2 | p.32 Table 1.8 | CONFIRMED |
| Sublevel height hn for ore 4.5-6 m / 7.5-30 m | 13-16 | m | - | D2 | p.32 Table 1.8 | CONFIRMED |
| Drill hole diameter for ore by thickness band | 46-50 / 55-60 / 64-70 / 64-105 | mm | - | D2 | p.32 Table 1.8 | CONFIRMED |
| Drill hole spacing in row / ore thickness band | 1.2-1.35 / 1.45-1.55 / 1.6-1.85 / 1.8-2.6 | m | - | D2 | p.32 Table 1.8 | CONFIRMED |
| Explosive consumption ore breaking, by band | 0.9-1.1 / 0.65-0.75 / 0.5-0.6 / 0.6-0.7 | kg/t | - | D2 | p.32 Table 1.8 | CONFIRMED |
| Maximum charge per delay | 350 | kg | - | D2 | p.32 Table 1.8 | CONFIRMED |
| Conditional ore size after blasting | 350 | mm | - | D2 | p.31 | CONFIRMED |
| Stope systems shortlisted (list of 11 options: sublevel stoping, sublevel open stoping with backfill, cut-and-fill type, etc.) | - | - | - | D2 | p.30 | CONFIRMED (list); the single system finally adopted is NOT named in pages read |
| Backfill: waste rock returned into mined-out space, no surface dump | - | - | - | D1 p.2; D2 p.34, p.41 | - | CONFIRMED |
| Backfill type (cemented or hydraulic) | not found in pages read | - | - | - | - | NOT IN THESE PAGES |
| Stope / pillar dimensions (strike length, width) | not found in pages read | - | - | - | - | NOT IN THESE PAGES |
| Pillar widths by drift design | "per drawing 21.0148.19.001.000-ПР sheets 26-36" (referenced, not in document) | - | - | D2 | p.28 | REFERENCED ONLY |

## A2. Mine geometry and openings (D2, D1)

| Parameter | Value | Unit | Year | Source | Page/section | Status |
|---|---|---|---|---|---|---|
| Mining licence area (horizontal projection) | 0.56 | km2 | - | D1 p.1; D2 p.22 | - | CONFIRMED |
| Deepest working level (design horizon) | -340 | m (elev.) | 2022 | D1 p.1 | "Глубина отработки - до горизонта -340 м" | CONFIRMED |
| Transport decline TU1: portal to bottom | +430 to -300 (extended to +100 and -300 in later stages) | m | - | D2 | p.22, p.25, p.28 | CONFIRMED |
| Transport decline TU1: cross-section in clear / slope | 18.0 m2 / 8 deg | - | - | D2 | p.28 | CONFIRMED |
| Transport decline TU2: portal to bottom | +320 to -200 (to +100 in stage 1) | m | - | D2 | p.22, p.25, p.28 | CONFIRMED |
| Transport decline TU2: cross-section / slope | 18.0 m2 / 8 deg | - | - | D2 | p.28 | CONFIRMED |
| Decline lengths (m) | not found in pages read | m | - | - | - | NOT IN THESE PAGES |
| Existing shaft "Sekisovskaya" (used as ventilation shaft VS1) | to +325 (also "to +320" in fan description), section 10.86 m2 | m; m2 | - | D2 | p.26, p.23, p.25, p.34 | CONFIRMED; elevation +325 vs +320 conflict within D2 |
| Ventilation shaft VS2 (proposed) | section 10.8 m2, to +340 (p.24) and "to horizon 335 m" (p.34) | m | - | D2 | p.24 vs p.34 | CONFIRMED; elevation conflict in D2 (+340 vs +335) |
| Ventilation raise VPV (proposed) | section 7.0 m2, from +324 to -200 | m | - | D2 | p.28 | CONFIRMED |
| Ventilation raises VHV TU1 / TU2 | 5.6 m2; -300 to +200 / -200 to +250 | m | - | D2 | p.28 | CONFIRMED |
| Exhaust raises VHV 7, 8, 10 | 10.75 m2 (two parallel raises 6.1 + 5.6 m2 in stage I) | m2 | - | D2 | p.29 | CONFIRMED |
| Lift raise (LV), emergency egress and hoisting | section 5.8 m2, -300 to -200; Alimak hoist | m2; m | - | D2 | p.28, p.38 | CONFIRMED |
| Total horizontal/vertical development volume (incl. chambers) | 447,354.6 | m3 | plan | D2 | p.29 | CONFIRMED |
| Surface portal/shaft elevations (any others) | +430 (TU1), +320 (TU2), +325 (shaft) | m | - | D2 | p.22, p.26 | CONFIRMED |
| Declines in development (development metres per year, plan) | not found in pages read | m/yr | - | - | - | NOT IN THESE PAGES |
| Current level status, 2025: decline 1 at -34 masl, decline 2 at sea level | - | m | 2025 | AltynGold RNS (see B) | - | CONFIRMED (primary RNS) |

## A3. Production and schedule (D2, D1)

| Parameter | Value | Unit | Year | Source | Page/section | Status |
|---|---|---|---|---|---|---|
| Design ore output (mine plan) | 1000 | kt/yr | plan | D2 | p.22, p.33, p.1.5.2 | CONFIRMED |
| Ore output current (before correction) | 500 | kt/yr | 2022 | D1 p.2 | "В настоящий момент годовая производительность ... 500 тыс. т" | CONFIRMED |
| Ore output ramp per D1 | 1000 kt in 2024-2025; 800 kt in 2026-2028; 426 kt in 2029 | kt/yr | 2024-2029 | D1 | p.2 | CONFIRMED (CONFLICTS with D2 Table 8.4, see below) |
| Calendar schedule of ore output (Table 8.4): 2023 650,000; 2024 800,000; 2025 1,000,000; 2026 1,000,000; 2027 800,000; 2028 800,000; 2029 800,000; 2030 426,305; total 6,276,305 t | 650,000-1,000,000 | t/yr | 2023-2030 | D2 | p.77 Table 8.4 | CONFIRMED; CONFLICTS with D1 p.2 for 2026-2027 |
| Ore output in m3 (Table 8.4) | 229,682 (2023) ... 150,638 (2030); total 2,217,776 | m3 | 2023-2030 | D2 | p.77 | CONFIRMED |
| Overburden/waste (Table 8.4 and Table 9.3): 2023 189,553; 2024 201,618; 2025 235,346; 2026 232,850; 2027 226,250; 2028 155,226; 2029 131,524; 2030 134,875 | total 1,507,241 t (532,594 m3) | t/yr | 2023-2030 | D2 | p.77 Table 8.4; p.141 Table 9.3 | CONFIRMED |
| Exploration/geology drilling | 15,800 (2023), 18,000 each year 2024-2030 | m | 2023-2030 | D2 | p.77 | CONFIRMED; total 141,800 m |
| Explosives consumption (BV) | 752.1 (2023), 854.1, 1007.9, 1005.4, 878.8, 807.7, 677.5, 428.3 (2030) | t/yr | 2023-2030 | D2 | p.77 | CONFIRMED; total 6,412 t |
| Reserve used for mine life: geological balance reserves | 2,327,020 (text says "тыс. т" but the calculation uses 2327.02 thousand t) | t | plan | D2 | p.33 | CONFIRMED value; unit label inconsistent in source |
| Mine life at 1000 kt/yr, Kп 0.944, Kр 0.35 | 6.6 | yr | plan | D2 | p.33 | CONFIRMED |
| Mine life incl. development and wind-down | 11 | yr | plan | D2 | p.33 | CONFIRMED |
| Calculated capacity from mining conditions | 1,023.5 | kt/yr | plan | D2 | p.33 | CONFIRMED |
| Loss and dilution coefficients: Kп 0.944 (loss 5.6 %), Kр 0.35 (text: "П=5,6%, Р=65%") | - | - | plan | D2 | p.33 | CONFIRMED as printed |
| Average stope/level horizontal area S | 2.85 | thousand m2 | plan | D2 | p.33 | CONFIRMED |
| Ore density | 2.83 | t/m3 | plan | D2 | p.33 | CONFIRMED |

## A4. Equipment (D2)

| Equipment | Model / count | Use | Year | Source | Page | Status |
|---|---|---|---|---|---|---|
| Underground drill jumbo for blast holes | Atlas Copco Boomer S1D, 12 t, carrier 1xCOP 1838ME, hole 64-105 mm | blast holes | plan | D2 | p.31 Table 1.6; p.78 Table 8.5 | CONFIRMED |
| Underground drill jumbo for blast holes | Atlas Copco Boomer T1D, 11 t, 1xCOP 1838ME | blast holes | plan | D2 | p.31 Table 1.7; p.78 | CONFIRMED |
| Drill for development rounds | Boomer S1D (electro-hydraulic), holes 42-51 mm | advance drifts | plan | D2 | p.31 | CONFIRMED |
| Exploration drilling rig | Diamec 252 (3650 h 2023-2029) | exploration | plan | D2 | p.78 Table 8.5 | CONFIRMED |
| Breaker/perforator for oversize | "Буровой перфоратор для шпуров", 525 h total | oversize | plan | D2 | p.78 | CONFIRMED |
| Haul trucks, TU2 | CAT AD30, 4 units | ore haulage to surface | plan | D2 | p.77 | CONFIRMED |
| Loaders, VHV 2 | CAT R1300, 2 units | load waste and ore | plan | D2 | p.78 | CONFIRMED |
| Also cited in D1 as intended larger trucks | AD45 and Cat 1700 | plan | 2022 | D1 | p.2 | CONFIRMED |
| Personnel transport | Mitsubishi Delica | - | plan | D2 | p.38, p.77 | CONFIRMED |
| Man-riding lift | Alimak | lift raise -300 to -200 | plan | D2 | p.28, p.38 | CONFIRMED |
| Fuel truck | Utimec MF 350 Fuel (from -50 m) | fuelling | plan | D2 | p.38 | CONFIRMED |
| Diesel consumption | 77 | t/yr | plan | D2 | p.77 | CONFIRMED |
| Compressors (existing) | HertzFrecon 250PLUS; DEN-90; 20 m3/min | compressed air | existing | D2 | p.35 | CONFIRMED |
| Compressed air planned | new surface compressor station near VHV 1, pipeline 159 mm | - | plan | D2 | p.35 | CONFIRMED (number and capacity not stated) |

## A5. Ventilation (D2, D1)

| Parameter | Value | Unit | Year | Source | Page | Status |
|---|---|---|---|---|---|---|
| Ventilation scheme | forcing (нагнетательный) and flank (фланговая), diagonal | - | plan | D1 p.2; D2 p.26, p.34 | - | CONFIRMED |
| Simulation | VentSim | - | plan | D2 | p.34 | CONFIRMED |
| Fresh air, current | 252 | m3/s | existing | D1 p.2 | "Увеличение подачи свежего воздуха с 252 до 322 м3/с" | CONFIRMED |
| Fresh air, planned | 322 | m3/s | plan | D1 p.2, p.4 (also p.4 "322 м3/с") | - | CONFIRMED |
| Surface fan at VS1 | VOD-16P (forcing, on surface at +320 m, Ventilation shaft 1) | - | existing | D2 | p.34 | CONFIRMED |
| Underground fan stage I | AL18-4500V, 2 units (1 working, 1 standby) at +330 m (level 0.0 m under stage I) | - | plan | D2 | p.34 | CONFIRMED |
| Underground fan stage II | AL18-4500V, 8 units (4 working, 4 standby) in modernised chamber, or larger fans | - | plan | D2 | p.34 | CONFIRMED |
| Surface fan at VS2 | Korfmann AL17-2000, 63.0-88.0 m3/s, pressure up to 3000 Pa, with electric heater | m3/s; Pa | plan | D2 | p.24, p.34 | CONFIRMED |
| Heater for intake air | 72 x SFO-100 electric heaters, 100 m3/s total; design min -48.9 deg C; 202-day heating season (VS2) | m3/s | plan | D2 | p.38-39 | CONFIRMED |
| Local face ventilation | VME-6, VME-8 | - | plan | D2 | p.34 | CONFIRMED |
| Exhaust routes | VHV 7, 10 then VHV 1 and 2 to surface; VHV 8 to quarry wall | - | plan | D2 | p.34 | CONFIRMED |

## A6. Mine water and dewatering (D1, D2)

| Parameter | Value | Unit | Year | Source | Page | Status |
|---|---|---|---|---|---|---|
| Average mine inflow, two years (2021, 2022) | 197 and 171 (average 184 for +150 to +100) | m3/h | 2021-2022 | D2 | p.20 | CONFIRMED |
| Expected total inflow to -200 m | 171 | m3/h | plan | D2 | p.20 | CONFIRMED |
| Expected total inflow to -300 m | 150-160 | m3/h | plan | D2 | p.20 | CONFIRMED |
| Inflow to workings at +320 m horizon | not more than 25 | m3/h | plan | D2 | p.21 | CONFIRMED |
| Total mine + technical water into the shaft, typical | 60-70 | m3/h | 2022 | D2 | p.21 | CONFIRMED |
| Historical 1984 mean / max (May) / min (Feb) | 53 / 62 / 44 | m3/h | 1984 | D2 | p.21 | CONFIRMED (historical, not current) |
| Design inflow "as approved in the mine plan" | 430 | m3/h | plan | D1 p.3 | "составит 430 м3/ч" | CONFIRMED |
| Pumping stations | main drainage at +150 m and -200 m; sectional at -300 m | - | plan | D2 | p.23, p.39 | CONFIRMED |
| Pumps at quarry sump | 3 pumps x 150 m3/h (2 working, 1 standby) | m3/h | plan | D1 p.3 | - | CONFIRMED |
| Mine water route | cascade -300 m to -200 m, then +150 m, then surface via ventilation shaft to settling ponds | - | plan | D2 | p.35, p.45 | CONFIRMED |
| Settling ponds (ilo-stoyniki) | volume 4530 m3, 6 h settling, pond area 755 m2 at 3 m depth; two ponds in series (upper, lower) | m3; m2 | plan | D2 | p.35, p.45 | CONFIRMED |
| Water balance 2023-2030: total use | 1,726.231 (of which mine water 1,725.72; domestic 0.511) | thousand m3/yr | 2023-2030 | D2 | p.36-37 Table 1.9 | CONFIRMED |
| Reused on site (BAURGOLD technological needs) | 602.688 | thousand m3/yr | 2023-2030 | D2 | p.36-37 | CONFIRMED |
| Transferred to Altyn MM concentrator | 1,123.032 | thousand m3/yr | 2023-2030 | D2 | p.36-37 | CONFIRMED |
| Discharge to Volchevka stream (emission permit, pipe no. 1, 2020) | 1,917.1123 | thousand m3/yr | 2020 permit | D1 p.3 | "Объем сбрасываемых вод в реку Волчевка ... 1917,1123 тыс. м3/год" | CONFIRMED; CONFLICTS with D2 balance (plan to end the discharge) |
| Pollutant mass in discharge (permit) | 642.09113 | t/yr | 2020 permit | D1 p.3 | - | CONFIRMED |
| Plan: discharge to Volchevka to be eliminated | - | - | plan | D2 | p.35-36, p.130 | CONFIRMED |
| Discharge limits (parameter values) | not in pages read | - | - | - | - | NOT IN THESE PAGES |
| Sludge (settling pond) yield | 64.3 max (2023 OVOS); 23.43 (2020, per D1 p.4); inflow 1725.72 thousand m3/yr, concentration 39.563 mg/l, settling coefficient 94.9 % | t/yr | 2023 | D2 p.140 Table 9.2; D1 p.4 | - | CONFIRMED both; D1 comment 12 asked for justification of the 7x lower sludge figure |

## A7. Water use (D1, D2)

| Parameter | Value | Unit | Year | Source | Page | Status |
|---|---|---|---|---|---|---|
| Domestic supply: infiltration intake along Sekisovka river | - | - | plan | D1 p.3; D2 p.35 | - | CONFIRMED |
| Special water-use permit | KZ14VTE00060177, 05.05.2021 | - | 2021 | D1 p.3 | - | CONFIRMED |
| Calculated water use under permit | 20,225 | m3 | 2021 permit | D1 p.3 | - | CONFIRMED; CONFLICTS with D2 balance (domestic 0.511 thousand m3, mine/quarry water is separate) - the basis of the 20,225 figure is not stated |
| Water-protection zone / strip | zone 500 m, strip 35 m from waterline | m | 2009-2012 | D1 p.4; D1 p.3 | "Постановление № 133 от 14.06.2012" | CONFIRMED |
| Water courses | Sekisovka river (quarry about 150 m from SW bank); Volchevka stream: 60 m from quarry south boundary; Volchevka 735 m long to Sekisovka | m | - | D1 p.3 | - | CONFIRMED |
| Fresh water quality | soft to moderately hard, 2.4-6 mg-eq/l hardness, Na-type 0.3-0.4 g/l | - | - | D2 | p.20 (sec. 1.2.4) | CONFIRMED |

## A8. Power (D2, D1)

| Parameter | Value | Unit | Year | Source | Page | Status |
|---|---|---|---|---|---|---|
| Supply | 110/6 kV substation (GPP); 6 kV lines to PS 6/0.4 kV and to tunnel portal 3 | kV | plan | D2 | p.24, p.40 | CONFIRMED |
| Surface transformer substation | PS 6/0.4 kV, 6 x 1600 kVA and 2 x 1000 kVA (block-modular) | kVA | plan | D2 | p.40 | CONFIRMED |
| Diesel-gen. substation DGPS | 10000 kVA, 6 kV, five generator sets | kVA | plan | D2 | p.40 | CONFIRMED |
| Diesel gensets DGU | 2 x 2000 kVA, 6 kV (DGU 2000 kVA) | kVA | plan | D2 | p.23-24, p.40 | CONFIRMED |
| DGPS 4000 kVA | 6 kV | kVA | plan | D2 | p.40 | CONFIRMED |
| Substation for VS2 fan | PS 2KTPB-4000/6/0.4 | kVA | plan | D2 | p.40 | CONFIRMED |
| Underground | CTP-400/6 kV and KTP-100/6 kV (CRU-RN cells) | kV | plan | D2 | p.40 | CONFIRMED |
| Lighting | 127 V from lighting units | V | plan | D2 | p.40 | CONFIRMED |
| Power demand (kW) and annual energy (kWh/yr) | not found in pages read | - | - | - | - | NOT IN THESE PAGES (not exhaustively searched in D2) |

## A9. Tailings facility (D2, D1)

| Parameter | Value | Unit | Year | Source | Page | Status |
|---|---|---|---|---|---|---|
| Facility | 4th section of tailings facility, owned by BAURGOLD (lease No. 19 (11) 05.01.2020) | - | - | D2 | p.143 | CONFIRMED |
| Coordinates | 50 deg 20' 23.88" N, 82 deg 36' 29.88" E | - | - | D2 | p.143 | CONFIRMED |
| Commissioned | 2017 | - | 2017 | D2 | p.143 | CONFIRMED |
| Capacity before reconstruction | 1,300,000 m3 (1,755,000 t) | m3; t | - | D2 | p.143 | CONFIRMED |
| Capacity after reconstruction | 2,357,000 m3 (3,181,950 t) | m3; t | - | D2 | p.143 | CONFIRMED |
| Area | 1.53 | km2 | - | D2 | p.143 | CONFIRMED |
| Deposition rate (permit basis) | 677,473 (2023) and 169,128 (2024) | t/yr (text says "тыс.т/год") | 2023-2024 | D2 | p.143 | CONFIRMED value; UNIT CONFLICT (677,473 thousand t/yr is implausible, read as t/yr) |
| Tailings composition | solids 60 % moisture, bulk 1.35 t/m3, density 2.67-2.91 t/m3, SiO2 56 % | - | - | D2 | p.143 | CONFIRMED |
| Gold in tailings (as printed) | 0,2 % (printed as %; likely g/t or unit slip) | % | - | D2 | p.143 | UNCONFIRMED unit |
| Tailings delivered by | Altyn MM (mining site plant) | - | - | D2 | p.143 | CONFIRMED |
| Dams | body of dam and clay blanket (понур) form the seepage barrier | - | - | D2 | p.143 | CONFIRMED |
| Dam heights, dam crest, raise schedule | not found in pages read | - | - | - | - | NOT IN THESE PAGES |
| Plan: expand existing dams in 2026 (AltynGold RNS FY2025) | - | - | 2026 | AltynGold RNS (see B) | - | CONFIRMED |

## A10. Emissions, waste and sanitary zone (D2, D1)

| Parameter | Value | Unit | Year | Source | Page | Status |
|---|---|---|---|---|---|---|
| Total atmospheric emissions (incl. autotransport) | 2023 27.93; 2024 29.95; 2025 32.50; 2026 32.45; 2027 30.15; 2028 29.07; 2029 27.11; 2030 22.61 | t/yr | 2023-2030 | D2 | p.44-45 | CONFIRMED |
| Number of sources | 21 total (11 organised, 10 unorganised) | - | plan | D2 | p.44 | CONFIRMED |
| Emission permit KZ61VCZ01763529 (11.04.2022) limits | emissions 2022 22.19605; 2023 25.85863; 2024 24.97419 | t/yr | 2022-2024 | D2 | p.328 (permit pp.1-32 of attachment) | CONFIRMED |
| Discharge permit limits, same permit | 424.61787 (2022); 584.851046 (2023); 584.85105 (2024) | t/yr | 2022-2024 | D2 | p.328 | CONFIRMED |
| Screening-era emissions (2020 permit KZ10VCZ00574839, per D1 p.2-3) | 25.06 (2022), 24.85 (2023), 25.83 (2024), 25.65 (2025), 25.64 (2026), 25.69 (2027), 25.80 (2028), 25.81 (2029) | t/yr | 2022-2029 | D1 p.2-3 | - | CONFIRMED |
| Waste limits (Table 9.4): TBO (household) | 14.775 | t/yr (code 20 03 01) | plan | D2 | p.142 | CONFIRMED (screening-era figure 16.05 t/yr, D1 p.4) |
| Scrap metal | 6.75 | t/yr (17 04 05) | plan | D2 | p.142 | CONFIRMED |
| Worn PPE | 0.455 | t/yr (15 02 03) | plan | D2 | p.140, p.142 | CONFIRMED |
| Sludge from settling ponds (max) | 64.3 | t/yr (19 08 16) | plan | D2 | p.140, p.142 | CONFIRMED |
| Mercury lamps | 0.007 | t/yr (20 01 21*) | plan | D2 | p.141, p.142 | CONFIRMED |
| Overburden to goaf | 189,553 (2023) ... 134,875 (2030) | t/yr | 2023-2030 | D2 | p.141 Table 9.3 | CONFIRMED |
| Sanitary protection zone (SZZ) boundaries per sanitary conclusion No. 426 (10.06.2014) | SE 435; S 395; SW 455; W 342; NW 302 | m | 2014 | D2 | p.135 sec. 8.4; sanitary conclusion pp.183-199 | CONFIRMED; SZZ area 0.4 km2 (p.199) |
| Nearest residential zone | NW, 302 m from emission sources | m | 2014 | D2 p.199; p.135 | - | CONFIRMED |
| Nearest village Sekisovka | 200-300 m from deposit (south/south-east side); about 2,000 residents | m; persons | - | D1 p.3 | - | CONFIRMED |
| District centre Glubokoye | 29 km NE of Glubokoye (village Sekisovka) and 40 km N of Ust-Kamenogorsk | km | - | D2 p.162 | - | CONFIRMED |
| Ust-Kamenogorsk to Glubokoye (district centre) | 27 km | km | - | D2 p.49 | - | CONFIRMED |
| Nearest railway station | Zashchita (Ust-Kamenogorsk), 40 km | km | - | D1 p.1 | - | CONFIRMED |
| Workforce | 214 | persons | 2023 | D2 | p.140 | CONFIRMED |
| Shift regime | 360 working days/yr, 2 shifts/day, 11 h shift underground and surface | - | plan | D2 | p.33 | CONFIRMED |
| Site plan | ситуационная карта-схема, legend includes SZZ boundary, pits, ilo-ponds, tailings, Sekisovka and Volchevka | - | - | D2 | p.195 (App. 3) | CONFIRMED (image) |

## B. AltynGold operating figures (primary RNS text, 29 Apr 2026 release)

Source files: `sekis/altn_9542769.txt` (FY2025 RNS, Investegate ID 9542769, primary HTML) and `sekis/altn_8845806.txt` (FY2024 RNS, Investegate ID 8845806, 25 Apr 2025, primary HTML). Raw HTML saved as `sekis/altn_*.html`.

| Metric | FY2025 | FY2024 | Unit | Source | Status |
|---|---|---|---|---|---|
| Ore mined | 926,422 | 750,045 | t | altn_9542769 table "Mining results ore extraction" | CONFIRMED (2024 headline text "750,000t" rounded) |
| Ore milled (processed) | 966,592 | 593,612 | t | altn_9542769 table "Milling" | CONFIRMED. The FY2024 RNS "Ore processed 750,045t" is a mislabel of ore mined (see note) |
| Mined gold grade | 2.06 | 2.10 | g/t | altn_9542769 table | CONFIRMED |
| Milled gold grade | 2.05 | 2.29 | g/t | altn_9542769 table | CONFIRMED |
| Gold recovery | 85.07 | 85.42 | % | altn_9542769 table; headline 85.07 / 85.4 | CONFIRMED |
| Silver recovery | 74.23 | 75.38 | % | altn_9542769 table | CONFIRMED |
| Gold poured | 53,852 | 37,279 | oz | altn_9542769 | CONFIRMED |
| Gold sold | 50,442 | 38,708 | oz | altn_9542769 | CONFIRMED |
| Contained gold (table) | 63,506 | 43,644 | oz | altn_9542769 | CONFIRMED |
| Horizontal underground development | 73,832 | 4,079 (tunnelling; 2023: 6,432) | m | altn_9542769 CEO statement; altn_8845806 CEO statement | CONFIRMED |
| Blast-hole drilling | "Exploration drilling of blast holes at Sekisovskoye 169,000" | 216,000 (2023: 151,116) | m | altn_9542769; altn_8845806 | CONFIRMED values; category labels differ between RNS years |
| Exploration drilling (CEO) | over 22,000 | 19,200 (2023: 11,756) | m | altn_9542769; altn_8845806 | CONFIRMED; FY2025 RNS summary table says 169,000 for blast-hole exploration |
| Teren-Sai core drilling | approx. 9,700 | 17,535 (54 holes) | m | altn_9542769; altn_8845806 | CONFIRMED |
| Operating cash cost | 1,252 | 992 | US$/oz | altn_9542769 (financial review) | CONFIRMED |
| Total cash cost | 1,399 | 1,162 | US$/oz | altn_9542769 | CONFIRMED |
| AISC | 1,562 | 1,318 | US$/oz | altn_9542769 | CONFIRMED |
| Average gold price realised | 3,474 | 2,441 | US$/oz | altn_9542769 | CONFIRMED |
| Capex (headline) | 15.6 (FY2025 total capital expenditure per cash flow review: "capital expenditure US$15.6m" but total capex in one note is US$28m including US$19.8m non-sustaining) | 21.9 (cash flow headline); 24 (note) | US$m | altn_9542769 | CONFIRMED; the two capex figures in FY2025 are both printed |

### B1. Capex plan 2026-2028 (FY2025 RNS, "Projected capital expenditure")

| Category | Total | 2026 | 2027 | 2028 | Status |
|---|---|---|---|---|---|
| Underground development | 34 | 16 | 9 | 9 | CONFIRMED (primary raw text) |
| Infrastructure (buildings, facilities) | 23 | 13 | 5 | 5 | CONFIRMED (primary raw text) |
| Mining equipment | 29 | 17 | 6 | 6 | CONFIRMED (primary raw text) |
| Tailings dumps | 1 | 1 | - | - | CONFIRMED (primary raw text) |
| Process plant equipment | 8 | 4 | 2 | 2 | UNCONFIRMED (row truncated in raw extraction; figures from WebFetch summary, column sums reconcile to total 95 and per-year totals 51/22/22) |
| Total | 95 | 51 | 22 | 22 | Reconciles by arithmetic |

FY2024 capex budget: US$61m (2023: US$32m) for Sekisovskoye declines and tailings (altn_8845806, CEO statement).

### B2. Plant line and expansion (verbatim)

- FY2024 RNS: "successfully commissioned the third production line at Sekisovskoye, increasing processing capacity by 50% to 1Mtpa" (altn_8845806 line 24; Chairman line 59 "In December, the third production line at Sekisovskoye was successfully commissioned on time and budget, increasing processing capacity by 50% to 1Mtpa.").
- FY2024 RNS has no statement about a 2 Mtpa expansion (grep of altn_8845806 for "2Mtpa/expan" found only plant-completion wording).
- FY2025 RNS, Outlook (altn_9542769 line 53): "The Company has set a production benchmark of 50,000oz of gold and an ore processing capacity of 1Mtpa. Building on this foundation, it is actively pursuing opportunities to expand capacity to 2Mtpa."
- FY2025 CEO (line 76): "we are evaluating plans to increase processing capacity to 2-2.5Mtpa, potentially boosting annual production to over 100,000 ounces in the medium term. Updates on these plans will be shared in the coming months."
- FY2025 Operations (line 95): "studies underway on a potential increase to 2-2.5Mtpa. An update will be provided to the market by mid-year."
- Pending decision: no final decision in the FY2025 RNS. Timing: market update promised "by mid-year" (2026); the outlook says updates expected in Q2 and Q3 2026. Status as of the latest primary text (dated 29 Apr 2026): pending.

### B3. Declines, ventilation, drainage

- FY2024 (altn_8845806 line 91): "Decline No. 1 reaching +0masl in January 2025 and Decline No. 2 to +34masl by year-end. Backfilling, ventilation, and drainage works progressed in parallel, with new infrastructure installed for main fan units on Decline No. 2."
- FY2025 (altn_9542769 line 47): "Transport decline 1 is at -34masl, decline 2 is at sea level (2024: Decline 1 at sea level, decline 2 at +34masl)".
- FY2025 (altn_9542769 line 46 and 92): "Development of the ventilation works and buildings to support continued development of the underground to lower levels." and "Key infrastructure upgrades were also completed, including improvements to ventilation and drainage systems and the expansion of tailings storage".
- FY2025 (altn_9542769 line 48): "Completion of the main drainage complex at +150masl, and laying associated pipelines amounting to 1,700 linear metres."
- FY2025 (altn_9542769 line 49): "Reconstruction of tailings dam 4 to extend its capacity was completed." and line 93: "To manage the rise in tailings from higher production, the Company will expand existing dams in 2026."
- 2026 guidance (altn_9542769 line 80): "we expect production of 52-55Koz".

### B4. Conflicts resolved (2024 figures)

| Figure | Earlier scout value | Resolution |
|---|---|---|
| Ore mined 2024 | 750,045 t vs 701 kt | 750,045 t is ORE MINED in 2024 (FY2025 RNS table, 2024 column). 701,000 t is ORE PROCESSED in 2023 (FY2024 RNS line 36 "2023: 701,000t"), not 2024 |
| Ore milled 2024 | 750,045 t (per FY2024 RNS "Ore processed") | 593,612 t per FY2025 RNS milling table; FY2024 CEO "processing volumes reaching nearly 594,000t". The FY2024 RNS headline 750,045 is a label error |
| Grade 2024 | 2.10 vs 2.29 g/t | Mined 2.10 g/t and milled 2.29 g/t per FY2025 RNS table. FY2024 RNS headline calls 2.29 "mined", which is the milled grade |
| FY2025 mined grade | headline 2.05 g/t | Table: mined 2.06, milled 2.05. Headline in FY2025 RNS labels 2.05 as mined |

### B5. Note on the WebFetch summaries

Two WebFetch summaries (one per RNS) were checked against the primary HTML text. The FY2025 summary's operating and capex numbers reconcile with the primary text, except process plant capex (row truncated). The FY2024 summary's "ore processed 750,045" and "mined grade 2.29" repeat the RNS labelling error and were not used.

## C. Gaps (not found in the pages read)

- Power demand (kW) and annual energy (kWh/yr): not found in D2 pages 39-40 or in other pages read.
- Discharge limits (mg/l or t/yr per parameter) for the Volchevka outfall: not in D1 pp.3 or D2 pages read (only totals).
- Stope and pillar dimensions, backfill type (cemented or hydraulic): not in pages read.
- Decline lengths, deepest working level for the current decline: not in pages read.
- Tailings dam heights and raise schedule: not in pages read.
- Exact system finally adopted from the list of 11 mining systems: not named in pages read.
- Ore head grade for the mine plan (g/t): not found in pages read (D1 p.1-7, D2 selected pages).
- D2 pages not read: about 330 of 369 (only pages cited above were viewed).
- D3 (25753, 13 pp.) and D4 (ee075..., 21 pp.): only page 1 read.

## D. Additional sources collected on 2026-10-13 (outside the documents above)

Source URLs for the codes used in sections A and B: D1 `https://ecoportal.kz/Rubric/RubService/LoadFile/23916`, D1b `https://ecoportal.kz/Rubric/RubService/LoadFile/11711`, D2 `https://ecoportal.kz/Rubric/RubService/LoadFile/23917`, D3 `https://ecoportal.kz/Rubric/RubService/LoadFile/25753`; FY2025 RNS `https://www.investegate.co.uk/announcement/bzw/altyngold--altn/annual-financial-report/9542769`; FY2024 RNS `https://www.investegate.co.uk/announcement/bzw/altyngold--altn/annual-financial-report/8845806`.

### D1. Half-year report H1 2026 (AltynGold RNS, 29 Sep 2026)

Source: `https://www.investegate.co.uk/announcement/bzw/altyngold--altn/half-year-financial-report/9795024`. Read through a summarising fetch: figures UNCONFIRMED until checked against the raw text.

| Parameter | H1 2026 | H1 2025 | Unit |
|---|---|---|---|
| Ore mined | 458,201 | 450,578 | t |
| Ore processed | 498,331 | 452,593 | t |
| Gold grade, mined | 1.81 | 2.02 | g/t |
| Gold grade, processed | 1.76 | 2.04 | g/t |
| Gold recovery | 84.55 | 84.75 | % |
| Gold poured | 23,906 | 25,081 | oz |
| Gold sold | 24,628 | 22,595 | oz |
| Development of the two transport declines | 330 | 322 | linear m |

- Expansion: review of raising processing capacity to 2.0-2.5 Mtpa continues; "no investment decision has yet been made"; update expected "by the end of 2026".
- Near-term step: capacity of the existing plant "can be increased by approximately 200kt per annum"; new crushing and milling equipment ordered.
- Plant ran at its 1 Mtpa nameplate capacity throughout H1 2026.
- Tailings: expansion of Tailings Dams 2 and 3 has commenced to provide the storage needed for the planned capacity increase.
- Declines: Decline No.1 advanced 230 linear m from -34 masl to -50 masl; Decline No.2 at 0 masl, 100 linear m completed, reaching -34 masl planned for H2 2026.
- Additional transport equipment purchased; backfilling of voids continues; a Q1 2026 vertical gap between ore bodies was bridged, removing a temporary constraint on the mining sequence; Q1 2026 mined grade dipped from 2.04 to 1.73 g/t during upper-horizon mining (secondary summary).
- Group AISC H1 2026: US$1,995/oz (secondary summary). FY2026 guidance 52-55 koz.
- Expansion capex estimate about US$125m: Q3 2025 results, secondary summary only, UNCONFIRMED (`https://www.investegate.co.uk/announcement/bzw/altyngold--altn/3rd-quarter-results/9194910`).

### D2. JORC competent person's report, EY, effective 31 May 2019 (Altyn RNS, 7 Oct 2019)

Source: `https://investegate.co.uk/announcement/bzw/altyngold--altn/cpr-results-sekisovskoye-/5663453`. Read by an earlier scout from the RNS page.

| Parameter | Value |
|---|---|
| Mineral Resources, cut-off 1.50 g/t Au | 69.66 Mt @ 2.98 g/t, 6.68 Moz Au |
| Measured + Indicated (levels +250 to -400 m) | 32.51 Mt @ 3.68 g/t, 3.85 Moz Au |
| Ore Reserves (to -400 m) | 33.45 Mt @ 3.53 g/t, 3.80 Moz Au; 6.20 Moz Ag |
| Modifying factors | dilution 5 %, mining loss 2 %, Au recovery 83 %, US$1,280/oz, underground mining cost US$23 per RoM t |
| Exploration target -800 to -1,500 m | 22.79 Mt, 1.74 Moz (conceptual) |

Note the conflict with D2 (OVOS) p.33, which gives a geological reserve of 2,327,020 t and a 6.6-year life at 1,000 kt/yr: the OVOS figure covers the mine-plan correction scope, the JORC figure the whole deposit. Do not mix them without stating which is used.

### D3. Location and project context

- Sekisovka village, Glubokoye district, East Kazakhstan region; about 40 km from Ust-Kamenogorsk (Hambledon/GoldBridges H2 2014 update, `https://www.investegate.co.uk/announcement/rns/altyngold--altn/h2-2014-operational-update/3913593`).
- Coordinates 50°19'43.17" N, 82°35'47.81" E (D1 p.1).
- SATREPS "Next-generation Smart Mining Plus for Sustainable Resources Development" (Hokkaido University, Nazarbayev University; April 2025 to March 2030) names AltynGold's Sekisovskoye mine as its site: JICA ex-ante evaluation `https://www2.jica.go.jp/ja/evaluation/pdf/2024_202313276_1_s.pdf`, JST page `https://www.jst.go.jp/global/english/kadai/r0601_kazakhstan.html`.
- Fleet reported in a 2020 company release (secondary, im-mining `https://im-mining.com/?p=64026`): 3 Cat R1300 LHDs, 3 Cat AD30 trucks delivered 2020; Epiroc T1D jumbos on order. Consistent with the OVOS equipment list in section A4.
