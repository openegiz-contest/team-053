// Sheet layout of the long section. The mine is drawn at one scale on both
// axes. Declines, stopes and airways overlap in projection, so text stays out of
// the mine body: every level is a ruled row that runs out of the drawing on both
// sides.
//   left   elevation ruler, «гор. +150 м», air flow and state of the level
//   right  the level's stopes (three cells, west to east), then its pump
//          station or underground fans
// The ground line is the terrain profile along the ore zone. The surface east of
// the workings (ponds, stockpile, yard, plant) lies above the right gutter; it is
// drawn to scale where it fits and compressed in x where it does not. The
// tailings facility, off the section to the north-east, takes the east end of
// the sheet past a break mark. Surface objects are labelled in two text lines
// above the ground.
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
import { shortName } from './model.js';

const BASE_FONT = 9.5;          // px, the smallest text size on the sheet
const MAX_FONT_SCALE = 1.5;
const MIN_W = 860;              // a smaller container shows the sheet scaled down
const MIN_H = 300;
const WEST_MIN = 0.5;           // the surface west of the mine may be drawn closer, to this factor
const VARIANTS = ['two', 'oneState', 'three', 'inbox', 'one'];       // in the order of preference
const LINES = { one: 1, oneState: 1, two: 2, three: 3, inbox: 3 };
const TOLERANCE = 0.9;          // a preferred variant may cost this share of the drawing scale
const STOPE_STATES = STOPE_ORDER;

/** px kept free above and below a stope box, so that the level drive between two stacked blocks reads. */
function stopeInset(s) {
  return Math.min(3, Math.max(1.5, 2 * s));
}

/** Widths of the tailings strip at font size F: dams with labels beside, or inside; the caption. */
function tailingsWidths(M, measure, F) {
  const m = (content, weight) => measure(content, F, weight);
  const gap = F * 0.9;
  const sample = (dam) => (dam.planned ? stateLabel('planned', 'tailings_dam') : '100 %');
  const name = (dam) => m(shortName(dam.id) || '№ 0', 600);
  const sum = (list) => list.reduce((total, w) => total + w, 0) + gap * Math.max(0, list.length - 1);
  return {
    gap,
    beside: sum(M.dams.map((dam) => name(dam) + F * 0.4 + m(sample(dam)) + 5)),
    inside: sum(M.dams.map((dam) => Math.max(name(dam), m(sample(dam))) + 9)),
    bare: sum(M.dams.map((dam) => name(dam) + 7)),
    caption: m('Хвосты:', 600) + F * 0.5 + m('осталось 3,1 года'),
  };
}

/**
 * The surface east of the workings in a strip of the given width: to scale when
 * it fits; otherwise the stretches the objects stand on keep a larger share
 * than the empty ground between them (a quarter of it, or more where there is
 * room), and the whole is scaled down. at(x) is px from mineX1; scale is the
 * smallest px per metre over the scale of the section (1 when to scale).
 */
