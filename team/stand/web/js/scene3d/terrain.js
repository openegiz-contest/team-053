// The real ground of the scene (spec 4.2, geometry.json `terrain`): one mesh of
// the 65 x 65 heightmap with the finer pit inset in place of its coarse cells,
// draped with the Sentinel-2 image, and a height sampler that follows exactly
// the drawn triangles (so that outlines and markers sit on the ground).
//
// Every cell is split along its south-west to north-east diagonal, the vertex
// order of three.js PlaneGeometry rotated to lie flat. The inset border
// elevations match the coarse edges, so the two grids meet without cracks.
//
// The underground stays the subject: an "x-ray" box around the workings makes
// the ground translucent wherever the line of sight continues into the box, from
// any camera; the rest of the ground is opaque (see terrainMaterial).

import * as THREE from 'three';

export const TEXTURE_URL = '/terrain/texture.jpg';

// Hillshade baked into the vertex colours: light from the north-west, high.
const SUN = new THREE.Vector3(-0.45, 0.78, -0.43).normalize();
const SHADE_GAIN = 2.2;            // contrast of the relief
const SHADE_RANGE = [0.62, 1.12];  // darkest and brightest factor on the image
const IMAGE_GAIN = 1.08;           // the image is a little dark on the dark page

/** A regular grid: elevation of the drawn triangles at (x, z), or null outside it. */
function gridSampler(origin, spacing, rows) {
  const ny = rows.length - 1;
  const nx = rows[0].length - 1;
  return (x, z) => {
    const fx = (x - origin[0]) / spacing;
    const fz = (z - origin[1]) / spacing;
    if (fx < -1e-9 || fz < -1e-9 || fx > nx + 1e-9 || fz > ny + 1e-9) return null;
    const i = Math.min(nx - 1, Math.max(0, Math.floor(fx)));
    const j = Math.min(ny - 1, Math.max(0, Math.floor(fz)));
    const u = fx - i;
    const v = fz - j;
    const a = rows[j][i];             // north-west
    const b = rows[j + 1][i];         // south-west
    const c = rows[j + 1][i + 1];     // south-east
    const d = rows[j][i + 1];         // north-east
    if (u + v <= 1) return a + (d - a) * u + (b - a) * v;
    return c + (b - c) * (1 - u) + (d - c) * (1 - v);
  };
}

/**
 * Build the terrain from the `terrain` block. Returns { geometry, triangles,
 * extent, heightAt(x, z), drape(points, lift, step) }; `null` when the block
 * is missing.
 */
