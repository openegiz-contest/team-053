// Low-poly models of the equipment and buildings, drawn in code (no model
// files, no textures). Every model is written once in its own frame (u along
// the machine or building, y up, w across; metres) through a "writer": the
// solid writer adds flat-shaded faces to a MeshBuilder, the edge writer adds
// the outlines of the same faces to a LineBuilder (dashed: still a project).
//
// Mobile units (truck, LHD, drill rig) and the pumps become one small buffer
// geometry each, normalised to a unit box centred on the origin (bottom at
// y = -0.5), so that the scene draws them as instances scaled to the size of
// the twin, exactly as the boxes they replace. Their vertex colours carry the
// baked shade times a grey value: 1 for the paint, which takes the colour of
// the instance (loaded or empty, the kind, a pump state), and dark values for
// tyres, glass and joints, which stay dark whatever the instance colour.
//
// Buildings and fixed equipment (fans, headframes, plant lines, the crusher
// house and its gallery, the stack, the pump-station plinth) are written into
// the merged static meshes of statics.js.
//
// Proportions: CAT AD30 / AD45 underground trucks (about 10.2–11.2 m long,
// 2.7–3.0 m wide, 2.6–2.8 m high, articulated, dump body over the rear axle),
// CAT R1300 / R1700 LHDs (8.7–10.6 m with the bucket, low profile, side cab),
// Epiroc Boomer S1D / T1D face rigs (one boom each; 11.8 m with the feed in
// tramming position, 1.9 m wide), from the twin sizes in geometry.json.

import { MeshBuilder } from './kit.js';

// Grey values of the parts that keep their colour (multiplied by the instance colour).
const PAINT = 1;
const TYRE = 0.17;
const GLASS = 0.3;
const DARK = 0.45;
const STEEL = 0.68;

const grey = (v) => ({ r: v, g: v, b: v });
const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const unit = (a) => {
  const l = Math.hypot(a[0], a[1], a[2]) || 1;
  return [a[0] / l, a[1] / l, a[2] / l];
};
const centroid = (points) => {
  const c = [0, 0, 0];
  for (const p of points) {
    c[0] += p[0] / points.length;
    c[1] += p[1] / points.length;
    c[2] += p[2] / points.length;
  }
  return c;
};

/**
 * Placement of a model: local (u, y, w) -> world origin + u * axis + y * up +
 * w * side, where axis is a horizontal direction [dx, dz] and side = axis x up
 * (to the right of a machine that faces +u). `scale` stretches the local axes.
 */
export function placement(origin = [0, 0, 0], axis = [1, 0], scale = [1, 1, 1]) {
  const l = Math.hypot(axis[0], axis[1]) || 1;
  const [dx, dz] = [axis[0] / l, axis[1] / l];
  return ([u, y, w]) => {
    const a = u * scale[0];
    const b = y * scale[1];
    const c = w * scale[2];
    return [origin[0] + a * dx - c * dz, origin[1] + b, origin[2] + a * dz + c * dx];
  };
}

const IDENTITY = (p) => p;

/** Shapes in the local frame of a model, made of flat convex faces. */
class Writer {
  constructor(place) {
    this.place = place || IDENTITY;
  }

  // Face primitives: implemented by the solid and the edge writer.
  poly() {}

  use() {
    return this;
  }

  quad(a, b, c, d, inside) {
    this.poly([a, b, c, d], inside);
  }

  /** Axis-aligned block in the local frame; the bottom face is left out unless asked for. */
  block(u0, u1, y0, y1, w0, w1, bottom = false) {
    const ring = (y) => [[u0, y, w0], [u1, y, w0], [u1, y, w1], [u0, y, w1]];
    this.hexa(ring(y0), ring(y1), bottom, true);
  }

