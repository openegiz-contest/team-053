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
LANDSCAPE_FILE = os.path.join(TEAM_DIR, "model", "terrain", "landscape.json")
LANDSCAPE_BUDGET_BYTES = 400_000
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
        # The plain grid (the photo's) stays under 10 000; the stylised ground is cut from it (landscape.js).
        self.assertLessEqual(2 * (coarse + fine), 10000)
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

    def test_equipment_models_are_drawn_in_code(self):
        # The equipment and the buildings are low-poly models written in code
        # (models.js): no model files, no loaders, nothing but the kit.
        models = read(os.path.join(SCENE_DIR, "models.js")).decode("utf-8")
        self.assertEqual(IMPORT_RE.findall(models), ["./kit.js"])
        text = "\n".join(read(path).decode("utf-8") for path in scene_files())
        self.assertNotRegex(text, r"\b(?:GLTF|OBJ|FBX|Collada|STL|PLY|Draco)Loader\b")
        self.assertNotRegex(text, r"\.(?:glb|gltf|obj|fbx|dae|stl|ply)['\"]")
        for name in ("function truck(", "function truckLoad(", "function lhd(", "function lhdLoad(", "function rig(",
                     "function pump(", "export function fan(", "export function headframe(",
                     "export function plantLine(", "export function crusherHouse(", "export function stack(",
                     "export function pumpStation("):
            self.assertIn(name, models)
        unit_models = re.search(r"export function buildUnitModels\(\) \{(.*?)\n\}", models, re.S).group(1)
        for kind in ("haul_truck", "lhd", "drill_rig"):
            self.assertIn(kind + ":", unit_models)
        statics = read(os.path.join(SCENE_DIR, "statics.js")).decode("utf-8")
        for call in ("fan(isGhost ? new EdgeWriter(ghost, place) : new SolidWriter(solid, place)",
                     "headframe(isGhost ? new EdgeWriter(ghost, place) : new SolidWriter(solid, place)",
                     "plantLine(isGhost ? new EdgeWriter(ghost, place) : new SolidWriter(solid, place)",
                     "crusherHouse(new SolidWriter(solid,", "stack(new SolidWriter(solid,",
                     "pumpStation(new SolidWriter(solid,"):
            self.assertIn(call, statics)   # merged into the static meshes; a project is dashed

    def test_units_are_instanced_per_model(self):
        # One instanced mesh (one draw call) per unit model and one for the
        # pumps; the instance colour carries loaded or empty and the state.
        text = read(os.path.join(SCENE_DIR, "index.js")).decode("utf-8")
        self.assertIn("const unitModels = buildUnitModels();", text)
        self.assertIn("for (const kind of ['haul_truck', 'truckLoad', 'lhd', 'lhdLoad', 'drill_rig']) {", text)
        self.assertIn("units[kind] = instanced(unitModels[kind], basic(), 48);", text)
        self.assertIn("const pumps = instanced(unitModels.pump, basic(), 24);", text)
        self.assertIn("color.copy(palette.scene(v.loaded ? 'truckLoaded' : 'truckEmpty'));", text)
        # Instanced meshes in all: boxes, cones, rings, plates, the unit models (loop) and the pumps.
        self.assertLessEqual(len(re.findall(r"\binstanced\(", text)) - 1, 6)   # minus the definition
        # Picking covers every instanced mesh that carries a thing id.
        self.assertIn("const pickable = [boxes, pumps, ...Object.values(units)];", text)

    def test_surface_data_is_attributed(self):
        # The licences ask for attribution wherever the data is shown: in the scene and in the page legend.
        ui = read(os.path.join(SCENE_DIR, "ui.js")).decode("utf-8")
        for notice in ("© DLR e.V. 2010–2014, © Airbus DS 2014–2018, Copernicus",
                       "Contains modified Copernicus Sentinel data 2026", "© OpenStreetMap contributors"):
            self.assertIn(notice, ui)
        self.assertIn("root.append(style, bar, legend, credit);", ui)
        html = read(os.path.join(WEB_DIR, "index.html")).decode("utf-8")
        self.assertIn("Поверхность — рельеф Copernicus DEM, местность — OpenStreetMap (снимок Sentinel-2 30.09.2026 — "
                      "кнопка «Снимок»); подземные выработки: отметки и сечения по документам, план — схема", html)
        self.assertNotIn("Поверхность — рельеф Copernicus DEM и снимок Sentinel-2", html)
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

    def test_server_serves_the_landscape(self):
        spec = importlib.util.spec_from_file_location("stand_server_landscape", SERVER_FILE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        server = module.make_server("127.0.0.1", 0, True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_address[1]}/terrain/landscape.json"
            with urllib.request.urlopen(url, timeout=10) as answer:
                self.assertEqual(answer.status, 200)
                self.assertTrue(answer.headers["Content-Type"].startswith("application/json"))
                self.assertIn("max-age", answer.headers["Cache-Control"])
                body = answer.read()
            self.assertEqual(body, read(LANDSCAPE_FILE))
        finally:
            server.shutdown()
            server.server_close()

    def test_calm_defaults(self):
        # Review round 3: the scene opens on the whole mine, labels few twins by
        # default, draws the declines quiet and behind the stopes, and keeps the
        # x-ray backdrop in a light warm grey.
        index = read(os.path.join(SCENE_DIR, "index.js")).decode("utf-8")
        self.assertIn("const DEFAULT_VIEW = 'mine';", index)
        self.assertIn("let presetId = VIEWS[query.get('view')] ? query.get('view') : DEFAULT_VIEW;", index)
        for preset in ("mine", "declines", "vent", "water", "plant"):
            self.assertRegex(index, rf"\n  {preset}: {{ target: ")
        # Labels: the default set, the rest only under the pointer or close to the camera.
        self.assertIn("const LABEL_NEAR_M = ", index)
        self.assertIn("const ORIENTATION = new Set(['decline', 'plant', 'tailings_facility']);", index)
        self.assertIn("if (!selected && !hovered && !alarm && !core && distance > LABEL_NEAR_M) continue;", index)
        self.assertIn("F(NS + 'advisor').binding_link", index)
        statics = read(os.path.join(SCENE_DIR, "statics.js")).decode("utf-8")
        self.assertIn("id: 'place:pit', name: 'Карьер'", statics)
        # Declines: their own meshes, drawn first and without depth (behind the stopes), strong only when they matter.
        self.assertIn("export function buildDeclines(geometry, live, looks)", statics)
        self.assertNotIn("solid.tube(above", statics)
        self.assertIn("const declineMesh = new THREE.Mesh(new THREE.BufferGeometry(), basic({ depthWrite: false }));", index)
        self.assertIn("declineMesh.renderOrder = -1;", index)
        self.assertIn("backdrop.renderOrder = -2;", index)
        self.assertIn("const strong = presetId === 'declines' || tone === 'fail' || selected || id === truckDecline;", index)
        # The level label names what the level gets and what its units need.
        texts = read(os.path.join(SCENE_DIR, "texts.js")).decode("utf-8")
        self.assertIn("`подаётся ${fmt(f.air_flow_m3s, 1)} · нужно ${unit(f.air_required_m3s, 1, 'м³/с')}`", texts)
        palette = read(os.path.join(SCENE_DIR, "palette.js")).decode("utf-8")
        for name in ("soil", "soilDeep"):
            hex_value = re.search(rf"\n  {name}: '#([0-9a-f]{{6}})'", palette).group(1)
            channels = [int(hex_value[i:i + 2], 16) for i in (0, 2, 4)]
            self.assertGreaterEqual(min(channels), 0x34, name)                 # not a dark brown
            self.assertLessEqual(max(channels) - min(channels), 0x10, name)    # a grey, warm at most

    def test_ride_with_a_truck(self):
        # «Проезд с самосвалом»: the camera rides with a truck on its way; the
        # same button, Esc or a drag returns the orbit camera; no geometry of its own.
        ui = read(os.path.join(SCENE_DIR, "ui.js")).decode("utf-8")
        self.assertIn("text: 'Проезд с самосвалом'", ui)
        self.assertIn("onRide(rideButton.getAttribute('aria-pressed') !== 'true')", ui)
        index = read(os.path.join(SCENE_DIR, "index.js")).decode("utf-8")
        self.assertIn("const MOVING_TRUCK = new Set(['surface_haul', 'descending', 'tram_level', 'hauling_up']);", index)
        self.assertIn("if (event.key === 'Escape' && ride) leaveRide(true);", index)
        self.assertIn("if (ride && press && Math.hypot(event.clientX - press.x, event.clientY - press.y) > 5) leaveRide(true);", index)
        self.assertIn("document.removeEventListener('keydown', onKeyDown);", index)
        self.assertIn("if (restore) flyTo(before.target, before.position);", index)
        # The caption is the truck's label: its short name and its status line.
        self.assertIn("return { name: shortName(ride.id, things), line: status.text, tone: status.tone };", index)

    def test_ui_text_is_russian(self):
        text = read(os.path.join(SCENE_DIR, "ui.js")).decode("utf-8")
        for preset in ("Рудник", "Уклоны", "Вентиляция", "Водоотлив", "Фабрика и хвосты"):
            self.assertTrue(f"'{preset}'" in text, preset)
        # The legend sentence of the page footer is not repeated inside the scene.
        scene_text = "\n".join(read(path).decode("utf-8") for path in scene_files())
        self.assertFalse("расположение в плане" in scene_text)



class Landscape(unittest.TestCase):
    """The stylised surface (spec 4.2): OSM data in model/terrain/landscape.json, drawn by landscape.js."""

    @classmethod
    def setUpClass(cls):
        cls.raw = read(LANDSCAPE_FILE)
        cls.data = json.loads(cls.raw.decode("utf-8"))

    def test_file_is_small_lf_and_attributed(self):
        self.assertLess(len(self.raw), LANDSCAPE_BUDGET_BYTES)
        self.assertNotIn(b"\r", self.raw)
        about = self.data["about"]
        for part in ("OpenStreetMap contributors", "Open Database License", "build_landscape.py", "ATTRIBUTION.md"):
            self.assertIn(part, about)
        text = self.raw.decode("utf-8")
        for raw in ('"uid"', '"user"', '"changeset"', '"timestamp"', '"version"', '"tags"', '"nodes"'):
            self.assertNotIn(raw, text)

    def test_geometry_is_quantised_inside_the_square(self):
        def coords(flat):
            self.assertEqual(len(flat) % 2, 0)
            for v in flat:
                self.assertLessEqual(abs(v), 2000)
                self.assertEqual(v * 2, int(v * 2))   # multiples of 0.5 m
            return list(zip(flat[0::2], flat[1::2]))

        def area(ring):
            return sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:] + ring[:1])) / 2

        order = self.data["class_order"]
        for item in self.data["areas"]:
            self.assertIn(item["class"], order)
            ring = coords(item["ring"])
            self.assertGreaterEqual(len(ring), 3)
            self.assertGreater(area(ring), 0)      # counter-clockwise in (x, z)
        ranks = [order.index(a["class"]) for a in self.data["areas"]]
        self.assertEqual(ranks, sorted(ranks))   # listed in drawing order
        self.assertEqual(sum(1 for a in self.data["areas"] if a["class"] == "pit"), 1)
        for item in self.data["heaps"]:
            self.assertGreater(area(coords(item["ring"])), 0)
            self.assertGreaterEqual(item["rise"], 2)
        for item in self.data["buildings"]:
            self.assertGreater(area(coords(item["ring"])), 0)
            if "levels" in item:
                self.assertGreater(item["levels"], 0)
        for key in ("roads", "waterways", "barriers"):
            for item in self.data[key]:
                self.assertGreaterEqual(len(coords(item["line"])), 2)
        counts = self.data["counts"]
        self.assertEqual(counts["buildings"], len(self.data["buildings"]))
        self.assertEqual(counts["roads"], len(self.data["roads"]))

    def test_landscape_is_the_default_and_the_photo_a_switch(self):
        index = read(os.path.join(SCENE_DIR, "index.js")).decode("utf-8")
        ui = read(os.path.join(SCENE_DIR, "ui.js")).decode("utf-8")
        landscape = read(os.path.join(SCENE_DIR, "landscape.js")).decode("utf-8")
        self.assertIn("export const LANDSCAPE_URL = '/terrain/landscape.json';", landscape)
        self.assertIn("fetch(LANDSCAPE_URL)", index)
        self.assertIn("let photoOn = false;", index)
        # The image is loaded only when «Снимок» is first turned on, and drawn at once.
        show = re.search(r"\n  function showSurface\(\) \{\n(.*?)\n  \}\n", index, re.S)
        self.assertIsNotNone(show)
        self.assertIn("new THREE.TextureLoader().load(TEXTURE_URL", show.group(1))
        self.assertIn("drawNow(true);", show.group(1))
        self.assertIn("text: 'Снимок'", ui)
        self.assertIn("onPhoto(photoButton.getAttribute('aria-pressed') !== 'true')", ui)

    def test_models_are_instanced_and_share_the_xray_window(self):
        landscape = read(os.path.join(SCENE_DIR, "landscape.js")).decode("utf-8")
        terrain = read(os.path.join(SCENE_DIR, "terrain.js")).decode("utf-8")
        # Houses, blocks and trees: instanced meshes made in one place, with the instanced x-ray material.
        self.assertEqual(landscape.count("new THREE.InstancedMesh("), 1)
        self.assertIn("new THREE.InstancedMesh(geometry, materials.instances,", landscape)
        for model in ("instancedOf(houseGeometry(", "instancedOf(treeGeometry(", "instancedOf(facetGeometry(boxFaces("):
            self.assertIn(model, landscape)
        self.assertIn("new THREE.Mesh(merged.geometry, materials.models)", landscape)
        self.assertIn("new THREE.Mesh(ribbons.geometry, materials.models)", landscape)
        # One x-ray shader for the ground and the models; contour lines only on the ground.
        self.assertEqual(terrain.count("m.onBeforeCompile = (shader) => xrayShader(shader, uniforms, inject);"), 1)
        self.assertIn("make('sekis-ground', { color: fallback.clone() }, { contours: true })", terrain)
        self.assertIn("make('sekis-instances', {}, { instanced: true })", terrain)

    def test_surface_overlays_fade_in_the_xray_window(self):
        # Review: in the underground views the houses, trees, walls, roads,
        # streams and the land-cover colours hid the workings. They now fade
        # with the ground's x-ray weight, much further than the ground.
        terrain = read(os.path.join(SCENE_DIR, "terrain.js")).decode("utf-8")
        landscape = read(os.path.join(SCENE_DIR, "landscape.js")).decode("utf-8")
        index = read(os.path.join(SCENE_DIR, "index.js")).decode("utf-8")
        statics = read(os.path.join(SCENE_DIR, "statics.js")).decode("utf-8")
        kit = read(os.path.join(SCENE_DIR, "kit.js")).decode("utf-8")
        ground = float(re.search(r"export const XRAY_ALPHA = ([0-9.]+);", terrain).group(1))
        overlay = float(re.search(r"export const XRAY_OVERLAY = ([0-9.]+);", terrain).group(1))
        self.assertLessEqual(overlay, ground / 3)
        grey = float(re.search(r"export const XRAY_GREY = ([0-9.]+);", terrain).group(1))
        self.assertGreater(grey, 0.5)
        # The same trigger as the ground: one weight, set together in setXray.
        self.assertIn("uniforms.xrayOverlay.value = ellipsoid ? XRAY_OVERLAY : 1;", terrain)
        self.assertIn("const look = contours ? CONTOUR_FRAGMENT + XRAY_GROUND : lines ? XRAY_LINES : XRAY_MODELS;", terrain)
        # The models blend over the translucent ground: drawn after it.
        self.assertIn("ground.renderOrder = 3;", index)
        self.assertEqual(landscape.count("mesh.renderOrder = 4;"), 3)
        self.assertNotIn("mesh.renderOrder = 2;", landscape)
        # The thin lines of the scenery thin out; the lines under the ground keep their strength.
        self.assertIn("make('sekis-lines', { transparent: false }, { lines: true }, THREE.LineBasicMaterial)", terrain)
        self.assertIn("const thinLines = new THREE.LineSegments(new THREE.BufferGeometry(), groundLook.lines);", index)
        self.assertIn("geometry.setAttribute('xraySurface',", kit)
        self.assertIn("lines.use(null, palette.scene(tint), true).path(path);", statics)
        self.assertIn("lines.use(id, palette.stope('standby')).boxEdges(", statics)
        # No new draw call: no new scene object for the fade.
        self.assertEqual(index.count("new THREE.LineSegments("), 4)

    def test_tree_and_building_counts_fit_the_budget(self):
        # Spec 4.5: at most 60 000 triangles in all. A tree takes 13 triangles, a house 14.
        landscape = read(os.path.join(SCENE_DIR, "landscape.js")).decode("utf-8")
        caps = re.search(r"const TREE_CAP = \{ wood: (\d+), river: (\d+), park: (\d+) \};", landscape)
        self.assertIsNotNone(caps)
        trees = sum(int(v) for v in caps.groups())
        self.assertLessEqual(trees, 1000)
        self.assertLessEqual(13 * trees + 14 * len(self.data["buildings"]), 20_000)


if __name__ == "__main__":
    unittest.main()
