// The stylised surface of the scene (spec 4.2), drawn from the OpenStreetMap
// extract model/terrain/landscape.json (served at /terrain/landscape.json) on
// the real terrain of terrain.js. Nothing here is a picture: the surface stays
// sharp at any distance.
//
// The ground: every triangle of the terrain mesh is cut along the land-cover
// outlines; each piece lies in the plane of its triangle (so the surface is
// exactly the drawn terrain and heightAt still holds) and takes the flat colour
// of what covers it, times a soft hillshade. Open land that no area covers is
// meadow. Contour lines are added by the ground material (terrain.js).
//
// Roads and waterways: ribbons of their class width, split wherever they cross
// an edge of the terrain triangles, so that they lie on the drawn ground, a
// few decimetres above it.
//
// The models on it, all procedural: houses and blocks (instanced boxes fitted
// to the OSM footprints, gable roofs on the small ones, flat roofs on the large
// ones), buildings of other shapes extruded from their footprints, trees
// (instanced) in the woods and along the waterways, the waste heaps as mounds,
// walls and fences. A seeded generator places the trees, so every load draws
// the same landscape. The models share the ground's x-ray window.

import * as THREE from 'three';
import { MeshBuilder } from './kit.js';

export const LANDSCAPE_URL = '/terrain/landscape.json';

// Half widths of the drawn roads and waterways by OSM class (m).
const ROAD_HALF = {
  primary: 4.5, secondary: 4, tertiary: 3.5, unclassified: 3, residential: 3, living_street: 2.5, service: 2.25,
  track: 1.6, path: 0.8, footway: 0.8,
};
const WATER_HALF = { river: 2.6, stream: 1.3 };
const RIBBON_LIFT = { road: 0.45, water: 0.3 };   // m above the ground: a road crosses a stream over it
const RIBBON_TOL = 0.15;     // m: a split point is kept where the ground under the ribbon bends more than this
const PAVED_SURFACES = new Set(['asphalt', 'paved', 'concrete', 'paving_stones']);
const DIRT_SURFACES = new Set(['unpaved', 'ground', 'dirt', 'gravel', 'compacted', 'earth']);
// What covers a point, for the trees (classAt): the pit (the carved ground
// carries nothing else), water, the roads (over a stream: a bridge or a
// culvert), the waterways, then the land-cover areas in their file order. The
// ground itself takes the colour of the areas only (areaAt); the roads and
// waterways are ribbons on it.
const STRIP_ORDER = ['paved', 'road', 'dirt', 'track', 'path', 'river'];
const LEAD_AREAS = new Set(['pit', 'water']);

const CUT_PIECE = 25;        // m: long outline edges are cut in pieces of at most this length
const HASH_CELL = 31.25;     // m: cell of the spatial hashes
const EPS = 1e-6;
const MIN_AREA = 1e-3;       // m2: thinner slivers are dropped

// Buildings (no heights are mapped here: OSM gives building:levels on 389 of 470).
const STOREY = 3;            // m per level
const WALLS_DEFAULT = 3;     // m: a house without levels has one
const BIG_FOOTPRINT = 320;   // m2: larger footprints get a flat roof
const BIG_WALLS = 6;         // m: walls of a large building without levels
const INDUSTRIAL_WALLS = 7;  // m: walls of building=industrial without levels
const ROOF_RISE = 0.8;       // gable rise as a share of the wall height (about 31 degrees on a house)
const BOXY = 0.82;           // footprint area / fitted box area at or above which the box is drawn
const BURY = 0.4;            // m: walls start this far below the lowest ground of the footprint

// Trees: one per WOOD_SPACING square in a wood, and pairs along the waterways
// every RIVER_SPACING metres, both wider where the cap would be passed. The
// caps keep the trees within the triangle budget (13 triangles a tree).
const WOOD_SPACING = 11;
const RIVER_SPACING = 18;
const TREE_CAP = { wood: 640, river: 320, park: 40 };
const TREE_HEIGHT = [7, 13];   // m
const TREE_CROWN = 0.4;        // crown radius as a share of the height
const TREE_SEED = 20261016;

const HEAP_SLOPE = Math.tan(34 * Math.PI / 180);   // the angle of repose of the heap sides
const BARRIER = { wall: [0.35, 2.2], fence: [0.12, 1.6] };   // thickness, height (m)
const BARRIER_STEP = 30;     // m: walls follow the ground in pieces of at most this length

// Hillshade of the stylised ground: light from the north-west, high (as the
// photo's in terrain.js), softer, and a little lighter with height.
const SUN = new THREE.Vector3(-0.45, 0.78, -0.43).normalize();
const SHADE_GAIN = 1.6;
const SHADE_RANGE = [0.7, 1.12];
const HYPSO = [450, 110, 0.07];   // m of the middle, m to either end, the brightness change at the ends

const EMPTY = [];
const WHITE = new THREE.Color(1, 1, 1);
const Y_AXIS = new THREE.Vector3(0, 1, 0);

/** Spatial hash of items by their bounding boxes. */
class Hash {
  constructor(cell) {
    this.cell = cell;
    this.map = new Map();
  }

  add(item, x0, z0, x1, z1) {
    const c = this.cell;
    for (let i = Math.floor(x0 / c); i <= Math.floor(x1 / c); i += 1) {
      for (let j = Math.floor(z0 / c); j <= Math.floor(z1 / c); j += 1) {
        const key = (i + 4096) * 8192 + j + 4096;
        const list = this.map.get(key);
        if (list) list.push(item);
        else this.map.set(key, [item]);
      }
    }
  }

  at(x, z) {
    const c = this.cell;
    return this.map.get((Math.floor(x / c) + 4096) * 8192 + Math.floor(z / c) + 4096) || EMPTY;
  }

  /** Every item of the cells under a box; an item may come more than once. */
  each(x0, z0, x1, z1, visit) {
    const c = this.cell;
    for (let i = Math.floor(x0 / c); i <= Math.floor(x1 / c); i += 1) {
      for (let j = Math.floor(z0 / c); j <= Math.floor(z1 / c); j += 1) {
        const list = this.map.get((i + 4096) * 8192 + j + 4096);
        if (list) for (const item of list) visit(item);
      }
    }
  }
}

/** Deterministic generator in [0, 1) (mulberry32). */
function random(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const pairs = (flat) => {
  const out = [];
  for (let i = 0; i + 1 < flat.length; i += 2) out.push([flat[i], flat[i + 1]]);
  return out;
};

function boxOf(points) {
  const box = [Infinity, Infinity, -Infinity, -Infinity];
  for (const [x, z] of points) {
    if (x < box[0]) box[0] = x;
    if (z < box[1]) box[1] = z;
    if (x > box[2]) box[2] = x;
    if (z > box[3]) box[3] = z;
  }
  return box;
}

function inRing(x, z, ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i, i += 1) {
    const [xi, zi] = ring[i];
    const [xj, zj] = ring[j];
    if ((zi > z) !== (zj > z) && x < xi + ((z - zi) * (xj - xi)) / (zj - zi)) inside = !inside;
  }
  return inside;
}

function ringArea(ring) {
  let s = 0;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i, i += 1) s += ring[j][0] * ring[i][1] - ring[i][0] * ring[j][1];
  return s / 2;
}

/** Distance from (x, z) to the nearest edge of a ring. */
function ringDistance(x, z, ring) {
  let best = Infinity;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i, i += 1) {
    const [ax, az] = ring[j];
    const [bx, bz] = ring[i];
    const dx = bx - ax;
    const dz = bz - az;
    const l2 = dx * dx + dz * dz;
    const t = l2 > 0 ? Math.max(0, Math.min(1, ((x - ax) * dx + (z - az) * dz) / l2)) : 0;
    best = Math.min(best, Math.hypot(x - ax - dx * t, z - az - dz * t));
  }
  return best;
}