  /** Solid between two 4-corner rings (corresponding corners in the same order). */
  hexa(r0, r1, cap0 = true, cap1 = true) {
    const inside = centroid([...r0, ...r1]);
    for (let i = 0; i < 4; i += 1) {
      const j = (i + 1) % 4;
      this.quad(r0[i], r0[j], r1[j], r1[i], inside);
    }
    if (cap0) this.poly(r0, inside);
    if (cap1) this.poly(r1, inside);
  }

  /** Box-section beam from p to q: `width` across, `height` in the plane of the beam and the vertical. */
  beam(p, q, width, height, caps = true) {
    const dir = unit(sub(q, p));
    let side = cross(dir, [0, 1, 0]);
    if (Math.hypot(side[0], side[1], side[2]) < 1e-3) side = [0, 0, 1];
    side = unit(side);
    const up = unit(cross(side, dir));
    const ring = (o) => [[-1, -1], [1, -1], [1, 1], [-1, 1]].map(([s, t]) => [
      o[0] + side[0] * s * width / 2 + up[0] * t * height / 2,
      o[1] + side[1] * s * width / 2 + up[1] * t * height / 2,
      o[2] + side[2] * s * width / 2 + up[2] * t * height / 2]);
    this.hexa(ring(p), ring(q), caps, caps);
  }

  /** Ring of `n` points around the axis p -> q at p (or q), radius r; `phase` turns it. */
  ring(center, dir, r, n, phase) {
    let e1 = cross(dir, [0, 1, 0]);
    if (Math.hypot(e1[0], e1[1], e1[2]) < 1e-3) e1 = [1, 0, 0];
    e1 = unit(e1);
    const e2 = unit(cross(e1, dir));
    const out = [];
    for (let i = 0; i < n; i += 1) {
      const a = phase + (i / n) * Math.PI * 2;
      const [c, s] = [Math.cos(a) * r, Math.sin(a) * r];
      out.push([center[0] + e1[0] * c + e2[0] * s, center[1] + e1[1] * c + e2[1] * s, center[2] + e1[2] * c + e2[2] * s]);
    }
    return out;
  }

  /** Cylinder or frustum from p (radius r0) to q (radius r1) with n sides; caps optional. */
  cyl(p, q, r0, r1, n = 8, cap0 = true, cap1 = true, phase = 0, skip = null) {
    const dir = unit(sub(q, p));
    const a = this.ring(p, dir, r0, n, phase);
    const b = this.ring(q, dir, r1, n, phase);
    const inside = [(p[0] + q[0]) / 2, (p[1] + q[1]) / 2, (p[2] + q[2]) / 2];
    this.tube(a, b, inside, cap0, cap1, skip);
  }

  /** Sides between two rings (`skip`: indices of sides never seen) and optional caps. */
  tube(a, b, inside, cap0, cap1, skip = null) {
    const n = a.length;
    for (let i = 0; i < n; i += 1) {
      if (skip && skip.includes(i)) continue;
      const j = (i + 1) % n;
      this.quad(a[i], a[j], b[j], b[i], inside);
    }
    if (cap0) this.poly(a, inside);
    if (cap1) this.poly(b, inside);
  }

  /** Convex side profile [[u, y], …] extruded across from w0 to w1. */
  extrude(profile, w0, w1) {
    const a = profile.map(([u, y]) => [u, y, w0]);
    const b = profile.map(([u, y]) => [u, y, w1]);
    this.tube(a, b, centroid([...a, ...b]), true, true);
  }

  /** Four walls (no floor, no top) of a block. */
  walls(u0, u1, y0, y1, w0, w1) {
    const ring = (y) => [[u0, y, w0], [u1, y, w0], [u1, y, w1], [u0, y, w1]];
    this.hexa(ring(y0), ring(y1), false, false);
  }

