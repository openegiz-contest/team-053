// «Сценарии»: targets, advisor actions, measure knobs with − / +, disturbances,
// undo and reset. The buttons are in index.html; this module wires them to
// POST /api/scenario and keeps them in step with the scenario twin.

import { postScenario } from './api.js';
import { FORMS, MEASURES, NS, countText, linkLabel, unitCounts } from './dict.js';
import { el, fmt, isNum, setText } from './format.js';

const same = (a, b) => isNum(a) && isNum(b) && Math.abs(a - b) < 1e-9;

/** No line break inside «№ 2», «1,76 г/т», «430 м³/ч». */
const NBSP = '\u00a0';
const keepTogether = (text) => (text || '').replace(/№ /g, '№' + NBSP).replace(/(\d) (?=[гмт])/g, '$1' + NBSP);

/**
 * What a disturbance or the live fleet does to a measure stage, as one line per
 * knob: { m_vent: { text, tone, design } }. `design` marks that the stage value is
 * the design one and the line gives the actual value.
 */
function stageNotes(things, knobs, advisor, stages) {
  const f = (name) => (things[NS + name] && things[NS + name].f) || {};
  const capOf = (id) => {
    const link = advisor && advisor.links ? advisor.links.find((row) => row.id === id) : null;
    return link && isNum(link.cap) ? link.cap : null;
  };
  const notes = {};

  // Ventilation: the supply of the stage against the supply now.
  const vent = MEASURES.find((m) => m.knob === 'm_vent');
  const supply = f('mine').air_supply_m3s;
  const ventDesign = isNum(stages.m_vent) ? vent.design[stages.m_vent] : null;
  if (isNum(supply) && isNum(ventDesign) && Math.abs(supply - ventDesign) >= 0.5) {
    const failed = Object.entries(things)
      .filter(([, t]) => t.kind === 'main_fan' && t.f && t.f.state === 'failed')
      .map(([id, t]) => {
        const name = t.name || id.replace(NS, '');
        const code = name.match(/\(([^)]+)\)\s*$/);   // «Вентилятор … (ВС-2)» -> ВС-2
        return code ? code[1] : name;
      });
    const why = failed.length ? `отказ вентилятора ${failed.join(', ')}`
      : knobs.fan_vs2_off ? 'отказ вентилятора ВС-2' : '';
    notes.m_vent = { design: true, tone: 'warn',
      text: `сейчас ${fmt(supply, 0)} ${vent.unit}${why ? ' — ' + why : ''}` };
  }

  // Plant: the capacity of the stage against the lines running now.
  const plantMeasure = MEASURES.find((m) => m.knob === 'm_plant');
  const plantCap = isNum(f('plant').capacity_ktpa) ? f('plant').capacity_ktpa : capOf('plant');
  const plantDesign = isNum(stages.m_plant) ? plantMeasure.design[stages.m_plant] : null;
  if (isNum(plantCap) && isNum(plantDesign) && plantCap < plantDesign - 0.5) {
    const stopped = Object.entries(things)
      .filter(([, t]) => t.kind === 'plant_line' && t.f && ['off', 'maintenance', 'failed'].includes(t.f.state))
      .map(([id]) => id.replace(/^.*-/, ''));
    const why = knobs.line_down ? `остановлена линия № ${fmt(knobs.line_down)}`
      : stopped.length ? `${stopped.length > 1 ? 'остановлены линии' : 'остановлена линия'} № ${stopped.join(', ')}` : '';
    notes.m_plant = { design: true, tone: 'warn',
      text: `сейчас ${fmt(plantCap, 0)} ${plantMeasure.unit}${why ? ' — ' + why : ''}` };
  }

  // Haulage: a closed decline, and the trucks of the stage that do not haul now.
  const counts = unitCounts(things);
  const haul = [];
  let haulTone = '';
  const closed = [knobs.tu1_closed ? 'ТУ-1' : null, knobs.tu2_closed ? 'ТУ-2' : null].filter(Boolean);
  if (closed.length) {
    const cap = capOf('haulage');
    haul.push(`${isNum(cap) ? `откатка ${fmt(cap, 0)} тыс. т/год — ` : ''}закрыт уклон ${closed.join(', ')}`);
    haulTone = 'warn';
  }
  if (isNum(counts.inService) && (counts.maintenance > 0 || counts.held > 0)) {
    const parts = [`самосвалов в работе ${fmt(counts.inService)}`];
    if (counts.maintenance > 0) parts.push(`в ремонте ${fmt(counts.maintenance)}`);
    if (counts.held > 0) {
      parts.push(`ждут воздуха ${fmt(counts.held)}`);
      haulTone = 'warn';
    }
    haul.push(parts.join(', '));
  }
  if (haul.length) notes.m_haul = { tone: haulTone, text: 'сейчас ' + haul.join('; ') };

  // Stopes: LHDs waiting for air, flooded stopes.
  const flooded = Object.values(things).filter((t) => t.kind === 'stope' && t.f && t.f.state === 'flooded').length;
  const stopes = [];
  if (counts.lhdHeld > 0) stopes.push(`ждут воздуха ${countText(counts.lhdHeld, FORMS.lhd)}`);
  if (flooded > 0) stopes.push(`затоплено ${countText(flooded, ['блок', 'блока', 'блоков'])}`);
  if (stopes.length) notes.m_stopes = { tone: 'warn', text: 'сейчас ' + stopes.join('; ') };
  return notes;
}

