"""Static checks of the plan view («План»): the mine on the Sentinel-2 image.

The view is plain ES modules and one style sheet under stand/web/js/plan2d.
These checks need no browser: the files keep the rules of the page (no other
host, LF line endings, Russian text on screen), the view contract is exported,
every relative import resolves, the attribution is on the view, the page has
the tab and its mount container, and the copy of the OpenStreetMap features in
plan2d/osm.js equals model/terrain/features.json.

    python tests/test_plan2d_static.py --write-osm    rewrites plan2d/osm.js
"""
import json
import os
import re
import sys
import unittest

TEAM_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(TEAM_DIR, "stand", "web")
PLAN_DIR = os.path.join(WEB_DIR, "js", "plan2d")
OSM_JS = os.path.join(PLAN_DIR, "osm.js")
FEATURES = os.path.join(TEAM_DIR, "model", "terrain", "features.json")
GEOMETRY = os.path.join(TEAM_DIR, "model", "geometry.json")

IMPORT = re.compile(r"""^\s*(?:import|export)\b[^'"]*?from\s+['"]([^'"]+)['"]""", re.M)
STRING = re.compile(r"""'((?:[^'\\\n]|\\.)*)'|`((?:[^`\\]|\\.)*)`""")
COMMENT = re.compile(r"/\*.*?\*/|(?<![:\w])//[^\n]*", re.S)
CYRILLIC = re.compile(r"[А-Яа-яЁё]")
# Latin words that may appear in a string shown on the view: the attribution of
# the image and the map data, the grid name and model names.
LATIN_ALLOWED = {"Contains", "modified", "Copernicus", "Sentinel", "data", "OpenStreetMap",
                 "contributors", "OSM", "UTM", "EPSG", "ODbL", "AL18", "V"}
ATTRIBUTION = "Снимок: Contains modified Copernicus Sentinel data 2026 · объекты: © OpenStreetMap contributors"

OSM_HEADER = """// OpenStreetMap features of the plan that geometry.json does not carry: the
// road graph, the heaps and the quarry north of the old pit, copied from
// team/model/terrain/features.json (scene frame: x east, z south, metres from
// the mine point). © OpenStreetMap contributors, ODbL 1.0; see
// team/model/terrain/ATTRIBUTION.md. Generated, do not edit; regenerate with
//   cd team && python tests/test_plan2d_static.py --write-osm
// (tests.test_plan2d_static checks that this copy equals features.json).
"""


def read(path):
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.read()


def osm_extract():
    """The part of features.json that the plan draws and geometry.json lacks."""
    with open(FEATURES, encoding="utf-8") as handle:
        features = json.load(handle)
    return {
        "osm_timestamp": features["osm_timestamp"],
        "roads": {"nodes": features["roads"]["nodes"], "edges": features["roads"]["edges"]},
        "heaps": [heap["outline"] for heap in features["heaps"]],
        "quarry_north": features["quarry_north"]["outline"],
    }


