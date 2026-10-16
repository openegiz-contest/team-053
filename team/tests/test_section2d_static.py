"""Static checks of the 2D long section (work package D2).

The module is plain ES modules and one style sheet under stand/web/js/section2d.
These checks need no browser: the files keep the rules of the page (no other
host, LF line endings, Russian text on screen), the view contract is exported,
every relative import resolves, and the geometry the drawing relies on is there.
"""
import json
import os
import re
import unittest

TEAM_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(TEAM_DIR, "stand", "web")
SECTION_DIR = os.path.join(WEB_DIR, "js", "section2d")
GEOMETRY = os.path.join(TEAM_DIR, "model", "geometry.json")
NS = "kz.sekis:"

IMPORT = re.compile(r"""^\s*(?:import|export)\b[^'"]*?from\s+['"]([^'"]+)['"]""", re.M)
STRING = re.compile(r"""'((?:[^'\\\n]|\\.)*)'|`((?:[^`\\]|\\.)*)`""")
COMMENT = re.compile(r"/\*.*?\*/|(?<![:\w])//[^\n]*", re.S)
CYRILLIC = re.compile(r"[А-Яа-яЁё]")
# Latin words that may appear in a string shown on the sheet: model names and the
# name of the elevation data set (Copernicus DEM) only.
LATIN_ALLOWED = {"AL18", "V", "Copernicus", "DEM"}


def read(path):
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.read()


def section_files():
    return sorted(os.path.join(SECTION_DIR, name) for name in os.listdir(SECTION_DIR)
                  if name.endswith((".js", ".css")))


