#!/usr/bin/env python3
"""Offline builder of the terrain assets of the Sekisovskoye scene (spec 4.2).

This tool is NOT part of the build or of the runtime: nothing calls it, and the Stand and
the simulator only read its outputs. Run it again only when an input file or a pit design
parameter in params.json changes, then regenerate geometry.json.

Inputs (downloaded files; read as data only, nothing in them is executed):

  --dem  Copernicus DEM GLO-30 tile Copernicus_DSM_COG_10_N50_00_E082_00_DEM.tif
         https://copernicus-dem-30m.s3.eu-central-1.amazonaws.com/Copernicus_DSM_COG_10_N50_00_E082_00_DEM/Copernicus_DSM_COG_10_N50_00_E082_00_DEM.tif
  --tci  Sentinel-2 L2A true-colour COG of scene S2C_44UPA_20260930_0_L2A (10 m, UTM 44N)
         https://sentinel-cogs.s3.us-west-2.amazonaws.com/sentinel-s2-l2a-cogs/44/U/PA/2026/9/S2C_44UPA_20260930_0_L2A/TCI.tif
  --osm  Overpass API answer for the 4 km box, queried at https://overpass-api.de/api/interpreter with
         [out:json][timeout:120]; nwr(50.31073,82.5685,50.34663,82.6247); out meta geom;
  --pylib  optional directory holding imagecodecs (the DEM is deflate with the floating-point
         predictor) when it is not installed; it is put first on sys.path.

Third-party packages (this tool only): numpy, Pillow, tifffile, imagecodecs.

Outputs (--out, default team/model/terrain):

  heightmap.json  65 x 65 elevations over the 4 x 4 km square around the mine point (62.5 m
                  spacing) and a 25 x 25 inset over the old pit (15.625 m); metres, 0.1 m.
  texture.jpg     512 x 512 true-colour image of the same square, north up, JPEG quality 85.
  features.json   the OpenStreetMap features the scene uses, in scene coordinates and simplified,
                  the haul-road graph, and the carved pit (outline, floor, crests, ramp, section).

The map data of the stylised 3D surface (landscape.json, land cover, buildings, roads, waterways)
comes from the same OSM extract through the sibling tool build_landscape.py.

Steps:

  1. Frame (sekis/geometry.py): scene x = UTM 44N easting - 613640.00, z = 5576392.36 - northing.
     The origin is the mine point 50 deg 19'43.17" N, 82 deg 35'47.81" E. Grid north is the scene's
     north; true north lies 1.23 deg west of it.
  2. Elevation: each heightmap vertex is the mean of 5 x 5 bilinear DEM samples spread over its
     62.5 m cell (inverse UTM per sample; the tile is pixel-is-point). Inset vertices are single
     bilinear samples. The DEM is a 2011-2015 surface and predates the final pit (2016).
  3. Pit carving: inside the OSM quarry outline (way 1327660021) the ground is lowered to a shell:
     floor at pit.floor_m; wall at the overall slope of a stack of benches of pit.bench_height_m
     with faces at pit.face_angle_deg and berms of pit.berm_m (the line through the bench toes).
     The floor edge is the outline moved inwards by the distance at which the wall reaches the
     highest DEM point on the outline, so the wall meets the ground inside the outline everywhere.
     Carved ground = min(DEM, shell).
  4. Inset: whole heightmap cells around the pit; its border vertices are the linear interpolation
     of the coarse grid along the cell edges, so a mesh that swaps those cells for the inset has
     no cracks. Coarse vertices inside the pit are point samples of the carved ground.
  5. Texture: TCI pixels resampled bilinearly to 512 x 512 pixels whose outer edges are the
     square's edges (7.8125 m per pixel); baseline JPEG, quality 85, no metadata.
  6. Features: the OSM ways named in FEATURES, converted to the scene, clipped to the square,
     simplified (Douglas-Peucker, 2 m) and rounded to 0.1 m. Roads: the OSM service, track and
     residential ways inside ROAD_BOX as a graph (nodes, edges) that geometry.py routes on.
  7. Pit drawing data: the floor outline and the rim (where the wall meets the DEM) of the shell;
     crest lines at every bench elevation and the ramp (a spiral at pit.ramp_grade_deg from the
     floor centre to the rim, leaving towards RAMP_EXIT_TOWARDS, vertices 15 m apart at the exact
     grade) traced on the drawn ground, i.e. the triangulated grids as sekis/geometry.py reads
     them, so they lie on what the views render; the lowest ground of the pit per 10 m of x (its
     projection on the long section).

Rerun:

  python -I team/tools/build_terrain.py --dem <tile.tif> --tci <TCI.tif> --osm <overpass.json> [--pylib <dir>]
  cd team && python -m sekis.geometry

Licences and the notices to carry with the outputs: team/model/terrain/ATTRIBUTION.md.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

TEAM_DIR = Path(__file__).resolve().parent.parent
PARAMS_PATH = TEAM_DIR / "model" / "params.json"
DEFAULT_OUT = TEAM_DIR / "model" / "terrain"

HALF = 2000.0                             # the square is x, z in [-2000, 2000]
GRID_N = 65                               # vertices per side of the heightmap
GRID_STEP = 2 * HALF / (GRID_N - 1)       # 62.5 m
AVERAGE_SUB = 5                           # DEM samples per side for a vertex's cell mean
INSET_DIV = 4                             # inset spacing = GRID_STEP / 4 = 15.625 m
TEXTURE_PX = 512
TEXTURE_QUALITY = 85
SIMPLIFY_M = 2.0
SECTION_STEP = 10.0
RAY_COUNT = 180                           # directions for crest lines and the rim
RAMP_STEP_DEG = 1.0                       # angular step of the ramp spiral
RAMP_SPACING = 15.0                       # plan spacing of the kept ramp vertices (keeps the 0.1 m rounding small)
PIT_CENTRE = (0.0, 62.5)                  # a vertex of both grids, on the carved floor (checked)
RAMP_EXIT_TOWARDS = (700.0, -300.0)       # the plant side: the imagery shows the haul roads leaving NE

# OSM ways the scene uses (team/research/spatial-data.md section 3).
FEATURES = {
    "pit": 1327660021,                    # landuse=quarry: the old open pit
    "ponds": [1327660019, 1327660020],    # natural=water: the turquoise settling ponds
    "tailings": [518396236, 518394934, 518394930, 518394932, 518394931],   # man_made=tailings_pond
    "industrial": 517673087,              # landuse=industrial
    "heaps": [1327659975, 1327659997, 1327659998],                          # man_made=heap
    "quarry_north": 1327659994,           # landuse=quarry north of the pit (use not known)
    "stream": [519955224, 519955223, 519955225, 519955222, 519955221],      # waterway=stream, head to mouth
    "river": [519403962, 519403961, 518595559],                             # waterway=river Секисовка, in flow order
    "village": 529885575,                 # place=village Секисовка (node)
}
# building=yes cluster east of the heaps, under the blue and white roofs of the imagery:
# taken as the processing plant site (the mill building itself is not identifiable at 10 m).
PLANT_BUILDINGS = [
    1327660003, 1327660004, 1327660005, 1327660006, 1327660007, 1327660008, 1327660009, 1327660010,
    1327660012, 1327660013, 1327660014, 1327660016, 1327660017, 1327660018, 1327659986,
]
ROAD_HIGHWAYS = {"service", "track", "residential", "unclassified"}
ROAD_BOX = (-500.0, -1000.0, 1300.0, 400.0)  # x_min, z_min, x_max, z_max


# --------------------------------------------------------------------------
# Plain-Python geometry helpers
# --------------------------------------------------------------------------

def point_in_polygon(x, z, poly):
    inside = False
    for (x1, z1), (x2, z2) in zip(poly, poly[1:] + poly[:1]):
        if (z1 > z) != (z2 > z) and x < x1 + (z - z1) * (x2 - x1) / (z2 - z1):
            inside = not inside
    return inside


def polygon_area(poly):
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(poly, poly[1:] + poly[:1]))) / 2


def convex_hull(points):
    pts = sorted(set(map(tuple, points)))
    if len(pts) < 3:
        return [list(p) for p in pts]

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return [list(p) for p in lower[:-1] + upper[:-1]]


def _seg_dist(p, a, b):
    dx, dz = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dz * dz
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dz) / length2))
    return math.hypot(p[0] - a[0] - dx * t, p[1] - a[1] - dz * t)


def simplify(points, tolerance):
    """Douglas-Peucker on an open line [[x, z] or [x, y, z], ...] (plan distance)."""
    if len(points) < 3:
        return [list(p) for p in points]
    plan = [(p[0], p[-1]) for p in points]
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        i, j = stack.pop()
        best, index = -1.0, None
        for k in range(i + 1, j):
            d = _seg_dist(plan[k], plan[i], plan[j])
            if d > best:
                best, index = d, k
        if index is not None and best > tolerance:
            keep[index] = True
            stack += [(i, index), (index, j)]
    return [list(p) for p, k in zip(points, keep) if k]


def simplify_ring(points, tolerance):
    """Douglas-Peucker on a closed ring given without the repeated first vertex."""
    far = max(range(len(points)), key=lambda i: math.dist(points[0], points[i]))
    a = simplify(points[:far + 1], tolerance)
    b = simplify(points[far:] + [points[0]], tolerance)
    return a[:-1] + b[:-1]


def r1(v):
    """Round to 0.1; integral values become ints."""
    v = round(float(v), 1)
    return int(v) if v == int(v) else v


def rounded(points):
    return [[r1(c) for c in p] for p in points]


def inside_square(p):
    return abs(p[0]) <= HALF and abs(p[-1]) <= HALF


def clip_line(points):
    """Longest run of consecutive vertices inside the square."""
    runs, current = [], []
    for p in points:
        if inside_square(p):
            current.append(p)
        else:
            if current:
                runs.append(current)
            current = []
    if current:
        runs.append(current)
    return max(runs, key=len) if runs else []


# --------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------

def load_params():
    with open(PARAMS_PATH, "rb") as f:
        params = json.loads(f.read().decode("utf-8"))
    return {k: v["value"] for k, v in params.items() if isinstance(v, dict) and "value" in v}


class Dem:
    """Copernicus DEM tile: bilinear samples at (lat, lon)."""

    def __init__(self, path, np, tifffile):
        self.np = np
        with tifffile.TiffFile(path) as tif:
            page = tif.pages[0]
            tags = {t.code: t.value for t in page.tags.values()}
            self.data = page.asarray().astype(np.float64)
        scale, tie, keys = tags[33550], tags[33922], tags[34735]
        geokeys = {keys[i]: keys[i + 3] for i in range(4, len(keys), 4)}
        if geokeys.get(1025) != 2 or geokeys.get(2048) != 4326:
            raise SystemExit("DEM: expected EPSG:4326, RasterPixelIsPoint")
        self.dlon, self.dlat = scale[0], scale[1]
        self.lon0, self.lat0 = tie[3], tie[4]          # centre of pixel (0, 0)
        if not np.isfinite(self.data).all():
            raise SystemExit("DEM: non-finite values")

    def sample(self, lats, lons):
        np = self.np
        rows = (self.lat0 - np.asarray(lats, dtype=float)) / self.dlat
        cols = (np.asarray(lons, dtype=float) - self.lon0) / self.dlon
        r0, c0 = np.floor(rows).astype(int), np.floor(cols).astype(int)
        fr, fc = rows - r0, cols - c0
        d = self.data
        return ((d[r0, c0] * (1 - fc) + d[r0, c0 + 1] * fc) * (1 - fr)
                + (d[r0 + 1, c0] * (1 - fc) + d[r0 + 1, c0 + 1] * fc) * fr)

    def at_scene(self, geo, points):
        """DEM elevation at scene points [(x, z), ...]."""
        lat_lon = [geo.from_scene(x, z) for x, z in points]
        return self.sample([a for a, _ in lat_lon], [b for _, b in lat_lon])


def load_osm(path):
    with open(path, "rb") as f:
        data = json.loads(f.read().decode("utf-8"))
    ways, nodes = {}, {}
    for e in data["elements"]:
        if e["type"] == "way" and "geometry" in e:
            ways[e["id"]] = e
        elif e["type"] == "node":
            nodes[e["id"]] = e
    return data, ways, nodes


def way_points(geo, way):
    return [list(geo.to_scene(g["lat"], g["lon"])) for g in way["geometry"]]


def ring(geo, way):
    pts = way_points(geo, way)
    if pts[0] == pts[-1]:
        pts = pts[:-1]
    return pts


# --------------------------------------------------------------------------
# Pit shell
# --------------------------------------------------------------------------

class Shell:
    """Pit shell over the distance from the outline (metres).

    The wall is a stack of benches: faces of `bench` metres at `face_deg` and berms of `berm`
    metres. The carved ground follows the overall slope of that stack (the line through the
    bench toes); the benches are drawn as crest lines at their elevations.
    """

    def __init__(self, outline, floor, bench, face_deg, berm):
        self.outline = outline
        self.floor, self.bench, self.berm = floor, bench, berm
        self.face_run = bench / math.tan(math.radians(face_deg))
        self.period = self.face_run + berm
        self.tan = bench / self.period
        self.overall_deg = math.degrees(math.atan(self.tan))
        self.width = None                      # horizontal distance outline -> floor edge
        self.edges = [(a, (b[0] - a[0], b[1] - a[1])) for a, b in zip(outline, outline[1:] + outline[:1])]

    def inward(self, x, z):
        """Distance from the outline for a point inside it (0 outside)."""
        if not point_in_polygon(x, z, self.outline):
            return 0.0
        best = math.inf
        for (ax, az), (dx, dz) in self.edges:
            length2 = dx * dx + dz * dz
            t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((x - ax) * dx + (z - az) * dz) / length2))
            best = min(best, math.hypot(x - ax - dx * t, z - az - dz * t))
        return best

    def height_at(self, d):
        return self.floor + max(0.0, self.width - d) * self.tan

    def height(self, x, z):
        """Shell elevation at (x, z); +inf outside the outline."""
        d = self.inward(x, z)
        return math.inf if d <= 0 else self.height_at(d)

    def distance_for(self, y):
        """Inward distance of the shell contour at elevation y."""
        return self.width - (y - self.floor) / self.tan

    def ray_point(self, angle, target):
        """First point from PIT_CENTRE along `angle` whose inward distance falls to `target`."""
        cx, cz = PIT_CENTRE
        ux, uz = math.cos(angle), math.sin(angle)
        step, r = 2.0, 0.0
        while self.inward(cx + ux * (r + step), cz + uz * (r + step)) > target:
            r += step
            if r > 1000:
                raise ValueError("ray left the pit")
        lo, hi = r, r + step
        for _ in range(30):
            mid = (lo + hi) / 2
            if self.inward(cx + ux * mid, cz + uz * mid) > target:
                lo = mid
            else:
                hi = mid
        return cx + ux * lo, cz + uz * lo


# --------------------------------------------------------------------------
# Building blocks
# --------------------------------------------------------------------------

def cell_mean_grid(np, geo, dem, xs, zs):
    """Mean of AVERAGE_SUB x AVERAGE_SUB bilinear DEM samples over each vertex's cell."""
    offsets = [((k + 0.5) / AVERAGE_SUB - 0.5) * GRID_STEP for k in range(AVERAGE_SUB)]
    out = np.zeros((len(zs), len(xs)))
    for i, z in enumerate(zs):
        pts = [(x + ox, z + oz) for x in xs for oz in offsets for ox in offsets]
        values = dem.at_scene(geo, pts).reshape(len(xs), AVERAGE_SUB * AVERAGE_SUB)
        out[i] = values.mean(axis=1)
    return out


