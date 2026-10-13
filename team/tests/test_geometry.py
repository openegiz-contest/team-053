"""Tests for sekis/geometry.py and team/model/geometry.json (spec section 4.2)."""

import json
import math
import sys
import tempfile
import unittest
from itertools import combinations
from pathlib import Path

TEAM = Path(__file__).resolve().parent.parent
if str(TEAM) not in sys.path:
    sys.path.insert(0, str(TEAM))

from sekis import geometry  # noqa: E402

MODEL = TEAM / "model"
NS = "kz.sekis"

# Kinds that the spec places in the scene (4.2, 4.3); the other five kinds are abstract.
POSITIONED_KINDS = {
    "level", "stope", "decline", "shaft", "raise", "main_fan", "pump_station", "settling_pond",
    "monitoring_point", "haul_truck", "lhd", "drill_rig", "rom_stockpile", "plant", "plant_line",
    "tailings_facility", "tailings_dam",
}
PRIMITIVES = {"box", "cylinder", "frustum", "cone", "prism", "polyline", "outline", "marker"}
SLOPE_TOLERANCE_DEG = 0.2
TOUCH = 0.15          # two rounded coordinates describe the same point


def load_json(path):
    return json.loads(path.read_bytes().decode("utf-8"))


def tid(name):
    return f"{NS}:{name}"


def segments(points):
    return list(zip(points, points[1:]))


def point_segment(p, a, b):
    ab = [b[i] - a[i] for i in range(3)]
    length2 = sum(c * c for c in ab)
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, sum((p[i] - a[i]) * ab[i] for i in range(3)) / length2))
    return math.dist(p, [a[i] + ab[i] * t for i in range(3)])


def point_polyline(p, points):
    return min(point_segment(p, a, b) for a, b in segments(points))


def segment_segment(a, b, c, d, steps=200):
    """Smallest distance between two 3D segments (sampled; good to a few centimetres here)."""
    best = min(point_segment(a, c, d), point_segment(b, c, d), point_segment(c, a, b), point_segment(d, a, b))
    for i in range(1, steps):
        p = [a[k] + (b[k] - a[k]) * i / steps for k in range(3)]
        best = min(best, point_segment(p, c, d))
    return best


def polyline_polyline(p, q):
    return min(segment_segment(a, b, c, d) for a, b in segments(p) for c, d in segments(q))


def box_limits(item):
    c, s = item["center"], item["size"]
    return [c[i] - s[i] / 2 for i in range(3)], [c[i] + s[i] / 2 for i in range(3)]


def point_box(p, item):
    """Distance from a point to an axis-aligned box (0 inside)."""
    low, high = box_limits(item)
    return math.sqrt(sum(max(low[i] - p[i], 0.0, p[i] - high[i]) ** 2 for i in range(3)))


def segment_enters_box(a, b, item, shrink=0.2):
    """True when the segment passes through the inside of the box."""
    low, high = box_limits(item)
    t0, t1 = 0.0, 1.0
    for i in range(3):
        lo, hi, d = low[i] + shrink, high[i] - shrink, b[i] - a[i]
        if d == 0:
            if not lo < a[i] < hi:
                return False
            continue
        ta, tb = sorted(((lo - a[i]) / d, (hi - a[i]) / d))
        t0, t1 = max(t0, ta), min(t1, tb)
        if t0 >= t1:
            return False
    return True


def boxes_overlap(a, b):
    la, ha = box_limits(a)
    lb, hb = box_limits(b)
    return all(la[i] < hb[i] and lb[i] < ha[i] for i in range(3))


def axis(item):
    x, bottom, z = item["base"]
    return [x, bottom, z], [x, item["top"], z]


class GeometryCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.params = {k: v["value"] for k, v in load_json(MODEL / "params.json").items()
                      if isinstance(v, dict) and "value" in v}
        cls.registry = load_json(MODEL / "registry.json")
        cls.things = {t["thingId"]: t for t in cls.registry["things"]}
        cls.raw = (MODEL / "geometry.json").read_bytes()
        cls.doc = json.loads(cls.raw.decode("utf-8"))
        cls.objects = cls.doc["objects"]
        cls.scenery = cls.doc["scenery"]
        cls.geo = geometry.Geometry(cls.doc)
        cls.surface = cls.doc["frame"]["surface"]

    def attr(self, thing_id, key, default=None):
        return self.things[thing_id]["attributes"].get(key, default)

    def state(self, thing_id):
        feature = self.things[thing_id]["features"].get("state")
        return feature["properties"]["value"] if feature else None

    def of_kind(self, *kinds):
        return {t: o for t, o in self.objects.items() if o["kind"] in kinds}

    def links(self, level_id, role=None):
        return [ln for ln in self.objects[level_id]["links"] if role is None or ln["role"] == role]


