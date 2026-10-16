// Static part of the scene, built from model/geometry.json into merged
// objects: `solid` (triangles of everything that exists), `fills` (the tailings
// in their dams, whose level follows the twin), `ghost` (dashed outlines of
// everything that is still a project), `lines` (thin outlines, roads, streams,
// pipes, the bench crests of the old pit) and the elevation ruler. The ground
// itself is the terrain mesh (terrain.js); surface outlines are laid on it.
//
// Which things are a project is decided by the live twin state, so the whole
// set is rebuilt when a measure turns a planned object into a working one or a
// decline face advances. A rebuild takes a few milliseconds.

import * as THREE from 'three';
import { LineBuilder, MeshBuilder, strokeText } from './kit.js';
import { elevationText } from './texts.js';

const VEHICLE_KINDS = new Set(['haul_truck', 'lhd', 'drill_rig']);
const MIN_AIRWAY_RADIUS = 2.2;   // m: thinner airways vanish at the overview scale
const LINE_LIFT = 1.8;           // m: surface lines above the ground, clear of the triangles
const SKIRT_DEPTH = 24;          // m: the edge of the terrain block

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
  }
  for (const [name, item] of Object.entries(scenery)) {
    if (!Array.isArray(item.points)) continue;
    // Already laid on the terrain by the generator: lifted clear of the triangles.
    const path = lift(item.points, LINE_LIFT);
    paths[name] = path;
    const tint = name.startsWith('road') ? 'road' : name.startsWith('stream') || name.startsWith('river') ? 'stream'
      : name === 'conveyor' ? 'road' : 'pipe';
    lines.use(null, palette.scene(tint)).path(path);
  }
  if (scenery.yard && scenery.yard.footprint) {
    lines.use(null, palette.scene('site')).path(drapeOutline(scenery.yard.footprint));
  }
  if (scenery['industrial-zone'] && scenery['industrial-zone'].footprint) {
    lines.use(null, palette.scene('site')).path(drapeOutline(scenery['industrial-zone'].footprint));
  }
  for (const name of ['tsf-cell-south', 'tsf-cell-southeast']) {
    const cell = scenery[name];
    if (cell && cell.footprint) lines.use(null, palette.scene('tsfCell')).path(drapeOutline(cell.footprint, 2.5));
  }
  const village = scenery.village;
  if (village && Array.isArray(village.anchor)) {
    const [x, , z] = village.anchor;
    const y = groundAt(x, z);
    const head = [x, y + 24, z];
    solid.use(null, palette.scene('village'));
    solid.beam([x, y, z], head, 1.8, 1.8);
    solid.box(head, [8, 8, 8]);
    places.push({ id: 'place:village', name: 'с. Секисовка', line: 'посёлок', position: [x, y + 30, z] });
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
  let frame = null;   // plan box of the underground workings, for the cutaway frame
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
      const bottom = live.bottom(id);
      const { above, below } = cutAtElevation(o.points, bottom);
      solid.use(id, palette.tone('ok'));
      if (above.length > 1) solid.tube(above, o.width || 4.5, o.height || 4);
      const built = [];
      for (const node of o.nodes || []) {
        if (!Array.isArray(node.at)) continue;
        if (node.elevation >= bottom - 0.5) {
          const size = node.type === 'portal' ? [16, 9, 12] : node.type === 'bay' ? [18, 6, 9] : [10, 6, 11];
          solid.box(node.at, size);
          built.push(node.at);
        }
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
      const axis = [[x, o.top, z], [x, isGhost ? y0 : split, z]];
      pick.set(id, sample(axis, 30));
      spheres.set(id, sphereOf(axis));
      grow(x, z);
    } else if (o.kind === 'main_fan' && o.center) {
      if (isGhost) {
        ghost.boxEdges(o.center, o.size);
      } else {
        solid.use(id, palette.tone('ok')).box(o.center, o.size);
        if (o.center[1] > groundAt(o.center[0], o.center[2]) - 6) {   // a surface fan gets its diffuser cone
          const top = o.center[1] + o.size[1] / 2;
          solid.cylinder(o.center[0], o.center[2], top, top + 7, 2.4, 4.2, 8);
        }
      }
      pick.set(id, [o.center]);
      spheres.set(id, { center: o.center, radius: 30 });
    } else if (o.kind === 'pump_station' && o.center) {
      const elevation = o.elevation === undefined ? o.center[1] : o.elevation;
      const gauge = { center: [o.center[0] + o.size[0] / 2 + 11, elevation + 26, o.center[2]], size: [10, 40, 10] };
      if (isGhost) {
        ghost.boxEdges(o.center, o.size);
        if (Array.isArray(o.pipe)) ghost.path(o.pipe);
      } else {
        solid.use(id, palette.tone('ok')).box(o.center, o.size);
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
    } else if (o.kind === 'rom_stockpile' && o.base) {
      if (o.pad) lines.use(id, palette.scene('site')).path(drapeOutline(o.pad));
      pick.set(id, [o.base, [o.base[0], o.base[1] + (o.height || 20) / 2, o.base[2]]]);
      spheres.set(id, { center: o.base, radius: (o.radius || 30) * 1.6 });
    } else if (o.kind === 'plant_line' && o.center) {
      if (isGhost) ghost.boxEdges(o.center, o.size);
      else solid.use(id, palette.tone('ok')).box(o.center, o.size);
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
      // The dam: its crest at `top`, the walls from the ground up; the base outline lies on the ground.
      const edges = isGhost ? ghost : lines.use(id, palette.tone('idle'));
      edges.outline(o.footprint, o.top);
      edges.path(drapeOutline(o.footprint, 1.2));
      for (const [x, z] of o.footprint) edges.seg([x, Math.min(o.top, groundAt(x, z)), z], [x, o.top, z]);
      // The tailings: a prism from the lowest ground, whose top derive() moves to the fill level.
      if (!isGhost) fills.use(id, palette.scene('tailings')).prism(o.footprint, o.bottom, o.bottom + 1);
      pick.set(id, [[cx, o.top, cz], [cx, groundAt(cx, cz), cz]]);
      spheres.set(id, sphereOf(o.footprint.map(([x, z]) => [x, o.top, z])));
      anchors.set(id, [cx, o.top, cz]);
    }
  }

  // ------------------------------- cutaway frame, x-ray box and the ruler
  const ruler = new LineBuilder();
  let rulerAt = null;
  let xray = null;
  if (frame && levels.length) {
    const [x0, z0, x1, z1] = [frame[0] - 28, frame[1] - 24, frame[2] + 28, frame[3] + 24];
    const lowest = Math.min(...levels.map((l) => l.elevation));
    const corners = [[x0, z0], [x1, z0], [x1, z1], [x0, z1]];
    lines.use(null, palette.scene('frame'));
    for (const [x, z] of corners) lines.seg([x, lowest, z], [x, groundAt(x, z), z]);
    lines.path(corners.map(([x, z]) => [x, lowest, z]), true);
    // The ground is translucent where the line of sight runs on into this box (terrain.js).
    let top = -Infinity;
    for (let i = 0; i <= 12; i += 1) {
      for (let j = 0; j <= 6; j += 1) top = Math.max(top, groundAt(x0 + ((x1 - x0) * i) / 12, z0 + ((z1 - z0) * j) / 6));
    }
    // It reaches west over the elevation ruler and its figures.
    xray = { min: [x0 - 150, lowest - 30, z0], max: [x1, top + 5, z1] };

    // Elevation ruler: a vertical scale left of the levels; the marks are the
    // level elevations and the ground at the ruler. Built in its own frame (x
    // to the right, text in the plane z = 0) so that it can turn to the camera.
    const driveZ = levels[0].points[0][2];
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