class SectionFilesTest(unittest.TestCase):

    def test_files_exist(self):
        names = {os.path.basename(path) for path in section_files()}
        self.assertIn("index.js", names)
        self.assertIn("section.css", names)

    def test_no_external_url_and_lf(self):
        for path in section_files():
            text = read(path)
            self.assertNotRegex(text, r"https?://", path)
            self.assertNotRegex(text, r"""(?:src|href)\s*=\s*["']//""", path)
            self.assertNotRegex(text, r"@import|url\(\s*['\"]?(?:https?:)?//", path)
            self.assertNotIn("\r", text, f"{path} must have LF line endings")
            self.assertTrue(text.endswith("\n"), path)

    def test_view_contract(self):
        text = read(os.path.join(SECTION_DIR, "index.js"))
        self.assertRegex(text, r"export\s+(?:async\s+)?function\s+mount\s*\(\s*container\s*,\s*geometry\s*\)")
        for member in ("update(state)", "focus(thingId)", "dispose()"):
            self.assertIn(member, text)
        self.assertIn("'sekis:select'", text)
        self.assertIn("bubbles: true", text)
        # The container is measured, never assumed.
        self.assertNotRegex(text, r"view-section2d|view-scene3d")
        self.assertIn("ResizeObserver", text)

    def test_imports_resolve(self):
        for path in section_files():
            if not path.endswith(".js"):
                continue
            for target in IMPORT.findall(read(path)):
                self.assertTrue(target.startswith("."), f"{path}: {target}")
                resolved = os.path.normpath(os.path.join(os.path.dirname(path), target))
                self.assertTrue(os.path.isfile(resolved), f"{path}: {target}")
                self.assertTrue(resolved.startswith(os.path.join(WEB_DIR, "js")), f"{path}: {target}")

    def test_shared_helpers_are_reused(self):
        text = "".join(read(path) for path in section_files() if path.endswith(".js"))
        self.assertIn("../panels/dict.js", text)
        self.assertIn("../panels/format.js", text)
        for helper in ("stateLabel", "stateTone", "fmt(", "withUnit("):
            self.assertIn(helper, text)
        # Numbers reach the sheet through format.js, not through the built-in formatters.
        self.assertNotRegex(text, r"toLocaleString|Intl\.NumberFormat")

    def test_screen_text_is_russian(self):
        """Text for the reader is Russian: titles, labels, and any literal that reads as a phrase."""
        shown = re.compile(r"""(?:\btitle|'aria-label'|\btext)\s*:\s*'((?:[^'\\\n]|\\.)*)'""")
        phrase = re.compile(r"^[A-Z][a-z]+(?: [A-Za-z]+)+[.!?]?$")
        seen = 0
        for path in section_files():
            if not path.endswith(".js"):
                continue
            code = COMMENT.sub("", read(path))
            for literal in shown.findall(code):
                if re.search(r"[A-Za-z]", literal):
                    self.fail(f"{path}: {literal!r} is shown to the reader and is not Russian")
            for match in STRING.finditer(code):
                literal = match.group(1) if match.group(1) is not None else match.group(2)
                if CYRILLIC.search(literal):
                    seen += 1
                    words = set(re.findall(r"[A-Za-z]{2,}", re.sub(r"\$\{[^}]*\}", "", literal)))
                    self.assertLessEqual(words, LATIN_ALLOWED, f"{path}: {literal!r}")
                else:
                    self.assertNotRegex(literal, phrase, f"{path}: {literal!r}")
        self.assertGreater(seen, 60)

    def test_calm_sheet(self):
        # Review round 3: declines under the stopes and quiet by default; no floating
        # label that repeats a table cell, a fan label or the legend; the mine row shows
        # the air delivered now against the demand of the units in work.
        index = read(os.path.join(SECTION_DIR, "index.js"))
        layers = re.search(r"const LAYERS = \[(.*?)\];", index).group(1)
        order = re.findall(r"'(\w+)'", layers)
        self.assertLess(order.index("declines"), order.index("stopes"))
        css = read(os.path.join(SECTION_DIR, "section.css"))
        self.assertIn(".sx-decline { --c: color-mix(in srgb, var(--ok) 58%, var(--sx-bg));", css)
        self.assertIn(".sx-decline.lit", css)
        underground = read(os.path.join(SECTION_DIR, "underground.js"))
        self.assertNotIn("карьер (в проекции)", underground)
        self.assertNotIn("stope.short, { class: 'sx-tag' }", underground)
        self.assertIn("if (roomy && !fanned) {", underground)
        tables = read(os.path.join(SECTION_DIR, "tables.js"))
        self.assertIn("isNum(f.air_delivered_m3s) && isNum(f.vod_demand_m3s)", tables)
        self.assertIn("`воздух: подаётся ${delivered}, нужно машинам в работе ${withUnit(needed, 'м³/с')}`", tables)
        self.assertNotIn("`воздух ${fmt(f.air_demand_m3s, 0)} из ${withUnit(fmt(f.air_supply_m3s, 0), 'м³/с')}`", tables)
        card = read(os.path.join(SECTION_DIR, "card.js"))
        self.assertIn("mine: ['air_delivered_m3s', 'vod_demand_m3s',", card)

    def test_tokens_come_from_the_page(self):
        css = read(os.path.join(SECTION_DIR, "section.css"))
        for token in ("--ok", "--warn", "--fail", "--planned", "--idle", "--flood", "--text"):
            self.assertIn(f"var({token}", css)
        # The accent belongs to the binding link.
        self.assertNotIn("var(--accent", css)
        self.assertIn("prefers-reduced-motion", css)

    def test_stope_palette_is_one_map_in_dict(self):
        dict_js = read(os.path.join(WEB_DIR, "js", "panels", "dict.js"))
        block = re.search(r"STOPE_COLORS = \{(.*?)\};", dict_js, re.S).group(1)
        palette = dict(re.findall(r"(\w+): '(#[0-9a-f]{6})'", block))
        self.assertEqual(len(palette), 10)
        tokens = dict(re.findall(r"--(\w+): (#[0-9a-f]{6});", read(os.path.join(WEB_DIR, "css", "tokens.css"))))
        for state, token in (("awaiting_blast", "warn"), ("standby", "idle"),
                             ("planned", "planned"), ("flooded", "flood")):
            self.assertEqual(palette[state], tokens[token], state)
        # The accent belongs to the binding link, and the section holds no stope colour of its own.
        self.assertNotIn(tokens["accent"], palette.values())
        self.assertNotRegex(read(os.path.join(SECTION_DIR, "section.css")), r"--st-\w+:")


