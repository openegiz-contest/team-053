# Terrain assets: sources, licences, notices

The files in this directory are built offline by `team/tools/build_terrain.py` and
`team/tools/build_landscape.py` from three open data sets.
The MIT licence of the repository covers the code only; these data files keep the licences below, and
anyone who passes them on must pass these notices on as well.

| File | What it is | Built from |
|---|---|---|
| `heightmap.json` | ground elevation, 65 × 65 vertices at 62.5 m over the 4 × 4 km square around the mine point, plus a 25 × 25 inset at 15.625 m over the old pit; metres above sea level | Copernicus DEM GLO-30; inside the pit outline: carved from the documents (see below) |
| `texture.jpg` | true-colour image of the same square, 512 × 512 pixels, north up | Sentinel-2C L2A scene S2C_44UPA_20260930_0_L2A, 30 September 2026 |
| `features.json` | the OpenStreetMap features the scene uses (pit, ponds, tailings cells, industrial zone, plant buildings, heaps, stream, river, village, roads) in scene coordinates, simplified to 2 m; the carved pit's floor, rim, bench crests, ramp and section | OpenStreetMap (Overpass API extract of 16 October 2026, 05:24 UTC); the pit design parameters in `params.json` |
| `landscape.json` | the OpenStreetMap features the stylised 3D surface is drawn from: land-cover areas (woods, water, tailings, heaps, quarries, cemetery, park, parking, industrial and residential land), 470 building footprints with `building:levels` where tagged, roads with their class and surface, rivers and streams, walls and fences; in scene coordinates, simplified (1.5 m, footprints 0.4 m) and quantised to 0.5 m; only the geometry, the OSM id and the tags the scene uses | OpenStreetMap (the same extract); the rise of each heap from Copernicus DEM GLO-30 |

`team/model/geometry.json` carries the same heightmap and positions read from these files; the same notices apply
to it.

## Which part is measured and which is carved

- **Measured (Copernicus DEM):** every elevation outside the OSM quarry outline of the old pit (way 1327660021).
  The DEM is a radar surface model from TanDEM-X acquisitions of about 2011–2015 (a surface model: it includes
  buildings, trees, heaps and the tailings as they were then). Each vertex of the main grid is the mean of
  25 bilinear samples over its 62.5 m cell; the inset vertices are single bilinear samples.
- **Carved from the documents:** inside the quarry outline. The DEM predates the end of open-pit mining (2016)
  and shows the pit floor at 389.7 m only. The tool lowers the ground there to the designed final pit: floor at
  +320 m (`pit.floor_m`: the TU2 portal elevation of the facts file, the portal being on the pit floor), wall at
  the overall slope of 15 m benches with 70° faces and 7 m berms (50.3°, `pit.bench_height_m`,
  `pit.face_angle_deg`, `pit.berm_m`), rising from the floor edge until it meets the DEM. Carved ground =
  min(DEM, designed shell). The bench crests are drawn as lines; the grid itself carries the overall slope.
- **Image:** the pixels are the Sentinel-2 true-colour product, resampled bilinearly from 10 m to 7.8125 m pixels
  whose edges are the edges of the square. The image shows the site on 30 September 2026; the dark south half of
  the pit is shadow of the south wall or water (not determined).
- **The stylised surface (default view):** the ground of the 3D scene is the measured and carved terrain above,
  coloured by the OpenStreetMap land cover of `landscape.json` (open land that no area covers is drawn as meadow:
  OpenStreetMap maps no fields or meadows here), with roads, waterways, buildings, trees, heaps, walls and fences
  drawn as models on it. What is drawn and what is assumed: building heights are `building:levels` x 3 m where
  tagged (389 of 470), else one storey (3 m) for small footprints, 6 m for footprints over 320 m2 and 7 m for
  `building=industrial`; gable roofs on footprints up to 320 m2; road widths by class; trees are placed by a seeded
  generator inside the mapped woods and along the waterways (not mapped trees); a heap is raised by `rise`, the
  90th percentile of the 30 m DEM above the drawn ground inside its outline, with 34 deg sides. The «Снимок»
  button of the scene shows the Sentinel-2 image instead.
- **Positions from OpenStreetMap:** outlines and lines of the pit, settling ponds, tailings cells, industrial
  zone, plant building cluster, heaps, the stream taken as the Volchevka, the Sekisovka river, the village node and
  the road graph. Which object of the twin is placed on which feature, and the objects that could not be
  identified, are stated in the `source` field of each object in `geometry.json`.

Frame: x = UTM 44N easting − 613640.00 m, z = 5576392.36 m − northing (EPSG:32644, WGS 84), origin at the mine
point 50°19'43.17" N, 82°35'47.81" E. Grid north is 1.23° east of true north here.

## Notices

### Copernicus DEM GLO-30 (`heightmap.json`, the terrain of `geometry.json`, the heap rise in `landscape.json`)

Licence: "Licence for Copernicus DEM instance COP-DEM-GLO-30-F Global 30m Full, Free & Open"
(https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Data/DEM/resources/license/License-COPDEM-30.pdf).
It allows worldwide reproduction, distribution and adaptation free of charge (Art. 3–5). The data here is
adapted, so the notice of Art. 6(b) applies:

> produced using Copernicus WorldDEM-30 © DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA; all rights reserved

> The organisations in charge of the Copernicus programme by law or by delegation do not incur any liability for any use of the Copernicus WorldDEM-30.

No endorsement by Airbus, the Licensor or Copernicus is implied (Art. 6(d)). Whoever redistributes this data must
pass these obligations on (Art. 6(e)). Tile used: `Copernicus_DSM_COG_10_N50_00_E082_00_DEM`.

### Sentinel-2 (`texture.jpg`)

Sentinel data are free, full and open. Credit for modified Sentinel data:

> Contains modified Copernicus Sentinel data 2026

Source: Sentinel-2 Cloud-Optimized GeoTIFFs, accessed on 16 October 2026 from
https://registry.opendata.aws/sentinel-2-l2a-cogs (scene S2C_44UPA_20260930_0_L2A, asset TCI). The exact wording of
the Copernicus Sentinel legal notice could not be read (the PDF is password-protected); the credit above is the
form in common use for modified Sentinel data.

### OpenStreetMap (`features.json`, `landscape.json`, positions in `geometry.json`)

> © OpenStreetMap contributors

The OpenStreetMap data is available under the Open Database License (ODbL) 1.0,
https://www.openstreetmap.org/copyright. `features.json` and `landscape.json` are derived databases of that data
and are made available under the ODbL 1.0 as well; the coordinates read from them into `geometry.json` and the drawn
scene are a produced work that carries the notice above. They keep no user, changeset, version or timestamp of any
element. The raw Overpass extract is not part of the repository.
