// Geometry kit of the 3D scene: builders that merge many small shapes into one
// buffer geometry each (spec 4.5: static geometry merged, no lights; the one
// texture is the satellite image of the terrain). Shading is baked into the
// vertex colours, so every material is a MeshBasicMaterial and the scene needs
// no light at all.

import * as THREE from 'three';

/** The one light of the scene, baked into vertex colours (and applied to the instanced landscape models). */
export const LIGHT_DIR = [-0.35, 0.8, 0.48];
const LIGHT = new THREE.Vector3().fromArray(LIGHT_DIR).normalize();

/** Baked brightness of a face with the given unit normal: 0.5 (away) … 1 (facing the light). */
export function faceShade(nx, ny, nz) {
  const d = nx * LIGHT.x + ny * LIGHT.y + nz * LIGHT.z;
  return 0.5 + 0.25 * (1 + d);
}

const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const norm = (a) => {
  const l = Math.hypot(a[0], a[1], a[2]) || 1;
  return [a[0] / l, a[1] / l, a[2] / l];
};
const mix = (p, a, sa, b, sb) => [p[0] + a[0] * sa + b[0] * sb, p[1] + a[1] * sa + b[1] * sb, p[2] + a[2] * sa + b[2] * sb];

function addRange(ranges, key, from, to) {
  if (key === null || to <= from) return;
  const list = ranges.get(key);
  if (!list) ranges.set(key, [[from, to]]);
  else if (list[list.length - 1][1] === from) list[list.length - 1][1] = to;
  else list.push([from, to]);
}

/**
 * Triangles with flat faces. Every shape is added under a key (a thing id or a
 * local name); the built object can recolour the vertices of a key and tell the
 * key of a face that a ray has hit.
 */
export class MeshBuilder {
  constructor() {
    this.pos = [];
    this.shade = [];
    this.col = [];
    this.idx = [];
    this.owner = [];        // per triangle: index into this.keys
    this.keys = [null];
    this.keyIndex = new Map();
    this.ranges = new Map();
    this.key = null;
    this.paintKey = null;
    this.keyNo = 0;
    this.rgb = [1, 1, 1];
    this.start = 0;
  }

  /**
   * Shapes added from now on belong to `key` and get the base colour `color`.
   * With `paint` false they still belong to the key (a ray that hits them names
   * it) but keep their colour when the key is recoloured: the neutral walls,
   * frames and pipes of a building whose state colour is on its roof or tanks.
   */
  use(key, color, paint = true) {
    this.flush();
    this.key = key === undefined ? null : key;
    this.paintKey = paint ? this.key : null;
    if (this.key === null) this.keyNo = 0;
    else {
      if (!this.keyIndex.has(this.key)) {
        this.keyIndex.set(this.key, this.keys.length);
        this.keys.push(this.key);
      }
      this.keyNo = this.keyIndex.get(this.key);
    }
    this.rgb = [color.r, color.g, color.b];
    return this;
  }

  flush() {
    const count = this.pos.length / 3;
    addRange(this.ranges, this.paintKey, this.start, count);
    this.start = count;
  }

  /**
   * Flat convex polygon (points in order, any plane), split as a fan from its
   * first point; `inside` is any point on the inner side, used to orient it.
   */
  face(points, inside) {
    if (points.length < 3) return;
    let n = norm(cross(sub(points[1], points[0]), sub(points[2], points[0])));
    let order = points;
    if (inside && dot(n, sub(points[0], inside)) < 0) {
      n = [-n[0], -n[1], -n[2]];
      order = points.slice().reverse();
    }
    const s = faceShade(n[0], n[1], n[2]);
    const base = this.pos.length / 3;
    for (const p of order) {
      this.pos.push(p[0], p[1], p[2]);
      this.shade.push(s);
      this.col.push(this.rgb[0] * s, this.rgb[1] * s, this.rgb[2] * s);
    }
    for (let i = 1; i < order.length - 1; i += 1) {
      this.idx.push(base, base + i, base + i + 1);
      this.owner.push(this.keyNo);
    }
  }

