// 3D scene of the Sekisovskoye twin (spec section 4, work package D1).
//
// View contract (spec 4.6): mount(container, geometry) returns
// { update(state), focus(thingId), dispose() }. `geometry` is the answer of
// GET /api/geometry, `state` the answer of GET /api/state (every 2 s). A click
// on an object dispatches a bubbling 'sekis:select' event on the container.
// mount() throws when no WebGL context can be created; the page then mounts the
// long section in this container.
//
// The ground is the stylised landscape of landscape.js (land cover, roads,
// water, buildings, trees, heaps from OpenStreetMap on the real terrain); the
// «Снимок» button puts the Sentinel-2 image on the terrain instead.
//
// Budget (spec 4.5): no lights, shadows or post-processing; one texture (the
// satellite image on the terrain, served by the Stand at /terrain/texture.jpg
// and loaded only when «Снимок» is first turned on); static geometry merged
// into a few objects (buildings and fixed equipment are low-poly models merged
// into them, models.js; the houses and trees of the landscape are instanced);
// moving things are instances:
// one mesh per unit model (truck, its load, LHD, its load, drill rig), the
// pumps, and boxes, cones and rings for the rest; antialias off, pixel ratio 1, canvas at most 1280 x 720; a
// frame is drawn only while something moves and at most 12 times a second. The
// one exception is a frame that must not wait: after mount, the first state, a
// canvas resize (which clears the buffer), the scene being shown again, the
// landscape or the image arriving, the frame is drawn at once (see drawNow).
// `?debug=1` in the page address shows triangle and draw-call counts;
// `?view=<preset>` (mine, declines, vent, water, plant) opens the scene in a
// preset; without it the scene opens on the declines (DEFAULT_VIEW).

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { NS, stateTone } from '../panels/dict.js';
import { el, fmt, isNum } from '../panels/format.js';
import { LIGHT_DIR, cumulative, faceShade, pointAlong } from './kit.js';
import { MAX_LABELS, createLabels } from './labels.js';
import { LANDSCAPE_URL, buildLandscape } from './landscape.js';
import { buildNetwork } from './network.js';
import { PLINTH, PUMP_SIZE, buildUnitModels } from './models.js';
import { createPalette } from './palette.js';
import { buildStatics } from './statics.js';
import {
  TEXTURE_URL, XRAY_EDGE, chordInEllipsoid, createTerrain, groundOpacity, terrainMaterial, xrayBackdrop,
} from './terrain.js';
import { shortName, statusLine } from './texts.js';
import { createOverlay } from './ui.js';

const FRAME_MS = 1000 / 12;
const MAX_CANVAS = [1280, 720];
const FOV = 32;
const DEG = Math.PI / 180;
const VEHICLE_KINDS = new Set(['haul_truck', 'lhd', 'drill_rig']);
const THIN_KINDS = new Set(['decline', 'level', 'shaft', 'raise', 'main_fan', 'pump_station', 'monitoring_point']);
const RING_STATES = new Set(['waiting_bay', 'held_vent', 'standby_vent', 'maintenance']);
const IDLE_STOPE = new Set(['standby', 'planned', 'preparation', 'backfilling']);
const ALARM_TONES = new Set(['fail', 'flood', 'warn']);
// Drawn length of a working unit at the preset distances, in CSS pixels of a
// scene about 820 px high (a smaller scene gets up to 28 % less). Closer than
// FULL_SIZE_AT the minimum shrinks, so that near units return to their true
// size instead of crowding each other; parked units are always drawn to scale.
const MIN_PIXELS = { haul_truck: 38, lhd: 30, drill_rig: 32 };
const FULL_SIZE_AT = [250, 900];   // m from the camera: no minimum … the whole minimum
const MAX_UNIT_SCALE = 12;
const PUMP_PIXELS = 10;   // drawn length of a pump at the preset distances
const STOUT = 1.45;      // working units are drawn thicker than to scale, to stay visible
const MAX_JUMP = 1900;   // m: a longer move between two samples is shown as a jump
const MAX_PITCH = 14 * Math.PI / 180;   // a unit is drawn pitched along a decline, never steeper

// Camera presets: the target, the direction the camera looks from (azimuth
// from the south towards the east, elevation above the horizon) and distance.
// The workings lie under the old pit (x -500 … +215, z -180 … +75); the plant
// is 0.9 km east-north-east and the tailings 1.1–1.5 km north-east of the pit.
const VIEWS = {
  mine: { target: [-120, 70, -40], azimuth: -24, elevation: 27, distance: 2350 },
  declines: { target: [20, 175, -30], azimuth: -12, elevation: 24, distance: 1900 },
  vent: { target: [-142, 200, -87], azimuth: 30, elevation: 24, distance: 1700 },
  water: { target: [-40, 200, -60], azimuth: -38, elevation: 25, distance: 1750 },
  plant: { target: [560, 440, -820], azimuth: -28, elevation: 34, distance: 2350 },
};

// The scene opens on the declines: both of them, the trucks on them and the
// portal yard, whatever the trucks are doing at that moment; `?view=` opens
// another preset.
const DEFAULT_VIEW = 'declines';

// Which kinds get a label first in each preset (0–100). Abnormal states and
// the selected twin are labelled in every preset.
const LABEL_WEIGHTS = {
  mine: { decline: 90, plant: 85, tailings_facility: 85, rom_stockpile: 75, pump_station: 62, shaft: 50,
    stope: 55, haul_truck: 45 },
  declines: { decline: 95, haul_truck: 80, level: 45, stope: 42 },
  vent: { main_fan: 95, shaft: 90, raise: 85, level: 60 },
  water: { pump_station: 95, monitoring_point: 85, settling_pond: 75, plant: 40, tailings_facility: 40 },
  plant: { plant: 100, tailings_facility: 96, rom_stockpile: 92, tailings_dam: 80, plant_line: 70,
    settling_pond: 60, monitoring_point: 60 },
};
// A preset is also a theme: these kinds are drawn darker so that the subject of
// the preset stands out (the hue, which carries the state, is kept).
const DIMMED = { vent: { decline: 0.42 }, water: { decline: 0.42, shaft: 0.6, raise: 0.6 } };
// Twins without a place of their own are shown by a preset.
const KIND_VIEW = { enterprise: 'mine', mine: 'mine', water_system: 'water' };

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const X_AXIS = new THREE.Vector3(1, 0, 0);
const Y_AXIS = new THREE.Vector3(0, 1, 0);

function viewPosition(view) {
  const a = view.azimuth * DEG;
  const e = view.elevation * DEG;
  return new THREE.Vector3(
    view.target[0] + view.distance * Math.sin(a) * Math.cos(e),
    view.target[1] + view.distance * Math.sin(e),
    view.target[2] + view.distance * Math.cos(a) * Math.cos(e));
}

/** Bake the face shade into a colour attribute, so that the mesh needs no light. */
function shaded(geometry) {
  const normal = geometry.getAttribute('normal');
  const colors = new Float32Array(normal.count * 3);
  for (let i = 0; i < normal.count; i += 1) {
    colors.fill(faceShade(normal.getX(i), normal.getY(i), normal.getZ(i)), i * 3, i * 3 + 3);
  }
  geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
  return geometry;
}

/** Instanced mesh refilled every frame: begin(), add(...), end(). */
function instanced(geometry, material, capacity) {
  const mesh = new THREE.InstancedMesh(geometry, material, capacity);
  mesh.frustumCulled = false;
  // A fixed sphere: three.js would otherwise keep the one of the first frame.
  mesh.boundingSphere = new THREE.Sphere(new THREE.Vector3(0, 100, 0), 9000);
  mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
  mesh.setColorAt(0, new THREE.Color(1, 1, 1));
  mesh.instanceColor.setUsage(THREE.DynamicDrawUsage);
  mesh.count = 0;
  const ids = new Array(capacity).fill(null);
  const matrix = new THREE.Matrix4();
  let n = 0;
  return {
    mesh,
    ids,
    begin() {
      n = 0;
    },
    add(position, quaternion, scale, color, id) {
      if (n >= capacity) return;
      matrix.compose(position, quaternion, scale);
      mesh.setMatrixAt(n, matrix);
      mesh.setColorAt(n, color);
      ids[n] = id || null;
      n += 1;
    },
    end() {
      mesh.count = n;
      mesh.instanceMatrix.needsUpdate = true;
      mesh.instanceColor.needsUpdate = true;
    },
  };
}