def point_grid(np, geo, dem, xs, zs):
    out = np.zeros((len(zs), len(xs)))
    for i, z in enumerate(zs):
        out[i] = dem.at_scene(geo, [(x, z) for x in xs])
    return out


def build_texture(np, Image, tifffile, path, out_path):
    with tifffile.TiffFile(path) as tif:
        page = tif.pages[0]
        tags = {t.code: t.value for t in page.tags.values()}
        scale, tie, keys = tags[33550], tags[33922], tags[34735]
        geokeys = {keys[i]: keys[i + 3] for i in range(4, len(keys), 4)}
        if geokeys.get(3072) != 32644 or geokeys.get(1025, 1) != 1:
            raise SystemExit("TCI: expected EPSG:32644, RasterPixelIsArea")
        image = page.asarray()
    px, east0, north0 = scale[0], tie[3], tie[4]       # top-left corner of pixel (0, 0)
    from sekis import geometry as geo
    step = 2 * HALF / TEXTURE_PX
    centres = -HALF + (np.arange(TEXTURE_PX) + 0.5) * step
    cols = (geo.E0 + centres - east0) / px - 0.5      # source pixel-centre coordinates
    rows = (north0 - (geo.N0 - centres)) / px - 0.5
    c0, r0 = int(math.floor(cols.min())) - 1, int(math.floor(rows.min())) - 1
    c1, r1_ = int(math.ceil(cols.max())) + 2, int(math.ceil(rows.max())) + 2
    window = image[r0:r1_, c0:c1].astype(np.float64)
    cc, rr = cols - c0, rows - r0
    ci, ri = np.floor(cc).astype(int), np.floor(rr).astype(int)
    fc, fr = cc - ci, rr - ri
    top = window[ri][:, ci] * (1 - fc)[None, :, None] + window[ri][:, ci + 1] * fc[None, :, None]
    bottom = window[ri + 1][:, ci] * (1 - fc)[None, :, None] + window[ri + 1][:, ci + 1] * fc[None, :, None]
    rgb = top * (1 - fr)[:, None, None] + bottom * fr[:, None, None]
    if (window.sum(axis=2) == 0).any():
        raise SystemExit("TCI: no-data pixels inside the square")
    out = Image.fromarray(np.clip(np.rint(rgb), 0, 255).astype(np.uint8), "RGB")
    out.save(out_path, "JPEG", quality=TEXTURE_QUALITY, optimize=True, progressive=False)
    return {"window": [int(r0), int(c0)], "pixel_m": px}


