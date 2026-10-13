// Static part of the scene, built from model/geometry.json into three merged
// objects: `solid` (triangles of everything that exists), `ghost` (dashed
// outlines of everything that is still a project) and `lines` (thin outlines,
// roads, streams, pipes). A fourth and fifth geometry hold the translucent
// ground with the old pit and the elevation ruler.
//
// Which things are a project is decided by the live twin state, so the whole
// set is rebuilt when a measure turns a planned object into a working one or a
// decline face advances. A rebuild takes a few milliseconds.

import * as THREE from 'three';
import { LineBuilder, MeshBuilder, strokeText } from './kit.js';
import { elevationText } from './texts.js';

const VEHICLE_KINDS = new Set(['haul_truck', 'lhd', 'drill_rig']);
const MIN_AIRWAY_RADIUS = 2.2;   // m: thinner airways vanish at the overview scale

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
export function buildStatics(geometry, palette, live) {
  const objects = geometry.objects || {};
  const scenery = geometry.scenery || {};
  const surfaceY = (geometry.frame && geometry.frame.surface) || 430;
  const solid = new MeshBuilder();
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
  const surface = scenery.surface;
  if (surface && surface.footprint) {
    lines.use(null, palette.color(palette.css['line-strong'])).outline(surface.footprint, surfaceY + 0.2);
    const xs = surface.footprint.map((p) => p[0]);
    const zs = surface.footprint.map((p) => p[1]);
    const [x0, x1, z0, z1] = [Math.min(...xs), Math.max(...xs), Math.min(...zs), Math.max(...zs)];
    solid.use(null, palette.scene('skirt'));
    solid.box([(x0 + x1) / 2, surfaceY - 7, z1], [x1 - x0, 14, 3]);
    solid.box([(x0 + x1) / 2, surfaceY - 7, z0], [x1 - x0, 14, 3]);
    solid.box([x0, surfaceY - 7, (z0 + z1) / 2], [3, 14, z1 - z0]);
    solid.box([x1, surfaceY - 7, (z0 + z1) / 2], [3, 14, z1 - z0]);
  }
  const pit = scenery['old-pit'];
  if (pit) {
    lines.use(null, palette.scene('pit'));
    lines.circle(pit.base[0], pit.top + 0.3, pit.base[2], pit.radius_top, 40);
    lines.circle(pit.base[0], pit.base[1] + 0.3, pit.base[2], pit.radius_base, 28);
  }
  for (const [name, item] of Object.entries(scenery)) {
    if (!Array.isArray(item.points)) continue;
    paths[name] = item.points;
    const tint = name.startsWith('road') ? 'road' : name.startsWith('stream') || name.startsWith('river') ? 'stream'
      : name === 'conveyor' ? 'road' : 'pipe';
    lines.use(null, palette.scene(tint)).path(lift(item.points, 0.8));
  }
  if (scenery.yard && scenery.yard.footprint) {
    solid.use(null, palette.scene('pad')).plate(scenery.yard.footprint, surfaceY + 0.3);
    lines.use(null, palette.scene('road')).outline(scenery.yard.footprint, surfaceY + 0.5);
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
        if (o.center[1] > surfaceY) {   // a surface fan gets its diffuser cone
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
      solid.use(id, palette.scene('pond')).box(o.center, o.size);
      pick.set(id, [o.center]);
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
      solid.use(id, palette.scene('pad')).plate(o.footprint, o.y + 0.3);
      lines.use(id, palette.scene('road')).outline(o.footprint, o.y + 0.5);
      const [cx, cz] = centroid(o.footprint);
      pick.set(id, [[cx, o.y, cz]]);
      spheres.set(id, sphereOf(o.footprint.map(([x, z]) => [x, o.y, z])));
      // Label over the west end, clear of the stockpile label.
      anchors.set(id, [Math.min(...o.footprint.map((p) => p[0])) + 10, o.anchor ? o.anchor[1] : o.y + 16, cz]);
    } else if (o.kind === 'rom_stockpile' && o.base) {
      if (o.pad) {
        solid.use(id, palette.scene('pad')).plate(o.pad, o.base[1] + 0.3);
        lines.use(id, palette.scene('road')).outline(o.pad, o.base[1] + 0.5);
      }
      pick.set(id, [o.base, [o.base[0], o.base[1] + (o.height || 20) / 2, o.base[2]]]);
      spheres.set(id, { center: o.base, radius: (o.radius || 30) * 1.6 });
    } else if (o.kind === 'plant_line' && o.center) {
      if (isGhost) ghost.boxEdges(o.center, o.size);
      else solid.use(id, palette.tone('ok')).box(o.center, o.size);
      pick.set(id, [o.center]);
      spheres.set(id, { center: o.center, radius: 45 });
    } else if (o.kind === 'tailings_facility' && o.footprint) {
      lines.use(id, palette.scene('road')).outline(o.footprint, o.y + 0.5);
      const [cx, cz] = centroid(o.footprint);
      // Not pickable by proximity: the dams inside it are.
      spheres.set(id, sphereOf(o.footprint.map(([x, z]) => [x, o.y, z])));
      // Label over the north-east corner, clear of the labels of the dams.
      anchors.set(id, [Math.max(...o.footprint.map((p) => p[0])) - 30, (o.anchor ? o.anchor[1] : o.y) + 6,
        Math.min(...o.footprint.map((p) => p[1]))]);
    } else if (o.kind === 'tailings_dam' && o.footprint) {
      const [cx, cz] = centroid(o.footprint);
      if (isGhost) {
        ghost.prismEdges(o.footprint, o.bottom, o.top);
      } else {
        solid.use(id, palette.scene('pad')).plate(o.footprint, o.bottom + 0.3);
        lines.use(id, palette.tone('idle')).prismEdges(o.footprint, o.bottom, o.top);
      }
      pick.set(id, [[cx, o.bottom, cz], [cx, o.top, cz]]);
      spheres.set(id, sphereOf(o.footprint.map(([x, z]) => [x, o.bottom, z])));
      anchors.set(id, [cx, o.top, cz]);
    }
  }

  // ----------------------------------------- cutaway frame and the ruler
  const ruler = new LineBuilder();
  let rulerAt = null;
  if (frame && levels.length) {
    const [x0, z0, x1, z1] = [frame[0] - 28, frame[1] - 24, frame[2] + 28, frame[3] + 24];
    const lowest = Math.min(...levels.map((l) => l.elevation));
    lines.use(null, palette.scene('frame'));
    for (const [x, z] of [[x0, z0], [x1, z0], [x1, z1], [x0, z1]]) lines.seg([x, lowest, z], [x, surfaceY, z]);
    lines.path([[x0, lowest, z0], [x1, lowest, z0], [x1, lowest, z1], [x0, lowest, z1]], true);

    // Elevation ruler: a vertical scale left of the levels; the marks are the
    // level elevations and the surface. Built in its own frame (x to the
    // right, text in the plane z = 0) so that it can turn to the camera.
    const driveZ = levels[0].points[0][2];
    rulerAt = [x0 - 46, 0, driveZ];
    ruler.use(null, palette.scene('ruler'));
    ruler.seg([0, lowest, 0], [0, surfaceY, 0]);
    const marks = [...new Set([surfaceY, ...levels.map((l) => l.elevation)])].sort((a, b) => b - a);
    for (let y = Math.ceil(lowest / 50) * 50; y < surfaceY; y += 50) ruler.seg([0, y, 0], [5, y, 0]);
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
    solid: solid.build(), ghost: ghost.build(), lines: lines.build(), ruler: ruler.build(), rulerAt,
    pick, spheres, anchors, paths, gauges, frame, surfaceY,
  };
}

