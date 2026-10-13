// «Сценарии»: targets, advisor actions, measure knobs with − / +, disturbances,
// undo and reset. The buttons are in index.html; this module wires them to
// POST /api/scenario and keeps them in step with the scenario twin.

import { postScenario } from './api.js';
import { MEASURES, NS, linkLabel } from './dict.js';
import { el, fmt, isNum, setText } from './format.js';

const same = (a, b) => isNum(a) && isNum(b) && Math.abs(a - b) < 1e-9;

export function createScenarios({ onChanged }) {
  const root = document.getElementById('scenarios');
  const message = document.getElementById('sc-message');
  const revision = document.getElementById('sc-revision');
  const hint = document.getElementById('sc-next');
  const undo = document.getElementById('sc-undo');
  const measures = document.getElementById('sc-measures');
  const knobRows = {};
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
    const row = el('div', { class: 'knob', dataset: { knob: measure.knob } },
      el('span', { class: 'knob-name', text: measure.name }),
      el('span', { class: 'knob-ctl' }, minus, pips, plus), stage);
    knobRows[measure.knob] = { row, minus, plus, pips, stage, measure };
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

    for (const button of root.querySelectorAll('.toggle')) {
      const on = known && same(knobs[button.dataset.knob], Number(button.dataset.on));
      button.setAttribute('aria-pressed', String(on));
      setText(button, on ? button.dataset.labelOn : button.dataset.labelOff);
    }

    const nextLink = advisor && advisor.next ? advisor.next.link : null;
    for (const { row, minus, plus, pips, stage, measure } of Object.values(knobRows)) {
      const value = isNum(knobs[measure.knob]) ? Math.round(knobs[measure.knob]) : null;
      const max = measure.stages.length - 1;
      minus.disabled = value === null || value <= 0;
      plus.disabled = value === null || value >= max;
      [...pips.children].forEach((pip, index) => pip.classList.toggle('on', value !== null && index < value));
      setText(stage, value === null ? '—' : `ступень ${value} из ${max}: ${measure.stages[value] || ''}`);
      row.title = measure.stages.map((text, index) => `${index}: ${text}`).join('\n');
      row.classList.toggle('is-next', Boolean(nextLink) && measure.link === nextLink);
    }

    const next = advisor && advisor.next;
    hint.replaceChildren();
    if (next) {
      hint.append('Сейчас ограничивает: ', el('b', { text: linkLabel(next.link).toLowerCase() }),
        `. Мера: ${next.text}.`);
    } else if (advisor && advisor.hasData) {
      hint.append(isNum(advisor.target) && isNum(advisor.achievable) && advisor.achievable >= advisor.target
        ? 'Цель достигается, мер не требуется.' : 'На узком месте ступеней больше нет.');
    }
    for (const id of ['advisor_next', 'advisor_all']) {
      root.querySelector(`[data-preset="${id}"]`).disabled = Boolean(advisor && advisor.hasData && !next);
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

  return { update, setInfo };
}