def road_graph(geo, ways):
    """OSM roads inside ROAD_BOX: nodes [[x, z]], edges [[i, j]], way IDs."""
    x0, z0, x1, z1 = ROAD_BOX
    index, nodes, edges, used = {}, [], set(), []
    for wid in sorted(ways):
        way = ways[wid]
        if way.get("tags", {}).get("highway") not in ROAD_HIGHWAYS:
            continue
        pts = way_points(geo, way)
        if not any(x0 <= x <= x1 and z0 <= z <= z1 for x, z in pts):
            continue
        used.append(wid)
        prev = None
        for nid, p in zip(way["nodes"], pts):
            if not (x0 - 200 <= p[0] <= x1 + 200 and z0 - 200 <= p[1] <= z1 + 200):
                prev = None
                continue
            if nid not in index:
                index[nid] = len(nodes)
                nodes.append(p)
            i = index[nid]
            if prev is not None and prev != i:
                edges.add((min(prev, i), max(prev, i)))
            prev = i
    # Drop vertices of degree 2 whose removal keeps the line within SIMPLIFY_M.
    adjacency = {i: set() for i in range(len(nodes))}
    for a, b in edges:
        adjacency[a].add(b)
        adjacency[b].add(a)
    changed = True
    while changed:
        changed = False
        for i in range(len(nodes)):
            nb = adjacency[i]
            if len(nb) == 2:
                a, b = sorted(nb)
                if b not in adjacency[a] and _seg_dist(nodes[i], nodes[a], nodes[b]) <= SIMPLIFY_M:
                    adjacency[a].discard(i)
                    adjacency[b].discard(i)
                    adjacency[a].add(b)
                    adjacency[b].add(a)
                    adjacency[i] = set()
                    changed = True
    keep = [i for i in range(len(nodes)) if adjacency[i]]
    renumber = {old: new for new, old in enumerate(keep)}
    out_edges = sorted({(min(renumber[a], renumber[b]), max(renumber[a], renumber[b]))
                        for a in keep for b in adjacency[a]})
    return {"nodes": rounded([nodes[i] for i in keep]), "edges": [list(e) for e in out_edges], "osm_ways": used}


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dem", required=True)
    parser.add_argument("--tci", required=True)
    parser.add_argument("--osm", required=True)
    parser.add_argument("--pylib")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args(argv)
    if args.pylib:
        sys.path.insert(0, args.pylib)
    if str(TEAM_DIR) not in sys.path:
        sys.path.append(str(TEAM_DIR))
    import numpy as np
    import tifffile
    from PIL import Image
    from sekis import geometry as geo

    p = load_params()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    dem = Dem(args.dem, np, tifffile)
    _, ways, nodes = load_osm(args.osm)

    # -- pit shell ---------------------------------------------------------
    outline = simplify_ring(ring(geo, ways[FEATURES["pit"]]), SIMPLIFY_M)
    shell = Shell(outline, float(p["pit.floor_m"]), float(p["pit.bench_height_m"]),
                  float(p["pit.face_angle_deg"]), float(p["pit.berm_m"]))
    rim_dem = dem.at_scene(geo, [tuple(q) for q in outline])
    rim_top = float(rim_dem.max())
    shell.width = (rim_top - shell.floor) / shell.tan
    if shell.inward(*PIT_CENTRE) < shell.width:
        raise SystemExit("PIT_CENTRE is not on the carved floor")

    def carved(x, z, ground):
        return min(ground, shell.height(x, z))

    # -- heightmap ---------------------------------------------------------
    xs = [-HALF + i * GRID_STEP for i in range(GRID_N)]
    coarse = cell_mean_grid(np, geo, dem, xs, xs)
    xs_o, zs_o = [q[0] for q in outline], [q[1] for q in outline]
    ci0 = int(math.floor((min(xs_o) + HALF) / GRID_STEP))
    ci1 = int(math.ceil((max(xs_o) + HALF) / GRID_STEP))
    cj0 = int(math.floor((min(zs_o) + HALF) / GRID_STEP))
    cj1 = int(math.ceil((max(zs_o) + HALF) / GRID_STEP))
    for j in range(GRID_N):
        for i in range(GRID_N):
            if ci0 <= i <= ci1 and cj0 <= j <= cj1:
                coarse[j, i] = carved(xs[i], xs[j], coarse[j, i])
    inset_step = GRID_STEP / INSET_DIV
    ixs = [xs[ci0] + k * inset_step for k in range((ci1 - ci0) * INSET_DIV + 1)]
    izs = [xs[cj0] + k * inset_step for k in range((cj1 - cj0) * INSET_DIV + 1)]
    fine = point_grid(np, geo, dem, ixs, izs)
    for j, z in enumerate(izs):
        for i, x in enumerate(ixs):
            fine[j, i] = carved(x, z, fine[j, i])
    # border: linear along the coarse cell edges
    nj, ni = len(izs), len(ixs)
    for j in range(nj):
        for i in range(ni):
            if 0 < i < ni - 1 and 0 < j < nj - 1:
                continue
            gi, gj = ci0 + i / INSET_DIV, cj0 + j / INSET_DIV
            i0, j0 = int(math.floor(gi)), int(math.floor(gj))
            fi, fj = gi - i0, gj - j0
            if fi == 0 and fj == 0:
                fine[j, i] = coarse[j0, i0]
            elif fj == 0:
                fine[j, i] = coarse[j0, i0] * (1 - fi) + coarse[j0, i0 + 1] * fi
            else:
                fine[j, i] = coarse[j0, i0] * (1 - fj) + coarse[j0 + 1, i0] * fj
    # coarse vertices inside the inset carry the inset's value there
    for j in range(cj0, cj1 + 1):
        for i in range(ci0, ci1 + 1):
            coarse[j, i] = fine[(j - cj0) * INSET_DIV, (i - ci0) * INSET_DIV]

    heightmap = {
        "about": "Ground elevation of the Sekisovskoye scene, metres above sea level (spec 4.2). Generated "
                 "by team/tools/build_terrain.py; see team/model/terrain/ATTRIBUTION.md for sources and "
                 "licences.",
        "frame": "x east, z south, metres; x = UTM 44N easting - 613640.00, z = 5576392.36 - northing",
        "layout": "rows[j][i] is the ground at x = origin[0] + i * spacing, z = origin[1] + j * spacing; row 0 "
                  "is the north edge, column 0 the west edge. Each cell is two triangles split along its "
                  "south-west to north-east diagonal (the vertex order of a three.js PlaneGeometry laid "
                  "on the ground).",
        "origin": [-HALF, -HALF], "spacing": GRID_STEP, "size": [GRID_N, GRID_N],
        "rows": [[r1(v) for v in row] for row in coarse],
        "inset": {
            "about": "Finer grid over the old pit. It covers whole cells of the main grid "
                     "(cells[0]..cells[2]-1 along x, cells[1]..cells[3]-1 along z); its border equals the main "
                     "grid's edges, so a mesh may replace those cells by the inset without cracks.",
            "origin": [ixs[0], izs[0]], "spacing": inset_step, "size": [ni, nj],
            "cells": [ci0, cj0, ci1, cj1],
            "rows": [[r1(v) for v in row] for row in fine],
        },
        "sources": {
            "dem": "Copernicus DEM GLO-30 (TanDEM-X, acquired 2011-2015), tile "
                   "Copernicus_DSM_COG_10_N50_00_E082_00_DEM; cell means of bilinear samples",
            "carved": "inside the OSM quarry outline (way 1327660021) the ground is the designed final pit, "
                      "carved by this tool from the documents: floor at the TU2 portal elevation, benched wall "
                      "at its overall slope",
        },
    }
    (out / "heightmap.json").write_bytes((json.dumps(heightmap, ensure_ascii=False, separators=(",", ":"))
                                          + "\n").encode("utf-8"))

    # -- texture -----------------------------------------------------------
    tex = build_texture(np, Image, tifffile, args.tci, out / "texture.jpg")

    # -- pit drawing data --------------------------------------------------
    centre = PIT_CENTRE

    def dem_at(x, z):
        return float(dem.at_scene(geo, [(x, z)])[0])

    angles = [2 * math.pi * k / RAY_COUNT for k in range(RAY_COUNT)]
    floor_ring = [shell.ray_point(a, shell.width) for a in angles]
    rim = []
    for a in angles:
        # walk outwards on the wall until it meets the DEM
        lo, hi = 0.0, shell.width
        for _ in range(40):
            mid = (lo + hi) / 2
            px, pz = shell.ray_point(a, shell.width - mid)
            if shell.height_at(shell.width - mid) < dem_at(px, pz):
                lo = mid
            else:
                hi = mid
        px, pz = shell.ray_point(a, shell.width - lo)
        rim.append([px, shell.height_at(shell.width - lo), pz])
    # Crest lines and the ramp lie on the drawn ground (the triangulated grids, as geometry.py reads them).
    drawn = geo.Terrain(heightmap)

    def drawn_ray(angle, y):
        """First point from the centre along `angle` where the drawn ground reaches y inside the outline."""
        ux, uz = math.cos(angle), math.sin(angle)
        bx, bz = shell.ray_point(angle, 0.01)
        r_max = math.hypot(bx - centre[0], bz - centre[1])
        r, step = 0.0, 1.0
        while r < r_max:
            if drawn.height(centre[0] + ux * (r + step), centre[1] + uz * (r + step)) >= y:
                lo, hi = r, r + step
                for _ in range(30):
                    mid = (lo + hi) / 2
                    if drawn.height(centre[0] + ux * mid, centre[1] + uz * mid) >= y:
                        hi = mid
                    else:
                        lo = mid
                if hi > r_max:
                    return None
                return centre[0] + ux * hi, centre[1] + uz * hi
            r += step
        return None

    benches = []
    y = shell.floor + shell.bench
    while y < rim_top:
        lines, current = [], []
        for a in angles + angles[:1]:
            q = drawn_ray(a, y)
            if q is not None and y <= dem_at(*q):
                current.append(list(q))
            else:
                if len(current) >= 2:
                    lines.append(current)
                current = []
        if len(current) >= 2:
            lines.append(current)
        if len(lines) > 1 and lines[0][0] == lines[-1][-1]:
            lines[0] = lines.pop()[:-1] + lines[0]      # join across the start angle
        lines = [rounded(simplify(line, 0.5)) for line in lines]
        if lines:
            benches.append({"y": r1(y), "lines": lines})
        y += shell.bench

    # Ramp: from the centre to the floor edge, then a spiral on the drawn wall at the ramp grade.
    grade = math.tan(math.radians(float(p["pit.ramp_grade_deg"])))
    exit_angle = math.atan2(RAMP_EXIT_TOWARDS[1] - centre[1], RAMP_EXIT_TOWARDS[0] - centre[0])

    def spiral(start):
        a, yv = start, shell.floor
        pts = [[centre[0], shell.floor, centre[1]]]
        px, pz = drawn_ray(a, shell.floor + 0.05)
        pts.append([px, shell.floor, pz])
        step = math.radians(RAMP_STEP_DEG)
        while True:
            a_next = a - step                           # counter-clockwise seen from above (z south)
            y_next, q = yv, None
            for _ in range(30):
                q = drawn_ray(a_next, y_next)
                if q is None:
                    break
                y_new = yv + math.hypot(q[0] - px, q[1] - pz) * grade
                if abs(y_new - y_next) < 1e-5:
                    break
                y_next = y_new
            if q is None or y_next > dem_at(*q):
                return pts, a_next                      # the wall has met the ground: the rim
            pts.append([q[0], y_next, q[1]])
            a, yv, (px, pz) = a_next, y_next, q

    start = exit_angle
    for _ in range(6):
        pts, end = spiral(start)
        turned = start - end
        start = exit_angle + turned
    ramp, end = spiral(start)
    kept = ramp[:2]
    for q in ramp[2:-1]:
        if math.dist((q[0], q[2]), (kept[-1][0], kept[-1][2])) >= RAMP_SPACING:
            kept.append(q)
    if math.dist((ramp[-1][0], ramp[-1][2]), (kept[-1][0], kept[-1][2])) < RAMP_SPACING / 2:
        kept.pop()
    ramp = kept + [ramp[-1]]
    for k in range(2, len(ramp)):                       # exact grade on the kept chords
        a, b = ramp[k - 1], ramp[k]
        b[1] = a[1] + math.hypot(b[0] - a[0], b[2] - a[2]) * grade

    # Lowest ground of the pit per 10 m of x (projection on the long section).
    section = []
    x = math.ceil(min(xs_o) / SECTION_STEP) * SECTION_STEP
    while x <= max(xs_o):
        zs = [z for z in np.arange(min(zs_o), max(zs_o) + 0.01, 2.0) if point_in_polygon(x, z, outline)]
        if zs:
            section.append([r1(x), r1(min(carved(x, z, dem_at(x, z)) for z in zs))])
        x += SECTION_STEP

    # -- other features ----------------------------------------------------
    def feature(wid):
        way = ways[wid]
        pts = rounded(simplify_ring(ring(geo, way), SIMPLIFY_M))
        return {"osm": wid, "outline": pts, "area": r1(polygon_area(pts))}

    def chain(ids):
        pts = []
        for wid in ids:
            part = way_points(geo, ways[wid])
            pts += part if not pts else part[1:]
        return pts

    stream = chain(FEATURES["stream"])
    river = clip_line(chain(FEATURES["river"]))
    mouth = river.index(stream[-1])                     # the confluence is a shared OSM node: keep it
    river_line = simplify(river[:mouth + 1], SIMPLIFY_M) + simplify(river[mouth:], SIMPLIFY_M)[1:]
    plant_pts = [q for wid in PLANT_BUILDINGS for q in ring(geo, ways[wid])]
    village = nodes[FEATURES["village"]]
    features = {
        "about": "OpenStreetMap features used by the Sekisovskoye scene, in scene coordinates (x east, z south, "
                 "metres from the mine point), simplified to 2 m and rounded to 0.1 m, and the carved final pit. "
                 "Generated by team/tools/build_terrain.py. Contains information from OpenStreetMap "
                 "(c) OpenStreetMap contributors, available under the Open Database License (ODbL) 1.0: "
                 "https://www.openstreetmap.org/copyright. See ATTRIBUTION.md.",
        "osm_timestamp": "2026-10-16T05:24:21Z",
        "pit": {
            "osm": FEATURES["pit"], "outline": rounded(outline), "area": r1(polygon_area(outline)),
            "centre": [r1(c) for c in centre], "floor": r1(shell.floor),
            "floor_outline": rounded(simplify_ring(floor_ring, 0.5)),
            "rim": rounded(simplify_ring(rim, 0.5)), "rim_dem_max": r1(rim_top),
            "wall_width": r1(shell.width), "overall_slope_deg": round(shell.overall_deg, 2),
            "bench_height": r1(shell.bench), "face_angle_deg": float(p["pit.face_angle_deg"]),
            "berm": r1(shell.berm), "benches": benches,
            "ramp": rounded(ramp), "ramp_grade_deg": float(p["pit.ramp_grade_deg"]),
            "section": section,
        },
        "ponds": [feature(w) for w in FEATURES["ponds"]],
        "tailings": [feature(w) for w in FEATURES["tailings"]],
        "industrial": feature(FEATURES["industrial"]),
        "heaps": [feature(w) for w in FEATURES["heaps"]],
        "quarry_north": feature(FEATURES["quarry_north"]),
        "plant_site": {"osm": PLANT_BUILDINGS, "outline": rounded(convex_hull(plant_pts))},
        "stream": {"osm": FEATURES["stream"], "points": rounded(simplify(stream, SIMPLIFY_M)),
                   "length": r1(sum(math.dist(a, b) for a, b in zip(stream, stream[1:])))},
        "river": {"osm": FEATURES["river"], "points": rounded(river_line)},
        "village": {"osm": FEATURES["village"], "at": [r1(c) for c in geo.to_scene(village["lat"], village["lon"])]},
        "roads": road_graph(geo, ways),
    }
    (out / "features.json").write_bytes((json.dumps(features, ensure_ascii=False, separators=(",", ":"))
                                         + "\n").encode("utf-8"))

    # -- report ------------------------------------------------------------
    print(f"heightmap {GRID_N} x {GRID_N} at {GRID_STEP} m: {coarse.min():.1f} .. {coarse.max():.1f} m; "
          f"inset {ni} x {nj} at {inset_step} m over cells {ci0}..{ci1} x {cj0}..{cj1}")
    print(f"pit: rim DEM max {rim_top:.1f} m, wall width {shell.width:.1f} m, overall slope "
          f"{shell.overall_deg:.1f} deg, floor {shell.floor} m, {len(benches)} bench levels, ramp "
          f"{len(ramp)} points to {ramp[-1][1]:.1f} m")
    print(f"texture window rows/cols from {tex['window']}, source pixel {tex['pixel_m']} m")
    print(f"stream length {features['stream']['length']} m; roads {len(features['roads']['nodes'])} nodes, "
          f"{len(features['roads']['edges'])} edges")
    for name in ("heightmap.json", "texture.jpg", "features.json"):
        print(f"{out / name}: {(out / name).stat().st_size} bytes")


if __name__ == "__main__":
    main()
