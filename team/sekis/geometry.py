"""Scene geometry of the Sekisovskoye twin (spec section 4.2).

Builds ``team/model/geometry.json`` from ``params.json``, ``registry.json`` and the
terrain assets in ``team/model/terrain/`` and gives the simulator the lookups it needs:
a point on a decline for a distance or an elevation, the passing bays, the route between
a stope and the ROM pad, the position of every thing that has one, and the ground
elevation anywhere in the scene.

Scene frame: x east, y up = elevation in metres above sea level, z south, 1 unit = 1 m.
The horizontal origin is the mine point 50 deg 19'43.17" N, 82 deg 35'47.81" E; x and z are
UTM zone 44N easting and southing from it (grid north). The surface is real: ground from the
Copernicus DEM with the final pit carved to the documents, positions of the pit, ponds,
tailings cells, plant site, water courses and roads from OpenStreetMap and Sentinel-2
imagery (team/model/terrain/, built offline by team/tools/build_terrain.py). Underground
elevations and cross-sections come from the model files; underground plan positions are
schematic (no mine plan is published) and live in the layout block below.

Run ``python -m sekis.geometry`` in ``team/`` to regenerate the file.
"""

from __future__ import annotations

import heapq
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

TEAM_DIR = Path(__file__).resolve().parent.parent
MODEL_DIR = TEAM_DIR / "model"
PARAMS_PATH = MODEL_DIR / "params.json"
REGISTRY_PATH = MODEL_DIR / "registry.json"
GEOMETRY_PATH = MODEL_DIR / "geometry.json"
TERRAIN_DIR = MODEL_DIR / "terrain"
HEIGHTMAP_PATH = TERRAIN_DIR / "heightmap.json"
FEATURES_PATH = TERRAIN_DIR / "features.json"
TEXTURE_FILE = "model/terrain/texture.jpg"          # paths in the document are relative to team/
HEIGHTMAP_FILE = "model/terrain/heightmap.json"
ATTRIBUTION_FILE = "model/terrain/ATTRIBUTION.md"

ATTRIBUTION = [
    "Elevation: produced using Copernicus WorldDEM-30 © DLR e.V. 2010-2014 and © Airbus Defence and Space "
    "GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA; all rights reserved.",
    "Image: contains modified Copernicus Sentinel data 2026 (Sentinel-2C, 30 September 2026).",
    "Map data: © OpenStreetMap contributors, available under the Open Database License (ODbL) 1.0, "
    "openstreetmap.org/copyright.",
]

# --------------------------------------------------------------------------
# Underground layout (spec 4.2), schematic. Plan pairs are (x, z) in the mine
# layout frame: origin on the ore zone under the centre of the old pit's floor,
# x along the strike, z across it (south). The strike runs east-west (grid
# azimuth 90 deg, about 91 deg true), along the long axis of the OSM pit outline
# (357 m east-west against 306 m north-south); no azimuth is published.
# LAYOUT_SHIFT places that frame in the scene: it is the centre of the carved
# pit floor (features.json pit.centre), where the TU2 portal stands, so the
# middle stope column lies under the pit centre and the outer ones run on along
# the strike beyond the rim at depth.
# Cross-section, north to south: shafts and raises (collars north of the pit,
# off the OSM roads, heaps and the northern quarry), the ventilation drive of the
# +320 m level under the pit's north wall, the ore zone, the level drives, the
# pump chambers, then the declines in the footwall, TU1 west and TU2 east.
# Every decline leg keeps the 8 deg slope and the 0.1 m horizontal runs of the
# earlier layout, so lengths and chainages are unchanged.
# --------------------------------------------------------------------------

LAYOUT_SHIFT = (0.0, 62.5)
STRIKE_AZIMUTH_DEG = 90              # grid azimuth of the strike (schematic)


def _lx(x):
    return x + LAYOUT_SHIFT[0]


def _lz(z):
    return z + LAYOUT_SHIFT[1]


ORE_X = (_lx(-300.0), _lx(300.0))   # ore zone along x
ORE_Z = _lz(0.0)                     # ... at this z; the long section is drawn in this plane
STOPE_X = tuple(_lx(x) for x in (-200.0, 0.0, 200.0))   # stope 1, 2, 3 of a level
DIP_DEG = 90                         # stopes are vertical tabular blocks (ore dips 70-90 deg, FACT A1)
DRIVE_Z = _lz(40.0)                  # level drive, south of the ore zone
# The +320 m ventilation level carries no stopes and joins the shafts: its drive runs
# north of the ore zone, under the pit's north wall (at least 35 m of rock above it);
# at DRIVE_Z it would cross the TU2 portal leg 6 m below the pit floor.
VENT_DRIVE_Z = _lz(-100.0)
DRIVE_WIDTH, DRIVE_HEIGHT = 4.0, 4.0
LEVEL_Z = (_lz(-30.0), _lz(150.0))   # z range of a level's workings (water plane, tint)

# Plan path of each decline's portal leg, (x, z) in the layout frame: the portal, any bends,
# then the first turn (the first multiple of 50 m below the portal). The leg falls at 8 deg
# along that path; from the first turn the zigzag runs east in the vertical plane of the
# first turn, turning every 50 m of depth: one leg runs 50 / tan 8 deg = 355.8 m.
# Every run is that of the earlier layout (portal legs 213.5 m and 142.3 m in plan), so the
# lengths and chainages do not change. TU1: the portal of the earlier layout (+430 m where
# the DEM ground is 431.1 m), 85.4 m west as before, then 128.1 m south into the footwall
# (the bend falls at +418 m). TU2: the portal on the pit floor centre, 142.3 m south under
# the pit's south wall.
# The planes also keep the volume of the -50 m and 0 m workings, from which the flood
# thresholds of params.json are derived (water.flood_threshold_*; test_vod checks them).
DECLINE_PLAN = {
    "decline-tu1": [(-288.8, -30.0), (-374.2, -30.0), (-374.2, 98.1)],
    "decline-tu2": [(0.0, 0.0), (0.0, 142.3)],
}
DECLINE_WIDTH = 4.5                  # 4.5 m x 4.0 m = the published 18 m2

# Airways stand where the level connections that cross the ore zone pass between the
# stope columns or beyond them, and where a vertical airway misses the stopes in the
# long section (stopes at x -253..-147, -53..53, 147..253).
AIRWAY_PLAN = {name: (_lx(x), _lz(z)) for name, (x, z) in {
    "shaft-vs1": (-172.3, -210.0),   # collar of the earlier layout, 111 m north of the pit
    "shaft-vs2": (135.0, -182.5),    # 43 m north of the pit, clear of the roads and the northern quarry
    "shaft-vs3": (-472.3, -210.0),   # collar of the earlier layout, west of the ore zone
    "raise-vpv": (-115.0, -190.0),   # between stope columns 1 and 2
    "raise-vhv-tu1": (-342.0, 68.0),  # 30 m north of the TU1 zigzag, west of the stopes
    "raise-vhv-tu2": (270.0, 110.0),  # 32 m north of the TU2 zigzag, east of the stopes
    "raise-vhv-exhaust": (320.0, 7.5),  # east of the ore zone, 149 m from the pit, off the roads
}.items()}
# Raises driven alongside a decline exist only as deep as that decline's levels.
RAISE_DECLINE = {"raise-vhv-tu1": "decline-tu1", "raise-vhv-tu2": "decline-tu2"}

PUMP_Z = _lz(70.0)                   # pump chambers, 30 m south of the drive
# between stope columns 2 and 3
PUMP_X = {name: _lx(x) for name, x in {"ps-p150": 100.0, "ps-m050": 100.0, "ps-m200": 112.0}.items()}
PUMP_CHAMBER = (20.0, 5.0, 10.0)
SUMP_DEPTH = 6.0
PIPE_SHAFT = "shaft-vs1"             # FACT A6: mine water leaves through the ventilation shaft

PORTAL_APRON = 30.0                  # the TU1 road leaves the portal eastwards

FAN_SURFACE = (10.0, 6.0, 8.0)
FAN_UNDERGROUND = (6.0, 4.0, 6.0)

# --------------------------------------------------------------------------
# Surface layout. Real positions come from features.json (OSM, imagery); the
# values here are the choices made where nothing is identifiable, and the
# mapping of registry things onto real features.
# --------------------------------------------------------------------------

# Settling ponds: the two OSM ponds by the pit; the higher one is the upper pond.
POND_LENGTH = 25.0                   # drawn box: documented area as 25 m x (area / 25 m)

# Not identifiable at 10 m: ROM pad and parking yard on flat free ground between the
# ponds and the plant, off every OSM road, heap, pond and quarry (team/tools search).
ROM_CENTER = (490.0, -250.0)
ROM_PAD = (100.0, 80.0)
ROM_CONE = (30.0, 22.0)              # radius, height at the starting tonnage
ROM_DUMP = (445.0, -215.0)
YARD_CENTER = (550.0, -70.0)
YARD_PITCH = 14.0
YARD_COLUMNS = 6
VEHICLE_SIZE = {                     # length, height, width: approximate overall size of each model
    "AD30": (10.2, 2.6, 2.7), "AD45": (11.2, 2.8, 3.0),
    "R1300": (8.7, 2.2, 2.1), "R1700": (10.6, 2.6, 2.7),
    "rig": (11.8, 2.2, 1.9),
}

# Plant lines: a row in the widest band of the OSM building cluster taken as the plant site.
PLANT_CENTER = (895.0, -380.0)
PLANT_LINE = (22.0, 16.0, 50.0)      # x, height, z of one line's box
PLANT_PITCH = 27.0

