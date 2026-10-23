# Sekisovskoye: open spatial data for a real-surface 3D scene

Scout research, 16 Oct 2026. Scratch root: a working copy of the downloads and scripts, not part of the repository.
(abbreviated below as `SCRATCH/`).

Tags: **CONFIRMED** = seen by the scout in the downloaded data or in the fetched primary page; **UNCONFIRMED** = from a secondary source, a search snippet, from memory, or not checked.

## 0. Reference frame and method

- Mine point (given, environmental screening): 50°19'43.17" N, 82°35'47.81" E = **50.3286583 N, 82.5966139 E** (CONFIRMED arithmetic). UTM 44N: **E 613640.00, N 5576392.36** (computed with `SCRATCH/_scripts/utm.py`, round-trip error < 1e-8 deg; CONFIRMED).
- Working 4 × 4 km box = ±2000 m around the mine point, using 111 320 m per degree latitude and 111 320·cos(lat) per degree longitude. Box: S 50.31069, N 50.34662, W 82.56847, E 82.62476 (CONFIRMED from script output).
- Offsets in this file: N = north metres, E = east metres from the mine point. Lat/lon in section 5 use the same flat-earth factor (error well under 5 m at this scale).
- Scripts (all run with `python -I`): `SCRATCH/_scripts/` (dem_crop.py, dem_pit.py, srtm_crop.py, srtm_vs_dem.py, s2_crop.py, osm_features.py, utm.py). The packages numpy 2.5.4 and imagecodecs were installed with `pip --target SCRATCH/_pylib` (scratch only). The global Python was not changed; pip printed a numba/numpy version warning for the global environment, which was not acted on.

## 1. Elevation

### 1a. Copernicus DEM GLO-30 (primary)

