// Map furniture of the plan: the UTM grid with its edge labels, the scale bar,
// the north arrow, the legend and the attribution line.

import { STOPE_ORDER, VEHICLE_MARKS, stateLabel, stopeColor } from '../panels/dict.js';
import { el, fmt } from '../panels/format.js';
import { S, set } from './svg.js';

export const ATTRIBUTION = 'Снимок: Contains modified Copernicus Sentinel data 2026 · объекты: © OpenStreetMap contributors';
const GRID_STEPS = [50, 100, 200, 250, 500, 1000];
const SCALE_STEPS = [10, 20, 50, 100, 200, 250, 500, 1000, 2000];

/** The offsets of the scene frame from UTM 44N, read from frame.crs (spec 4.2). */
export function utmOffsets(geometry) {
  const crs = (geometry.frame && geometry.frame.crs) || '';
  const east = crs.match(/easting\s*-\s*([\d.]+)/);
  const north = crs.match(/=\s*([\d.]+)\s*-\s*UTM/);
  return { e0: east ? Number(east[1]) : 613640, n0: north ? Number(north[1]) : 5576392.36 };
}

const metres = (value) => (value >= 1000 ? `${fmt(value / 1000, value % 1000 ? 1 : 0)} км` : `${fmt(value)} м`);

export function createGrid(layer, { e0, n0 }, extent) {
  const lines = S('path', { class: 'pl-grid' });
  const labels = S('g', { class: 'pl-grid-labels' });
  layer.append(lines, labels);
  let step = 0;
  return {
    get step() {
      return step;
    },
    layout(view, k, toScreen, size) {
      step = GRID_STEPS.find((candidate) => candidate * k >= 120) || GRID_STEPS[GRID_STEPS.length - 1];
      const [vx0, vz0, vx1, vz1] = view;
      const x0 = Math.max(vx0, extent[0]);
      const x1 = Math.min(vx1, extent[2]);
      const z0 = Math.max(vz0, extent[1]);
      const z1 = Math.min(vz1, extent[3]);
      const [sx0, sy0] = toScreen(x0, z0);
      const [sx1, sy1] = toScreen(x1, z1);
      let d = '';
      const texts = [];
      for (let e = Math.ceil((x0 + e0) / step) * step; e - e0 <= x1; e += step) {
        const [sx] = toScreen(e - e0, 0);
        d += `M${sx.toFixed(1)} ${sy0.toFixed(1)}V${sy1.toFixed(1)}`;
        if (sx > 70 && sx < size.w - 60) texts.push(['e', sx, Math.max(sy0, 0) + 50, fmt(e)]);
      }
      for (let n = Math.ceil((n0 - z1) / step) * step; n0 - n >= z0; n += step) {
        const [, sy] = toScreen(0, n0 - n);
        d += `M${sx0.toFixed(1)} ${sy.toFixed(1)}H${sx1.toFixed(1)}`;
        if (sy > 40 && sy < size.h - 40) texts.push(['n', Math.max(sx0, 0) + 5, sy - 4, fmt(n)]);
      }
      set(lines, { d });
      while (labels.childNodes.length < texts.length) labels.append(S('text', {}));
      [...labels.childNodes].forEach((node, i) => {
        const item = texts[i];
        if (!item) {
          node.setAttribute('visibility', 'hidden');
          return;
        }
        const [axis, x, y, content] = item;
        if (node.textContent !== content) node.textContent = content;
        set(node, { x: axis === 'e' ? x + 4 : x, y, visibility: 'visible', class: axis });
      });
    },
  };
}

export function createScale(layer) {
  const g = S('g', { class: 'pl-scale' });
  const left = S('rect', { class: 'a', height: 4 });
  const right = S('rect', { class: 'b', height: 4 });
  const zero = S('text', { 'text-anchor': 'middle' }, '0');
  const mid = S('text', { 'text-anchor': 'middle' });
  const end = S('text', { 'text-anchor': 'middle' });
  g.append(left, right, zero, mid, end);
  layer.append(g);
  return {
    layout(k, size) {
      const length = SCALE_STEPS.find((candidate) => candidate * k >= 80) || SCALE_STEPS[SCALE_STEPS.length - 1];
      const w = length * k;
      const x = 14;
      const y = size.h - 34;
      set(left, { x, y, width: w / 2 });
      set(right, { x: x + w / 2, y, width: w / 2 });
      set(zero, { x, y: y - 4 });
      set(mid, { x: x + w / 2, y: y - 4 });
      set(end, { x: x + w, y: y - 4 });
      mid.textContent = metres(length / 2).replace(/ (м|км)$/, '');
      end.textContent = metres(length);
      return [x - 6, y - 16, x + w + 24, y + 8];
    },
  };
}

export function northArrow() {
  const svg = S('svg', { class: 'pl-north-mark', viewBox: '-12 -16 24 30', width: 24, height: 30, 'aria-hidden': 'true' },
    S('path', { class: 'l', d: 'M0 -14L7 8L0 4Z' }),
    S('path', { class: 'r', d: 'M0 -14L-7 8L0 4Z' }));
  return el('div', {
    class: 'pl-north', title: 'Север сетки UTM 44N; истинный север на 1,2° западнее',
  }, svg, el('span', { text: 'С' }));
}