class FileTest(GeometryCase):
    def test_regenerating_gives_the_same_bytes(self):
        first = geometry.dumps(geometry.build()).encode("utf-8")
        second = geometry.dumps(geometry.build()).encode("utf-8")
        self.assertEqual(first, second)
        self.assertEqual(first, self.raw, "geometry.json is stale: run `python -m sekis.geometry` in team/")

    def test_write_produces_the_committed_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = geometry.write(Path(tmp) / "geometry.json")
            self.assertEqual(path.read_bytes(), self.raw)

    def test_file_is_lf_utf8_without_bom(self):
        self.assertFalse(self.raw.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\r", self.raw)
        self.assertTrue(self.raw.endswith(b"}\n"))
        self.raw.decode("ascii")

    def test_top_level_shape(self):
        self.assertEqual(list(self.doc), ["_schema", "namespace", "frame", "bounds", "scenery", "objects"])
        self.assertEqual(self.doc["namespace"], NS)
        self.assertEqual((self.doc["frame"]["x"], self.doc["frame"]["z"], self.doc["frame"]["unit"]),
                         ("east", "south", "m"))

    def test_numbers_are_rounded_to_a_decimetre(self):
        def walk(value, key, path):
            if isinstance(value, bool) or isinstance(value, str):
                return
            if isinstance(value, (int, float)):
                if key not in geometry.EXACT_KEYS:
                    self.assertEqual(value, round(value, 1), path)
                return
            if isinstance(value, dict):
                for k, v in value.items():
                    walk(v, k, f"{path}/{k}")
            else:
                for v in value:
                    walk(v, key, path)

        walk(self.objects, None, "objects")
        walk(self.scenery, None, "scenery")

    def test_everything_lies_inside_the_bounds(self):
        low, high = self.doc["bounds"]["min"], self.doc["bounds"]["max"]
        for name, item in list(self.objects.items()) + list(self.scenery.items()):
            for p in geometry.item_points(item):
                for i in range(3):
                    self.assertTrue(low[i] <= p[i] <= high[i], f"{name} {p}")


class RegistryTest(GeometryCase):
    def test_every_positioned_thing_is_present_and_no_id_is_unknown(self):
        expected = [t for t in self.things if self.attr(t, "kind") in POSITIONED_KINDS]
        self.assertEqual(list(self.objects), expected)
        self.assertEqual(len(expected), 91)
        absent = {self.attr(t, "kind") for t in self.things if t not in self.objects}
        self.assertEqual(absent, {"enterprise", "mine", "water_system", "scenario_control", "advisor"})

    def test_common_keys(self):
        for thing_id, item in self.objects.items():
            self.assertEqual(list(item)[:5], ["kind", "primitive", "sourced", "planned", "anchor"], thing_id)
            self.assertEqual(item["kind"], self.attr(thing_id, "kind"), thing_id)
            self.assertIn(item["primitive"], PRIMITIVES, thing_id)
            self.assertIsInstance(item["sourced"], bool, thing_id)
            self.assertEqual(item["planned"], self.state(thing_id) == "planned", thing_id)
            self.assertEqual(len(item["anchor"]), 3, thing_id)
        for name, item in self.scenery.items():
            self.assertIn(item["primitive"], PRIMITIVES, name)
            self.assertIsInstance(item["sourced"], bool, name)

    def test_planned_things_are_flagged(self):
        planned = {t for t, o in self.objects.items() if o["planned"]}
        for name in ("shaft-vs3", "raise-vpv", "fan-vpv", "fan-vs3", "ps-m200", "plant-line-4", "plant-line-5",
                     "plant-line-6", "tsf-cell5", "lvl-m100", "lvl-m300", "stp-m100-1"):
            self.assertIn(tid(name), planned)
        self.assertNotIn(tid("truck-12"), planned)      # parked, not planned

    def test_sourced_flags(self):
        for name in ("lvl-p150", "decline-tu1", "decline-tu2", "shaft-vs1", "shaft-vs2", "raise-vpv",
                     "raise-vhv-tu1", "raise-vhv-tu2", "ps-p150", "ps-m200", "pond-upper", "tailings"):
            self.assertTrue(self.objects[tid(name)]["sourced"], name)
        for name in ("raise-vhv-exhaust", "shaft-vs3", "stp-p150-1", "fan-vs1", "ps-m050", "truck-01",
                     "plant-line-1", "rom-stockpile", "tsf-dam4", "mon-volchevka"):
            self.assertFalse(self.objects[tid(name)]["sourced"], name)

    def test_references_resolve(self):
        for thing_id, item in self.objects.items():
            refs = [ln["to"] for ln in item.get("links", [])] + item.get("routes", []) + item.get("airway", [])
            refs += [item[k] for k in ("level", "discharges_to") if k in item]
            refs += [n["level"] for n in item.get("nodes", []) if "level" in n]
            for ref in refs:
                self.assertIn(ref, self.objects, f"{thing_id} -> {ref}")
        for name, item in self.scenery.items():
            for key in ("level", "decline"):
                if key in item:
                    self.assertIn(item[key], self.objects, name)


class DeclineTest(GeometryCase):
    def declines(self):
        return self.of_kind("decline")

    def test_every_segment_keeps_the_slope(self):
        slope = self.params["decline.slope_deg"]
        self.assertEqual(slope, 8)
        for thing_id, item in self.declines().items():
            self.assertEqual(item["slope_deg"], slope)
            for a, b in segments(item["points"]):
                angle = math.degrees(math.atan2(a[1] - b[1], math.hypot(b[0] - a[0], b[2] - a[2])))
                self.assertAlmostEqual(angle, slope, delta=SLOPE_TOLERANCE_DEG, msg=f"{thing_id} {a} {b}")

    def test_polyline_spans_portal_and_bottom(self):
        for thing_id, item in self.declines().items():
            token = item["token"]
            portal = self.params[f"decline.{token}.portal_m"]
            design = self.params[f"decline.{token}.design_bottom_m"]
            self.assertEqual(portal, self.attr(thing_id, "portal_elevation_m"))
            self.assertEqual(design, self.attr(thing_id, "design_bottom_m"))
            ys = [p[1] for p in item["points"]]
            self.assertEqual((ys[0], ys[-1]), (portal, design), thing_id)
            self.assertEqual((item["portal_elevation"], item["design_bottom"]), (portal, design))
            self.assertEqual(ys, sorted(ys, reverse=True))
            self.assertEqual(len(set(ys)), len(ys))
            self.assertEqual(item["anchor"], item["points"][0])
            self.assertEqual(item["bottom_elevation"], self.params[f"decline.{token}.bottom_m"])
            self.assertEqual(item["bottom_at"][1], item["bottom_elevation"])
            self.assertLess(point_polyline(item["bottom_at"], item["points"]), TOUCH)

    def test_portals_stand_on_the_surface_and_on_the_pit_floor(self):
        pit = self.scenery["old-pit"]
        self.assertEqual(self.objects[tid("decline-tu1")]["points"][0][1], self.surface)
        self.assertEqual(self.objects[tid("decline-tu2")]["points"][0], pit["base"])
        self.assertEqual(pit["top"], self.surface)

    def test_zigzag_turns_at_every_floor_height(self):
        floor = self.params["level.floor_height_m"]
        for thing_id, item in self.declines().items():
            inner = item["points"][1:-1]
            self.assertEqual([p[1] % floor for p in inner], [0] * len(inner), thing_id)
            self.assertEqual({a[1] - b[1] for a, b in segments(item["points"][1:])}, {floor})
            self.assertEqual(len({p[2] for p in item["points"]}), 1, "one vertical plane")
            xs = [p[0] for p in item["points"][1:]]
            self.assertEqual(len(set(xs)), 2, thing_id)
            self.assertTrue(all(a != b for a, b in zip(xs, xs[1:])), "turns alternate")

    def test_lengths(self):
        sin = math.sin(math.radians(self.params["decline.slope_deg"]))
        factor = self.params["decline.length_factor"]
        for thing_id, item in self.declines().items():
            drop = item["portal_elevation"] - item["design_bottom"]
            built = item["portal_elevation"] - item["bottom_elevation"]
            self.assertAlmostEqual(item["length"], geometry.polyline_length(item["points"]), delta=0.06)
            self.assertAlmostEqual(item["length"], drop / sin, delta=drop / sin * 0.001)
            self.assertAlmostEqual(item["built_length"], built / sin, delta=built / sin * 0.001)
            self.assertEqual(item["length_factor"], factor)
            # The registry length is the built polyline times the allowance for curves and bays.
            self.assertAlmostEqual(item["built_length"] * factor, self.attr(thing_id, "length_m"), delta=2.0)
            self.assertAlmostEqual(item["width"] * item["height"], self.attr(thing_id, "section_m2"), delta=0.01)
            self.assertEqual(item["section_m2"], self.attr(thing_id, "section_m2"))

    def test_passing_bays_every_25_m_of_depth(self):
        bay = self.params["decline.bay_spacing_vm"]
        sin = math.sin(math.radians(self.params["decline.slope_deg"]))
        for thing_id, item in self.declines().items():
            nodes = item["nodes"]
            portal, design = item["portal_elevation"], item["design_bottom"]
            expected = [portal] + [e for e in range(int(portal) - 1, int(design) - 1, -1) if e % bay == 0]
            self.assertEqual([n["elevation"] for n in nodes], expected, thing_id)
            self.assertEqual(nodes[0]["type"], "portal")
            self.assertEqual(nodes[0]["chainage"], 0)
            for a, b in segments(nodes):
                if a["type"] != "portal":
                    self.assertEqual(a["elevation"] - b["elevation"], bay)
                self.assertAlmostEqual(b["chainage"] - a["chainage"], (a["elevation"] - b["elevation"]) / sin,
                                       delta=0.3)
            for n in nodes:
                self.assertEqual(n["at"][1], n["elevation"])
                self.assertLess(point_polyline(n["at"], item["points"]), TOUCH)
                self.assertEqual(n["planned"], n["elevation"] < item["bottom_elevation"])
                self.assertIn(n["type"], {"portal", "bay", "turn", "access"})
                if n["elevation"] % self.params["level.floor_height_m"]:
                    self.assertIn(n["type"], {"portal", "bay"})

    def test_passing_bays_function(self):
        for thing_id, item in self.declines().items():
            bays = self.geo.passing_bays(thing_id)
            self.assertEqual(bays[0]["type"], "portal")
            self.assertEqual(bays[-1]["elevation"], item["bottom_elevation"])
            self.assertEqual([b["chainage"] for b in bays], sorted(b["chainage"] for b in bays))
            for b in bays:
                self.assertEqual(b["at"], self.geo.decline_point(thing_id, elevation=b["elevation"]))
                self.assertAlmostEqual(b["chainage"], self.geo.decline_chainage(thing_id, b["elevation"]))
            deep = self.geo.passing_bays(thing_id, bottom=item["design_bottom"])
            self.assertEqual([b["elevation"] for b in deep], [n["elevation"] for n in item["nodes"]])
        tu2 = self.geo.passing_bays("tu2")
        self.assertEqual((tu2[-1]["elevation"], tu2[-1]["type"]), (-34, "bottom"))
        self.assertEqual(tu2[-2]["elevation"], -25)
        tu1 = self.geo.passing_bays("decline-tu1")
        self.assertEqual((tu1[-1]["elevation"], tu1[-1]["type"]), (-50, "access"))
        self.assertEqual(len(tu1), 1 + (425 + 50) // 25 + 1)
        self.assertEqual(geometry.passing_bays("tu1"), tu1)

    def test_point_by_distance_and_by_elevation(self):
        for thing_id, item in self.declines().items():
            pts = item["points"]
            self.assertEqual(self.geo.decline_point(thing_id, distance=0), tuple(pts[0]))
            self.assertEqual(self.geo.decline_point(thing_id, elevation=item["portal_elevation"]), tuple(pts[0]))
            self.assertEqual(self.geo.decline_point(thing_id, elevation=item["design_bottom"]), tuple(pts[-1]))
            total = self.geo.decline_length(thing_id)
            self.assertAlmostEqual(total, item["length"], delta=0.06)
            previous = None
            for i in range(0, 201):
                d = total * i / 200
                p = self.geo.decline_point(thing_id, distance=d)
                self.assertLess(point_polyline(p, pts), 1e-6)
                self.assertAlmostEqual(self.geo.decline_chainage(thing_id, p[1]), d, delta=1e-6)
                self.assertAlmostEqual(self.geo.decline_elevation(thing_id, d), p[1])
                q = self.geo.decline_point(thing_id, elevation=p[1])
                self.assertLess(math.dist(p, q), 1e-6)
                if previous:
                    self.assertLessEqual(math.dist(p, previous), total / 200 + 1e-6)
                    self.assertLess(p[1], previous[1])
                previous = p
            with self.assertRaises(ValueError):
                self.geo.decline_point(thing_id)
            with self.assertRaises(ValueError):
                self.geo.decline_point(thing_id, distance=1, elevation=1)
            with self.assertRaises(ValueError):
                self.geo.decline_point(thing_id, distance=total + 1)
            with self.assertRaises(ValueError):
                self.geo.decline_point(thing_id, elevation=item["portal_elevation"] + 1)
        self.assertEqual(geometry.decline_point("tu1", elevation=0), self.geo.decline_point("tu1", elevation=0))


class LevelTest(GeometryCase):
    def test_level_drives_lie_on_their_elevation(self):
        low, high = geometry.ORE_X
        for thing_id, item in self.of_kind("level").items():
            e = self.attr(thing_id, "elevation_m")
            self.assertEqual(item["elevation"], e)
            self.assertEqual([p[1] for p in item["points"]], [e, e], thing_id)
            (x0, _, z0), (x1, _, z1) = item["points"]
            self.assertEqual(z0, z1)
            self.assertLessEqual(x0, low)
            self.assertGreaterEqual(x1, high)
            for link in item["links"]:
                start = link["points"][0]
                self.assertEqual((start[1], start[2]), (e, z0), f"{thing_id} -> {link['to']}")
                self.assertTrue(x0 <= start[0] <= x1, f"{thing_id} -> {link['to']} leaves the drive")
                self.assertIn(link["role"], {"access", "crosscut", "airway", "chamber"})
            self.assertEqual(len({ln["to"] for ln in item["links"]}), len(item["links"]))

    def test_level_accesses_meet_the_declines_at_the_turns(self):
        for thing_id, item in self.of_kind("level").items():
            accesses = {ln["to"]: ln for ln in self.links(thing_id, "access")}
            for decline in self.attr(thing_id, "link_declines"):
                self.assertIn(decline, accesses, f"{thing_id} has no access to {decline}")
            for decline, link in accesses.items():
                polyline = self.objects[decline]["points"]
                end = link["points"][-1]
                self.assertEqual(end[1], item["elevation"])
                self.assertLess(point_polyline(end, polyline), TOUCH)
                if thing_id in self.attr(decline, "link_levels"):
                    self.assertIn(end, polyline[1:], f"{thing_id}: access to {decline} is not at a turn")
                    self.assertEqual(link["planned"],
                                     item["planned"] or item["elevation"] < self.objects[decline]["bottom_elevation"])
                if decline not in self.attr(thing_id, "link_declines"):
                    self.assertTrue(link["planned"], "an access the registry does not know is design only")

    def test_decline_levels_have_an_access_node(self):
        for decline, item in self.of_kind("decline").items():
            by_level = {n["level"]: n for n in item["nodes"] if n["type"] == "access"}
            for level in self.attr(decline, "link_levels"):
                self.assertIn(level, by_level)
                self.assertEqual(by_level[level]["elevation"], self.attr(level, "elevation_m"))
                link = next(ln for ln in self.links(level, "access") if ln["to"] == decline)
                self.assertEqual(link["points"][-1], by_level[level]["at"])

    def test_a_working_level_has_no_planned_drive(self):
        for thing_id, item in self.of_kind("level").items():
            if not item["planned"]:
                x0, x1 = item["points"][0][0], item["points"][1][0]
                live = [ln["points"][0][0] for ln in item["links"] if not ln["planned"]]
                self.assertIn(x0, live + [geometry.ORE_X[0]])
                self.assertIn(x1, live + [geometry.ORE_X[1]])


class StopeTest(GeometryCase):
    def test_stopes_sit_on_their_level(self):
        for thing_id, item in self.of_kind("stope").items():
            level = self.attr(thing_id, "link_level")
            e = self.attr(level, "elevation_m")
            self.assertEqual(item["level"], level)
            self.assertEqual(item["center"][1] - item["size"][1] / 2, e, thing_id)
            self.assertEqual(item["draw_point"][1], e)
            self.assertEqual(item["size"], list(geometry.STOPE_SIZE))
            self.assertLess(item["center"][1] + item["size"][1] / 2, e + self.params["level.floor_height_m"])
            self.assertEqual(item["routes"], self.attr(thing_id, "link_ore_route"))
            link = next(ln for ln in self.links(level, "crosscut") if ln["to"] == thing_id)
            self.assertEqual(link["points"][-1], item["draw_point"])
            self.assertLess(point_box(item["draw_point"], item), TOUCH)

    def test_three_stopes_per_level_inside_the_ore_zone(self):
        per_level = {}
        for thing_id, item in self.of_kind("stope").items():
            per_level.setdefault(item["level"], []).append(item)
            low, high = box_limits(item)
            self.assertGreaterEqual(low[0], geometry.ORE_X[0])
            self.assertLessEqual(high[0], geometry.ORE_X[1])
        self.assertEqual({len(v) for v in per_level.values()}, {3})

    def test_blocks_do_not_overlap(self):
        boxes = dict(self.of_kind("stope"))
        boxes.update({k: v for k, v in self.scenery.items() if k.startswith("backfill-")})
        for (a, box_a), (b, box_b) in combinations(boxes.items(), 2):
            self.assertFalse(boxes_overlap(box_a, box_b), f"{a} / {b}")


class AirwayTest(GeometryCase):
    def airways(self):
        return self.of_kind("shaft", "raise")

    def test_shafts_and_raises_span_their_elevation_ranges(self):
        for thing_id, item in self.airways().items():
            top, bottom = self.attr(thing_id, "top_elevation_m"), self.attr(thing_id, "bottom_elevation_m")
            if top is None:
                # Not published: from the lowest level it serves to the surface, and flagged.
                served = [self.attr(t, "elevation_m") for t in self.things
                          if self.attr(t, "kind") == "level" and self.attr(t, "link_air_exhaust") == thing_id]
                top, bottom = self.surface, min(served)
                self.assertFalse(item["sourced"])
                self.assertEqual(thing_id, tid("raise-vhv-exhaust"))
            self.assertEqual((item["top"], item["base"][1]), (top, bottom), thing_id)
            self.assertEqual(item["anchor"], [item["base"][0], top, item["base"][2]])
            self.assertEqual(item["section_m2"], self.attr(thing_id, "section_m2"))
            self.assertAlmostEqual(item["radius"], math.sqrt(item["section_m2"] / math.pi), delta=0.06)
            self.assertEqual(item["direction"], self.attr(thing_id, "direction"))

    def test_shaft_collars_are_on_the_surface(self):
        for thing_id, item in self.of_kind("shaft").items():
            self.assertEqual(item["top"], self.surface, thing_id)

    def test_airways_connect_the_levels_they_pass(self):
        levels = self.of_kind("level")
        for thing_id, item in self.airways().items():
            bottom, top = item["base"][1], item["top"]
            linked = {}
            for level_id, level in levels.items():
                for link in self.links(level_id, "airway"):
                    if link["to"] == thing_id:
                        linked[level_id] = link
            self.assertTrue(linked, f"{thing_id} is connected to no level")
            for level_id, level in levels.items():
                if bottom <= level["elevation"] <= top:
                    self.assertIn(level_id, linked, f"{thing_id} passes {level_id} without a connection")
            for level_id, link in linked.items():
                end = link["points"][-1]
                self.assertEqual((end[0], end[2]), (item["base"][0], item["base"][2]))
                self.assertTrue(bottom <= end[1] <= top, f"{thing_id} / {level_id}")
                below = item.get("planned_below", -math.inf)
                self.assertEqual(link["planned"], item["planned"] or levels[level_id]["planned"]
                                 or levels[level_id]["elevation"] < below, f"{thing_id} / {level_id}")

    def test_exhaust_serves_every_level(self):
        for level_id in self.of_kind("level"):
            exhaust = self.attr(level_id, "link_air_exhaust")
            self.assertIn(exhaust, [ln["to"] for ln in self.links(level_id, "airway")])

    def test_planned_below_marks_the_undeveloped_depth(self):
        developed = min(self.attr(t, "elevation_m") for t in self.of_kind("level") if self.state(t) != "planned")
        self.assertEqual(developed, -50)
        expected = {"raise-vhv-tu1": -50, "raise-vhv-tu2": 0, "raise-vhv-exhaust": -50}
        for thing_id, item in self.airways().items():
            self.assertEqual(item.get("planned_below"), expected.get(thing_id.split(":")[1]), thing_id)


class ClearanceTest(GeometryCase):
    """Nothing runs through anything else."""

    def test_declines_do_not_meet_each_other(self):
        a, b = (self.objects[tid(n)]["points"] for n in ("decline-tu1", "decline-tu2"))
        self.assertGreater(polyline_polyline(a, b), 25.0)

    def test_declines_keep_clear_of_shafts_and_raises(self):
        for decline, item in self.of_kind("decline").items():
            for airway, shaft in self.of_kind("shaft", "raise").items():
                gap = polyline_polyline(item["points"], list(axis(shaft)))
                self.assertGreater(gap, 15.0, f"{decline} / {airway}: {gap:.1f} m")

    def test_declines_keep_clear_of_level_workings(self):
        for decline, item in self.of_kind("decline").items():
            for level_id, level in self.of_kind("level").items():
                self.assertGreater(polyline_polyline(item["points"], level["points"]), 15.0)
                for link in level["links"]:
                    if link["to"] == decline:
                        continue
                    gap = polyline_polyline(item["points"], link["points"])
                    self.assertGreater(gap, 15.0, f"{decline} / {level_id} -> {link['to']}: {gap:.1f} m")

    def test_shafts_and_raises_keep_apart(self):
        for (a, item_a), (b, item_b) in combinations(self.of_kind("shaft", "raise").items(), 2):
            gap = math.dist((item_a["base"][0], item_a["base"][2]), (item_b["base"][0], item_b["base"][2]))
            self.assertGreater(gap, 15.0, f"{a} / {b}")

    def test_nothing_cuts_through_a_block(self):
        blocks = dict(self.of_kind("stope"))
        blocks.update({k: v for k, v in self.scenery.items() if k.startswith("backfill-")})
        lines = {}
        for thing_id, item in self.objects.items():
            if item["kind"] in ("shaft", "raise"):
                lines[thing_id] = list(axis(item))
            elif item["kind"] in ("level", "decline"):
                lines[thing_id] = item["points"]
                for link in item.get("links", []):
                    lines[f"{thing_id} -> {link['to']}"] = link["points"]
            elif item["kind"] == "pump_station":
                lines[f"{thing_id} pipe"] = item["pipe"]
        for name, points in lines.items():
            for a, b in segments(points):
                for block, box in blocks.items():
                    self.assertFalse(segment_enters_box(a, b, box), f"{name} passes through {block}")

    def test_vertical_airways_miss_the_blocks_in_the_long_section(self):
        blocks = [box_limits(item) for item in self.of_kind("stope").values()]
        columns = {t: (o["base"][0], o["base"][1], o["top"]) for t, o in self.of_kind("shaft", "raise").items()}
        for thing_id, item in self.of_kind("pump_station").items():
            columns[thing_id] = (item["center"][0], item["elevation"], item["elevation"] + 1)
        for thing_id, (x, bottom, top) in columns.items():
            for low, high in blocks:
                crosses = low[0] - 5 < x < high[0] + 5 and bottom < high[1] and top > low[1]
                self.assertFalse(crosses, f"{thing_id} at x = {x} runs over a stope in the x-y projection")

    def test_nothing_hangs_in_the_old_pit(self):
        pit = self.scenery["old-pit"]
        cx, floor, cz = pit["base"]

        def clearance(p):
            wall = pit["radius_base"] + (min(max(p[1], floor), pit["top"]) - floor) \
                   / (pit["top"] - floor) * (pit["radius_top"] - pit["radius_base"])
            return math.hypot(p[0] - cx, p[2] - cz) - wall

        def samples(points, n=40):
            for a, b in segments(points):
                for i in range(n + 1):
                    yield [a[k] + (b[k] - a[k]) * i / n for k in range(3)]

        for thing_id, item in self.objects.items():
            if thing_id == tid("decline-tu2"):
                continue   # its portal is the centre of the pit floor
            if item["kind"] in ("shaft", "raise"):
                lines = [list(axis(item))]
            elif item["primitive"] == "polyline":
                lines = [item["points"]] + [ln["points"] for ln in item.get("links", [])]
            else:
                lines = [geometry.item_points(item) + item.get("pipe", [])]
            for line in lines:
                for p in samples(line) if len(line) > 1 else line:
                    if floor <= p[1] <= pit["top"]:
                        self.assertGreater(clearance(p), 5.0, f"{thing_id} at {p}")

    def test_pit_ramp_lies_on_the_pit_wall(self):
        pit = self.scenery["old-pit"]
        cx, floor, cz = pit["base"]
        road = self.scenery["road-tu2"]["points"]
        self.assertEqual(road[0], pit["base"])
        ramp = [p for p in road if math.hypot(p[0] - cx, p[2] - cz) <= pit["radius_top"] + TOUCH][1:]
        self.assertEqual((ramp[0][1], ramp[-1][1]), (floor, self.surface))
        for p in ramp:
            wall = pit["radius_base"] + (p[1] - floor) / (pit["top"] - floor) \
                   * (pit["radius_top"] - pit["radius_base"])
            self.assertAlmostEqual(math.hypot(p[0] - cx, p[2] - cz), wall, delta=0.3)
        for a, b in segments(ramp):
            grade = math.degrees(math.atan2(b[1] - a[1], math.hypot(b[0] - a[0], b[2] - a[2])))
            self.assertAlmostEqual(grade, 8.0, delta=0.5)


class ConnectionTest(GeometryCase):
    """Nothing floats: every underground object hangs on the network that reaches the surface."""

    def touches(self, point, target):
        if target["primitive"] == "polyline":
            return point_polyline(point, target["points"]) < TOUCH
        if target["primitive"] == "cylinder":
            return point_segment(point, *axis(target)) < TOUCH
        return point_box(point, target) < TOUCH

    def test_links_end_on_their_target(self):
        for level_id, level in self.of_kind("level").items():
            for link in level["links"]:
                self.assertTrue(self.touches(link["points"][-1], self.objects[link["to"]]),
                                f"{level_id} -> {link['to']} ends in the rock")
                for a, b in segments(link["points"]):
                    self.assertGreater(math.dist(a, b), 0)

    def test_underground_network_is_one_piece(self):
        edges = {}

        def join(a, b):
            edges.setdefault(a, set()).add(b)
            edges.setdefault(b, set()).add(a)

        for level_id, level in self.of_kind("level").items():
            for link in level["links"]:
                join(level_id, link["to"])
        for fan_id, fan in self.of_kind("main_fan").items():
            parent = self.attr(fan_id, "_parents")
            target = self.objects[parent]
            if target["kind"] == "level":
                near = min(point_polyline(fan["center"], ln["points"]) for ln in target["links"])
            else:
                near = point_segment(fan["center"], *axis(target))
            self.assertLess(near, 12.0, f"{fan_id} is away from {parent}")
            join(fan_id, parent)
        seen, queue = set(), [t for t, o in self.of_kind("decline", "shaft").items()
                              if o.get("top", o["anchor"][1]) >= self.objects[tid("decline-tu2")]["anchor"][1]]
        self.assertEqual(len(queue), 5)       # two portals, three collars
        while queue:
            node = queue.pop()
            if node not in seen:
                seen.add(node)
                queue.extend(edges.get(node, ()))
        underground = self.of_kind("level", "stope", "decline", "shaft", "raise", "main_fan", "pump_station")
        self.assertEqual(set(underground) - seen, set())

    def test_working_network_is_one_piece_without_planned_parts(self):
        edges = {}
        for level_id, level in self.of_kind("level").items():
            for link in level["links"]:
                if not link["planned"] and not level["planned"]:
                    edges.setdefault(level_id, set()).add(link["to"])
                    edges.setdefault(link["to"], set()).add(level_id)
        seen, queue = set(), [tid("decline-tu1")]
        while queue:
            node = queue.pop()
            if node not in seen:
                seen.add(node)
                queue.extend(edges.get(node, ()))
        working = {t for t, o in self.of_kind("level", "stope", "decline", "shaft", "raise", "pump_station").items()
                   if not o["planned"]}
        self.assertEqual(working - seen, set())

    def test_pump_stations(self):
        for thing_id, item in self.of_kind("pump_station").items():
            e = self.attr(thing_id, "elevation_m")
            self.assertEqual(item["elevation"], e)
            self.assertEqual(item["center"][1] - item["size"][1] / 2, e, "chamber floor on the level")
            sump = item["sump"]
            self.assertEqual(sump["center"][1] + sump["size"][1] / 2, e, "sump under the floor")
            volume = sump["size"][0] * sump["size"][1] * sump["size"][2]
            self.assertAlmostEqual(volume, self.attr(thing_id, "sump_volume_m3"), delta=1.0)
            target = self.attr(thing_id, "link_discharges_to")
            self.assertEqual(item["discharges_to"], target)
            pipe = item["pipe"]
            self.assertLess(point_box(pipe[0], item), TOUCH)
            self.assertLess(point_box(pipe[-1], self.objects[target]), TOUCH, f"{thing_id} pipe misses {target}")
            for a, b in segments(pipe):
                self.assertGreater(math.dist(a, b), 0)
            level = self.attr(thing_id, "_parents")
            self.assertIn(thing_id, [ln["to"] for ln in self.links(level, "chamber")])

    def test_mine_water_leaves_through_the_ventilation_shaft(self):
        pipe = self.objects[tid("ps-p150")]["pipe"]
        shaft = self.objects[tid(geometry.PIPE_SHAFT)]
        self.assertIn(shaft["anchor"], pipe)
        self.assertIn(shaft["base"], pipe)


class RouteTest(GeometryCase):
    def routes(self):
        for stope_id, stope in self.of_kind("stope").items():
            for decline in stope["routes"]:
                yield stope_id, decline, self.geo.stope_route(stope_id, decline)

    def assert_continuous(self, route, label):
        for a, b in segments(route.legs):
            self.assertEqual(a.points[-1], b.points[0], f"{label}: jump between {a.name} and {b.name}")
        joined = [p for leg in route.legs for p in leg.points]
        self.assertEqual(len(route.points), len(joined) - (len(route.legs) - 1))
        for a, b in segments(route.points):
            self.assertGreater(math.dist(a, b), 0, label)
        self.assertAlmostEqual(route.length, geometry.polyline_length(route.points), places=6)
        self.assertAlmostEqual(route.length, sum(leg.length for leg in route.legs), places=6)
        step = 5.0
        previous = route.point_at(0)
        self.assertEqual(previous, route.points[0])
        d = step
        while d < route.length:
            p = route.point_at(d)
            self.assertLessEqual(math.dist(previous, p), step + 1e-6, f"{label}: jump at {d:.0f} m")
            previous, d = p, d + step
        self.assertEqual(route.point_at(route.length + 10), route.points[-1])
        self.assertEqual(route.point_at_fraction(1.0), route.points[-1])

    def test_every_stope_reaches_the_rom_pad(self):
        dump = tuple(self.objects[tid("rom-stockpile")]["dump"])
        count = 0
        for stope_id, decline, route in self.routes():
            label = f"{stope_id} via {decline}"
            self.assertEqual([leg.name for leg in route.legs], ["level", "decline", "surface"], label)
            self.assertEqual(route.points[0], tuple(self.objects[stope_id]["draw_point"]), label)
            self.assertEqual(route.points[-1], dump, label)
            self.assert_continuous(route, label)
            count += 1
        self.assertEqual(count, sum(len(self.attr(s, "link_ore_route")) for s in self.of_kind("stope")))
        self.assertEqual(count, 30)

    def test_route_legs_follow_the_drawn_geometry(self):
        for stope_id, decline, route in self.routes():
            item = self.objects[decline]
            level = self.objects[self.objects[stope_id]["level"]]
            lvl, ramp, road = route.legs
            self.assertEqual({p[1] for p in lvl.points}, {level["elevation"]})
            self.assertEqual(ramp.points[-1], tuple(item["points"][0]))
            self.assertEqual(ramp.points[0][1], level["elevation"])
            for p in ramp.points:
                self.assertLess(point_polyline(p, item["points"]), 1e-6)
            ys = [p[1] for p in ramp.points]
            self.assertEqual(ys, sorted(ys))
            self.assertAlmostEqual(ramp.length, self.geo.decline_chainage(decline, level["elevation"]), places=6)
            self.assertEqual(list(road.points), self.geo.surface_road(decline))
            self.assertEqual(road.points[0], tuple(item["points"][0]))
            self.assertGreaterEqual(min(p[1] for p in road.points), item["portal_elevation"])

    def test_default_decline_and_reversed_route(self):
        up = self.geo.stope_route("stp-p150-1")
        self.assertEqual(up.points, self.geo.stope_route(tid("stp-p150-1"), "tu1").points)
        down = up.reversed()
        self.assertEqual(down.points, tuple(reversed(up.points)))
        self.assertEqual([leg.name for leg in down.legs], ["surface", "decline", "level"])
        self.assertAlmostEqual(down.length, up.length)
        self.assert_continuous(down, "reversed")
        self.assertEqual(geometry.stope_route("stp-p150-1").points, up.points)
        self.assertEqual(up.leg("decline").name, "decline")

    def test_a_decline_that_does_not_reach_the_stope_is_refused(self):
        self.assertEqual(self.geo.declines_for("stp-m050-1"), [tid("decline-tu1")])
        with self.assertRaises(ValueError):
            self.geo.stope_route("stp-m050-1", "tu2")

    def test_routes_between_stopes(self):
        stopes = list(self.of_kind("stope"))
        for a in stopes:
            for b in stopes:
                if a == b:
                    continue
                route = self.geo.stopes_route(a, b)
                self.assertEqual(route.points[0], tuple(self.objects[a]["draw_point"]))
                self.assertEqual(route.points[-1], tuple(self.objects[b]["draw_point"]))
                self.assert_continuous(route, f"{a} -> {b}")
                same = self.objects[a]["level"] == self.objects[b]["level"]
                self.assertEqual(len(route.legs), 1 if same else 3)

    def test_surface_roads(self):
        dump = self.objects[tid("rom-stockpile")]["dump"]
        for decline, item in self.of_kind("decline").items():
            road = self.geo.surface_road(decline)
            self.assertEqual(road[0], tuple(item["points"][0]))
            self.assertEqual(road[-1], tuple(dump))


class PositionTest(GeometryCase):
    def test_every_object_has_a_position(self):
        positions = self.geo.positions()
        self.assertEqual(list(positions), list(self.objects))
        for thing_id, item in self.objects.items():
            self.assertEqual(positions[thing_id], tuple(item["anchor"]))
            self.assertEqual(self.geo.position(thing_id), positions[thing_id])
            self.assertEqual(self.geo.position(thing_id.split(":")[1]), positions[thing_id])
            if item["primitive"] == "box":
                self.assertLess(point_box(item["anchor"], item), TOUCH, thing_id)
        self.assertEqual(geometry.positions(), positions)
        self.assertEqual(geometry.position("truck-01"), positions[tid("truck-01")])

    def test_abstract_things_have_none(self):
        for name in ("enterprise", "mine", "water", "scenario", "advisor", "no-such-thing"):
            self.assertIsNone(self.geo.position(name))

    def test_names_ids_and_tokens_resolve(self):
        self.assertEqual(self.geo.thing_id("tu2"), tid("decline-tu2"))
        self.assertEqual(self.geo.thing_id("lvl-000"), tid("lvl-000"))
        self.assertEqual(self.geo.obj("tu1")["token"], "tu1")
        self.assertEqual(self.geo.declines(), [tid("decline-tu1"), tid("decline-tu2")])
        self.assertEqual(self.geo.thing_ids(), list(self.objects))

    def test_parking_slots(self):
        mobile = self.of_kind("haul_truck", "lhd", "drill_rig")
        self.assertEqual(len(mobile), 27)
        yard = self.scenery["yard"]["footprint"]
        xs, zs = [p[0] for p in yard], [p[1] for p in yard]
        for thing_id, item in mobile.items():
            self.assertTrue(item["mobile"])
            self.assertEqual(item["center"][1] - item["size"][1] / 2, self.surface, thing_id)
            for p in geometry.item_points(item):
                self.assertTrue(min(xs) <= p[0] <= max(xs) and min(zs) <= p[2] <= max(zs), thing_id)
        for (a, box_a), (b, box_b) in combinations(mobile.items(), 2):
            self.assertFalse(boxes_overlap(box_a, box_b), f"{a} / {b}")
        self.assertEqual([t for t, o in self.objects.items() if o.get("mobile")], list(mobile))


class SurfaceTest(GeometryCase):
    def footprint_box(self, item):
        xs, zs = [p[0] for p in item["footprint"]], [p[1] for p in item["footprint"]]
        return {"center": [(min(xs) + max(xs)) / 2, 0, (min(zs) + max(zs)) / 2],
                "size": [max(xs) - min(xs), 1, max(zs) - min(zs)]}

    def test_ponds_keep_their_area_and_depth(self):
        total = 0.0
        for thing_id, item in self.of_kind("settling_pond").items():
            area = item["size"][0] * item["size"][2]
            self.assertAlmostEqual(area, self.attr(thing_id, "area_m2"), delta=2.5)
            self.assertEqual(item["size"][1], self.attr(thing_id, "depth_m"))
            self.assertEqual(item["center"][1] + item["size"][1] / 2, self.surface)
            total += area
        self.assertAlmostEqual(total, self.params["pond.area_m2"], delta=5.0)

    def test_tailings_lie_on_the_true_bearing(self):
        item = self.objects[tid("tailings")]
        x, _, z = item["anchor"]
        self.assertAlmostEqual(math.degrees(math.atan2(x, -z)), item["bearing_deg"], delta=0.1)
        self.assertAlmostEqual(item["bearing_deg"], 33.0, delta=1.0)        # spec 4.2: N 33 deg E
        self.assertAlmostEqual(item["true_distance"], math.hypot(1257, 830), delta=15.0)
        self.assertAlmostEqual(math.hypot(x, z), item["drawn_distance"], delta=0.2)
        self.assertEqual(item["drawn_distance"], 900)
        outline = self.footprint_box(item)
        for thing_id, dam in self.of_kind("tailings_dam").items():
            self.assertEqual((dam["bottom"], dam["anchor"][1]), (self.surface, dam["top"]))
            box = self.footprint_box(dam)
            for corner in dam["footprint"]:
                self.assertLess(point_box([corner[0], 0, corner[1]], outline), TOUCH, thing_id)
            volume = box["size"][0] * box["size"][2] * (dam["top"] - dam["bottom"])
            self.assertAlmostEqual(volume / self.attr(thing_id, "capacity_m3"), item["volume_scale"], delta=0.002)

    def test_surface_objects_do_not_overlap(self):
        boxes = {}
        for thing_id, item in self.of_kind("tailings_dam").items():
            boxes[thing_id] = self.footprint_box(item)
        for thing_id, item in self.of_kind("plant_line", "settling_pond", "main_fan").items():
            if item["center"][1] > self.surface - 5:
                boxes[thing_id] = {"center": [item["center"][0], 0, item["center"][2]],
                                   "size": [item["size"][0], 1, item["size"][2]]}
        for name in ("yard",):
            boxes[name] = self.footprint_box(self.scenery[name])
        pad = self.objects[tid("rom-stockpile")]
        boxes["rom-pad"] = self.footprint_box({"footprint": pad["pad"]})
        self.assertEqual(len(boxes), 4 + 6 + 2 + 3 + 2)
        for (a, box_a), (b, box_b) in combinations(boxes.items(), 2):
            self.assertFalse(boxes_overlap(box_a, box_b), f"{a} / {b}")
        pit = self.scenery["old-pit"]
        for name, box in boxes.items():
            low, high = box_limits(box)
            for x in (low[0], high[0]):
                for z in (low[2], high[2]):
                    gap = math.hypot(x - pit["base"][0], z - pit["base"][2]) - pit["radius_top"]
                    self.assertGreater(gap, 5.0, f"{name} stands in the old pit")

    def test_surface_objects_stand_apart_in_the_long_section(self):
        for kinds in (("plant_line",), ("settling_pond",), ("tailings_dam",)):
            spans = []
            for item in self.of_kind(*kinds).values():
                points = geometry.item_points(item)
                spans.append((min(p[0] for p in points), max(p[0] for p in points)))
            spans.sort()
            for a, b in segments(spans):
                self.assertLess(a[1], b[0], kinds)

    def test_plant_and_stockpile(self):
        lines = self.of_kind("plant_line")
        self.assertEqual(len(lines), 6)
        outline = self.footprint_box(self.objects[tid("plant")])
        for thing_id, item in lines.items():
            self.assertEqual(item["center"][1] - item["size"][1] / 2, self.surface)
            self.assertLess(point_box([item["center"][0], 0, item["center"][2]], outline), TOUCH)
        rom = self.objects[tid("rom-stockpile")]
        self.assertEqual(rom["base"][1], self.surface)
        self.assertEqual(rom["reference_t"], self.params["stockpile.start_t"])
        self.assertEqual(rom["dump"][1], self.surface)
        self.assertLess(point_box([rom["dump"][0], 0, rom["dump"][2]], self.footprint_box({"footprint": rom["pad"]})),
                        TOUCH)
        self.assertGreater(math.dist(rom["dump"], rom["base"]), 1.5 * rom["radius"])

    def test_monitoring_points_stand_on_their_water_course(self):
        for name, course in (("mon-volchevka", "stream-volchevka"), ("mon-sekisovka", "river-sekisovka")):
            self.assertLess(point_polyline(self.objects[tid(name)]["anchor"], self.scenery[course]["points"]), TOUCH)

    def test_water_courses_keep_the_published_distances(self):
        pit = self.scenery["old-pit"]
        cx, _, cz = pit["base"]
        stream = self.scenery["stream-volchevka"]["points"]
        river = self.scenery["river-sekisovka"]["points"]
        self.assertAlmostEqual(geometry.polyline_length(stream), 735, delta=2)
        self.assertLess(point_polyline(stream[-1], river), TOUCH, "the stream runs into the river")
        south = [cx, self.surface, cz + pit["radius_top"]]
        self.assertAlmostEqual(point_polyline(south, stream), 60, delta=3)
        self.assertAlmostEqual(point_polyline([cx, self.surface, cz], river) - pit["radius_top"], 150, delta=3)

    def test_surface_is_flat_and_holds_everything(self):
        surface = self.scenery["surface"]
        self.assertEqual(surface["y"], self.surface)
        self.assertEqual(self.surface, self.params["decline.tu1.portal_m"])
        xs, zs = [p[0] for p in surface["footprint"]], [p[1] for p in surface["footprint"]]
        low, high = self.doc["bounds"]["min"], self.doc["bounds"]["max"]
        self.assertEqual((min(xs), min(zs), max(xs), max(zs)), (low[0], low[2], high[0], high[2]))
        for name, item in self.scenery.items():
            if item["primitive"] == "polyline" and name != "road-tu2":
                self.assertEqual({p[1] for p in item["points"]}, {self.surface}, name)


if __name__ == "__main__":
    unittest.main()