  /** Quad a-b-c-d; `inside` is any point on the inner side, used to orient the face. */
  quad(a, b, c, d, inside) {
    let n = norm(cross(sub(b, a), sub(c, a)));
    let order = [a, b, c, d];
    if (inside && dot(n, sub(a, inside)) < 0) {
      n = [-n[0], -n[1], -n[2]];
      order = [a, d, c, b];
    }
    const s = faceShade(n[0], n[1], n[2]);
    const base = this.pos.length / 3;
    for (const p of order) {
      this.pos.push(p[0], p[1], p[2]);
      this.shade.push(s);
      this.col.push(this.rgb[0] * s, this.rgb[1] * s, this.rgb[2] * s);
    }
    this.idx.push(base, base + 1, base + 2, base, base + 2, base + 3);
    this.owner.push(this.keyNo, this.keyNo);
  }

  tri(a, b, c, inside) {
    let n = norm(cross(sub(b, a), sub(c, a)));
    let order = [a, b, c];
    if (inside && dot(n, sub(a, inside)) < 0) {
      n = [-n[0], -n[1], -n[2]];
      order = [a, c, b];
    }
    const s = faceShade(n[0], n[1], n[2]);
    const base = this.pos.length / 3;
    for (const p of order) {
      this.pos.push(p[0], p[1], p[2]);
      this.shade.push(s);
      this.col.push(this.rgb[0] * s, this.rgb[1] * s, this.rgb[2] * s);
    }
    this.idx.push(base, base + 1, base + 2);
    this.owner.push(this.keyNo);
  }

  /** Solid between two parallel 4-corner rings. */
  hexa(r0, r1, caps = true) {
    const c = [0, 1, 2].map((i) => (r0[0][i] + r0[2][i] + r1[0][i] + r1[2][i]) / 4);
    for (let i = 0; i < 4; i += 1) {
      const j = (i + 1) % 4;
      this.quad(r0[i], r0[j], r1[j], r1[i], c);
    }
    if (caps) {
      this.quad(r0[0], r0[1], r0[2], r0[3], c);
      this.quad(r1[0], r1[1], r1[2], r1[3], c);
    }
  }

  box(center, size) {
    const [x, y, z] = center;
    const [hx, hy, hz] = [size[0] / 2, size[1] / 2, size[2] / 2];
    const ring = (yy) => [[x - hx, yy, z - hz], [x + hx, yy, z - hz], [x + hx, yy, z + hz], [x - hx, yy, z + hz]];
    this.hexa(ring(y - hy), ring(y + hy));
  }

  /** Box-section beam from p to q: `width` across (horizontal), `height` in the vertical plane. */
  beam(p, q, width, height, caps = true) {
    const dir = norm(sub(q, p));
    let side = cross(dir, [0, 1, 0]);
    if (Math.hypot(side[0], side[1], side[2]) < 1e-3) side = [1, 0, 0];
    side = norm(side);
    const up = norm(cross(side, dir));
    const ring = (o) => [mix(o, side, -width / 2, up, -height / 2), mix(o, side, width / 2, up, -height / 2),
      mix(o, side, width / 2, up, height / 2), mix(o, side, -width / 2, up, height / 2)];
    this.hexa(ring(p), ring(q), caps);
  }

  /** Polyline of beams with a small overlap at the joints. */
  tube(points, width, height) {
    for (let i = 0; i < points.length - 1; i += 1) this.beam(points[i], points[i + 1], width, height);
  }

  /** Vertical cylinder or frustum (radius r0 at y0, r1 at y1). */
  cylinder(x, z, y0, y1, r0, r1 = r0, segments = 8, caps = true) {
    const mid = [x, (y0 + y1) / 2, z];
    const at = (r, y, i) => {
      const a = (i / segments) * Math.PI * 2;
      return [x + Math.cos(a) * r, y, z + Math.sin(a) * r];
    };
    for (let i = 0; i < segments; i += 1) {
      this.quad(at(r0, y0, i), at(r0, y0, i + 1), at(r1, y1, i + 1), at(r1, y1, i), mid);
      if (caps) {
        if (r1 > 0) this.tri([x, y1, z], at(r1, y1, i), at(r1, y1, i + 1), mid);
        if (r0 > 0) this.tri([x, y0, z], at(r0, y0, i), at(r0, y0, i + 1), mid);
      }
    }
  }

