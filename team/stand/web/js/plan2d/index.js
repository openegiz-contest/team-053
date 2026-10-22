// Plan of the mine («План»): a top-down map on the Sentinel-2 image with crisp
// vector overlays and live twin data, like a dispatcher's map.
// View contract (spec 4.6): mount(container, geometry) -> { update, focus, dispose };
// update(state) receives GET /api/state every 2 s; a click on an object sends
// the bubbling 'sekis:select' event with detail { thingId } from the container.
//
// Files: model.js reads the geometry (and the OSM copy osm.js), draw.js draws
// the world layers in metres, marks.js the point symbols and units.js the
// trucks in screen pixels, labels.js places the labels, furniture.js holds the
// grid, scale, north arrow, legend and attribution, viewport.js zooms and pans,
// card.js is the hover card.
//
// Address options of the page: ?plan=<x>,<z>,<px per metre> opens the plan at
// that centre and scale; ?planhide=image,underground starts with those layers
// hidden; the legend starts collapsed (it would cover the right edge of the
// mine), ?planshow=legend opens it.

import { NS, stateTone, unitCounts } from '../panels/dict.js';
import { el, fmt, isNum } from '../panels/format.js';
import { S, createMeasure } from './svg.js';
import { readModel } from './model.js';
import { buildBase, buildSurface, buildUnderground } from './draw.js';
import { buildMarks } from './marks.js';
import { buildUnits } from './units.js';
import { createLabels } from './labels.js';
import { ATTRIBUTION, createGrid, createLegend, createScale, northArrow, utmOffsets } from './furniture.js';
import { createViewport } from './viewport.js';
import { createCard } from './card.js';

const POLL_MS = 2000;
const FRAME_MS = 50;          // the trucks move at up to 20 frames per second
const MAX_PULSES = 10;
const MOBILE = new Set(['haul_truck', 'lhd', 'drill_rig']);
// The least scale a focused thing is shown at, px per metre.
const FOCUS_SCALE = { haul_truck: 1.4, lhd: 1.4, drill_rig: 1.4, shaft: 1.1, raise: 1.1, main_fan: 1.1,
  monitoring_point: 1, stope: 1.3, level: 0.9, decline: 0.9, pump_station: 1.3, plant_line: 1.6 };
let mounts = 0;

function ensureCss() {
  const id = 'pl-style';
  let link = document.getElementById(id);
  if (link && link.sheet) return Promise.resolve();
  if (!link) {
    link = document.createElement('link');
    link.id = id;
    link.rel = 'stylesheet';
    link.href = new URL('./plan.css', import.meta.url).href;
    document.head.append(link);
  }
  return new Promise((resolve) => {
    link.addEventListener('load', resolve, { once: true });
    link.addEventListener('error', resolve, { once: true });
    setTimeout(resolve, 2000);
  });
}

/** Address options: the starting view and the hidden layers. */
function addressOptions() {
  const params = new URLSearchParams(location.search);
  const at = (params.get('plan') || '').split(',').map(Number);
  return {
    view: at.length === 3 && at.every(Number.isFinite) && at[2] > 0 ? { cx: at[0], cz: at[1], k: at[2] } : null,
    hide: new Set((params.get('planhide') || '').split(',').filter(Boolean)),
    show: new Set((params.get('planshow') || '').split(',').filter(Boolean)),
  };
}

