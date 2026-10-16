// Colours of the 3D scene. State tones are read from the page tokens
// (css/tokens.css), so a state has one colour in the scene, the section and the
// panels; the values below are the fallback when a token is missing.

import * as THREE from 'three';
import { STOPE_COLORS, stopeColor } from '../panels/dict.js';

const TOKEN_FALLBACK = {
  ok: '#3ec79a', warn: '#f2dc5c', fail: '#dc4046', planned: '#8796ab', idle: '#5d6c80',
  flood: '#58a6e6', info: '#9fb3c8', text: '#e9eef4', 'text-2': '#a8b5c3', 'text-3': '#73839a',
  line: '#273341', 'line-strong': '#3a4959',
};

// Scene-only colours: rock, ground and materials that are not states. The stope
// states are not here: they come from panels/dict.js (stopeColor), the one
// palette of the scene and the long section.
const SCENE = {
  background: '#0a0e13',
  pit: '#e2d6bb',            // bench crest lines and the rim of the old pit
  pitFloor: '#b9ad94',
  skirt: '#2a343d',
  soil: '#40382a',            // backdrop of the x-ray window near the surface
  soilDeep: '#1b1915',        // … and at depth
  pad: '#27313b',
  site: '#efe6d2',           // outlines of sites on the image: plant, pad, yard, industrial zone
  tsfCell: '#cfc4ab',        // tailings cells without a dam number
  ruler: '#7c8da3',
  drive: '#8494a8',          // a level drive with enough air
  driveQuiet: '#4d5a6b',     // mined-out level
  airway: '#93a7bc',
  backfill: '#4b4135',
  road: '#ddd3bd',
  stream: '#4fb0f2',
  pipe: '#86b0d2',
  pond: '#3f8fd0',
  water: '#58a6e6',
  ore: '#d9a544',
  tailings: '#9c907c',
  tailingsActive: '#c2b396',
  tailingsPond: '#4f7c86',   // the pond on a tailings fill
  airIntake: '#9fdcec',
  airExhaust: '#c9a27e',
  truckEmpty: '#dfe6ee',
  truckLoaded: '#f2b63a',
  lhd: '#8ed1c6',
  rig: '#b9a8e2',
  select: '#ffffff',
  building: '#c9cfd6',       // walls of the mill hall, the crusher house and the collar houses
  roof: '#8f9cab',           // roofs that carry no state
  concrete: '#8a9096',       // fan base frames
  steel: '#b4bec9',          // ducts, galleries, headers
  stack: '#dfe3e8',
  stackBand: '#c9574f',
  fanMouth: '#2b333c',       // the open end of a fan diffuser
  plate: '#51647a',
  plateQuiet: '#33404e',
};

// The stylised surface (landscape.js): land cover of the ground, in calm tones
// that sit under the twin and the labels on the dark page; roads and water
// stand out a little. The hillshade multiplies them.
const COVER = {
  meadow: '#56644d',         // open land under no mapped area
  farmland: '#69684b',
  wood: '#34503a',           // the forest floor under the trees
  scrub: '#4a5d42',
  park: '#4b6247',
  cemetery: '#55604f',
  residential: '#5a6352',     // the mapped village outline takes in fields too: only a hint
  industrial: '#5f645b',
  quarry: '#7b766c',
  pit: '#857f74',            // the carved final pit
  bare: '#77705f',
  heap: '#7c776c',           // waste heaps
  parking: '#6a6a67',
  tailings: '#a19985',       // tailings beaches inside the dams
  water: '#2f6d9c',
  paved: '#b5ae9f',          // asphalt roads
  road: '#a59b86',           // village streets and service roads
  dirt: '#9a8f78',
  track: '#887d68',
  path: '#7c7564',
};
// Models of the landscape: walls and roofs of the OSM buildings, trees, heaps, walls and fences.
const MODEL = {
  wall: '#d4cec2',
  wallIndustrial: '#bcc2c7',
  roofFlat: '#8c9399',
  roofIndustrial: '#8e979f',
  trunk: '#5b4b3b',
  heapSide: '#8a8478',
  heapTop: '#958f82',
  wallBarrier: '#a8a297',
  fence: '#8d897f',
  dam: '#9c937f',            // the embankments of the tailings cells
  damCrest: '#b2a993',
};
const ROOFS = ['#a5604c', '#9a5a49', '#6f7e8d', '#6b8a69', '#857060', '#8a8d8f', '#b07a52'];
const GREENS = ['#4f7a45', '#5a8549', '#45703f', '#62894c', '#3f6a3d', '#7f9446', '#90944a'];

export const GRADE_MIN = 1.4;   // g/t, dark end of the grade ramp
export const GRADE_MAX = 2.7;   // g/t, bright end
const GRADE_LOW = '#4a3b22';
const GRADE_HIGH = '#ffd65c';

export function createPalette() {
  const style = getComputedStyle(document.documentElement);
  const css = {};
  for (const [name, fallback] of Object.entries(TOKEN_FALLBACK)) {
    const value = style.getPropertyValue('--' + name).trim();
    css[name] = /^#[0-9a-f]{6}$/i.test(value) ? value : fallback;
  }
  const cache = new Map();
  const color = (hex) => {
    if (!cache.has(hex)) cache.set(hex, new THREE.Color(hex));
    return cache.get(hex);
  };
  const low = new THREE.Color(GRADE_LOW);
  const high = new THREE.Color(GRADE_HIGH);
  return {
    css,
    cssScene: SCENE,
    cssStope: STOPE_COLORS,
    cssGrade: [GRADE_LOW, GRADE_HIGH],
    /** Colour of a state tone: ok | warn | fail | planned | idle | flood | info. */
    tone: (tone) => color(css[tone] || css.idle),
    scene: (name) => color(SCENE[name]),
    stope: (state) => color(stopeColor(state)),
    /** Sequential ramp for the gold grade of a stope. */
    grade(value, out) {
      const t = Math.max(0, Math.min(1, (value - GRADE_MIN) / (GRADE_MAX - GRADE_MIN)));
      return out.copy(low).lerp(high, t);
    },
    /** Land-cover colour of the stylised ground (meadow for an unknown class). */
    cover: (cls) => color(COVER[cls] || COVER.meadow),
    model: (name) => color(MODEL[name]),
    roofs: () => ROOFS.map(color),
    greens: () => GREENS.map(color),
    color,
  };
}