  /** Pitched roof over u0..u1 x w0..w1: eaves at yEave, ridge along u at yRidge. */
  roof(u0, u1, w0, w1, yEave, yRidge) {
    const wm = (w0 + w1) / 2;
    const inside = [(u0 + u1) / 2, yEave - 0.5, wm];
    this.quad([u0, yEave, w0], [u1, yEave, w0], [u1, yRidge, wm], [u0, yRidge, wm], inside);
    this.quad([u0, yEave, w1], [u1, yEave, w1], [u1, yRidge, wm], [u0, yRidge, wm], inside);
    this.poly([[u0, yEave, w0], [u0, yEave, w1], [u0, yRidge, wm]], inside);
    this.poly([[u1, yEave, w0], [u1, yEave, w1], [u1, yRidge, wm]], inside);
  }
}

/** Writes faces into a MeshBuilder. */
export class SolidWriter extends Writer {
  constructor(mesh, place) {
    super(place);
    this.mesh = mesh;
  }

  use(key, color, paint = true) {
    this.mesh.use(key, color, paint);
    return this;
  }

  poly(points, inside) {
    this.mesh.face(points.map(this.place), this.place(inside));
  }
}

/** Writes the outlines of the same faces into a LineBuilder (the dashed project). */
export class EdgeWriter extends Writer {
  constructor(lines, place) {
    super(place);
    this.lines = lines;
  }

  poly(points) {
    this.lines.path(points.map(this.place), true);
  }

  // A cylinder outline: its two rings and four generators, not every facet.
  tube(a, b) {
    this.lines.path(a.map(this.place), true);
    this.lines.path(b.map(this.place), true);
    const n = a.length;
    for (let i = 0; i < n; i += Math.max(1, Math.floor(n / 4))) this.lines.seg(this.place(a[i]), this.place(b[i]));
  }
}

// ------------------------------------------------------------ mobile units

/**
 * One axle: a hexagonal prism across the whole width, flat side down; its
 * caps are the wheels. The flat top (inside the body) and the flat bottom (on
 * the ground) are never seen and left out.
 */
function axle(s, u, r, halfWidth) {
  s.cyl([u, r, -halfWidth], [u, r, halfWidth], r, r, 6, true, true, 0, [1, 4]);
}

/** Corners of a cross-section at u: from y0 to y1, half width hw. */
const section = (u, y0, y1, hw) => [[u, y0, -hw], [u, y0, hw], [u, y1, hw], [u, y1, -hw]];

// Underground articulated truck (CAT AD45 frame: 11 x 2.8 x 3 m), facing +u.
const TRUCK = { length: 11, height: 2.8, width: 3 };
const TUB = { front: 1.0, rear: -5.5, floor: 1.0, flatTo: -3.7, tail: 1.95, topRear: 2.62, topFront: 2.8, half: 1.47, wall: 0.16 };