  /** Flat polygon (any simple footprint, concave too: plan pairs [x, z]) at elevation y, facing up. */
  polygon(footprint, y) {
    const ring = openRing(footprint);
    if (ring.length < 3) return;
    const faces = THREE.ShapeUtils.triangulateShape(ring.map(([x, z]) => new THREE.Vector2(x, z)), []);
    const below = [ring[0][0], y - 1, ring[0][1]];
    for (const [a, b, c] of faces) {
      this.tri([ring[a][0], y, ring[a][1]], [ring[b][0], y, ring[b][1]], [ring[c][0], y, ring[c][1]], below);
    }
  }

  /** Prism of a footprint from y0 to y1: the walls (facing out) and the top. */
  prism(footprint, y0, y1) {
    const ring = openRing(footprint);
    if (ring.length < 3) return;
    let area = 0;
    for (let i = 0; i < ring.length; i += 1) {
      const p = ring[i];
      const q = ring[(i + 1) % ring.length];
      area += p[0] * q[1] - q[0] * p[1];
    }
    const sign = area >= 0 ? 1 : -1;
    for (let i = 0; i < ring.length; i += 1) {
      const p = ring[i];
      const q = ring[(i + 1) % ring.length];
      // A point just inside the wall: the outward normal of the edge p-q is sign * (dz, -dx).
      const [dx, dz] = [q[0] - p[0], q[1] - p[1]];
      const l = Math.hypot(dx, dz) || 1;
      const inside = [(p[0] + q[0]) / 2 - (sign * dz) / l, (y0 + y1) / 2, (p[1] + q[1]) / 2 + (sign * dx) / l];
      this.quad([p[0], y0, p[1]], [q[0], y0, q[1]], [q[0], y1, q[1]], [p[0], y1, p[1]], inside);
    }
    this.polygon(ring, y1);
  }

  build() {
    this.flush();
    const geometry = new THREE.BufferGeometry();
    const position = new THREE.Float32BufferAttribute(this.pos, 3);
    geometry.setAttribute('position', position);
    const color = new THREE.Float32BufferAttribute(this.col, 3);
    geometry.setAttribute('color', color);
    const count = this.pos.length / 3;
    geometry.setIndex(count > 65535 ? new THREE.Uint32BufferAttribute(this.idx, 1) : new THREE.Uint16BufferAttribute(this.idx, 1));
    geometry.computeBoundingSphere();
    const { shade, ranges, owner, keys } = this;
    const last = new Map();
    let built = null;   // positions as built, for setLevel
    return {
      geometry,
      triangles: this.idx.length / 3,
      has: (key) => ranges.has(key),
      /** Recolour the vertices of a key; returns true when something changed. */
      setColor(key, c) {
        const list = ranges.get(key);
        if (!list) return false;
        const tag = c.r.toFixed(4) + c.g.toFixed(4) + c.b.toFixed(4);
        if (last.get(key) === tag) return false;
        last.set(key, tag);
        const array = color.array;
        for (const [from, to] of list) {
          for (let i = from; i < to; i += 1) {
            const s = shade[i];
            array[i * 3] = c.r * s;
            array[i * 3 + 1] = c.g * s;
            array[i * 3 + 2] = c.b * s;
          }
        }
        color.needsUpdate = true;
        return true;
      },
      keyOfFace: (faceIndex) => keys[owner[faceIndex]] || null,
      /**
       * Move the vertices of a key that were built above elevation `split` to
       * elevation `y` (the level of a fill); returns true when something changed.
       */
      setLevel(key, split, y) {
        const list = ranges.get(key);
        if (!list) return false;
        const tag = 'level' + y.toFixed(2);
        if (last.get('level:' + key) === tag) return false;
        last.set('level:' + key, tag);
        if (!built) built = Float32Array.from(position.array);
        for (const [from, to] of list) {
          for (let i = from; i < to; i += 1) {
            if (built[i * 3 + 1] > split) position.array[i * 3 + 1] = y;
          }
        }
        position.needsUpdate = true;
        geometry.computeBoundingSphere();
        geometry.boundingBox = null;
        return true;
      },
    };
  }
}

