// Stand page: owns fetching and hands the data to the panels and to the three
// view modules (3D scene, long section, plan). View contract (spec 4.6): a view module exports
// mount(container, geometry) -> { update(state), focus(thingId), dispose() };
// update() is called with the unchanged answer of GET /api/state every 2 s.
// If scene3d.mount throws, the section is mounted in the scene's container.
// A view whose container is hidden by the view switch gets no update() until it
// is shown again; then it gets the latest state at once. The plan («План») has
// a mode of its own; ?view=plan (or scene, section, both) opens a mode.
//
// A view reports a click on an object with a bubbling DOM event:
//   container.dispatchEvent(new CustomEvent('sekis:select',
//     { bubbles: true, detail: { thingId: 'kz.sekis:truck-01' } }))

import { getAdvisor, getGeometry, getParams, getScenario, getState } from './panels/api.js';
import { createAdvisor, createPlan, normalize } from './panels/advisor.js';
import { createAssumptions } from './panels/assumptions.js';
import { createCalibration } from './panels/calibration.js';
import { createChanges } from './panels/changes.js';
import { NS, airStatus } from './panels/dict.js';
import { el, fmt, isNum, setText } from './panels/format.js';
import { createHeader } from './panels/header.js';
import { createScenarios } from './panels/scenarios.js';
import { createTwins } from './panels/twins.js';
import { createVod } from './panels/vod.js';

const POLL_MS = 2000;
const ADVISOR_REFRESH_MS = 30000;
const VIEW_MODULES = { scene3d: './scene3d/index.js', section2d: './section2d/index.js', plan2d: './plan2d/index.js' };
const VIEW_TEXT = {
  scene3d: ['3D-сцена рудника', 'модуль сцены не подключён'],
  section2d: ['Продольный разрез рудника', 'модуль разреза не подключён'],
  plan2d: ['План рудника', 'модуль плана не подключён'],
};
const MODE_NAMES = { plan: 'plan2d', scene: 'scene3d', section: 'section2d' };
const EMBED = { '/embed/scene': 'scene3d', '/embed/section': 'section2d' }[location.pathname] || null;

const viewsBox = document.getElementById('views');
const containers = {
  scene3d: document.getElementById('view-scene3d'),
  section2d: document.getElementById('view-section2d'),
  plan2d: document.getElementById('view-plan2d'),
};
const mounted = [];   // { name, container, instance }

let lastState = null;
let report = null;
let advisorModel = null;
let advisorFetchedAt = 0;
let polling = false;
let failures = 0;
let floodCompression = null;   // water.flood_compression: the flood episode runs this much faster (spec 2.7)
// A page address may name a twin to open: /?twin=kz.sekis:truck-01
let pendingTwin = new URLSearchParams(location.search).get('twin');

const header = createHeader();
const advisorPanel = createAdvisor();
const planPanel = createPlan();
const changesPanel = createChanges();
const calibrationPanel = createCalibration();
const assumptionsPanel = createAssumptions();
const twinsPanel = createTwins({ onSelect: (id) => focusThing(id) });
const scenariosPanel = createScenarios({
  onChanged: (result) => {
    changesPanel.noteAction(result);
    advisorFetchedAt = 0;
    refresh();
  },
});
// «Вентиляция по потребности»: its switch is a scenario change like the others (undo in «Сценарии»).
const vodPanel = createVod({
  onChanged: (result) => {
    scenariosPanel.setInfo(result);
    changesPanel.noteAction(result);
    advisorFetchedAt = 0;
    refresh();
  },
});

// -------------------------------------------------------------------- views

function setMode(mode) {
  viewsBox.dataset.mode = mode;
  // The plan fills the view area alone; the scene and the section share it.
  if (containers.plan2d) {
    containers.plan2d.hidden = mode !== 'plan2d';
    containers.scene3d.hidden = mode === 'plan2d';
    containers.section2d.hidden = mode === 'plan2d';
  }
  for (const button of document.querySelectorAll('.viz .seg button')) {
    button.setAttribute('aria-pressed', String(button.dataset.mode === mode));
  }
  updateViews();
}

const isShown = (container) => container.getClientRects().length > 0;

function updateViews() {
  if (lastState) eachView((view) => view.update && view.update(lastState), null, true);
}

function placeholder(name, detail) {
  const [title, absent] = VIEW_TEXT[name];
  containers[name].replaceChildren(el('div', { class: 'view-empty' },
    el('strong', { text: title }), el('span', { text: detail || absent })));
}

async function loadModule(name) {
  try {
    const module = await import(VIEW_MODULES[name]);
    return typeof module.mount === 'function' ? module : null;
  } catch (error) {
    return null;   // the module is not in this build
  }
}