// Legend rows: a small symbol and its meaning.
function swatch(kind) {
  const box = (...children) => S('svg', { viewBox: '0 0 26 14', width: 26, height: 14, 'aria-hidden': 'true' }, children);
  switch (kind) {
    case 'haul': return box(S('path', { class: 'lg-haul-case', d: 'M1 7H25' }), S('path', { class: 'lg-haul', d: 'M1 7H25' }));
    case 'road': return box(S('path', { class: 'lg-road', d: 'M1 7H25' }));
    case 'water': return box(S('path', { class: 'lg-water', d: 'M1 9C7 3 13 11 19 5 22 3 24 5 25 5' }));
    case 'pond': return box(S('rect', { class: 'lg-pond', x: 6, y: 2, width: 14, height: 10, rx: 4 }));
    case 'dam': return box(S('rect', { class: 'lg-dam-a', x: 2, y: 2, width: 10, height: 10 }), S('rect', { class: 'lg-dam-b', x: 14, y: 2, width: 10, height: 10 }));
    case 'plant': return box(S('rect', { class: 'lg-plant', x: 3, y: 2, width: 20, height: 10 }), S('rect', { class: 'lg-line', x: 7, y: 4, width: 4, height: 6 }), S('rect', { class: 'lg-line', x: 13, y: 4, width: 4, height: 6 }));
    case 'shaft': return box(S('g', { class: 'lg-fan', transform: 'translate(7 7)' }, S('rect', { x: -4.2, y: -4.2, width: 8.4, height: 8.4, rx: 1.8 }), S('circle', { r: 2.1 })), S('g', { class: 'lg-shaft', transform: 'translate(18 7)' }, S('circle', { class: 'rim', r: 5 }), S('circle', { class: 'core', r: 1.8 })));
    case 'portal': return box(S('path', { class: 'lg-portal', d: 'M7 12V6A6 6 0 0 1 19 6V12Z' }));
    case 'monitor': return box(S('path', { class: 'lg-monitor', d: 'M13 2L18 7L13 12L8 7Z' }));
    case 'loaded': return box(S('rect', { class: 'lg-truck loaded', x: 7, y: 4, width: 12, height: 6, rx: 1.2 }));
    case 'empty': return box(S('rect', { class: 'lg-truck', x: 7, y: 4, width: 12, height: 6, rx: 1.2 }));
    case 'held': return box(S('circle', { class: 'lg-ring warn', cx: 13, cy: 7, r: 5.5 }), S('rect', { class: 'lg-truck', x: 9.5, y: 5.2, width: 7, height: 3.6, rx: 0.8 }));
    case 'repair': return box(S('circle', { class: 'lg-ring fail', cx: 13, cy: 7, r: 5.5 }), S('rect', { class: 'lg-truck', x: 9.5, y: 5.2, width: 7, height: 3.6, rx: 0.8 }));
    case 'open': return box(S('path', { class: 'lg-decline', d: 'M1 7H25' }));
    case 'closed': return box(S('path', { class: 'lg-decline closed', d: 'M1 7H25' }));
    case 'drive': return box(S('path', { class: 'lg-drive', d: 'M1 7H25' }));
    case 'pump': return box(S('rect', { class: 'lg-pump', x: 8.5, y: 2.5, width: 9, height: 9, rx: 1.5 }));
    case 'bind': return box(S('path', { class: 'lg-bind', d: 'M1 7H25' }));
    default: return box();
  }
}

export function createLegend(onToggle) {
  const row = (kind, text) => el('li', {}, swatch(kind), el('span', { text }));
  const stopeList = el('ul', { class: 'pl-legend-stopes' });
  const body = el('div', { class: 'pl-legend-body' },
    el('h4', { text: 'Поверхность' }),
    el('ul', {},
      row('haul', 'откаточная дорога'), row('road', 'дорога (OSM)'), row('water', 'ручей, река'),
      row('pond', 'илоотстойник'), row('dam', 'карта хвостохранилища, полоса — заполнение'),
      row('plant', 'фабрика и её линии'), row('shaft', 'вентилятор и ствол'),
      row('portal', 'портал уклона'), row('monitor', 'пост мониторинга воды')),
    el('h4', { text: 'Самосвалы' }),
    el('ul', {},
      row('loaded', 'гружёный'), row('empty', 'порожний'),
      row('held', VEHICLE_MARKS.held), row('repair', VEHICLE_MARKS.repair)),
    el('h4', { class: 'under', text: 'Подземная часть, план — схема' }),
    el('ul', { class: 'under' },
      row('open', 'уклон открыт'), row('closed', 'уклон закрыт'), row('drive', 'штрек горизонта'),
      row('pump', 'насосная станция')),
    stopeList,
    el('ul', { class: 'pl-legend-bind' }, row('bind', 'узкое место производства')));
  const toggle = el('button', {
    type: 'button', class: 'pl-legend-toggle', 'aria-expanded': 'true', text: 'Легенда',
    onclick: () => {
      const open = toggle.getAttribute('aria-expanded') !== 'true';
      toggle.setAttribute('aria-expanded', String(open));
      body.hidden = !open;
      if (onToggle) onToggle();
    },
  });
  const node = el('div', { class: 'pl-legend' }, toggle, body);
  let shownStates = '';
  return {
    node,
    open(open) {
      toggle.setAttribute('aria-expanded', String(open));
      body.hidden = !open;
    },
    /** The stope states present now, in the order of the one palette. */
    stopes(states) {
      const list = STOPE_ORDER.filter((state) => states.has(state));
      const key = list.join(',');
      if (key === shownStates) return;
      shownStates = key;
      stopeList.replaceChildren(...list.map((state) => el('li', {},
        el('i', { style: `--c: ${stopeColor(state)}`, 'data-state': state }),
        el('span', { text: stateLabel(state, 'stope') }))));
    },
  };
}