# Tailings: which OSM tailings_pond cell carries which dam number is not published. Dam 4,
# the active one, is put on the north cell with the open pond; dams 2 and 3 on the two
# middle cells. The two southern cells are drawn without a number.
TSF_CELLS = {"tsf-dam4": 518396236, "tsf-dam2": 518394934, "tsf-dam3": 518394930}
TSF_UNNUMBERED = {"tsf-cell-south": 518394932, "tsf-cell-southeast": 518394931}
# Planned cell 5 (measure X1): free farmland east of the facility, clear of the OSM roads.
# The farmland slopes about 17 m across any 0.3 km2 there; this is the flattest such site.
TSF_CELL5 = ("tsf-cell5", (1200.0, -1350.0, 1800.0, -850.0))   # x_min, z_min, x_max, z_max

DRAPE_STEP = 25.0                    # spacing of draped surface lines (m)
PROFILE_STEP = 10.0                  # spacing of the long-section ground line (m)

# Things whose drawn elevations, cross-section or bearing are published figures, or
# whose surface position is read from OSM or imagery.
SOURCED_KINDS = {"level", "decline", "settling_pond", "tailings_facility"}
SOURCED_THINGS = {
    "shaft-vs1", "shaft-vs2", "raise-vpv", "raise-vhv-tu1", "raise-vhv-tu2",
    "ps-p150", "ps-m200", "tsf-dam2", "tsf-dam3", "tsf-dam4",
}
# Kinds with no place in the scene.
ABSTRACT_KINDS = {"enterprise", "mine", "water_system", "scenario_control", "advisor"}

# Keys whose numbers are not rounded to 0.1 m.
EXACT_KEYS = {"section_m2", "slope_deg", "bearing_deg", "length_factor", "spacing",
              "density_t_m3", "overall_slope_deg", "grid_convergence_deg", "face_angle_deg"}

SCHEMA = {
    "purpose": "Scene geometry of the Sekisovskoye twin (spec 4.2). Generated by sekis/geometry.py from "
               "params.json, registry.json and model/terrain/; regenerate with `python -m sekis.geometry` in team/.",
    "frame": "x east, y up = elevation in metres above sea level, z south; 1 unit = 1 m on every axis. x and z are "
             "UTM 44N easting and southing from the mine point (frame.origin). Points are [x, y, z]; plan pairs "
             "are [x, z].",
    "numbers": "Coordinates and lengths are rounded to 0.1 m. section_m2, slope_deg, bearing_deg, length_factor, "
               "spacing, density_t_m3 and the *_deg slopes keep their own precision.",
    "terrain": "The ground. rows[j][i] is the elevation at x = origin[0] + i * spacing, z = origin[1] + j * "
               "spacing (row 0 north, column 0 west); each cell is two triangles split along its south-west to "
               "north-east diagonal (three.js PlaneGeometry vertex order). inset is a finer grid over the old pit "
               "that replaces the main-grid cells cells[0]..cells[2]-1 (x) by cells[1]..cells[3]-1 (z) without "
               "cracks. texture is a north-up image whose edges are extent. Show attribution with the scene.",
    "profile": "Ground elevation along the long section: points [x, y] every step metres of x at z.",
    "objects": "One entry per registry thing that has a place in the scene, keyed by thing ID, in registry "
               "order. Every entry has kind, primitive, sourced, planned and anchor (label and click point), "
               "then source (what the position and size rest on).",
    "scenery": "Drawable items that are not things: surface, old pit, haul roads, yard, water courses, village, "
               "industrial zone, unnumbered tailings cells, pipelines, backfilled blocks. Keyed by a local name; "
               "each has primitive, sourced and source.",
    "sourced": "Underground: true when the elevations, cross-section or bearing drawn are published figures; plan "
               "positions underground are schematic for every object (plan: schematic). Surface: true when the "
               "position is read from OpenStreetMap or the Sentinel-2 image (sizes may still come from the "
               "documents); false when the place was chosen because the object is not identifiable.",
    "planned": "true: the thing is in state planned in the registry (draw dashed). On a link or a decline "
               "node it marks a connection below the workings developed at the start. planned_below on an "
               "airway is the elevation under which the airway is design only.",
    "primitives": {
        "box": "center [x,y,z], size [dx,dy,dz], axis-aligned",
        "cylinder": "vertical; base [x,bottom,z], top (elevation), radius, section_m2",
        "pit": "the old open pit: outline [[x,z]] (OSM rim polygon), rim [[x,y,z]] (where the carved wall meets "
               "the DEM), floor (elevation) with floor_outline [[x,z]], base [x,floor,z] (floor centre), top "
               "(highest rim point), benches [{y, lines [[[x,z],...]]}] (crest lines at each bench elevation), "
               "section [[x,y]] (lowest ground per 10 m of x: the pit projected on the long section). The carved "
               "ground itself is in terrain.",
        "cone": "base [x,y,z], radius and height at reference_t tonnes",
        "prism": "footprint [[x,z],...] extruded from bottom to top (elevations)",
        "polyline": "points [[x,y,z],...]; width and height of the opening where it is a drive",
        "outline": "footprint [[x,z],...] at elevation y",
        "marker": "a point; the position is anchor",
    },
    "decline": "points run from the portal to the design bottom, every segment at slope_deg. bottom_elevation "
               "is the face at the start (the live value is the twin feature of the same name). nodes are the "
               "passing bays: the portal and every 25 m of elevation below it; chainage is metres along "
               "points from the portal; type is portal, bay, turn or access (a turn with a level access). "
               "Haul distance for travel times is chainage x length_factor.",
    "level": "points is the level drive. links leave the drive: role access (to a decline), crosscut (to a "
             "stope), airway (to a shaft or raise), chamber (to a pump station). extent is [x_min, z_min, "
             "x_max, z_max] of the level's workings.",
    "stope": "a vertical tabular block: size [strike_length, height, thickness] with height the 50 m floor, "
             "thickness stope.thickness_m and strike_length = tonnage_t / (density_t_m3 x height x thickness).",
    "mobile": "trucks, loaders and rigs carry mobile true; their box stands on its parking slot. Live "
              "positions are the twin features pos_x, pos_y, pos_z.",
    "surface": "Surface objects stand on the terrain: a box or prism bottom is the lowest ground under its "
               "footprint; markers, cones and line vertices are at the ground; a settling pond's water surface "
               "is the ground at its centre. A tailings prism's top is the level that holds the dam's capacity_m3 "
               "between the ground and the top. Shaft collars are at the ground of their position (the registry "
               "collar elevation is kept as documented_top).",
}


# --------------------------------------------------------------------------
# Frame: UTM zone 44N (WGS 84) shifted to the mine point
# --------------------------------------------------------------------------

LAT0 = 50 + 19 / 60 + 43.17 / 3600       # mine point of the environmental screening (D1)
LON0 = 82 + 35 / 60 + 47.81 / 3600
E0, N0 = 613640.00, 5576392.36           # its UTM 44N easting and northing: the scene origin
UTM_ZONE_LON0 = 81.0                     # central meridian of zone 44

_A, _F, _K0 = 6378137.0, 1 / 298.257223563, 0.9996
_N = _F / (2 - _F)
_AA = _A / (1 + _N) * (1 + _N ** 2 / 4 + _N ** 4 / 64)
_ALPHA = (_N / 2 - 2 * _N ** 2 / 3 + 5 * _N ** 3 / 16, 13 * _N ** 2 / 48 - 3 * _N ** 3 / 5, 61 * _N ** 3 / 240)
_BETA = (_N / 2 - 2 * _N ** 2 / 3 + 37 * _N ** 3 / 96, _N ** 2 / 48 + _N ** 3 / 15, 17 * _N ** 3 / 480)
_DELTA = (2 * _N - 2 * _N ** 2 / 3 - 2 * _N ** 3, 7 * _N ** 2 / 3 - 8 * _N ** 3 / 5, 56 * _N ** 3 / 15)
_E2 = 2 * math.sqrt(_N) / (1 + _N)


def utm_forward(lat, lon):
    """(lat, lon) in degrees -> (easting, northing) in UTM zone 44N (Krueger series, mm accuracy)."""
    phi, lam = math.radians(lat), math.radians(lon - UTM_ZONE_LON0)
    t = math.sinh(math.atanh(math.sin(phi)) - _E2 * math.atanh(_E2 * math.sin(phi)))
    xi, eta = math.atan2(t, math.cos(lam)), math.atanh(math.sin(lam) / math.sqrt(1 + t * t))
    e = eta + sum(a * math.cos(2 * j * xi) * math.sinh(2 * j * eta) for j, a in enumerate(_ALPHA, 1))
    n = xi + sum(a * math.sin(2 * j * xi) * math.cosh(2 * j * eta) for j, a in enumerate(_ALPHA, 1))
    return 500000.0 + _K0 * _AA * e, _K0 * _AA * n


def utm_inverse(easting, northing):
    """(easting, northing) in UTM zone 44N -> (lat, lon) in degrees."""
    xi, eta = northing / (_K0 * _AA), (easting - 500000.0) / (_K0 * _AA)
    xi1 = xi - sum(b * math.sin(2 * j * xi) * math.cosh(2 * j * eta) for j, b in enumerate(_BETA, 1))
    eta1 = eta - sum(b * math.cos(2 * j * xi) * math.sinh(2 * j * eta) for j, b in enumerate(_BETA, 1))
    chi = math.asin(math.sin(xi1) / math.cosh(eta1))
    phi = chi + sum(d * math.sin(2 * j * chi) for j, d in enumerate(_DELTA, 1))
    lam = math.atan2(math.sinh(eta1), math.cos(xi1))
    return math.degrees(phi), UTM_ZONE_LON0 + math.degrees(lam)


def to_scene(lat, lon):
    """(lat, lon) in degrees -> scene (x, z)."""
    e, n = utm_forward(lat, lon)
    return e - E0, N0 - n


def from_scene(x, z):
    """Scene (x, z) -> (lat, lon) in degrees."""
    return utm_inverse(E0 + x, N0 - z)