function eastStrip(M, s, room) {
  const x0 = M.mineX1;
  const x1 = Math.max(M.eastX1, x0 + 1);
  const pad = 6;
  const spans = M.surfaceSpans
    .map(([a, b]) => [Math.max(x0, a - pad), Math.min(x1, b + pad)])
    .filter(([a, b]) => b > a)
    .sort((a, b) => a[0] - b[0]);
  const merged = [];
  for (const span of spans) {
    const last = merged[merged.length - 1];
    if (last && span[0] <= last[1]) last[1] = Math.max(last[1], span[1]);
    else merged.push(span.slice());
  }
  const busy = merged.reduce((sum, [a, b]) => sum + (b - a), 0);
  const free = x1 - x0 - busy;
  const full = (x1 - x0) * s;
  let gap = 1;
  let k = 1;
  if (full > room) {
    // Empty ground first, down to a quarter; then everything together.
    gap = free > 0 ? Math.max(0.25, (room / s - busy) / free) : 1;
    k = Math.min(1, room / (s * (busy + gap * free)));
  }
  const knots = [[x0, 0]];
  let at = x0;
  let offset = 0;
  const advance = (to, density) => {
    offset += (to - at) * s * k * density;
    at = to;
    knots.push([at, offset]);
  };
  for (const [a, b] of merged) {
    if (a > at) advance(a, gap);
    advance(b, 1);
  }
  if (x1 > at) advance(x1, gap);
  const last = knots[knots.length - 1];
  return {
    width: last[1],
    scale: Math.min(1, k * Math.min(1, gap)),
    at(x) {
      if (x >= last[0]) return last[1] + (x - last[0]) * s * k * gap;
      for (let i = 1; i < knots.length; i += 1) {
        const [xa, pa] = knots[i - 1];
        const [xb, pb] = knots[i];
        if (x <= xb) return xb === xa ? pa : pa + (pb - pa) * (x - xa) / (xb - xa);
      }
      return last[1];
    },
  };
}

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
    // A stope box (106 x 50 m, face-on) has to hold «150-1 80,0 тыс. т» and the state under it.
    fits = fits && M.stopeW * s - 10 >= Math.max(w.name + w.gap + w.valueUnit, w.state)
      && M.stopeH * s - 2 * stopeInset(s) >= w.lineH * 2 + 5;
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
  const yg = oy + L.padTop + L.sky;                                // px of M.top, the highest ground

  // From the west edge to mineX1 the sheet is to scale. The surface west of
  // mineX0 is drawn closer to the mine when the left gutter is narrower than it.
  const overhang = (M.mineX0 - M.worldX0) * s;
  const west = overhang > 0 ? Math.min(1, (ox - 4) / overhang) : 1;
  const linear = (x) => (x >= M.mineX0 ? ox + (x - M.mineX0) * s : ox - (M.mineX0 - x) * s * west);

  // East of mineX1: the surface strip over the right gutter, then the tailings past a break.
  const gutterX0 = linear(M.mineX1);
  const right = W - 8;
  const tail = tailingsWidths(M, measure, L.F);
  const breakW = M.dams.length ? L.F * 2.6 : 0;
  let tailW = 0;
  if (M.dams.length) {
    // As much as the dams with their values beside or inside need, within 45 % of
    // the gutter; at least the bare dams (fill only) and the caption.
    const low = Math.max(tail.bare, tail.caption);
    tailW = Math.min(Math.max((right - gutterX0) * 0.45, low), Math.max(low, tail.beside * 1.2));
  }
  let tx0 = right - tailW;
  const strip = eastStrip(M, s, tx0 - breakW - gutterX0);
  // The surface fits to scale: the tailings follow it and take the rest of the sheet.
  if (strip.scale >= 1 && M.dams.length) tx0 = Math.min(tx0, gutterX0 + strip.width + breakW);
  const px = (x) => (x <= M.mineX1 ? linear(x) : gutterX0 + strip.at(x));
  const py = (y) => yg + (M.top - y) * s;
  const groundY = (x) => py(M.groundAt(x));
  const rightX0 = px(M.mineX1) + L.rightPad;
  const cols = [0, 1, 2].map((index) => rightX0 + index * (L.chip + L.chipGap));
  const stationX = rightX0 + 3 * (L.chip + L.chipGap);

  return {
    W, H, fit, s, F: L.F, lineH: L.lineH, variant: L.variant, lines: L.lines, inbox: L.variant === 'inbox', west,
    east: strip.scale,
    ox, yg, px, py, groundY, stopeInset: stopeInset(s),
    padBottom: L.padBottom, legendH: L.legendH, structH: L.structH,
    skyLine1: yg - L.structH - 5 - L.F * 1.22, skyLine2: yg - L.structH - 5,
    left: { rulerX: L.ruler, nameX: L.ruler + 8, valueX: ox - 4 },
    right: {
      x0: rightX0, cols, chip: L.chip, stationX, x1: W - 6, swatch: L.swatch, gap: L.gap,
      stationW: Math.max(L.station, W - 6 - stationX),
    },
    // The surface east of the workings ends at eastPx1; the tailings strip is [x0, x1].
    eastPx1: px(M.eastX1),
    // The ground line of the section runs on to the break mark before the tailings.
    groundEndPx: M.dams.length ? tx0 - L.F * 1.25 - 4 : px(M.eastX1),
    tail: { x0: tx0, x1: right, gap: tail.gap },
  };
}
