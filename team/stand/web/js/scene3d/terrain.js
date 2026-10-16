// The real ground of the scene (spec 4.2, geometry.json `terrain`): one mesh of
// the 65 x 65 heightmap with the finer pit inset in place of its coarse cells,
// draped with the Sentinel-2 image, and a height sampler that follows exactly
// the drawn triangles (so that outlines and markers sit on the ground).
//
// Every cell is split along its south-west to north-east diagonal, the vertex
// order of three.js PlaneGeometry rotated to lie flat. The inset border
// elevations match the coarse edges, so the two grids meet without cracks.
//
// The underground stays the subject: an "x-ray" ellipsoid around the workings
// makes the ground translucent wherever the line of sight continues into it,
// from any camera; the rest of the ground is opaque (see terrainMaterial).

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
// The workings are wrapped in an ellipsoid (statics.js). A terrain fragment is
// drawn the more translucent the longer the line of sight, continued beyond it,
// runs inside that ellipsoid: `edge[0]` metres or less keep the ground opaque,
// `edge[1]` and more give the x-ray opacity. Because the chord of an ellipsoid
// shrinks smoothly towards its outline, the window over the workings fades out
// softly in an oval, without a box edge, from any camera. Inside the window the
// image is lightened rather than darkened, so that the ground over the workings
// stays part of the landscape. The same test runs in JavaScript for picking and
// for the labels, so that hidden workings are not picked or labelled through
// opaque ground.

export const XRAY_EDGE = [30, 330];   // m of line of sight inside the ellipsoid
export const XRAY_ALPHA = 0.34;       // opacity of the ground at the heart of the window
export const XRAY_LIGHT = [1.22, 0.025];   // inside the window: colour * gain + lift

/**
 * Length of the ray from `p` along unit `d` inside the ellipsoid
 * { center, radii }: the part with t >= 0.
 */
export function chordInEllipsoid(p, d, ellipsoid) {
  const { center: c, radii: r } = ellipsoid;
  const P = [(p[0] - c[0]) / r[0], (p[1] - c[1]) / r[1], (p[2] - c[2]) / r[2]];
  const D = [d[0] / r[0], d[1] / r[1], d[2] / r[2]];
  const a = D[0] * D[0] + D[1] * D[1] + D[2] * D[2];
  const b = P[0] * D[0] + P[1] * D[1] + P[2] * D[2];
  const k = P[0] * P[0] + P[1] * P[1] + P[2] * P[2] - 1;
  const disc = b * b - a * k;
  if (disc <= 0 || a <= 0) return 0;
  const root = Math.sqrt(disc);
  const t1 = (-b + root) / a;
  const t0 = Math.max(0, (-b - root) / a);
  return Math.max(0, t1 - t0);
}

/** 0 outside the x-ray window, 1 at its heart: the shader's weight at `p` seen from `eye`. */
export function xrayWeight(p, eye, ellipsoid) {
  if (!ellipsoid) return 0;
  const d = [p[0] - eye[0], p[1] - eye[1], p[2] - eye[2]];
  const l = Math.hypot(d[0], d[1], d[2]) || 1;
  const chord = chordInEllipsoid(p, [d[0] / l, d[1] / l, d[2] / l], ellipsoid);
  const t = THREE.MathUtils.clamp((chord - XRAY_EDGE[0]) / (XRAY_EDGE[1] - XRAY_EDGE[0]), 0, 1);
  return t * t * (3 - 2 * t);
}

/** Opacity of the ground at world point `p` seen from `eye` (the shader's formula). */
export function groundOpacity(p, eye, ellipsoid) {
  return 1 + (XRAY_ALPHA - 1) * xrayWeight(p, eye, ellipsoid);
}

/**
 * Material of the ground: unlit, vertex hillshade times the image (plain
 * `fallback` colour until the image has loaded), with the x-ray window.
 * Returns { material, setXray(ellipsoid), setMap(texture) }; `ellipsoid` is
 * { center: [x, y, z], radii: [rx, ry, rz] } around the workings, or null for
 * an opaque ground.
 */
