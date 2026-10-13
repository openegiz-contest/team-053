// 2D long section of the mine: an SVG projection of geometry.json onto the X-Y
// plane (x east, y elevation, seen from the south), with live twin data.
// View contract (spec 7.1): mount(container, geometry) -> { update, focus, dispose }.
// The same module is mounted in the scene's container when WebGL is unavailable,
// so nothing here assumes a container id or size.
//
// Files: model.js reads the geometry, layout.js solves scale and gutters,
// underground.js, units.js, surface.js and tables.js draw the sheet and register
// their live updates, viewport.js zooms and pans, card.js is the hover card.

import { NS, STOPE_ORDER, stopeColor } from '../panels/dict.js';
import { el } from '../panels/format.js';
import { S, createMeasure, setText } from './svg.js';
import { readModel } from './model.js';
import { computeLayout } from './layout.js';
import { buildUnderground } from './underground.js';
import { buildUnits } from './units.js';
import { buildSurface } from './surface.js';
import { buildTables } from './tables.js';
import { createCard } from './card.js';
import { createViewport } from './viewport.js';

const LAYERS = ['grid', 'back', 'bands', 'stopes', 'drives', 'air', 'water', 'declines', 'units', 'labels', 'over'];
const MOBILE = new Set(['haul_truck', 'lhd', 'drill_rig']);
const RINGED = new Set([...MOBILE, 'main_fan', 'pump_station', 'monitoring_point', 'settling_pond']);
const MAX_PULSES = 14;
let mounts = 0;

function ensureCss() {
  const id = 'sx-style';
  let link = document.getElementById(id);
  if (link && link.sheet) return Promise.resolve();
  if (!link) {
    link = document.createElement('link');
    link.id = id;
    link.rel = 'stylesheet';
    link.href = new URL('./section.css', import.meta.url).href;
    document.head.append(link);
  }
  return new Promise((resolve) => {
    link.addEventListener('load', resolve, { once: true });
    link.addEventListener('error', resolve, { once: true });
    setTimeout(resolve, 2000);
  });
}