/** The surface classes of the data: which class covers a point, and what to cut the ground along. */
export function createCover(data) {
  const areas = [];
  const areaHash = new Hash(HASH_CELL * 2);
  const cuts = [];             // [ax, az, bx, bz]
  const cutHash = new Hash(HASH_CELL);
  const strips = [];             // road and waterway segments: what a tree must keep off
  const stripHash = new Hash(HASH_CELL);
  const lines = [];              // the same as polylines, for the ribbons

  const addCut = (ax, az, bx, bz) => {
    const n = Math.max(1, Math.ceil(Math.hypot(bx - ax, bz - az) / CUT_PIECE));
    for (let k = 0; k < n; k += 1) {
      const s = [ax + ((bx - ax) * k) / n, az + ((bz - az) * k) / n, ax + ((bx - ax) * (k + 1)) / n,
        az + ((bz - az) * (k + 1)) / n];
      cuts.push(s);
      cutHash.add(s, Math.min(s[0], s[2]), Math.min(s[1], s[3]), Math.max(s[0], s[2]), Math.max(s[1], s[3]));
    }
  };
  const addRing = (ring) => {
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i, i += 1) addCut(ring[j][0], ring[j][1], ring[i][0], ring[i][1]);
  };

  // Where areas overlap, the class earlier in class_order wins (the heaps colour the ground under their mounds).
  const ranks = data.class_order || [];
  const rank = (cls) => (ranks.includes(cls) ? ranks.indexOf(cls) : ranks.length);
  const items = [...(data.areas || []), ...(data.heaps || []).map((h) => ({ ...h, class: 'heap' }))];
  items.forEach((item, k) => {
    const ring = pairs(item.ring || []);
    if (ring.length < 3) return;
    const order = LEAD_AREAS.has(item.class) ? -1 : rank(item.class) * 1e4 + k;
    const area = { cls: item.class, ring, box: boxOf(ring), order };
    areas.push(area);
    areaHash.add(area, ...area.box);
    addRing(ring);
  });

  const addStrip = (cls, half, line) => {
    const pts = pairs(line);
    const rank = STRIP_ORDER.indexOf(cls);
    for (let i = 0; i + 1 < pts.length; i += 1) {
      const [ax, az] = pts[i];
      const [bx, bz] = pts[i + 1];
      const length = Math.hypot(bx - ax, bz - az);
      if (length < EPS) continue;
      const ux = (bx - ax) / length;
      const uz = (bz - az) / length;
      const strip = { cls, rank, half, ax, az, bx, bz, ux, uz, length, capA: i === 0, capB: i + 2 === pts.length };
      strips.push(strip);
      stripHash.add(strip, Math.min(ax, bx) - half, Math.min(az, bz) - half, Math.max(ax, bx) + half,
        Math.max(az, bz) + half);
    }
    if (pts.length > 1) lines.push({ cls, half, lift: RIBBON_LIFT[cls === 'river' ? 'water' : 'road'], points: pts });
  };
  for (const road of data.roads || []) {
    const half = ROAD_HALF[road.highway];
    if (!half) continue;
    const paved = road.highway === 'primary' || road.highway === 'secondary' || road.highway === 'tertiary'
      || PAVED_SURFACES.has(road.surface);
    const cls = paved ? 'paved' : road.highway === 'track' ? 'track'
      : road.highway === 'path' || road.highway === 'footway' ? 'path' : DIRT_SURFACES.has(road.surface) ? 'dirt' : 'road';
    addStrip(cls, half, road.line || []);
  }
  for (const way of data.waterways || []) {
    const half = WATER_HALF[way.waterway];
    if (half) addStrip('river', half, way.line || []);
  }

  const onStrip = (s, x, z) => {
    const t = (x - s.ax) * s.ux + (z - s.az) * s.uz;
    if ((t < 0 && s.capA) || (t > s.length && s.capB)) return false;
    const c = Math.max(0, Math.min(s.length, t));
    return Math.hypot(x - s.ax - s.ux * c, z - s.az - s.uz * c) <= s.half;
  };

  const areaOf = (x, z) => {
    let best = null;
    for (const a of areaHash.at(x, z)) {
      if (best && a.order >= best.order) continue;
      if (x < a.box[0] || x > a.box[2] || z < a.box[1] || z > a.box[3] || !inRing(x, z, a.ring)) continue;
      best = a;
    }
    return best;
  };

  /** The land-cover class at (x, z): the class of the strongest area there, or meadow. */
  function areaAt(x, z) {
    const best = areaOf(x, z);
    return best ? best.cls : 'meadow';
  }

  /** What covers (x, z), roads and waterways included: pit, water, a road class, an area class or meadow. */
  function classAt(x, z) {
    const best = areaOf(x, z);
    if (best && best.order < 0) return best.cls;
    let strip = null;
    for (const s of stripHash.at(x, z)) {
      if (strip && s.rank >= strip.rank) continue;
      if (onStrip(s, x, z)) strip = s;
    }
    if (strip) return strip.cls === 'river' ? 'water' : strip.cls;
    return best ? best.cls : 'meadow';
  }

  return { classAt, areaAt, cutHash, areas, strips, lines, cuts: cuts.length };
}

// --------------------------------------------------------------- the ground

/** Hillshade factor of the stylised ground at (x, z), from the slope of the drawn terrain. */
export function groundShade(terrain) {
  const h = 15.625;
  const n = new THREE.Vector3();
  return (x, z) => {
    const y = terrain.heightAt(x, z);
    const dx = terrain.heightAt(x + h, z) - terrain.heightAt(x - h, z);
    const dz = terrain.heightAt(x, z + h) - terrain.heightAt(x, z - h);
    n.set(-dx, 2 * h, -dz).normalize();
    const s = THREE.MathUtils.clamp(1 + SHADE_GAIN * (n.dot(SUN) - SUN.y), SHADE_RANGE[0], SHADE_RANGE[1]);
    return s * (1 + HYPSO[2] * THREE.MathUtils.clamp((y - HYPSO[0]) / HYPSO[1], -1, 1));
  };
}

/**
 * Split the convex polygon `poly` ([[x, z], ...]) by the line of segment `s`
 * where the segment itself crosses it; returns the two parts or null.
 */
function split(poly, s) {
  const [ax, az, bx, bz] = s;
  const dx = bx - ax;
  const dz = bz - az;
  const length = Math.hypot(dx, dz);
  if (length < EPS) return null;
  const nx = -dz / length;
  const nz = dx / length;
  const d = poly.map(([x, z]) => (x - ax) * nx + (z - az) * nz);
  let pos = false;
  let neg = false;
  for (const v of d) {
    if (v > EPS) pos = true;
    else if (v < -EPS) neg = true;
  }
  if (!pos || !neg) return null;
  const left = [];
  const right = [];
  let tMin = Infinity;
  let tMax = -Infinity;
  for (let i = 0; i < poly.length; i += 1) {
    const j = (i + 1) % poly.length;
    const p = poly[i];
    if (d[i] >= -EPS) left.push(p);
    if (d[i] <= EPS) right.push(p);
    if ((d[i] > EPS && d[j] < -EPS) || (d[i] < -EPS && d[j] > EPS)) {
      const t = d[i] / (d[i] - d[j]);
      const q = [p[0] + (poly[j][0] - p[0]) * t, p[1] + (poly[j][1] - p[1]) * t];
      left.push(q);
      right.push(q);
      const along = ((q[0] - ax) * dx + (q[1] - az) * dz) / (length * length);
      tMin = Math.min(tMin, along);
      tMax = Math.max(tMax, along);
    } else if (Math.abs(d[i]) <= EPS) {
      const along = ((p[0] - ax) * dx + (p[1] - az) * dz) / (length * length);
      tMin = Math.min(tMin, along);
      tMax = Math.max(tMax, along);
    }
  }
  // The segment must reach into the polygon, not only its line.
  const margin = 0.01 / length;
  if (tMax <= margin || tMin >= 1 - margin) return null;
  if (left.length < 3 || right.length < 3) return null;
  if (Math.abs(ringArea(left)) < MIN_AREA || Math.abs(ringArea(right)) < MIN_AREA) return null;
  return [left, right];
}

