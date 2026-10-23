# Norms and equipment for the Sekisovskoye digital twin (research notes)

Prepared 2026-10-14 by a scout for the "Data and Assumptions" section. Public sources only.

Status key:
- CONFIRMED (raw): text read directly by the scout from the primary document (curl, raw HTML text).
- CONFIRMED (WebFetch): read through the WebFetch tool from a primary or official page. The tool returns a model summary, so quotes are close to, not always identical to, the page text.
- UNCONFIRMED: only a search-result snippet, a secondary source, or a figure from the team's own facts file. Not read by the scout in a primary source.
- NOT FOUND: searched; no value in a usable source.

The source documents (HTML of the FY2024 and FY2025 annual reports, the H1 2026 report, the H1 2022 report, the FY2021 results, the Q4 2021 results; a copy of the Permsc PDF) were read from a working copy of the downloads that is not part of the repository; every source is cited below by its public address. Untrusted, not executed.

---

## Q1. Kazakh ventilation norm per unit of engine power (Order No. 352)

### Table 1A. Kazakh rule text and comparison norms

| item | value | unit | source URL | quote or page | status |
|---|---|---|---|---|---|
| Binding order | Order of the Minister for Investments and Development No. 352, 30.12.2014; registered with MoJ 13.02.2015 No. 10247; page states "updated 02.10.2025" | - | https://zakon.uchet.kz/rus/docs/V1400010247 | Page metadata read via WebFetch. The adilet.zan.kz page for V1400010247 returned only the site header ("НЦПС Әділет"), so it could not be read | CONFIRMED (WebFetch, zakon.uchet.kz mirror) |
| Clause on air for internal-combustion machines | point 1063 (Параграф 2. Эксплуатация машин с двигателями внутреннего сгорания, points 1061-1070) | - | https://zakon.uchet.kz/rus/docs/V1400010247 | WebFetch quotes: "Объем воздуха, подаваемого в горные выработки, где работают машины с двигателями внутреннего сгорания," and "определяется Расчетом нормы подачи воздуха на единицу мощности машины с двигателем внутреннего сгорания"; the text cites "приложению 25-1" (Appendix 25-1) | CONFIRMED (WebFetch; partial quotes, the tool would not return the full sentence) |
| Unit, coefficient, kW or hp, all engines or simultaneous engines | not stated in point 1063; set by the Appendix 25-1 calculation | m3/min or m3/s per kW or per hp | - | Appendix 25-1 is not in the zakon.uchet.kz text (it ends at point 2103 with no appendix 25-1). prg.kz copy (https://prg.kz/m/amp/document/39153989) is Appendix 5 to Order 493 (2025) behind a login | UNCONFIRMED (appendix text not found) |
| Point 1063, other sentences | Permissible exhaust concentrations apply underground (Appendix 25 table); CO measured after catalytic neutralizer at exhaust temperature >= 250 C; the point was amended by MChS order of 26.12.2022 No. 336, effective after 60 days | - | https://zakon.uchet.kz/rus/docs/V1400010247 | WebFetch summary of point 1063 and footnote | CONFIRMED (WebFetch) |
| Point 1064 | "Все машины с дизельными двигателями внутреннего сгорания должны оборудоваться системой очистки выхлопных газов." | - | https://zakon.uchet.kz/rus/docs/V1400010247 | WebFetch quote of point 1064 | CONFIRMED (WebFetch) |
| Point 828, item 3 | ventilation is to be calculated "по вредным компонентам выхлопных газов, выделяющихся при применении оборудования с двигателями внутреннего сгорания" (no coefficient) | - | https://zakon.uchet.kz/rus/docs/V1400010247 | WebFetch quote of point 828(3) | CONFIRMED (WebFetch) |
| Point 782 | continuous monitoring of the air quantity supplied to workings where non-explosion-proof ICE machines run ("непрерывно осуществляется контроль за количеством подаваемого воздуха") | - | https://zakon.uchet.kz/rus/docs/V1400010247 | WebFetch quote of point 782 | CONFIRMED (WebFetch) |
| Point 829 (air per person) | "из расчета не менее 6 м3 в минуту на каждого человека" | m3/min per person | https://zakon.uchet.kz/rus/docs/V1400010247 | WebFetch quote of point 829 | CONFIRMED (WebFetch) |
| Reviewer's rule "about 5 m3/min per hp" | not found in any primary text read | m3/min per hp | - | Searches returned only a secondary article (see next row) | NOT FOUND in primary text |
| Per-hp figures in a Russian article | numbers legible in the PDF text layer: 4,2-5; 4-7,7; 5,5; 5; 5; 5,3; 5 m3/min per hp. The article says the normative literature lacks a required rate per unit of ICE power. The country labels (Australia, Canada, China, USA, Russia) come from a search summary and are not legible in the PDF | m3/min per hp | https://journal.permsc.ru/index.php/echo/article/download/echo2020n3p21/1647/3003 | PDF text layer is largely garbled Cyrillic; numbers read from the text layer of a working copy of the PDF (not in the repository) | UNCONFIRMED (secondary; country mapping not verified) |
| Ontario, Reg. 854 s.183.1(1) Rule 2 | "0.06 m3/s per kilowatt engine power" (airflow = engine power x unit airflow requirement, for equipment without a CSA M424.2 certified airflow rate). Informally "100 CFM per brake horsepower rule" | m3/s per kW | https://www.ontario.ca/page/ventilation-requirements-diesel-powered-equipment-underground-mines (page published 13.10.2023, updated 15.12.2023). Regulation text https://www.ontario.ca/laws/regulation/900854 could not be fetched | WebFetch of the ontario.ca page quotes the 0.06 figure and the subsection 183.1(1) reference | CONFIRMED (WebFetch of official government page; regulation text not read directly) |
| Ontario, Rule 3 | after-treatment device: the airflow determined in consultation with JHSC or HSR "may be lower than the airflow rate determined under Rule 1 or 2", based on emission tests after installing the device | - | same Ontario URL | WebFetch summary | CONFIRMED (WebFetch) |
| California, 8 CCR section 7070 | fresh air in an air course "shall never be less than 100 cubic feet of air per minute per brake horsepower of the aggregate diesel equipment ... plus 200 cubic feet of air per minute for each employee" | cfm per bhp (approx. 0.063 m3/s per kW) | https://www.dir.ca.gov/Title8/7070.html | Search-result snippet only; dir.ca.gov was unreachable (connection refused) | UNCONFIRMED |
| MSHA / US federal | "100 cubic feet of air per minute" per brake horsepower quoted on a Q&A site; MSHA 30 CFR 57.5067 is the cited provision; the scout could not confirm the current MSHA wording | cfm per bhp | https://www.salussafety.io/us/thread/do-you-know-msha-regulations--08728f93-f527-49e5-a699-3b5d30d56242 | Search snippet; the quoted text is cut off and may be OSHA rather than MSHA text | UNCONFIRMED |
| West Virginia (state rule) | 75 cfm per rated horsepower for MSHA-approved engines | cfm per hp | https://minesafety.wv.gov/PDFs/Diesel%20Rule%20Final%20no%20underline.pdf | Search snippet only | UNCONFIRMED |
| ILO Encyclopaedia | "between 0.03 and 0.06 m3/s per kW of rated power ... depending on the type of the engine and whether any exhaust gas conditioning is being used" | m3/s per kW | https://iloencyclopaedia.org/part-xi-36283/mining-and-quarrying/item/604-ventilation-and-cooling-in-underground-mines | Search snippet only; the page could not be fetched | UNCONFIRMED |
| Western Australia | no primary WA figure found. The DMIRS/WorkSafe diesel emissions guideline was not readable (redirect loop and fetch failure) | - | https://worksafe.wa.gov.au/publications/management-diesel-emissions-western-australian-mining-operations-guideline ; https://www.dmp.wa.gov.au/Safety/MSH_G_DieselEmissions.pdf | Fetch failed; the 0.05-0.06 m3/s per kW figure for Australia (2019 conference paper) and Queensland (0.06 m3/s/kW, some mines on superseded 0.04) appear only as search snippets with no captured URL | NOT FOUND (WA) / UNCONFIRMED (Australia, Queensland) |

Unit conversions (scout arithmetic, not from sources):
- 5 m3/min per hp = (5/60) / 0.7457 = 0.1117 m3/s per kW.
- 0.06 m3/s per kW = 2.68 m3/min per hp.
- 100 cfm per bhp = 0.0472 m3/s per hp = 0.0633 m3/s per kW.
- 75 cfm per hp = 0.0354 m3/s per hp = 0.0475 m3/s per kW.

### Table 1B. Fleet power and what each rule gives (scout arithmetic)

Engine kW used: model values from params.json and registry.json, and sourced values from Table 3.

| fleet case | engine kW total (no drill rigs) | Kazakh reviewer rule 0.1117 m3/s per kW | model coefficient 0.06 m3/s per kW | model formula 180 + 0.06 x kW |
|---|---|---|---|---|
| Brief fleet, model kW: 5 AD30 x 304 + 4 R1300 x 123 | 2012 kW | 224.7 m3/s | 120.7 m3/s | 300.7 m3/s |
| Brief fleet, sourced kW: 5 AD30 x 299 + 4 R1300 x 117 | 1963 kW | 219.3 m3/s | 117.8 m3/s | 297.8 m3/s |
| params.json base fleet: 4 AD30 x 304 + 1 AD45 x 439 + 3 R1300 x 123 + 1 R1700 x 263 | 2287 kW | 255.4 m3/s | 137.2 m3/s | 317.2 m3/s |
| registry.json full fleet: 4 AD30 x 304 + 8 AD45 x 439 + 3 R1300 x 123 + 7 R1700 x 263 | 6938 kW | 774.9 m3/s | 416.3 m3/s | 596.3 m3/s |

Drill rigs (2 in the brief, 5 in registry.json) are excluded because no engine kW is sourced for them (Table 3). Each 100 kW of rig power adds 11.2 m3/s under the reviewer rule and 6.0 m3/s under 0.06.

Model check: the published 322 m3/s with the model's 0.06 coefficient implies (322 - 180) / 0.06 = 2367 kW of active diesel power. The brief fleet has 2012 kW without rigs, so about 355 kW would be needed for the two rigs. No source gives that figure.

Usage factor implied by 322 m3/s (scout arithmetic):
- Model structure, base 180 m3/s additive: the air left for diesel is 322 - 180 = 142 m3/s. Under the reviewer rule that is a usage factor of 142 / 224.7 = 0.63 for the brief fleet (no rigs), or 142 / 255.4 = 0.56 for the params.json base fleet.
- Base zero (322 is the whole requirement): 322 / 224.7 = 1.43 for the brief fleet, so 322 would satisfy the reviewer rule at full nameplate with headroom.
- The model's own coefficient 0.06 corresponds to a usage factor of 0.06 / 0.1117 = 0.54 on the reviewer rule.

Answer to Q1 (scout reading): the reviewer's 5 m3/min per hp rule is not confirmed. The binding Kazakh text (point 1063) defers the number to Appendix 25-1, which the scout could not read. If the reviewer's rule applied at full nameplate and base air is additive as in the model, the brief fleet would need about 405 m3/s, above 322. If the base is not additive, 322 covers the diesel-only figure of about 225 m3/s. The result therefore depends on the unread Appendix 25-1.

---

## Q2. Ore stockpile at Sekisovskoye

### Table 2A. Stockpile balances (disclosed)

| item | value | unit | source URL | quote or page | status |
|---|---|---|---|---|---|
| Ore stockpile carrying value, 30 Jun 2026 | 24,480 (US$24.5m) | US$'000 | https://www.investegate.co.uk/announcement/bzw/altyngold--altn/half-year-financial-report/9795024 | Note 11 Inventories table row "Ore 24,480 25,830 27,319" (columns 30 Jun 2026, 30 Jun 2025, 31 Dec 2025). Text: "the carrying value of ore stockpiles reduced from US$27.3m at 31 December 2025 to US$24.5m at 30 June 2026" | CONFIRMED (raw) |
| Ore stockpile carrying value, 31 Dec 2025 | 27,319 (US$27.3m) | US$'000 | same | same note row | CONFIRMED (raw) |
| Ore stockpile carrying value, 30 Jun 2025 | 25,830 | US$'000 | same | same note row | CONFIRMED (raw) |
| Total inventories, 30 Jun 2026 / 31 Dec 2025 / 30 Jun 2025 | 45,144 / 46,564 / 37,585 | US$'000 | same | Table sums check: 24,480 + 8,614 + 3,937 + 8,113 = 45,144 (raw/WT) | CONFIRMED (raw) |
| Inventories, 31 Dec 2024 (balance sheet, total) | 23,503 | US$'000 | https://www.investegate.co.uk/announcement/bzw/altyngold--altn/annual-financial-report/9542769 | Consolidated balance sheet line "Inventories 46,564 (2025) 23,503 (2024)". The FY2025 report has no ore line or tonnage | CONFIRMED (raw) |
| Ore stockpile carrying value, 31 Dec 2024 | NOT FOUND | - | FY2024 and FY2025 reports read (see sources) | No ore breakdown in these reports | NOT FOUND |
| Ore stockpile tonnage | NOT DISCLOSED | t | all reports read (list below) | No tonnage of stockpiled ore in any report read: FY2021 and H1 2022 results, FY2024 and FY2025 annual reports, H1 2026 report | NOT FOUND |
| H1 2026 stockpile use | ore processed exceeded ore mined by 40,130t "the difference being drawn from stockpile" | t | https://www.investegate.co.uk/announcement/bzw/altyngold--altn/half-year-financial-report/9795024 | Operating review text | CONFIRMED (raw) |
| FY2024 "Transfer from inventories" | (1,126) in PP&E note 8 (2024, assets under construction) | US$'000 | https://www.investegate.co.uk/announcement/bzw/altyngold--altn/annual-financial-report/9542769 | WebFetch summary of note 8 (this is not an ore stockpile item) | CONFIRMED (WebFetch) |

### Table 2B. Ore mined and milled, 2019-2026

| year | ore mined (t) | ore milled/processed (t) | source URL | quote or table | status |
|---|---|---|---|---|---|
| 2019 | 255,000 | 231,000 | https://www.businesswire.com/news/home/20210430005508/en/Altyn-Plc-UK-Regulatory-Announcement-Final-Results (not reachable from this environment; the FY2020 results text) | Search summary of the FY2020 results: "Ore mined for the year was 255,000 t"; "processed ore which grew 82% from 231,000t to 420,000t" | UNCONFIRMED (secondary summary, primary not reachable) |
| 2020 | 506,050 | 420,256 | https://www.investegate.co.uk/announcement/bzw/altyngold--altn/final-results/7071334 | Table "Mining results ore extraction": Ore mined 571,035 (2021) / 506,050 (2020). Table "Milling": 541,576 (2021) / 420,256 (2020). Same document also says "Ore processed 571,000t (2020 506,000t)" and "the resulting ore processed of 534,000t ... prior year of 506,000t" | CONFIRMED (raw table); internal conflict in the narrative (see note) |
| 2021 | 571,035 | 541,576 | same | same table. Narrative: "ore mined was 571,000t against the budget of 570,000t, the resulting ore processed of 534,000t" | CONFIRMED (raw table); narrative milled 534,000 conflicts |
| H1 2021 | 266,607 | 262,774 | https://www.investegate.co.uk/announcement/bzw/altyngold--altn/half-year-report/7120671 | Table H1 2022 / H1 2021 "Ore mined 277,398 / 266,607"; milled table 306,599 / 262,774 (narrative says "H1 2021: 262,744t") | CONFIRMED (raw) |
| H1 2022 | 277,398 | 306,599 | same | "The milled ore was 306,599t (H1 2021: 262,744t), in the current period, an increase of 17%." | CONFIRMED (raw) |
| 2022 (full year) | 527,231 | 584,223 | https://businesswire.com/news/home/20230505005209/en (not reachable) | Search summary of the FY2022 annual report and Q4 2022 update: mined 527,231 (134,461 + 142,937 + 131,204 + 118,629); milled 584,223 | UNCONFIRMED (secondary; the Q4 quarter labels conflict within the summary) |
| 2023 (full year) | 701,465 (mined, from a Feb 2024 update summary) | ~533,000 inferred (not stated) | https://www.businesswire.com/news/home/20240225738572/en (not reachable) | Summary: "full-year 2023 volume of mined ore increased 33%"; milled "increased 1.1%" | UNCONFIRMED (mined) / NOT FOUND (milled) |
| 2023 label in FY2024 report | "Ore processed 750,045t (2023: 701,000t)" | t | https://www.investegate.co.uk/announcement/bzw/altyngold--altn/annual-financial-report/8845806 | Raw text, operational highlights: "Ore processed 750,045t (2023: 701,000t)" | CONFIRMED (raw); conflicts with the 2023 mined figure above |
| 2024 | 750,045 (mined; FY2025 table) | 593,612 | FY2024 report https://www.investegate.co.uk/announcement/bzw/altyngold--altn/annual-financial-report/8845806 and FY2025 report https://www.investegate.co.uk/announcement/bzw/altyngold--altn/annual-financial-report/9542769 | FY2024 raw text: "Ore extraction for the year totalled 750,000t, with processing volumes reaching nearly 594,000t." FY2025 table (WebFetch): "Milling ... 966,592 (2025); 593,612 (2024)", "Ore mined 926,000t (2024: 750,000t)" | CONFIRMED (raw for 750,000t and ~594,000t; WebFetch for 593,612) |
| 2025 | 926,422 | 966,592 | https://www.investegate.co.uk/announcement/bzw/altyngold--altn/annual-financial-report/9542769 | Raw text: "Ore extraction totaled 926Kt, while processing volumes reached 967Kt"; table values by WebFetch | CONFIRMED (raw text; table values WebFetch) |
| H1 2026 | 458,201 | 498,331 | https://www.investegate.co.uk/announcement/bzw/altyngold--altn/half-year-financial-report/9795024 | Raw text: "Ore mined of 458,201t, up 1.7% (H1 2025: 450,578t)"; "Ore processed of 498,331t, up 10.1% (H1 2025: 452,593t)"; "Ore processed of 498,331t exceeded ore mined of 458,201t by 40,130t" | CONFIRMED (raw) |

Note on conflicts in the sources:
- FY2024 report labels 701,000 t as 2023 "ore processed"; the FY2025 CFO statement reads "increased ore mined (926kt vs. 701kt)", while the FY2025 table gives 750,045 t as 2024 mined. The FY2025 report itself is therefore inconsistent on the 2023/2024 labels.
- FY2021 results give three different 2021 milled values: table 541,576; narrative 534,000; bullet 571,000 (raw text, investegate 7071334).
- The FY2024 report states 2024 ore processed 750,045 t in the highlights, while the table in the FY2025 report gives 2024 milled 593,612 t. The team's facts file (sekisovskoye-facts.md) also flags this as a label error.

### Table 2C. Derived balance (mined minus milled, scout arithmetic)

| period | mined - milled (t) | basis | status |
|---|---|---|---|
| 2019 | +24,000 | 255,000 - 231,000 (secondary) | UNCONFIRMED |
| 2020 | +85,794 | 506,050 - 420,256 (FY2021 results table) | CONFIRMED (raw table) |
| 2021 | +29,459 | 571,035 - 541,576 (FY2021 results table) | CONFIRMED (raw table) |
| 2022 | -56,992 | 527,231 - 584,223 (secondary) | UNCONFIRMED |
| 2023 | 0 to +168,465 | depends on the source; 0 if milled = mined (FY2024 label); +168,465 if milled = ~533,000 | UNRESOLVED |
| 2024 | +156,433 | 750,045 - 593,612 (FY2025 table) | CONFIRMED (WebFetch) |
| 2025 | -40,170 | 926,422 - 966,592 | CONFIRMED (WebFetch table) |
| H1 2026 | -40,130 | 458,201 - 498,331 | CONFIRMED (raw) |
| H2 2026 (model assumption) | -40,000 | model assumption (params.json stockpile.start_t) | ASSUMPTION |

Cumulative sums (scout arithmetic):
- 2024 to H1 2026: 156,433 - 40,170 - 40,130 = +76,133 t.
- The model's 36,000 t equals 156,433 - 40,170 - 40,130 - 40,000 = 36,133 t, i.e. it assumes an opening stock of zero at 1 Jan 2024. It excludes the 2019-2023 surpluses above.
- 2019 to H1 2026: 158,394 t if 2023 is zero; 326,859 t if 2023 is +168,465 t. The 2019 and 2022 inputs are secondary.

Cross-check of the carrying value against tonnage (scout arithmetic; the unit cost is not disclosed):

| assumed cost per tonne (US$/t) | implied ore tonnes at 30 Jun 2026 (US$24.48m) | basis |
|---|---|---|
| 680 | 36,000 t | the tonnage the model uses; requires US$680/t |
| 100 | 245,000 t | illustrative |
| 71 | 346,000 t | H1 2026 change of US$2.839m / 40,130 t drawn = US$70.7/t, if the whole change is tonnage at constant unit cost (rough; ignores ore added and any NRV change) |
| 50 | 490,000 t | illustrative |
| 23 | 1,064,000 t | underground mining cost of US$23 per RoM t quoted in the JORC CPR summary (https://investegate.co.uk/announcement/bzw/altyngold--altn/cpr-results-sekisovskoye-/5663453 , read in team facts file, not re-read by scout; UNCONFIRMED) |

### Q2 conclusions (scout)

What can be concluded:
- The stockpile is recorded at US$24.48m at 30 June 2026 (CONFIRMED). A 36,000 t stockpile would imply about US$680 per tonne, which is high for ore carried at cost. The model's tonnage is therefore hard to reconcile with the carrying value unless the unit cost is very high. A stock of several hundred kilotonnes is consistent with the carrying value at plausible costs (about US$50 to US$100 per tonne).
- The model's 36 kt is the sum of the 2024 to H2 2026 mined-minus-milled flows from a zero opening. The 2019 to 2023 surpluses (2020 and 2021 in particular, CONFIRMED from the FY2021 table) were not included, so the opening stock was probably not zero.
- The 2024 to H1 2026 drawdown is confirmed (H1 2026 narrative).

What cannot be concluded:
- No report read gives any ore stockpile tonnage, low-grade or otherwise. Heap or open-pit stockpile tonnage from before 2016 was not found (the search for the 2015-2016 open pit returned nothing usable).
- The 2019, 2022 and 2023 flows rest on secondary summaries or conflicting labels, so the cumulative stock is somewhere between about 158 kt and 327 kt on those inputs, but this range is not reliable.
- Tonnage, grade and stock location cannot be pinned from public data. The unit cost of the stock is not disclosed.

---

## Q3. Engine power and payload of the fleet

### Table 3. Model values against sourced values

| item | model value (file and line) | sourced value | unit | source URL | quote or page | status | difference |
|---|---|---|---|---|---|---|---|
| CAT AD30 engine power | 304 kW (params.json line 176-180; registry.json line 2126 and others) | 299 kW, Cat C15, ISO 14396:2002 (Tier 3 and VR); not stated whether gross or net. Search summary also cites 305 kW SAE J1995 gross (Peterson listing, not fetched) | kW | https://www.toromontcat.com/mining/equipment/details/underground-mining-trucks/17796875-ad30 (Cat page https://www.cat.com/en_US/by-industry/mining/underground-mining/ug-trucks/AD30.html timed out) | WebFetch: "Engine power: 299 kW (401 hp) under ISO 14396:2002 for both the Tier 3 and VR engines." | CONFIRMED (WebFetch, dealer page reproducing Cat spec) | model +5 kW (+1.7%) vs ISO; 304 is close to the SAE 305 kW |
| CAT AD30 payload | 30 t (params.json line 171-175) | 30,000 kg nominal payload (66,139 lb) | t | same Toromont URL | WebFetch: "Nominal payload capacity: 30000 kg (66139 lb)" | CONFIRMED (WebFetch) | none |
| CAT AD30 gross mass and body | not in model | 60,000 kg gross machine mass; standard body 14.4 m3 heaped SAE 2:1 | kg, m3 | same | WebFetch | CONFIRMED (WebFetch) | - |
| CAT AD45 engine power | 439 kW (params.json line 186-190; registry 2298 and others) | Cat C18: 446 kW Stage V (ISO 14396:2002); 433 kW Tier 3 and VR (ISO 14396:2002). 439 kW SAE J1995 gross appears in dealer listings in search results (westrac.com.au and petersoncat.com node 32236, not fetched) | kW | https://www.miltoncat.com/machinery-equipment/new/c/ad45-underground-articulated-truck (Westrac page returned 403) | WebFetch: "Engine power: 446 kW (598 hp) for the EU Stage V engine, rated under ISO 14396:2002 ... The Tier 3 and VR engines are rated at 433 kW" | CONFIRMED (ISO, WebFetch); SAE 439 UNCONFIRMED | model equals the SAE J1995 value; +6 kW vs Tier 3 ISO, -7 kW vs Stage V ISO. Rating standard must be stated |
| CAT AD45 payload | 45 t (params.json line 181-185) | 45,000 kg nominal payload (99,208 lb) | t | same Milton Cat URL | WebFetch: "Nominal payload: 45000 kg (45 t; listed as 99208 lb)" | CONFIRMED (WebFetch) | none |
| CAT AD45 gross mass | not in model | 89,250 kg gross machine mass | kg | same | WebFetch | CONFIRMED (WebFetch) | - |
| CAT R1300G (R1300) engine power | 123 kW (params.json line 196-200; registry 2629 and others) | 117 kW (157 hp), Cat 3306B DITA, ISO 14396:2002, rated at 2,200 rpm | kW | https://www.toromontcat.com/mining/equipment/details/underground-mining-load-haul-dump-lhd-loaders/18192466-r1300g (cat.com page https://www.cat.com/en_US/by-industry/mining/underground-mining/ug-loaders/R1300G.html timed out) | WebFetch: "Engine power (ISO 14396:2002): 157 hp / 117 kW" | CONFIRMED (WebFetch, dealer page) | model +6 kW (+5.1%) |
| CAT R1300G payload (model field "bucket_t") | 6.8 t (params.json line 201-205) | 6,800 kg nominal payload; dump bucket options 2.5, 2.8, 3.1 (standard), 3.4 m3; ejector bucket 2.4 m3 | t; m3 | same Toromont URL | WebFetch: "Nominal payload: 6800 kg (6.8 t)" | CONFIRMED (WebFetch) | payload matches; the model field is named "bucket_t" but holds payload. Bucket capacity is not in the model |
| CAT R1300G operating mass | not in model | 20,725 kg (operating mass) | kg | same | WebFetch | CONFIRMED (WebFetch) | - |
| CAT R1700 engine power / bucket | 263 kW, 15 t (params.json line 206-210; registry 2690 and others) | NOT CHECKED (not in the brief's search list) | - | - | - | NOT CHECKED | - |
| Atlas Copco / Epiroc Boomer S1D carrier diesel engine power | none (registry.json rig entries have no engine_kw; params.json fleet.base.rigs = 2 units, line 227-231) | NOT FOUND. Epiroc S1D spec page https://www.epiroc.com/en-et/products/drill-rigs/face-drill-rigs/boomer-s1d returned HTTP 403 to curl; WebFetch refused the epiroc.com domain. A used-equipment listing gives "55 kW" for a pipe-jacking unit (not trusted) | kW | - | - | NOT FOUND | - |
| Boomer S1D weight (team facts) | not in model | 12 t | t | https://ecoportal.kz (OVOS D2, sekis/ecoportal_23917.pdf, p.31 Table 1.6) as recorded in team facts file sekisovskoye-facts.md (A2 table) | per team facts file | UNCONFIRMED by scout (team facts file) | - |
| Boomer T1D diesel engine power | none in model | NOT FOUND. Epiroc T1D page not reachable; no spec sheet in search | kW | - | - | NOT FOUND | - |
| Boomer T1D weight (team facts) | not in model | 11 t | t | OVOS D2 p.31 Table 1.7, as recorded in team facts file | per team facts file | UNCONFIRMED by scout | - |
| Diamec 252 | none in model | NOT FOUND (two searches; no Diamec 252 result). Related Epiroc Diamec products from search snippets only: Diamec 232 (15 kW power unit, electric DHC); Diamec PHC 4 (55 kW); PHC 8 (110 kW); MCR (90 kW installed) | kW | https://www.epiroc.com/en/products/drill-rigs/exploration-drill-rigs/core-drilling-rigs/diamec-phc8 (snippet) | - | NOT FOUND | - |
| Boomer M2C / X3EC / M1L / S2 engines (reference only) | none | Boomer M2C: Deutz TCD 2013 L04, 120 kW (dealer listing); X3EC: Deutz TCD 2013 L06, 173 kW (dealer listing); M1L: 59 kW total installed (spec PDF search snippet); S2: Deutz TCD 3.6, 90 kW (mining magazine snippet) | kW | not fetched (search snippets only) | - | UNCONFIRMED (not S1D or T1D) | - |

### Fleet counts: the brief's baseline does not match the model

| source | CAT AD30 | CAT AD45 | CAT R1300 | CAT R1700 | drill rigs | location |
|---|---|---|---|---|---|---|
| Brief (task text) | 5 | - | 4 | - | 2 | task text |
| params.json fleet.base | 4 (line 211) | 1 (line 217, ASSUMPTION) | 3 (line 212) | 1 (line 222, ASSUMPTION) | 2 (line 227, ASSUMPTION) | team/model/params.json |
| registry.json entries | 4 | 8 | 3 | 7 (10 LHDs total) | 5 (4 Boomer S1D, 1 Boomer T1D) | registry.json lines 2112-2604 (haul trucks and LHDs) and 2853-2941 (drill rigs) |
| OVOS D2 (team facts file A4) | 4 (CAT AD30 TU2, p.77) | - (cited as intended in D1 p.2) | 2 (CAT R1300 VHV 2, p.78) | - | Boomer S1D and T1D (p.31) | sekisovskoye-facts.md A4 |
| im-mining 2020 release (secondary, team facts D3) | 3 | - | 3 | - | - | https://im-mining.com/?p=64026 (not fetched by scout) |

The brief's 5 AD30 and 4 R1300 match no source read. The OVOS lists 2 R1300 (p.78); the 2020 release lists 3 R1300 and 3 AD30 (secondary).

---

## Not verified (open items)

1. The Appendix 25-1 calculation for air per unit of ICE power (unit, coefficient, kW vs hp, all vs simultaneous engines). Not in the zakon.uchet.kz mirror; the adilet.zan.kz page returned only the header; the prg.kz copy is behind a login. Next step: a readable copy of the order text with its appendices (adilet.zan.kz with JavaScript, or the official Ministry publication).
2. The reviewer's "5 m3/min per hp" as a Kazakh norm: not found in any primary text.
3. Western Australia: no primary figure found.
4. MSHA and California (primary wording): not fetched; the snippets are unverified.
5. ILO and Queensland figures: not fetched; the snippets are unverified.
6. Boomer S1D and T1D carrier diesel kW, and the Diamec 252 engine: NOT FOUND (Epiroc pages blocked to the tool).
7. Stockpile tonnage: not disclosed in any report read.
8. 2019, 2022 and 2023 ore mined and milled: secondary only (businesswire pages not reachable; LSE mirror returned 403).
9. CAT R1700 engine and payload: not searched.
10. The Cat AD30 and R1300 values use the Toromont dealer pages; the cat.com pages timed out.