async function mountInto(module, name, geometry) {
  const container = containers[name];
  container.replaceChildren();
  const instance = await module.mount(container, geometry);
  mounted.push({ name, container, instance: instance || {} });
}

async function mountViews(geometry) {
  const wanted = EMBED ? [EMBED] : ['scene3d', 'section2d', 'plan2d'];
  if (!geometry) {
    for (const name of wanted) placeholder(name, 'геометрия сцены не получена');
    return;
  }
  const section = await loadModule('section2d');
  let sectionInScene = false;
  if (wanted.includes('scene3d')) {
    const scene = await loadModule('scene3d');
    if (!scene) {
      placeholder('scene3d');
    } else {
      try {
        await mountInto(scene, 'scene3d', geometry);
      } catch (error) {
        console.warn('scene3d.mount failed, the section takes its place', error);
        try {
          if (!section) throw error;
          await mountInto(section, 'scene3d', geometry);
          sectionInScene = true;
        } catch (inner) {
          placeholder('scene3d', '3D-сцена недоступна в этом браузере');
        }
      }
    }
  }
  if (sectionInScene) {      // one section is enough: the second container is not used
    if (viewsBox.dataset.mode !== 'plan2d') setMode('scene3d');
    for (const button of document.querySelectorAll('.viz .seg button')) {
      if (button.dataset.mode === 'both' || button.dataset.mode === 'section2d') button.hidden = true;
      if (button.dataset.mode === 'scene3d') button.textContent = 'Продольный разрез';
    }
  } else if (wanted.includes('section2d')) {
    if (!section) {
      placeholder('section2d');
    } else {
      try {
        await mountInto(section, 'section2d', geometry);
      } catch (error) {
        console.warn('section2d.mount failed', error);
        placeholder('section2d', 'разрез недоступен');
      }
    }
  }
  if (wanted.includes('plan2d') && containers.plan2d) {
    const plan = await loadModule('plan2d');
    if (!plan) {
      placeholder('plan2d');
    } else {
      try {
        await mountInto(plan, 'plan2d', geometry);
      } catch (error) {
        console.warn('plan2d.mount failed', error);
        placeholder('plan2d', 'план недоступен');
      }
    }
  }
}

function eachView(action, except, shownOnly) {
  for (const view of mounted) {
    if (view.container === except || (shownOnly && !isShown(view.container))) continue;
    try {
      action(view.instance);
    } catch (error) {
      console.error(`view ${view.name}`, error);
    }
  }
}

/** Select a twin everywhere: the table row, the card and every view. */
function focusThing(thingId, sourceContainer) {
  twinsPanel.select(thingId, { scroll: true });
  if (thingId) eachView((view) => view.focus && view.focus(thingId), sourceContainer);
}

document.addEventListener('sekis:select', (event) => {
  const thingId = event.detail && event.detail.thingId;
  if (thingId) focusThing(thingId, event.target.closest ? event.target.closest('.view') : null);
});

// --------------------------------------------------------------------- data

function advisorDue(state) {
  const age = performance.now() - advisorFetchedAt;
  if (!report) return age >= POLL_MS;
  const twin = (state.things[NS + 'advisor'] && state.things[NS + 'advisor'].f) || {};
  if (isNum(report.report_revision)) {
    if (report.report_revision !== state.revision) return true;            // scenario moved on
    if (isNum(twin.report_revision) && twin.report_revision !== report.report_revision) return true;
    return age >= ADVISOR_REFRESH_MS;
  }
  return age >= 3 * POLL_MS;   // a report without a revision is simply re-read
}