export async function mount(container, geometry) {
  await ensureCss();
  mounts += 1;
  const uid = `sx${mounts}`;
  const M = readModel(geometry);

  if (getComputedStyle(container).position === 'static') container.style.position = 'relative';
  const root = el('div', { class: 'sx-root' });
  // The stope colours come from the one palette in panels/dict.js.
  for (const state of STOPE_ORDER) root.style.setProperty(`--st-${state}`, stopeColor(state));
  const sheet = S('g', { class: 'sx-sheet' });
  const svg = S('svg', { class: 'sx-svg', 'aria-label': 'Продольный разрез рудника' },
    S('defs', {},
      S('pattern', { id: `${uid}-backfill`, width: 5, height: 5, patternUnits: 'userSpaceOnUse', patternTransform: 'rotate(45)' },
        S('rect', { width: 5, height: 5, fill: '#0f151c' }),
        S('line', { x1: 0, y1: 0, x2: 0, y2: 5, stroke: '#2a3644', 'stroke-width': 1.6 })),
      S('pattern', { id: `${uid}-blast`, width: 6, height: 6, patternUnits: 'userSpaceOnUse', patternTransform: 'rotate(-45)' },
        S('line', { x1: 0, y1: 0, x2: 0, y2: 6, stroke: stopeColor('awaiting_blast'), 'stroke-opacity': 0.6, 'stroke-width': 2.4 }))),
    sheet);
  const tools = el('div', { class: 'sx-tools' },
    el('button', { type: 'button', title: 'Отдалить', 'aria-label': 'Отдалить', text: '−', onclick: () => viewport.zoomBy(1 / 1.5) }),
    el('button', { type: 'button', title: 'Приблизить', 'aria-label': 'Приблизить', text: '+', onclick: () => viewport.zoomBy(1.5) }),
    el('button', { type: 'button', title: 'Показать разрез целиком', text: 'Весь разрез', onclick: () => viewport.reset() }));
  root.append(svg, tools);
  container.append(root);
  const card = createCard(root);
  const measure = createMeasure(getComputedStyle(root).fontFamily || 'sans-serif');

  let L = null;                  // layout of the current build
  let layers = {};
  let handlers = new Map();      // thing id -> functions (thing, state, first)
  let stateFns = [];             // functions (state, first)
  let registry = new Map();      // thing id -> [x, y] on the sheet
  let elements = new Map();      // thing id -> elements that carry data-thing
  let selectRing = null;
  let lastState = null;
  let selected = null;
  let hovered = null;
  let builtFor = '';
  let frame = 0;
  let disposed = false;
  const tokens = new Map();      // thing id -> last state token, for change pulses

  const viewport = createViewport(svg, sheet, {
    onMove: () => card.hide(),
    onClick: (event) => {
      const hit = document.elementFromPoint(event.clientX, event.clientY);
      const node = hit && hit.closest ? hit.closest('[data-thing]') : null;
      if (!node || !root.contains(node)) return;
      const thingId = node.getAttribute('data-thing');
      select(thingId, false);
      container.dispatchEvent(new CustomEvent('sekis:select', { bubbles: true, detail: { thingId } }));
    },
  });

  function pulse(x, y, extra) {
    if (!L) return;
    const ring = S('circle', { class: `sx-pulse ${extra || ''}`, cx: x, cy: y, r: L.F * 0.9 });
    layers.over.append(ring);
    setTimeout(() => ring.remove(), 1900);
  }

  function rebuild() {
    const cw = root.clientWidth;
    const ch = root.clientHeight;
    if (cw < 60 || ch < 60) return;         // hidden by the view switch; built when shown
    builtFor = `${cw}x${ch}`;
    L = computeLayout(cw, ch, M, measure);
    handlers = new Map();
    stateFns = [];
    registry = new Map();
    elements = new Map();
    layers = {};
    sheet.replaceChildren();
    sheet.style.fontSize = `${L.F.toFixed(2)}px`;
    sheet.style.setProperty('--u', (L.F / 9.5).toFixed(3));
    for (const name of LAYERS) {
      layers[name] = S('g', { class: `sx-layer-${name}` });
      sheet.append(layers[name]);
    }
    const ctx = {
      L, M, layers, measure, uid, sky: [], pulse,
      id: (name) => NS + name,
      on(thingId, fn) {
        if (!handlers.has(thingId)) handlers.set(thingId, []);
        handlers.get(thingId).push(fn);
      },
      onState: (fn) => stateFns.push(fn),
      reg: (thingId, x, y) => registry.set(thingId, [x, y]),
      skyLabel(config) {
        const label = {
          ...config, lines: [config.sample[0], ''], nodes: null,
          set(first, second) {
            this.lines = [first, second];
            if (this.nodes) {
              setText(this.nodes[0], first);
              setText(this.nodes[1], second);
            }
          },
        };
        this.sky.push(label);
        return label;
      },
    };
    buildUnderground(ctx);
    buildUnits(ctx);
    buildSurface(ctx);
    buildTables(ctx);
    selectRing = S('circle', { class: 'sx-select', r: L.F * 1.45, visibility: 'hidden' });
    layers.over.append(selectRing);
    for (const node of sheet.querySelectorAll('[data-thing]')) {
      const thingId = node.getAttribute('data-thing');
      if (!elements.has(thingId)) elements.set(thingId, []);
      elements.get(thingId).push(node);
    }
    svg.setAttribute('viewBox', `0 0 ${cw} ${ch}`);
    svg.dataset.layout = L.variant;
    svg.dataset.scale = L.s.toFixed(3);
    svg.dataset.font = L.F.toFixed(2);
    viewport.setSheet(cw, ch, L.W, L.H, L.fit);
    hovered = null;
    card.hide();
    if (lastState) apply(lastState, true);
    markSelection(true);
  }

  function apply(state, first) {
    for (const [thingId, fns] of handlers) {
      const thing = state.things[thingId];
      if (!thing || !thing.f) continue;
      for (const fn of fns) {
        try {
          fn(thing, state, first);
        } catch (error) {
          console.error('section2d', thingId, error);
        }
      }
    }
    for (const fn of stateFns) {
      try {
        fn(state, first);
      } catch (error) {
        console.error('section2d', error);
      }
    }
    card.refresh(state);
    markSelection(first);
  }

  /** A short ring where a twin changed its state, so that a scenario effect is noticed. */
  function notePulses(state, quiet) {
    let budget = MAX_PULSES;
    for (const [thingId, thing] of Object.entries(state.things)) {
      const token = thing.f && typeof thing.f.state === 'string' ? thing.f.state : null;
      if (token === null) continue;
      const before = tokens.get(thingId);
      tokens.set(thingId, token);
      if (quiet || before === undefined || before === token || budget <= 0) continue;
      if (MOBILE.has(thing.kind) && before !== 'parked' && token !== 'parked') continue;
      const at = registry.get(thingId);
      if (!at) continue;
      budget -= 1;
      pulse(at[0], at[1]);
    }
  }

  function markSelection(instant) {
    for (const node of sheet.querySelectorAll('.sel')) {
      if (node.getAttribute('data-thing') !== selected) node.classList.remove('sel');
    }
    if (!selectRing) return;
    const at = selected ? registry.get(selected) : null;
    const kind = selected && lastState && lastState.things[selected] ? lastState.things[selected].kind : M.kinds[selected];
    for (const node of (selected && elements.get(selected)) || []) node.classList.add('sel');
    if (!at || !RINGED.has(kind)) {
      selectRing.setAttribute('visibility', 'hidden');
      return;
    }
    if (instant || selectRing.getAttribute('visibility') === 'hidden') {
      selectRing.style.transition = 'none';
      selectRing.style.transform = `translate(${at[0].toFixed(1)}px, ${at[1].toFixed(1)}px)`;
      selectRing.getBoundingClientRect();
      selectRing.style.transition = '';
    } else {
      selectRing.style.transform = `translate(${at[0].toFixed(1)}px, ${at[1].toFixed(1)}px)`;
    }
    selectRing.setAttribute('visibility', 'visible');
  }

  function select(thingId, reveal) {
    selected = thingId || null;
    if (!L) return;
    markSelection(true);
    const at = selected ? registry.get(selected) : null;
    if (at && reveal) {
      viewport.reveal(at[0], at[1]);
      pulse(at[0], at[1], 'locate');
    }
  }

  function setHover(thingId) {
    if (thingId === hovered) return;
    for (const node of (hovered && elements.get(hovered)) || []) node.classList.remove('hl');
    hovered = thingId;
    for (const node of (hovered && elements.get(hovered)) || []) node.classList.add('hl');
  }

  function onPointerMove(event) {
    if (viewport.dragging || event.pointerType === 'touch') {
      setHover(null);
      card.hide();
      return;
    }
    const node = event.target.closest ? event.target.closest('[data-thing]') : null;
    const thingId = node ? node.getAttribute('data-thing') : null;
    setHover(thingId);
    if (thingId && lastState) card.show(thingId, lastState, event.clientX, event.clientY);
    else card.hide();
  }

  function onPointerLeave() {
    setHover(null);
    card.hide();
  }

  svg.addEventListener('pointermove', onPointerMove);
  svg.addEventListener('pointerleave', onPointerLeave);

  const observer = 'ResizeObserver' in window ? new ResizeObserver(() => {
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(() => {
      if (!disposed && `${root.clientWidth}x${root.clientHeight}` !== builtFor) rebuild();
    });
  }) : null;
  if (observer) observer.observe(root);
  rebuild();

  return {
    update(state) {
      if (disposed || !state || typeof state.things !== 'object') return;
      const quiet = !lastState;
      lastState = state;
      if (!L || `${root.clientWidth}x${root.clientHeight}` !== builtFor) rebuild();
      else apply(state, false);
      notePulses(state, quiet || !L);
    },
    focus(thingId) {
      if (!disposed) select(thingId, true);
    },
    dispose() {
      disposed = true;
      cancelAnimationFrame(frame);
      if (observer) observer.disconnect();
      viewport.dispose();
      svg.removeEventListener('pointermove', onPointerMove);
      svg.removeEventListener('pointerleave', onPointerLeave);
      root.remove();
    },
  };
}
