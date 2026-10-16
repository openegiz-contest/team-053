#!/usr/bin/env python3
"""Offline builder of the stylised landscape of the Sekisovskoye scene (spec 4.2).

This tool is NOT part of the build or of the runtime: nothing calls it, and the Stand only
serves its output (GET /terrain/landscape.json). Run it again only when the OpenStreetMap
extract changes. It is a sibling of build_terrain.py and reuses its geometry helpers.

Inputs (downloaded files; read as data only, nothing in them is executed):

  --osm    the Overpass API answer for the 4 km box (the same file as build_terrain.py --osm)
  --dem    optional: the Copernicus DEM GLO-30 tile (the same file as build_terrain.py --dem), used
           only for the rise of the waste heaps; without it every heap rises DEFAULT_HEAP_RISE
  --pylib  optional directory holding imagecodecs (needed to read the DEM tile)

Output (--out, default team/model/terrain):

  landscape.json  the OpenStreetMap features the stylised surface is drawn from, in scene
                  coordinates, simplified and quantised to 0.5 m: land-cover areas, building
                  footprints with their levels, roads with their class, waterways, walls and
                  fences. Only geometry, the OSM id and the tags the scene uses are kept (no
                  user, changeset, version or timestamp of any element).

Steps:

  1. Frame (sekis/geometry.py): scene x = UTM 44N easting - 613640.00, z = 5576392.36 - northing.
  2. Areas: closed ways with a land-cover tag (AREA_RULES, first match wins), clipped to the
     4 x 4 km square, simplified (Douglas-Peucker, AREA_SIMPLIFY_M) and quantised. The scene
     resolves overlaps by CLASS_ORDER (water over tailings over heap ... over residential);
     open land that no area covers is drawn as meadow.
  3. Heaps (man_made=heap): the drawn ground (the 62.5 m cell means of heightmap.json) smooths
     them out; `rise` is the 90th percentile of the 30 m DEM above the drawn ground inside the
     outline, sampled every HEAP_SAMPLE_M (at least MIN_HEAP_RISE), rounded to 0.5 m.
  4. Buildings: every building way wholly inside the square, simplified (BUILDING_SIMPLIFY_M)
     and quantised; `levels` is building:levels where it is tagged, else absent.
  5. Lines: highways (ROAD_CLASSES), waterways (river, stream; culverts dropped) and barriers
     (wall, fence), clipped to the square (every run inside it), simplified (LINE_SIMPLIFY_M)
     and quantised.

Rings are open (the first point is not repeated) and turn counter-clockwise in the (x, z)
plane (positive shoelace area). Every ring and line is a flat list x0, z0, x1, z1, ...

Rerun:

  python -I team/tools/build_landscape.py --osm <overpass.json> [--dem <tile.tif> --pylib <dir>]

Licences and the notices to carry with the output: team/model/terrain/ATTRIBUTION.md.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
TEAM_DIR = TOOLS_DIR.parent
DEFAULT_OUT = TEAM_DIR / "model" / "terrain"
HEIGHTMAP_PATH = DEFAULT_OUT / "heightmap.json"

HALF = 2000.0                  # the square is x, z in [-2000, 2000]
QUANTUM = 0.5                  # m: every coordinate is a multiple of this
AREA_SIMPLIFY_M = 1.5
BUILDING_SIMPLIFY_M = 0.4
LINE_SIMPLIFY_M = 1.5
MIN_BUILDING_AREA = 6.0        # m2: smaller footprints are mapping noise at this scale
HEAP_SAMPLE_M = 5.0
MIN_HEAP_RISE = 2.0
DEFAULT_HEAP_RISE = 4.0
PIT_WAY = 1327660021           # landuse=quarry of the old open pit (build_terrain.FEATURES["pit"])

# Land-cover class of a closed way: the first rule whose tags all match.
AREA_RULES = [
    ("tailings", {"man_made": "tailings_pond"}),
    ("water", {"natural": "water"}),
    ("heap", {"man_made": "heap"}),
    ("heap", {"man_made": "spoil_heap"}),
    ("heap", {"landuse": "landfill"}),
    ("quarry", {"landuse": "quarry"}),
    ("wood", {"natural": "wood"}),
    ("wood", {"landuse": "forest"}),
    ("scrub", {"natural": "scrub"}),
    ("farmland", {"landuse": "farmland"}),
    ("meadow", {"landuse": "meadow"}),
    ("meadow", {"landuse": "grass"}),
    ("meadow", {"natural": "grassland"}),
    ("bare", {"natural": "bare_rock"}),
    ("bare", {"natural": "sand"}),
    ("parking", {"amenity": "parking"}),
    ("cemetery", {"landuse": "cemetery"}),
    ("park", {"leisure": "park"}),
    ("industrial", {"landuse": "industrial"}),
    ("residential", {"landuse": "residential"}),
]
# Drawing order of the scene, the strongest first (documented here, applied in landscape.js).
CLASS_ORDER = ["water", "tailings", "heap", "pit", "quarry", "bare", "parking", "wood", "scrub", "park",
               "cemetery", "farmland", "meadow", "industrial", "residential"]
ROAD_CLASSES = {"primary", "secondary", "tertiary", "unclassified", "residential", "living_street", "service",
                "track", "path", "footway"}
WATERWAY_CLASSES = {"river", "stream"}
BARRIER_CLASSES = {"wall", "fence"}


def q(v):
    """Quantise to QUANTUM; integral values become ints."""
    v = round(float(v) / QUANTUM) * QUANTUM
    return int(v) if v == int(v) else v


def flat(points):
    out = []
    for p in points:
        out += [q(p[0]), q(p[1])]
    return out


def quantised(points, closed):
    """Quantise and drop repeated points (and a closing repeat of a ring)."""
    out = []
    for p in points:
        r = (q(p[0]), q(p[1]))
        if not out or r != out[-1]:
            out.append(r)
    if closed and len(out) > 1 and out[0] == out[-1]:
        out.pop()
    return [list(p) for p in out]


def signed_area(ring):
    return sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:] + ring[:1])) / 2


def ccw(ring):
    return ring if signed_area(ring) >= 0 else ring[::-1]


def clip_ring(ring):
    """Sutherland-Hodgman clip of a ring to the square."""
    out = ring
    for axis, sign in ((0, 1), (0, -1), (1, 1), (1, -1)):
        if not out:
            break
        src, out = out, []

        def inside(p):
            return sign * p[axis] <= HALF

        for i, cur in enumerate(src):
            prev = src[i - 1]
            if inside(cur):
                if not inside(prev):
                    out.append(cut(prev, cur, axis, sign * HALF))
                out.append(cur)
            elif inside(prev):
                out.append(cut(prev, cur, axis, sign * HALF))
    return out


def cut(a, b, axis, value):
    t = (value - a[axis]) / (b[axis] - a[axis])
    p = [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]
    p[axis] = value
    return p


def clip_runs(points):
    """Every run of a line inside the square, cut exactly at its edges (Liang-Barsky per segment)."""
    runs, current = [], []
    for a, b in zip(points, points[1:]):
        t0, t1 = 0.0, 1.0
        d = (b[0] - a[0], b[1] - a[1])
        ok = True
        for k in (0, 1):
            for p, qv in ((-d[k], a[k] + HALF), (d[k], HALF - a[k])):
                if p == 0:
                    if qv < 0:
                        ok = False
                else:
                    r = qv / p
                    if p < 0:
                        t0 = max(t0, r)
                    else:
                        t1 = min(t1, r)
        if not ok or t0 > t1:
            if len(current) > 1:
                runs.append(current)
            current = []
            continue
        start = [a[0] + d[0] * t0, a[1] + d[1] * t0]
        end = [a[0] + d[0] * t1, a[1] + d[1] * t1]
        if not current:
            current = [start]
        current.append(end)
        if t1 < 1.0:
            runs.append(current)
            current = []
    if len(current) > 1:
        runs.append(current)
    return runs


def area_class(tags):
    for name, rule in AREA_RULES:
        if all(tags.get(k) == v for k, v in rule.items()):
            return name
    return None


def heap_rise(np, dem, geo, terrain, ring, point_in_polygon):
    """90th percentile of the DEM above the drawn ground inside the ring (m)."""
    xs, zs = [p[0] for p in ring], [p[1] for p in ring]
    pts = []
    x = min(xs)
    while x <= max(xs):
        z = min(zs)
        while z <= max(zs):
            if point_in_polygon(x, z, ring):
                pts.append((x, z))
            z += HEAP_SAMPLE_M
        x += HEAP_SAMPLE_M
    if not pts:
        return MIN_HEAP_RISE
    rises = dem.at_scene(geo, pts) - np.array([terrain.height(x, z) for x, z in pts])
    return max(MIN_HEAP_RISE, round(float(np.percentile(rises, 90)) / QUANTUM) * QUANTUM)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--osm", required=True)
    parser.add_argument("--dem")
    parser.add_argument("--pylib")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args(argv)
    if args.pylib:
        sys.path.insert(0, args.pylib)
    for path in (str(TEAM_DIR), str(TOOLS_DIR)):
        if path not in sys.path:
            sys.path.append(path)
    import build_terrain as bt
    from sekis import geometry as geo

    _, ways, _ = bt.load_osm(args.osm)
    with open(args.osm, "rb") as f:
        stamp = json.loads(f.read().decode("utf-8"))["osm3s"]["timestamp_osm_base"]
    with open(HEIGHTMAP_PATH, "rb") as f:
        terrain = geo.Terrain(json.loads(f.read().decode("utf-8")))
    dem = np = None
    if args.dem:
        import numpy as np
        import tifffile
        dem = bt.Dem(args.dem, np, tifffile)

    areas, heaps, buildings, roads, waterways, barriers = [], [], [], [], [], []
    for wid in sorted(ways):
        way = ways[wid]
        tags = way.get("tags", {})
        closed = way["nodes"][0] == way["nodes"][-1] and len(way["nodes"]) > 3
        pts = bt.way_points(geo, way)
        if "building" in tags:
            if not closed or not all(bt.inside_square(p) for p in pts):
                continue
            ring = quantised(bt.simplify_ring(pts[:-1], BUILDING_SIMPLIFY_M), True)
            if len(ring) < 3 or abs(signed_area(ring)) < MIN_BUILDING_AREA:
                continue
            item = {"osm": wid, "building": tags["building"]}
            levels = tags.get("building:levels")
            if levels is not None:
                try:
                    item["levels"] = float(levels) if "." in levels else int(levels)
                except ValueError:
                    pass
            item["ring"] = flat(ccw(ring))
            buildings.append(item)
            continue
        cls = area_class(tags) if closed else None
        if cls == "quarry" and wid == PIT_WAY:
            cls = "pit"
        if cls:
            clipped = clip_ring(pts[:-1])
            if len(clipped) < 3:
                continue
            ring = quantised(bt.simplify_ring(clipped, AREA_SIMPLIFY_M), True)
            if len(ring) < 3 or abs(signed_area(ring)) < 1.0:
                continue
            ring = ccw(ring)
            if cls == "heap":
                rise = heap_rise(np, dem, geo, terrain, ring, bt.point_in_polygon) if dem else DEFAULT_HEAP_RISE
                heaps.append({"osm": wid, "rise": q(rise), "ring": flat(ring)})
            else:
                areas.append({"osm": wid, "class": cls, "ring": flat(ring)})
            continue
        kind, out, extra = None, None, {}
        if tags.get("highway") in ROAD_CLASSES:
            kind, out = tags["highway"], roads
            if "surface" in tags:
                extra["surface"] = tags["surface"]
        elif tags.get("waterway") in WATERWAY_CLASSES and tags.get("tunnel") != "culvert":
            kind, out = tags["waterway"], waterways
        elif tags.get("barrier") in BARRIER_CLASSES:
            kind, out = tags["barrier"], barriers
        if out is None:
            continue
        key = "highway" if out is roads else "waterway" if out is waterways else "barrier"
        for run in clip_runs(pts):
            line = quantised(bt.simplify(run, LINE_SIMPLIFY_M), False)
            if len(line) >= 2:
                out.append({"osm": wid, key: kind, **extra, "line": flat(line)})

    order = {name: k for k, name in enumerate(CLASS_ORDER)}
    areas.sort(key=lambda a: (order[a["class"]], a["osm"]))

    def length(items):
        total = 0.0
        for item in items:
            c = item["line"]
            total += sum(math.hypot(c[i + 2] - c[i], c[i + 3] - c[i + 1]) for i in range(0, len(c) - 2, 2))
        return round(total)

    doc = {
        "about": "OpenStreetMap features the stylised surface of the Sekisovskoye scene is drawn from, in scene "
                 "coordinates (x east, z south, metres from the mine point), simplified and quantised to 0.5 m. "
                 "Generated by team/tools/build_landscape.py. Contains information from OpenStreetMap "
                 "(c) OpenStreetMap contributors, available under the Open Database License (ODbL) 1.0: "
                 "https://www.openstreetmap.org/copyright. See ATTRIBUTION.md.",
        "osm_timestamp": stamp,
        "frame": "x = UTM 44N easting - 613640.00, z = 5576392.36 - northing (EPSG:32644)",
        "layout": "every ring and line is a flat list x0, z0, x1, z1, ... in metres, multiples of 0.5; rings are "
                  "open (the first point is not repeated) with a positive shoelace area in (x, z). areas: "
                  "land cover, class from the OSM tags, listed in drawing order (the first class wins where "
                  "areas overlap; open land under no area is meadow). heaps: man_made=heap, rise = metres the "
                  "30 m DEM stands above the drawn ground inside (90th percentile). buildings: building=* with "
                  "building:levels where tagged. roads: highway with surface where tagged. waterways: river and "
                  "stream, culverts left out. barriers: wall and fence.",
        "class_order": CLASS_ORDER,
        "areas": areas,
        "heaps": heaps,
        "buildings": buildings,
        "roads": roads,
        "waterways": waterways,
        "barriers": barriers,
        "counts": {
            "areas": len(areas), "heaps": len(heaps), "buildings": len(buildings),
            "roads": len(roads), "road_length_m": length(roads),
            "waterways": len(waterways), "waterway_length_m": length(waterways),
            "barriers": len(barriers), "barrier_length_m": length(barriers),
        },
    }
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "landscape.json"
    path.write_bytes((json.dumps(doc, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"))
    print(json.dumps(doc["counts"]))
    print(f"heaps: {[(h['osm'], h['rise']) for h in heaps]}")
    print(f"{path}: {path.stat().st_size} bytes")


if __name__ == "__main__":
    main()