// Counts follow the one definition of dict.js (unitCounts): «в работе» is every
// truck of the fleet that is not under repair, «в рейсе» those of them that are
// not waiting for air. The air is the delivered air against the demand in work (airStatus).
function vizSummary(state, advisor) {
  const f = (name) => (state.things[NS + name] && state.things[NS + name].f) || {};
  const mine = f('mine');
  const air = airStatus(state.things, advisor);
  const c = air.counts;
  const onRamp = [f('decline-tu1').trucks_on_ramp, f('decline-tu2').trucks_on_ramp].filter(isNum);
  let trucks;
  if (isNum(c.inService)) {
    trucks = `самосвалов в работе: ${fmt(c.inService)}`;
    if (c.maintenance > 0) trucks += ` из ${fmt(c.fleet)}, в ремонте: ${fmt(c.maintenance)}`;
    if (c.held > 0) trucks += ` (в рейсе ${fmt(c.onTrip)}, ждут воздуха ${fmt(c.held)})`;
  } else {
    trucks = `самосвалов в рейсе: ${fmt(c.onTrip)}`;
  }
  // The air now: delivered by the fans against the demand of the units in work. While units
  // wait for air the demand of the whole fleet against the design supply says why.
  const airNow = `воздух: подаётся ${fmt(air.delivered, 0)} м³/с, нужно машинам в работе ${fmt(air.inWork, 0)} м³/с`;
  const airText = air.short && isNum(air.fleetDemand)
    ? `${airNow}; всему парку нужно ${fmt(air.fleetDemand, 0)} при проектной подаче ${fmt(air.supply, 0)} м³/с`
    : airNow;
  const parts = [
    trucks,
    c.lhdHeld > 0 ? `ПДМ ждут воздуха: ${fmt(c.lhdHeld)}` : null,
    onRamp.length ? `на уклонах: ${fmt(onRamp.reduce((a, b) => a + b, 0))}` : null,
    airText,
    `приток воды: ${fmt(mine.inflow_m3h)} м³/ч`,
    isNum(mine.flood_volume_m3) && mine.flood_volume_m3 > 0
      ? `затоплено: ${fmt(mine.flood_volume_m3)} м³${isNum(floodCompression) && floodCompression > 1
        ? ` (×${fmt(floodCompression)})` : ''}` : null,
  ];
  return parts.filter(Boolean).join(' · ');
}

function render(state) {
  advisorModel = normalize(report, state);
  header.update(state, advisorModel);
  scenariosPanel.update(state, advisorModel);
  advisorPanel.update(advisorModel);
  planPanel.update(advisorModel);
  changesPanel.update(state, advisorModel);
  calibrationPanel.update(advisorModel.calibration);
  twinsPanel.update(state);
  vodPanel.update(state);
  const meta = document.getElementById('viz-meta');
  setText(meta, vizSummary(state, advisorModel));
  meta.title = meta.textContent;
  updateViews();
  if (pendingTwin && state.things[pendingTwin]) {
    focusThing(pendingTwin);
    pendingTwin = null;
  }
}

async function refresh() {
  if (polling) return;
  polling = true;
  try {
    const state = await getState();
    if (!state || typeof state.things !== 'object') throw new Error('bad state');
    lastState = state;
    failures = 0;
    if (advisorDue(state)) {
      advisorFetchedAt = performance.now();
      try {
        report = await getAdvisor();
      } catch (error) {
        // The bars keep working from the advisor twin; the report is retried.
      }
    }
    render(state);
    if (state.mode === 'fixture') header.connection('ok', 'образец данных, без Ditto');
    else if (isNum(state.age_s) && state.age_s > 10) header.connection('stale', `данные Ditto устарели на ${fmt(state.age_s)} с`);
    else if (!Object.keys(state.things).length) header.connection('stale', 'двойники ещё не получены');
    else header.connection('ok', 'данные двойников из Ditto');
  } catch (error) {
    failures += 1;
    if (failures >= 2) header.connection('down', 'нет связи со стендом');
  } finally {
    polling = false;
  }
}

// --------------------------------------------------------------------- start

function start() {
  if (EMBED) {
    document.documentElement.dataset.embed = EMBED;
    setMode(EMBED);
  } else {
    const asked = new URLSearchParams(location.search).get('view');
    const mode = MODE_NAMES[asked] || asked;
    setMode(['both', 'scene3d', 'section2d', 'plan2d'].includes(mode) ? mode
      : window.innerHeight >= 900 && window.innerWidth >= 1500 ? 'both' : 'scene3d');
    document.querySelector('.viz .seg').addEventListener('click', (event) => {
      const button = event.target.closest('button[data-mode]');
      if (button) setMode(button.dataset.mode);
    });
  }
  for (const [name, container] of Object.entries(containers)) {
    if (!container) continue;
    placeholder(name, 'загрузка');
    if ('ResizeObserver' in window) {   // the current size of each mount container, for the views
      new ResizeObserver(() => {
        container.dataset.size = `${container.clientWidth}x${container.clientHeight}`;
      }).observe(container);
    }
  }

  getGeometry().then(mountViews).then(() => {
    updateViews();
    const selected = twinsPanel.selected();
    if (selected) eachView((view) => view.focus && view.focus(selected));
  });
  if (!EMBED) {
    getScenario().then((info) => scenariosPanel.setInfo(info)).catch(() => {});
    getParams().then((params) => {
      const k = params && params['water.flood_compression'];
      floodCompression = k && isNum(k.value) ? k.value : null;
      vodPanel.setParams(params);
      scenariosPanel.setParams(params);
      assumptionsPanel.render(params);
    }).catch(() => assumptionsPanel.render(null));
  }
  refresh();
  setInterval(refresh, POLL_MS);
  window.sekisStand = { focus: focusThing, state: () => lastState, advisor: () => advisorModel };
}

start();
