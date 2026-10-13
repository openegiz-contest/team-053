// Sheet layout of the long section. The mine is drawn at one scale on both
// axes. Declines, stopes and airways overlap in projection, so text stays out of
// the mine body: every level is a ruled row that runs out of the drawing on both
// sides.
//   left   elevation ruler, «гор. +150 м», air flow and state of the level
//   right  the level's stopes (three cells, west to east), then its pump
//          station or underground fans
// Surface objects are labelled in two text lines above the ground line.
//
// The scale, the cell layout and the font size are solved together from the
// container size. Cell layouts (variants):
//   oneState  one line per row: name, state, value        (short, wide containers)
//   one       one line per row: name, value
//   two       two lines: name and value, then the state
//   three     three lines: name, value, state             (narrower gutters)
//   inbox     the stope text moves into the stope boxes, which are large enough
//             at this scale; the right gutter keeps stations, fans and the summary

import { STOPE_ORDER, stateLabel } from '../panels/dict.js';

const BASE_FONT = 9.5;          // px, the smallest text size on the sheet
const MAX_FONT_SCALE = 1.5;
const MIN_W = 860;              // a smaller container shows the sheet scaled down
const MIN_H = 300;
const WEST_MIN = 0.5;           // the surface west of the mine may be drawn closer, to this factor
const VARIANTS = ['two', 'oneState', 'three', 'inbox', 'one'];       // in the order of preference
const LINES = { one: 1, oneState: 1, two: 2, three: 3, inbox: 3 };
const TOLERANCE = 0.9;          // a preferred variant may cost this share of the drawing scale
const STOPE_STATES = STOPE_ORDER;

function widths(measure, fontScale, variant) {
  const F = BASE_FONT * fontScale;
  const m = (content, weight) => measure(content, F, weight);
  const lineH = F * 1.2;
  const swatch = F * 1.05;
  const gap = F * 0.6;
  const name = m('−100-1', 600);
  const valueUnit = m('90,0 тыс. т');
  const value = m('90,0');
  const state = Math.max(...STOPE_STATES.map((token) => m(stateLabel(token, 'stope'))));
  let chip = swatch + name + gap + valueUnit;
  if (variant === 'three') chip = swatch + Math.max(name, valueUnit, state);
  else if (variant === 'two') chip = Math.max(swatch + name + gap + valueUnit, swatch + state);
  else if (variant === 'oneState') chip = swatch + name + gap + state + gap + value;
  const chipGap = F * 1.5;
  const narrow = LINES[variant] === 3;
  const station = narrow
    ? F * 1.1 + Math.max(m('насосная', 600), m('59 % · 300 м³/ч'), m(stateLabel('idle', 'pump_station')))
    : F * 1.4 + m('насосная · 59 % · 300 м³/ч', 600);
  const fanPair = 2 * (F * 1.15 + m('в работе · 102 м³/с')) + F * 1.8;
  const rightPad = 10;
  const ruler = m('+400') + 12;
  const levelName = m('гор. +150 м', 600);
  const levelValue = F * 0.9 + m('104,5 м³/с');
  const left = narrow
    ? ruler + 8 + F * 0.85 + Math.max(levelName, m('104,5 м³/с'), m('вентиляционный')) + 8
    : ruler + 8 + levelName + F * 1.2 + levelValue + 8;
  const inbox = variant === 'inbox';
  const legendH = inbox ? lineH * 1.08 * 3 + F * 0.6 : 0;      // the legend runs under the drawing
  return {
    F, lineH, swatch, gap, name, valueUnit, state, station, rightPad, ruler, left, legendH,
    chip: inbox ? 0 : chip,
    chipGap: inbox ? 0 : chipGap,
    right: rightPad + (inbox ? Math.max(station, fanPair) : 3 * (chip + chipGap) + station) + 6,
    structH: F * 2.3,
    sky: F * 2.5 + F * 2.3 + 6,
    padTop: 3,
    padBottom: F * 1.7 + 5,
  };
}