class SectionGeometryTest(unittest.TestCase):
    """What the drawing reads from geometry.json."""

    @classmethod
    def setUpClass(cls):
        with open(GEOMETRY, encoding="utf-8") as handle:
            cls.geometry = json.load(handle)
        cls.objects = cls.geometry["objects"]

    def kind(self, name):
        return [(key, value) for key, value in self.objects.items() if value["kind"] == name]

    def test_counts(self):
        self.assertEqual(len(self.kind("level")), 12)
        self.assertEqual(len(self.kind("stope")), 18)
        self.assertEqual(len(self.kind("main_fan")), 5)
        self.assertEqual(len(self.kind("pump_station")), 3)
        self.assertEqual(len(self.kind("decline")), 2)

    def test_fields_used_by_the_section(self):
        self.assertIn("surface", self.geometry["frame"])
        for _, level in self.kind("level"):
            self.assertIn("elevation", level)
            self.assertGreaterEqual(len(level["points"]), 2)
        for _, stope in self.kind("stope"):
            self.assertIn(stope["level"], self.objects)
            self.assertEqual(len(stope["center"]), 3)
            self.assertEqual(len(stope["size"]), 3)
        for _, decline in self.kind("decline"):
            ys = [point[1] for point in decline["points"]]
            self.assertEqual(ys, sorted(ys, reverse=True), "a decline runs from the portal down")
            self.assertIn("bottom_elevation", decline)
            self.assertTrue(all(node["type"] in ("portal", "bay", "turn", "access") for node in decline["nodes"]))
        for kind in ("shaft", "raise"):
            for _, airway in self.kind(kind):
                self.assertGreater(airway["top"], airway["base"][1])
                self.assertIn(airway["direction"], ("intake", "exhaust"))
        for _, fan in self.kind("main_fan"):
            self.assertTrue(all(airway in self.objects for airway in fan["airway"]))
        for _, station in self.kind("pump_station"):
            self.assertGreaterEqual(len(station["pipe"]), 2)
            self.assertIn("elevation", station)

    def test_ground_and_surface_fields(self):
        """The ground line, the pit cut, the dams on their own ground and the tailings caption."""
        profile = self.geometry["profile"]
        xs = [point[0] for point in profile["points"]]
        self.assertGreater(len(xs), 100)
        self.assertEqual(xs, sorted(xs))
        mine_xs = [point[0] for _, level in self.kind("level") for point in level["points"]]
        self.assertLessEqual(xs[0], min(mine_xs))
        pit = self.geometry["scenery"]["old-pit"]
        self.assertEqual(pit["primitive"], "pit")
        self.assertGreater(len(pit["section"]), 2)
        self.assertIn("floor", pit)
        self.assertTrue(all("y" in bench for bench in pit["benches"]))
        for _, dam in self.kind("tailings_dam"):
            self.assertLess(dam["bottom"], dam["top"])
        (_, facility), = self.kind("tailings_facility")
        self.assertGreater(facility["true_distance"], 0)
        self.assertIn("bearing_deg", facility)
        for _, stope in self.kind("stope"):
            self.assertEqual(stope["size"][1], 50, "a block fills the floor between two levels")
        self.assertTrue(any("documented_top" in shaft for _, shaft in self.kind("shaft")))
        text = read(os.path.join(SECTION_DIR, "surface.js"))
        for field in ("yearsLeft(", "tailings_facility", "sx-break"):
            self.assertIn(field, text)
        model = read(os.path.join(SECTION_DIR, "model.js"))
        for field in ("geometry.profile", "o.section", "true_distance", "bearing_deg", "documented_top"):
            self.assertIn(field, model)

    def test_short_names_point_to_things(self):
        text = read(os.path.join(SECTION_DIR, "model.js"))
        block = re.search(r"const SHORT = \{(.*?)\};", text, re.S)
        self.assertIsNotNone(block)
        names = re.findall(r"'([a-z0-9-]+)':", block.group(1))
        self.assertGreaterEqual(len(names), 15)
        for name in names:
            self.assertIn(NS + name, self.objects, name)

    def test_declines_do_not_overlap_each_other(self):
        """The two declines are told apart by their halves of the section as well as by line style."""
        (_, first), (_, second) = self.kind("decline")
        span = lambda decline: (min(p[0] for p in decline["points"][1:]), max(p[0] for p in decline["points"][1:]))
        a, b = sorted((span(first), span(second)))
        self.assertLessEqual(a[1], b[0] + 5.0)


if __name__ == "__main__":
    unittest.main()