/** Drop the vertices of a convex polygon that lie on the line of their neighbours. */
function dropCollinear(poly) {
  if (poly.length <= 3) return poly;
  const out = [];
  for (let i = 0; i < poly.length; i += 1) {
    const p = poly[(i + poly.length - 1) % poly.length];
    const c = poly[i];
    const q = poly[(i + 1) % poly.length];
    const ex = q[0] - p[0];
    const ez = q[1] - p[1];
    const l = Math.hypot(ex, ez);
    if (l > EPS && Math.abs((c[0] - p[0]) * ez - (c[1] - p[1]) * ex) / l < 1e-5) continue;
    out.push(c);
  }
  return out.length >= 3 ? out : poly;
}

const same = (a, b) => Math.abs(a[0] - b[0]) < 1e-7 && Math.abs(a[1] - b[1]) < 1e-7;

/** The union of two convex polygons of one orientation that share an edge, when it is convex; else null. */
function union(P, Q) {
  for (let a = 0; a < P.length; a += 1) {
    const u = P[a];
    const v = P[(a + 1) % P.length];
    for (let b = 0; b < Q.length; b += 1) {
      if (!same(Q[b], v) || !same(Q[(b + 1) % Q.length], u)) continue;
      const out = [];
      for (let k = 1; k <= P.length; k += 1) out.push(P[(a + k) % P.length]);
      for (let k = 2; k < Q.length; k += 1) out.push(Q[(b + k) % Q.length]);
      // Convex: every turn has the sign of the polygon (or none).
      const sign = Math.sign(ringArea(out));
      for (let i = 0; i < out.length; i += 1) {
        const p = out[(i + out.length - 1) % out.length];
        const c = out[i];
        const q = out[(i + 1) % out.length];
        const turn = (c[0] - p[0]) * (q[1] - c[1]) - (c[1] - p[1]) * (q[0] - c[0]);
        if (turn * sign < -1e-6) return null;
      }
      return dropCollinear(out);
    }
  }
  return null;
}

/** Merge neighbouring pieces of one class back into convex polygons (fewer triangles). */
function mergePieces(parts, classes) {
  for (let i = 0; i < parts.length; i += 1) parts[i] = dropCollinear(parts[i]);
  let merged = true;
  while (merged) {
    merged = false;
    for (let i = 0; i < parts.length && !merged; i += 1) {
      for (let j = i + 1; j < parts.length && !merged; j += 1) {
        if (classes[i] !== classes[j]) continue;
        const u = union(parts[i], parts[j]);
        if (u) {
          parts[i] = u;
          parts.splice(j, 1);
          classes.splice(j, 1);
          merged = true;
        }
      }
    }
  }
}

/** Twice the signed area of triangle a-b-c in (x, z). */
const area2 = (a, b, c) => (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);

/** Parameter of q on segment a-b when q lies on it, strictly between its ends; otherwise -1. */
function onSegment(q, a, b) {
  const dx = b[0] - a[0];
  const dz = b[1] - a[1];
  const l2 = dx * dx + dz * dz;
  if (l2 < EPS * EPS) return -1;
  const t = ((q[0] - a[0]) * dx + (q[1] - a[1]) * dz) / l2;
  if (t <= 1e-7 || t >= 1 - 1e-7) return -1;
  return Math.abs((q[0] - a[0]) * dz - (q[1] - a[1]) * dx) / Math.sqrt(l2) < 1e-5 ? t : -1;
}

/**
 * Triangles of a convex polygon that may carry vertices on its sides: a fan
 * from a vertex that gives no flat triangle, or else from the centroid (index
 * -1), so that every vertex is a corner of the triangles around it and the
 * mesh has no T-junctions (which crack in rasterisation).
 */
function fan(poly) {
  const k = poly.length;
  for (let a = 0; a < k; a += 1) {
    let ok = true;
    for (let i = 1; i < k - 1 && ok; i += 1) ok = Math.abs(area2(poly[a], poly[(a + i) % k], poly[(a + i + 1) % k])) > 1e-6;
    if (ok) {
      const out = [];
      for (let i = 1; i < k - 1; i += 1) out.push([a, (a + i) % k, (a + i + 1) % k]);
      return out;
    }
  }
  const out = [];
  for (let i = 0; i < k; i += 1) out.push([-1, i, (i + 1) % k]);
  return out;
}

/**
 * The stylised ground: the terrain triangles cut by the cover and coloured.
 * `colorOf(cls)` gives a THREE.Color per class; `shadeAt(x, z)` the hillshade
 * factor. Every vertex of a piece that lies on a side of another piece (in the
 * same triangle, or across an edge of the terrain grids) is put into that side,
 * so that the pieces meet without cracks. Returns { geometry, triangles, pieces }.
 */