function truck(s) {
  s.use(null, grey(TYRE));
  axle(s, 3.7, 0.86, 1.5);
  axle(s, -2.5, 0.86, 1.5);
  // Front frame with the engine, lower at the nose.
  s.use(null, grey(PAINT));
  s.hexa(section(5.5, 0.7, 1.45, 1.12), section(1.3, 0.7, 1.8, 1.25), true, false);
  // Low cab on the left of the front frame: glass band and roof.
  s.use(null, grey(GLASS)).block(1.3, 2.9, 1.7, 2.42, -1.4, -0.22);
  s.use(null, grey(PAINT)).block(1.15, 3.05, 2.42, 2.56, -1.46, -0.16);
  // Articulation joint.
  s.use(null, grey(DARK)).walls(0.6, 1.3, 0.55, 1.35, -0.55, 0.55);
  // Dump body: an open tub whose floor rises to the tail.
  s.use(null, grey(PAINT));
  const t = TUB;
  const top = (u) => t.topRear + ((u - t.rear) / (t.front - t.rear)) * (t.topFront - t.topRear);
  const outer = [[t.front, t.floor], [t.flatTo, t.floor + 0.05], [t.rear, t.tail], [t.rear, t.topRear], [t.front, t.topFront]];
  const inside = [-2.2, 1.9, 0];
  for (const w of [-t.half, t.half]) s.poly(outer.map(([u, y]) => [u, y, w]), inside);
  for (let i = 0; i < outer.length; i += 1) {
    if (i === 3) continue;   // the top edge: rim and interior below
    const [a, b] = [outer[i], outer[(i + 1) % outer.length]];
    s.quad([a[0], a[1], -t.half], [b[0], b[1], -t.half], [b[0], b[1], t.half], [a[0], a[1], t.half], inside);
  }
  const [uf, ur, wi] = [t.front - t.wall, t.rear + t.wall, t.half - t.wall];
  const below = (u, w) => [u, top(u) - 1, w];
  // Rim.
  s.quad([t.front, top(t.front), -t.half], [t.front, top(t.front), t.half], [uf, top(uf), wi], [uf, top(uf), -wi], below(t.front - 0.08, 0));
  s.quad([t.rear, top(t.rear), -t.half], [t.rear, top(t.rear), t.half], [ur, top(ur), wi], [ur, top(ur), -wi], below(t.rear + 0.08, 0));
  for (const sign of [-1, 1]) {
    s.quad([t.front, top(t.front), sign * t.half], [t.rear, top(t.rear), sign * t.half], [ur, top(ur), sign * wi],
      [uf, top(uf), sign * wi], below(-2, sign * (t.half - 0.08)));
  }
  // Interior: floor, tail slope, end walls and side walls, all facing into the tub.
  s.use(null, grey(0.78));
  const f0 = [uf, t.floor + t.wall];
  const f1 = [t.flatTo + 0.1, t.floor + 0.05 + t.wall];
  const f2 = [ur, t.tail + 0.08];
  s.quad([f0[0], f0[1], -wi], [f1[0], f1[1], -wi], [f1[0], f1[1], wi], [f0[0], f0[1], wi], [-1, 0, 0]);
  s.quad([f1[0], f1[1], -wi], [f2[0], f2[1], -wi], [f2[0], f2[1], wi], [f1[0], f1[1], wi], [-4.6, 1.0, 0]);
  s.quad([f2[0], f2[1], -wi], [f2[0], f2[1], wi], [ur, top(ur), wi], [ur, top(ur), -wi], [ur - 1, 2.3, 0]);
  s.quad([uf, f0[1], -wi], [uf, f0[1], wi], [uf, top(uf), wi], [uf, top(uf), -wi], [uf + 1, 2, 0]);
  for (const sign of [-1, 1]) {
    s.poly([f0, f1, f2, [ur, top(ur)], [uf, top(uf)]].map(([u, y]) => [u, y, sign * wi]), [-2, 2, sign * (wi + 1)]);
  }
}

/** The ore in the truck body: a ridge over the tub. */
function truckLoad(s) {
  s.use(null, grey(PAINT));
  const [u0, u1, y, hw, top] = [0.75, -4.9, 2.45, 1.22, 3.35];
  const [r0, r1] = [0.0, -3.9];
  const inside = [-2, y + 0.2, 0];
  s.quad([u0, y, hw], [u1, y, hw], [r1, top, 0], [r0, top, 0], inside);
  s.quad([u0, y, -hw], [u1, y, -hw], [r1, top, 0], [r0, top, 0], inside);
  s.poly([[u0, y, -hw], [u0, y, hw], [r0, top, 0]], inside);
  s.poly([[u1, y, -hw], [u1, y, hw], [r1, top, 0]], inside);
}

// LHD loader (CAT R1700 frame: 10.6 x 2.6 x 2.7 m), bucket at +u.
const LHD = { length: 10.6, height: 2.6, width: 2.7 };
const BUCKET = [[5.3, 0.08], [3.7, 0.08], [3.55, 1.5], [4.35, 1.62]];

