// DOM chrome of the scene: its own style sheet (scoped by the s3d- prefix; the
// colours are the page tokens), the camera preset bar (with the grade and the
// «Снимок» switches and the zoom buttons), the legend line, the
// attribution of the surface data (required by the licences wherever the data
// is shown), the debug overlay and the message shown when the graphics context
// is lost.

import { STOPE_ORDER, VEHICLE_MARKS, stateLabel, stopeColor } from '../panels/dict.js';
import { el, fmt, setText } from '../panels/format.js';
import { GRADE_MAX, GRADE_MIN } from './palette.js';

const CSS = `
.s3d-root { position: absolute; inset: 0; overflow: hidden; background: #0a0e13; touch-action: none;
  font-family: var(--font, system-ui, sans-serif);
  user-select: none; -webkit-user-select: none; cursor: grab; }
.s3d-root[data-hover="1"] { cursor: pointer; }
.s3d-root[data-drag="1"] { cursor: grabbing; }
.s3d-root canvas { position: absolute; left: 0; top: 0; width: 100%; height: 100%; display: block; }
.s3d-labels { position: absolute; inset: 0; overflow: hidden; pointer-events: none; }
.s3d-tag { padding-bottom: 9px; pointer-events: none; }
.s3d-tag::after { content: ""; position: absolute; left: 50%; bottom: 1px; width: 1px; height: 8px;
  background: var(--line-strong, #3a4959); }
.s3d-tag[data-align="right"] { padding: 0 0 0 12px; }
.s3d-tag[data-dim="1"] { opacity: 0.55; }
.s3d-tag[data-align="right"]::after { left: 2px; bottom: 50%; width: 10px; height: 1px; }
.s3d-label { position: relative; padding: 2px 7px 3px 8px; border-radius: 3px; white-space: nowrap;
  background: rgba(13, 19, 26, 0.84); border: 1px solid var(--line-strong, #3a4959);
  border-left: 2px solid var(--tone, var(--idle, #5d6c80));
  font: 10.5px/1.25 var(--font, system-ui, sans-serif); color: var(--text, #e9eef4);
  pointer-events: auto; cursor: pointer; }
.s3d-label b { display: block; font-weight: 600; }
.s3d-label span { display: block; font-size: 10px; color: var(--text-2, #a8b5c3); }
.s3d-label:hover { background: var(--surface-3, #202b37); }
.s3d-label[data-tone="ok"] { --tone: var(--ok, #3ec79a); }
.s3d-label[data-tone="warn"] { --tone: var(--warn, #f2dc5c); }
.s3d-label[data-tone="fail"] { --tone: var(--fail, #dc4046); }
.s3d-label[data-tone="planned"] { --tone: var(--planned, #8796ab); border-style: dashed; border-left-style: solid; }
.s3d-label[data-tone="idle"] { --tone: var(--idle, #5d6c80); }
.s3d-label[data-tone="flood"] { --tone: var(--flood, #58a6e6); }
.s3d-label[data-tone="info"] { --tone: var(--info, #9fb3c8); }
.s3d-label[data-tone="place"] { --tone: transparent; background: rgba(13, 19, 26, 0.62);
  border-color: rgba(233, 238, 244, 0.22); font-style: italic; cursor: default; }
.s3d-label[data-tone="place"]:hover { background: rgba(13, 19, 26, 0.62); }
.s3d-label[data-selected="1"] { background: var(--surface-3, #202b37); border-color: var(--text, #e9eef4);
  border-left-color: var(--tone, var(--text, #e9eef4)); }
.s3d-bar { position: absolute; left: 8px; top: 8px; right: 8px; display: flex; flex-wrap: wrap; gap: 6px;
  pointer-events: none; }
.s3d-seg { display: inline-flex; border: 1px solid var(--line-strong, #3a4959); border-radius: 4px;
  overflow: hidden; background: rgba(18, 25, 33, 0.88); pointer-events: auto; }
.s3d-seg button { padding: 3px 9px; background: transparent; border: 0;
  border-left: 1px solid var(--line-strong, #3a4959); font: 11.5px/1.4 var(--font, system-ui, sans-serif);
  color: var(--text-2, #a8b5c3); cursor: pointer; white-space: nowrap; }
.s3d-seg button:first-child { border-left: 0; }
.s3d-seg button:hover { background: var(--surface-2, #18212b); color: var(--text, #e9eef4); }
.s3d-seg button[aria-pressed="true"] { background: var(--surface-3, #202b37); color: var(--text, #e9eef4);
  font-weight: 600; }
.s3d-legend { position: absolute; left: 6px; bottom: 21px; max-width: calc(100% - 12px); display: flex;
  flex-wrap: wrap; gap: 1px 11px; padding: 2px 6px; border-radius: 3px; background: rgba(10, 14, 19, 0.78);
  font: 10.5px/1.5 var(--font, system-ui, sans-serif); color: var(--text-3, #73839a); pointer-events: none; }
.s3d-legend span { white-space: nowrap; }
.s3d-legend i { display: inline-block; width: 9px; height: 9px; margin-right: 4px; border-radius: 2px;
  vertical-align: -1px; }
.s3d-legend i.s3d-ramp { width: 54px; }
.s3d-legend i.s3d-ring { background: transparent; border: 2px solid; border-radius: 50%; }
.s3d-legend i.s3d-dash { background: transparent; border: 1px dashed; border-radius: 0; }
.s3d-credit { position: absolute; left: 6px; bottom: 3px; max-width: calc(100% - 12px); padding: 0 6px;
  border-radius: 3px; background: rgba(10, 14, 19, 0.7); font: 9.5px/1.6 var(--font, system-ui, sans-serif);
  color: var(--text-3, #73839a); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.s3d-debug { position: absolute; right: 8px; top: 8px; padding: 3px 7px; border-radius: 3px;
  background: rgba(18, 25, 33, 0.9); border: 1px solid var(--line, #273341); white-space: pre;
  font: 10.5px/1.45 var(--mono, monospace); color: var(--text-2, #a8b5c3); pointer-events: none; }
.s3d-note { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
  background: rgba(10, 14, 19, 0.8); color: var(--text-2, #a8b5c3); font: 13px var(--font, system-ui, sans-serif); }
@media (max-width: 760px) { .s3d-legend { display: none; } .s3d-credit { white-space: normal; } }
`;