export function coverGround(terrain, cover, colorOf, shadeAt) {
  const source = terrain.geometry;
  const pos = source.getAttribute('position').array;
  const index = source.getIndex().array;
  let stamp = 0;
  const seen = new Map();
  // 1. Cut every triangle, classify and merge its pieces.
  const tris = [];
  const rim = new Hash(16);          // piece vertices on the sides of their triangle
  for (let t = 0; t < index.length; t += 3) {
    const a = index[t] * 3;
    const b = index[t + 1] * 3;
    const c = index[t + 2] * 3;
    const P = [[pos[a], pos[a + 1], pos[a + 2]], [pos[b], pos[b + 1], pos[b + 2]], [pos[c], pos[c + 1], pos[c + 2]]];
    const flat = P.map((p) => [p[0], p[2]]);
    const x0 = Math.min(flat[0][0], flat[1][0], flat[2][0]);
    const x1 = Math.max(flat[0][0], flat[1][0], flat[2][0]);
    const z0 = Math.min(flat[0][1], flat[1][1], flat[2][1]);
    const z1 = Math.max(flat[0][1], flat[1][1], flat[2][1]);
    stamp += 1;
    const segs = [];
    cover.cutHash.each(x0, z0, x1, z1, (s) => {
      if (seen.get(s) === stamp) return;
      seen.set(s, stamp);
      if (Math.max(s[0], s[2]) < x0 || Math.min(s[0], s[2]) > x1 || Math.max(s[1], s[3]) < z0
        || Math.min(s[1], s[3]) > z1) return;
      segs.push(s);
    });
    let parts = [flat];
    for (const s of segs) {
      const next = [];
      for (const part of parts) {
        const halves = split(part, s);
        if (halves) next.push(halves[0], halves[1]);
        else next.push(part);
      }
      parts = next;
    }
    const classes = parts.map((part) => {
      let cx = 0;
      let cz = 0;
      for (const [x, z] of part) {
        cx += x;
        cz += z;
      }
      return cover.areaAt(cx / part.length, cz / part.length);
    });
    if (classes.every((cls) => cls === classes[0])) {
      parts = [flat];
      classes.length = 1;
    } else {
      mergePieces(parts, classes);
    }
    tris.push({ P, flat, parts, classes });
    if (parts.length > 1) {
      for (const part of parts) {
        for (const v of part) {
          if (onSegment(v, flat[0], flat[1]) >= 0 || onSegment(v, flat[1], flat[2]) >= 0
            || onSegment(v, flat[2], flat[0]) >= 0) rim.add(v, v[0], v[1], v[0], v[1]);
        }
      }
    }
  }
  // The finer inset meets the coarse grid with more vertices on the common sides: they go in as well.
  if (terrain.grids && terrain.grids[1]) {
    const box = terrain.grids[1].box;
    const onBorder = ([x, z]) => (Math.abs(x - box[0]) < 1e-6 || Math.abs(x - box[2]) < 1e-6
      || Math.abs(z - box[1]) < 1e-6 || Math.abs(z - box[3]) < 1e-6);
    for (const tri of tris) {
      for (const v of tri.flat) if (onBorder(v)) rim.add(v, v[0], v[1], v[0], v[1]);
    }
  }

  // 2. Put the vertices of the neighbours into the sides of each piece, and triangulate.
  const positions = [];
  const colors = [];
  const indices = [];
  const shadeCache = new Map();
  const shade = (x, z) => {
    const key = Math.round(x * 64) * 1e7 + Math.round(z * 64);
    let v = shadeCache.get(key);
    if (v === undefined) {
      v = shadeAt(x, z);
      shadeCache.set(key, v);
    }
    return v;
  };
  let pieces = 0;
  for (const { P, flat, parts, classes } of tris) {
    const ux = P[1][0] - P[0][0];
    const uy = P[1][1] - P[0][1];
    const uz = P[1][2] - P[0][2];
    const vx = P[2][0] - P[0][0];
    const vy = P[2][1] - P[0][1];
    const vz = P[2][2] - P[0][2];
    const nx = uy * vz - uz * vy;
    const ny = uz * vx - ux * vz;
    const nz = ux * vy - uy * vx;
    const planeY = (x, z) => P[0][1] - (nx * (x - P[0][0]) + nz * (z - P[0][2])) / ny;
    const sides = [[flat[0], flat[1]], [flat[1], flat[2]], [flat[2], flat[0]]];
    const onSide = (v, [a, b]) => onSegment(v, a, b) >= 0 || same(v, a) || same(v, b);
    for (let k = 0; k < parts.length; k += 1) {
      const part = parts[k];
      const ring = [];
      for (let i = 0; i < part.length; i += 1) {
        const p = part[i];
        const q = part[(i + 1) % part.length];
        ring.push(p);
        const extra = [];
        const take = (v) => {
          const t = onSegment(v, p, q);
          if (t >= 0 && !extra.some((e) => Math.abs(e[0] - t) < 1e-9)) extra.push([t, v]);
        };
        if (parts.length > 1) for (const other of parts) if (other !== part) for (const v of other) take(v);
        if (sides.some((side) => onSide(p, side) && onSide(q, side))) {
          rim.each(Math.min(p[0], q[0]), Math.min(p[1], q[1]), Math.max(p[0], q[0]), Math.max(p[1], q[1]), take);
        }
        extra.sort((e, f) => e[0] - f[0]);
        for (const [, v] of extra) ring.push(v);
      }
      const color = colorOf(classes[k]);
      const base = positions.length / 3;
      for (const [x, z] of ring) {
        const sh = shade(x, z);
        positions.push(x, planeY(x, z), z);
        colors.push(color.r * sh, color.g * sh, color.b * sh);
      }
      const faces = fan(ring);
      let centre = -1;
      if (faces[0][0] < 0) {
        let cx = 0;
        let cz = 0;
        for (const [x, z] of ring) {
          cx += x / ring.length;
          cz += z / ring.length;
        }
        const sh = shade(cx, cz);
        centre = positions.length / 3;
        positions.push(cx, planeY(cx, cz), cz);
        colors.push(color.r * sh, color.g * sh, color.b * sh);
      }
      // The winding of the source triangle (facing up) is kept.
      for (const [a, b, c] of faces) indices.push(a < 0 ? centre : base + a, base + b, base + c);
      pieces += 1;
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
  geometry.setIndex(positions.length / 3 > 65535 ? new THREE.Uint32BufferAttribute(indices, 1)
    : new THREE.Uint16BufferAttribute(indices, 1));
  geometry.computeBoundingSphere();
  return { geometry, triangles: indices.length / 3, pieces };
}

/** Parameters (0 … 1) at which segment a-b crosses an edge of the terrain triangles. */
function crossings(grids, ax, az, bx, bz) {
  const out = [];
  const dx = bx - ax;
  const dz = bz - az;
  for (const { origin, spacing, box } of grids) {
    const inBox = (t) => {
      const x = ax + dx * t;
      const z = az + dz * t;
      return x >= box[0] - EPS && x <= box[2] + EPS && z >= box[1] - EPS && z <= box[3] + EPS;
    };
    // Lines x = const, z = const and the cell diagonals x + z = const.
    const families = [[ax - origin[0], dx], [az - origin[1], dz], [ax - origin[0] + az - origin[1], dx + dz]];
    for (const [start, delta] of families) {
      if (Math.abs(delta) < EPS) continue;
      const k0 = Math.ceil(Math.min(start, start + delta) / spacing);
      const k1 = Math.floor(Math.max(start, start + delta) / spacing);
      for (let k = k0; k <= k1; k += 1) {
        const t = (k * spacing - start) / delta;
        if (t > EPS && t < 1 - EPS && inBox(t)) out.push(t);
      }
    }
  }
  return out.sort((a, b) => a - b);
}

/**
 * Which split points of a ribbon to keep: its bends always, the others where
 * the ground under its middle or either edge departs from the straight line
 * between the kept neighbours by more than RIBBON_TOL (Douglas-Peucker on the
 * height profiles), so that a ribbon on even ground stays a few long quads.
 */
function thinRibbon(pts, corner, half, height) {
  const keep = corner.slice();
  const profile = (p, n) => [height(p[0] - n[0], p[1] - n[1]), height(p[0], p[1]), height(p[0] + n[0], p[1] + n[1])];
  let from = 0;
  for (let to = 1; to < pts.length; to += 1) {
    if (!corner[to]) continue;
    const stack = [[from, to]];
    while (stack.length) {
      const [i, j] = stack.pop();
      if (j - i < 2) continue;
      const [a, b] = [pts[i], pts[j]];
      const l = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1;
      const n = [(-(b[1] - a[1]) / l) * half, ((b[0] - a[0]) / l) * half];
      const ha = profile(a, n);
      const hb = profile(b, n);
      let worst = RIBBON_TOL;
      let at = -1;
      for (let k = i + 1; k < j; k += 1) {
        const t = Math.hypot(pts[k][0] - a[0], pts[k][1] - a[1]) / l;
        const hk = profile(pts[k], n);
        for (let e = 0; e < 3; e += 1) {
          const d = Math.abs(hk[e] - (ha[e] + (hb[e] - ha[e]) * t));
          if (d > worst) {
            worst = d;
            at = k;
          }
        }
      }
      if (at >= 0) {
        keep[at] = true;
        stack.push([i, at], [at, j]);
      }
    }
    from = to;
  }
  return keep;
}

/**
 * Ribbons of the roads and waterways laid on the drawn ground: each polyline
 * is split where it crosses an edge of the terrain triangles (and every metre
 * of `fine(x, z)` where that asks for it; thinRibbon drops the splits that even
 * ground does not need), mitred at its bends, lifted by its class and coloured
 * like the ground under it. `lift(x, z)` adds the rise of a
 * mound; `skip(x, z)` leaves a piece out (the carved pit). Returns { geometry, triangles }.
 */
function ribbonGeometry(lines, terrain, colorOf, shadeAt, { lift = () => 0, skip = () => false, fine = () => 0 } = {}) {
  const positions = [];
  const colors = [];
  const indices = [];
  for (const { cls, half, lift: up, points } of lines) {
    // Densify.
    const pts = [];
    const corner = [];
    for (let i = 0; i + 1 < points.length; i += 1) {
      const [ax, az] = points[i];
      const [bx, bz] = points[i + 1];
      pts.push([ax, az]);
      corner.push(true);
      const ts = crossings(terrain.grids, ax, az, bx, bz);
      const step = fine((ax + bx) / 2, (az + bz) / 2);
      if (step > 0) {
        const n = Math.ceil(Math.hypot(bx - ax, bz - az) / step);
        for (let k = 1; k < n; k += 1) ts.push(k / n);
        ts.sort((a, b) => a - b);
      }
      for (const t of ts) {
        pts.push([ax + (bx - ax) * t, az + (bz - az) * t]);
        corner.push(false);
      }
    }
    pts.push(points[points.length - 1]);
    corner.push(true);
    const keep = thinRibbon(pts, corner, half, (x, z) => terrain.heightAt(x, z) + lift(x, z));
    for (let i = pts.length - 1; i >= 0; i -= 1) {
      if (!keep[i]) {
        pts.splice(i, 1);
        corner.splice(i, 1);
      }
    }
    const color = colorOf(cls);
    let prev = -1;   // index of the last pair of vertices written, -1 after a gap
    for (let i = 0; i < pts.length; i += 1) {
      const p = pts[i];
      const a = pts[Math.max(0, i - 1)];
      const b = pts[Math.min(pts.length - 1, i + 1)];
      // Unit normals of the segments before and after the point; the mitre between them.
      const n0 = i > 0 ? [-(p[1] - a[1]), p[0] - a[0]] : null;
      const n1 = i + 1 < pts.length ? [-(b[1] - p[1]), b[0] - p[0]] : null;
      const unit = (v) => {
        const l = Math.hypot(v[0], v[1]) || 1;
        return [v[0] / l, v[1] / l];
      };
      const u0 = n0 ? unit(n0) : unit(n1);
      const u1 = n1 ? unit(n1) : u0;
      let m = unit([u0[0] + u1[0], u0[1] + u1[1]]);
      const scale = corner[i] ? 1 / Math.max(0.5, m[0] * u0[0] + m[1] * u0[1]) : 1;
      if (!corner[i]) m = u0;
      const left = [p[0] + m[0] * half * scale, p[1] + m[1] * half * scale];
      const right = [p[0] - m[0] * half * scale, p[1] - m[1] * half * scale];
      const gap = i > 0 && skip((p[0] + a[0]) / 2, (p[1] + a[1]) / 2);
      const base = positions.length / 3;
      for (const q of [left, right]) {
        const s = shadeAt(q[0], q[1]);
        positions.push(q[0], terrain.heightAt(q[0], q[1]) + up + lift(q[0], q[1]), q[1]);
        colors.push(color.r * s, color.g * s, color.b * s);
      }
      // Left is +normal = (-dz, dx): for a ribbon heading east (+x) that is +z, south. Faces up:
      if (prev >= 0 && !gap) indices.push(prev, base, prev + 1, prev + 1, base, base + 1);
      prev = base;
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
  geometry.setIndex(positions.length / 3 > 65535 ? new THREE.Uint32BufferAttribute(indices, 1)
    : new THREE.Uint16BufferAttribute(indices, 1));
  geometry.computeBoundingSphere();
  return { geometry, triangles: indices.length / 3 };
}

// --------------------------------------------------------------- the models

/**
 * Non-indexed geometry of flat faces for an instanced model: positions, face
 * normals (the vertex shader shades them), colours and `paint` (how much of
 * the instance colour a vertex takes).
 */
function facetGeometry(faces) {
  const pos = [];
  const nor = [];
  const col = [];
  const paint = [];
  for (const { points, color, paint: p } of faces) {
    const [a, b, c] = points;
    const ux = b[0] - a[0];
    const uy = b[1] - a[1];
    const uz = b[2] - a[2];
    const vx = c[0] - a[0];
    const vy = c[1] - a[1];
    const vz = c[2] - a[2];
    let n = [uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx];
    const l = Math.hypot(n[0], n[1], n[2]) || 1;
    n = [n[0] / l, n[1] / l, n[2] / l];
    for (let i = 1; i < points.length - 1; i += 1) {
      for (const q of [points[0], points[i], points[i + 1]]) {
        pos.push(q[0], q[1], q[2]);
        nor.push(n[0], n[1], n[2]);
        col.push(color.r, color.g, color.b);
        paint.push(p);
      }
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  geometry.setAttribute('normal', new THREE.Float32BufferAttribute(nor, 3));
  geometry.setAttribute('color', new THREE.Float32BufferAttribute(col, 3));
  geometry.setAttribute('paint', new THREE.Float32BufferAttribute(paint, 1));
  geometry.computeBoundingSphere();
  return geometry;
}

/** Faces of an outward-facing box from y0 to y1 over the unit square (x, z in -0.5 … 0.5), without its bottom. */
function boxFaces(y0, y1, wall, roof, top = true) {
  const c = [[-0.5, -0.5], [0.5, -0.5], [0.5, 0.5], [-0.5, 0.5]];
  const faces = [];
  for (let i = 0; i < 4; i += 1) {
    const [p, q] = [c[i], c[(i + 1) % 4]];
    // Counter-clockwise seen from outside.
    faces.push({ points: [[p[0], y0, p[1]], [p[0], y1, p[1]], [q[0], y1, q[1]], [q[0], y0, q[1]]], color: wall, paint: 0 });
  }
  if (top) faces.push({ points: [[-0.5, y1, -0.5], [-0.5, y1, 0.5], [0.5, y1, 0.5], [0.5, y1, -0.5]], color: roof, paint: 1 });
  return faces;
}

/** A house: walls from 0 to 1, a gable roof along x rising ROOF_RISE above them, eaves a little out. */
function houseGeometry(wall, roof) {
  const faces = boxFaces(0, 1, wall, roof, false);
  const top = 1 + ROOF_RISE;
  const e = 0.56;   // eaves 6 % out on the long sides
  const g = 0.52;   // and 2 % at the gables
  faces.push(
    { points: [[-g, 0.97, -e], [-g, top, 0], [g, top, 0], [g, 0.97, -e]], color: roof, paint: 1 },
    { points: [[g, 0.97, e], [g, top, 0], [-g, top, 0], [-g, 0.97, e]], color: roof, paint: 1 },
    { points: [[0.5, 1, -0.5], [0.5, top - 0.02, 0], [0.5, 1, 0.5]], color: wall, paint: 0 },
    { points: [[-0.5, 1, 0.5], [-0.5, top - 0.02, 0], [-0.5, 1, -0.5]], color: wall, paint: 0 },
  );
  return facetGeometry(faces);
}

/** A broadleaf tree of height 1: a trunk (a thin pyramid) and a faceted crown of radius 1 (scaled per instance). */
function treeGeometry(trunk, crown) {
  const faces = [];
  const ring = (n, r, y, turn = 0) => Array.from({ length: n }, (_, i) => {
    const a = ((i + turn) / n) * Math.PI * 2;
    return [Math.cos(a) * r, y, Math.sin(a) * r];
  });
  const foot = ring(3, 0.09, 0);
  const tip = [0, 0.5, 0];
  for (let i = 0; i < 3; i += 1) faces.push({ points: [foot[i], tip, foot[(i + 1) % 3]], color: trunk, paint: 0 });
  const mid = ring(5, 1, 0.56);
  const top = [0, 1, 0];
  const bottom = [0, 0.24, 0];
  for (let i = 0; i < 5; i += 1) {
    const j = (i + 1) % 5;
    faces.push({ points: [mid[i], top, mid[j]], color: crown, paint: 1 });
    faces.push({ points: [mid[j], bottom, mid[i]], color: crown, paint: 1 });
  }
  return facetGeometry(faces);
}

function convexHull(points) {
  const pts = points.slice().sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  if (pts.length < 3) return pts;
  const cross = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const lower = [];
  for (const p of pts) {
    while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], p) <= 0) lower.pop();
    lower.push(p);
  }
  const upper = [];
  for (let i = pts.length - 1; i >= 0; i -= 1) {
    const p = pts[i];
    while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], p) <= 0) upper.pop();
    upper.push(p);
  }
  return lower.slice(0, -1).concat(upper.slice(0, -1));
}