function lhd(s) {
  s.use(null, grey(TYRE));
  axle(s, 2.2, 0.8, 1.35);
  axle(s, -1.8, 0.8, 1.35);
  s.use(null, grey(PAINT));
  s.extrude(BUCKET, -1.35, 1.35);
  // Lift arms from the front frame to the back of the bucket.
  for (const w of [-1.02, 1.02]) s.beam([1.2, 1.95, w], [3.7, 1.05, w], 0.3, 0.42, false);
  s.block(1.0, 3.6, 0.45, 1.35, -0.8, 0.8);                  // front frame
  s.hexa(section(0.5, 0.45, 1.5, 1.2), section(-5.3, 0.6, 1.95, 1.3), true, true);   // engine frame
  s.use(null, grey(DARK)).walls(0.45, 1.05, 0.55, 1.25, -0.5, 0.5);                    // joint
  // The bucket mouth, darker.
  const [a, b] = BUCKET[3];
  const [c, d] = BUCKET[0];
  const n = unit([b - d, c - a, 0]);   // outward normal of the mouth face in the u-y plane
  const lift = (p, k) => [p[0] + n[0] * 0.03, p[1] + n[1] * 0.03, k];
  s.quad(lift([a + (c - a) * 0.08, b + (d - b) * 0.08], -1.22), lift([a + (c - a) * 0.08, b + (d - b) * 0.08], 1.22),
    lift([a + (c - a) * 0.9, b + (d - b) * 0.9], 1.22), lift([a + (c - a) * 0.9, b + (d - b) * 0.9], -1.22), [4.2, 0.6, 0]);
  // Side cab: glass and roof.
  s.use(null, grey(GLASS)).block(-0.9, 0.8, 1.5, 2.38, -1.32, -0.32);
  s.use(null, grey(PAINT)).block(-1.0, 0.9, 2.38, 2.6, -1.38, -0.26);
}

/** Ore in the bucket (an LHD that mucks or loads a truck). */
function lhdLoad(s) {
  s.use(null, grey(PAINT));
  const [a, b] = BUCKET[3];
  const [c, d] = BUCKET[0];
  const n = unit([b - d, c - a, 0]);
  const at = (k, h, w) => [a + (c - a) * k + n[0] * h, b + (d - b) * k + n[1] * h, w];
  const inside = at(0.5, -0.3, 0);
  const [p0, p1, q0, q1] = [at(0.05, 0, -1.25), at(0.05, 0, 1.25), at(0.92, 0, -1.25), at(0.92, 0, 1.25)];
  const [r0, r1] = [at(0.3, 0.55, 0), at(0.7, 0.55, 0)];
  s.quad(p0, q0, r1, r0, inside);
  s.quad(p1, q1, r1, r0, inside);
  s.poly([p0, p1, r0], inside);
  s.poly([q0, q1, r1], inside);
}

// Face drill rig (Boomer S1D: 11.8 x 2.2 x 1.9 m with the feed forward), boom at +u.
const RIG = { length: 11.8, height: 2.2, width: 1.9 };

function rig(s) {
  s.use(null, grey(TYRE));
  axle(s, 0.9, 0.55, 0.95);
  axle(s, -3.4, 0.55, 0.95);
  s.use(null, grey(PAINT));
  s.hexa(section(-1.4, 0.35, 1.35, 0.9), section(-5.9, 0.4, 1.3, 0.95), true, true);   // power pack
  s.block(-1.4, 2.0, 0.35, 1.0, -0.78, 0.78);                                          // front carrier
  s.beam([1.5, 0.95, 0], [3.5, 1.42, 0], 0.34, 0.38);                                  // boom
  s.use(null, grey(GLASS)).block(-1.2, 0.5, 1.0, 1.92, -0.82, 0.82);                    // canopy
  s.use(null, grey(PAINT)).block(-1.35, 0.65, 1.92, 2.12, -0.95, 0.95);
  s.use(null, grey(STEEL));
  s.beam([2.2, 1.62, 0], [5.9, 1.62, 0], 0.28, 0.3);                                   // feed beam
  s.cyl([-4.35, 1.75, -0.72], [-4.35, 1.75, 0.72], 0.5, 0.5, 6, true, true, 0, [4]);   // cable reel
}

