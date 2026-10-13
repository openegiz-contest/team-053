// «Что изменилось»: effects of the last scenario change. The sentences come from
// the advisor report; without them the panel compares the features of the
// advisor twin before and after the change of revision.

import { FEATURE_RU, LINKS, NS, featureLabel, linkLabel, unitLabel } from './dict.js';
import { clear, el, fmt, isNum, setText, withUnit } from './format.js';

const TWIN_KEYS = ['achievable_ktpa', ...LINKS.map((link) => `cap_${link}_ktpa`), 'gold_koz_year',
  'air_demand_m3s', 'water_deficit_m3h', 'discharge_m3h', 'tailings_years_left', 'stockpile_days_left'];
const LOWER_IS_BETTER = new Set(['air_demand_m3s', 'water_deficit_m3h', 'discharge_m3h']);

export function createChanges() {
  const body = document.getElementById('chg-body');
  const meta = document.getElementById('chg-meta');
  const lastSeen = {};        // revision -> advisor twin features seen last at that revision
  let knobChange = null;      // { revision, changed } from the last POST of this page
  let signature = '';

  function fromTwin(state) {
    const revision = state.revision;
    const before = lastSeen[revision - 1];
    const after = lastSeen[revision];
    if (!before || !after) return [];
    const units = (state.things[NS + 'advisor'].attrs || {}).units || {};
    const items = [];
    if (before.binding_link !== after.binding_link) {
      items.push({ trend: 'neutral', text: `Узкое место: ${linkLabel(before.binding_link).toLowerCase()} → ${linkLabel(after.binding_link).toLowerCase()}` });
    }
    for (const key of TWIN_KEYS) {
      const a = before[key];
      const b = after[key];
      if (!isNum(a) || !isNum(b) || Math.abs(a - b) < 0.05) continue;
      const digits = key.endsWith('_ktpa') || key === 'stockpile_days_left' ? 0 : 1;
      const better = (b > a) !== LOWER_IS_BETTER.has(key);
      items.push({
        trend: better ? 'better' : 'worse',
        text: `${featureLabel(key)}: ${fmt(a, digits)} → ${withUnit(fmt(b, digits), unitLabel(units[key]))} (${fmt(b - a, digits, { sign: true })})`,
      });
    }
    return items;
  }

  function update(state, advisor) {
    if (!state || !state.things) return;
    const twin = state.things[NS + 'advisor'];
    const scenario = (state.things[NS + 'scenario'] && state.things[NS + 'scenario'].f) || {};
    if (twin && isNum(state.revision)) lastSeen[state.revision] = { ...twin.f };

    const effects = advisor && advisor.effects;
    const current = effects && (!isNum(effects.revision) || effects.revision === state.revision);
    const items = current ? effects.items : twin ? fromTwin(state) : [];
    const label = (current && effects.label) || scenario.label || '';
    const knobs = knobChange && knobChange.revision === state.revision ? knobChange.changed : null;

    const next = JSON.stringify([state.revision, label, items, knobs]);
    if (next === signature) return;
    signature = next;

    setText(meta, isNum(state.revision) ? `ревизия ${fmt(state.revision)}${label ? ' · ' + label : ''}` : '—');
    meta.title = label;
    clear(body);
    if (!state.revision) {
      body.append(el('p', { class: 'empty', text: 'Сценарий не менялся: рудник работает в базовом режиме.' }));
      return;
    }
    if (items.length) {
      body.append(el('ul', { class: 'chg-list' }, items.map((item) => el('li',
        { class: 'chg num', dataset: { trend: item.trend || 'neutral' }, text: item.text }))));
    } else {
      body.append(el('p', { class: 'empty', text: effects && !current
        ? 'Советник пересчитывает показатели для новой ревизии.'
        : 'Пропускные способности звеньев и показатели не изменились.' }));
    }
    if (knobs && Object.keys(knobs).length) {
      const parts = Object.entries(knobs).map(([knob, [a, b]]) => `${FEATURE_RU[knob] || knob}: ${fmt(a, 2).replace(/,00$/, '')} → ${fmt(b, 2).replace(/,00$/, '')}`);
      body.append(el('p', { class: 'chg-knobs' },
        'Запись в двойник ', el('span', { class: 'mono', text: 'kz.sekis:scenario' }), ': ', parts.join('; ')));
    }
  }

  /** Remember which knobs the last action of this page changed. */
  function noteAction(result) {
    if (result && result.changed) knobChange = { revision: result.revision, changed: result.changed };
  }

  return { update, noteAction };
}