/** Smallest box around a footprint: { cx, cz, length, width, ux, uz } with length along (ux, uz). */
function fittedBox(ring) {
  const hull = convexHull(ring);
  let best = null;
  for (let i = 0; i < hull.length; i += 1) {
    const [ax, az] = hull[i];
    const [bx, bz] = hull[(i + 1) % hull.length];
    const l = Math.hypot(bx - ax, bz - az);
    if (l < EPS) continue;
    const ux = (bx - ax) / l;
    const uz = (bz - az) / l;
    let u0 = Infinity;
    let u1 = -Infinity;
    let v0 = Infinity;
    let v1 = -Infinity;
    for (const [x, z] of hull) {
      const u = x * ux + z * uz;
      const v = -x * uz + z * ux;
      u0 = Math.min(u0, u);
      u1 = Math.max(u1, u);
      v0 = Math.min(v0, v);
      v1 = Math.max(v1, v);
    }
    const area = (u1 - u0) * (v1 - v0);
    if (!best || area < best.area) {
      const um = (u0 + u1) / 2;
      const vm = (v0 + v1) / 2;
      best = { area, cx: um * ux - vm * uz, cz: um * uz + vm * ux, a: u1 - u0, b: v1 - v0, ux, uz };
    }
  }
  if (!best) return null;
  // Length along the longer side.
  return best.a >= best.b
    ? { cx: best.cx, cz: best.cz, length: best.a, width: best.b, ux: best.ux, uz: best.uz, area: best.area }
    : { cx: best.cx, cz: best.cz, length: best.b, width: best.a, ux: -best.uz, uz: best.ux, area: best.area };
}