def grid_convergence_deg():
    """Angle by which true north lies west of the scene's (grid) north at the origin."""
    x1, z1 = to_scene(LAT0 + 0.01, LON0)
    x0, z0 = to_scene(LAT0, LON0)
    return math.degrees(math.atan2(-(x1 - x0), -(z1 - z0)))


# --------------------------------------------------------------------------
# Terrain
# --------------------------------------------------------------------------

class _Grid:
    def __init__(self, grid):
        self.x0, self.z0 = (float(c) for c in grid["origin"])
        self.step = float(grid["spacing"])
        self.nx, self.nz = grid["size"]
        self.rows = grid["rows"]
        self.x1 = self.x0 + (self.nx - 1) * self.step
        self.z1 = self.z0 + (self.nz - 1) * self.step

    def contains(self, x, z):
        return self.x0 <= x <= self.x1 and self.z0 <= z <= self.z1

    def height(self, x, z):
        gx = min(max((x - self.x0) / self.step, 0.0), self.nx - 1.0)
        gz = min(max((z - self.z0) / self.step, 0.0), self.nz - 1.0)
        i, j = min(int(gx), self.nx - 2), min(int(gz), self.nz - 2)
        u, v = gx - i, gz - j
        a, b = self.rows[j][i], self.rows[j][i + 1]           # north-west, north-east
        c, d = self.rows[j + 1][i], self.rows[j + 1][i + 1]   # south-west, south-east
        if u + v <= 1.0:
            return a + (b - a) * u + (c - a) * v
        return d + (c - d) * (1.0 - u) + (b - d) * (1.0 - v)


class Terrain:
    """Ground elevation from a heightmap document (heightmap.json or geometry.json terrain):
    the inset where it covers the point, the main grid elsewhere, both triangulated along the
    south-west to north-east diagonal of each cell. Outside the extent the edge value is used."""

    def __init__(self, heightmap):
        self.main = _Grid(heightmap)
        self.inset = _Grid(heightmap["inset"]) if heightmap.get("inset") else None
        self.extent = [self.main.x0, self.main.z0, self.main.x1, self.main.z1]

    def height(self, x, z):
        if self.inset is not None and self.inset.contains(x, z):
            return self.inset.height(x, z)
        return self.main.height(x, z)

    def range(self):
        values = [v for row in self.main.rows for v in row]
        if self.inset is not None:
            values += [v for row in self.inset.rows for v in row]
        return min(values), max(values)


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

def _read_json(path):
    with open(path, "rb") as f:
        return json.loads(f.read().decode("utf-8"))


def _short(thing_id):
    """'kz.sekis:lvl-p150' -> 'lvl-p150'."""
    return thing_id.split(":", 1)[1] if ":" in thing_id else thing_id


def _state(thing):
    feature = thing.get("features", {}).get("state")
    return feature["properties"]["value"] if feature else None


def _num(value):
    """Round to 0.1; integral values become ints so the file stays compact."""
    rounded = round(float(value), 1)
    if rounded == int(rounded):
        return int(rounded)
    return rounded


def _normalise(value, key=None):
    """Recursively round every number that is not listed in EXACT_KEYS."""
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return value if key in EXACT_KEYS else _num(value)
    if isinstance(value, dict):
        return {k: _normalise(v, k) for k, v in value.items()}
    return [_normalise(v, key) for v in value]


def _rounded(points):
    return [[_num(c) for c in p] for p in points]


def _rect(cx, cz, dx, dz):
    """Footprint of an axis-aligned rectangle, counter-clockwise seen from above."""
    return [[cx - dx / 2, cz - dz / 2], [cx + dx / 2, cz - dz / 2],
            [cx + dx / 2, cz + dz / 2], [cx - dx / 2, cz + dz / 2]]


def _dedupe(points):
    out = []
    for p in points:
        p = [float(c) for c in p]
        if not out or out[-1] != p:
            out.append(p)
    return out


def point_in_polygon(x, z, poly):
    """True when (x, z) lies inside the polygon [[x, z], ...] (even-odd rule)."""
    inside = False
    for (x1, z1), (x2, z2) in zip(poly, poly[1:] + poly[:1]):
        if (z1 > z) != (z2 > z) and x < x1 + (z - z1) * (x2 - x1) / (z2 - z1):
            inside = not inside
    return inside


def polygon_area(poly):
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(poly, poly[1:] + poly[:1]))) / 2


def polygon_centroid(poly):
    a = cx = cz = 0.0
    for (x1, z1), (x2, z2) in zip(poly, poly[1:] + poly[:1]):
        cross = x1 * z2 - x2 * z1
        a += cross
        cx += (x1 + x2) * cross
        cz += (z1 + z2) * cross
    return [cx / (3 * a), cz / (3 * a)]


def convex_hull(points):
    pts = sorted(set(tuple(p) for p in points))

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


def footprint_samples(terrain, footprint, step=10.0):
    """Ground on a `step` grid inside a footprint (the grid starts at its minimum x and z)."""
    xs, zs = [p[0] for p in footprint], [p[1] for p in footprint]
    out, x = [], min(xs)
    while x <= max(xs):
        z = min(zs)
        while z <= max(zs):
            if point_in_polygon(x, z, footprint):
                out.append(_num(terrain.height(_num(x), _num(z))))
            z += step
        x += step
    return out


def plan_distance_to_polygon(x, z, poly):
    """Distance in plan from (x, z) to the polygon's boundary."""
    best = math.inf
    for a, b in zip(poly, poly[1:] + poly[:1]):
        dx, dz = b[0] - a[0], b[1] - a[1]
        length2 = dx * dx + dz * dz
        t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((x - a[0]) * dx + (z - a[1]) * dz) / length2))
        best = min(best, math.hypot(x - a[0] - dx * t, z - a[1] - dz * t))
    return best


def polyline_length(points):
    """Length of a polyline given as [[x, y, z], ...]."""
    return sum(math.dist(a, b) for a, b in zip(points, points[1:]))


def polyline_point(points, distance):
    """Point at `distance` metres along a polyline; clamped to its ends."""
    if distance <= 0:
        return tuple(float(c) for c in points[0])
    for a, b in zip(points, points[1:]):
        seg = math.dist(a, b)
        if distance < seg - 1e-9:
            t = distance / seg
            return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))
        if distance <= seg + 1e-9:          # a vertex: return it exactly
            return tuple(float(c) for c in b)
        distance -= seg
    return tuple(float(c) for c in points[-1])


def _point_at_elevation(points, elevation):
    """Point of a polyline that falls monotonically, at the given elevation."""
    for a, b in zip(points, points[1:]):
        if a[1] >= elevation >= b[1] and a[1] != b[1]:
            if elevation in (a[1], b[1]):   # a vertex: return it exactly
                return [float(c) for c in (a if elevation == a[1] else b)]
            t = (a[1] - elevation) / (a[1] - b[1])
            return [a[i] + (b[i] - a[i]) * t for i in range(3)]
    raise ValueError(f"elevation {elevation} is outside the polyline")


def _chainage_at_elevation(points, elevation):
    run = 0.0
    for a, b in zip(points, points[1:]):
        if a[1] >= elevation >= b[1] and a[1] != b[1]:
            return run + math.dist(a, b) * (a[1] - elevation) / (a[1] - b[1])
        run += math.dist(a, b)
    raise ValueError(f"elevation {elevation} is outside the polyline")


def _dms(text):
    """'50°19'43" N, 82°35'48" E' -> (latitude, longitude) in degrees."""
    parts = re.findall(r"(\d+)\D+(\d+)\D+(\d+)\D*?([NSEW])", text)
    if len(parts) != 2:
        raise ValueError(f"cannot read coordinates: {text!r}")
    out = {}
    for deg, minute, sec, hemi in parts:
        value = int(deg) + int(minute) / 60 + int(sec) / 3600
        out["lat" if hemi in "NS" else "lon"] = -value if hemi in "SW" else value
    return out["lat"], out["lon"]


# --------------------------------------------------------------------------
# Builder
# --------------------------------------------------------------------------

SCHEMATIC_PLAN = "plan position schematic (no mine plan is published)"