function solve(M, measure, W, H, fontScale, variant) {
  const w = widths(measure, fontScale, variant);
  const mineW = M.mineX1 - M.mineX0;
  const overhang = M.mineX0 - M.worldX0;      // surface objects west of the mine
  const sV = (H - w.padTop - w.sky - w.padBottom - w.legendH) / (M.top - M.bottom);
  const sW = Math.min((W - w.left - w.right) / mineW, (w.left - 4) / (overhang * WEST_MIN));
  const s = Math.min(sV, sW);
  const lines = LINES[variant];
  let fits = s > 0 && 50 * s >= (lines === 1 ? w.F * 1.5 : w.lineH * lines + w.F * 0.1 + 3);
  if (variant === 'inbox') {
    // A stope box (120 x 40 m) has to hold «150-1 80,0 тыс. т» and the state under it.
    fits = fits && 120 * s - 10 >= Math.max(w.name + w.gap + w.valueUnit, w.state) && 40 * s >= w.lineH * 2 + 5;
  }
  return { ...w, s, fits, variant, lines, fontScale };
}

export function computeLayout(containerW, containerH, M, measure) {
  const W = Math.max(containerW, MIN_W);
  const H = Math.max(containerH, MIN_H);
  const fit = Math.min(containerW / W, containerH / H);

  // The first variant in the order of preference that keeps the drawing within
  // the tolerance of the largest scale any variant reaches is taken.
  const trials = VARIANTS.map((name) => solve(M, measure, W, H, 1, name)).filter((trial) => trial.fits);
  const largest = Math.max(...trials.map((trial) => trial.s), 0);
  const chosen = trials.find((trial) => trial.s >= largest * TOLERANCE);
  const variant = chosen ? chosen.variant : 'one';

  // Grow the text as far as it pays: a larger font costs gutter width.
  let best = solve(M, measure, W, H, 1, variant);
  let bestScore = best.s;
  for (let fontScale = 1.05; fontScale <= MAX_FONT_SCALE + 1e-9; fontScale += 0.05) {
    const trial = solve(M, measure, W, H, fontScale, variant);
    if (!trial.fits) break;
    const score = trial.s * Math.pow(fontScale, 0.6);
    if (score > bestScore) {
      best = trial;
      bestScore = score;
    }
  }

  const L = best;
  const s = Math.max(L.s, 0.2);
  const mineW = (M.mineX1 - M.mineX0) * s;
  const spare = Math.max(0, W - L.left - L.right - mineW);
  const ox = L.left + Math.min(spare * 0.25, 60);                  // px of x = mineX0
  const contentH = L.padTop + L.sky + (M.top - M.bottom) * s + L.padBottom + L.legendH;
  const oy = Math.max(0, (H - contentH) * 0.35);
  const yg = oy + L.padTop + L.sky;                                // px of the ground line

  // East of mineX0 the sheet is to scale. The surface west of it (stockpile,
  // plant) is drawn closer to the mine when the left gutter is narrower than it.
  const overhang = (M.mineX0 - M.worldX0) * s;
  const west = overhang > 0 ? Math.min(1, (ox - 4) / overhang) : 1;
  const px = (x) => (x >= M.mineX0 ? ox + (x - M.mineX0) * s : ox - (M.mineX0 - x) * s * west);
  const py = (y) => yg + (M.top - y) * s;
  const rightX0 = px(M.mineX1) + L.rightPad;
  const cols = [0, 1, 2].map((index) => rightX0 + index * (L.chip + L.chipGap));
  const stationX = rightX0 + 3 * (L.chip + L.chipGap);

  return {
    W, H, fit, s, F: L.F, lineH: L.lineH, variant: L.variant, lines: L.lines, inbox: L.variant === 'inbox', west,
    ox, yg, px, py,
    padBottom: L.padBottom, legendH: L.legendH, structH: L.structH,
    skyLine1: yg - L.structH - 5 - L.F * 1.22, skyLine2: yg - L.structH - 5,
    left: { rulerX: L.ruler, nameX: L.ruler + 8, valueX: ox - 4 },
    right: {
      x0: rightX0, cols, chip: L.chip, stationX, x1: W - 6, swatch: L.swatch, gap: L.gap,
      stationW: Math.max(L.station, W - 6 - stationX),
    },
  };
}
