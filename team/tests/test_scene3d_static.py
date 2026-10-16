"""3D scene (work package D1): static checks of the module and of the vendored three.js.

The scene itself runs in a browser; these tests guard what can be checked
without one: the vendored release is the pinned one and unmodified, nothing is
loaded from another host, the files are LF, every import resolves inside the
repository, and the constraints of the performance budget (spec 4.5) that are
visible in the source are in place.
"""

import hashlib
import importlib.util
import json
import os
import re
import threading
import unittest
import urllib.request

TEAM_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(TEAM_DIR, "stand", "web")
SCENE_DIR = os.path.join(WEB_DIR, "js", "scene3d")
VENDOR_DIR = os.path.join(WEB_DIR, "vendor", "three")
GEOMETRY_FILE = os.path.join(TEAM_DIR, "model", "geometry.json")
TEXTURE_FILE = os.path.join(TEAM_DIR, "model", "terrain", "texture.jpg")
SERVER_FILE = os.path.join(TEAM_DIR, "stand", "server.py")

# three@0.160.0 from the npm registry tarball (sha1 cd1e4dbd01aee0719280a9086d75545db52b7a8f):
# package/build/three.module.min.js, package/examples/jsm/controls/OrbitControls.js,
# package/examples/jsm/renderers/CSS2DRenderer.js, package/LICENSE.
VENDORED_SHA256 = {
    "three.module.min.js": "3e690ac7d180b0aadf0891bea39eec643e29e2d3e75c99b18689518665f69ba6",
    "OrbitControls.js": "5a44a9e86a2a0fb11933eed69bc2cd33c76a496854c1aed6ed776efa87d7b064",
    "CSS2DRenderer.js": "a4f0f79184c043f6b9d2654d8ba051e49a7d631d34e8f437c1804798a68c379f",
    "LICENSE": "852e0e8699169bf9f6fdc6bda3e682d078dcbc738b5d33e74df594721bff271d",
}
VENDOR_BUDGET_BYTES = 1_500_000
IMPORT_RE = re.compile(r"""^\s*(?:import|export)\b[^'"]*?from\s+['"]([^'"]+)['"]""", re.M)


def read(path):
    with open(path, "rb") as handle:
        return handle.read()


def scene_files():
    return [os.path.join(SCENE_DIR, name) for name in sorted(os.listdir(SCENE_DIR)) if name.endswith(".js")]


def import_map():
    html = read(os.path.join(WEB_DIR, "index.html")).decode("utf-8")
    block = re.search(r'<script type="importmap">(.*?)</script>', html, re.S)
    return json.loads(block.group(1))["imports"]


class VendoredThree(unittest.TestCase):
    def test_files_are_the_pinned_release(self):
        self.assertEqual(sorted(os.listdir(VENDOR_DIR)), sorted(VENDORED_SHA256))
        for name, expected in VENDORED_SHA256.items():
            self.assertEqual(hashlib.sha256(read(os.path.join(VENDOR_DIR, name))).hexdigest(), expected, name)

    def test_revision_license_and_size(self):
        library = read(os.path.join(VENDOR_DIR, "three.module.min.js")).decode("utf-8")
        self.assertRegex(library[:400], r'const \w+="160"')
        self.assertIn("SPDX-License-Identifier: MIT", library[:200])
        license_text = read(os.path.join(VENDOR_DIR, "LICENSE")).decode("utf-8")
        self.assertIn("The MIT License", license_text)
        self.assertIn("three.js authors", license_text)
        total = sum(os.path.getsize(os.path.join(VENDOR_DIR, name)) for name in os.listdir(VENDOR_DIR))
        self.assertLess(total, VENDOR_BUDGET_BYTES)

    def test_files_are_lf(self):
        for name in VENDORED_SHA256:
            self.assertNotIn(b"\r", read(os.path.join(VENDOR_DIR, name)), name)

    def test_import_map_serves_the_addons(self):
        imports = import_map()
        for specifier, target in imports.items():
            self.assertTrue(target.startswith("/vendor/three/"), specifier)
            self.assertTrue(os.path.isfile(os.path.join(WEB_DIR, target.lstrip("/"))), target)
        # The add-ons import the library by its bare name, which the map resolves.
        for name in ("OrbitControls.js", "CSS2DRenderer.js"):
            text = read(os.path.join(VENDOR_DIR, name)).decode("utf-8")
            self.assertEqual(set(IMPORT_RE.findall(text)), {"three"}, name)
        self.assertIn("three", imports)