/** Offset a counter-clockwise ring inwards by `d` (mitred, the mitre capped at 2 d). */
function insetRing(ring, d) {
  const n = ring.length;
  const out = [];
  for (let i = 0; i < n; i += 1) {
    const p = ring[(i + n - 1) % n];
    const c = ring[i];
    const q = ring[(i + 1) % n];
    const e1 = [c[0] - p[0], c[1] - p[1]];
    const e2 = [q[0] - c[0], q[1] - c[1]];
    const l1 = Math.hypot(e1[0], e1[1]) || 1;
    const l2 = Math.hypot(e2[0], e2[1]) || 1;
    // Positive area in (x, z): the inside is to the left of each edge, i.e. along (-dz, dx).
    const n1 = [-e1[1] / l1, e1[0] / l1];
    const n2 = [-e2[1] / l2, e2[0] / l2];
    let m = [n1[0] + n2[0], n1[1] + n2[1]];
    const ml = Math.hypot(m[0], m[1]) || 1;
    m = [m[0] / ml, m[1] / ml];
    const cos = Math.max(0.5, m[0] * n1[0] + m[1] * n1[1]);
    out.push([c[0] + (m[0] * d) / cos, c[1] + (m[1] * d) / cos]);
  }
  return out;
}

/** Clip a polygon (any shape) to a convex one (Sutherland-Hodgman); both [[x, z], ...], the clip counter-clockwise. */
function clipToConvex(subject, clip) {
  let out = subject;
  for (let i = 0; i < clip.length && out.length; i += 1) {
    const a = clip[i];
    const b = clip[(i + 1) % clip.length];
    const side = (p) => (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]);
    const src = out;
    out = [];
    for (let k = 0; k < src.length; k += 1) {
      const cur = src[k];
      const prev = src[(k + src.length - 1) % src.length];
      const sc = side(cur);
      const sp = side(prev);
      if (sc >= 0) {
        if (sp < 0) out.push([prev[0] + ((cur[0] - prev[0]) * sp) / (sp - sc), prev[1] + ((cur[1] - prev[1]) * sp) / (sp - sc)]);
        out.push(cur);
      } else if (sp >= 0) {
        out.push([prev[0] + ((cur[0] - prev[0]) * sp) / (sp - sc), prev[1] + ((cur[1] - prev[1]) * sp) / (sp - sc)]);
      }
    }
  }
  return out;
}

/**
 * A waste heap: its outline on the ground, sides at the angle of repose up to
 * a top `rise` metres above the drawn ground, which follows the terrain
 * triangles (so the mound keeps the relief of the DEM under it).
 */
function heapMound(solid, ring, rise, terrain, sideColor, topColor) {
  const run = rise / HEAP_SLOPE;
  const inner = insetRing(ring, run);
  if (Math.abs(ringArea(inner)) < 50 || Math.sign(ringArea(inner)) !== Math.sign(ringArea(ring))) return 0;
  const before = solid.idx.length;
  // Sides: outline samples every 8 m, each with its point on the inner ring.
  solid.use(null, sideColor);
  const n = ring.length;
  for (let i = 0; i < n; i += 1) {
    const [a, b] = [ring[i], ring[(i + 1) % n]];
    const [ia, ib] = [inner[i], inner[(i + 1) % n]];
    const k = Math.max(1, Math.ceil(Math.hypot(b[0] - a[0], b[1] - a[1]) / 8));
    for (let s = 0; s < k; s += 1) {
      const f0 = s / k;
      const f1 = (s + 1) / k;
      const o0 = [a[0] + (b[0] - a[0]) * f0, a[1] + (b[1] - a[1]) * f0];
      const o1 = [a[0] + (b[0] - a[0]) * f1, a[1] + (b[1] - a[1]) * f1];
      const i0 = [ia[0] + (ib[0] - ia[0]) * f0, ia[1] + (ib[1] - ia[1]) * f0];
      const i1 = [ia[0] + (ib[0] - ia[0]) * f1, ia[1] + (ib[1] - ia[1]) * f1];
      const y = (p, up) => terrain.heightAt(p[0], p[1]) + up;
      const inside = [(i0[0] + i1[0]) / 2, y(i0, rise) - rise * 2, (i0[1] + i1[1]) / 2];
      solid.quad([o0[0], y(o0, -0.3), o0[1]], [o1[0], y(o1, -0.3), o1[1]], [i1[0], y(i1, rise), i1[1]],
        [i0[0], y(i0, rise), i0[1]], inside);
    }
  }
  // Top: the inner ring cut by the terrain triangles, lifted by `rise`.
  solid.use(null, topColor);
  const box = boxOf(inner);
  const source = terrain.geometry;
  const pos = source.getAttribute('position').array;
  const index = source.getIndex().array;
  for (let t = 0; t < index.length; t += 3) {
    const v = [index[t] * 3, index[t + 1] * 3, index[t + 2] * 3];
    const xs = v.map((k) => pos[k]);
    const zs = v.map((k) => pos[k + 2]);
    if (Math.max(...xs) < box[0] || Math.min(...xs) > box[2] || Math.max(...zs) < box[1] || Math.min(...zs) > box[3]) continue;
    let tri = v.map((k) => [pos[k], pos[k + 2]]);
    if (ringArea(tri) < 0) tri = tri.reverse();
    const piece = clipToConvex(inner, tri);
    if (piece.length < 3 || Math.abs(ringArea(piece)) < MIN_AREA) continue;
    const faces = THREE.ShapeUtils.triangulateShape(piece.map(([x, z]) => new THREE.Vector2(x, z)), []);
    const at = ([x, z]) => [x, terrain.heightAt(x, z) + rise, z];
    for (const [a, b, c] of faces) {
      const pa = at(piece[a]);
      solid.tri(pa, at(piece[b]), at(piece[c]), [pa[0], pa[1] - 10, pa[2]]);
    }
  }
  return (solid.idx.length - before) / 3;
}