/** Footprint without a closing duplicate of its first point. */
function openRing(footprint) {
  const n = footprint.length;
  if (n > 1 && footprint[0][0] === footprint[n - 1][0] && footprint[0][1] === footprint[n - 1][1]) {
    return footprint.slice(0, n - 1);
  }
  return footprint;
}

/**
 * Line segments with a colour per vertex and recolourable key ranges. A line
 * written after use(key, color, true) lies on the ground: its vertices carry
 * `xraySurface` 1, and it thins out in the x-ray window (terrain.js).
 */
export class LineBuilder {
  constructor() {
    this.pos = [];
    this.col = [];
    this.surf = [];
    this.ranges = new Map();
    this.key = null;
    this.rgb = [1, 1, 1];
    this.surface = 0;
    this.start = 0;
  }

  use(key, color, surface = false) {
    this.flush();
    this.key = key === undefined ? null : key;
    this.rgb = [color.r, color.g, color.b];
    this.surface = surface ? 1 : 0;
    return this;
  }

  flush() {
    const count = this.pos.length / 3;
    addRange(this.ranges, this.key, this.start, count);
    this.start = count;
  }

  seg(a, b) {
    this.pos.push(a[0], a[1], a[2], b[0], b[1], b[2]);
    this.col.push(this.rgb[0], this.rgb[1], this.rgb[2], this.rgb[0], this.rgb[1], this.rgb[2]);
    this.surf.push(this.surface, this.surface);
  }

  path(points, closed = false) {
    for (let i = 0; i < points.length - 1; i += 1) this.seg(points[i], points[i + 1]);
    if (closed && points.length > 2) this.seg(points[points.length - 1], points[0]);
  }

  /** Outline of a plan footprint at elevation y. */
  outline(footprint, y) {
    this.path(footprint.map(([x, z]) => [x, y, z]), true);
  }

  boxEdges(center, size) {
    const [x, y, z] = center;
    const [hx, hy, hz] = [size[0] / 2, size[1] / 2, size[2] / 2];
    const ring = (yy) => [[x - hx, yy, z - hz], [x + hx, yy, z - hz], [x + hx, yy, z + hz], [x - hx, yy, z + hz]];
    const low = ring(y - hy);
    const high = ring(y + hy);
    this.path(low, true);
    this.path(high, true);
    for (let i = 0; i < 4; i += 1) this.seg(low[i], high[i]);
  }

  circle(x, y, z, radius, segments = 24) {
    const pts = [];
    for (let i = 0; i < segments; i += 1) {
      const a = (i / segments) * Math.PI * 2;
      pts.push([x + Math.cos(a) * radius, y, z + Math.sin(a) * radius]);
    }
    this.path(pts, true);
  }

  /** Vertical airway drawn as three verticals and two rings. */
  cylinderEdges(x, z, y0, y1, radius) {
    for (let i = 0; i < 3; i += 1) {
      const a = (i / 3) * Math.PI * 2 + 0.5;
      const p = [x + Math.cos(a) * radius, 0, z + Math.sin(a) * radius];
      this.seg([p[0], y0, p[2]], [p[0], y1, p[2]]);
    }
    this.circle(x, y0, z, radius, 8);
    this.circle(x, y1, z, radius, 8);
  }

