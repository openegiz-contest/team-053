// Static part of the scene, built from model/geometry.json into merged
// objects: `solid` (triangles of everything that exists: workings, and the
// buildings and fixed equipment drawn as models, models.js), `fills` (the tailings
// in their dams, whose level follows the twin), `ghost` (dashed outlines of
// everything that is still a project), `lines` (thin outlines, roads, streams,
// pipes, the bench crests of the old pit) and the elevation ruler. The ground
// itself is the terrain mesh (terrain.js, landscape.js); surface outlines are
// laid on it. The tailings cells stand on it as embankments with sloped faces
// (a cell that is still a project is dashed). The lines of the scenery (roads,
// streams, pipes, the yard and the cells) are marked as lying on the ground:
// they thin out in the x-ray window like the landscape models. The old pit is
// a landmark of the scene and keeps its lines.
//
// Which things are a project is decided by the live twin state, so the whole
// set is rebuilt when a measure turns a planned object into a working one or a
// decline face advances. A rebuild takes a few milliseconds.

import * as THREE from 'three';
import { LineBuilder, MeshBuilder, strokeText } from './kit.js';
import {
  EdgeWriter, FAN_BOX, SolidWriter, crusherHouse, fan, headframe, placement, plantLine, pumpStation, stack,
} from './models.js';
import { elevationText } from './texts.js';

const VEHICLE_KINDS = new Set(['haul_truck', 'lhd', 'drill_rig']);
const MIN_AIRWAY_RADIUS = 2.2;   // m: thinner airways vanish at the overview scale
const LINE_LIFT = 1.8;           // m: surface lines above the ground, clear of the triangles
const SKIRT_DEPTH = 24;          // m: the edge of the terrain block
const GALLERY_RISE = 13;         // m: the conveyor gallery climbs to the top of the crusher house
const GALLERY_RAMP = 120;        // m of conveyor along which it climbs (about 6 degrees)
const TURN = 0.15;               // rad: the crusher house stands at the first turn of the conveyor sharper than this
// The x-ray ellipsoid: semi-axes over the half sizes of the box of the workings
// (x, y, z); the ore zone is narrow north-south, so z grows most. Its centre is
// raised by XRAY_LIFT of the box height, so that the window is widest near the
// ground, where the portals, the upper turns of the declines and the top of the
// ruler are, and the dashed design levels at the bottom fade first.
const XRAY_GROW = [1.3, 1.28, 1.75];
const XRAY_LIFT = 0.1;
// Embankments of the tailings cells (schematic: no dam section is published).
const DAM_OUTER = 2.5;   // m of run per metre of height, outer face (1:2.5)
const DAM_INNER = 2;     // inner face (1:2)
const DAM_CREST = 6;     // m: crest width
const DAM_STEP = 25;     // m: the faces follow the ground in pieces of at most this length
const UNNUMBERED_BUND = 2;   // m: the crest of a cell without a dam number above the highest ground of its outline
const POND_SHARE = 0.45;     // the pond on a tailings fill: the outline shrunk to this share about its centre
const PORTAL = [16, 9, 12];      // m: the portal box of a decline
const BAY = [18, 6, 9];          // m: a passing bay
const TURN_BOX = [10, 6, 11];    // m: a turn or a level access

/**
 * The embankment of a tailings cell: a flat crest DAM_CREST wide inside the
 * mapped outline at elevation `crest`, the outer face down to the ground and
 * the inner face down to `floor`. The fill prism of the cell (its level
 * follows the twin) covers the lower part of the inner face.
 */