// Pump with its motor on a skid (local x along the pump row, motor axis across).
const PUMP = { length: 4.2, height: 3.4, width: 7 };

function pump(s) {
  s.use(null, grey(0.62)).block(-2.1, 2.1, 0, 0.5, -3.5, 3.5);
  s.use(null, grey(PAINT));
  s.cyl([0, 1.75, -3.3], [0, 1.75, 0.7], 1.25, 1.25, 6, true, true, Math.PI / 2);
  s.block(-1.5, 1.5, 0.5, 3.4, 1.0, 3.3);
}

/** A model written into its own buffer geometry, normalised to the unit box (y from -0.5 to 0.5). */
function unitGeometry(write, dims) {
  const mesh = new MeshBuilder();
  write(new SolidWriter(mesh));
  const built = mesh.build();
  const geometry = built.geometry;
  geometry.translate(0, -dims.height / 2, 0);
  geometry.scale(1 / dims.length, 1 / dims.height, 1 / dims.width);
  geometry.computeBoundingSphere();
  return geometry;
}

/**
 * The instanced geometries of the moving units and the pumps. Each is drawn
 * with the transform of the box it replaces: position at the centre of the
 * unit, x along the direction of travel, scale = [length, height, width].
 */
export function buildUnitModels() {
  return {
    haul_truck: unitGeometry(truck, TRUCK),
    truckLoad: unitGeometry(truckLoad, TRUCK),
    lhd: unitGeometry(lhd, LHD),
    lhdLoad: unitGeometry(lhdLoad, LHD),
    drill_rig: unitGeometry(rig, RIG),
    pump: unitGeometry(pump, PUMP),
  };
}

// ------------------------------------------------------- fixed equipment

/**
 * Main fan in the frame of its box (10 x 6 x 8 m at the surface): base frame,
 * cylindrical casing with flanges and a duct at +u (towards the shaft collar).
 * A surface fan turns its diffuser up through an elbow (the evase stands
 * above the box, which keeps the fan readable from far away); a fan in a
 * chamber underground has a straight, flared diffuser at -u. `look` gives the
 * colours: casing (state), base, duct and the dark mouth.
 */
export const FAN_BOX = [10, 6, 8];

export function fan(s, look) {
  s.use(look.key, look.base, false).block(-4.8, 4.2, -1, 0.7, -2.5, 2.5);
  s.use(look.key, look.duct, false).block(3.6, 5.6, 1.1, 4.9, -1.8, 1.8);
  s.use(look.key, look.casing);
  s.cyl([-1.4, 3, 0], [3.6, 3, 0], 2.2, 2.2, 8, false, false);
  let mouth;
  if (look.surface) {
    s.cyl([-1.4, 3, 0], [-3.2, 4.6, 0], 2.2, 2.2, 8, false, false);   // elbow
    s.cyl([-3.5, 4.4, 0], [-3.5, 10.5, 0], 2.15, 3.1, 8, false, false);
    mouth = { at: [-3.5, 10.5, 0], dir: [0, 1, 0], inside: [-3.5, 9, 0] };
  } else {
    s.cyl([-5, 3, 0], [-1.4, 3, 0], 3.0, 2.2, 8, false, false);
    mouth = { at: [-5, 3, 0], dir: [1, 0, 0], inside: [-4, 3, 0] };
  }
  // The flange between the casing and the diffuser.
  s.use(look.key, look.duct, false);
  s.cyl([-1.45, 3, 0], [-0.95, 3, 0], 2.5, 2.5, 8, false, false);
  s.use(look.key, look.mouth, false).poly(s.ring(mouth.at, mouth.dir, look.surface ? 3.1 : 3.0, 8, 0), mouth.inside);
}