  build() {
    this.flush();
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(this.pos, 3));
    const color = new THREE.Float32BufferAttribute(this.col, 3);
    geometry.setAttribute('color', color);
    // Always present (a shader attribute without a buffer reads whatever its slot last held); a float,
    // as a normalised byte attribute did not reach the line shader.
    geometry.setAttribute('xraySurface', new THREE.Float32BufferAttribute(this.surf, 1));
    geometry.computeBoundingSphere();
    const { ranges } = this;
    const last = new Map();
    return {
      geometry,
      segments: this.pos.length / 6,
      has: (key) => ranges.has(key),
      setColor(key, c) {
        const list = ranges.get(key);
        if (!list) return false;
        const tag = c.r.toFixed(4) + c.g.toFixed(4) + c.b.toFixed(4);
        if (last.get(key) === tag) return false;
        last.set(key, tag);
        const array = color.array;
        for (const [from, to] of list) {
          for (let i = from; i < to; i += 1) {
            array[i * 3] = c.r;
            array[i * 3 + 1] = c.g;
            array[i * 3 + 2] = c.b;
          }
        }
        color.needsUpdate = true;
        return true;
      },
    };
  }
}

// Seven-segment strokes for the elevation ruler (digits and signs as plain
// line segments: no font texture is needed). Cell is 1 wide and 2 high.
const SEG = {
  a: [0, 2, 1, 2], b: [1, 2, 1, 1], c: [1, 1, 1, 0], d: [0, 0, 1, 0], e: [0, 1, 0, 0], f: [0, 2, 0, 1], g: [0, 1, 1, 1],
};
const GLYPH = {
  0: 'abcdef', 1: 'bc', 2: 'abged', 3: 'abgcd', 4: 'fgbc', 5: 'afgcd', 6: 'afgedc', 7: 'abc', 8: 'abcdefg',
  9: 'abfgcd',
};

/**
 * Add `text` (digits, + and -) to a LineBuilder, right-aligned so that it ends
 * at x = right; the baseline is y, the text plane is z = 0 of the builder frame.
 */
export function strokeText(lines, text, right, y, height) {
  const w = height / 2;
  const gap = w * 0.5;
  // The digit 1 is a single stroke: it gets a narrow cell, so that +100 has even spacing.
  const widthOf = (ch) => (ch === '1' ? 0.12 : ch === '+' || ch === '-' ? 0.8 : 1) * w;
  let total = -gap;
  for (const ch of text) total += widthOf(ch) + gap;
  let x = right - total;
  for (const ch of text) {
    const cw = widthOf(ch);
    if (ch === '+') {
      lines.seg([x, y + height / 2, 0], [x + cw, y + height / 2, 0]);
      lines.seg([x + cw / 2, y + height / 2 - cw / 2, 0], [x + cw / 2, y + height / 2 + cw / 2, 0]);
    } else if (ch === '-') {
      lines.seg([x, y + height / 2, 0], [x + cw, y + height / 2, 0]);
    } else if (ch === '1') {
      lines.seg([x + cw, y, 0], [x + cw, y + height, 0]);
    } else {
      for (const name of GLYPH[ch] || '') {
        const s = SEG[name];
        lines.seg([x + s[0] * w, y + s[1] * w, 0], [x + s[2] * w, y + s[3] * w, 0]);
      }
    }
    x += cw + gap;
  }
}

/** Point at a distance along a polyline given as arrays; also returns the direction. */
export function pointAlong(points, cum, distance, out, dirOut) {
  const total = cum[cum.length - 1];
  const d = Math.max(0, Math.min(total, distance));
  let i = 1;
  while (i < cum.length - 1 && cum[i] < d) i += 1;
  const a = points[i - 1];
  const b = points[i];
  const span = cum[i] - cum[i - 1] || 1;
  const t = (d - cum[i - 1]) / span;
  out.set(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t);
  if (dirOut) dirOut.set(b[0] - a[0], b[1] - a[1], b[2] - a[2]);
  return out;
}

/** Cumulative lengths of a polyline: [0, l1, l1 + l2, …]. */
export function cumulative(points) {
  const cum = [0];
  for (let i = 1; i < points.length; i += 1) {
    cum.push(cum[i - 1] + Math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1],
      points[i][2] - points[i - 1][2]));
  }
  return cum;
}