/**
 * Build the landscape from the data, the terrain and the materials of
 * terrain.js. `colors` gives the THREE.Color of a land-cover class
 * (`colors.cover(cls)`) and of a model part (`colors.model(name)`);
 * `keepOut` lists [x, z, r] circles of the twin's own surface models, where no
 * OSM building or tree is drawn. Returns { ground, group, counts, dispose() }:
 * `ground` the geometry for the ground mesh, `group` the models.
 */
export function buildLandscape(data, terrain, colors, materials, keepOut = []) {
  const started = performance.now();
  const cover = createCover(data);
  const shade = groundShade(terrain);
  const ground = coverGround(terrain, cover, (cls) => colors.cover(cls), shade);
  // Roads and waterways: not in the carved pit; over a heap they climb its mound.
  const pit = cover.areas.find((a) => a.cls === 'pit');
  const heaps = (data.heaps || []).map((h) => {
    const ring = pairs(h.ring || []);
    return { ring, box: boxOf(ring), rise: Number(h.rise) || 4 };
  }).filter((h) => h.ring.length >= 3);
  const inBox = (x, z, box, m = 0) => x >= box[0] - m && x <= box[2] + m && z >= box[1] - m && z <= box[3] + m;
  const ribbons = ribbonGeometry(cover.lines, terrain, (cls) => colors.cover(cls === 'river' ? 'water' : cls), shade, {
    skip: (x, z) => Boolean(pit) && inBox(x, z, pit.box) && inRing(x, z, pit.ring),
    lift: (x, z) => {
      for (const h of heaps) {
        if (inBox(x, z, h.box) && inRing(x, z, h.ring)) return Math.min(h.rise, ringDistance(x, z, h.ring) * HEAP_SLOPE);
      }
      return 0;
    },
    fine: (x, z) => (heaps.some((h) => inBox(x, z, h.box, 40)) ? 3 : 0),
  });
  const blocked = (x, z, margin = 0) => keepOut.some(([kx, kz, r]) => Math.hypot(x - kx, z - kz) < r + margin);

  const group = new THREE.Group();
  if (ribbons.triangles) {
    const mesh = new THREE.Mesh(ribbons.geometry, materials.models);
    mesh.renderOrder = 2;
    mesh.matrixAutoUpdate = false;
    group.add(mesh);
  }
  const solid = new MeshBuilder();
  const counts = { houses: 0, blocks: 0, footprints: 0, trees: 0, heaps: 0, barrier_m: 0 };

  // ---- buildings
  const houses = [];
  const blocks = [];
  for (const item of data.buildings || []) {
    const ring = pairs(item.ring || []);
    if (ring.length < 3) continue;
    const fit = fittedBox(ring);
    if (!fit || fit.width < 1.5) continue;
    if (blocked(fit.cx, fit.cz, fit.length / 2)) continue;
    const area = Math.abs(ringArea(ring));
    const levels = Number.isFinite(item.levels) && item.levels > 0 ? item.levels : null;
    const industrial = item.building === 'industrial';
    const big = area > BIG_FOOTPRINT || industrial;
    const walls = levels ? levels * STOREY : industrial ? INDUSTRIAL_WALLS : big ? BIG_WALLS : WALLS_DEFAULT;
    let low = Infinity;
    let high = -Infinity;
    const corners = [[-0.5, -0.5], [0.5, -0.5], [0.5, 0.5], [-0.5, 0.5], [0, 0]];
    for (const [a, b] of corners) {
      const x = fit.cx + fit.ux * a * fit.length - fit.uz * b * fit.width;
      const z = fit.cz + fit.uz * a * fit.length + fit.ux * b * fit.width;
      const h = terrain.heightAt(x, z);
      low = Math.min(low, h);
      high = Math.max(high, h);
    }
    const base = low - BURY;
    if (area / fit.area >= BOXY || ring.length <= 5) {
      (big ? blocks : houses).push({ fit, base, height: high - base + walls, seed: item.osm || houses.length });
    } else {
      // Other shapes: the footprint extruded, with a flat roof.
      const top = high + walls;
      solid.use(null, colors.model(industrial ? 'wallIndustrial' : 'wall'));
      const sign = ringArea(ring) >= 0 ? 1 : -1;
      for (let i = 0; i < ring.length; i += 1) {
        const p = ring[i];
        const q = ring[(i + 1) % ring.length];
        const [dx, dz] = [q[0] - p[0], q[1] - p[1]];
        const l = Math.hypot(dx, dz) || 1;
        const inside = [(p[0] + q[0]) / 2 - (sign * dz) / l, (base + top) / 2, (p[1] + q[1]) / 2 + (sign * dx) / l];
        solid.quad([p[0], base, p[1]], [q[0], base, q[1]], [q[0], top, q[1]], [p[0], top, p[1]], inside);
      }
      solid.use(null, colors.model(industrial ? 'roofIndustrial' : 'roofFlat')).polygon(ring, top);
      counts.footprints += 1;
    }
  }
  const tint = new THREE.Color();
  const matrix = new THREE.Matrix4();
  const quaternion = new THREE.Quaternion();
  const position = new THREE.Vector3();
  const scale = new THREE.Vector3();
  const roofs = colors.roofs();
  const instancedOf = (geometry, list, place) => {
    const mesh = new THREE.InstancedMesh(geometry, materials.instances, Math.max(1, list.length));
    list.forEach((item, i) => {
      place(item, i);
      matrix.compose(position, quaternion, scale);
      mesh.setMatrixAt(i, matrix);
      mesh.setColorAt(i, tint);
    });
    mesh.count = list.length;
    mesh.computeBoundingSphere();
    mesh.renderOrder = 2;
    mesh.matrixAutoUpdate = false;
    return mesh;
  };
  const placeBuilding = (roofOf) => (b, i) => {
    const { fit } = b;
    position.set(fit.cx, b.base, fit.cz);
    quaternion.setFromAxisAngle(Y_AXIS, Math.atan2(-fit.uz, fit.ux));
    scale.set(fit.length, b.height, fit.width);
    tint.copy(roofOf(b, i));
  };
  const hash = (n) => {
    const r = random(Math.abs(Math.round(n)) % 2147483647);
    r();
    return r();
  };
  if (houses.length) {
    group.add(instancedOf(houseGeometry(colors.model('wall'), WHITE), houses,
      placeBuilding((b) => roofs[Math.floor(hash(b.seed) * roofs.length)])));
  }
  if (blocks.length) {
    const industrialRoof = colors.model('roofIndustrial');
    group.add(instancedOf(facetGeometry(boxFaces(0, 1, colors.model('wallIndustrial'), WHITE)), blocks,
      placeBuilding(() => industrialRoof)));
  }
  counts.houses = houses.length;
  counts.blocks = blocks.length;

  // ---- trees
  const rand = random(TREE_SEED);
  const trees = [];
  const treeOk = (x, z, cls) => {
    const at = cover.classAt(x, z);
    return (cls ? at === cls : at === 'meadow' || at === 'residential' || at === 'wood' || at === 'industrial')
      && !blocked(x, z, 4);
  };
  const addTree = (x, z) => {
    const h = TREE_HEIGHT[0] + (TREE_HEIGHT[1] - TREE_HEIGHT[0]) * rand();
    trees.push({ x, z, h, r: h * TREE_CROWN * (0.85 + 0.3 * rand()), turn: rand() * Math.PI * 2, tone: rand() });
  };
  const woods = cover.areas.filter((a) => a.cls === 'wood' || a.cls === 'scrub');
  const woodArea = woods.reduce((s, a) => s + Math.abs(ringArea(a.ring)), 0);
  const woodStep = Math.max(WOOD_SPACING, Math.sqrt(woodArea / TREE_CAP.wood));
  for (const a of woods) {
    for (let x = Math.ceil(a.box[0] / woodStep) * woodStep; x <= a.box[2]; x += woodStep) {
      for (let z = Math.ceil(a.box[1] / woodStep) * woodStep; z <= a.box[3]; z += woodStep) {
        const px = x + (rand() - 0.5) * woodStep * 0.8;
        const pz = z + (rand() - 0.5) * woodStep * 0.8;
        if (inRing(px, pz, a.ring) && treeOk(px, pz, a.cls)) addTree(px, pz);
      }
    }
  }
  const parks = cover.areas.filter((a) => a.cls === 'park' || a.cls === 'cemetery');
  let parkTrees = 0;
  for (const a of parks) {
    const step = woodStep * 1.6;
    for (let x = Math.ceil(a.box[0] / step) * step; x <= a.box[2]; x += step) {
      for (let z = Math.ceil(a.box[1] / step) * step; z <= a.box[3]; z += step) {
        const px = x + (rand() - 0.5) * step * 0.8;
        const pz = z + (rand() - 0.5) * step * 0.8;
        if (parkTrees < TREE_CAP.park && inRing(px, pz, a.ring) && treeOk(px, pz, a.cls)) {
          addTree(px, pz);
          parkTrees += 1;
        }
      }
    }
  }
  // Along the waterways: trees on both banks, a few metres off the water, spread evenly over all of them.
  const banks = cover.strips.filter((s) => s.cls === 'river');
  const bankLength = banks.reduce((t, s) => t + s.length, 0);
  const bankStep = Math.max(RIVER_SPACING, (bankLength * 2 * 0.65) / TREE_CAP.river);
  let riverTrees = 0;
  for (const s of banks) {
    for (let d = rand() * bankStep; d < s.length && riverTrees < TREE_CAP.river; d += bankStep) {
      for (const side of [1, -1]) {
        if (rand() < 0.35) continue;
        const off = s.half + 3 + rand() * 6;
        const x = s.ax + s.ux * d - s.uz * off * side;
        const z = s.az + s.uz * d + s.ux * off * side;
        if (treeOk(x, z, null)) {
          addTree(x, z);
          riverTrees += 1;
        }
      }
    }
  }
  if (trees.length) {
    const greens = colors.greens();
    group.add(instancedOf(treeGeometry(colors.model('trunk'), WHITE), trees, (t) => {
      position.set(t.x, terrain.heightAt(t.x, t.z) - 0.3, t.z);
      quaternion.setFromAxisAngle(Y_AXIS, t.turn);
      scale.set(t.r, t.h, t.r);
      tint.copy(greens[Math.floor(t.tone * greens.length)]);
    }));
  }
  counts.trees = trees.length;
  Object.assign(counts, {
    trees_wood: trees.length - parkTrees - riverTrees, trees_river: riverTrees, trees_park: parkTrees,
  });

  // ---- heaps, walls and fences (merged, shade baked)
  for (const item of data.heaps || []) {
    const ring = pairs(item.ring || []);
    if (ring.length < 3) continue;
    const ccw = ringArea(ring) >= 0 ? ring : ring.slice().reverse();
    if (heapMound(solid, ccw, Number(item.rise) || 4, terrain, colors.model('heapSide'), colors.model('heapTop'))) {
      counts.heaps += 1;
    }
  }
  for (const item of data.barriers || []) {
    const [thick, height] = BARRIER[item.barrier] || BARRIER.fence;
    solid.use(null, colors.model(item.barrier === 'wall' ? 'wallBarrier' : 'fence'));
    const pts = pairs(item.line || []);
    for (let i = 0; i + 1 < pts.length; i += 1) {
      const [a, b] = [pts[i], pts[i + 1]];
      const length = Math.hypot(b[0] - a[0], b[1] - a[1]);
      counts.barrier_m += length;
      const k = Math.max(1, Math.ceil(length / BARRIER_STEP));
      for (let s = 0; s < k; s += 1) {
        const p = [a[0] + ((b[0] - a[0]) * s) / k, a[1] + ((b[1] - a[1]) * s) / k];
        const q = [a[0] + ((b[0] - a[0]) * (s + 1)) / k, a[1] + ((b[1] - a[1]) * (s + 1)) / k];
        const yp = terrain.heightAt(p[0], p[1]);
        const yq = terrain.heightAt(q[0], q[1]);
        // Two faces and the top (6 triangles a piece): nobody looks at a wall from under the ground.
        const [ox, oz] = [(-(q[1] - p[1]) / length) * k * (thick / 2), ((q[0] - p[0]) / length) * k * (thick / 2)];
        const low = [yp - 0.3, yq - 0.3];
        const high = [yp + height, yq + height];
        const mid = [(p[0] + q[0]) / 2, (yp + yq) / 2 + height / 2, (p[1] + q[1]) / 2];
        for (const side of [1, -1]) {
          solid.quad([p[0] + ox * side, low[0], p[1] + oz * side], [q[0] + ox * side, low[1], q[1] + oz * side],
            [q[0] + ox * side, high[1], q[1] + oz * side], [p[0] + ox * side, high[0], p[1] + oz * side], mid);
        }
        solid.quad([p[0] + ox, high[0], p[1] + oz], [q[0] + ox, high[1], q[1] + oz], [q[0] - ox, high[1], q[1] - oz],
          [p[0] - ox, high[0], p[1] - oz], [mid[0], mid[1] - height, mid[2]]);
      }
    }
  }
  counts.barrier_m = Math.round(counts.barrier_m);
  const merged = solid.build();
  if (merged.triangles) {
    const mesh = new THREE.Mesh(merged.geometry, materials.models);
    mesh.renderOrder = 2;
    mesh.matrixAutoUpdate = false;
    group.add(mesh);
  }

  let modelTriangles = merged.triangles + ribbons.triangles;
  for (const mesh of group.children) {
    if (mesh.isInstancedMesh) modelTriangles += (mesh.geometry.getAttribute('position').count / 3) * mesh.count;
  }
  Object.assign(counts, {
    ground_triangles: ground.triangles, ground_pieces: ground.pieces, cuts: cover.cuts,
    ribbon_triangles: ribbons.triangles,
    model_triangles: modelTriangles, build_ms: Math.round(performance.now() - started),
  });
  return {
    ground: ground.geometry,
    group,
    counts,
    cover,
    dispose() {
      ground.geometry.dispose();
      for (const mesh of group.children) mesh.geometry.dispose();
    },
  };
}