class _Builder:
    def __init__(self, params, registry, heightmap, features):
        self.p = {k: v["value"] for k, v in params.items() if isinstance(v, dict) and "value" in v}
        self.ns = registry["namespace"]
        self.things = {_short(t["thingId"]): t for t in registry["things"]}
        self.order = list(self.things)
        self.built = {}
        self.scenery = {}
        self.heightmap = heightmap
        self.terrain = Terrain(heightmap)
        self.features = features
        self.pit_outline = features["pit"]["outline"]

    # -- registry access ---------------------------------------------------

    def attr(self, name, key, default=None):
        return self.things[name]["attributes"].get(key, default)

    def kind(self, name):
        return self.attr(name, "kind")

    def of_kind(self, *kinds):
        return [n for n in self.order if self.kind(n) in kinds]

    def planned(self, name):
        return _state(self.things[name]) == "planned"

    def tid(self, name):
        return f"{self.ns}:{name}"

    def links(self, name, key):
        value = self.attr(name, key)
        if value is None:
            return []
        return [_short(v) for v in (value if isinstance(value, list) else [value])]

    def head(self, name, primitive, anchor, source):
        sourced = self.kind(name) in SOURCED_KINDS or name in SOURCED_THINGS
        return {"kind": self.kind(name), "primitive": primitive, "sourced": sourced,
                "planned": self.planned(name), "anchor": list(anchor), "source": source}

    # -- ground ------------------------------------------------------------

    def ground(self, x, z):
        """Ground at a point rounded to 0.1 m in plan, itself rounded to 0.1 m."""
        return _num(self.terrain.height(_num(x), _num(z)))

    def at_ground(self, x, z):
        return [_num(x), self.ground(x, z), _num(z)]

    def lowest_ground(self, footprint, step=10.0):
        """Lowest ground under a footprint: its vertices and an inner grid."""
        return min([self.ground(x, z) for x, z in footprint] + footprint_samples(self.terrain, footprint, step))

    def crest(self, footprint, volume):
        """Level whose volume above the ground inside the footprint is `volume` (m3)."""
        samples = footprint_samples(self.terrain, footprint)
        cell = polygon_area(footprint) / len(samples)
        lo, hi = min(samples), max(samples) + volume / polygon_area(footprint)
        for _ in range(60):
            mid = (lo + hi) / 2
            if sum(max(0.0, mid - g) for g in samples) * cell < volume:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2

    def drape(self, plan, step=DRAPE_STEP):
        """Plan line [[x, z], ...] -> points on the ground, at most `step` metres apart."""
        out = []
        for a, b in zip(plan, plan[1:]):
            n = max(1, math.ceil(math.dist(a, b) / step))
            for k in range(n):
                t = k / n
                out.append(self.at_ground(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
        out.append(self.at_ground(*plan[-1]))
        return _dedupe(out)

    def route(self, start, end):
        """Plan path [[x, z], ...] from start to end along the OSM roads (shortest in plan),
        joined to the nearest road node at both ends. Nodes inside the pit outline are not used."""
        roads = self.features["roads"]
        nodes = roads["nodes"]
        usable = [not point_in_polygon(x, z, self.pit_outline) for x, z in nodes]
        adjacency = {}
        for a, b in roads["edges"]:
            if usable[a] and usable[b]:
                w = math.dist(nodes[a], nodes[b])
                adjacency.setdefault(a, []).append((b, w))
                adjacency.setdefault(b, []).append((a, w))

        def nearest(p):
            return min(adjacency, key=lambda i: (math.dist(nodes[i], p), i))

        s, t = nearest(start), nearest(end)
        dist, back, queue = {s: 0.0}, {}, [(0.0, s)]
        while queue:
            d, i = heapq.heappop(queue)
            if i == t:
                break
            if d > dist[i]:
                continue
            for j, w in adjacency[i]:
                if d + w < dist.get(j, math.inf):
                    dist[j], back[j] = d + w, i
                    heapq.heappush(queue, (d + w, j))
        if t not in dist:
            raise ValueError(f"no road from {start} to {end}")
        path = [t]
        while path[-1] != s:
            path.append(back[path[-1]])
        return [list(start)] + [list(nodes[i]) for i in reversed(path)] + [list(end)]

    # -- declines ----------------------------------------------------------

    def decline_frame(self):
        self.floor = float(self.p["level.floor_height_m"])
        self.slope = float(self.p["decline.slope_deg"])
        self.run = self.floor / math.tan(math.radians(self.slope))
        self.levels = {n: float(self.attr(n, "elevation_m")) for n in self.of_kind("level")}
        self.developed_bottom = min(e for n, e in self.levels.items() if not self.planned(n))
        self.decline_pts, self.decline_bottom = {}, {}
        for name in self.of_kind("decline"):
            token = name.rsplit("-", 1)[1]
            portal = float(self.p[f"decline.{token}.portal_m"])
            design = float(self.p[f"decline.{token}.design_bottom_m"])
            if (portal, design) != (float(self.attr(name, "portal_elevation_m")),
                                    float(self.attr(name, "design_bottom_m"))):
                raise ValueError(f"{name}: params.json and registry.json disagree on its elevations")
            path = [(_lx(x), _lz(z)) for x, z in DECLINE_PLAN[name]]
            first = math.floor(portal / self.floor) * self.floor
            if first == portal:
                first -= self.floor
            tan = math.tan(math.radians(self.slope))
            # The portal leg keeps the horizontal run of the earlier layout, rounded to 0.1 m.
            runs = [math.dist(a, b) for a, b in zip(path, path[1:])]
            if abs(sum(runs) - _num((portal - first) / tan)) > 1e-6:
                raise ValueError(f"{name}: the portal leg is not {_num((portal - first) / tan)} m long in plan")
            points, done = [], 0.0
            for (x, z), run in zip(path[:-1], [0.0] + runs[:-1]):   # the first turn follows below
                done += run
                points.append([x, portal - (portal - first) * done / sum(runs), z])
            tx, tz = path[-1]
            y, side = first, 0
            while y > design:
                points.append([tx + side * self.run, y, tz])
                y, side = y - self.floor, 1 - side
            last = points[-1]
            x_end = last[0] + (1 if side else -1) * (last[1] - design) / tan
            points.append([x_end, design, tz])
            self.decline_pts[name] = _rounded(points)
            self.decline_bottom[name] = float(self.p[f"decline.{token}.bottom_m"])
        self.surface_y = max(p[0][1] for p in self.decline_pts.values())
        pit = self.features["pit"]
        portal = self.decline_pts["decline-tu2"][0]
        if [portal[0], portal[2]] != pit["centre"] or portal[1] != pit["floor"]:
            raise ValueError(f"the TU2 portal {portal} is not on the pit floor centre {pit['centre']}: "
                             "LAYOUT_SHIFT and features.json disagree")

    def accesses(self, level):
        """Declines that meet a level: [(decline, point, planned)]."""
        e, out = self.levels[level], []
        for name, pts in self.decline_pts.items():
            linked = name in self.links(level, "link_declines")
            at_turn = any(p[1] == e for p in pts[1:])
            if not pts[-1][1] <= e < pts[0][1] or not (linked or at_turn):
                continue
            # A turn that the registry does not link to the level is the decline's design extension.
            planned = self.planned(level) or e < self.decline_bottom[name] or not linked
            out.append((name, _point_at_elevation(pts, e), planned))
        return out

    def build_declines(self):
        bay = float(self.p["decline.bay_spacing_vm"])
        for name, pts in self.decline_pts.items():
            portal, design, bottom = pts[0][1], pts[-1][1], self.decline_bottom[name]
            access = {}
            for level in self.levels:
                for decline, _, _ in self.accesses(level):
                    if decline == name:
                        access[self.levels[level]] = level
            nodes, y = [], portal
            while y >= design:
                if y == portal:
                    kind = "portal"
                elif y in access:
                    kind = "access"
                elif y % self.floor == 0:
                    kind = "turn"
                else:
                    kind = "bay"
                node = {"elevation": y, "chainage": _chainage_at_elevation(pts, y),
                        "at": _point_at_elevation(pts, y), "type": kind}
                if kind == "access":
                    node["level"] = self.tid(access[y])
                node["planned"] = y < bottom
                nodes.append(node)
                y = math.ceil(y / bay) * bay - bay if y == portal else y - bay
            section = self.attr(name, "section_m2")
            if name == "decline-tu2":
                source = ("elevations, slope and section: facts file A2; portal on the centre of the carved pit "
                          "floor (OSM pit outline), first leg south under the pit wall, zigzag in the footwall "
                          "plane; " + SCHEMATIC_PLAN)
            else:
                g = self.terrain.height(pts[0][0], pts[0][2])
                source = (f"elevations, slope and section: facts file A2; portal at +{portal:g} m where the "
                          f"ground (Copernicus DEM, cell mean) is {g:.1f} m, west of the pit; first leg west, then south "
                          "(bend at +418 m), zigzag in the footwall plane; " + SCHEMATIC_PLAN)
            obj = self.head(name, "polyline", pts[0], source)
            obj.update({
                "token": name.rsplit("-", 1)[1],
                "slope_deg": self.attr(name, "slope_deg"),
                "section_m2": section,
                "width": DECLINE_WIDTH, "height": float(section) / DECLINE_WIDTH,
                "portal_elevation": portal, "design_bottom": design,
                "bottom_elevation": bottom, "bottom_at": _point_at_elevation(pts, bottom),
                "length": polyline_length(pts), "built_length": _chainage_at_elevation(pts, bottom),
                "length_factor": self.p["decline.length_factor"],
                "points": pts, "nodes": nodes,
            })
            self.built[name] = obj

    # -- airways -----------------------------------------------------------

    def build_airways(self):
        self.airway_levels = {}
        for name in self.of_kind("shaft", "raise"):
            x, z = AIRWAY_PLAN[name]
            top, bottom = self.attr(name, "top_elevation_m"), self.attr(name, "bottom_elevation_m")
            documented_top = top
            served = [e for lvl, e in self.levels.items()
                      if name in self.links(lvl, "link_air_intake") + self.links(lvl, "link_air_exhaust")]
            if self.kind(name) == "shaft" or top is None:
                # A collar is on the ground of its position.
                top = self.ground(x, z)
            if bottom is None:
                # No published range: from the lowest level that names it to the surface.
                bottom = min(served)
            top, bottom = float(top), float(bottom)
            section = self.attr(name, "section_m2")
            if self.kind(name) == "shaft":
                source = (f"section and bottom: facts file A2; collar on the DEM ground ({top:g} m; registry "
                          f"collar +{documented_top:g} m); " + SCHEMATIC_PLAN)
            elif documented_top is None:
                source = ("section: facts file A2; range not published: from the lowest level it serves to the "
                          "ground; " + SCHEMATIC_PLAN)
            else:
                source = "section and elevation range: facts file A2; " + SCHEMATIC_PLAN
            obj = self.head(name, "cylinder", [x, top, z], source)
            obj.update({"base": [x, bottom, z], "top": top,
                        "radius": math.sqrt(float(section) / math.pi), "section_m2": section,
                        "direction": self.attr(name, "direction")})
            if documented_top is not None and self.kind(name) == "shaft":
                obj["documented_top"] = documented_top
            if not obj["planned"]:
                decline = RAISE_DECLINE.get(name)
                reach = (min(self.levels[lvl] for lvl in self.links(decline, "link_levels"))
                         if decline else self.developed_bottom)
                if bottom < reach:
                    obj["planned_below"] = reach
            self.built[name] = obj
            inside = [lvl for lvl, e in self.levels.items() if bottom <= e <= top]
            if not inside:
                # The shaft stops above the top level: a drift joins its foot to that level.
                below = [lvl for lvl, e in self.levels.items() if e < bottom]
                inside = [max(below, key=lambda lvl: self.levels[lvl])]
            self.airway_levels[name] = inside

    def drive_z(self, level):
        """z of a level's drive: the ventilation level's runs north of the ore zone."""
        return VENT_DRIVE_Z if self.attr(level, "role") == "ventilation" else DRIVE_Z

    def airway_link(self, airway, level):
        obj, e = self.built[airway], self.levels[level]
        x, bottom, z = obj["base"]
        return [[x, e, self.drive_z(level)], [x, max(e, bottom), z]]

    # -- stopes and levels -------------------------------------------------

    def stope_size(self, tonnes):
        """[strike length, height, thickness] of a vertical tabular block holding `tonnes` of ore."""
        height, thickness = self.floor, float(self.p["stope.thickness_m"])
        return [tonnes / (float(self.p["ore.density"]) * height * thickness), height, thickness]

    def build_stopes(self):
        for name in self.of_kind("stope"):
            level = self.links(name, "link_level")[0]
            e = self.levels[level]
            x = STOPE_X[int(name.rsplit("-", 1)[1]) - 1]
            tonnes = float(self.attr(name, "ore_initial_t"))
            dx, dy, dz = self.stope_size(tonnes)
            source = ("height: 50 m floor (facts file A1); thickness stope.thickness_m; strike length from "
                      "ore_initial_t at ore.density 2.83 t/m3 (A3); vertical (dip 70-90 deg, A1); " + SCHEMATIC_PLAN)
            obj = self.head(name, "box", [x, e + dy / 2, ORE_Z], source)
            obj.update({"center": [x, e + dy / 2, ORE_Z], "size": [dx, dy, dz],
                        "strike_length": dx, "thickness": dz, "dip_deg": DIP_DEG,
                        "tonnage_t": tonnes, "density_t_m3": float(self.p["ore.density"]),
                        "level": self.tid(level), "draw_point": [x, e, ORE_Z + dz / 2],
                        "routes": [self.tid(d) for d in self.links(name, "link_ore_route")]})
            self.built[name] = obj

    def build_levels(self):
        for level, e in self.levels.items():
            level_planned = self.planned(level)
            dz = self.drive_z(level)
            links = []
            for decline, point, planned in self.accesses(level):
                links.append({"to": self.tid(decline), "role": "access", "planned": planned,
                              "points": [[point[0], e, dz], point]})
            for stope in self.of_kind("stope"):
                if self.links(stope, "link_level") == [level]:
                    links.append({"to": self.tid(stope), "role": "crosscut", "planned": self.planned(stope),
                                  "points": [[self.built[stope]["draw_point"][0], e, dz],
                                             self.built[stope]["draw_point"]]})
            for airway, served in self.airway_levels.items():
                if level in served:
                    obj = self.built[airway]
                    planned = level_planned or obj["planned"] or e < obj.get("planned_below", e)
                    links.append({"to": self.tid(airway), "role": "airway", "planned": planned,
                                  "points": self.airway_link(airway, level)})
            for station in self.of_kind("pump_station"):
                if _short(self.attr(station, "_parents")) == level:
                    x = PUMP_X[station]
                    links.append({"to": self.tid(station), "role": "chamber", "planned": self.planned(station),
                                  "points": [[x, e, dz], [x, e, PUMP_Z - PUMP_CHAMBER[2] / 2]]})
            # The drive spans the ore zone and every junction that exists with the level itself.
            xs = list(ORE_X) + [ln["points"][0][0] for ln in links if level_planned or not ln["planned"]]
            x_min, x_max = min(xs), max(xs)
            for ln in links:
                x = ln["points"][0][0]
                if not x_min <= x <= x_max:
                    ln["points"].insert(0, [min(max(x, x_min), x_max), e, dz])
            obj = self.head(level, "polyline", [x_min, e, dz],
                            "elevation: facts file A2 and the 50 m floor (A1); " + SCHEMATIC_PLAN)
            obj.update({"elevation": e, "role": self.attr(level, "role"),
                        "width": DRIVE_WIDTH, "height": DRIVE_HEIGHT,
                        "points": [[x_min, e, dz], [x_max, e, dz]],
                        "extent": [x_min, min(LEVEL_Z[0], dz - 30.0), x_max, LEVEL_Z[1]], "links": links})
            self.built[level] = obj

    # -- fans and pump stations --------------------------------------------

    def build_fans(self):
        for name in self.of_kind("main_fan"):
            parent = _short(self.attr(name, "_parents"))
            if self.kind(parent) == "shaft":
                size = FAN_SURFACE
                x, _, z = self.built[parent]["base"]
                bottom = self.lowest_ground(_rect(x - size[0], z, size[0], size[2]), step=2.0)
                center = [x - size[0], bottom + size[1] / 2, z]
                source = "on the ground beside the shaft collar; " + SCHEMATIC_PLAN
            elif self.kind(parent) == "raise":
                size = FAN_UNDERGROUND
                x, _, z = self.built[parent]["base"]
                center = [x, self.built[parent]["top"] + size[1] / 2, z]
                source = "at the head of the raise; " + SCHEMATIC_PLAN
            else:
                # Underground installation: in the level's access to the decline it feeds.
                size = FAN_UNDERGROUND
                airway = self.tid(self.links(name, "link_airway")[0])
                a, b = next(ln["points"] for ln in self.built[parent]["links"] if ln["to"] == airway)[-2:]
                center = [(a[0] + b[0]) / 2, a[1] + size[1] / 2, (a[2] + b[2]) / 2]
                source = "in the level's connection to its airway; " + SCHEMATIC_PLAN
            obj = self.head(name, "box", center, source)
            obj.update({"center": center, "size": list(size),
                        "airway": [self.tid(a) for a in self.links(name, "link_airway")]})
            self.built[name] = obj

    def build_pump_stations(self):
        for name in self.of_kind("pump_station"):
            e, x = float(self.attr(name, "elevation_m")), PUMP_X[name]
            dx, dy, dz = PUMP_CHAMBER
            center = [x, e + dy / 2, PUMP_Z]
            volume = float(self.attr(name, "sump_volume_m3"))
            sump_dz = 15.0 if volume >= 1000 else 10.0
            target = self.links(name, "link_discharges_to")[0]
            pipe = [[x, e, PUMP_Z]]
            if self.kind(target) == "pump_station":
                te, tx = float(self.attr(target, "elevation_m")), PUMP_X[target]
                pipe += [[x, te, PUMP_Z], [tx, te, PUMP_Z]]
            else:
                # Up a borehole to the level under the shaft, along that level, up the shaft, over the
                # ground to the pond.
                level = self.airway_levels[PIPE_SHAFT][0]
                le = self.levels[level]
                shaft = self.built[PIPE_SHAFT]
                sx, _, sz = shaft["base"]
                pond = self.built[target]["anchor"]
                pipe += [[x, le, PUMP_Z], [x, le, self.drive_z(level)]] + self.airway_link(PIPE_SHAFT, level)
                pipe += [[sx, shaft["top"], sz]] + self.drape([[sx, sz], [pond[0], pond[2]]])
            obj = self.head(name, "box", center, "elevation and sump: facts file A6; " + SCHEMATIC_PLAN)
            obj.update({"center": center, "size": [dx, dy, dz], "elevation": e,
                        "sump": {"center": [x, e - SUMP_DEPTH / 2, PUMP_Z],
                                 "size": [volume / SUMP_DEPTH / sump_dz, SUMP_DEPTH, sump_dz]},
                        "discharges_to": self.tid(target), "pipe": _dedupe(pipe)})
            self.built[name] = obj

    # -- surface -----------------------------------------------------------

    def build_ponds(self):
        ponds = sorted(self.features["ponds"],
                       key=lambda f: -sum(self.ground(x, z) for x, z in f["outline"]) / len(f["outline"]))
        for name, pond in zip(self.of_kind("settling_pond"), ponds):
            cx, cz = polygon_centroid(pond["outline"])
            g = self.ground(cx, cz)
            depth, area = float(self.attr(name, "depth_m")), float(self.attr(name, "area_m2"))
            source = (f"position: OSM natural=water way {pond['osm']} (turquoise pond in the Sentinel-2 image), "
                      f"the higher of the two is the upper pond; size: documented area {area:g} m2 and depth "
                      f"{depth:g} m (the mapped pond is {pond['area']:g} m2)")
            obj = self.head(name, "box", [cx, g, cz], source)
            obj.update({"center": [cx, g - depth / 2, cz], "size": [POND_LENGTH, depth, area / POND_LENGTH],
                        "outline": pond["outline"]})
            self.built[name] = obj

    def build_surface_things(self):
        self.build_ponds()

        cx, cz = ROM_CENTER
        pad = _rect(cx, cz, *ROM_PAD)
        base = self.lowest_ground(pad)
        for name in self.of_kind("rom_stockpile"):
            source = ("not identifiable in the 10 m image: placed on flat free ground between the ponds and the "
                      "plant, off the OSM roads and heaps")
            obj = self.head(name, "cone", [cx, base + ROM_CONE[1], cz], source)
            obj.update({"base": [cx, base, cz], "radius": ROM_CONE[0], "height": ROM_CONE[1],
                        "reference_t": self.p["stockpile.start_t"],
                        "pad": pad, "dump": [ROM_DUMP[0], base, ROM_DUMP[1]]})
            self.built[name] = obj
        self.rom_base = base

        site = self.features["plant_site"]["outline"]
        lines = self.of_kind("plant_line")
        dx, dy, dz = PLANT_LINE
        tops = []
        for index, name in enumerate(lines):
            x = PLANT_CENTER[0] + (index - (len(lines) - 1) / 2) * PLANT_PITCH
            bottom = self.lowest_ground(_rect(x, PLANT_CENTER[1], dx, dz))
            center = [x, bottom + dy / 2, PLANT_CENTER[1]]
            source = ("in the plant site (OSM building cluster of the industrial zone); which building holds the "
                      "line is not identifiable at 10 m")
            obj = self.head(name, "box", center, source)
            obj.update({"center": center, "size": [dx, dy, dz]})
            self.built[name] = obj
            tops.append(bottom + dy)
        for name in self.of_kind("plant"):
            y = self.lowest_ground(site)
            source = (f"OSM building cluster east of the heaps ({len(self.features['plant_site']['osm'])} buildings) "
                      "inside the OSM industrial zone; the mill itself is not identifiable at 10 m")
            obj = self.head(name, "outline", [PLANT_CENTER[0], max(tops), PLANT_CENTER[1]], source)
            obj.update({"y": y, "footprint": site})
            self.built[name] = obj

        # Tailings: real OSM cells; the facility anchor at its registry coordinates.
        cells = {c["osm"]: c for c in self.features["tailings"]}
        for name in self.of_kind("tailings_facility"):
            tx, tz = to_scene(*_dms(self.attr(name, "coordinates")))
            hull = convex_hull([p for c in cells.values() for p in c["outline"]])
            dams = [d for d in self.of_kind("tailings_dam") if _short(self.attr(d, "_parents")) == name]
            for dam in dams:
                if dam in TSF_CELLS:
                    cell = cells[TSF_CELLS[dam]]
                    footprint = cell["outline"]
                    source = (f"on OSM man_made=tailings_pond way {cell['osm']}; which cell carries the dam number "
                              "is not published (assumed); top: the level that holds the documented capacity "
                              "above the ground")
                else:
                    x0, z0, x1, z1 = TSF_CELL5[1]
                    footprint = _rect((x0 + x1) / 2, (z0 + z1) / 2, x1 - x0, z1 - z0)
                    source = ("planned cell (measure X1): placed on free farmland east of the facility, clear of "
                              "the OSM roads; top: the level that holds the capacity above the ground")
                bottom = self.lowest_ground(footprint)
                top = self.crest(footprint, float(self.attr(dam, "capacity_m3")))
                ax, az = polygon_centroid(footprint)
                obj = self.head(dam, "prism", [ax, top, az], source)
                obj.update({"footprint": footprint, "bottom": bottom, "top": top})
                self.built[dam] = obj
            source = ("anchor: registry coordinates 50°20'24\" N, 82°36'30\" E; outline: convex hull of the five "
                      "OSM tailings_pond cells")
            obj = self.head(name, "outline", [tx, self.ground(tx, tz), tz], source)
            obj.update({"y": self.lowest_ground(hull, step=25.0), "footprint": hull,
                        "bearing_deg": round(math.degrees(math.atan2(tx, -tz)), 1),
                        "true_distance": math.hypot(tx, tz)})
            self.built[name] = obj

        # Monitoring points on the OSM water courses.
        stream = self.features["stream"]["points"]
        river = self.features["river"]["points"]
        self.outfall = stream[0]
        self.intake = min(river, key=lambda p: (math.dist(p, PLANT_CENTER), p))
        for name, at, source in (
                ("mon-volchevka", self.outfall,
                 "on the OSM stream (taken as the Volchevka: 60-75 m from the pit's south edge, joins the "
                 "Sekisovka) at its head 70 m south of the ponds; the outfall position is not published"),
                ("mon-sekisovka", self.intake,
                 "on the OSM river Sekisovka at its point nearest the plant; the intake position is not "
                 "published")):
            self.built[name] = self.head(name, "marker", self.at_ground(*at), source)

    def build_mobile(self):
        rows = [self.of_kind("haul_truck"), self.of_kind("lhd"), self.of_kind("drill_rig")]
        slots, row = {}, 0
        for group in rows:
            for index, name in enumerate(group):
                slots[name] = (row + index // YARD_COLUMNS, index % YARD_COLUMNS)
            row += math.ceil(len(group) / YARD_COLUMNS)
        self.yard = (YARD_COLUMNS * YARD_PITCH, row * YARD_PITCH)
        footprint = _rect(YARD_CENTER[0], YARD_CENTER[1], *self.yard)
        self.yard_y = y = self.lowest_ground(footprint)
        x0, z0 = YARD_CENTER[0] - self.yard[0] / 2, YARD_CENTER[1] - self.yard[1] / 2
        for name, (r, c) in slots.items():
            kind = self.kind(name)
            if kind == "haul_truck":
                model = "AD30" if self.attr(name, "payload_t") == self.p["truck.AD30.payload_t"] else "AD45"
            elif kind == "lhd":
                model = "R1300" if self.attr(name, "bucket_t") == self.p["lhd.R1300.bucket_t"] else "R1700"
            else:
                model = "rig"
            length, height, width = VEHICLE_SIZE[model]
            center = [x0 + (c + 0.5) * YARD_PITCH, y + height / 2, z0 + (r + 0.5) * YARD_PITCH]
            obj = self.head(name, "box", center, "parking slot in the yard (schematic)")
            obj.update({"center": center, "size": [length, height, width], "mobile": True})
            self.built[name] = obj

    # -- scenery -----------------------------------------------------------

    def build_scenery(self):
        s = self.scenery
        F = self.features
        pit = F["pit"]
        tu1, tu2 = self.decline_pts["decline-tu1"], self.decline_pts["decline-tu2"]
        cx, cz = pit["centre"]
        s["old-pit"] = {
            "primitive": "pit", "sourced": True,
            "source": (f"outline: OSM landuse=quarry way {pit['osm']} (matches the pit in the Sentinel-2 image and "
                       "the DEM depression); carved from the documents: final floor at the TU2 portal +320 m, "
                       f"benches of {pit['bench_height']:g} m at {pit['face_angle_deg']:g} deg with {pit['berm']:g} m "
                       f"berms, overall slope {pit['overall_slope_deg']:.1f} deg (the 2011-2015 DEM floor is "
                       "389.7 m)"),
            "base": [cx, pit["floor"], cz], "floor": pit["floor"], "top": max(p[1] for p in pit["rim"]),
            "outline": pit["outline"], "rim": pit["rim"], "floor_outline": pit["floor_outline"],
            "overall_slope_deg": pit["overall_slope_deg"], "bench_height": pit["bench_height"],
            "benches": pit["benches"], "section": pit["section"],
        }

        # Haul roads: the pit ramp (TU2), then the OSM roads to the ROM pad dump point.
        dump = [ROM_DUMP[0], self.rom_base, ROM_DUMP[1]]
        ramp = [list(p) for p in pit["ramp"]]
        if ramp[0] != tu2[0]:
            raise ValueError("the pit ramp does not start at the TU2 portal")
        exit_ = ramp[-1]
        path = self.route([exit_[0], exit_[2]], [dump[0], dump[2]])
        s["road-tu2"] = {"primitive": "polyline", "sourced": False,
                         "source": "ramp: designed spiral on the carved wall at 8 deg; then OSM service roads "
                                   "(shortest path) to the ROM pad",
                         "decline": self.tid("decline-tu2"),
                         "points": _dedupe(ramp + self.drape(path)[1:-1] + [dump])}
        apron = [tu1[0][0] + PORTAL_APRON, tu1[0][2]]
        path = self.route(apron, [dump[0], dump[2]])
        s["road-tu1"] = {"primitive": "polyline", "sourced": False,
                         "source": "from the schematic TU1 portal along OSM tracks and service roads (shortest "
                                   "path) to the ROM pad",
                         "decline": self.tid("decline-tu1"),
                         "points": _dedupe([tu1[0]] + self.drape([[tu1[0][0], tu1[0][2]]] + path)[1:-1] + [dump])}
        s["yard"] = {"primitive": "outline", "sourced": False,
                     "source": "parking yard on flat free ground near the ROM pad (not identifiable)",
                     "y": self.yard_y, "footprint": _rect(YARD_CENTER[0], YARD_CENTER[1], *self.yard)}

        # Water courses, village, industrial zone, unnumbered tailings cells.
        s["stream-volchevka"] = {
            "primitive": "polyline", "sourced": True,
            "source": (f"OSM waterway=stream ways {', '.join(map(str, F['stream']['osm']))} from the head to the "
                       f"Sekisovka; unnamed in OSM, taken as the Volchevka (facts: 60 m from the pit's south "
                       f"boundary, 735 m long; mapped length {F['stream']['length']:g} m)"),
            "points": self.drape(F["stream"]["points"])}
        s["river-sekisovka"] = {
            "primitive": "polyline", "sourced": True,
            "source": f"OSM waterway=river Секисовка, ways {', '.join(map(str, F['river']['osm']))}, in flow order",
            "points": self.drape(F["river"]["points"])}
        vx, vz = F["village"]["at"]
        s["village"] = {"primitive": "marker", "sourced": True,
                        "source": f"OSM place=village node {F['village']['osm']} (Секисовка)",
                        "anchor": self.at_ground(vx, vz)}
        zone = F["industrial"]
        s["industrial-zone"] = {"primitive": "outline", "sourced": True,
                                "source": f"OSM landuse=industrial way {zone['osm']}",
                                "y": self.lowest_ground(zone["outline"], step=50.0), "footprint": zone["outline"]}
        cells = {c["osm"]: c for c in F["tailings"]}
        for key, osm in TSF_UNNUMBERED.items():
            s[key] = {"primitive": "outline", "sourced": True,
                      "source": f"OSM man_made=tailings_pond way {osm}; no dam number assigned",
                      "y": self.lowest_ground(cells[osm]["outline"]), "footprint": cells[osm]["outline"]}

        # Process lines on the surface (schematic routes between real or chosen end points).
        lines = self.of_kind("plant_line")
        row = (len(lines) - 1) * PLANT_PITCH + PLANT_LINE[0]
        west, east = PLANT_CENTER[0] - row / 2, PLANT_CENTER[0] + row / 2
        south, north = PLANT_CENTER[1] + PLANT_LINE[2] / 2, PLANT_CENTER[1] - PLANT_LINE[2] / 2
        lower = self.built["pond-lower"]["anchor"]
        lower = [lower[0], lower[2]]
        dam4 = self.built["tsf-dam4"]["anchor"]
        plan = {
            "conveyor": [[ROM_CENTER[0] + ROM_PAD[0] / 2, ROM_CENTER[1]], [west - 15, south + 15],
                         [east, south + 15]],
            "pipeline-tailings": [[PLANT_CENTER[0], north], [PLANT_CENTER[0], north - 40], [1080.0, -640.0],
                                  [1080.0, dam4[2]], [dam4[0], dam4[2]]],
            "pipeline-water-supply": self.route(lower, [west - 15, PLANT_CENTER[1]]),
            "pipeline-discharge": [lower, list(self.outfall)],
            # across the fields east of the pit (along the roads it would run 1.8 km through the village)
            "pipeline-intake": [list(self.intake), [west - 15, PLANT_CENTER[1]]],
        }
        for name, pts in plan.items():
            along = " along the OSM roads" if name == "pipeline-water-supply" else ""
            s[name] = {"primitive": "polyline", "sourced": False,
                       "source": f"schematic route between its end points{along}, laid on the ground",
                       "points": self.drape(pts)}

        # Backfilled blocks of the mined-out levels, on the stope grid.
        dx, dy, dz = self.stope_size(float(self.p["stope.ore_initial_t"]))
        for level, e in self.levels.items():
            if self.attr(level, "role") == "mined_out":
                for index, x in enumerate(STOPE_X):
                    s[f"backfill-{level.split('-', 1)[1]}-{index + 1}"] = {
                        "primitive": "box", "sourced": False,
                        "source": "mined-out block of the stope grid; " + SCHEMATIC_PLAN,
                        "level": self.tid(level), "center": [x, e + dy / 2, ORE_Z], "size": [dx, dy, dz]}

    # -- terrain and profile -----------------------------------------------

    def terrain_block(self):
        hm = self.heightmap
        low, high = self.terrain.range()
        return {
            "sourced": True,
            "source": ("Copernicus DEM GLO-30 (TanDEM-X 2011-2015), cell means over 62.5 m; inside the OSM pit "
                       "outline the final pit carved to the documents (floor +320 m, benched wall at its overall "
                       "slope); built offline by tools/build_terrain.py"),
            "attribution": ATTRIBUTION, "attribution_file": ATTRIBUTION_FILE, "heightmap_file": HEIGHTMAP_FILE,
            "extent": list(self.terrain.extent),
            "origin": hm["origin"], "spacing": hm["spacing"], "size": hm["size"],
            "triangles": 2 * (hm["size"][0] - 1) * (hm["size"][1] - 1),
            "elevation_range": [low, high],
            "rows": hm["rows"],
            "inset": {k: hm["inset"][k] for k in ("origin", "spacing", "size", "cells", "rows")},
            "texture": {"file": TEXTURE_FILE, "size": [512, 512], "extent": list(self.terrain.extent),
                        "north_up": True, "format": "jpeg",
                        "source": "Sentinel-2C L2A true colour, scene S2C_44UPA_20260930_0_L2A, 30 September "
                                  "2026, 10 m, resampled to 7.8 m pixels"},
        }

    def profile(self):
        x0, _, x1, _ = self.terrain.extent
        n = int(round((x1 - x0) / PROFILE_STEP))
        return {"sourced": True,
                "source": "ground of the terrain block along the long section (DEM, pit carved)",
                "z": ORE_Z, "step": PROFILE_STEP,
                "points": [[x0 + k * PROFILE_STEP, self.ground(x0 + k * PROFILE_STEP, ORE_Z)] for k in range(n + 1)]}

    # -- assembly ----------------------------------------------------------

    def document(self):
        self.decline_frame()
        self.build_declines()
        self.build_airways()
        self.build_stopes()
        self.build_levels()
        self.build_fans()
        self.build_surface_things()
        self.build_pump_stations()
        self.build_mobile()
        self.build_scenery()

        missing = [n for n in self.order if self.kind(n) not in ABSTRACT_KINDS and n not in self.built]
        if missing:
            raise ValueError(f"no geometry for {missing}")
        objects = {self.tid(n): self.built[n] for n in self.order if n in self.built}
        terrain = self.terrain_block()
        x0, z0, x1, z1 = terrain["extent"]
        surface = {"primitive": "outline", "sourced": True,
                   "source": "extent of the terrain block; the ground itself is terrain (y is the TU1 portal, "
                             "kept as the reference surface elevation)",
                   "y": self.surface_y, "footprint": [[x0, z0], [x1, z0], [x1, z1], [x0, z1]]}
        body = _normalise({"scenery": {"surface": surface, **self.scenery}, "objects": objects})
        points = [p for item in list(body["scenery"].values()) + list(body["objects"].values())
                  for p in item_points(item)]
        low = min(min(p[1] for p in points), terrain["elevation_range"][0])
        high = max(max(p[1] for p in points), terrain["elevation_range"][1])
        for p in points:
            if not (x0 <= p[0] <= x1 and z0 <= p[2] <= z1):
                raise ValueError(f"a point lies outside the terrain: {p}")
        return _normalise({
            "_schema": SCHEMA,
            "namespace": self.ns,
            "frame": {"x": "east", "y": "up, elevation m a.s.l.", "z": "south", "unit": "m",
                      "surface": self.surface_y,
                      "origin": "x = 0, z = 0 is the mine point 50.3286583 N, 82.5966139 E (50 deg 19'43.17\" N, "
                                "82 deg 35'47.81\" E); y = 0 is sea level",
                      "crs": "x = UTM 44N easting - 613640.00, z = 5576392.36 - UTM 44N northing (EPSG:32644, "
                             "WGS 84); grid north is the scene's north",
                      "grid_convergence_deg": round(grid_convergence_deg(), 3),
                      "layout_shift": list(LAYOUT_SHIFT),
                      "strike_azimuth_deg": STRIKE_AZIMUTH_DEG,
                      "layout": "underground plan positions are schematic: the mine layout (ore zone, declines, "
                                "airways, levels) is drawn in a frame whose origin, layout_shift, is the centre of "
                                "the carved pit floor, where the TU2 portal stands; the ore zone strikes east-west "
                                "(strike_azimuth_deg, grid) under the old pit, along its long axis; no azimuth is "
                                "published; surface positions are real (sourced flags)"},
            "bounds": {"min": [x0, math.floor(low), z0], "max": [x1, math.ceil(high), z1]},
            "terrain": terrain,
            "profile": self.profile(),
            "scenery": body["scenery"],
            "objects": body["objects"],
        })


def item_points(item):
    """Corner or vertex points of one object or scenery item (for bounds and checks)."""
    prim = item["primitive"]
    if prim == "polyline":
        pts = [list(p) for p in item["points"]]
        for link in item.get("links", []):
            pts += link["points"]
        return pts
    if prim == "box":
        c, s = item["center"], item["size"]
        return [[c[0] + i * s[0] / 2, c[1] + j * s[1] / 2, c[2] + k * s[2] / 2]
                for i in (-1, 1) for j in (-1, 1) for k in (-1, 1)]
    if prim == "cylinder":
        x, y, z = item["base"]
        r = item["radius"]
        return [[x + i * r, yy, z + k * r] for i in (-1, 1) for k in (-1, 1) for yy in (y, item["top"])]
    if prim == "pit":
        return [list(p) for p in item["rim"]] + [list(item["base"])]
    if prim == "cone":
        x, y, z = item["base"]
        r = item["radius"]
        return [[x + i * r, yy, z + k * r] for i in (-1, 1) for k in (-1, 1) for yy in (y, y + item["height"])]
    if prim == "prism":
        return [[x, yy, z] for x, z in item["footprint"] for yy in (item["bottom"], item["top"])]
    if prim == "outline":
        return [[x, item["y"], z] for x, z in item["footprint"]]
    if prim == "marker":
        return [list(item["anchor"])]
    raise ValueError(f"unknown primitive {prim!r}")


# --------------------------------------------------------------------------
# Public API: building and writing
# --------------------------------------------------------------------------

def build(params=None, registry=None, heightmap=None, features=None):
    """Return the geometry document (the content of geometry.json) as a dict."""
    params = _read_json(PARAMS_PATH) if params is None else params
    registry = _read_json(REGISTRY_PATH) if registry is None else registry
    heightmap = _read_json(HEIGHTMAP_PATH) if heightmap is None else heightmap
    features = _read_json(FEATURES_PATH) if features is None else features
    return _Builder(params, registry, heightmap, features).document()


def dumps(doc):
    """Canonical text of a geometry document: fixed key order, one object per line, LF."""
    def js(value):
        return json.dumps(value, ensure_ascii=True, separators=(",", ":"))

    lines = ["{"]
    keys = list(doc)
    for i, key in enumerate(keys):
        value, comma = doc[key], "," if i < len(keys) - 1 else ""
        if key in ("_schema", "scenery", "objects"):
            lines.append(f" {js(key)}:{{")
            items = list(value.items())
            for j, (k, v) in enumerate(items):
                lines.append(f"  {js(k)}:{js(v)}" + ("," if j < len(items) - 1 else ""))
            lines.append(" }" + comma)
        else:
            lines.append(f" {js(key)}:{js(value)}{comma}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def write(path=GEOMETRY_PATH):
    """Generate geometry.json; returns the path."""
    path = Path(path)
    path.write_bytes(dumps(build()).encode("utf-8"))
    return path


# --------------------------------------------------------------------------
# Public API: lookups
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Leg:
    """One stretch of a route: 'level', 'decline' or 'surface'."""
    name: str
    points: tuple
    length: float


class Route:
    """A continuous polyline made of legs, with lookup by distance."""

    def __init__(self, legs):
        self.legs = tuple(legs)
        points = []
        for leg in self.legs:
            for p in leg.points:
                if not points or points[-1] != p:
                    points.append(p)
        self.points = tuple(points)
        self.length = sum(leg.length for leg in self.legs)

    def point_at(self, distance):
        """(x, y, z) at `distance` metres from the start; clamped to the ends."""
        return polyline_point(self.points, distance)

    def point_at_fraction(self, fraction):
        return self.point_at(self.length * fraction)

    def leg(self, name):
        return next(leg for leg in self.legs if leg.name == name)

    def reversed(self):
        return Route(Leg(leg.name, tuple(reversed(leg.points)), leg.length) for leg in reversed(self.legs))


def _leg(name, points):
    pts = tuple(tuple(float(c) for c in p) for p in _dedupe(points))
    return Leg(name, pts, polyline_length(pts))


class Geometry:
    """Lookups over a geometry document. Thing arguments take a full thing ID
    ('kz.sekis:stp-p150-1'), a thing name ('stp-p150-1') or, for declines, the
    token used in truck telemetry ('tu1')."""

    def __init__(self, doc):
        self.doc = doc
        self.namespace = doc["namespace"]
        self.objects = doc["objects"]
        self.scenery = doc["scenery"]
        self.terrain = Terrain(doc["terrain"]) if "terrain" in doc else None

    # -- ground ------------------------------------------------------------

    def ground(self, x, z):
        """Ground elevation at scene (x, z), interpolated on the drawn terrain triangles."""
        return self.terrain.height(x, z)

    # -- identity ----------------------------------------------------------

    def thing_id(self, thing):
        if ":" in thing:
            return thing
        full = f"{self.namespace}:{thing}"
        if full in self.objects:
            return full
        return f"{self.namespace}:decline-{thing}"

    def thing_ids(self):
        """Thing IDs that have geometry, in registry order."""
        return list(self.objects)

    def obj(self, thing):
        """Geometry entry of a thing; KeyError when it has none."""
        return self.objects[self.thing_id(thing)]

    # -- positions ---------------------------------------------------------

    def position(self, thing):
        """Anchor (x, y, z) of a thing, or None when it has no place in the scene.
        For trucks, loaders and rigs this is the parking slot."""
        entry = self.objects.get(self.thing_id(thing))
        return tuple(float(c) for c in entry["anchor"]) if entry else None

    def positions(self):
        """{thing ID: (x, y, z)} for every thing that has a position."""
        return {tid: tuple(float(c) for c in entry["anchor"]) for tid, entry in self.objects.items()}

    # -- declines ----------------------------------------------------------

    def declines(self):
        return [tid for tid, entry in self.objects.items() if entry["kind"] == "decline"]

    def decline_length(self, decline, bottom=None):
        """Metres along the decline from the portal to `bottom` (default: the design bottom)."""
        entry = self.obj(decline)
        return _chainage_at_elevation(entry["points"], entry["design_bottom"] if bottom is None else bottom)

    def decline_chainage(self, decline, elevation):
        """Metres along the decline from the portal to the given elevation."""
        return _chainage_at_elevation(self.obj(decline)["points"], elevation)

    def decline_elevation(self, decline, distance):
        """Elevation at `distance` metres from the portal."""
        return self.decline_point(decline, distance=distance)[1]

    def decline_point(self, decline, distance=None, elevation=None):
        """(x, y, z) on the decline, by metres from the portal or by elevation (give exactly one)."""
        if (distance is None) == (elevation is None):
            raise ValueError("give exactly one of distance and elevation")
        points = self.obj(decline)["points"]
        if elevation is not None:
            return tuple(_point_at_elevation(points, elevation))
        if not -0.05 <= distance <= polyline_length(points) + 0.05:
            raise ValueError(f"distance {distance} is outside the decline")
        return polyline_point(points, distance)

    def passing_bays(self, decline, bottom=None):
        """Traffic nodes from the portal down to `bottom` (default: the bottom at the start):
        the portal, every 25 m of elevation below it and the bottom itself. Each node is a dict with
        elevation, chainage, at (x, y, z), type (portal, bay, turn, access, bottom) and, for an
        access, level."""
        entry = self.obj(decline)
        bottom = entry["bottom_elevation"] if bottom is None else bottom
        nodes = []
        for node in entry["nodes"]:
            if node["elevation"] < bottom:
                break
            item = {"elevation": float(node["elevation"]),
                    "chainage": _chainage_at_elevation(entry["points"], node["elevation"]),
                    "at": tuple(_point_at_elevation(entry["points"], node["elevation"])),
                    "type": node["type"]}
            if "level" in node:
                item["level"] = node["level"]
            nodes.append(item)
        if nodes[-1]["elevation"] != bottom:
            nodes.append({"elevation": float(bottom),
                          "chainage": _chainage_at_elevation(entry["points"], bottom),
                          "at": tuple(_point_at_elevation(entry["points"], bottom)), "type": "bottom"})
        return nodes

    def decline_path(self, decline, from_elevation, to_elevation):
        """Points along the decline between two elevations, in travel order."""
        points = self.obj(decline)["points"]
        high, low = max(from_elevation, to_elevation), min(from_elevation, to_elevation)
        path = [_point_at_elevation(points, high)]
        path += [p for p in points if low < p[1] < high]
        path.append(_point_at_elevation(points, low))
        if from_elevation < to_elevation:
            path.reverse()
        return [tuple(float(c) for c in p) for p in _dedupe(path)]

    def surface_road(self, decline):
        """Road on the surface from the decline's portal to the ROM pad dump point."""
        tid = self.thing_id(decline)
        road = next(item for item in self.scenery.values() if item.get("decline") == tid)
        return [tuple(float(c) for c in p) for p in road["points"]]

    # -- routes ------------------------------------------------------------

    def declines_for(self, stope):
        """Declines that reach the stope (its link_ore_route)."""
        return list(self.obj(stope)["routes"])

    def _level_leg(self, stope, decline):
        """Stope draw point -> crosscut -> level drive -> access -> decline."""
        stope_id, decline_id = self.thing_id(stope), self.thing_id(decline)
        level = self.objects[self.objects[stope_id]["level"]]
        crosscut = next(ln["points"] for ln in level["links"] if ln["to"] == stope_id)
        access = next((ln["points"] for ln in level["links"]
                       if ln["to"] == decline_id and ln["role"] == "access"), None)
        if access is None or decline_id not in self.objects[stope_id]["routes"]:
            raise ValueError(f"{decline_id} does not reach {stope_id}")
        return list(reversed(crosscut)) + list(access)

    def stope_route(self, stope, decline=None):
        """Route from a stope to the ROM pad: legs 'level', 'decline', 'surface'.
        `decline` defaults to the first decline that reaches the stope. Use .reversed() for the way down."""
        decline = self.declines_for(stope)[0] if decline is None else decline
        level_leg = self._level_leg(stope, decline)
        portal = self.obj(decline)["portal_elevation"]
        return Route([
            _leg("level", level_leg),
            _leg("decline", self.decline_path(decline, level_leg[-1][1], portal)),
            _leg("surface", self.surface_road(decline)),
        ])

    def stopes_route(self, stope_from, stope_to, decline=None):
        """Route between two stopes (for loaders and rigs): along the drive on one level,
        otherwise through a decline that reaches both."""
        a, b = self.thing_id(stope_from), self.thing_id(stope_to)
        if self.objects[a]["level"] == self.objects[b]["level"]:
            level = self.objects[self.objects[a]["level"]]
            start = next(ln["points"] for ln in level["links"] if ln["to"] == a)
            end = next(ln["points"] for ln in level["links"] if ln["to"] == b)
            return Route([_leg("level", list(reversed(start)) + list(end))])
        if decline is None:
            shared = [d for d in self.declines_for(a) if d in self.declines_for(b)]
            if not shared:
                raise ValueError(f"no decline reaches both {a} and {b}")
            decline = shared[0]
        leg_a, leg_b = self._level_leg(a, decline), self._level_leg(b, decline)
        return Route([
            _leg("level", leg_a),
            _leg("decline", self.decline_path(decline, leg_a[-1][1], leg_b[-1][1])),
            _leg("level", list(reversed(leg_b))),
        ])


def load(path=GEOMETRY_PATH):
    """Geometry read from geometry.json."""
    return Geometry(_read_json(path))


_default = None


def default():
    """The shared Geometry: read from geometry.json, generated in memory when the file is absent."""
    global _default
    if _default is None:
        _default = load() if GEOMETRY_PATH.exists() else Geometry(build())
    return _default


def position(thing):
    return default().position(thing)


def positions():
    return default().positions()


def decline_point(decline, distance=None, elevation=None):
    return default().decline_point(decline, distance=distance, elevation=elevation)


def passing_bays(decline, bottom=None):
    return default().passing_bays(decline, bottom=bottom)


def stope_route(stope, decline=None):
    return default().stope_route(stope, decline=decline)


def main():
    path = write()
    doc = _read_json(path)
    counts = {}
    for item in list(doc["objects"].values()) + list(doc["scenery"].values()):
        counts[item["primitive"]] = counts.get(item["primitive"], 0) + 1
    print(f"{path}: {path.stat().st_size} bytes, {len(doc['objects'])} objects, {len(doc['scenery'])} scenery")
    print("primitives: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    for tid, item in doc["objects"].items():
        if item["kind"] == "decline":
            print(f"{tid}: {item['length']} m to the design bottom, {item['built_length']} m built")


if __name__ == "__main__":
    main()