export async function mount(container, geometry) {
  await ensureCss();
  mounts += 1;
  const uid = `pl${mounts}`;
  const M = readModel(geometry);
  const options = addressOptions();

  if (getComputedStyle(container).position === 'static') container.style.position = 'relative';
  const root = el('div', { class: 'pl-root' });
  const layers = {
    base: S('g', { class: 'pl-world' }),
    grid: S('g', { class: 'pl-gridlayer' }),
    land: S('g'), tailings: S('g'), water: S('g'), pit: S('g'), roads: S('g'), pipes: S('g'), plant: S('g'),
    under: S('g', { class: 'pl-under pl-under-world' }),
    underMarks: S('g', { class: 'pl-under' }),
    marks: S('g'), units: S('g'), labels: S('g', { class: 'pl-labels' }), over: S('g', { class: 'pl-over' }),
    furniture: S('g'),
  };
  const vec = S('g', { class: 'pl-world' },
    layers.land, layers.tailings, layers.water, layers.pit, layers.roads, layers.pipes, layers.plant, layers.under);
  const svg = S('svg', { class: 'pl-svg', role: 'img', 'aria-label': 'План рудника на космическом снимке' },
    S('defs', {},
      S('pattern', { id: `${uid}-heap`, width: 6, height: 6, patternUnits: 'userSpaceOnUse', patternTransform: 'rotate(45)' },
        S('line', { x1: 0, y1: 0, x2: 0, y2: 6, class: 'pl-hatch' }))),
    layers.base, layers.grid, vec, layers.underMarks, layers.marks, layers.units, layers.labels, layers.over, layers.furniture);

  // ------------------------------------------------------------ the tools
  const chip = (layer, text, title) => el('button', {
    type: 'button', class: 'pl-chip', 'aria-pressed': 'true', dataset: { layer }, title, text,
  });
  const imageChip = chip('image', 'Снимок', 'Показать или скрыть космический снимок');
  const underChip = chip('under', 'Подземная часть', 'Показать или скрыть выработки в плане (схема)');
  const go = (name, text) => el('button', { type: 'button', class: 'pl-go', dataset: { go: name }, text });
  const bar = el('div', { class: 'pl-bar' },
    imageChip, underChip, el('span', { class: 'pl-sep', 'aria-hidden': 'true' }),
    go('pit', 'Карьер'), go('plant', 'Фабрика'), go('tailings', 'Хвостохранилище'));
  const zoomTools = el('div', { class: 'pl-zoom' },
    el('button', { type: 'button', title: 'Отдалить', 'aria-label': 'Отдалить', text: '−', onclick: () => viewport.zoomBy(1 / 1.6) }),
    el('button', { type: 'button', title: 'Приблизить', 'aria-label': 'Приблизить', text: '+', onclick: () => viewport.zoomBy(1.6) }),
    el('button', { type: 'button', title: 'Показать карьер, фабрику и хвостохранилище', text: 'Весь план', onclick: () => viewport.fit(M.home) }));
  const legend = createLegend(() => schedule(true));
  const north = northArrow();
  const attribution = el('div', { class: 'pl-attr', text: ATTRIBUTION });
  const status = el('div', { class: 'pl-status', 'aria-live': 'polite' });
  const gridNote = el('div', { class: 'pl-utm' });
  const right = el('div', { class: 'pl-right' }, north, legend.node);
  bar.append(status);
  root.append(svg, bar, right, zoomTools, gridNote, attribution);
  container.append(root);

  const card = createCard(root, (thingId) => cardNotes(thingId));
  const measure = createMeasure(getComputedStyle(root).fontFamily || 'sans-serif');
  const labels = createLabels(layers.labels, measure);
  const grid = createGrid(layers.grid, utmOffsets(geometry), M.image.extent);
  const scale = createScale(layers.furniture);

  // ------------------------------------------------------------- the build
  const handlers = new Map();      // thing id -> functions (thing, state, first)
  const marks = [];
  const extra = [];                // [thing id, element] drawn for a thing without data-thing
  const ctx = {
    M, uid, layers, state: null,
    on(thingId, fn) {
      if (!handlers.has(thingId)) handlers.set(thingId, []);
      handlers.get(thingId).push(fn);
    },
    thing: (thingId, node) => extra.push([thingId, node]),
    label: (spec) => labels.add(spec),
    flowLabel: (points, name, fraction) => labels.addFlow(points, name, fraction),
    mark: (spec) => marks.push(spec),
  };
  buildBase(ctx);
  buildSurface(ctx);
  buildUnderground(ctx);
  buildMarks(ctx);
  const units = buildUnits(ctx, POLL_MS);
  const selectRing = S('circle', { class: 'pl-select', r: 12, visibility: 'hidden' });
  layers.over.append(selectRing);

  const elements = new Map();      // thing id -> elements that show its hover and selection
  const pairs = [...svg.querySelectorAll('[data-thing]')].map((node) => [node.getAttribute('data-thing'), node]);
  for (const [thingId, node] of [...pairs, ...extra]) {
    if (!elements.has(thingId)) elements.set(thingId, []);
    if (!elements.get(thingId).includes(node)) elements.get(thingId).push(node);
  }
  const bindable = [...svg.querySelectorAll('[data-bind]')].filter((node) => node.getAttribute('data-bind'));

  let lastState = null;
  let applied = false;
  let selected = null;
  let hovered = null;
  let pendingFocus = null;
  let sized = false;
  let disposed = false;
  let frame = 0;
  let animFrame = 0;
  let lastAnim = 0;
  let binding = '';
  const tokens = new Map();

  // --------------------------------------------------------------- layers
  function setLayer(layer, on) {
    const button = layer === 'image' ? imageChip : underChip;
    button.setAttribute('aria-pressed', String(on));
    root.classList.toggle(layer === 'image' ? 'no-image' : 'no-under', !on);
    schedule(true);
  }
  const layerOn = (layer) => (layer === 'image' ? imageChip : underChip).getAttribute('aria-pressed') === 'true';
  bar.addEventListener('click', (event) => {
    const button = event.target.closest('button');
    if (!button) return;
    if (button.dataset.layer) setLayer(button.dataset.layer, !layerOn(button.dataset.layer));
    if (button.dataset.go) viewport.fit(M.presets[button.dataset.go] || M.home);
  });
  if (options.hide.has('image')) setLayer('image', false);
  if (options.hide.has('underground')) setLayer('under', false);

  // ------------------------------------------------------------- the view
  const viewport = createViewport(svg, {
    extent: M.image.extent,
    // The bar, the legend and the bottom line cover the edges of the view.
    insets: () => {
      const base = root.getBoundingClientRect();
      const legendOpen = legend.node.querySelector('[aria-expanded="true"]');
      const r = legendOpen ? base.right - right.getBoundingClientRect().left : 50;
      return { l: 8, r: Math.max(50, r), t: bar.getBoundingClientRect().bottom - base.top, b: 34 };
    },
    onChange: () => {
      card.hide();
      schedule(true);
    },
    onClick: (event) => {
      const node = pick(event);
      if (!node) return;
      const thingId = node.getAttribute('data-thing');
      select(thingId);
      container.dispatchEvent(new CustomEvent('sekis:select', { bubbles: true, detail: { thingId } }));
    },
  });

  const toScreen = (x, z) => [viewport.tx + viewport.k * x, viewport.ty + viewport.k * z];

  /** Boxes of the HTML furniture in the coordinates of the view, which labels avoid. */
  function furnitureBoxes() {
    const base = root.getBoundingClientRect();
    return [bar, right, zoomTools, attribution, gridNote].map((node) => {
      const r = node.getBoundingClientRect();
      return r.width ? [r.left - base.left - 4, r.top - base.top - 4, r.right - base.left + 4, r.bottom - base.top + 4] : null;
    }).filter(Boolean);
  }

  function pointOf(thingId, now) {
    if (MOBILE.has(M.kinds[thingId])) return units.at(thingId, now);
    const mark = marks.find((item) => item.id === thingId);
    if (mark) return mark.at;
    return M.anchors[thingId] || null;
  }

  function placeRing(now) {
    const kind = M.kinds[selected];
    const box = selected ? M.boxes[selected] : null;
    const at = selected && (!box || MOBILE.has(kind)) ? pointOf(selected, now) : null;
    const hiddenUnder = selected && !layerOn('under') && (M.under[selected] || units.isUnder(selected));
    if (!at || hiddenUnder || kind === 'level' || kind === 'stope') {
      selectRing.setAttribute('visibility', 'hidden');
      return;
    }
    const mark = marks.find((item) => item.id === selected);
    const [sx, sy] = toScreen(at[0], at[1]);
    selectRing.setAttribute('transform', `translate(${(sx + ((mark && mark.dx) || 0)).toFixed(1)} ${sy.toFixed(1)})`);
    selectRing.setAttribute('visibility', 'visible');
  }

  /** Lay out everything for the current view (labels too). */
  function render() {
    frame = 0;
    if (disposed) return;
    const w = root.clientWidth;
    const h = root.clientHeight;
    if (w < 60 || h < 60) return;      // hidden by the view switch; laid out when shown
    if (!sized || w !== viewport.size.w || h !== viewport.size.h) {
      viewport.resize(w, h);
      if (!sized) {
        sized = true;
        legend.open(options.show.has('legend') && h >= 640);
        if (options.view) viewport.fit(boxAround(options.view), true, 0);
        else viewport.fit(M.home, true);
        if (pendingFocus) {
          const id = pendingFocus;
          pendingFocus = null;
          focusOn(id, true);
        }
      }
    }
    const k = viewport.k;
    const transform = `matrix(${k.toFixed(5)} 0 0 ${k.toFixed(5)} ${viewport.tx.toFixed(1)} ${viewport.ty.toFixed(1)})`;
    layers.base.setAttribute('transform', transform);
    vec.setAttribute('transform', transform);
    root.dataset.zoom = k >= 1.6 ? 'near' : k >= 0.6 ? 'mid' : 'far';
    const size = viewport.size;
    grid.layout(viewport.visible(), k, toScreen, size);
    gridNote.textContent = `Сетка UTM 44N (EPSG:32644), шаг ${fmt(grid.step)} м`;
    const showUnder = layerOn('under');
    const obstacles = [scale.layout(k, size), ...furnitureBoxes()];
    for (const mark of marks) {
      const [sx0, sy0] = toScreen(mark.at[0], mark.at[1]);
      const sx = sx0 + (mark.dx || 0);
      const sy = sy0 + (mark.dy || 0);
      if (mark.layout) {
        const box = mark.layout(sx, sy, k);
        if (box && (!mark.under || showUnder)) obstacles.push(box);
        continue;
      }
      mark.node.setAttribute('transform', `translate(${sx.toFixed(1)} ${sy.toFixed(1)})`);
      if (mark.r && (!mark.under || showUnder)) obstacles.push([sx - mark.r, sy - mark.r, sx + mark.r, sy + mark.r]);
    }
    const now = performance.now();
    units.layout(now, toScreen, k);
    const forced = new Set(binding ? bindable.filter((node) => node.classList.contains('bind'))
      .map((node) => node.getAttribute('data-thing')).filter(Boolean) : []);
    labels.place({ toScreen, k, size, obstacles, showUnder, selected, forced });
    placeRing(now);
  }

  function boxAround(view) {
    const w = viewport.size.w / view.k;
    const h = viewport.size.h / view.k;
    return [view.cx - w / 2, view.cz - h / 2, view.cx + w / 2, view.cz + h / 2];
  }

  function schedule(full) {
    if (disposed) return;
    if (full && !frame) frame = requestAnimationFrame(render);
    if (!animFrame) animFrame = requestAnimationFrame(animate);
  }

  /** The trucks between two samples: only the units and the selection ring move. */
  function animate(now) {
    animFrame = 0;
    if (disposed || !sized || root.clientWidth < 60) return;
    if (now - lastAnim < FRAME_MS) {
      animFrame = requestAnimationFrame(animate);
      return;
    }
    lastAnim = now;
    const moving = units.layout(now, toScreen, viewport.k);
    if (selected && MOBILE.has(M.kinds[selected])) placeRing(now);
    if (moving) animFrame = requestAnimationFrame(animate);
  }

  // ------------------------------------------------------ hover and click
  function pick(event) {
    const hit = document.elementFromPoint(event.clientX, event.clientY);
    const node = hit && hit.closest ? hit.closest('[data-thing]') : null;
    return node && root.contains(node) ? node : null;
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

  /** «Самосвалов в работе: 5 — на поверхности 2, под землёй 3» from the unit twins (unitCounts). */
  function fleetText(state) {
    const counts = unitCounts(state.things);
    if (!isNum(counts.fleet)) return '';
    let top = 0;
    let below = 0;
    for (const u of units.units) {
      const thing = state.things[u.id];
      const f = thing && thing.f;
      if (!u.truck || !f || f.state === 'parked' || f.state === 'planned' || f.state === 'maintenance') continue;
      const ground = isNum(f.pos_x) && isNum(f.pos_z) ? M.terrainAt(f.pos_x, f.pos_z) : null;
      if (ground !== null && isNum(f.pos_y) && f.pos_y < ground - 4) below += 1;
      else top += 1;
    }
    let text = `Самосвалов в работе: ${fmt(counts.inService)} — на поверхности ${fmt(top)}, под землёй ${fmt(below)}`;
    if (counts.held > 0) text += `, ждут воздуха ${fmt(counts.held)}`;
    if (counts.maintenance > 0) text += ` · в ремонте ${fmt(counts.maintenance)}`;
    return text;
  }

  /** What the plan position rests on, under the values of the hover card. */
  function cardNotes(thingId) {
    const notes = [];
    if (M.under[thingId]) notes.push('подземная выработка: положение в плане — схема');
    else if (MOBILE.has(M.kinds[thingId]) && units.isUnder(thingId)) notes.push('под землёй: положение в плане — схема');
    if (M.facility && thingId === M.facility.id && isNum(M.facility.distance)) {
      notes.push(`${fmt(M.facility.distance / 1000, 2)} км от рудника, азимут ${fmt(M.facility.bearing)}°`);
    }
    if (thingId === binding) notes.push('узкое место');
    return notes;
  }

  // ------------------------------------------------- selection and focus
  function markSelection() {
    for (const node of svg.querySelectorAll('.sel')) node.classList.remove('sel');
    for (const node of (selected && elements.get(selected)) || []) node.classList.add('sel');
  }

  function select(thingId) {
    selected = thingId || null;
    markSelection();
    schedule(true);
  }

  function focusOn(thingId, instant) {
    const kind = M.kinds[thingId];
    if ((M.under[thingId] || (MOBILE.has(kind) && units.isUnder(thingId))) && !layerOn('under')) setLayer('under', true);
    const box = M.boxes[thingId];
    const now = performance.now();
    if (box && !MOBILE.has(kind)) {
      // Zoom in so that the outline takes at least 40 % of the free view, with
      // its surroundings; never closer than the outline itself.
      const fit = viewport.fitOf(box, 40);
      const k = Math.min(fit.k, Math.max(viewport.k, fit.k * 0.4));
      const grow = fit.k / k;
      const [cx, cz] = [(box[0] + box[2]) / 2, (box[1] + box[3]) / 2];
      const hw = ((box[2] - box[0]) / 2) * grow;
      const hh = ((box[3] - box[1]) / 2) * grow;
      viewport.fit([cx - hw, cz - hh, cx + hw, cz + hh], instant);
    } else {
      const at = pointOf(thingId, now);
      if (at) viewport.centre(at[0], at[1], FOCUS_SCALE[kind] || 1, instant);
    }
    const at = pointOf(thingId, now);
    if (at) pulseAt(at, 'locate');
  }

  function pulseAt(at, extra) {
    const [sx, sy] = toScreen(at[0], at[1]);
    const ring = S('circle', { class: `pl-pulse ${extra || ''}`, cx: sx, cy: sy, r: 9 });
    layers.over.append(ring);
    setTimeout(() => ring.remove(), 1800);
  }

  // ----------------------------------------------------------- live data
  function apply(state) {
    const first = !applied;
    for (const [thingId, fns] of handlers) {
      const thing = state.things[thingId];
      if (!thing || !thing.f) continue;
      for (const fn of fns) {
        try {
          fn(thing, state, first);
        } catch (error) {
          console.error('plan2d', thingId, error);
        }
      }
    }
    applied = true;
    // The binding link, if it is a surface object, is outlined in the accent.
    const advisor = state.things[NS + 'advisor'];
    const enterprise = state.things[NS + 'enterprise'];
    const link = (advisor && advisor.f && advisor.f.binding_link) || (enterprise && enterprise.f && enterprise.f.binding_link) || '';
    if (link !== binding) {
      binding = link;
      root.dataset.binding = link;
      let any = false;
      for (const node of bindable) {
        const on = !!link && node.getAttribute('data-bind').split(' ').includes(link);
        node.classList.toggle('bind', on);
        any = any || on;
      }
      root.classList.toggle('has-bind', any);
    }
    const states = new Set();
    for (const stope of M.stopes) {
      const thing = state.things[stope.id];
      if (thing && thing.f && thing.f.state) states.add(thing.f.state);
    }
    legend.stopes(states);
    status.textContent = fleetText(state);
    // Exceeded monitoring points and flooded levels say so at once.
    for (const point of M.monitors) {
      const thing = state.things[point.id];
      root.classList.toggle(`alarm-${point.id.replace(/^.*:/, '')}`, !!(thing && thing.f && stateTone(thing.f.state, 'monitoring_point') === 'fail'));
    }
    card.refresh(state);
    markSelection();
  }

  /** A short ring where a twin changed its state, so that a scenario effect is noticed. */
  function notePulses(state, quiet) {
    let budget = MAX_PULSES;
    const now = performance.now();
    for (const [thingId, thing] of Object.entries(state.things)) {
      const token = thing.f && typeof thing.f.state === 'string' ? thing.f.state : null;
      if (token === null) continue;
      const before = tokens.get(thingId);
      tokens.set(thingId, token);
      if (quiet || before === undefined || before === token || budget <= 0) continue;
      if (MOBILE.has(thing.kind)) continue;
      if (M.under[thingId] && !layerOn('under')) continue;
      const at = pointOf(thingId, now);
      if (!at) continue;
      budget -= 1;
      pulseAt(at);
    }
  }

  const observer = 'ResizeObserver' in window ? new ResizeObserver(() => schedule(true)) : null;
  if (observer) observer.observe(root);
  schedule(true);

  return {
    update(state) {
      if (disposed || !state || typeof state.things !== 'object') return;
      const quiet = !lastState;
      lastState = state;
      ctx.state = state;
      apply(state);
      notePulses(state, quiet || !sized);
      schedule(true);
    },
    focus(thingId) {
      if (disposed || !thingId) return;
      select(thingId);
      if (!sized) {
        pendingFocus = thingId;
        return;
      }
      focusOn(thingId, false);
    },
    dispose() {
      disposed = true;
      cancelAnimationFrame(frame);
      cancelAnimationFrame(animFrame);
      if (observer) observer.disconnect();
      viewport.dispose();
      svg.removeEventListener('pointermove', onPointerMove);
      svg.removeEventListener('pointerleave', onPointerLeave);
      root.remove();
    },
  };
}

