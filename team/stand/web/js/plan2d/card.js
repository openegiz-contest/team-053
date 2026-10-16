// Hover card of the plan: kind, name, state and the key values of the twin
// under the pointer, then what the plan position rests on. A click opens the
// full twin card of the page.

import { KEY_FEATURES, featureLabel, featureText, kindLabel, thingState } from '../panels/dict.js';
import { append, clear, el } from '../panels/format.js';

// Values shown after the key features of the kind.
const MORE = {
  decline: ['bottom_elevation', 'loaded_trips_today', 'avg_cycle_min'],
  main_fan: ['pressure'],
  pump_station: ['inflow_m3h', 'pumps_running', 'hours_to_overflow'],
  haul_truck: ['speed', 'tonnes_today'],
  plant: ['capacity_ktpa', 'lines_running'],
  plant_line: ['milled_today_t'],
  rom_stockpile: ['inflow_tph', 'outflow_tph'],
  tailings_facility: ['stored_t', 'reclaim_m3h'],
  tailings_dam: ['stored_t', 'inflow_tph'],
  monitoring_point: ['tss_mgl'],
  settling_pond: ['tss_in_mgl'],
  stope: ['drilled_pct'],
};

export function createCard(root, extra = () => []) {
  const node = el('div', { class: 'pl-card', hidden: true });
  root.append(node);
  let shown = null;
  let signature = '';

  function render(thingId, thing, things) {
    const state = thingState(thing);
    const units = (thing.attrs && thing.attrs.units) || {};
    const keys = [...(KEY_FEATURES[thing.kind] || []), ...(MORE[thing.kind] || [])]
      .filter((key, index, all) => key in thing.f && all.indexOf(key) === index);
    const rows = keys.map((key) => [featureLabel(key, thing.kind),
      featureText(key, thing.f[key], { kind: thing.kind, unit: units[key], things })]);
    const notes = extra(thingId);
    const next = JSON.stringify([thing.name, state, rows, notes]);
    if (next === signature) return;
    signature = next;
    append(clear(node), [
      el('div', { class: 'pl-card-kind', text: kindLabel(thing.kind) }),
      el('div', { class: 'pl-card-name', text: thing.name || '' }),
      el('div', { class: 'pl-card-state', 'data-tone': state.tone }, el('i', {}), state.label),
      el('dl', {}, rows.map(([label, value]) => el('div', { style: 'display: contents' },
        el('dt', { text: label }), el('dd', { text: value })))),
      notes.length ? el('div', { class: 'pl-card-note', text: notes.join(' · ') }) : null,
      el('div', { class: 'pl-card-hint', text: 'Щелчок — карточка двойника' })]);
  }

  function place(clientX, clientY) {
    const box = root.getBoundingClientRect();
    const w = node.offsetWidth;
    const h = node.offsetHeight;
    let x = clientX - box.left + 16;
    let y = clientY - box.top + 16;
    if (x + w > box.width - 4) x = clientX - box.left - w - 14;
    if (y + h > box.height - 4) y = clientY - box.top - h - 14;
    node.style.transform = `translate(${Math.max(4, x).toFixed(0)}px, ${Math.max(4, y).toFixed(0)}px)`;
  }

  return {
    show(thingId, state, clientX, clientY) {
      const thing = state && state.things[thingId];
      if (!thing || !thing.f) {
        this.hide();
        return;
      }
      shown = thingId;
      render(thingId, thing, state.things);
      node.hidden = false;
      place(clientX, clientY);
    },
    /** Keep the values of the open card live. */
    refresh(state) {
      if (shown && state && state.things[shown]) render(shown, state.things[shown], state.things);
    },
    hide() {
      shown = null;
      signature = '';
      node.hidden = true;
    },
  };
}
