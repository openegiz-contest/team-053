"""Scene geometry of the Sekisovskoye twin (spec section 4.2).

Builds ``team/model/geometry.json`` from ``params.json`` and ``registry.json`` and
gives the simulator the lookups it needs: a point on a decline for a distance or
an elevation, the passing bays, the route between a stope and the ROM pad, and
the position of every thing that has one.

Scene frame: x east, y up = elevation in metres above sea level, z south,
1 unit = 1 m. Elevations and cross-sections come from the model files; every
plan position is schematic (no mine plan is published) and lives in the layout
block below.

Run ``python -m sekis.geometry`` in ``team/`` to regenerate the file.
"""

from __future__ import annotations

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

# --------------------------------------------------------------------------
# Schematic layout (spec 4.2). Plan pairs are (x, z). Where a value differs
# from the spec text, the comment says why.
# --------------------------------------------------------------------------

ORE_X = (-300.0, 300.0)          # ore zone along x, at z = 0
STOPE_X = (-200.0, 0.0, 200.0)   # stope 1, 2, 3 of a level
STOPE_SIZE = (120.0, 40.0, 20.0)  # along strike, height, thickness
DRIVE_Z = 40.0                   # level drive, south of the ore zone
DRIVE_WIDTH, DRIVE_HEIGHT = 4.0, 4.0
LEVEL_Z = (-30.0, 160.0)         # z range of a level's workings (water plane, tint)

# West end of each zigzag and its vertical plane. The east end follows from the
# slope: one leg of 50 m of depth runs 50 / tan 8 deg = 355.8 m.
DECLINE_PLAN = {
    "decline-tu1": {"x_west": -330.0, "z": 120.0},
    "decline-tu2": {"x_west": 30.0, "z": 150.0},
}
DECLINE_WIDTH = 4.5              # 4.5 m x 4.0 m = the published 18 m2

AIRWAY_PLAN = {
    "shaft-vs1": (0.0, -60.0),
    # spec (250, -60) lies inside the pit rim; 30 m further north the collar and its fan are clear
    "shaft-vs2": (250.0, -90.0),
    # spec (-250, -60): its level connections would cut through stope 1
    "shaft-vs3": (-300.0, -60.0),
    "raise-vpv": (-100.0, -40.0),
    # spec x = -250 / +250 projects onto stopes 1 and 3 in the long section
    "raise-vhv-tu1": (-280.0, 100.0),
    "raise-vhv-tu2": (280.0, 100.0),
    # spec (330, -20) stands 2 m from the pit rim
    "raise-vhv-exhaust": (340.0, -20.0),
}
# Raises driven alongside a decline exist only as deep as that decline's levels.
RAISE_DECLINE = {"raise-vhv-tu1": "decline-tu1", "raise-vhv-tu2": "decline-tu2"}

PUMP_Z = 70.0                    # pump chambers, 30 m south of the drive
PUMP_X = {"ps-p150": 100.0, "ps-m050": 100.0, "ps-m200": 112.0}
PUMP_CHAMBER = (20.0, 5.0, 10.0)
SUMP_DEPTH = 6.0
PIPE_SHAFT = "shaft-vs1"         # FACT A6: mine water leaves through the ventilation shaft

PIT_FLOOR_RADIUS, PIT_RIM_RADIUS = 90.0, 230.0
PIT_RAMP_SWEEP_DEG, PIT_RAMP_EXIT_DEG, PIT_RAMP_STEP_DEG = 300.0, 120.0, 15.0
PORTAL_APRON = 30.0              # TU1 road leaves the portal eastwards

ROM_CENTER = (-350.0, -250.0)
ROM_PAD = (100.0, 80.0)
ROM_CONE = (30.0, 22.0)          # radius, height at the starting tonnage
ROM_DUMP = (-305.0, -215.0)

PLANT_CENTER = (-500.0, -350.0)
PLANT_LINE = (24.0, 16.0, 60.0)
PLANT_PITCH = 30.0