/** Translucent ground: the surface plate with the old pit sunk into it. */
export function buildGround(geometry, palette) {
  const scenery = geometry.scenery || {};
  const surface = scenery.surface;
  const pit = scenery['old-pit'];
  const y = (geometry.frame && geometry.frame.surface) || 430;
  const mesh = new MeshBuilder();
  if (!surface || !surface.footprint) return mesh.build();
  const shape = new THREE.Shape(surface.footprint.map(([x, z]) => new THREE.Vector2(x, z)));
  if (pit) {
    const hole = new THREE.Path();
    hole.absarc(pit.base[0], pit.base[2], pit.radius_top, 0, Math.PI * 2, true);
    shape.holes.push(hole);
  }
  const flat = new THREE.ShapeGeometry(shape, 20);
  const p = flat.getAttribute('position');
  const index = flat.getIndex();
  mesh.use(null, palette.scene('ground'));
  for (let i = 0; i < index.count; i += 3) {
    const v = [0, 1, 2].map((k) => [p.getX(index.getX(i + k)), y, p.getY(index.getX(i + k))]);
    mesh.tri(v[0], v[1], v[2], [v[0][0], y - 1, v[0][2]]);
  }
  flat.dispose();
  if (pit) {
    const [x, floorY, z] = pit.base;
    mesh.use(null, palette.scene('pit'));
    mesh.cylinder(x, z, floorY, pit.top, pit.radius_base, pit.radius_top, 28, false);
    for (let i = 0; i < 28; i += 1) {
      const a0 = (i / 28) * Math.PI * 2;
      const a1 = ((i + 1) / 28) * Math.PI * 2;
      mesh.tri([x, floorY, z], [x + Math.cos(a0) * pit.radius_base, floorY, z + Math.sin(a0) * pit.radius_base],
        [x + Math.cos(a1) * pit.radius_base, floorY, z + Math.sin(a1) * pit.radius_base], [x, floorY - 1, z]);
    }
  }
  return mesh.build();
}