export function createScenarios({ onChanged }) {
  const root = document.getElementById('scenarios');
  const message = document.getElementById('sc-message');
  const revision = document.getElementById('sc-revision');
  const hint = document.getElementById('sc-next');
  const undo = document.getElementById('sc-undo');
  const measures = document.getElementById('sc-measures');
  const floodNote = document.getElementById('sc-flood-note');
  const knobRows = {};
  let params = null;   // model/params.json, for the statement of the flood time compression
  let busy = false;
  let undoDepth = null;
  let defaults = null;   // knob defaults from GET /api/scenario

  for (const measure of MEASURES) {
    const minus = el('button', { type: 'button', class: 'btn', text: '−',
      'aria-label': `${measure.name}: предыдущая ступень`, dataset: { step: '-1', knob: measure.knob } });
    const plus = el('button', { type: 'button', class: 'btn', text: '+',
      'aria-label': `${measure.name}: следующая ступень`, dataset: { step: '1', knob: measure.knob } });
    const pips = el('span', { class: 'pips', 'aria-hidden': 'true' },
      measure.stages.slice(1).map(() => el('i', {})));
    const stage = el('span', { class: 'knob-stage' });
    const note = el('span', { class: 'knob-note', hidden: true });
    const row = el('div', { class: 'knob', dataset: { knob: measure.knob } },
      el('span', { class: 'knob-name', text: measure.name }),
      el('span', { class: 'knob-ctl' }, minus, pips, plus), stage, note);
    knobRows[measure.knob] = { row, minus, plus, pips, stage, note, measure };
    measures.append(row);
  }

  function say(text, tone) {
    message.dataset.tone = tone || '';
    setText(message, text || '');
  }

  async function send(body, button) {
    if (busy) return;
    busy = true;
    if (button) button.classList.add('is-busy');
    try {
      const result = await postScenario(body);
      setInfo(result);
      say(result.message || '', '');
      onChanged(result);
    } catch (error) {
      say(error.message, 'fail');
    } finally {
      busy = false;
      if (button) button.classList.remove('is-busy');
    }
  }

  root.addEventListener('click', (event) => {
    const button = event.target.closest('button');
    if (!button || button.disabled) return;
    if (button.dataset.preset) {
      const id = button.dataset.preset;
      const key = ['undo', 'reset', 'advisor_next', 'advisor_all'].includes(id) ? 'action' : 'preset';
      send({ [key]: id }, button);
    } else if (button.dataset.step) {
      send({ step: { [button.dataset.knob]: Number(button.dataset.step) } }, button);
    }
  });

  /** Reflect the scenario twin (and the advisor's next measure) in the controls. */
  function update(state, advisor) {
    const things = (state && state.things) || {};
    const knobs = (things[NS + 'scenario'] && things[NS + 'scenario'].f) || {};
    const known = isNum(knobs.target_ktpa);

    const isBase = known && defaults !== null
      && Object.entries(defaults).every(([knob, value]) => same(knobs[knob], value));
    const targetOf = { base: 1000, step1200: 1200, step2000: 2000, step2500: 2500 };
    for (const button of root.querySelectorAll('.sc-targets button')) {
      const id = button.dataset.preset;
      const pressed = id === 'base' ? isBase : known && same(knobs.target_ktpa, targetOf[id]);
      button.setAttribute('aria-pressed', String(Boolean(pressed)));
    }

    // The next step is either a measure (its row is marked) or the removal of a disturbance
    // (report schema 2: the matching disturbance button is marked, no measure row).
    const nextStep = advisor && advisor.next ? advisor.next : null;
    const repair = Boolean(nextStep) && nextStep.kind === 'disturbance';
    const toggles = [...root.querySelectorAll('.toggle')];
    const pressedOf = new Map(toggles.map((button) => [button,
      known && same(knobs[button.dataset.knob], Number(button.dataset.on))]));
    // Buttons of the disturbance the advisor removes next: those that are on, else every button of the knob.
    const ofKnob = repair && nextStep.knob ? toggles.filter((button) => button.dataset.knob === nextStep.knob) : [];
    const marked = new Set(ofKnob.some((button) => pressedOf.get(button))
      ? ofKnob.filter((button) => pressedOf.get(button)) : ofKnob);
    for (const button of toggles) {
      const on = pressedOf.get(button);
      button.setAttribute('aria-pressed', String(on));
      setText(button, keepTogether(on ? button.dataset.labelOn : button.dataset.labelOff));
      button.classList.toggle('is-next', marked.has(button));
      button.style.boxShadow = marked.has(button) ? 'inset 3px 0 0 var(--accent)' : '';
      if (marked.has(button)) button.title = 'Следующий шаг советника: устранить нарушение';
      else button.removeAttribute('title');
    }

    const nextLink = nextStep && !repair ? nextStep.link : null;
    const stages = {};
    for (const measure of MEASURES) {
      stages[measure.knob] = isNum(knobs[measure.knob]) ? Math.round(knobs[measure.knob]) : null;
    }
    const notes = known ? stageNotes(things, knobs, advisor, stages) : {};
    for (const { row, minus, plus, pips, stage, note, measure } of Object.values(knobRows)) {
      const value = stages[measure.knob];
      const max = measure.stages.length - 1;
      const extra = notes[measure.knob];
      minus.disabled = value === null || value <= 0;
      plus.disabled = value === null || value >= max;
      [...pips.children].forEach((pip, index) => pip.classList.toggle('on', value !== null && index < value));
      setText(stage, value === null ? '—'
        : `ступень ${value} из ${max}: ${measure.stages[value] || ''}${extra && extra.design ? ' по проекту' : ''}`);
      note.hidden = !extra;
      note.dataset.tone = extra ? extra.tone : '';
      setText(note, extra ? extra.text : '');
      row.title = measure.stages.map((text, index) => `${index}: ${text}`).join('\n');
      row.classList.toggle('is-next', Boolean(nextLink) && measure.link === nextLink);
    }

    // «Сейчас ограничивает» names the smallest link (the binding one of the bars); a disturbance
    // the advisor removes first is named apart, «Сначала устранить», because it may relieve
    // another link (a dead pump station relieves dewatering while haulage binds).
    const next = advisor && advisor.next;
    const binding = advisor && advisor.binding ? advisor.links.find((link) => link.id === advisor.binding) : null;
    hint.replaceChildren();
    if (binding) {
      hint.append('Сейчас ограничивает: ', el('b', { text: linkLabel(binding.id).toLowerCase() }),
        isNum(binding.cap) ? ` (${fmt(binding.cap)} тыс. т/год).` : '.');
    }
    if (next && next.kind === 'disturbance') {
      hint.append(binding ? ' ' : '', 'Сначала устранить: ', el('b', { text: linkLabel(next.link).toLowerCase() }),
        ` — ${next.text}.`);
    } else if (next) {
      if (!binding) hint.append('Сейчас ограничивает: ', el('b', { text: linkLabel(next.link).toLowerCase() }), '.');
      hint.append(` Мера: ${next.text}.`);
    } else if (advisor && advisor.hasData) {
      if (binding) hint.append(' ');
      hint.append(isNum(advisor.target) && isNum(advisor.achievable) && advisor.achievable >= advisor.target
        ? 'Цель достигается, мер не требуется.' : 'На узком месте ступеней больше нет.');
    }
    for (const id of ['advisor_next', 'advisor_all']) {
      root.querySelector(`[data-preset="${id}"]`).disabled = Boolean(advisor && advisor.hasData && !next);
    }

    // The flood episode runs faster than the mine clock (spec 2.7, water.flood_compression): say so
    // while the +150 m station is out or water stands in the workings.
    if (floodNote) {
      const mine = (things[NS + 'mine'] && things[NS + 'mine'].f) || {};
      const station = (things[NS + 'ps-p150'] && things[NS + 'ps-p150'].f) || {};
      const episode = station.state === 'failed' || (isNum(mine.flood_volume_m3) && mine.flood_volume_m3 > 0);
      floodNote.hidden = !episode;
      if (episode) {
        const value = (id, fallback) => (params && params[id] && isNum(params[id].value) ? params[id].value : fallback);
        const k = value('water.flood_compression', 24);
        setText(floodNote, `Затопление показано ускоренно: вода в зумпфах и выработках прибывает в ${fmt(k)} раза `
          + `быстрее часов рудника (час на стенде — ${k === 24 ? 'сутки' : fmt(k) + ' ч'} притока). Пороги: гор. −50 м — `
          + `${fmt(value('water.flood_threshold_m050_m3', 14960))} м³, гор. 0 м — ${fmt(value('water.flood_threshold_000_m3', 44930))} м³; `
          + 'приток, откачка и поверхность — по часам рудника.');
      }
    }

    setText(revision, known
      ? `ревизия ${fmt(knobs.revision)}${knobs.label ? ' · ' + knobs.label : ''}` : 'ревизия —');
    revision.title = knobs.label || '';
    undo.disabled = undoDepth === 0;
    setText(undo, undoDepth ? `Шаг назад (${fmt(undoDepth)})` : 'Шаг назад');
  }

  /** Take the undo depth and the knob defaults from a /api/scenario answer. */
  function setInfo(info) {
    if (!info) return;
    undoDepth = isNum(info.undo_depth) ? info.undo_depth : null;
    if (info.defaults) defaults = info.defaults;
  }

  /** model/params.json (GET /api/params) for the texts that quote a parameter. */
  function setParams(list) {
    params = list && typeof list === 'object' ? list : null;
  }

  return { update, setInfo, setParams };
}