POND_CENTER = (100.0, -200.0)
POND_LENGTH, POND_GAP = 25.0, 5.0

TSF_DISTANCE = 900.0             # drawn distance; the true one is about 1.5 km
TSF_ORDER = ("tsf-dam2", "tsf-dam3", "tsf-dam4", "tsf-cell5")  # west to east
TSF_DEPTH, TSF_HEIGHT, TSF_GAP = 150.0, 20.0, 20.0
TSF_VOLUME_SCALE = 0.2           # drawn volume / capacity

YARD_CENTER = (-135.0, -85.0)
YARD_PITCH = 14.0
YARD_COLUMNS = 6
VEHICLE_SIZE = {                 # length, height, width: approximate overall size of each model
    "AD30": (10.2, 2.6, 2.7), "AD45": (11.2, 2.8, 3.0),
    "R1300": (8.7, 2.2, 2.1), "R1700": (10.6, 2.6, 2.7),
    "rig": (11.8, 2.2, 1.9),
}

# Facts file, row "Water courses": Volchevka runs 60 m from the pit's south boundary and is
# 735 m long to the Sekisovka; the pit is about 150 m from the Sekisovka's south-west bank.
STREAM_OFFSET, STREAM_LENGTH, RIVER_OFFSET = 60.0, 735.0, 150.0

FAN_SURFACE = (10.0, 6.0, 8.0)
FAN_UNDERGROUND = (6.0, 4.0, 6.0)

# Things whose drawn elevations, cross-section or bearing are published figures.
SOURCED_KINDS = {"level", "decline", "settling_pond", "tailings_facility"}
SOURCED_THINGS = {
    "shaft-vs1", "shaft-vs2", "raise-vpv", "raise-vhv-tu1", "raise-vhv-tu2",
    "ps-p150", "ps-m200",
}
# Kinds with no place in the scene.
ABSTRACT_KINDS = {"enterprise", "mine", "water_system", "scenario_control", "advisor"}

# Keys whose numbers are not rounded to 0.1 m.
EXACT_KEYS = {"section_m2", "slope_deg", "bearing_deg", "length_factor", "volume_scale"}