export async function mount(container, geometry) {
  if (!geometry || typeof geometry.objects !== 'object') throw new Error('scene3d: geometry has no objects');

  // ------------------------------------------------------------ renderer
  const canvas = document.createElement('canvas');
  const contextAttributes = {
    alpha: false, antialias: false, depth: true, stencil: false, powerPreference: 'low-power',
    premultipliedAlpha: true, preserveDrawingBuffer: false,
  };
  const gl = canvas.getContext('webgl2', contextAttributes) || canvas.getContext('webgl', contextAttributes);
  if (!gl) throw new Error('scene3d: a WebGL context cannot be created in this browser');
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ canvas, context: gl, antialias: false, alpha: false, stencil: false });
  } catch (error) {
    throw new Error('scene3d: the WebGL renderer did not start: ' + (error && error.message));
  }
  renderer.setPixelRatio(1);
  renderer.sortObjects = true;

  const query = new URLSearchParams(location.search);
  const debugOn = query.get('debug') === '1';
  const palette = createPalette();
  const objects = geometry.objects;
  const root = el('div', { class: 's3d-root' });
  root.append(canvas);
  container.append(root);

  const scene = new THREE.Scene();
  scene.background = palette.scene('background');
  scene.fog = new THREE.Fog(palette.scene('background').getHex(), 4200, 11000);
  const camera = new THREE.PerspectiveCamera(FOV, 2, 25, 12000);
  const labels = createLabels(root, scene);

  // ------------------------------------------------------- scene objects
  const white = new THREE.Color(1, 1, 1);
  const basic = (options) => new THREE.MeshBasicMaterial({ vertexColors: true, ...options });

  // The ground: drawn after everything else, opaque except where the line of
  // sight runs on into the workings (the x-ray cut, terrain.js). It writes
  // depth, so that a near hill hides the ground behind it. Until the landscape
  // has arrived it is the plain grid in the meadow colour; the landscape models
  // (houses, trees, heaps, walls) share its x-ray window.
  const terrain = createTerrain(geometry.terrain);
  const groundLook = terrainMaterial(palette.cover('meadow'), LIGHT_DIR);
  const ground = new THREE.Mesh(terrain ? terrain.geometry : new THREE.BufferGeometry(), groundLook.material);
  ground.renderOrder = 3;
  ground.visible = Boolean(terrain);
  // Picking and the ground tests use the plain grid, whatever is drawn (never added to the scene).
  const groundPick = new THREE.Mesh(ground.geometry);
  let groundTexture = null;
  let landscape = null;
  let photoOn = false;
  let photoLoading = false;
  // Behind the workings, seen through the x-ray window: soil, not the page.
  const backdrop = new THREE.Mesh(new THREE.BufferGeometry(), basic({ side: THREE.BackSide }));
  backdrop.visible = false;
  const solidMesh = new THREE.Mesh(new THREE.BufferGeometry(), basic());
  // The fills are pulled a little towards the eye: a low fill level that meets the ground does not flicker.
  const fillMesh = new THREE.Mesh(new THREE.BufferGeometry(),
    basic({ polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -2 }));
  const ghostLines = new THREE.LineSegments(new THREE.BufferGeometry(),
    new THREE.LineDashedMaterial({ vertexColors: true, dashSize: 9, gapSize: 8 }));
  const thinLines = new THREE.LineSegments(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ vertexColors: true }));
  const rulerLines = new THREE.LineSegments(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ vertexColors: true }));

  const boxes = instanced(shaded(new THREE.BoxGeometry(1, 1, 1)), basic(), 320);
  // The units and the pumps: one instanced mesh per model; the colour of an
  // instance tints the paint of its model (models.js).
  const unitModels = buildUnitModels();
  const units = {};
  for (const kind of ['haul_truck', 'truckLoad', 'lhd', 'lhdLoad', 'drill_rig']) {
    units[kind] = instanced(unitModels[kind], basic(), 48);
  }
  const pumps = instanced(unitModels.pump, basic(), 24);
  const pickable = [boxes, pumps, ...Object.values(units)];
  const cones = instanced(shaded(new THREE.ConeGeometry(1, 2.4, 8)), basic(), 64);
  const rings = instanced(new THREE.RingGeometry(0.8, 1, 24),
    new THREE.MeshBasicMaterial({ depthTest: false, depthWrite: false, side: THREE.DoubleSide, fog: false }), 40);
  rings.mesh.renderOrder = 10;
  const plateGeometry = new THREE.PlaneGeometry(1, 1);
  plateGeometry.rotateX(-Math.PI / 2);
  const plates = instanced(plateGeometry,
    new THREE.MeshBasicMaterial({ transparent: true, opacity: 0.13, side: THREE.DoubleSide, depthWrite: false }), 24);
  plates.mesh.renderOrder = 1;
  const water = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), new THREE.MeshBasicMaterial({
    color: palette.scene('water'), transparent: true, opacity: 0.3, depthWrite: false, side: THREE.DoubleSide }));
  water.renderOrder = 2;
  water.visible = false;

  const stockId = Object.keys(objects).find((id) => objects[id].kind === 'rom_stockpile' && objects[id].base);
  const stockObject = stockId ? objects[stockId] : null;
  const stock = new THREE.Mesh(
    shaded(new THREE.ConeGeometry(stockObject ? stockObject.radius || 30 : 30, stockObject ? stockObject.height || 22 : 22, 14)),
    basic({ color: palette.scene('ore') }));
  stock.geometry.translate(0, (stockObject ? stockObject.height || 22 : 22) / 2, 0);
  stock.visible = Boolean(stockObject);
  if (stockObject) stock.position.fromArray(stockObject.base);

  scene.add(solidMesh, fillMesh, thinLines, ghostLines, rulerLines, boxes.mesh, cones.mesh, stock, plates.mesh, water,
    backdrop, ground, rings.mesh, pumps.mesh, ...Object.values(units).map((unit) => unit.mesh));

  // ---------------------------------------------------------- live state
  let things = {};
  let lastState = null;
  let lastFreshAt = 0;
  let sampleMs = 2000;
  let statics = null;
  let lastSignature = null;
  let selectedId = null;
  let gradeMode = false;
  let presetId = VIEWS[query.get('view')] ? query.get('view') : DEFAULT_VIEW;
  let dirty = true;
  let disposed = false;
  let stateDrawn = false;

  const F = (id) => (things[id] && things[id].f) || {};
  const live = {
    isGhost(id) {
      const state = F(id).state;
      if (typeof state === 'string') return state === 'planned';
      return Boolean(objects[id] && objects[id].planned);
    },
    bottom(id) {
      const value = F(id).bottom_elevation;
      if (isNum(value)) return value;
      const o = objects[id] || {};
      return isNum(o.bottom_elevation) ? o.bottom_elevation : isNum(o.design_bottom) ? o.design_bottom : -1e9;
    },
    /** A connection marked planned in the geometry is open once its far end exists. */
    linkOpen(level, link) {
      const target = objects[link.to];
      if (!target) return false;
      if (target.kind === 'decline') return live.bottom(link.to) <= level.elevation + 0.5;
      if (live.isGhost(link.to)) return false;
      if (target.planned_below !== undefined) return level.elevation >= target.planned_below;
      return true;
    },
  };

  function signature() {
    let text = '';
    for (const [id, o] of Object.entries(objects)) {
      if (VEHICLE_KINDS.has(o.kind)) continue;
      text += live.isGhost(id) ? '1' : '0';
      if (o.kind === 'decline') text += Math.round(live.bottom(id)) + ';';
    }
    return text;
  }

  const labelPositions = new Map();
  function rebuildStatics() {
    const next = buildStatics(geometry, palette, live, terrain);
    for (const [object, built] of [[solidMesh, next.solid], [fillMesh, next.fills], [ghostLines, next.ghost],
      [thinLines, next.lines], [rulerLines, next.ruler]]) {
      object.geometry.dispose();
      object.geometry = built.geometry;
    }
    ghostLines.computeLineDistances();
    if (next.rulerAt) rulerLines.position.fromArray(next.rulerAt);
    rulerLines.visible = Boolean(next.rulerAt);
    labelPositions.clear();
    for (const [id, anchor] of next.anchors) labelPositions.set(id, new THREE.Vector3().fromArray(anchor));
    for (const place of next.places) labelPositions.set(place.id, new THREE.Vector3().fromArray(place.position));
    groundLook.setXray(next.xray);
    const wall = terrain && xrayBackdrop(next.xray, terrain.heightAt, palette.scene('soil'), palette.scene('soilDeep'));
    backdrop.geometry.dispose();
    backdrop.geometry = wall || new THREE.BufferGeometry();
    backdrop.visible = Boolean(wall);
    statics = next;
  }

  // -------------------------------------------------------------- camera
  const controls = new OrbitControls(camera, root);
  controls.enableDamping = false;
  controls.enableZoom = false;      // the wheel scrolls the page until the scene is clicked
  controls.zoomSpeed = 0.9;
  controls.rotateSpeed = 0.7;
  controls.minDistance = 90;
  controls.maxDistance = 5200;
  controls.maxPolarAngle = 100 * DEG;
  controls.target.fromArray(VIEWS[presetId].target);
  camera.position.copy(viewPosition(VIEWS[presetId]));
  controls.update();
  let fly = null;
  controls.addEventListener('change', () => {
    dirty = true;
  });
  controls.addEventListener('start', () => {
    fly = null;   // a drag takes over from a camera flight
  });

  function flyTo(target, position, duration = 700) {
    fly = {
      fromTarget: controls.target.clone(), toTarget: target.clone(),
      fromPosition: camera.position.clone(), toPosition: position.clone(),
      startedAt: performance.now(), duration,
    };
    dirty = true;
  }

  const size = { width: 0, height: 0 };
  function resize() {
    const width = container.clientWidth;
    const height = container.clientHeight;
    const wasHidden = !size.width || !size.height;
    size.width = width;
    size.height = height;
    if (!width || !height) return;
    const k = Math.min(1, MAX_CANVAS[0] / width, MAX_CANVAS[1] / height);
    const pixelWidth = Math.max(1, Math.round(width * k));
    const pixelHeight = Math.max(1, Math.round(height * k));
    // Setting the canvas size clears the drawing buffer, even to the same value.
    const cleared = canvas.width !== pixelWidth || canvas.height !== pixelHeight;
    if (cleared) renderer.setSize(pixelWidth, pixelHeight, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    labels.setSize(width, height);
    dirty = true;
    labelsDueAt = 0;
    // A cleared buffer is refilled in this same frame: if the redraw waited for
    // the next animation frame, the page could be painted (or captured) with an
    // empty, black canvas in between.
    drawNow(cleared || wasHidden);
  }
  const worldPerPixel = (position) => (2 * Math.tan((FOV * DEG) / 2) * camera.position.distanceTo(position))
    / Math.max(1, size.height);

  // ------------------------------------------------------------- overlay
  /** A preset is a camera position and a theme (which labels come first, what is dimmed). */
  function applyPreset(id) {
    presetId = id;
    overlay.setPreset(id);
    const view = VIEWS[id];
    flyTo(new THREE.Vector3().fromArray(view.target), viewPosition(view));
    derive(performance.now(), false);
    labelsDueAt = 0;
  }
  const overlay = createOverlay(root, palette, {
    onPreset: applyPreset,
    onPhoto(on) {
      photoOn = on;
      overlay.setPhoto(on);
      showSurface();
    },
    onGrade(on) {
      gradeMode = on;
      overlay.setGrade(on);
      derive(performance.now(), false);
      labelsDueAt = 0;
      dirty = true;
    },
    onZoom(direction) {
      const offset = camera.position.clone().sub(controls.target);
      const distance = clamp(offset.length() * (direction > 0 ? 0.72 : 1.39), controls.minDistance, controls.maxDistance);
      flyTo(controls.target, controls.target.clone().add(offset.setLength(distance)), 260);
    },
  });
  overlay.setPreset(presetId);

  // ----------------------------------------------- derived, per state sample
  const network = buildNetwork(geometry);
  const vehicles = new Map();     // id -> moving unit
  const stopeFx = new Map();      // stope id -> { state, flashUntil }
  const flowPhase = new Map();    // flow key -> phase 0..1
  let fixed = [];                 // boxes that do not move between samples
  let pumpList = [];              // pumps on the plinths of the stations, coloured by pump
  let flows = [];                 // beads travelling along pipes and the conveyor
  let arrows = [];                // air flow in shafts and raises
  let plateList = [];
  let waterTarget = null;         // elevation of the water surface, or null
  let waterLevel = null;
  let waterFloor = 0;
  let blastWindow = false;

  const tmpColor = new THREE.Color();
  function paint(built, key, color, selected, dim = 1) {
    tmpColor.copy(color);
    if (selected) tmpColor.lerp(white, 0.45);
    else if (dim !== 1) tmpColor.multiplyScalar(dim);
    return built.setColor(key, tmpColor);
  }

  function stopeColor(id, out) {
    const f = F(id);
    if (f.state === 'flooded') return out.copy(palette.stope('flooded'));
    if (gradeMode && isNum(f.grade)) return palette.grade(f.grade, out);
    return out.copy(palette.stope(f.state));
  }

  function levelLook(id, restricted) {
    const f = F(id);
    if (f.state === 'flooded') return { drive: palette.tone('flood'), plate: palette.tone('flood') };
    const short = isNum(f.air_flow_m3s) && isNum(f.air_required_m3s) && f.air_required_m3s > 0
      && f.air_flow_m3s < f.air_required_m3s * 0.98;
    // While the mine holds units for lack of air, every ventilated level is marked.
    if (short || (restricted && isNum(f.air_required_m3s) && f.air_required_m3s > 0)) {
      return { drive: palette.tone('warn'), plate: palette.tone('warn') };
    }
    if (f.state === 'mined_out') return { drive: palette.scene('driveQuiet'), plate: palette.scene('plateQuiet') };
    return { drive: palette.scene('drive'), plate: palette.scene('plate') };
  }

  function addFlow(list, key, points, { size, color, spacing = 70, speed = 60, reverse = false, offset = null }) {
    if (!Array.isArray(points) || points.length < 2) return;
    let path = reverse ? points.slice().reverse() : points;
    if (offset) path = path.map((p) => [p[0] + offset[0], p[1] + offset[1], p[2] + offset[2]]);
    const cum = cumulative(path);
    const length = cum[cum.length - 1];
    if (!(length > 1)) return;
    list.push({ key, path, cum, length, size, color, speed, count: Math.max(2, Math.round(length / spacing)) });
  }

  /** Recompute colours and all non-moving instances from the twin state. */
  function derive(now, fresh) {
    if (!statics) return;
    const mine = F(NS + 'mine');
    const waterSystem = F(NS + 'water');
    const plant = F(NS + 'plant');
    const restricted = mine.state === 'restricted_air';
    blastWindow = F(NS + 'enterprise').shift === 'blast';
    const nextFixed = [];
    const nextFlows = [];
    const nextArrows = [];
    const nextPlates = [];
    const nextPumps = [];
    const flooded = [];
    let lowest = Infinity;
    const dimmed = DIMMED[presetId] || {};
    const box = (x, y, z, sx, sy, sz, color, id, fx) => nextFixed.push({
      position: new THREE.Vector3(x, y, z), scale: new THREE.Vector3(sx, sy, sz), color: color.clone(), id, fx: fx || null,
    });

    for (const [id, o] of Object.entries(objects)) {
      if (VEHICLE_KINDS.has(o.kind)) continue;
      const thing = things[id];
      const f = (thing && thing.f) || {};
      const selected = id === selectedId;
      const ghost = live.isGhost(id);
      const tone = thing && typeof f.state === 'string' ? stateTone(f.state, o.kind) : null;

      if (o.kind === 'level') {
        if (ghost) continue;
        const look = levelLook(id, restricted);
        paint(statics.solid, id, look.drive, selected);
        lowest = Math.min(lowest, o.elevation);
        if (f.state === 'flooded') flooded.push(o.elevation);
        if (o.extent) {
          nextPlates.push({
            position: new THREE.Vector3((o.extent[0] + o.extent[2]) / 2, o.elevation - 2.2, (o.extent[1] + o.extent[3]) / 2),
            scale: new THREE.Vector3(o.extent[2] - o.extent[0], 1, o.extent[3] - o.extent[1]),
            color: look.plate,
          });
        }
      } else if (o.kind === 'stope') {
        if (ghost || !thing) continue;
        const fill = stopeColor(id, new THREE.Color());
        paint(statics.lines, id, tmpColor.copy(fill).lerp(white, 0.3).clone(), selected);
        const initial = (thing.attrs && isNum(thing.attrs.ore_initial_t) && thing.attrs.ore_initial_t) || 90000;
        let part = isNum(f.ore_remaining_t) ? clamp(f.ore_remaining_t / initial, 0, 1) : 1;
        if (f.state === 'backfilling' && isNum(f.backfill_pct)) part = clamp(f.backfill_pct / 100, 0, 1);
        const h = Math.max(1.5, part * o.size[1] * 0.985);
        if (selected) fill.lerp(white, 0.4);
        const fx = stopeFx.get(id) || { state: null, flashUntil: 0 };
        if (fresh) {
          if (fx.state && fx.state !== 'ventilating' && f.state === 'ventilating') fx.flashUntil = now + 3600;
          fx.state = f.state;
          stopeFx.set(id, fx);
        }
        fx.pulse = f.state === 'awaiting_blast' && blastWindow;
        box(o.center[0], o.center[1] - o.size[1] / 2 + h / 2 + 0.2, o.center[2],
          o.size[0] * 0.985, h, o.size[2] * 0.95, fill, id, fx);
      } else if (o.kind === 'decline') {
        if (tone) paint(statics.solid, id, palette.tone(tone), selected, dimmed.decline);
      } else if (o.kind === 'shaft' || o.kind === 'raise') {
        if (ghost) continue;
        const flow = isNum(f.air_flow_m3s) ? f.air_flow_m3s : 0;
        paint(statics.solid, id, flow > 0 || !thing ? palette.scene('airway') : palette.tone('idle'), selected, dimmed[o.kind]);
        const from = Math.max(o.base[1], o.planned_below === undefined ? o.base[1] : o.planned_below);
        if (flow > 0 && o.top - from > 20) {
          const down = o.direction !== 'exhaust';
          nextArrows.push({
            key: id, x: o.base[0], z: o.base[2], from: down ? o.top : from, to: down ? from : o.top,
            radius: clamp(2.6 + flow * 0.036, 2.6, 13),
            speed: 26 + 2.2 * (isNum(f.air_velocity_ms) ? f.air_velocity_ms : 8),
            color: palette.scene(down ? 'airIntake' : 'airExhaust'),
            count: Math.max(2, Math.round((o.top - from) / 75)),
          });
        }
      } else if (o.kind === 'main_fan') {
        if (!ghost && tone) paint(statics.solid, id, palette.tone(tone), selected);
      } else if (o.kind === 'pump_station') {
        if (ghost || !thing) continue;
        paint(statics.solid, id, palette.tone(tone || 'idle'), selected);
        paint(statics.lines, id + '#gauge', palette.tone(tone === 'ok' ? 'info' : tone || 'info'), false);
        const pumped = isNum(f.pumped_m3h) ? f.pumped_m3h : 0;
        paint(statics.lines, id + '#pipe', pumped > 0 ? palette.scene('water') : tone === 'fail' ? palette.tone('fail') : palette.scene('pipe'), false);
        const gauge = statics.gauges.get(id);
        if (gauge && isNum(f.sump_level_pct)) {
          const h = gauge.size[1] * clamp(f.sump_level_pct / 100, 0, 1);
          if (h > 0.4) {
            box(gauge.center[0], gauge.center[1] - gauge.size[1] / 2 + h / 2, gauge.center[2],
              gauge.size[0] * 0.78, h, gauge.size[2] * 0.78, palette.scene('water'), id);
          }
        }
        const total = (thing.attrs && isNum(thing.attrs.pumps_total) && thing.attrs.pumps_total) || 0;
        const available = isNum(f.pumps_available) ? f.pumps_available : total;
        const running = isNum(f.pumps_running) ? f.pumps_running : 0;
        // The pumps stand in a row on the plinth: running, ready or out of service.
        for (let i = 0; i < total; i += 1) {
          const color = i < running ? palette.tone('ok') : i < available ? palette.tone('info') : palette.tone('fail');
          nextPumps.push({
            position: new THREE.Vector3(o.center[0] - o.size[0] / 2 + 3 + i * 7,
              o.center[1] - o.size[1] / 2 + PLINTH + PUMP_SIZE[1] / 2, o.center[2]),
            center: new THREE.Vector3(o.center[0], o.center[1] - o.size[1] / 2 + PLINTH, o.center[2]),
            color: (selected ? tmpColor.copy(color).lerp(white, 0.45) : color).clone(), id, failed: i >= available,
          });
        }
        if (pumped > 0) {
          addFlow(nextFlows, id + '#pipe', statics.paths[id + '#pipe'],
            { size: clamp(5 + pumped / 50, 6, 18), color: palette.scene('water'), spacing: 55, speed: 75 });
        }
      } else if (o.kind === 'monitoring_point') {
        if (tone) paint(statics.solid, id, palette.tone(tone), selected);
      } else if (o.kind === 'settling_pond') {
        paint(statics.solid, id, palette.scene('pond'), selected);
      } else if (o.kind === 'plant_line') {
        if (ghost || !thing) continue;
        if (tone === 'ok') {
          // A running line is brighter the more it mills (30 … 55 t/h).
          const k = 0.52 + 0.48 * clamp(((isNum(f.feed_tph) ? f.feed_tph : 40) - 30) / 25, 0, 1);
          paint(statics.solid, id, tmpColor.copy(palette.tone('ok')).multiplyScalar(k).clone(), selected);
        } else {
          paint(statics.solid, id, palette.tone(tone || 'idle'), selected);
        }
      } else if (o.kind === 'tailings_dam') {
        if (ghost || !thing) continue;
        paint(statics.lines, id, palette.tone(tone || 'idle'), selected);
        // The tailings prism rises from the lowest ground to the fill level
        // (where the level is under the ground, the ground hides it).
        // An empty cell keeps its prism under the ground.
        const pct = isNum(f.fill_pct) ? f.fill_pct : 0;
        const h = pct > 0 ? Math.max(0.6, (o.top - o.bottom) * clamp(pct / 100, 0, 1)) : -1;
        statics.fills.setLevel(id, o.bottom + 0.5, o.bottom + h);
        // The pond lies on the fill once there is one; on an empty cell it stays under the ground.
        statics.fills.setLevel(id + '#pond', o.bottom + 0.5, o.bottom + h + (h > 2 ? 0.3 : -0.5));
        paint(statics.fills, id, palette.scene(f.state === 'active' ? 'tailingsActive' : 'tailings'), selected);
      } else if (o.kind === 'plant' || o.kind === 'tailings_facility' || o.kind === 'rom_stockpile') {
        paint(statics.lines, id, selected ? white : palette.scene('site'), false);
      }
    }

    // Stockpile cone: volume follows the tonnes.
    if (stockObject) {
      const f = F(stockId);
      const k = isNum(f.tonnes) ? clamp(Math.cbrt(Math.max(0, f.tonnes) / (stockObject.reference_t || 36000)), 0.1, 2.2) : 1;
      stock.scale.setScalar(k);
      const tone = typeof f.state === 'string' ? stateTone(f.state, 'rom_stockpile') : 'ok';
      stock.material.color.copy(tone === 'ok' ? palette.scene('ore') : palette.tone(tone));
      if (stockId === selectedId) stock.material.color.lerp(white, 0.4);
    }

    // Surface flows: tailings, reclaim, water supply, discharge, intake, ore feed.
    const p = statics.paths;
    const amount = (value) => (isNum(value) && value > 0 ? value : 0);
    if (amount(plant.tailings_tph)) {
      addFlow(nextFlows, 'tailings', p['pipeline-tailings'],
        { size: clamp(4 + plant.tailings_tph / 45, 5, 13), color: palette.scene('tailingsActive'), spacing: 95, speed: 65 });
    }
    const reclaim = amount(waterSystem.reclaim_m3h) || amount(F(NS + 'tailings').reclaim_m3h);
    if (reclaim) {
      addFlow(nextFlows, 'reclaim', p['pipeline-tailings'],
        { size: clamp(4 + reclaim / 30, 5, 13), color: palette.scene('water'), spacing: 95, speed: 65, reverse: true, offset: [0, 0, 14] });
    }
    if (amount(waterSystem.plant_supply_m3h)) {
      addFlow(nextFlows, 'supply', p['pipeline-water-supply'],
        { size: clamp(3.5 + waterSystem.plant_supply_m3h / 50, 4, 12), color: palette.scene('water'), spacing: 75, speed: 60 });
    }
    if (amount(waterSystem.discharge_m3h) > 0.5) {
      addFlow(nextFlows, 'discharge', p['pipeline-discharge'],
        { size: clamp(3 + waterSystem.discharge_m3h / 26, 3.5, 14), color: palette.scene('water'), spacing: 80, speed: 60 });
    }
    if (amount(waterSystem.extra_intake_m3h)) {
      addFlow(nextFlows, 'intake', p['pipeline-intake'],
        { size: clamp(4 + waterSystem.extra_intake_m3h / 30, 5, 12), color: palette.scene('water'), spacing: 75, speed: 60 });
    }
    if (amount(plant.feed_tph)) {
      addFlow(nextFlows, 'conveyor', p.conveyor,
        { size: clamp(3.5 + plant.feed_tph / 45, 4, 10), color: palette.scene('ore'), spacing: 38, speed: 24 });
    }

    // Water in the workings: a surface over the flooded levels, a film below otherwise.
    const volume = amount(mine.flood_volume_m3);
    if (Number.isFinite(lowest)) waterFloor = lowest - 9;
    if (flooded.length) waterTarget = Math.max(...flooded) + 5 + Math.min(12, volume / 400);
    else if (volume > 0 && Number.isFinite(lowest)) waterTarget = lowest - 7 + Math.min(9, volume / 35);
    else waterTarget = null;

    overlay.setAlerts({
      air: restricted || nextPlates.some((plate) => plate.color === palette.tone('warn')),
      flood: waterTarget !== null,
    });
    fixed = nextFixed;
    pumpList = nextPumps;
    flows = nextFlows;
    arrows = nextArrows;
    plateList = nextPlates;
  }

  function updateVehicles(now) {
    for (const [id, o] of Object.entries(objects)) {
      if (!VEHICLE_KINDS.has(o.kind)) continue;
      const f = F(id);
      const target = isNum(f.pos_x) && isNum(f.pos_y) && isNum(f.pos_z) ? [f.pos_x, f.pos_y, f.pos_z]
        : o.center || o.anchor;
      if (!target) continue;
      let v = vehicles.get(id);
      const state = typeof f.state === 'string' ? f.state : 'parked';
      if (!v) {
        v = { id, kind: o.kind, size: o.size || [10, 2.5, 2.5], position: new THREE.Vector3().fromArray(target),
          direction: new THREE.Vector3(1, 0, 0), path: null, cum: null, length: 0, startedAt: 0, duration: 0 };
        vehicles.set(id, v);
      } else {
        const from = v.position.toArray();
        const direct = Math.hypot(target[0] - from[0], target[1] - from[1], target[2] - from[2]);
        v.path = null;
        if (direct > 0.5) {
          const routed = network.route(from, target) || [from, target];
          const path = routed.filter((pt, i) => i === 0 || Math.hypot(pt[0] - routed[i - 1][0], pt[1] - routed[i - 1][1], pt[2] - routed[i - 1][2]) > 0.05);
          const cum = cumulative(path);
          const length = cum[cum.length - 1];
          if (path.length > 1 && length <= MAX_JUMP) {
            Object.assign(v, { path, cum, length, startedAt: now, duration: sampleMs });
          } else {
            v.position.fromArray(target);
          }
        }
      }
      v.state = state;
      v.parked = state === 'parked';
      v.loaded = isNum(f.payload) && f.payload > 0;
      v.working = state === 'mucking' || state === 'loading_truck' || state === 'drilling';
      v.ring = RING_STATES.has(state) ? stateTone(state, o.kind) : null;
    }
  }

  // -------------------------------------------------------------- labels
  let labelsDueAt = 0;
  let labelCount = 0;
  const scratch = new THREE.Vector3();

  /** How much larger than to scale a unit is drawn, so that it stays visible (1 = true size). */
  function unitScale(v) {
    if (v.parked) return 1;
    const distance = camera.position.distanceTo(v.position);
    const near = clamp((distance - FULL_SIZE_AT[0]) / (FULL_SIZE_AT[1] - FULL_SIZE_AT[0]), 0, 1);
    const pixels = MIN_PIXELS[v.kind] * near * clamp(size.height / 820, 0.72, 1);
    return clamp((pixels * worldPerPixel(v.position)) / v.size[0], 1, MAX_UNIT_SCALE);
  }

  function vehicleLabelPosition(v, out) {
    const k = unitScale(v);
    return out.copy(v.position).addScaledVector(Y_AXIS, v.size[1] * k * (k > 1 ? STOUT : 1) + 3);
  }

  /**
   * Where a label anchor stands for the camera: 'hidden' (opaque ground lies
   * in front of it), 'behind' (on or above the ground beyond the x-ray window,
   * so that its label would float over the workings), 'over' (on the line of
   * sight through the window, in front of it or inside it) or 'clear'.
   */
  const toEye = new THREE.Vector3();
  function anchorSight(point) {
    if (!terrain) return 'clear';
    const eye = camera.position;
    const distance = eye.distanceTo(point);
    if (!(distance > 1)) return 'clear';
    toEye.copy(point).sub(eye).divideScalar(distance);
    // The first place where the line of sight from the eye goes into the ground.
    const steps = clamp(Math.ceil(distance / 30), 8, 160);
    let prevT = 0;
    let prevAbove = eye.y - terrain.heightAt(eye.x, eye.z);
    for (let i = 1; i <= steps; i += 1) {
      const t = (distance * i) / steps;
      const x = eye.x + toEye.x * t;
      const y = eye.y + toEye.y * t;
      const z = eye.z + toEye.z * t;
      const above = y - terrain.heightAt(x, z);
      if (above < -2 && prevAbove >= -2) {
        if (distance - t < 12) break;   // the anchor itself stands on the ground
        const k = prevT + ((t - prevT) * (prevAbove + 2)) / Math.max(1e-6, prevAbove - above);
        const at = [eye.x + toEye.x * k, eye.y + toEye.y * k, eye.z + toEye.z * k];
        if (groundOpacity(at, eye.toArray(), statics.xray) > 0.6) return 'hidden';
        break;
      }
      prevT = t;
      prevAbove = above;
    }
    if (!statics.xray) return 'clear';
    const sight = chordInEllipsoid(eye.toArray(), toEye.toArray(), statics.xray);
    if (sight <= XRAY_EDGE[0]) return 'clear';
    const surface = point.y >= terrain.heightAt(point.x, point.z) - 5;
    // On the surface beyond the window: the line of sight has crossed the ellipsoid before it.
    if (surface && chordInEllipsoid(point.toArray(), toEye.toArray(), statics.xray) < 1
      && sight > XRAY_EDGE[0] * 2) return 'behind';
    return surface ? 'over' : 'clear';
  }

  function relabel() {
    if (!statics || !size.width) return;
    const weights = LABEL_WEIGHTS[presetId] || LABEL_WEIGHTS.mine;
    const options = { gradeMode };
    const candidates = [];
    for (const id of Object.keys(objects)) {
      const thing = things[id];
      const o = objects[id];
      if (!thing) continue;
      const selected = id === selectedId;
      const v = vehicles.get(id);
      let position = labelPositions.get(id);
      if (v) {
        if (v.parked && !selected) continue;
        if (!position) {
          position = new THREE.Vector3();
          labelPositions.set(id, position);
        }
        vehicleLabelPosition(v, position);
      }
      if (!position) continue;
      const status = statusLine(thing, options);
      const state = thing.f && thing.f.state;
      const routine = o.kind === 'stope' && state === 'awaiting_blast';
      // A label behind a hill is not shown, and one beyond the x-ray window
      // yields to the workings and is faded. A fault is always shown, faded
      // only behind a hill; the selected twin is always shown in full.
      const alarm = !routine && ALARM_TONES.has(status.tone);
      const sight = selected ? 'clear' : anchorSight(position);
      if (sight === 'hidden' && !alarm) continue;
      let weight = weights[o.kind] || 0;
      if (o.kind === 'stope' && IDLE_STOPE.has(state)) weight = 0;
      if (state === 'planned') weight *= 0.5;   // a project is named only where it is the subject
      if (state === 'active' && weight) weight += 8;   // the dam being filled comes before the idle ones
      let score = weight + 45 * clamp(1 - camera.position.distanceTo(position) / 700, 0, 1);
      if (!routine) score += status.tone === 'fail' ? 300 : status.tone === 'flood' ? 260 : status.tone === 'warn' ? 180 : 0;
      if (labels.isShown(id)) score += 6;       // a shown label is not swapped for an equal one
      const dim = alarm ? sight === 'hidden' : sight === 'behind';
      if (sight === 'behind' && !alarm) score -= 30;
      if (selected) score += 10000;
      if (score < 40) continue;
      candidates.push({
        id, position, score, selected, dim, name: shortName(id, things), line: status.text, tone: status.tone,
        title: thing.name || '', align: o.kind === 'level' ? 'right' : 'above',
      });
    }
    // Named places of the image (village, river, stream): context, after every
    // twin, and never over the x-ray window or behind a hill.
    for (const place of statics.places) {
      const position = labelPositions.get(place.id);
      if (!position || anchorSight(position) !== 'clear') continue;
      candidates.push({ id: place.id, position, score: 20 + (labels.isShown(place.id) ? 6 : 0), selected: false,
        name: place.name, line: place.line, tone: 'place', title: place.name, align: 'above' });
    }
    labelCount = labels.layout(candidates, camera, size.width, size.height, overlay.reserved());
  }

  // ------------------------------------------------------------- picking
  const raycaster = new THREE.Raycaster();
  const pointer = new THREE.Vector2();
  const scratch2 = new THREE.Vector3();

  function screenDistance2(position, x, y) {
    scratch.copy(position).project(camera);
    if (scratch.z < -1 || scratch.z > 1) return Infinity;
    const dx = (scratch.x * 0.5 + 0.5) * size.width - x;
    const dy = (-scratch.y * 0.5 + 0.5) * size.height - y;
    return dx * dx + dy * dy;
  }

  /** True when opaque ground lies between the camera and a world point. */
  const groundRay = new THREE.Raycaster();
  function hiddenByGround(point) {
    if (!ground.visible) return false;
    const distance = camera.position.distanceTo(point);
    groundRay.set(camera.position, scratch.copy(point).sub(camera.position).normalize());
    groundRay.far = Math.max(0, distance - 6);
    const hit = groundRay.intersectObject(groundPick, false)[0];
    return Boolean(hit) && groundOpacity(hit.point.toArray(), camera.position.toArray(), statics.xray) > 0.6;
  }

  function nearestPickPoint(x, y, radius, kinds) {
    let best = null;
    let bestPoint = null;
    let bestD = radius * radius;
    for (const [id, points] of statics.pick) {
      if (kinds && !kinds.has(objects[id].kind)) continue;
      for (const pt of points) {
        const d = screenDistance2(scratch2.fromArray(pt), x, y);
        if (d < bestD) {
          bestD = d;
          best = id;
          bestPoint = pt;
        }
      }
    }
    return best && !hiddenByGround(scratch2.fromArray(bestPoint)) ? best : null;
  }

  function pickAt(clientX, clientY) {
    if (!statics || !size.width) return null;
    const rect = root.getBoundingClientRect();
    const x = clientX - rect.left;
    const y = clientY - rect.top;
    // 1. Mobile units: small, so a generous radius.
    let best = null;
    let bestD = Infinity;
    for (const v of vehicles.values()) {
      const reach = v.parked ? 7 : 15;
      const d = screenDistance2(v.position, x, y);
      if (d < reach * reach && d < bestD) {
        bestD = d;
        best = v.id;
      }
    }
    if (best) return best;
    // 2. Thin workings right under the pointer.
    best = nearestPickPoint(x, y, 5, THIN_KINDS);
    if (best) return best;
    // 3. Whatever surface the ray hits first.
    pointer.set((x / size.width) * 2 - 1, -(y / size.height) * 2 + 1);
    raycaster.setFromCamera(pointer, camera);
    const instances = pickable.map((item) => item.mesh);
    const surface = ground.visible ? [groundPick] : [];
    for (const hit of raycaster.intersectObjects([solidMesh, fillMesh, ...instances, stock, ...surface], false)) {
      if (hit.object === groundPick) {
        // Opaque ground ends the search; through the x-ray cut the ray goes on.
        if (groundOpacity(hit.point.toArray(), camera.position.toArray(), statics.xray) > 0.6) return null;
        continue;
      }
      const key = hit.object === solidMesh ? statics.solid.keyOfFace(hit.faceIndex)
        : hit.object === fillMesh ? statics.fills.keyOfFace(hit.faceIndex)
          : hit.object === stock ? stockId : pickable[instances.indexOf(hit.object)].ids[hit.instanceId];
      const id = key ? key.split('#')[0] : null;   // a part such as the pond of a dam names its twin
      if (id && objects[id]) return id;
    }
    // 4. Anything close.
    return nearestPickPoint(x, y, 14, null);
  }

  function select(id) {
    selectedId = id || null;
    derive(performance.now(), false);
    labelsDueAt = 0;
    dirty = true;
  }

  let press = null;
  let hoverAt = 0;
  const onPointerDown = (event) => {
    controls.enableZoom = true;
    // The label is noted now: the controls capture the pointer, so the release
    // event no longer names the element under it.
    const label = event.target instanceof Element ? event.target.closest('.s3d-label') : null;
    press = { x: event.clientX, y: event.clientY, at: performance.now(), button: event.button,
      labelId: label ? label.dataset.thing : null };
    root.dataset.drag = '1';
  };
  const onPointerUp = (event) => {
    delete root.dataset.drag;
    const down = press;
    press = null;
    if (!down || down.button !== 0 || event.button !== 0) return;
    if (Math.hypot(event.clientX - down.x, event.clientY - down.y) > 5 || performance.now() - down.at > 700) return;
    const id = down.labelId || pickAt(event.clientX, event.clientY);
    if (!id || !objects[id]) return;   // a place label (village, river) has no twin
    select(id);
    container.dispatchEvent(new CustomEvent('sekis:select', { bubbles: true, detail: { thingId: id } }));
  };
  const onPointerMove = (event) => {
    if (press || event.buttons) return;
    const now = performance.now();
    if (now - hoverAt < 140) return;
    hoverAt = now;
    const onLabel = event.target instanceof Element && event.target.closest('.s3d-label');
    const hover = onLabel || pickAt(event.clientX, event.clientY) ? '1' : '0';
    if (root.dataset.hover !== hover) root.dataset.hover = hover;
  };
  const onPointerLeave = () => {
    controls.enableZoom = false;
    delete root.dataset.hover;
  };
  root.addEventListener('pointerdown', onPointerDown);
  root.addEventListener('pointerup', onPointerUp);
  root.addEventListener('pointercancel', () => {
    press = null;
    delete root.dataset.drag;
  });
  root.addEventListener('pointermove', onPointerMove);
  root.addEventListener('pointerleave', onPointerLeave);

  // ---------------------------------------------------------- frame loop
  const position = new THREE.Vector3();
  const scale = new THREE.Vector3();
  const direction = new THREE.Vector3();
  const quaternion = new THREE.Quaternion();
  const identity = new THREE.Quaternion();
  const heading = new THREE.Euler();
  const pumpScale = new THREE.Vector3().fromArray(PUMP_SIZE);
  const color = new THREE.Color();
  let lastStepAt = 0;
  let moving = false;

  function step(now) {
    const dt = lastStepAt ? Math.min(0.5, (now - lastStepAt) / 1000) : 0;
    lastStepAt = now;
    moving = false;
    camera.updateMatrixWorld();

    if (fly) {
      const k = clamp((now - fly.startedAt) / fly.duration, 0, 1);
      const eased = k * k * (3 - 2 * k);
      controls.target.lerpVectors(fly.fromTarget, fly.toTarget, eased);
      camera.position.lerpVectors(fly.fromPosition, fly.toPosition, eased);
      controls.update();
      if (k >= 1) {
        fly = null;
        labelsDueAt = 0;
      }
      moving = true;
    }

    // Boxes: stope fills and sump gauges, then the flow beads; the pumps; the units.
    boxes.begin();
    for (const item of fixed) {
      let c = item.color;
      if (item.fx) {
        if (item.fx.flashUntil > now) {      // the blast: a white flash that fades
          const k = (item.fx.flashUntil - now) / 3600;
          c = color.copy(item.color).lerp(white, k * (0.65 + 0.35 * Math.sin(now / 55)));
          moving = true;
        } else if (item.fx.pulse) {          // waiting for the blast in the blast window
          c = color.copy(item.color).lerp(white, 0.22 + 0.22 * Math.sin(now / 260));
          moving = true;
        }
      }
      boxes.add(item.position, identity, item.scale, c, item.id);
    }

    // The pumps: drawn larger at a distance (the row spreads from the middle of
    // the plinth), so that a pump out of service shows as a red one with a red ring.
    rings.begin();
    pumps.begin();
    for (const item of pumpList) {
      const distance = camera.position.distanceTo(item.center);
      const near = clamp((distance - FULL_SIZE_AT[0]) / (FULL_SIZE_AT[1] - FULL_SIZE_AT[0]), 0, 1);
      const wpp = worldPerPixel(item.center);
      const k = clamp((PUMP_PIXELS * near * wpp) / PUMP_SIZE[0], 1, 6);
      position.set(item.center.x + (item.position.x - item.center.x) * k, item.center.y + (PUMP_SIZE[1] * k) / 2,
        item.position.z);
      pumps.add(position, identity, scale.copy(pumpScale).multiplyScalar(k), item.color, item.id);
      if (item.failed) {
        const r = Math.max(PUMP_SIZE[0] * k * 0.95, 13 * wpp);
        rings.add(position, camera.quaternion, scale.set(r, r, r), palette.tone('fail'), item.id);
      }
    }
    pumps.end();

    for (const unit of Object.values(units)) unit.begin();
    for (const v of vehicles.values()) {
      if (v.path) {
        const k = clamp((now - v.startedAt) / v.duration, 0, 1);
        pointAlong(v.path, v.cum, k * v.length, v.position, direction);
        // A (near) vertical leg of a route keeps the heading the unit had.
        if (Math.hypot(direction.x, direction.z) > 0.3 * direction.length()) v.direction.copy(direction).normalize();
        if (k >= 1) v.path = null;
        moving = true;
      }
      const wpp = worldPerPixel(v.position);
      const k = unitScale(v);
      const length = v.size[0];
      const height = v.size[1] * (k > 1 ? STOUT : 1);
      const width = v.size[2] * (k > 1 ? STOUT : 1);
      const selected = v.id === selectedId;
      // Heading along the travel direction, pitched with the slope, never rolled.
      heading.set(0, Math.atan2(-v.direction.z, v.direction.x),
        clamp(Math.atan2(v.direction.y, Math.hypot(v.direction.x, v.direction.z)), -MAX_PITCH, MAX_PITCH), 'YZX');
      quaternion.setFromEuler(heading);
      position.copy(v.position).addScaledVector(Y_AXIS, (height * k) / 2 + (v.parked ? 0 : 1.2));
      // A parked unit stands on the drawn ground of the sloping yard, not in it.
      if (v.parked && terrain) {
        position.y = Math.max(v.position.y, terrain.heightAt(v.position.x, v.position.z) + 0.05) + height / 2;
      }
      // The model: the paint carries loaded or empty, the kind, or parked.
      if (v.parked) color.copy(palette.tone('idle'));
      else if (v.kind === 'haul_truck') color.copy(palette.scene(v.loaded ? 'truckLoaded' : 'truckEmpty'));
      else color.copy(palette.scene(v.kind === 'lhd' ? 'lhd' : 'rig'));
      if (selected) color.lerp(white, 0.5);
      scale.set(length * k, height * k, width * k);
      const model = units[v.kind] || units.haul_truck;
      model.add(position, quaternion, scale, color, v.id);
      // Ore in the body of a loaded truck and in the bucket of an LHD at work.
      const load = v.kind === 'haul_truck' && v.loaded ? units.truckLoad
        : v.kind === 'lhd' && v.working && !v.parked ? units.lhdLoad : null;
      if (load) {
        color.copy(palette.scene('ore'));
        if (selected) color.lerp(white, 0.4);
        load.add(position, quaternion, scale, color, v.id);
      }
      if (v.ring) {
        const r = Math.max(length * k * 0.78, 11 * wpp);
        rings.add(position.copy(v.position).addScaledVector(Y_AXIS, (height * k) / 2), camera.quaternion,
          scale.set(r, r, r), palette.tone(v.ring), v.id);
      }
      if (labels.isShown(v.id)) labels.move(v.id, vehicleLabelPosition(v, scratch));
    }
    for (const unit of Object.values(units)) unit.end();

    for (const flow of flows) {
      const phase = ((flowPhase.get(flow.key) || 0) + (flow.speed * dt) / flow.length) % 1;
      flowPhase.set(flow.key, phase);
      for (let i = 0; i < flow.count; i += 1) {
        pointAlong(flow.path, flow.cum, ((i / flow.count + phase) % 1) * flow.length, position);
        const s = Math.max(flow.size, 4 * worldPerPixel(position));
        boxes.add(position, identity, scale.set(s, s, s), flow.color, null);
      }
      moving = true;
    }
    boxes.end();

    // Air: cones travelling down the intake airways and up the exhaust ones.
    cones.begin();
    for (const arrow of arrows) {
      const span = arrow.to - arrow.from;
      const phase = ((flowPhase.get(arrow.key) || 0) + (arrow.speed * dt) / Math.abs(span)) % 1;
      flowPhase.set(arrow.key, phase);
      quaternion.setFromAxisAngle(X_AXIS, span < 0 ? Math.PI : 0);
      for (let i = 0; i < arrow.count; i += 1) {
        position.set(arrow.x, arrow.from + span * ((i / arrow.count + phase) % 1), arrow.z);
        const r = Math.max(arrow.radius, 3 * worldPerPixel(position));
        cones.add(position, quaternion, scale.set(r, r, r), arrow.color, arrow.key);
      }
      moving = true;
    }
    cones.end();

    // Selection ring.
    if (selectedId && statics) {
      const v = vehicles.get(selectedId);
      const sphere = statics.spheres.get(selectedId);
      if (v || sphere) {
        if (v) position.copy(v.position);
        else position.fromArray(sphere.center);
        const wpp = worldPerPixel(position);
        const r = clamp(v ? 0 : sphere.radius * 1.15, 17 * wpp, 34 * wpp);
        rings.add(position, camera.quaternion, scale.set(r, r, r), white, null);
      }
    }
    rings.end();

    plates.begin();
    for (const plate of plateList) plates.add(plate.position, identity, plate.scale, plate.color, null);
    plates.end();

    // Water rises to its target and drains back.
    if (waterTarget !== null || waterLevel !== null) {
      const goal = waterTarget === null ? waterFloor : waterTarget;
      if (waterLevel === null) waterLevel = waterFloor;
      const next = waterLevel + (goal - waterLevel) * (1 - Math.exp(-dt / 1.6));
      if (Math.abs(goal - next) > 0.05) {
        waterLevel = next;
        moving = true;
      } else {
        waterLevel = waterTarget === null ? null : goal;
      }
      const f = statics.frame;
      if (waterLevel !== null && f) {
        const h = Math.max(0.5, waterLevel - waterFloor);
        water.position.set((f[0] + f[2]) / 2, waterFloor + h / 2, (f[1] + f[3]) / 2);
        water.scale.set(f[2] - f[0] + 30, h, f[3] - f[1] + 30);
        water.visible = true;
      } else {
        water.visible = false;
      }
    }

    // The ruler turns about its vertical axis to face the camera.
    if (rulerLines.visible) {
      rulerLines.rotation.y = Math.atan2(camera.position.x - rulerLines.position.x, camera.position.z - rulerLines.position.z);
    }

    if (now >= labelsDueAt) {
      labelsDueAt = now + 350;
      relabel();
    }
  }

  const stats = { triangles: 0, calls: 0, lines: 0, fps: 0, frameMs: 0, frames: 0, since: performance.now() };
  function draw(now) {
    const started = performance.now();
    step(now);
    renderer.render(scene, camera);
    labels.render(camera);
    dirty = false;
    stats.triangles = renderer.info.render.triangles;
    stats.calls = renderer.info.render.calls;
    stats.lines = renderer.info.render.lines;
    stats.frameMs = stats.frameMs * 0.8 + (performance.now() - started) * 0.2;
    stats.frames += 1;
    if (now - stats.since >= 1000) {
      stats.fps = (stats.frames * 1000) / (now - stats.since);
      stats.frames = 0;
      stats.since = now;
      if (debugOn) {
        overlay.debug(`треугольников: ${fmt(stats.triangles)} · вызовов отрисовки: ${fmt(stats.calls)} · отрезков: ${fmt(stats.lines)}\n`
          + `кадров в секунду: ${fmt(stats.fps, 1)} · расчёт кадра: ${fmt(stats.frameMs, 1)} мс · подписей: ${fmt(labelCount)} из ${MAX_LABELS}`);
      }
    }
  }

  let inView = true;
  let nextFrameAt = 0;
  let raf = 0;
  let contextLost = false;
  const isShown = () => !document.hidden && inView && size.width > 0 && size.height > 0 && !contextLost;

  /**
   * Draw at once rather than in the next animation frame. Used on mount, on a
   * resize, on a new state and when the page or the scene comes into view: a
   * browser may grant animation frames rarely (a headless capture in virtual
   * time gives about one a second), and the first frames must not wait for
   * them. `force` (the buffer was cleared or the scene was just shown) skips the
   * 12 fps cap and the in-view test; otherwise a frame drawn too recently leaves
   * the work to the frame loop (`dirty` stays set). Nothing is drawn while the
   * container has no size (hidden by the view switch) or the page is hidden.
   */
  function drawNow(force) {
    if (disposed || !statics || document.hidden || contextLost || !size.width || !size.height) return;
    const now = performance.now();
    if (!force && (!inView || now < nextFrameAt)) return;
    nextFrameAt = now + FRAME_MS - 2;
    draw(now);
  }

  function frame(now) {
    if (disposed) return;
    raf = requestAnimationFrame(frame);
    if (!isShown() || now < nextFrameAt) return;
    // Nothing moved in the last frame and nothing asked for a redraw: stay idle.
    if (!dirty && !moving && !fly) return;
    nextFrameAt = now + FRAME_MS - 2;   // 2 ms of slack for the timer; never more than 12 a second
    draw(now);
  }

  // ------------------------------------------------------------- surface
  /**
   * The ground as chosen: the stylised landscape (default) or, with «Снимок»,
   * the plain grid draped with the Sentinel-2 image (the one texture of the
   * budget, loaded the first time it is asked for) and no landscape models.
   */
  function showSurface() {
    if (!terrain || disposed) return;
    if (photoOn && !groundTexture && !photoLoading) {
      photoLoading = true;
      new THREE.TextureLoader().load(TEXTURE_URL, (texture) => {
        photoLoading = false;
        if (disposed) {
          texture.dispose();
          return;
        }
        texture.colorSpace = THREE.SRGBColorSpace;
        groundTexture = texture;
        showSurface();
      }, undefined, () => {   // no image: the stylised ground stays
        photoLoading = false;
        photoOn = false;
        overlay.setPhoto(false);
      });
    }
    const photo = Boolean(photoOn && groundTexture);
    ground.geometry = photo || !landscape ? terrain.geometry : landscape.ground;
    if (photo) groundLook.showPhoto(groundTexture);
    else groundLook.showStyled(landscape ? white : palette.cover('meadow'));
    if (landscape) landscape.group.visible = !photo;
    dirty = true;
    drawNow(true);
  }

  /** [x, z, r] circles around the twin's own surface models: no OSM building or tree is drawn there. */
  function keepOut() {
    const out = [];
    const near = (x, y, z) => Math.abs(y - terrain.heightAt(x, z)) < 25;
    for (const o of Object.values(objects)) {
      if (VEHICLE_KINDS.has(o.kind)) continue;
      if ((o.kind === 'plant_line' || o.kind === 'main_fan' || o.kind === 'settling_pond') && o.center && o.size
        && near(o.center[0], o.center[1] - o.size[1] / 2, o.center[2])) {
        out.push([o.center[0], o.center[2], Math.hypot(o.size[0], o.size[2]) / 2 + 6]);
      } else if (o.kind === 'shaft' && o.base && near(o.base[0], o.top, o.base[2])) {
        out.push([o.base[0], o.base[2], 22]);
      } else if (o.kind === 'rom_stockpile' && o.base) {
        out.push([o.base[0], o.base[2], (o.radius || 30) + 12]);
      } else if (o.kind === 'monitoring_point' && o.anchor) {
        out.push([o.anchor[0], o.anchor[2], 8]);
      } else if (o.kind === 'decline') {
        for (const node of o.nodes || []) {
          if (node.type === 'portal' && Array.isArray(node.at) && near(...node.at)) out.push([node.at[0], node.at[2], 24]);
        }
      }
    }
    return out;
  }

  // ------------------------------------------------------------ plumbing
  const resizeObserver = 'ResizeObserver' in window ? new ResizeObserver(resize) : null;
  if (resizeObserver) resizeObserver.observe(container);
  else window.addEventListener('resize', resize);
  const viewObserver = 'IntersectionObserver' in window ? new IntersectionObserver((entries) => {
    inView = entries[entries.length - 1].isIntersecting;
    if (inView) {
      dirty = true;
      drawNow(false);
    }
  }) : null;
  if (viewObserver) viewObserver.observe(root);
  const onVisibility = () => {
    if (document.hidden) return;
    dirty = true;
    drawNow(true);   // the browser may have dropped the buffer of a hidden page
  };
  document.addEventListener('visibilitychange', onVisibility);
  canvas.addEventListener('webglcontextlost', (event) => {
    event.preventDefault();
    contextLost = true;
    overlay.note('3D-сцена остановлена: графический контекст потерян');
  });
  canvas.addEventListener('webglcontextrestored', () => {
    contextLost = false;
    overlay.note('');
    dirty = true;
    drawNow(true);
  });

  rebuildStatics();
  lastSignature = signature();
  derive(performance.now(), false);
  updateVehicles(performance.now());
  resize();   // sizes the canvas and draws the first frame now
  raf = requestAnimationFrame(frame);

  // The landscape: built from /terrain/landscape.json once it has arrived
  // (until then, and without it, the ground is the plain grid in the meadow
  // colour), then the frame is drawn at once.
  if (terrain) {
    fetch(LANDSCAPE_URL).then((answer) => (answer.ok ? answer.json() : null)).then((data) => {
      if (disposed || !data) return;
      landscape = buildLandscape(data, terrain, palette, groundLook, keepOut());
      scene.add(landscape.group);
      showSurface();
    }).catch(() => {});   // no landscape: the plain ground stays
  }

  if (debugOn) {
    // Measurement hooks for the performance budget (only with ?debug=1).
    window.sekisScene3d = {
      stats: () => ({ ...stats, labels: labelCount, canvas: [canvas.width, canvas.height], network: [network.nodes, network.edges],
        landscape: landscape ? landscape.counts : null, photo: Boolean(photoOn && groundTexture) }),
      /** «Снимок» on or off, as the button does. */
      photo(on) {
        photoOn = Boolean(on);
        overlay.setPhoto(photoOn);
        showSurface();
      },
      /**
       * Draw `count` frames back to back; reading one pixel after each frame
       * waits until the rasteriser has finished it. Returns ms per frame.
       */
      bench(count = 20) {
        const pixel = new Uint8Array(4);
        const kept = { frames: stats.frames, since: stats.since, fps: stats.fps };
        const started = performance.now();
        for (let i = 0; i < count; i += 1) {
          draw(started);   // the same time stamp: the frames are not counted as animation
          gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, pixel);
        }
        Object.assign(stats, kept);
        return (performance.now() - started) / count;
      },
      pick: (x, y) => pickAt(x, y),
      /** How each label anchor stands for the camera: hidden, behind, over or clear. */
      sights: () => Object.fromEntries([...labelPositions].map(([id, at]) => [id, anchorSight(at)])),
      vehicles: () => [...vehicles.values()].map((v) => ({ id: v.id, state: v.state, moving: Boolean(v.path),
        position: v.position.toArray(), off: network.snap(v.position.toArray()).d })),
      project(thingId) {
        const v = vehicles.get(thingId);
        const sphere = statics.spheres.get(thingId);
        if (!v && !sphere) return null;
        scratch.copy(v ? v.position : new THREE.Vector3().fromArray(sphere.center)).project(camera);
        const rect = root.getBoundingClientRect();
        return [rect.left + (scratch.x * 0.5 + 0.5) * size.width, rect.top + (-scratch.y * 0.5 + 0.5) * size.height];
      },
      camera: () => ({ position: camera.position.toArray(), target: controls.target.toArray() }),
      /** Put the camera at `position` looking at `target` (close-ups for review), and draw. */
      look(target, position) {
        fly = null;
        controls.target.fromArray(target);
        camera.position.fromArray(position);
        camera.lookAt(controls.target);   // closer than the orbit limit allows: no controls.update()
        labelsDueAt = 0;
        dirty = true;
        drawNow(true);
      },
    };
  }

  return {
    update(state) {
      if (disposed || !state || typeof state.things !== 'object') return;
      const now = performance.now();
      const fresh = state !== lastState;
      if (fresh) {
        if (lastFreshAt) sampleMs = clamp(now - lastFreshAt, 900, 4500);
        lastFreshAt = now;
        lastState = state;
      }
      things = state.things;
      const next = signature();
      if (next !== lastSignature) {
        lastSignature = next;
        rebuildStatics();
      }
      derive(now, fresh);
      if (fresh) updateVehicles(now);
      labelsDueAt = Math.min(labelsDueAt, now + 150);
      dirty = true;
      // The first state is drawn at once; later ones too unless a frame was
      // drawn less than 1/12 s ago (then the frame loop picks it up).
      drawNow(!stateDrawn);
      stateDrawn = true;
    },

    focus(thingId) {
      if (disposed || !statics) return;
      if (!thingId || !objects[thingId]) {
        const kind = thingId && things[thingId] && things[thingId].kind;
        select(null);
        if (KIND_VIEW[kind]) applyPreset(KIND_VIEW[kind]);
        return;
      }
      select(thingId);
      const v = vehicles.get(thingId);
      const sphere = statics.spheres.get(thingId) || { center: objects[thingId].anchor, radius: 60 };
      const center = v ? v.position.clone() : new THREE.Vector3().fromArray(sphere.center);
      const radius = v ? 45 : sphere.radius;
      const distance = clamp((radius / Math.sin((FOV * DEG) / 2)) * 1.3, 520, 2700);
      const away = camera.position.clone().sub(controls.target).normalize();
      if (away.y < 0.12) away.setY(0.12).normalize();   // never look up from under the object
      flyTo(center, center.clone().addScaledVector(away, distance));
    },

    dispose() {
      if (disposed) return;
      disposed = true;
      cancelAnimationFrame(raf);
      if (resizeObserver) resizeObserver.disconnect();
      else window.removeEventListener('resize', resize);
      if (viewObserver) viewObserver.disconnect();
      document.removeEventListener('visibilitychange', onVisibility);
      controls.dispose();
      labels.dispose();
      scene.traverse((object) => {
        if (object.geometry) object.geometry.dispose();
        if (object.material) object.material.dispose();
      });
      if (groundTexture) groundTexture.dispose();
      if (landscape) landscape.dispose();
      if (terrain) terrain.geometry.dispose();   // the plain grid, also when the landscape was drawn
      for (const look of [groundLook.models, groundLook.instances]) look.dispose();
      renderer.dispose();
      if (debugOn) delete window.sekisScene3d;
      root.remove();
    },
  };
}