/**
 * Headframe over a shaft collar (the collar at the origin; +u towards the
 * fan): a collar house with a pitched roof, a four-legged braced tower with
 * its head, and two backstays away from the fan.
 */
export function headframe(s, look) {
  const [h, foot, head] = [21, 2.7, 2.0];
  s.use(look.key, look.house, false).walls(-4.5, 4.5, -0.6, 6, -4.5, 4.5);
  s.use(look.key, look.roof, false).roof(-4.9, 4.9, -4.9, 4.9, 6, 8.2);
  s.use(look.key, look.steel);
  for (const [a, b] of [[-1, -1], [1, -1], [1, 1], [-1, 1]]) {
    s.beam([a * foot, -0.5, b * foot], [a * head, h, b * head], 0.9, 0.9, false);
  }
  for (const b of [-1, 1]) {
    // X-bracing on the two long faces above the roof.
    const at = (y) => foot + ((head - foot) * y) / h;
    s.beam([-at(8.5), 8.5, b * at(8.5)], [at(h - 1), h - 1, b * at(h - 1)], 0.5, 0.5, false);
    s.beam([at(8.5), 8.5, b * at(8.5)], [-at(h - 1), h - 1, b * at(h - 1)], 0.5, 0.5, false);
    s.beam([-head, h - 0.5, b * head], [-12, -0.5, b * 3.2], 0.8, 0.8, false);   // backstay
  }
  s.block(-2.8, 2.8, h, h + 1.6, -2.8, 2.8);
}

/**
 * One plant line in its own frame (u east along the row of lines, w south,
 * the origin at the centre of the line on the ground): a bay of the mill hall
 * (walls neutral, roof in the state colour; the bays of the lines make one
 * long building) and its row of four CIL tanks to the north.
 */
export function plantLine(s, look) {
  s.use(look.key, look.walls, false).walls(-13.5, 13.5, -1.5, 10, 3, 25);
  s.use(look.key, look.state);
  s.roof(-13.5, 13.5, 3, 25, 10, 15);
  for (const w of [-21.5, -14.5, -7.5, -0.5]) s.cyl([0, look.tankBase, w], [0, 9, w], 3, 3, 6, false, true, Math.PI / 6);
}

/** Crusher house (the gallery arrives at its top): walls and a pitched roof. */
export function crusherHouse(s, look) {
  s.use(look.key, look.walls, false).walls(-7, 7, -1.5, 15, -7, 7);
  s.use(look.key, look.roof, false).roof(-7.4, 7.4, -7.4, 7.4, 15, 18.5);
}

/** Stack of the plant (gold room and elution), with a red band at the top. */
export function stack(s, look) {
  s.use(look.key, look.stack, false).cyl([0, -1, 0], [0, 33, 0], 1.8, 1.2, 8, false, false);
  s.use(look.key, look.band, false).cyl([0, 33, 0], [0, 38, 0], 1.2, 1.05, 8, false, true);
}

/**
 * Underground pump station in the frame of its box: a plinth in the state
 * colour (the pumps stand on it as instances, coloured by pump) and the
 * discharge header along the row.
 */
export const PLINTH = 1.4;   // m: height of the plinth; the pumps stand on it
export const PUMP_SIZE = [PUMP.length, PUMP.height, PUMP.width];

export function pumpStation(s, look, size) {
  const [hx, hz] = [size[0] / 2, size[2] / 2];
  s.use(look.key, look.state).block(-hx, hx, 0, PLINTH, -hz, hz, true);
  s.use(look.key, look.pipe, false).cyl([-hx + 0.8, PLINTH + PUMP.height + 1.4, 0], [hx - 0.8, PLINTH + PUMP.height + 1.4, 0],
    0.6, 0.6, 6, false, false);
}