SCHEMA = {
    "purpose": "Scene geometry of the Sekisovskoye twin (spec 4.2). Generated by sekis/geometry.py from "
               "params.json and registry.json; regenerate with `python -m sekis.geometry` in team/.",
    "frame": "x east, y up = elevation in metres above sea level, z south; 1 unit = 1 m on every axis. "
             "Points are [x, y, z]; plan pairs are [x, z].",
    "numbers": "Coordinates and lengths are rounded to 0.1 m. section_m2, slope_deg, bearing_deg, "
               "length_factor and volume_scale keep their own precision.",
    "objects": "One entry per registry thing that has a place in the scene, keyed by thing ID, in registry "
               "order. Every entry has kind, primitive, sourced, planned and anchor (label and click point).",
    "scenery": "Drawable items that are not things: surface, old pit, haul roads, yard, streams, pipelines, "
               "backfilled blocks. Keyed by a local name; each has primitive and sourced.",
    "sourced": "true: the elevations, cross-section or bearing drawn for the object are published figures. "
               "false: at least one of them is an assumption. Plan position is schematic for every object.",
    "planned": "true: the thing is in state planned in the registry (draw dashed). On a link or a decline "
               "node it marks a connection below the workings developed at the start. planned_below on an "
               "airway is the elevation under which the airway is design only.",
    "primitives": {
        "box": "center [x,y,z], size [dx,dy,dz], axis-aligned",
        "cylinder": "vertical; base [x,bottom,z], top (elevation), radius, section_m2",
        "frustum": "vertical; base [x,y,z] with radius_base, top (elevation) with radius_top",
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
    "mobile": "trucks, loaders and rigs carry mobile true; their box stands on its parking slot. Live "
              "positions are the twin features pos_x, pos_y, pos_z.",
}


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

class _Builder:
    def __init__(self, params, registry):
        self.p = {k: v["value"] for k, v in params.items() if isinstance(v, dict) and "value" in v}
        self.ns = registry["namespace"]
        self.things = {_short(t["thingId"]): t for t in registry["things"]}
        self.order = list(self.things)
        self.built = {}
        self.scenery = {}

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

    def head(self, name, primitive, anchor):
        sourced = self.kind(name) in SOURCED_KINDS or name in SOURCED_THINGS
        return {"kind": self.kind(name), "primitive": primitive, "sourced": sourced,
                "planned": self.planned(name), "anchor": list(anchor)}

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
            plan = DECLINE_PLAN[name]
            first = math.floor(portal / self.floor) * self.floor
            if first == portal:
                first -= self.floor
            tan = math.tan(math.radians(self.slope))
            points = [[plan["x_west"] + (portal - first) / tan, portal, plan["z"]]]
            y, side = first, 0
            while y > design:
                points.append([plan["x_west"] + side * self.run, y, plan["z"]])
                y, side = y - self.floor, 1 - side
            last = points[-1]
            x_end = last[0] + (1 if side else -1) * (last[1] - design) / tan
            points.append([x_end, design, plan["z"]])
            self.decline_pts[name] = _rounded(points)
            self.decline_bottom[name] = float(self.p[f"decline.{token}.bottom_m"])
        self.surface_y = max(p[0][1] for p in self.decline_pts.values())

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
            obj = self.head(name, "polyline", pts[0])
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
            if top is None or bottom is None:
                # No published range: from the lowest level that names it to the surface.
                served = [e for lvl, e in self.levels.items()
                          if name in self.links(lvl, "link_air_intake") + self.links(lvl, "link_air_exhaust")]
                top, bottom = self.surface_y, min(served)
            top, bottom = float(top), float(bottom)
            section = self.attr(name, "section_m2")
            obj = self.head(name, "cylinder", [x, top, z])
            obj.update({"base": [x, bottom, z], "top": top,
                        "radius": math.sqrt(float(section) / math.pi), "section_m2": section,
                        "direction": self.attr(name, "direction")})
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

    def airway_link(self, airway, level):
        obj, e = self.built[airway], self.levels[level]
        x, bottom, z = obj["base"]
        return [[x, e, DRIVE_Z], [x, max(e, bottom), z]]

    # -- stopes and levels -------------------------------------------------

    def build_stopes(self):
        dx, dy, dz = STOPE_SIZE
        for name in self.of_kind("stope"):
            level = self.links(name, "link_level")[0]
            e = self.levels[level]
            x = STOPE_X[int(name.rsplit("-", 1)[1]) - 1]
            obj = self.head(name, "box", [x, e + dy / 2, 0.0])
            obj.update({"center": [x, e + dy / 2, 0.0], "size": [dx, dy, dz],
                        "level": self.tid(level), "draw_point": [x, e, dz / 2],
                        "routes": [self.tid(d) for d in self.links(name, "link_ore_route")]})
            self.built[name] = obj

    def build_levels(self):
        for level, e in self.levels.items():
            level_planned = self.planned(level)
            links = []
            for decline, point, planned in self.accesses(level):
                links.append({"to": self.tid(decline), "role": "access", "planned": planned,
                              "points": [[point[0], e, DRIVE_Z], point]})
            for stope in self.of_kind("stope"):
                if self.links(stope, "link_level") == [level]:
                    links.append({"to": self.tid(stope), "role": "crosscut", "planned": self.planned(stope),
                                  "points": [[self.built[stope]["draw_point"][0], e, DRIVE_Z],
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
                                  "points": [[x, e, DRIVE_Z], [x, e, PUMP_Z - PUMP_CHAMBER[2] / 2]]})
            # The drive spans the ore zone and every junction that exists with the level itself.
            xs = list(ORE_X) + [ln["points"][0][0] for ln in links if level_planned or not ln["planned"]]
            x_min, x_max = min(xs), max(xs)
            for ln in links:
                x = ln["points"][0][0]
                if not x_min <= x <= x_max:
                    ln["points"].insert(0, [min(max(x, x_min), x_max), e, DRIVE_Z])
            obj = self.head(level, "polyline", [x_min, e, DRIVE_Z])
            obj.update({"elevation": e, "role": self.attr(level, "role"),
                        "width": DRIVE_WIDTH, "height": DRIVE_HEIGHT,
                        "points": [[x_min, e, DRIVE_Z], [x_max, e, DRIVE_Z]],
                        "extent": [x_min, LEVEL_Z[0], x_max, LEVEL_Z[1]], "links": links})
            self.built[level] = obj

    # -- fans and pump stations --------------------------------------------

    def build_fans(self):
        for name in self.of_kind("main_fan"):
            parent = _short(self.attr(name, "_parents"))
            if self.kind(parent) == "shaft":
                size = FAN_SURFACE
                x, _, z = self.built[parent]["base"]
                center = [x - size[0], self.built[parent]["top"] + size[1] / 2, z]
            elif self.kind(parent) == "raise":
                size = FAN_UNDERGROUND
                x, _, z = self.built[parent]["base"]
                center = [x, self.built[parent]["top"] + size[1] / 2, z]
            else:
                # Underground installation: in the level's access to the decline it feeds.
                size = FAN_UNDERGROUND
                airway = self.tid(self.links(name, "link_airway")[0])
                a, b = next(ln["points"] for ln in self.built[parent]["links"] if ln["to"] == airway)[-2:]
                center = [(a[0] + b[0]) / 2, a[1] + size[1] / 2, (a[2] + b[2]) / 2]
            obj = self.head(name, "box", center)
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
                # Up a borehole to the level under the shaft, along that level, up the shaft, to the pond.
                level = self.airway_levels[PIPE_SHAFT][0]
                le = self.levels[level]
                sx, _, sz = self.built[PIPE_SHAFT]["base"]
                pond = self.pond_center(target)
                pipe += [[x, le, PUMP_Z], [x, le, DRIVE_Z]] + self.airway_link(PIPE_SHAFT, level)
                pipe += [[sx, self.surface_y, sz], [pond[0], self.surface_y, pond[1]]]
            obj = self.head(name, "box", center)
            obj.update({"center": center, "size": [dx, dy, dz], "elevation": e,
                        "sump": {"center": [x, e - SUMP_DEPTH / 2, PUMP_Z],
                                 "size": [volume / SUMP_DEPTH / sump_dz, SUMP_DEPTH, sump_dz]},
                        "discharges_to": self.tid(target), "pipe": _dedupe(pipe)})
            self.built[name] = obj

    # -- surface -----------------------------------------------------------

    def pond_center(self, name):
        index = self.of_kind("settling_pond").index(name)
        return [POND_CENTER[0] + (index - 0.5) * (POND_LENGTH + POND_GAP), POND_CENTER[1]]

    def build_surface_things(self):
        y = self.surface_y
        for name in self.of_kind("settling_pond"):
            cx, cz = self.pond_center(name)
            depth, area = float(self.attr(name, "depth_m")), float(self.attr(name, "area_m2"))
            center = [cx, y - depth / 2, cz]
            obj = self.head(name, "box", [cx, y, cz])
            obj.update({"center": center, "size": [POND_LENGTH, depth, area / POND_LENGTH]})
            self.built[name] = obj

        cx, cz = ROM_CENTER
        for name in self.of_kind("rom_stockpile"):
            obj = self.head(name, "cone", [cx, y + ROM_CONE[1], cz])
            obj.update({"base": [cx, y, cz], "radius": ROM_CONE[0], "height": ROM_CONE[1],
                        "reference_t": self.p["stockpile.start_t"],
                        "pad": _rect(cx, cz, *ROM_PAD), "dump": [ROM_DUMP[0], y, ROM_DUMP[1]]})
            self.built[name] = obj

        lines = self.of_kind("plant_line")
        dx, dy, dz = PLANT_LINE
        for index, name in enumerate(lines):
            x = PLANT_CENTER[0] + (index - (len(lines) - 1) / 2) * PLANT_PITCH
            center = [x, y + dy / 2, PLANT_CENTER[1]]
            obj = self.head(name, "box", center)
            obj.update({"center": center, "size": [dx, dy, dz]})
            self.built[name] = obj
        for name in self.of_kind("plant"):
            width = (len(lines) - 1) * PLANT_PITCH + dx + 20
            obj = self.head(name, "outline", [PLANT_CENTER[0], y + dy, PLANT_CENTER[1]])
            obj.update({"y": y, "footprint": _rect(PLANT_CENTER[0], PLANT_CENTER[1], width, dz + 20)})
            self.built[name] = obj

        # Tailings: on the true bearing from the mine, at a shortened distance.
        lat0, lon0 = _dms(self.attr("enterprise", "coordinates"))
        for name in self.of_kind("tailings_facility"):
            lat1, lon1 = _dms(self.attr(name, "coordinates"))
            north = math.radians(lat1 - lat0) * 6371000.0
            east = math.radians(lon1 - lon0) * 6371000.0 * math.cos(math.radians((lat0 + lat1) / 2))
            bearing = math.atan2(east, north)
            tx, tz = TSF_DISTANCE * math.sin(bearing), -TSF_DISTANCE * math.cos(bearing)
            dams = [d for d in TSF_ORDER if d in self.things]
            widths = {d: float(self.attr(d, "capacity_m3")) * TSF_VOLUME_SCALE / TSF_HEIGHT / TSF_DEPTH
                      for d in dams}
            total = sum(widths.values()) + TSF_GAP * (len(dams) - 1)
            x = tx - total / 2
            for dam in dams:
                cx = x + widths[dam] / 2
                obj = self.head(dam, "prism", [cx, y + TSF_HEIGHT, tz])
                obj.update({"footprint": _rect(cx, tz, widths[dam], TSF_DEPTH),
                            "bottom": y, "top": y + TSF_HEIGHT})
                self.built[dam] = obj
                x += widths[dam] + TSF_GAP
            obj = self.head(name, "outline", [tx, y + TSF_HEIGHT, tz])
            obj.update({"y": y, "footprint": _rect(tx, tz, total + 20, TSF_DEPTH + 20),
                        "bearing_deg": round(math.degrees(bearing), 1),
                        "true_distance": math.hypot(north, east), "drawn_distance": TSF_DISTANCE,
                        "volume_scale": TSF_VOLUME_SCALE})
            self.built[name] = obj
            self.tsf = (tx, tz, total)

    def build_mobile(self):
        y = self.surface_y
        rows = [self.of_kind("haul_truck"), self.of_kind("lhd"), self.of_kind("drill_rig")]
        slots, row = {}, 0
        for group in rows:
            for index, name in enumerate(group):
                slots[name] = (row + index // YARD_COLUMNS, index % YARD_COLUMNS)
            row += math.ceil(len(group) / YARD_COLUMNS)
        self.yard = (YARD_COLUMNS * YARD_PITCH, row * YARD_PITCH)
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
            obj = self.head(name, "box", center)
            obj.update({"center": center, "size": [length, height, width], "mobile": True})
            self.built[name] = obj

    # -- scenery -----------------------------------------------------------

    def build_scenery(self):
        y = self.surface_y
        tu2 = self.decline_pts["decline-tu2"]
        tu1 = self.decline_pts["decline-tu1"]
        pcx, floor_y, pcz = tu2[0]
        s = self.scenery
        s["old-pit"] = {"primitive": "frustum", "sourced": False, "base": [pcx, floor_y, pcz],
                        "radius_base": PIT_FLOOR_RADIUS, "top": y, "radius_top": PIT_RIM_RADIUS}
        self.pit = (pcx, pcz, floor_y)

        # Haul roads. TU2 climbs the pit wall on a spiral of constant grade, then both share one road.
        dump = [ROM_DUMP[0], y, ROM_DUMP[1]]
        apron = [tu1[0][0] + PORTAL_APRON, y, tu1[0][2]]
        s["road-tu1"] = {"primitive": "polyline", "sourced": False, "decline": self.tid("decline-tu1"),
                         "points": [tu1[0], apron, dump]}
        sweep = math.radians(PIT_RAMP_SWEEP_DEG)
        growth = math.log(PIT_RIM_RADIUS / PIT_FLOOR_RADIUS) / sweep
        ramp, steps = [tu2[0]], round(PIT_RAMP_SWEEP_DEG / PIT_RAMP_STEP_DEG)
        for i in range(steps + 1):
            turned = sweep * i / steps
            angle = math.radians(PIT_RAMP_EXIT_DEG) - sweep + turned
            r = PIT_FLOOR_RADIUS * math.exp(growth * turned)
            ry = floor_y + (r - PIT_FLOOR_RADIUS) / (PIT_RIM_RADIUS - PIT_FLOOR_RADIUS) * (y - floor_y)
            ramp.append([pcx + r * math.cos(angle), ry, pcz + r * math.sin(angle)])
        s["road-tu2"] = {"primitive": "polyline", "sourced": False, "decline": self.tid("decline-tu2"),
                         "points": ramp + [apron, dump]}
        s["yard"] = {"primitive": "outline", "sourced": False, "y": y,
                     "footprint": _rect(YARD_CENTER[0], YARD_CENTER[1], *self.yard)}

        # Water courses, placed from the published distances to the pit.
        reach = (PIT_RIM_RADIUS + RIVER_OFFSET) / math.sqrt(2)
        river_c = (pcz + reach) - (pcx - reach)            # the river is the line z = x + river_c
        stream_z = pcz + PIT_RIM_RADIUS + STREAM_OFFSET
        mouth = [stream_z + 5 - river_c, stream_z + 5]
        stream = [mouth, [pcx - 130, stream_z + 10], [pcx, stream_z], [pcx + PIT_RIM_RADIUS, stream_z - 15]]
        rest = STREAM_LENGTH - sum(math.dist(a, b) for a, b in zip(stream, stream[1:]))
        heading = math.radians(6.0)                       # the head of the stream runs east, 6 deg to the north
        stream.append([stream[-1][0] + rest * math.cos(heading), stream[-1][1] - rest * math.sin(heading)])
        outfall = stream[3]
        s["stream-volchevka"] = {"primitive": "polyline", "sourced": False,
                                 "points": [[px, y, pz] for px, pz in reversed(stream)]}
        intake = [-450.0, -450.0 + river_c]
        river = [[-600.0, -600.0 + river_c], intake, [-270.0, -270.0 + river_c - 15],
                 [pcx - reach, pcz + reach], mouth, [mouth[0] + 90, mouth[1] + 90]]
        s["river-sekisovka"] = {"primitive": "polyline", "sourced": False,
                                "points": [[px, y, pz] for px, pz in river]}
        for name, at in (("mon-volchevka", outfall), ("mon-sekisovka", intake)):
            obj = self.head(name, "marker", [at[0], y, at[1]])
            self.built[name] = obj

        # Process lines on the surface.
        lines = self.of_kind("plant_line")
        row = (len(lines) - 1) * PLANT_PITCH + PLANT_LINE[0]
        west, east = PLANT_CENTER[0] - row / 2, PLANT_CENTER[0] + row / 2
        south, north = PLANT_CENTER[1] + PLANT_LINE[2] / 2, PLANT_CENTER[1] - PLANT_LINE[2] / 2
        lower = self.pond_center("pond-lower")
        tx, tz, total = self.tsf
        header_z = tz + TSF_DEPTH / 2 + 30
        bypass = pcx + PIT_RIM_RADIUS + 40
        plan = {
            "conveyor": [[ROM_CENTER[0] - ROM_PAD[0] / 2, ROM_CENTER[1]], [east, south + 15], [west, south + 15]],
            "pipeline-tailings": [[PLANT_CENTER[0], north], [PLANT_CENTER[0], north - 40],
                                  [tx - total / 2, header_z], [tx + total / 2, header_z]],
            "pipeline-water-supply": [lower, [lower[0], lower[1] - 35], [-280.0, -330.0],
                                      [east, PLANT_CENTER[1]]],
            "pipeline-discharge": [lower, [bypass, -120.0], [bypass, 300.0], outfall],
            "pipeline-intake": [intake, [west - 33, -150.0], [west - 33, PLANT_CENTER[1]],
                                [west, PLANT_CENTER[1]]],
        }
        for name, pts in plan.items():
            s[name] = {"primitive": "polyline", "sourced": False, "points": [[px, y, pz] for px, pz in pts]}

        # Backfilled blocks of the mined-out levels, on the stope grid.
        dx, dy, dz = STOPE_SIZE
        for level, e in self.levels.items():
            if self.attr(level, "role") == "mined_out":
                for index, x in enumerate(STOPE_X):
                    s[f"backfill-{level.split('-', 1)[1]}-{index + 1}"] = {
                        "primitive": "box", "sourced": False, "level": self.tid(level),
                        "center": [x, e + dy / 2, 0.0], "size": [dx, dy, dz]}

    # -- assembly ----------------------------------------------------------

    def document(self):
        self.decline_frame()
        self.build_declines()
        self.build_airways()
        self.build_stopes()
        self.build_levels()
        self.build_fans()
        self.build_pump_stations()
        self.build_surface_things()
        self.build_mobile()
        self.build_scenery()

        missing = [n for n in self.order if self.kind(n) not in ABSTRACT_KINDS and n not in self.built]
        if missing:
            raise ValueError(f"no geometry for {missing}")
        objects = {self.tid(n): self.built[n] for n in self.order if n in self.built}
        body = _normalise({"scenery": self.scenery, "objects": objects})

        points = [p for item in list(body["scenery"].values()) + list(body["objects"].values())
                  for p in item_points(item)]
        low = [min(p[i] for p in points) for i in range(3)]
        high = [max(p[i] for p in points) for i in range(3)]
        x0, z0 = (math.floor((low[i] - 40) / 10) * 10 for i in (0, 2))
        x1, z1 = (math.ceil((high[i] + 40) / 10) * 10 for i in (0, 2))
        surface = {"primitive": "outline", "sourced": False, "y": self.surface_y,
                   "footprint": [[x0, z0], [x1, z0], [x1, z1], [x0, z1]]}
        return _normalise({
            "_schema": SCHEMA,
            "namespace": self.ns,
            "frame": {"x": "east", "y": "up, elevation m a.s.l.", "z": "south", "unit": "m",
                      "surface": self.surface_y,
                      "origin": "x = 0 is the axis of shaft VS1, y = 0 is sea level, z = 0 is the ore zone"},
            "bounds": {"min": [x0, low[1], z0], "max": [x1, high[1], z1]},
            "scenery": {"surface": surface, **body["scenery"]},
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
    if prim == "frustum":
        x, y, z = item["base"]
        r = max(item["radius_base"], item["radius_top"])
        return [[x + i * r, yy, z + k * r] for i in (-1, 1) for k in (-1, 1) for yy in (y, item["top"])]
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

def build(params=None, registry=None):
    """Return the geometry document (the content of geometry.json) as a dict."""
    params = _read_json(PARAMS_PATH) if params is None else params
    registry = _read_json(REGISTRY_PATH) if registry is None else registry
    return _Builder(params, registry).document()


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