class SceneModule(unittest.TestCase):
    def test_entry_point(self):
        text = read(os.path.join(SCENE_DIR, "index.js")).decode("utf-8")
        self.assertRegex(text, r"export async function mount\(container, geometry\)")
        for member in ("update(state)", "focus(thingId)", "dispose()",
                       "new CustomEvent('sekis:select', { bubbles: true, detail: { thingId: id } })",
                       # No WebGL: a clear error, so that the page mounts the section instead.
                       "throw new Error('scene3d: a WebGL context cannot be created in this browser')"):
            self.assertTrue(member in text, member)

    def test_no_other_host_and_lf(self):
        for path in scene_files():
            data = read(path)
            self.assertNotIn(b"\r", data, f"{path} must have LF line endings")
            text = data.decode("utf-8")
            self.assertNotRegex(text, r"https?://", path)
            self.assertNotRegex(text, r"""(?:src|href)\s*=\s*["']//""", path)
            self.assertNotRegex(text, r"@import|url\(\s*['\"]?(?:https?:)?//", path)
            self.assertNotRegex(text, r"\bimport\s*\(", path)   # no dynamic import of anything

    def test_imports_resolve_inside_the_repository(self):
        bare = set(import_map())
        for path in scene_files():
            for target in IMPORT_RE.findall(read(path).decode("utf-8")):
                if target.startswith("."):
                    resolved = os.path.normpath(os.path.join(os.path.dirname(path), target))
                    self.assertTrue(resolved.startswith(os.path.join(WEB_DIR, "js")), (path, target))
                    self.assertTrue(os.path.isfile(resolved), (path, target))
                else:
                    self.assertIn(target, bare, (path, target))

    def test_budget_constraints_in_source(self):
        text = "\n".join(read(path).decode("utf-8") for path in scene_files())
        self.assertFalse("antialias: true" in text)
        for required in ("antialias: false", "renderer.setPixelRatio(1)", "const FRAME_MS = 1000 / 12;",
                         "const MAX_CANVAS = [1280, 720];", "export const MAX_LABELS = 30;"):
            self.assertTrue(required in text, required)
        for banned in ("CanvasTexture", "DataTexture", "new THREE.Texture(", "VideoTexture", "shadowMap",
                       "castShadow", "EffectComposer", "DirectionalLight", "AmbientLight", "PointLight",
                       "MeshStandardMaterial", "MeshPhongMaterial", "MeshLambertMaterial"):
            self.assertFalse(banned in text, f"{banned} is outside the budget")
        # One texture (spec 4.5): the satellite image of the terrain, from the Stand server.
        self.assertEqual(text.count("new THREE.TextureLoader()"), 1)
        self.assertEqual(text.count("TextureLoader"), 1)
        self.assertIn("export const TEXTURE_URL = '/terrain/texture.jpg';", text)
        # At most five translucent materials (spec 4.5).
        self.assertLessEqual(len(re.findall(r"transparent: true", text)), 5)

    def test_terrain_fits_the_budget(self):
        with open(GEOMETRY_FILE, encoding="utf-8") as handle:
            terrain = json.load(handle)["terrain"]
        rows, inset = terrain["rows"], terrain["inset"]
        x0, z0, x1, z1 = inset["cells"]
        # The scene draws every main cell outside the inset and every inset cell, two triangles each.
        coarse = (len(rows) - 1) * (len(rows[0]) - 1) - (x1 - x0) * (z1 - z0)
        fine = (len(inset["rows"]) - 1) * (len(inset["rows"][0]) - 1)
        self.assertEqual(2 * (coarse + fine), 9272)
        self.assertLessEqual(2 * (coarse + fine), 10000)   # leaves 10 000 of the 20 000 for the rest
        self.assertEqual(terrain["texture"]["size"], [512, 512])

    def test_resize_never_leaves_the_canvas_cleared(self):
        # Setting the canvas size clears the WebGL buffer. A headless capture
        # (--screenshot with --virtual-time-budget) resizes the page just before
        # the capture and grants animation frames rarely, so the scene must be
        # redrawn inside the resize callback, not in a later animation frame.
        text = read(os.path.join(SCENE_DIR, "index.js")).decode("utf-8")
        resize = re.search(r"\n  function resize\(\) \{\n(.*?)\n  \}\n", text, re.S)
        self.assertIsNotNone(resize)
        body = resize.group(1)
        self.assertIn("if (cleared) renderer.setSize(", body)
        self.assertIn("drawNow(cleared || wasHidden);", body)
        self.assertIn("function drawNow(force)", text)

    def test_every_geometry_kind_is_drawn(self):
        with open(GEOMETRY_FILE, encoding="utf-8") as handle:
            geometry = json.load(handle)
        kinds = {item["kind"] for item in geometry["objects"].values()}
        primitives = {item["primitive"] for item in geometry["objects"].values()}
        self.assertTrue(kinds)
        text = "\n".join(read(path).decode("utf-8") for path in scene_files())
        for kind in sorted(kinds):
            self.assertTrue(f"'{kind}'" in text, f"kind {kind} is not handled by the scene")
        # The scene reads these fields of the geometry contract; fail early if one is renamed.
        used = {"box": ("center", "size"), "cylinder": ("base", "top", "radius"), "prism": ("footprint", "bottom", "top"),
                "polyline": ("points",), "outline": ("footprint", "y"), "cone": ("base", "radius", "height"),
                "marker": ("anchor",)}
        self.assertLessEqual(primitives, set(used))
        for thing_id, item in geometry["objects"].items():
            for field in used[item["primitive"]] + ("anchor", "planned"):
                self.assertIn(field, item, f"{thing_id} lacks {field}")
        for name in ("surface", "old-pit", "road-tu1", "road-tu2", "village", "industrial-zone",
                     "river-sekisovka", "stream-volchevka"):
            self.assertIn(name, geometry["scenery"], name)
        # The terrain and the carved pit, as the scene reads them.
        terrain = geometry["terrain"]
        for field in ("extent", "origin", "spacing", "rows", "inset", "texture"):
            self.assertIn(field, terrain, field)
        for field in ("origin", "spacing", "rows", "cells"):
            self.assertIn(field, terrain["inset"], field)
        self.assertEqual(terrain["texture"]["extent"], terrain["extent"])
        pit = geometry["scenery"]["old-pit"]
        self.assertEqual(pit["primitive"], "pit")
        for field in ("rim", "floor", "floor_outline", "benches"):
            self.assertIn(field, pit, field)
        self.assertTrue(all("y" in bench and "lines" in bench for bench in pit["benches"]))
        for thing_id, item in geometry["objects"].items():
            if item["kind"] == "settling_pond":
                self.assertIn("outline", item, thing_id)
        # Flow paths the scene animates are looked up by these names.
        for name in ("conveyor", "pipeline-tailings", "pipeline-water-supply", "pipeline-discharge",
                     "pipeline-intake"):
            self.assertIn(name, geometry["scenery"], name)
            self.assertTrue(name in text, f"{name} is not animated by the scene")

    def test_surface_data_is_attributed(self):
        # The licences ask for attribution wherever the data is shown: in the scene and in the page legend.
        ui = read(os.path.join(SCENE_DIR, "ui.js")).decode("utf-8")
        for notice in ("© DLR e.V. 2010–2014, © Airbus DS 2014–2018, Copernicus",
                       "Contains modified Copernicus Sentinel data 2026", "© OpenStreetMap contributors"):
            self.assertIn(notice, ui)
        self.assertIn("root.append(style, bar, legend, credit);", ui)
        html = read(os.path.join(WEB_DIR, "index.html")).decode("utf-8")
        self.assertIn("Поверхность — рельеф Copernicus DEM и снимок Sentinel-2 (30.09.2026), объекты — OpenStreetMap; "
                      "подземные выработки: отметки и сечения по документам, план — схема", html)
        self.assertNotIn("Отметки и сечения — по опубликованным данным; расположение в плане — схема", html)

    def test_server_serves_the_texture(self):
        spec = importlib.util.spec_from_file_location("stand_server_texture", SERVER_FILE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        server = module.make_server("127.0.0.1", 0, True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_address[1]}/terrain/texture.jpg"
            with urllib.request.urlopen(url, timeout=10) as answer:
                self.assertEqual(answer.status, 200)
                self.assertEqual(answer.headers["Content-Type"], "image/jpeg")
                self.assertIn("max-age", answer.headers["Cache-Control"])
                body = answer.read()
            self.assertEqual(body, read(TEXTURE_FILE))
            self.assertTrue(body.startswith(bytes([0xFF, 0xD8])))   # JPEG start of image
        finally:
            server.shutdown()
            server.server_close()

    def test_ui_text_is_russian(self):
        text = read(os.path.join(SCENE_DIR, "ui.js")).decode("utf-8")
        for preset in ("Рудник", "Уклоны", "Вентиляция", "Водоотлив", "Фабрика и хвосты"):
            self.assertTrue(f"'{preset}'" in text, preset)
        # The legend sentence of the page footer is not repeated inside the scene.
        scene_text = "\n".join(read(path).decode("utf-8") for path in scene_files())
        self.assertFalse("расположение в плане" in scene_text)


if __name__ == "__main__":
    unittest.main()