- Tile: `Copernicus_DSM_COG_10_N50_00_E082_00_DEM` (covers 50–51 N, 82–83 E).
- Download URL: https://copernicus-dem-30m.s3.eu-central-1.amazonaws.com/Copernicus_DSM_COG_10_N50_00_E082_00_DEM/Copernicus_DSM_COG_10_N50_00_E082_00_DEM.tif — HTTP 200 (CONFIRMED). Downloaded to `SCRATCH/dem/cop30_N50_E082.tif`.
- File size: **29,339,562 bytes** (CONFIRMED). Format: tiled float32 GeoTIFF, WGS84 (EPSG:4326), deflate + floating-point predictor (needs imagecodecs to read). Shape 3600 × 2400 px; pixel scale 1/2400° lon × 1/3600° lat = **≈29.6 m E-W × 30.9 m N-S** at this latitude (CONFIRMED from tags and script).
- Resolution: 30 m (CONFIRMED from pixel scale; product name GLO-30).
- Type: **Digital Surface Model** (includes vegetation and built features) per the licence text, Art. 2 (CONFIRMED, https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Data/DEM/resources/license/License-COPDEM-30.pdf; read directly).
- Acquisition period: derived from TanDEM-X radar data. Sources differ: **2011–2015** per ESA MAAP catalogue (https://catalog.maap.eo.esa.int/catalogue/series/eo:platform/TanDEM-X/EOP:ESA:CopDem) and **2010–2015** per EMD DEM wiki (https://help.emd.dk/mediawiki/index.php/Copernicus_DEM) and RGI citation guide (https://www.glims.org/rgi_user_guide/products/dem_citations.html). The Product Handbook (v5.0, https://dataspace.copernicus.eu/sites/default/files/media/files/2024-06/geo1988-copernicusdem-spe-002_producthandbook_i5.0.pdf) was not read to the acquisition-date section. **UNCONFIRMED** exact window; in either case the acquisition ends in 2015, before the pit was completed in 2016.
- Vertical reference: heights are referred to the EGM2008 geoid (standard for Copernicus DEM). **UNCONFIRMED** here (not read from the handbook in this session).

Cropped result (CONFIRMED from `SCRATCH/_scripts/dem_crop.py` output):
- Crop: 130 rows × 136 cols, lat 50.31069–50.34662, lon 82.56847–82.62476.
- Files: GeoTIFF (EPSG:4326, float32, tiepoint at crop origin) `SCRATCH/dem/sekisovskoye_dem_4km.tif` (71,120 bytes); NumPy `SCRATCH/dem/sekisovskoye_dem_4km.npy`; CSV `SCRATCH/dem/sekisovskoye_dem_4km_elev.csv`; metadata `SCRATCH/dem/sekisovskoye_dem_4km_meta.json`; hillshade preview `SCRATCH/dem/sekisovskoye_dem_4km_hillshade.png`.
- Elevation range in the 4 km crop: **389.7 m to 550.8 m**, mean 455.1 m (CONFIRMED).
- Mine point pixel: **411.2 m** (CONFIRMED). Mean within 150 m / 300 m / 500 m of the mine point: 417.4 / 431.3 / 436.8 m (CONFIRMED).
- The pit is **visible** as a closed depression with floor minimum **389.7 m** at N −87, E −1 m (CONFIRMED). The hillshade shows the pit walls and a flat rectangular feature NE (see section 1d and 2b).

### 1b. SRTM 1 arc-second (alternative, via Skadi/Terrain Tiles)

- Tile used: `N50E082.hgt.gz`, URL https://elevation-tiles-prod.s3.amazonaws.com/skadi/N50/N50E082.hgt.gz — HTTP 200 (CONFIRMED). Also served at https://s3.amazonaws.com/elevation-tiles-prod/skadi/N50/N50E082.hgt.gz (CONFIRMED). Size **9,325,113 bytes** (CONFIRMED). Downloaded to `SCRATCH/srtm/N50E082.hgt.gz`.
- Resolution: 1 arc-second, 3601 × 3601 samples, void-free in this tile (CONFIRMED: no −32768 values; min 242, max 1288 m).
- Acquisition: SRTM mission, February 2000 — **UNCONFIRMED** here (from general knowledge; not checked against a NASA page in this session).
- Licence: the Skadi tiles are Mapzen/Tilezen "Terrain Tiles" (https://registry.opendata.aws/terrain-tiles/, read: CONFIRMED). The attribution document is https://github.com/tilezen/joerd/blob/master/docs/attribution.md — **not read** (UNCONFIRMED wording). Underlying NASA SRTM is generally treated as US-government public domain — **UNCONFIRMED**.
- The original USGS LP DAAC URL for N50E082 returned 404 (CONFIRMED, https://e4ftl01.cr.usgs.gov/MEASURES/SRTMGL1.003/2000.02.11/N50E082.SRTMGL1.hgt.zip); the Skadi copy was used instead.
- Crop: 131 × 205 samples, `SCRATCH/srtm/sekisovskoye_srtm1_4km.npy` (107,548 bytes), CSV `..._elev.csv`, meta `..._meta.json`. Range 410–557 m; mine-point value **479 m** (CONFIRMED). No GeoTIFF was written for SRTM.

### 1c. ALOS AW3D30 (not downloaded)

- Source page: https://www.eorc.jaxa.jp/ALOS/en/dataset/aw3d30/aw3d30_e.htm (read: CONFIRMED).
- Resolution about 30 m (1 arc-second) (CONFIRMED from page). Height above sea level, vertical datum not stated on the page (CONFIRMED).
- Access: **registration required** (account on the AW3D30 homepage, email activation) (CONFIRMED from page). Not downloaded because no account was used.
- Licence: page says commercial and non-commercial use "free of charge" under the "Terms for Use" (CONFIRMED). Redistribution terms are on earth.jaxa.jp and were **not read** (UNCONFIRMED). No attribution wording given on the page (CONFIRMED).

### 1d. Pit analysis from the DEM (CONFIRMED from `dem_pit.py`, flood-fill at fixed thresholds)

| Threshold (connected to pit floor) | Area | N–S extent | E–W extent | Centroid (N, E) |
|---|---|---|---|---|
| < 400 m | 1.2 ha | 155 m | 148 m | N −94, E −6 |
| < 410 m | 2.7 ha | 216 m | 207 m | N −95, E −10 |
| < 420 m | 5.4 ha | 247 m | 296 m | N −69, E +11 |
| < 430 m | 7.0 ha | 278 m | 355 m | N −69, E +16 |
| < 440 m | not closed (floods the crop) | – | – | – |

- Pit floor (DEM minimum): **389.7 m** at N −87, E −1.
- Rim: the surrounding ground is 430–500 m; the 440 m contour is not closed, so there is no clean rim contour. Ground within 150 m of the mine point averages 417 m, within 300 m averages 431 m (CONFIRMED).
- Approximate pit depth in the DEM (rim about 440–460 m minus floor 390 m): **about 50–70 m** (UNCONFIRMED: DSM over water, spoil and walls; not a survey).
- Outline size: about **280 m × 355 m** at the 430 m level (UNCONFIRMED as a rim, CONFIRMED as a contour).
- Whether the DEM predates or postdates the end of mining: **predates**. The facts file (`team/research/sekisovskoye-facts.md` line 20) states the open pit was completed in 2016 (CONFIRMED there), and the DEM was acquired by TanDEM-X in about 2011–2015 (section 1a, UNCONFIRMED window). The DEM therefore shows the pit as it was during open-pit mining, not its final form.

**Change since about 2000 (SRTM vs DEM), CONFIRMED from `srtm_vs_dem.py`:**
- SRTM (Skadi) mine point 479 m vs Copernicus 411 m (difference −68 m). SRTM shows no pit at the site: 9 × 9 samples around the mine point range 445–485 m.
- DEM minus SRTM, averaged over the crop: +1.0 m; within 200 m of the mine point: mean −37.8 m, min −92.7 m.
- Area lowered by more than 20 m across the 4 km crop: **11.4 ha**.
- Caveat: SRTM heights are referenced to EGM96 and Copernicus to EGM2008; the difference between them in this area was **not** computed (UNCONFIRMED magnitude). Sampling of the two grids differs (bilinear resampling used).
- Difference map: `SCRATCH/srtm/dem_minus_srtm_map.png` (red = lower in DEM).

### 1e. Mine document elevations vs the DEM

Document values (from `team/research/sekisovskoye-facts.md`, CONFIRMED against the cited document pages):
- TU1 decline portal at **+430 m** (line 46, p.22/25/28 of D2).
- TU2 decline portal at **+320 m** (line 48).
- Ventilation shaft VS1 collar to **+325 m** (line 51; a "+320" conflict is noted in D2).
- Ventilation shaft VS2 (proposed) to +340 m (line 52; "335 m" conflict in D2).
- Also: the RNS of 2026 states "Decline No.1 advanced ... from **-34 masl** to -50 masl" (facts line 340, CONFIRMED against the RNS text). "masl" = metres above sea level.

Comparison:
- **+430 m (TU1 portal):** the DEM ground is 420–445 m at 100–300 m from the mine point (CONFIRMED). The +430 level is therefore inside the DEM surface range of the site, so the magnitude is consistent. The portal's own position is not given in the documents, so it cannot be matched to a DEM pixel (UNCONFIRMED).
- **+320 m (TU2 portal / "pit floor about +320 m"):** the DEM pit floor is **389.7 m**, about **70 m above** +320 m (CONFIRMED arithmetic). This is consistent with the DEM predating the final, deeper pit floor reached before 2016 (UNCONFIRMED interpretation). The model's +320 m floor should not be copied from the DEM.
- **Datum:** the documents say "masl" (CONFIRMED). The DEM is orthometric, EGM2008-based (UNCONFIRMED here). Kazakhstan's national height system (Baltic 1977 is commonly used) was **not** checked; the offset to the DEM is therefore UNCONFIRMED. The values are in the same range as DEM heights (about 390–550 m), so absolute heights are the likely reading, not a local datum with an arbitrary zero.

## 2. Imagery

### 2a. Sentinel-2 L2A scene selection (CONFIRMED from Earth Search query)

- STAC search: `https://earth-search.aws.element84.com/v1/search` (POST, collection `sentinel-2-l2a`, bbox 82.45–82.75 E, 50.22–50.45 N, Jul–Oct 2026, cloud < 15 %). Response saved as `SCRATCH/osm/s2_search.json`. No account needed.
- Tile covering the mine point: **MGRS 44UPA** (lat range 49.53–50.54 N, lon 82.38–83.96 E). Tile 44UPB starts at 50.43 N and does **not** cover the mine (CONFIRMED from footprints in `s2_search.json`).
- Selected scene: **S2C_44UPA_20260930_0_L2A**, acquired **2026-09-30T05:35:00Z**, cloud cover **0.0005 %** (CONFIRMED, item JSON `SCRATCH/s2/S2C_44UPA_20260930_0_L2A_item.json`, item URL https://earth-search.aws.element84.com/v1/collections/sentinel-2-l2a/items/S2C_44UPA_20260930_0_L2A).
- Alternatives on the same tile: S2A_44UPA_20260925_1_L2A (2.51 % cloud), S2B_44UPA_20260928_0_L2A (0.34 %), S2B_44UPA_20260925_0_L2A (2.77 %) (CONFIRMED from search).
- True-colour asset (TCI): https://sentinel-cogs.s3.us-west-2.amazonaws.com/sentinel-s2-l2a-cogs/44/U/PA/2026/9/S2C_44UPA_20260930_0_L2A/TCI.tif — HTTP 200 (CONFIRMED). Size **322,298,036 bytes** (CONFIRMED). Saved as `SCRATCH/s2/TCI_44UPA_20260930.tif`.
- Full tile: 10 980 × 10 980 px, uint8 RGB, **10 m**, EPSG:32644 (WGS 84 / UTM 44N), origin (600000, 5600040) (CONFIRMED from tags).
- Bucket: `sentinel-cogs`, us-west-2, no AWS account needed (CONFIRMED: https://registry.opendata.aws/sentinel-2-l2a-cogs/).

Crops (CONFIRMED from `s2_crop.py`):
- Crop = ±2000 m around the mine point, 400 × 400 px at native 10 m; cols 1164–1564, rows 2165–2565 of the tile; mine point at pixel (1364.0, 2364.8) (CONFIRMED).
- Files: `SCRATCH/s2/sekisovskoye_s2_tci_4km_600px.jpg` (600 × 600 px JPEG, upsampled from 400 px; 91,072 bytes); `..._600px_grid_overlay.jpg` (500 m grid + red mine-point cross, reference only, 110,688 bytes); `..._native400.png` (400 × 400, native); zoom `SCRATCH/s2/sekisovskoye_s2_zoom_1400m_700px.jpg` (±700 m, 700 px).
- Colour check: no zero/nodata pixels in the crop (CONFIRMED).

### 2b. What is visible (CONFIRMED by viewing the crops; offsets are estimates ±30 m)

- **Pit:** a pale-rimmed pit with a dark water-filled south-east part, centred about N −20 to −110, E −20 to +15 (zoom view). Roughly 350 m × 300 m across, consistent with the DEM outline.
- **Haul roads:** loops from the pit rim running north-east and east to the industrial zone; a road also runs south-east of the pit.
- **Settling/process pond:** a turquoise pond at about N +100 to +170, E +350 to +420 (zoom view).
- **Waste heaps:** light-coloured heaps north of the pit at about N +40 to +620, E −100 to +330 (zoom view and OSM heaps, section 3).
- **Industrial zone / plant:** pale industrial buildings and a dark green roof at about N +300 to +700, E +300 to +700. The plant footprint itself is not clear at 10 m; UNCONFIRMED as to which building is the plant.
- **Tailings facility:** large beige and pale-grey dam structures and a dark red-brown pond at about N +600 to +1800, E +300 to +1100 (4 km overlay). The red-brown pond is the most distinctive element at about N +1300 to +1550, E +500 to +960.
- **Village:** residential streets and roofs west and south-west of the pit, starting about E −400 m and extending to the crop edge (CONFIRMED visually). The OSM village node is at N −552, E −666.
- **Watercourses:** not clearly distinguishable in the 10 m crop south of the pit; the OSM positions in section 3 are used instead (UNCONFIRMED visually).
- Vegetation: dark green belts (trees) around the pit, mostly south and east.

### 2c. Landsat (open, lower resolution)

- Earth Search collection `landsat-c2-l2` (Landsat 8/9 Collection 2 Level-2, 30 m) returns scenes for the box (CONFIRMED, `SCRATCH/osm/landsat_c2l2_search.json`): e.g. LC09_L2SP_148025_20260928_02_T1 (cloud 0.02 %), LC09_L2SP_147025_20260921_02_T1 (1.1 %), LC08_L2SP_147025_20260929_02_T1 (0.01 %). Whether these footprints fully cover the mine point was **not** checked (UNCONFIRMED).
- Landsat is 30 m, so it adds nothing over Sentinel-2 at 10 m for this task.
- Note: `landsat-c2l2-sr` returned no matches (CONFIRMED); `landsat-c2-l2` was used instead.

### 2d. Higher-resolution open imagery

- No open source with resolution finer than 10 m was found in this session. Commercial very-high-resolution imagery (Maxar, Airbus Pléiades, Planet) and Google/Esri basemaps are not open for redistribution (UNCONFIRMED, from general knowledge; not checked against each licence).
- Copernicus Data Space catalogue API responded HTTP 200 (CONFIRMED, https://catalogue.dataspace.copernicus.eu/odata/v1/Products). It has the same Sentinel data; it was not used because the Earth Search COG was enough.

## 3. OpenStreetMap features (Overpass)

- Query: 4 km box, all elements (nodes, ways, relations), with tags and geometry.
  - Endpoint: https://overpass-api.de/api/interpreter (POST, raw body; the first attempt with form encoding returned 406).
  - Query text (saved as `SCRATCH/osm/all.ql`):
    ```
    [out:json][timeout:120];
    nwr(50.31073,82.5685,50.34663,82.6247);
    out meta geom;
    ```
  - Raw response: `SCRATCH/osm/overpass_all_bbox.json`, **3,133,484 bytes**, 6,056 elements, timestamp 2026-10-16T05:24:21Z (CONFIRMED). Note: `overpass.kumi.systems` returned 500 (CONFIRMED).
  - Feature list with offsets: `SCRATCH/osm/osm_features_offsets.txt` (664 rows). Tag summary: `SCRATCH/osm/osm_summary.txt`.
- Licence: **ODbL** (CONFIRMED that the OSM copyright page names the Open Database License; "1.0" appears only in the linked legal code, UNCONFIRMED on the page; https://www.openstreetmap.org/copyright). Attribution: "© OpenStreetMap contributors" is the usual notice (UNCONFIRMED: the page refers to the attribution guidelines and did not quote the string).

Features mapped (counts CONFIRMED from `osm_summary.txt`):
- **Buildings:** 377 detached, 78 generic, 15 industrial (`building=industrial`).
- **Roads:** 55 service, 33 residential, 27 track, 6 path, 5 primary, 1 secondary, 2 living_street, 2 footway.
- **Water:** 14 `natural=water`, 9 river segments, 6 stream segments.
- **Mining/industrial:** `landuse=quarry` ×2; `man_made=heap` ×3; `man_made=tailings_pond` ×5 (all also `natural=water`); `landuse=industrial` ×1; `man_made=bunker_silo` ×2.
- **Other:** `place=village` ×2 (one node named Секисовка; one residential polygon); `amenity` items (bus station, police post, cafe, pharmacy, fuel, parking, toilets); `landuse=cemetery`, `landuse=residential`; power lines and 8 poles.

Key polygons (centroid and extent from the mine point, CONFIRMED arithmetic from the Overpass geometry):
- **Pit (`landuse=quarry`, way 1327660021):** centroid N −53, E −2; extent N −196…+110, E −186…+171 m. Matches the DEM pit (section 1d).
- **Second quarry polygon (`landuse=quarry`, way 1327659994):** centroid N +236, E −38; extent N +126…+339, E −169…+96. Use is **UNCONFIRMED** (possibly a stockpile or ROM pad; it sits on the light area seen north of the pit in the zoom).
- **Heaps (`man_made=heap`):** way 1327659975 N +342…+616, E +314…+786; way 1327659997 N +409…+618, E −101…+78; way 1327659998 N +42…+225, E +153…+327.
- **Industrial landuse (way 517673087):** extent N −253…+1868, E −368…+1255 (broad, covers the plant and part of the tailings area).
- **Tailings ponds (`man_made=tailings_pond`):** 518394930 N +921…+1330, E +731…+1056; 518394931 N +669…+917, E +782…+981; 518394932 N +630…+891, E +305…+813; 518394934 N +889…+1341, E +376…+765; 518396236 N +1296…+1747, E +458…+1074.
- **Settling/process ponds (`natural=water`):** 1327660020 N +135…+173, E +352…+412; 1327660019 N +93…+135, E +352…+416; 1327659970 N +349…+388, E +436…+466; 1327660011 N +295…+323, E +740…+795; 1327660015 N +246…+289, E +918…+945.
- **Industrial buildings (15):** most lie west and south-west of the pit, about 1 km away (e.g. way 704758482 centroid N +190, E −1272; way 704758492 centroid N −276, E −724). Their use is UNCONFIRMED.
- **Village:** node 529885575 "Секисовка" (place=village), centroid N −552, E −666. Residential polygon way 42444554, extent N −1634…+2171, E −1364…+836 (very large; the village edge visible in imagery is around E −400 m).
- **Watercourses:**
  - Named river "Секисовка" (waterway=river): way 519403961 N −385…−377, E −155…−148 (short piece near the SW side of the box, about 190 m from the pit's south-west corner); way 519403962 N −3950…−346, E −148…+1386 (UNCONFIRMED which part is the river near the mine).
  - Unnamed streams (waterway=stream): 519955221 N −377…−260, E −155…+79; 519955222 N −270…−268, E +79…+91; 519955223 N −174…−168, E +314…+319; 519955224 N −168…+6, E +319…+397; 519955225 N −273…−174, E +91…+314. Way 519955221 lies about 60 m south of the pit's south edge and is the **most likely Volchevka** (UNCONFIRMED: OSM does not name it; the facts file gives a Volchevka distance of 60 m from the quarry south boundary, which matches).
- Power: power lines (way 547613030) and poles (8) to the south-west; not critical.

## 4. Licences for redistribution (committed to a public MIT repository)

General point: MIT covers only code. Data derivatives keep their own licences, so ship them with a separate `DATA-LICENSES` or `NOTICE` file that carries the exact notices below.

### 4a. Copernicus DEM GLO-30 (CONFIRMED licence text, read directly)

- Licence PDF: "Licence for Copernicus DEM instance COP-DEM-GLO-30-F Global 30m Full, Free & Open" (https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Data/DEM/resources/license/License-COPDEM-30.pdf).
- Art. 3: rights "worldwide and without limitation in time". Art. 4: reproduction, distribution, communication to the General Public, and **adaptation, modification and combination with other data**. Art. 5: free of charge.
- **Cropped heightmap in an MIT repo: allowed**, with the notices below.
- Notice for distribution, Art. 6(a): `© DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA; all rights reserved.`
- Notice for modified data, Art. 6(b): `produced using Copernicus WorldDEM-30 © DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA; all rights reserved`. **Use this one for the cropped heightmap**, because it is adapted.
- No-liability sentence, Art. 6(c): `The organisations in charge of the Copernicus programme by law or by delegation do not incur any liability for any use of the Copernicus WorldDEM-30.`
- Art. 6(d): do not imply endorsement by Airbus, the Licensor or Copernicus.
- Art. 6(e): anyone who redistributes must pass these obligations on to later users.

### 4b. Sentinel-2 L2A imagery

- Access: "free, full and open" (CONFIRMED: https://registry.opendata.aws/sentinel-2-l2a-cogs/). The legal notice PDF (https://sentinels.copernicus.eu/documents/247904/690755/Sentinel_Data_Legal_Notice) is password-protected and could not be read (CONFIRMED).
- Required credit for modified Sentinel data: **"Contains modified Copernicus Sentinel data 2026"** (UNCONFIRMED against the primary text; from secondary sources and an example in Wikimedia/OSM diary pages: https://api.openstreetmap.org/user/PlaneMad/diary/37816; the modified-data wording was seen in an EOX example, not in Copernicus' own text).
- A cropped, resampled JPEG may be committed to an MIT repo with that credit (UNCONFIRMED against the primary notice; the Copernicus terms are believed to allow this).
- The bucket citation given by AWS: "Sentinel-2 Cloud-Optimized GeoTIFFs was accessed on DATE from https://registry.opendata.aws/sentinel-2-l2a-cogs" (CONFIRMED on the AWS page).

### 4c. OpenStreetMap (ODbL)

- Licence: ODbL (CONFIRMED on https://www.openstreetmap.org/copyright). The page says: "If you alter or build upon our data, you may distribute the result only under the same license", and asks to "name and link directly to the license(s)" when distributing data (CONFIRMED).
- A rendered texture or a 3D scene built from OSM data is generally a "produced work" with attribution only (UNCONFIRMED: the page does not define produced works; check ODbL 1.0 §4.3 before publishing).
- **Committing an extracted OSM geometry or tag list (e.g. the 664-row feature list or GeoJSON) to the repo is a database extract under ODbL share-alike.** Keep such extracts out of the MIT repo, or publish them under ODbL.
- Attribution notice to show: "© OpenStreetMap contributors, ODbL 1.0 (https://www.openstreetmap.org/copyright)" (UNCONFIRMED exact string).

### 4d. SRTM via Skadi (Terrain Tiles)

- Source page: https://registry.opendata.aws/terrain-tiles/ (CONFIRMED). It links to https://github.com/tilezen/joerd/blob/master/docs/attribution.md, which was **not read**. Attribution wording and the NASA public-domain status are UNCONFIRMED.
- Before committing a derivative, read the joerd attribution file.

### 4e. ALOS AW3D30

- Free for commercial and non-commercial use under JAXA's "Terms for Use" (CONFIRMED on the JAXA page); redistribution terms not read (UNCONFIRMED). Registration required (CONFIRMED). Not used.

### 4f. Landsat C2 L2

- Not checked in this session. USGS Landsat data are generally public domain (UNCONFIRMED).

## 5. Approximate positions in the scene (estimates; no positions invented beyond what the data show)

Lat/lon are computed from the N/E offsets with the 111 320 m flat-earth factor (CONFIRMED arithmetic). Uncertainty is given per item.

| Feature | N (m) | E (m) | Lat, Lon | Source and uncertainty |
|---|---|---|---|---|
| Mine point (given) | 0 | 0 | 50.328658, 82.596614 | Screening document; UTM44N 613640.00, 5576392.36 |
| Pit floor (DEM minimum) | −87 | −1 | 50.327877, 82.596600 | DEM, CONFIRMED value; ±30 m |
| Pit centre (OSM quarry centroid) | −53 | −2 | 50.328182, 82.596586 | OSM way 1327660021; ±30 m |
| Pit centre (DEM 430 m contour centroid) | −69 | +16 | 50.328038, 82.596839 | DEM; ±40 m |
| Pit rim radius | ~150–180 | | | Half of OSM quarry extent (306 × 357 m); UNCONFIRMED as a rim (no closed DEM rim contour) |
| Pit south edge (OSM) | −196 | | | OSM way 1327660021; CONFIRMED vector |
| Plant (industrial zone) | +300…+700 | +300…+700 | ~50.3314…50.3350, 82.6008…82.6065 | Imagery + OSM landuse=industrial centroid N +634, E +448 (50.334354, 82.602918); plant footprint UNCONFIRMED |
| ROM pad | not identified | | | Candidate only: OSM quarry way 1327659994 (N +126…+339, E −169…+96); UNCONFIRMED |
| Tailings dams / ponds | +630…+1750 | +305…+1074 | centroid of 5 ponds N +1060, E +750 → 50.338180, 82.607168 | OSM tailings_pond polygons, CONFIRMED vector; the 1.3 km N / 0.8 km E estimate from the twin registry is consistent (not independently checked against a dam crest) |
| Red-brown tailings pond (imagery) | +1300…+1550 | +500…+960 | ~50.3403…50.3426, 82.6037…82.6101 | Visible in TCI (CONFIRMED visually, ±30 m) |
| Settling ponds | +93…+173 | +352…+416 | 50.329…50.330, 82.602…82.603 | OSM natural=water 1327660019/1327660020 (CONFIRMED vector); turquoise pond in imagery (CONFIRMED visually) |
| Portal area (TU1 +430 / TU2 +320) | not located | | | No coordinates in the documents; imagery shows roads entering the pit rim on the east side only; UNCONFIRMED |
| Village edge (nearest houses to pit) | about −400 | about −400 to −700 | ~50.3251…50.3224, 82.5910…82.5868 (N −400…−700, E −400…−700) | Imagery (CONFIRMED visually: houses from about E −400 m); OSM village place node at N −552, E −666 → 50.323700, 82.587242 |
| Sekisovka river (OSM, nearest piece) | −381 | −151 | 50.325236, 82.594489 | OSM way 519403961; about 190 m from the pit's SW corner; facts file says 150 m (UNCONFIRMED which matches) |
| Volchevka stream (candidate) | −260 to −377 | −155 to +79 | centroid 50.3258, 82.5961 | OSM stream way 519955221 (unnamed in OSM); about 60 m south of the pit edge; UNCONFIRMED identification |

## What is usable and what is not

Usable now:
- Copernicus DEM GLO-30 crop, 30 m, EPSG:4326 GeoTIFF/NumPy/CSV, licensed for a public MIT repo with the notice in 4a. Pit visible (floor 390 m); predates the 2016 end of mining.
- SRTM 1 arc-second crop (2000, pre-mining), useful as a before/after comparison, not as the current surface.
- Sentinel-2 10 m true-colour crop (2026-09-30), licence credit in 4b.
- OSM feature list with offsets and raw JSON, licensed ODbL; keep out of the MIT repo unless published under ODbL.

Not available or not verified:
- ALOS AW3D30 not downloaded (account needed); redistribution terms not read.
- Document-to-DEM elevation matching: the TU1 and TU2 portal coordinates are not in the documents, so +430 and +320 cannot be placed on the DEM.
- Vertical datum of the documents (Baltic 1977 vs EGM2008) not established; offset not computed.
- Exact DEM acquisition window (2010–2015 vs 2011–2015) and the EGM2008 reference: not confirmed from the Product Handbook.
- Sentinel-2 licence wording: primary legal notice unreadable (password-protected PDF).
- Plant, ROM pad, dam crests and portals not identifiable at 10 m; positions above are estimates.
- Landsat coverage over the mine point not checked; higher-resolution open imagery: none found.
- SRTM acquisition date and Skadi attribution text not confirmed against primary sources.
- OSM names for the Volchevka stream and the river segments near the pit were not found in OSM tags.