export function createTerrain(block) {
  if (!block || !Array.isArray(block.rows) || !block.rows.length) return null;
  const { origin, spacing, rows } = block;
  const nx = rows[0].length - 1;
  const nz = rows.length - 1;
  const extent = block.extent || [origin[0], origin[1], origin[0] + nx * spacing, origin[1] + nz * spacing];
  const coarse = gridSampler(origin, spacing, rows);
  const inset = block.inset && Array.isArray(block.inset.rows) ? block.inset : null;
  const fine = inset ? gridSampler(inset.origin, inset.spacing, inset.rows) : null;
  const insetBox = inset ? [inset.origin[0], inset.origin[1],
    inset.origin[0] + (inset.rows[0].length - 1) * inset.spacing,
    inset.origin[1] + (inset.rows.length - 1) * inset.spacing] : null;

  function heightAt(x, z) {
    if (fine && x >= insetBox[0] && x <= insetBox[2] && z >= insetBox[1] && z <= insetBox[3]) {
      const h = fine(x, z);
      if (h !== null) return h;
    }
    const cx = Math.max(extent[0], Math.min(extent[2], x));
    const cz = Math.max(extent[1], Math.min(extent[3], z));
    return coarse(cx, cz);
  }

  // ------------------------------------------------------------ the mesh
  const positions = [];
  const uvs = [];
  const indices = [];
  const [ex0, ez0, ex1, ez1] = block.texture && block.texture.extent ? block.texture.extent : extent;
  const vertex = (x, y, z) => {
    positions.push(x, y, z);
    // u east, v north: the north edge is the top of the (flipped) image.
    uvs.push((x - ex0) / (ex1 - ex0), 1 - (z - ez0) / (ez1 - ez0));
    return positions.length / 3 - 1;
  };
  const grid = (o, step, r, skip) => {
    const w = r[0].length;
    const base = positions.length / 3;
    for (let j = 0; j < r.length; j += 1) {
      for (let i = 0; i < w; i += 1) vertex(o[0] + i * step, r[j][i], o[1] + j * step);
    }
    for (let j = 0; j < r.length - 1; j += 1) {
      for (let i = 0; i < w - 1; i += 1) {
        if (skip && skip(i, j)) continue;
        const a = base + i + w * j;
        const b = base + i + w * (j + 1);
        const c = base + i + 1 + w * (j + 1);
        const d = base + i + 1 + w * j;
        indices.push(a, b, d, b, c, d);
      }
    }
  };
  const cells = inset && Array.isArray(inset.cells) ? inset.cells : null;
  grid(origin, spacing, rows, cells ? (i, j) => i >= cells[0] && i < cells[2] && j >= cells[1] && j < cells[3] : null);
  if (inset && cells) grid(inset.origin, inset.spacing, inset.rows, null);

  // Hillshade from the slope of the drawn surface.
  const colors = new Float32Array(positions.length);
  const h = spacing / 4;
  const n = new THREE.Vector3();
  for (let k = 0; k < positions.length; k += 3) {
    const x = positions[k];
    const z = positions[k + 2];
    const dx = heightAt(x + h, z) - heightAt(x - h, z);
    const dz = heightAt(x, z + h) - heightAt(x, z - h);
    n.set(-dx, 2 * h, -dz).normalize();
    const s = THREE.MathUtils.clamp(1 + SHADE_GAIN * (n.dot(SUN) - SUN.y), SHADE_RANGE[0], SHADE_RANGE[1]) * IMAGE_GAIN;
    colors[k] = s;
    colors[k + 1] = s;
    colors[k + 2] = s;
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute('uv', new THREE.Float32BufferAttribute(uvs, 2));
  geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
  geometry.setIndex(positions.length / 3 > 65535 ? new THREE.Uint32BufferAttribute(indices, 1)
    : new THREE.Uint16BufferAttribute(indices, 1));
  geometry.computeBoundingSphere();

  /**
   * Polyline laid on the ground: points are [x, y, z] or plan pairs [x, z];
   * every segment is split at `step` metres and lies `lift` above the surface.
   */
  function drape(points, lift = 1.5, step = 20) {
    const out = [];
    const planZ = (p) => (p.length === 3 ? p[2] : p[1]);
    for (let i = 0; i < points.length; i += 1) {
      const a = points[i];
      const b = points[i + 1];
      const ax = a[0];
      const az = planZ(a);
      out.push([ax, heightAt(ax, az) + lift, az]);
      if (!b) break;
      const bx = b[0];
      const bz = planZ(b);
      const parts = Math.max(1, Math.ceil(Math.hypot(bx - ax, bz - az) / step));
      for (let k = 1; k < parts; k += 1) {
        const x = ax + ((bx - ax) * k) / parts;
        const z = az + ((bz - az) * k) / parts;
        out.push([x, heightAt(x, z) + lift, z]);
      }
    }
    return out;
  }

  return {
    geometry,
    triangles: indices.length / 3,
    extent,
    heightAt,
    drape,
  };
}

// ------------------------------------------------------------------ x-ray
// A terrain fragment is drawn translucent when the line of sight, continued
// beyond it, runs through the box of the workings for at least `edge[0]`
// metres (fully translucent from `edge[1]`). The same test runs in JavaScript
// for picking, so that hidden workings are not picked through opaque ground.

export const XRAY_EDGE = [25, 150];   // m of line of sight inside the box
export const XRAY_ALPHA = 0.24;       // opacity of the ground over the workings

/** Length of the ray from `p` along unit `d` inside the box [min, max]. */
export function chordInBox(p, d, min, max) {
  let t0 = 0;
  let t1 = Infinity;
  for (let k = 0; k < 3; k += 1) {
    const dk = Math.abs(d[k]) < 1e-5 ? 1e-5 : d[k];
    let a = (min[k] - p[k]) / dk;
    let b = (max[k] - p[k]) / dk;
    if (a > b) [a, b] = [b, a];
    t0 = Math.max(t0, a);
    t1 = Math.min(t1, b);
  }
  return Math.max(0, t1 - t0);
}

/** Opacity of the ground at world point `p` seen from `eye` (the shader's formula). */
export function groundOpacity(p, eye, box) {
  if (!box) return 1;
  const d = [p[0] - eye[0], p[1] - eye[1], p[2] - eye[2]];
  const l = Math.hypot(d[0], d[1], d[2]) || 1;
  const chord = chordInBox(p, [d[0] / l, d[1] / l, d[2] / l], box.min, box.max);
  const t = THREE.MathUtils.clamp((chord - XRAY_EDGE[0]) / (XRAY_EDGE[1] - XRAY_EDGE[0]), 0, 1);
  const k = t * t * (3 - 2 * t);
  return 1 + (XRAY_ALPHA - 1) * k;
}

/**
 * Material of the ground: unlit, vertex hillshade times the image (plain
 * `fallback` colour until the image has loaded), with the x-ray cut. Returns
 * { material, setXray(box), setMap(texture) }; `box` is { min: [x, y, z],
 * max: [x, y, z] } of the workings, or null for an opaque ground.
 */
export function terrainMaterial(fallback) {
  const material = new THREE.MeshBasicMaterial({
    color: fallback.clone(), vertexColors: true, transparent: true, depthWrite: true,
  });
  const uniforms = {
    xrayMin: { value: new THREE.Vector3() },
    xrayMax: { value: new THREE.Vector3() },
    xrayEdge: { value: new THREE.Vector2(XRAY_EDGE[0], XRAY_EDGE[1]) },
    xrayAlpha: { value: 1 },
  };
  material.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, uniforms);
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', '#include <common>\nvarying vec3 vXrayWorld;')
      .replace('#include <project_vertex>',
        '#include <project_vertex>\n\tvXrayWorld = (modelMatrix * vec4(transformed, 1.0)).xyz;');
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <common>', `#include <common>
varying vec3 vXrayWorld;
uniform vec3 xrayMin;
uniform vec3 xrayMax;
uniform vec2 xrayEdge;
uniform float xrayAlpha;
float xrayChord(vec3 p, vec3 d) {
  vec3 s = vec3(abs(d.x) < 1e-5 ? 1e-5 : d.x, abs(d.y) < 1e-5 ? 1e-5 : d.y, abs(d.z) < 1e-5 ? 1e-5 : d.z);
  vec3 a = (xrayMin - p) / s;
  vec3 b = (xrayMax - p) / s;
  vec3 n = min(a, b);
  vec3 f = max(a, b);
  float t0 = max(max(max(n.x, n.y), n.z), 0.0);
  float t1 = min(min(f.x, f.y), f.z);
  return max(t1 - t0, 0.0);
}`)
      .replace('#include <opaque_fragment>', `#include <opaque_fragment>
\tgl_FragColor.a *= mix(1.0, xrayAlpha,
\t\tsmoothstep(xrayEdge.x, xrayEdge.y, xrayChord(vXrayWorld, normalize(vXrayWorld - cameraPosition))));`);
  };
  return {
    material,
    setXray(box) {
      uniforms.xrayMin.value.fromArray(box ? box.min : [0, 0, 0]);
      uniforms.xrayMax.value.fromArray(box ? box.max : [0, 0, 0]);
      uniforms.xrayAlpha.value = box ? XRAY_ALPHA : 1;
    },
    /** The image replaces the plain colour (the vertex hillshade stays). */
    setMap(texture) {
      material.map = texture;
      material.color.setRGB(1, 1, 1);
      material.needsUpdate = true;
    },
  };
}