function embankment(solid, footprint, crest, floor, groundAt, colors, key) {
  let ring = footprint.length > 1 && footprint[0][0] === footprint[footprint.length - 1][0]
    && footprint[0][1] === footprint[footprint.length - 1][1] ? footprint.slice(0, -1) : footprint.slice();
  let area = 0;
  for (let i = 0; i < ring.length; i += 1) {
    const [a, b] = [ring[i], ring[(i + 1) % ring.length]];
    area += a[0] * b[1] - b[0] * a[1];
  }
  if (area < 0) ring = ring.reverse();   // interior to the left of every edge
  const n = ring.length;
  // Outward normal of each edge, and the mitre at each vertex.
  const normals = ring.map((a, i) => {
    const b = ring[(i + 1) % n];
    const l = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1;
    return [(b[1] - a[1]) / l, -(b[0] - a[0]) / l];
  });
  const mitres = ring.map((_, i) => {
    const [p, q] = [normals[(i + n - 1) % n], normals[i]];
    const m = [p[0] + q[0], p[1] + q[1]];
    const l = Math.hypot(m[0], m[1]) || 1;
    const cos = Math.max(0.5, (m[0] * q[0] + m[1] * q[1]) / l);
    return [m[0] / l / cos, m[1] / l / cos];
  });
  const samples = [];   // [point, outward direction]
  for (let i = 0; i < n; i += 1) {
    const [a, b] = [ring[i], ring[(i + 1) % n]];
    const k = Math.max(1, Math.ceil(Math.hypot(b[0] - a[0], b[1] - a[1]) / DAM_STEP));
    samples.push([a, mitres[i]]);
    for (let s = 1; s < k; s += 1) samples.push([[a[0] + ((b[0] - a[0]) * s) / k, a[1] + ((b[1] - a[1]) * s) / k], normals[i]]);
  }
  const at = ([x, z], [dx, dz], d) => [x + dx * d, z + dz * d];
  const toe = (p, dir) => {
    let d = Math.max(0, crest - groundAt(p[0], p[1])) * DAM_OUTER;
    for (let k = 0; k < 2; k += 1) {
      const q = at(p, dir, d);
      d = Math.max(0, crest - groundAt(q[0], q[1])) * DAM_OUTER;
    }
    const q = at(p, dir, d);
    return [q[0], groundAt(q[0], q[1]) - 0.4, q[1]];
  };
  const rows = samples.map(([p, dir]) => {
    const inner = at(p, dir, -DAM_CREST);
    const foot = at(inner, dir, -Math.max(0, crest - floor) * DAM_INNER);
    return {
      toe: toe(p, dir), edge: [p[0], crest, p[1]], inner: [inner[0], crest, inner[1]], foot: [foot[0], floor - 0.5, foot[1]],
    };
  });
  for (let i = 0; i < rows.length; i += 1) {
    const [a, b] = [rows[i], rows[(i + 1) % rows.length]];
    const below = (p, q) => [(p[0] + q[0]) / 2, Math.min(p[1], q[1]) - 30, (p[2] + q[2]) / 2];
    solid.use(key, colors.face, false).quad(a.edge, b.edge, b.toe, a.toe, below(a.inner, b.inner));
    solid.use(key, colors.crest, false).quad(a.inner, b.inner, b.edge, a.edge, below(a.edge, b.edge));
    solid.use(key, colors.face, false).quad(a.foot, b.foot, b.inner, a.inner, below(a.edge, b.edge));
  }
}

/** The outline shrunk to `share` about its centroid (the pond on a tailings fill). */
function shrunk(footprint, share) {
  const n = footprint.length || 1;
  const cx = footprint.reduce((t, p) => t + p[0], 0) / n;
  const cz = footprint.reduce((t, p) => t + p[1], 0) / n;
  return footprint.map(([x, z]) => [cx + (x - cx) * share, cz + (z - cz) * share]);
}

/**
 * The conveyor from the ROM pad: on the ground up to its ramp, then in an
 * inclined gallery up to the top of the crusher house at its first sharp turn,
 * down inside the house and on along the plant lines. Returns the path the ore
 * beads follow and the parts to draw, or null when the route has no turn.
 */