export function terrainMaterial(fallback) {
  const material = new THREE.MeshBasicMaterial({
    color: fallback.clone(), vertexColors: true, transparent: true, depthWrite: true,
  });
  const uniforms = {
    xrayCenter: { value: new THREE.Vector3() },
    xrayRadii: { value: new THREE.Vector3(1, 1, 1) },
    xrayEdge: { value: new THREE.Vector2(XRAY_EDGE[0], XRAY_EDGE[1]) },
    xrayAlpha: { value: 1 },
    xrayLight: { value: new THREE.Vector2(XRAY_LIGHT[0], XRAY_LIGHT[1]) },
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
uniform vec3 xrayCenter;
uniform vec3 xrayRadii;
uniform vec2 xrayEdge;
uniform float xrayAlpha;
uniform vec2 xrayLight;
float xrayChord(vec3 p, vec3 d) {
  vec3 q = (p - xrayCenter) / xrayRadii;
  vec3 e = d / xrayRadii;
  float a = dot(e, e);
  float b = dot(q, e);
  float disc = b * b - a * (dot(q, q) - 1.0);
  if (disc <= 0.0) return 0.0;
  float root = sqrt(disc);
  return max((-b + root) / a - max((-b - root) / a, 0.0), 0.0);
}`)
      .replace('#include <opaque_fragment>', `#include <opaque_fragment>
\tfloat xrayK = xrayAlpha < 1.0
\t\t? smoothstep(xrayEdge.x, xrayEdge.y, xrayChord(vXrayWorld, normalize(vXrayWorld - cameraPosition))) : 0.0;
\tgl_FragColor.rgb = mix(gl_FragColor.rgb, min(gl_FragColor.rgb * xrayLight.x + xrayLight.y, vec3(1.0)), xrayK);
\tgl_FragColor.a *= mix(1.0, xrayAlpha, xrayK);`);
  };
  return {
    material,
    setXray(ellipsoid) {
      uniforms.xrayCenter.value.fromArray(ellipsoid ? ellipsoid.center : [0, 0, 0]);
      uniforms.xrayRadii.value.fromArray(ellipsoid ? ellipsoid.radii : [1, 1, 1]);
      uniforms.xrayAlpha.value = ellipsoid ? XRAY_ALPHA : 1;
    },
    /** The image replaces the plain colour (the vertex hillshade stays). */
    setMap(texture) {
      material.map = texture;
      material.color.setRGB(1, 1, 1);
      material.needsUpdate = true;
    },
  };
}

/**
 * The backdrop of the x-ray window: the inner wall of the ellipsoid, pressed
 * under the ground where it would rise above it, coloured like the soil near
 * the surface and darker with depth. Through the translucent ground the
 * workings are seen against it rather than against the black page, so the
 * window reads as a look into the earth, not as a dark box. Drawn opaque, back
 * faces only, so that from outside only its far side shows. Returns a
 * BufferGeometry (about 800 triangles), or null without an ellipsoid.
 */
export function xrayBackdrop(ellipsoid, heightAt, near, deep) {
  if (!ellipsoid) return null;
  const geometry = new THREE.SphereGeometry(1, 32, 14);
  const position = geometry.getAttribute('position');
  const colors = new Float32Array(position.count * 3);
  const { center: c, radii: r } = ellipsoid;
  const tint = new THREE.Color();
  for (let i = 0; i < position.count; i += 1) {
    const x = c[0] + position.getX(i) * r[0];
    const z = c[2] + position.getZ(i) * r[2];
    const ground = heightAt(x, z) - 4;
    const y = Math.min(ground, c[1] + position.getY(i) * r[1]);
    position.setXYZ(i, x, y, z);
    const t = THREE.MathUtils.clamp((ground - y) / (r[1] * 1.4), 0, 1);
    tint.copy(near).lerp(deep, Math.sqrt(t));
    colors[i * 3] = tint.r;
    colors[i * 3 + 1] = tint.g;
    colors[i * 3 + 2] = tint.b;
  }
  geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
  geometry.deleteAttribute('normal');
  geometry.deleteAttribute('uv');
  geometry.computeBoundingSphere();
  return geometry;
}
