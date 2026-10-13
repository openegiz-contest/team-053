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
  ground: '#66757a',
  pit: '#8a8273',
  skirt: '#2a343d',
  pad: '#27313b',
  frame: '#2c3a49',
  ruler: '#7c8da3',
  drive: '#8494a8',          // a level drive with enough air
  driveQuiet: '#4d5a6b',     // mined-out level
  airway: '#93a7bc',
  backfill: '#4b4135',
  road: '#5f6b78',
  stream: '#3f86c4',
  pipe: '#4b6f8f',
  pond: '#3f86c4',
  water: '#58a6e6',
  ore: '#d9a544',
  tailings: '#9c907c',
  tailingsActive: '#c2b396',
  airIntake: '#9fdcec',
  airExhaust: '#c9a27e',
  truckEmpty: '#dfe6ee',
  truckLoaded: '#f2b63a',
  cab: '#8fa0b4',
  lhd: '#8ed1c6',
  rig: '#b9a8e2',
  select: '#ffffff',
  plate: '#51647a',
  plateQuiet: '#33404e',
};

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
    color,
  };
}