function conveyorRoute(points) {
  let turn = -1;
  for (let i = 1; i < points.length - 1 && turn < 0; i += 1) {
    const [a, b, c] = [points[i - 1], points[i], points[i + 1]];
    const t0 = Math.atan2(b[2] - a[2], b[0] - a[0]);
    const t1 = Math.atan2(c[2] - b[2], c[0] - b[0]);
    let d = Math.abs(t1 - t0);
    if (d > Math.PI) d = 2 * Math.PI - d;
    if (d > TURN) turn = i;
  }
  if (turn < 0) return null;
  const cum = [0];
  for (let i = 1; i < points.length; i += 1) {
    cum.push(cum[i - 1] + Math.hypot(points[i][0] - points[i - 1][0], points[i][2] - points[i - 1][2]));
  }
  const from = Math.max(0, cum[turn] - GALLERY_RAMP);
  const rise = (d) => (GALLERY_RISE * (d - from)) / Math.max(1, cum[turn] - from);
  const ground = [];
  const gallery = [];
  for (let i = 0; i < turn; i += 1) {
    if (cum[i] <= from) ground.push(points[i]);
    if (cum[i] === from) gallery.push(points[i]);
    if (cum[i] < from && cum[i + 1] > from) {
      const t = (from - cum[i]) / (cum[i + 1] - cum[i]);
      const a = points[i];
      const b = points[i + 1];
      const at = [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
      ground.push(at);
      gallery.push(at);
    } else if (cum[i] > from) {
      gallery.push([points[i][0], points[i][1] + rise(cum[i]), points[i][2]]);
    }
  }
  const top = points[turn];
  gallery.push([top[0], top[1] + GALLERY_RISE, top[2]]);
  const after = points.slice(turn);
  return { path: [...ground.slice(0, -1), ...gallery, ...after], ground, gallery, after, house: top };
}

function sample(points, step) {
  const out = [];
  for (let i = 0; i < points.length - 1; i += 1) {
    const a = points[i];
    const b = points[i + 1];
    const n = Math.max(1, Math.round(Math.hypot(b[0] - a[0], b[1] - a[1], b[2] - a[2]) / step));
    for (let k = 0; k < n; k += 1) {
      const t = k / n;
      out.push([a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t]);
    }
  }
  out.push(points[points.length - 1]);
  return out;
}

function sphereOf(points) {
  const box = new THREE.Box3();
  const v = new THREE.Vector3();
  for (const p of points) box.expandByPoint(v.set(p[0], p[1], p[2]));
  const sphere = box.getBoundingSphere(new THREE.Sphere());
  return { center: sphere.center.toArray(), radius: Math.max(20, sphere.radius) };
}

const lift = (points, dy) => points.map((p) => [p[0], p[1] + dy, p[2]]);
const centroid = (footprint) => {
  const n = footprint.length || 1;
  return [footprint.reduce((s, p) => s + p[0], 0) / n, footprint.reduce((s, p) => s + p[1], 0) / n];
};

/** Polyline cut at an elevation (points descend): the part above and the part below. */
function cutAtElevation(points, elevation) {
  const above = [points[0]];
  const below = [];
  for (let i = 1; i < points.length; i += 1) {
    const a = points[i - 1];
    const b = points[i];
    if (below.length) {
      below.push(b);
    } else if (b[1] >= elevation - 1e-6) {
      above.push(b);
    } else {
      const t = a[1] === b[1] ? 0 : (a[1] - elevation) / (a[1] - b[1]);
      const cut = [a[0] + (b[0] - a[0]) * t, elevation, a[2] + (b[2] - a[2]) * t];
      if (t > 1e-6) above.push(cut);
      below.push(cut, b);
    }
  }
  return { above, below };
}

/**
 * `live` answers two questions from the twin state:
 *   live.isGhost(thingId)  -> the thing is still a project (dashed)
 *   live.bottom(declineId) -> elevation of the decline face
 */
export function buildStatics(geometry, palette, live, terrain) {
  const objects = geometry.objects || {};
  const scenery = geometry.scenery || {};
  const surfaceY = (geometry.frame && geometry.frame.surface) || 430;
  // Without a terrain block the ground is the flat reference surface.
  const groundAt = terrain ? terrain.heightAt : () => surfaceY;
  const drape = (points, dy = LINE_LIFT) => (terrain ? terrain.drape(points, dy)
    : points.map((p) => (p.length === 3 ? [p[0], surfaceY + dy, p[2]] : [p[0], surfaceY + dy, p[1]])));
  const drapeOutline = (footprint, dy = LINE_LIFT) => drape([...footprint, footprint[0]], dy);
  const solid = new MeshBuilder();
  const fills = new MeshBuilder();
  const ghost = new LineBuilder();
  const lines = new LineBuilder();
  const pick = new Map();       // thing id -> sample points for picking near thin objects
  const spheres = new Map();    // thing id -> { center, radius } for focus()
  const anchors = new Map();    // thing id -> label anchor
  const paths = {};             // named polylines for flow beads
  const gauges = new Map();     // pump station id -> sump gauge box
  const ghostColor = palette.tone('planned');

  ghost.use(null, ghostColor);

  // ------------------------------------------------------------- scenery
  const places = [];            // named places without a twin: label anchors
  if (terrain) {
    // The edge of the block: a narrow skirt under the edge of the ground.
    const [x0, z0, x1, z1] = terrain.extent;
    const step = 62.5;
    const edges = [[[x0, z0], [x1, z0]], [[x1, z0], [x1, z1]], [[x1, z1], [x0, z1]], [[x0, z1], [x0, z0]]];
    const inside = [(x0 + x1) / 2, 0, (z0 + z1) / 2];
    solid.use(null, palette.scene('skirt'));
    for (const [a, b] of edges) {
      const n = Math.max(1, Math.round(Math.hypot(b[0] - a[0], b[1] - a[1]) / step));
      for (let k = 0; k < n; k += 1) {
        const p = [a[0] + ((b[0] - a[0]) * k) / n, a[1] + ((b[1] - a[1]) * k) / n];
        const q = [a[0] + ((b[0] - a[0]) * (k + 1)) / n, a[1] + ((b[1] - a[1]) * (k + 1)) / n];
        const hp = groundAt(p[0], p[1]);
        const hq = groundAt(q[0], q[1]);
        inside[1] = (hp + hq) / 2 - SKIRT_DEPTH / 2;
        solid.quad([p[0], hp - 0.3, p[1]], [q[0], hq - 0.3, q[1]], [q[0], hq - SKIRT_DEPTH, q[1]],
          [p[0], hp - SKIRT_DEPTH, p[1]], inside);
      }
    }
  }
  const pit = scenery['old-pit'];
  if (pit && pit.primitive === 'pit') {
    // The carved pit is in the terrain; the bench crests, the rim and the floor are lines on it.
    lines.use(null, palette.scene('pit'));
    for (const bench of pit.benches || []) {
      for (const line of bench.lines || []) {
        if (line.length > 1) lines.path(line.map(([x, z]) => [x, bench.y + 0.6, z]));
      }
    }
    if (Array.isArray(pit.rim) && pit.rim.length > 2) lines.path(lift(pit.rim, 1), true);
    if (Array.isArray(pit.floor_outline) && pit.floor_outline.length > 2) {
      lines.use(null, palette.scene('pitFloor')).outline(pit.floor_outline, pit.floor + 0.6);
    }
    if (Array.isArray(pit.rim) && pit.rim.length > 2) {
      // One of the orientation labels of the scene: over the north rim, beyond the workings.
      const north = pit.rim.reduce((best, p) => (p[p.length - 1] < best[best.length - 1] ? p : best), pit.rim[0]);
      const [x, z] = [north[0], north[north.length - 1]];
      places.push({
        id: 'place:pit', name: 'Карьер', line: `отработан · дно ${elevationText(pit.floor)} м`,
        position: [x, groundAt(x, z) + 14, z], orient: true,
      });
    }
  }
  const plantId = Object.keys(objects).find((id) => objects[id].kind === 'plant') || null;
  for (const [name, item] of Object.entries(scenery)) {
    if (!Array.isArray(item.points)) continue;
    // Already laid on the terrain by the generator: lifted clear of the triangles.
    const path = lift(item.points, LINE_LIFT);
    paths[name] = path;
    const tint = name.startsWith('road') ? 'road' : name.startsWith('stream') || name.startsWith('river') ? 'stream'
      : name === 'conveyor' ? 'road' : 'pipe';
    const route = name === 'conveyor' ? conveyorRoute(path) : null;
    if (!route) {
      lines.use(null, palette.scene(tint), true).path(path);
      continue;
    }
    // The conveyor: a ground line, the inclined gallery on trestles, the crusher house.
    paths[name] = route.path;
    lines.use(null, palette.scene(tint), true).path(route.ground);
    lines.path(route.after);
    solid.use(plantId, palette.scene('steel'), false);
    const g = route.gallery;
    for (let i = 0; i < g.length - 1; i += 1) {
      solid.beam([g[i][0], g[i][1] - 1.4, g[i][2]], [g[i + 1][0], g[i + 1][1] - 1.4, g[i + 1][2]], 3.4, 2.4);
    }
    for (let i = 1; i < g.length - 1; i += 1) {
      const [x, y, z] = g[i];
      const foot = groundAt(x, z);
      if (y - foot > 5) solid.beam([x, foot - 0.5, z], [x, y - 2.6, z], 0.9, 0.9, false);
    }
    const [hx, , hz] = route.house;
    const [a, b] = [route.after[0], route.after[1] || route.after[0]];
    crusherHouse(new SolidWriter(solid, placement([hx, groundAt(hx, hz), hz], [b[0] - a[0], b[2] - a[2]])),
      { key: plantId, walls: palette.scene('building'), roof: palette.scene('roof') });
  }
  if (scenery.yard && scenery.yard.footprint) {
    lines.use(null, palette.scene('site'), true).path(drapeOutline(scenery.yard.footprint));
  }
  if (scenery['industrial-zone'] && scenery['industrial-zone'].footprint) {
    lines.use(null, palette.scene('site'), true).path(drapeOutline(scenery['industrial-zone'].footprint));
  }
  const damLook = { face: palette.model('dam'), crest: palette.model('damCrest') };
  for (const name of ['tsf-cell-south', 'tsf-cell-southeast']) {
    const cell = scenery[name];
    if (!cell || !cell.footprint) continue;
    // No dam number and no capacity: a low bund above the highest ground of the outline.
    const crest = Math.max(...cell.footprint.map(([x, z]) => groundAt(x, z))) + UNNUMBERED_BUND;
    embankment(solid, cell.footprint, crest, cell.y, groundAt, damLook, null);
    lines.use(null, palette.scene('tsfCell'), true).outline(cell.footprint, crest + 0.4);
  }
  const village = scenery.village;
  if (village && Array.isArray(village.anchor)) {
    // The houses of the landscape show the village; its name stands over the mapped village point.
    const [x, , z] = village.anchor;
    places.push({ id: 'place:village', name: 'с. Секисовка', line: 'посёлок', position: [x, groundAt(x, z) + 22, z] });
  }
  const watercourses = [['river-sekisovka', 'р. Секисовка', 'река'], ['stream-volchevka', 'руч. Волчевка', 'ручей']];
  for (const [name, text, line] of watercourses) {
    const item = scenery[name];
    if (!item || !Array.isArray(item.points) || item.points.length < 2) continue;
    // The label sits at 30 % of the course from its first point, clear of the pit.
    const cum = [0];
    for (let i = 1; i < item.points.length; i += 1) {
      const [a, b] = [item.points[i - 1], item.points[i]];
      cum.push(cum[i - 1] + Math.hypot(b[0] - a[0], b[2] - a[2]));
    }
    const at = item.points[cum.findIndex((c) => c >= cum[cum.length - 1] * 0.3)];
    places.push({ id: 'place:' + name, name: text, line, position: [at[0], at[1] + 6, at[2]] });
  }
  solid.use(null, palette.scene('backfill'));
  for (const [name, item] of Object.entries(scenery)) {
    if (name.startsWith('backfill') && item.center) solid.box(item.center, item.size);
  }

  // -------------------------------------------------------------- things
  let frame = null;   // plan box of the underground workings: the x-ray window and the water plane
  const grow = (x, z) => {
    if (!frame) frame = [x, z, x, z];
    frame = [Math.min(frame[0], x), Math.min(frame[1], z), Math.max(frame[2], x), Math.max(frame[3], z)];
  };
  const levels = [];

  for (const [id, o] of Object.entries(objects)) {
    if (Array.isArray(o.anchor)) anchors.set(id, o.anchor);
    if (VEHICLE_KINDS.has(o.kind)) continue;
    const isGhost = live.isGhost(id);

    if (o.kind === 'level' && Array.isArray(o.points)) {
      levels.push(o);
      if (o.extent) {
        grow(o.extent[0], o.extent[1]);
        grow(o.extent[2], o.extent[3]);
      }
      const size = [o.width || 4, o.height || 4];
      if (isGhost) ghost.path(o.points);
      else solid.use(id, palette.scene('drive')).tube(o.points, size[0], size[1]);
      for (const link of o.links || []) {
        if (!Array.isArray(link.points)) continue;
        const open = !isGhost && (!link.planned || live.linkOpen(o, link));
        if (open) solid.use(id, palette.scene('drive')).tube(link.points, 3, 3);
        else ghost.path(link.points);
      }
      pick.set(id, sample(o.points, 40));
      spheres.set(id, sphereOf(o.points));
      // The label sits right of the east end of the drive; the ruler is on the west side.
      const east = o.points[0][0] >= o.points[o.points.length - 1][0] ? o.points[0] : o.points[o.points.length - 1];
      anchors.set(id, east);
    } else if (o.kind === 'stope' && o.center) {
      if (isGhost) ghost.boxEdges(o.center, o.size);
      else lines.use(id, palette.stope('standby')).boxEdges(o.center, o.size);
      pick.set(id, [o.center, [o.center[0] - o.size[0] / 3, o.center[1], o.center[2]],
        [o.center[0] + o.size[0] / 3, o.center[1], o.center[2]]]);
      spheres.set(id, { center: o.center, radius: Math.max(...o.size) * 0.6 });
      anchors.set(id, [o.center[0], o.center[1] + o.size[1] / 2, o.center[2]]);
    } else if (o.kind === 'decline' && Array.isArray(o.points)) {
      // The portal stands with the workings; the drive itself, its bays and
      // turns are drawn apart, behind the stopes (buildDeclines).
      const bottom = live.bottom(id);
      const { above, below } = cutAtElevation(o.points, bottom);
      solid.use(id, palette.tone('ok'));
      for (const node of o.nodes || []) {
        if (node.type === 'portal' && Array.isArray(node.at) && node.elevation >= bottom - 0.5) solid.box(node.at, PORTAL);
      }
      if (below.length > 1) ghost.path(below);
      const shown = above.length > 1 ? above : o.points;
      pick.set(id, sample(shown, 30));
      spheres.set(id, sphereOf(shown));
      for (const p of o.points) grow(p[0], p[2]);
    } else if ((o.kind === 'shaft' || o.kind === 'raise') && o.base) {
      const [x, y0, z] = o.base;
      const radius = Math.max(MIN_AIRWAY_RADIUS, o.radius || 0);
      const split = isGhost ? o.top : Math.max(y0, o.planned_below === undefined ? y0 : o.planned_below);
      if (split < o.top) solid.use(id, palette.scene('airway')).cylinder(x, z, split, o.top, radius, radius, 8);
      if (split > y0) ghost.cylinderEdges(x, z, y0, split, radius);
      if (o.kind === 'shaft' && o.top >= groundAt(x, z) - 3) {
        // The collar at the surface: a headframe, its backstays away from the fan.
        const fanAt = Object.values(objects).find((f) => f.kind === 'main_fan' && f.center
          && Array.isArray(f.airway) && f.airway.includes(id));
        const place = placement([x, o.top, z], fanAt ? [fanAt.center[0] - x, fanAt.center[2] - z] : [1, 0]);
        headframe(isGhost ? new EdgeWriter(ghost, place) : new SolidWriter(solid, place), {
          key: id, house: palette.scene('building'), roof: palette.scene('roof'), steel: palette.scene('airway'),
        });
      }
      const axis = [[x, o.top, z], [x, isGhost ? y0 : split, z]];
      pick.set(id, sample(axis, 30));
      spheres.set(id, sphereOf(axis));
      grow(x, z);
    } else if (o.kind === 'main_fan' && o.center) {
      // The casing points its duct at the shaft it serves (+u), the diffuser away from it.
      const shaft = (o.airway || []).map((a) => objects[a]).find((a) => a && a.kind === 'shaft' && a.base);
      const axis = shaft ? [shaft.base[0] - o.center[0], shaft.base[2] - o.center[2]] : [1, 0];
      const along = Math.abs(axis[0]) >= Math.abs(axis[1]);
      const [sx, sy, sz] = along ? o.size : [o.size[2], o.size[1], o.size[0]];
      const place = placement([o.center[0], o.center[1] - sy / 2, o.center[2]], axis,
        [sx / FAN_BOX[0], sy / FAN_BOX[1], sz / FAN_BOX[2]]);
      fan(isGhost ? new EdgeWriter(ghost, place) : new SolidWriter(solid, place), {
        key: id, casing: palette.tone('ok'), base: palette.scene('concrete'), duct: palette.scene('steel'),
        mouth: palette.scene('fanMouth'), surface: o.center[1] > groundAt(o.center[0], o.center[2]) - 6,
      });
      pick.set(id, [o.center]);
      spheres.set(id, { center: o.center, radius: 30 });
    } else if (o.kind === 'pump_station' && o.center) {
      const elevation = o.elevation === undefined ? o.center[1] : o.elevation;
      const gauge = { center: [o.center[0] + o.size[0] / 2 + 11, elevation + 26, o.center[2]], size: [10, 40, 10] };
      if (isGhost) {
        ghost.boxEdges(o.center, o.size);
        if (Array.isArray(o.pipe)) ghost.path(o.pipe);
      } else {
        pumpStation(new SolidWriter(solid, placement([o.center[0], o.center[1] - o.size[1] / 2, o.center[2]])),
          { key: id, state: palette.tone('ok'), pipe: palette.scene('steel') }, o.size);
        if (o.sump) lines.use(id + '#gauge', palette.tone('info')).boxEdges(o.sump.center, o.sump.size);
        lines.use(id + '#gauge', palette.tone('info')).boxEdges(gauge.center, gauge.size);
        gauges.set(id, gauge);
        if (Array.isArray(o.pipe)) {
          lines.use(id + '#pipe', palette.scene('pipe')).path(o.pipe);
          paths[id + '#pipe'] = o.pipe;
        }
      }
      pick.set(id, [o.center, gauge.center]);
      spheres.set(id, { center: o.center, radius: 45 });
      anchors.set(id, [gauge.center[0], gauge.center[1] + gauge.size[1] / 2 + 2, gauge.center[2]]);
    } else if (o.kind === 'settling_pond' && o.center) {
      // The mapped pond: its water surface, lifted to stay clear of the coarser ground.
      const ring = Array.isArray(o.outline) && o.outline.length > 2 ? o.outline : null;
      const water = o.center[1] + o.size[1] / 2;
      if (ring) {
        const y = Math.max(water, ...ring.map(([x, z]) => groundAt(x, z))) + 0.8;
        solid.use(id, palette.scene('pond')).polygon(ring, y);
        lines.use(null, palette.scene('stream')).outline(ring, y + 0.4);
        pick.set(id, [[o.center[0], y, o.center[2]]]);
      } else {
        solid.use(id, palette.scene('pond')).box(o.center, o.size);
        pick.set(id, [o.center]);
      }
      spheres.set(id, { center: o.center, radius: 40 });
    } else if (o.kind === 'monitoring_point' && o.anchor) {
      const [x, y, z] = o.anchor;
      const head = [x, y + 26, z];
      solid.use(id, palette.tone('ok'));
      solid.beam([x, y, z], head, 1.6, 1.6);
      solid.box(head, [10, 10, 10]);
      pick.set(id, [head, [x, y + 12, z]]);
      spheres.set(id, { center: head, radius: 60 });
      anchors.set(id, [x, y + 32, z]);
    } else if (o.kind === 'plant' && o.footprint) {
      lines.use(id, palette.scene('site')).path(drapeOutline(o.footprint));
      const [cx, cz] = centroid(o.footprint);
      pick.set(id, [[cx, o.y, cz]]);
      spheres.set(id, sphereOf(o.footprint.map(([x, z]) => [x, o.y, z])));
      // Label over the west end, clear of the stockpile label.
      anchors.set(id, [Math.min(...o.footprint.map((p) => p[0])) + 10, o.anchor ? o.anchor[1] : o.y + 16, cz]);
      // The stack stands north-west of the westmost line, between its hall and its tanks.
      const first = Object.values(objects).filter((l) => l.kind === 'plant_line' && l.center)
        .sort((a, b) => a.center[0] - b.center[0])[0];
      if (first) {
        const [sx, sz] = [first.center[0] - 11, first.center[2] - 20];
        stack(new SolidWriter(solid, placement([sx, groundAt(sx, sz), sz])),
          { key: id, stack: palette.scene('stack'), band: palette.scene('stackBand') });
      }
    } else if (o.kind === 'rom_stockpile' && o.base) {
      if (o.pad) lines.use(id, palette.scene('site')).path(drapeOutline(o.pad));
      pick.set(id, [o.base, [o.base[0], o.base[1] + (o.height || 20) / 2, o.base[2]]]);
      spheres.set(id, { center: o.base, radius: (o.radius || 30) * 1.6 });
    } else if (o.kind === 'plant_line' && o.center) {
      // A bay of the mill hall and the CIL tank row of the line; a project is dashed.
      const y0 = o.center[1] - o.size[1] / 2;
      const place = placement([o.center[0], y0, o.center[2]]);
      plantLine(isGhost ? new EdgeWriter(ghost, place) : new SolidWriter(solid, place), {
        key: id, walls: palette.scene('building'), state: palette.tone('ok'),
        tankBase: Math.min(0, groundAt(o.center[0], o.center[2] - 11) - y0) - 1,
      });
      pick.set(id, [o.center]);
      spheres.set(id, { center: o.center, radius: 45 });
    } else if (o.kind === 'tailings_facility' && o.footprint) {
      lines.use(id, palette.scene('site')).path(drapeOutline(o.footprint));
      const [cx, cz] = centroid(o.footprint);
      // Not pickable by proximity: the dams inside it are.
      spheres.set(id, sphereOf(o.footprint.map(([x, z]) => [x, o.y, z])));
      // Label over the north-east corner, clear of the labels of the dams.
      anchors.set(id, [Math.max(...o.footprint.map((p) => p[0])) - 30, (o.anchor ? o.anchor[1] : o.y) + 6,
        Math.min(...o.footprint.map((p) => p[1]))]);
    } else if (o.kind === 'tailings_dam' && o.footprint) {
      const [cx, cz] = centroid(o.footprint);
      if (isGhost) {
        // A project: its crest at `top`, the walls from the ground up, dashed.
        ghost.outline(o.footprint, o.top);
        ghost.path(drapeOutline(o.footprint, 1.2));
        for (const [x, z] of o.footprint) ghost.seg([x, Math.min(o.top, groundAt(x, z)), z], [x, o.top, z]);
      } else {
        // The embankment with its crest at `top`; the crest line carries the state of the dam.
        embankment(solid, o.footprint, o.top, o.bottom, groundAt, damLook, id);
        lines.use(id, palette.tone('idle')).outline(o.footprint, o.top + 0.4);
        // The tailings: a prism from the lowest ground, whose top derive() moves to the fill level,
        // and the pond on it.
        fills.use(id, palette.scene('tailings')).prism(o.footprint, o.bottom, o.bottom + 1);
        fills.use(id + '#pond', palette.scene('tailingsPond')).polygon(shrunk(o.footprint, POND_SHARE), o.bottom + 1);
      }
      pick.set(id, [[cx, o.top, cz], [cx, groundAt(cx, cz), cz]]);
      spheres.set(id, sphereOf(o.footprint.map(([x, z]) => [x, o.top, z])));
      anchors.set(id, [cx, o.top, cz]);
    }
  }

  // ------------------------------------------- x-ray window and the ruler
  const ruler = new LineBuilder();
  let rulerAt = null;
  let xray = null;
  if (frame && levels.length) {
    const [x0, z0, x1, z1] = [frame[0] - 28, frame[1] - 24, frame[2] + 28, frame[3] + 24];
    const lowest = Math.min(...levels.map((l) => l.elevation));
    // The ground is translucent where the line of sight runs on into an
    // ellipsoid around the workings (terrain.js): an oval window that fades
    // out at its rim, without the edges of a box. It reaches west over the
    // elevation ruler and its figures.
    let top = -Infinity;
    for (let i = 0; i <= 12; i += 1) {
      for (let j = 0; j <= 6; j += 1) top = Math.max(top, groundAt(x0 + ((x1 - x0) * i) / 12, z0 + ((z1 - z0) * j) / 6));
    }
    const min = [x0 - 150, lowest - 30, z0];
    const max = [x1, top + 5, z1];
    xray = {
      center: min.map((v, k) => (v + max[k]) / 2 + (k === 1 ? (max[1] - min[1]) * XRAY_LIFT : 0)),
      radii: min.map((v, k) => ((max[k] - v) / 2) * XRAY_GROW[k]),
    };

    // Elevation ruler: a vertical scale left of the levels; the marks are the
    // level elevations and the ground at the ruler. Built in its own frame (x
    // to the right, text in the plane z = 0) so that it can turn to the camera.
    // It stands at the z of most level drives (the ventilation level's drive runs elsewhere).
    const zs = levels.map((l) => l.points[0][2]);
    const driveZ = zs.reduce((best, z) => (zs.filter((v) => v === z).length > zs.filter((v) => v === best).length ? z : best), zs[0]);
    rulerAt = [x0 - 46, 0, driveZ];
    const groundY = Math.round(groundAt(rulerAt[0], rulerAt[2]));
    ruler.use(null, palette.scene('ruler'));
    ruler.seg([0, lowest, 0], [0, groundY, 0]);
    const marks = [...new Set([groundY, ...levels.map((l) => l.elevation)])].sort((a, b) => b - a);
    for (let y = Math.ceil(lowest / 50) * 50; y < groundY; y += 50) ruler.seg([0, y, 0], [5, y, 0]);
    let lastY = Infinity;
    for (const y of marks) {
      ruler.seg([0, y, 0], [12, y, 0]);
      if (lastY - y >= 28) {
        strokeText(ruler, elevationText(y).replace('−', '-'), -10, y - 10, 20);
        lastY = y;
      }
    }
  }

  return {
    solid: solid.build(), fills: fills.build(), ghost: ghost.build(), lines: lines.build(), ruler: ruler.build(),
    rulerAt, pick, spheres, anchors, paths, gauges, frame, xray, places,
  };
}

/**
 * The declines down to their faces, apart from the other workings so that
 * they can be drawn behind the stopes and in two weights. `looks` maps a
 * decline id to { color, strong }: a strong decline (the «Уклоны» preset, a
 * closed decline, a decline or a truck on it selected) is a tube with its bays
 * and turns; the others are a thin line in a quiet colour. Returns { mesh, lines }
 * (built geometry: the tubes, keyed by decline id, and the thin lines).
 */
export function buildDeclines(geometry, live, looks) {
  const tubes = new MeshBuilder();
  const thin = new LineBuilder();
  for (const [id, o] of Object.entries(geometry.objects || {})) {
    if (o.kind !== 'decline' || !Array.isArray(o.points)) continue;
    const look = looks.get(id);
    if (!look) continue;
    const bottom = live.bottom(id);
    const { above } = cutAtElevation(o.points, bottom);
    if (!look.strong) {
      if (above.length > 1) thin.use(id, look.color).path(above);
      continue;
    }
    tubes.use(id, look.color);
    if (above.length > 1) tubes.tube(above, o.width || 4.5, o.height || 4);
    for (const node of o.nodes || []) {
      if (!Array.isArray(node.at) || node.type === 'portal' || node.elevation < bottom - 0.5) continue;
      tubes.box(node.at, node.type === 'bay' ? BAY : TURN_BOX);
    }
  }
  return { mesh: tubes.build(), lines: thin.build() };
}