// Attribution of the terrain (Copernicus DEM), the image (Sentinel-2) and the
// map data (OpenStreetMap); see model/terrain/ATTRIBUTION.md.
export const CREDIT = '© DLR e.V. 2010–2014, © Airbus DS 2014–2018, Copernicus · '
  + 'Contains modified Copernicus Sentinel data 2026 · © OpenStreetMap contributors';

export const PRESETS = [
  ['mine', 'Рудник'], ['declines', 'Уклоны'], ['vent', 'Вентиляция'], ['water', 'Водоотлив'],
  ['plant', 'Фабрика и хвосты'],
];

/**
 * Build the chrome inside `root`. Handlers: onPreset(id), onGrade(on), onPhoto(on), onZoom(direction).
 */
export function createOverlay(root, palette, { onPreset, onGrade, onPhoto, onZoom }) {
  const style = el('style', { text: CSS });
  const swallow = (node) => {
    // Keep clicks on the chrome away from the orbit controls and the picker.
    for (const type of ['pointerdown', 'pointerup', 'wheel', 'dblclick']) {
      node.addEventListener(type, (event) => event.stopPropagation());
    }
    return node;
  };

  const presetButtons = PRESETS.map(([id, text]) => el('button', {
    type: 'button', 'aria-pressed': 'false', dataset: { preset: id }, text, onclick: () => onPreset(id),
  }));
  const gradeButton = el('button', {
    type: 'button', 'aria-pressed': 'false', text: 'Содержание золота',
    title: 'Раскрасить очистные блоки по содержанию золота в руде',
    onclick: () => onGrade(gradeButton.getAttribute('aria-pressed') !== 'true'),
  });
  // The surface is drawn from map data by default; the image is the evidence of the real place.
  const photoButton = el('button', {
    type: 'button', 'aria-pressed': 'false', text: 'Снимок',
    title: 'Показать на рельефе спутниковый снимок Sentinel-2 (30.09.2026, 10 м) вместо условной поверхности',
    onclick: () => onPhoto(photoButton.getAttribute('aria-pressed') !== 'true'),
  });
  const bar = el('div', { class: 's3d-bar' },
    swallow(el('div', { class: 's3d-seg', role: 'group', 'aria-label': 'Ракурс' }, presetButtons)),
    swallow(el('div', { class: 's3d-seg' }, gradeButton)),
    swallow(el('div', { class: 's3d-seg' }, photoButton)),
    swallow(el('div', { class: 's3d-seg', role: 'group', 'aria-label': 'Масштаб' },
      el('button', { type: 'button', text: '+', title: 'Приблизить', 'aria-label': 'Приблизить', onclick: () => onZoom(1) }),
      el('button', { type: 'button', text: '−', title: 'Отдалить', 'aria-label': 'Отдалить', onclick: () => onZoom(-1) }))));

  const swatch = (color, text, cls) => el('span', null,
    el('i', { class: cls || null, style: cls ? `border-color: ${color}` : `background: ${color}` }), text);
  const stateLegend = el('span', { style: 'display: contents' },
    el('span', { text: 'Блоки:' }),
    STOPE_ORDER.map((state) => swatch(stopeColor(state), stateLabel(state, 'stope'),
      state === 'planned' ? 's3d-dash' : null)));
  const gradeLegend = el('span', { style: 'display: contents', hidden: true },
    el('span', { text: 'Блоки, содержание золота:' }),
    el('span', null, fmt(GRADE_MIN, 1) + ' ',
      el('i', { class: 's3d-ramp', style: `background: linear-gradient(90deg, ${palette.cssGrade[0]}, ${palette.cssGrade[1]})` }),
      fmt(GRADE_MAX, 1) + ' г/т'));
  const legend = el('div', { class: 's3d-legend', 'aria-hidden': 'true' },
    stateLegend, gradeLegend,
    el('span', { text: 'Самосвалы:' }),
    swatch(palette.cssScene.truckLoaded, 'с рудой'),
    swatch(palette.cssScene.truckEmpty, 'порожний'),
    swatch(palette.css.warn, VEHICLE_MARKS.held, 's3d-ring'),
    swatch(palette.css.fail, VEHICLE_MARKS.repair, 's3d-ring'),
    swatch(palette.css.planned, 'проект', 's3d-dash'));
  // Shown only while the condition holds, so that the tint explains itself.
  const airAlert = el('span', { hidden: true }, el('i', { style: `background: ${palette.css.warn}` }),
    'горизонты: не хватает воздуха');
  const floodAlert = el('span', { hidden: true }, el('i', { style: `background: ${palette.css.flood}` }),
    'вода в выработках');
  legend.append(airAlert, floodAlert);

  const credit = el('div', { class: 's3d-credit', text: CREDIT, title: CREDIT });
  swallow(credit);

  root.append(style, bar, legend, credit);

  let debug = null;
  let note = null;
  return {
    setPreset(id) {
      for (const button of presetButtons) button.setAttribute('aria-pressed', String(button.dataset.preset === id));
    },
    setGrade(on) {
      gradeButton.setAttribute('aria-pressed', String(on));
      stateLegend.hidden = on;
      gradeLegend.hidden = !on;
    },
    setPhoto(on) {
      photoButton.setAttribute('aria-pressed', String(on));
    },
    setAlerts({ air, flood }) {
      if (airAlert.hidden === air) airAlert.hidden = !air;
      if (floodAlert.hidden === flood) floodAlert.hidden = !flood;
    },
    /** Rectangles (in root pixels) the labels must keep clear of. */
    reserved() {
      const base = root.getBoundingClientRect();
      return [...bar.children, legend, credit].map((node) => {
        const r = node.getBoundingClientRect();
        return [r.left - base.left, r.top - base.top, r.width, r.height];
      }).filter((r) => r[2] > 0 && r[3] > 0);
    },
    debug(text) {
      if (!debug) {
        debug = el('div', { class: 's3d-debug' });
        root.append(debug);
      }
      setText(debug, text);
    },
    note(text) {
      if (note) note.remove();
      note = text ? el('div', { class: 's3d-note', role: 'status', text }) : null;
      if (note) root.append(note);
    },
  };
}