def write_osm():
    body = json.dumps(osm_extract(), ensure_ascii=False, separators=(",", ":"))
    with open(OSM_JS, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(OSM_HEADER + "export default " + body + ";\n")


def plan_files():
    return sorted(os.path.join(PLAN_DIR, name) for name in os.listdir(PLAN_DIR)
                  if name.endswith((".js", ".css")))


class PlanFilesTest(unittest.TestCase):

    def test_files_exist(self):
        names = {os.path.basename(path) for path in plan_files()}
        for name in ("index.js", "plan.css", "osm.js", "model.js"):
            self.assertIn(name, names)

    def test_no_external_url_and_lf(self):
        for path in plan_files():
            text = read(path)
            self.assertNotRegex(text, r"https?://", path)
            self.assertNotRegex(text, r"""(?:src|href)\s*=\s*["']//""", path)
            self.assertNotRegex(text, r"@import|url\(\s*['\"]?(?:https?:)?//", path)
            self.assertNotRegex(text, r"\bfetch\s*\(\s*['\"`](?!/)", path)
            self.assertNotIn("\r", text, f"{path} must have LF line endings")
            self.assertTrue(text.endswith("\n"), path)

    def test_view_contract(self):
        text = read(os.path.join(PLAN_DIR, "index.js"))
        self.assertRegex(text, r"export\s+(?:async\s+)?function\s+mount\s*\(\s*container\s*,\s*geometry\s*\)")
        for member in ("update(state)", "focus(thingId)", "dispose()"):
            self.assertIn(member, text)
        self.assertIn("'sekis:select'", text)
        self.assertIn("bubbles: true", text)
        self.assertIn("detail: { thingId }", text)
        # The container is measured, never assumed.
        self.assertNotRegex(text, r"view-plan2d|view-section2d|view-scene3d")
        self.assertIn("ResizeObserver", text)
        # The image is the texture the server already serves, placed by its extent.
        self.assertIn("'/terrain/texture.jpg'", read(os.path.join(PLAN_DIR, "model.js")))
        self.assertIn("texture.extent", read(os.path.join(PLAN_DIR, "model.js")))

    def test_imports_resolve(self):
        for path in plan_files():
            if not path.endswith(".js"):
                continue
            for target in IMPORT.findall(read(path)):
                self.assertTrue(target.startswith("."), f"{path}: {target}")
                resolved = os.path.normpath(os.path.join(os.path.dirname(path), target))
                self.assertTrue(os.path.isfile(resolved), f"{path}: {target}")
                self.assertTrue(resolved.startswith(os.path.join(WEB_DIR, "js")), f"{path}: {target}")
                # The plan stands on its own: it shares the panels, not another view's files.
                self.assertNotRegex(resolved, r"section2d|scene3d", f"{path}: {target}")

    def test_shared_helpers_are_reused(self):
        text = "".join(read(path) for path in plan_files() if path.endswith(".js"))
        self.assertIn("../panels/dict.js", text)
        self.assertIn("../panels/format.js", text)
        for helper in ("stateLabel", "stateTone", "stopeColor", "STOPE_ORDER", "featureLabel",
                       "unitCounts", "fmt(", "withUnit("):
            self.assertIn(helper, text)
        # Numbers reach the view through format.js, not through the built-in formatters.
        self.assertNotRegex(text, r"toLocaleString|Intl\.NumberFormat|\.toFixed\(\d\)\s*\+\s*'\s*[мт%]")

    def test_screen_text_is_russian(self):
        """Text for the reader is Russian: titles, labels, and any literal that reads as a phrase."""
        shown = re.compile(r"""(?:\btitle|'aria-label'|\btext)\s*:\s*'((?:[^'\\\n]|\\.)*)'""")
        phrase = re.compile(r"^[A-Z][a-z]+(?: [A-Za-z]+)+[.!?]?$")
        seen = 0
        for path in plan_files():
            if not path.endswith(".js") or path == OSM_JS:
                continue
            code = COMMENT.sub("", read(path))
            for literal in shown.findall(code):
                words = set(re.findall(r"[A-Za-z]{2,}", literal))
                self.assertLessEqual(words, LATIN_ALLOWED, f"{path}: {literal!r} is shown and is not Russian")
            for match in STRING.finditer(code):
                literal = match.group(1) if match.group(1) is not None else match.group(2)
                if CYRILLIC.search(literal):
                    seen += 1
                    words = set(re.findall(r"[A-Za-z]{2,}", re.sub(r"\$\{[^}]*\}", "", literal)))
                    self.assertLessEqual(words, LATIN_ALLOWED, f"{path}: {literal!r}")
                else:
                    self.assertNotRegex(literal, phrase, f"{path}: {literal!r}")
        self.assertGreater(seen, 50)

    def test_attribution_on_the_view(self):
        text = "".join(read(path) for path in plan_files() if path.endswith(".js") and path != OSM_JS)
        self.assertIn(ATTRIBUTION, text)
        self.assertIn("UTM 44N", text)

    def test_tokens_come_from_the_page(self):
        css = read(os.path.join(PLAN_DIR, "plan.css"))
        for token in ("--ok", "--warn", "--fail", "--planned", "--idle", "--flood", "--text"):
            self.assertIn(f"var({token}", css)
        # The accent marks the binding link only (one-line rules of the .bind class).
        self.assertIn("var(--accent", css)
        for line in css.splitlines():
            if "var(--accent" in line:
                self.assertIn(".bind", line, line)
        self.assertIn("prefers-reduced-motion", css)
        # The stope palette is the one map of dict.js.
        self.assertNotRegex(css, r"--st-\w+:")


class PlanPageTest(unittest.TestCase):
    """The tab and the mount container in index.html, the wiring in app.js."""

    def test_tab_and_container(self):
        html = read(os.path.join(WEB_DIR, "index.html"))
        self.assertRegex(html, r'<button type="button" data-mode="plan2d" aria-pressed="false">План</button>')
        self.assertRegex(html, r'<div class="view" id="view-plan2d" data-view="plan2d"[^>]*>')
        for mode in ("both", "scene3d", "section2d"):
            self.assertIn(f'data-mode="{mode}"', html)
        self.assertNotIn("\r", html)

    def test_app_mounts_the_plan(self):
        app = read(os.path.join(WEB_DIR, "js", "app.js"))
        self.assertIn("plan2d: './plan2d/index.js'", app)
        self.assertIn("document.getElementById('view-plan2d')", app)
        self.assertNotIn("\r", app)


class PlanDataTest(unittest.TestCase):
    """What the plan reads: the OSM copy and the geometry fields."""

    def test_osm_copy_is_current(self):
        text = read(OSM_JS)
        self.assertTrue(text.startswith(OSM_HEADER), "osm.js header")
        line = next(row for row in text.splitlines() if row.startswith("export default "))
        copy = json.loads(line[len("export default "):].rstrip(";"))
        self.assertEqual(copy, osm_extract(),
                         "plan2d/osm.js is stale: run python tests/test_plan2d_static.py --write-osm")
        nodes = copy["roads"]["nodes"]
        self.assertTrue(all(0 <= i < len(nodes) and 0 <= j < len(nodes) for i, j in copy["roads"]["edges"]))

    def test_geometry_fields(self):
        with open(GEOMETRY, encoding="utf-8") as handle:
            geometry = json.load(handle)
        texture = geometry["terrain"]["texture"]
        self.assertEqual(len(texture["extent"]), 4)
        self.assertTrue(texture["north_up"])
        scenery = geometry["scenery"]
        for name in ("old-pit", "road-tu1", "road-tu2", "yard", "stream-volchevka", "river-sekisovka",
                     "village", "industrial-zone", "tsf-cell-south", "tsf-cell-southeast", "conveyor"):
            self.assertIn(name, scenery)
        self.assertTrue(all("lines" in bench for bench in scenery["old-pit"]["benches"]))
        objects = geometry["objects"]
        kinds = {}
        for key, value in objects.items():
            kinds.setdefault(value["kind"], []).append(value)
            self.assertEqual(len(value["anchor"]), 3, key)
        for pond in kinds["settling_pond"]:
            self.assertGreaterEqual(len(pond["outline"]), 3)
        for dam in kinds["tailings_dam"]:
            self.assertGreaterEqual(len(dam["footprint"]), 3)
        self.assertGreaterEqual(len(objects["kz.sekis:plant"]["footprint"]), 3)
        self.assertIn("pad", objects["kz.sekis:rom-stockpile"])
        for decline in kinds["decline"]:
            self.assertEqual(decline["nodes"][0]["type"], "portal")


if __name__ == "__main__":
    if "--write-osm" in sys.argv:
        write_osm()
        print(f"wrote {OSM_JS}")
    else:
        unittest.main()
