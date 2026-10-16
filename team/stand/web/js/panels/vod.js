// «Вентиляция по потребности» (spec 3.5): the main fans follow the air demand of the units in
// work. The panel shows the demand against the air delivered by level, the fans with their
// setpoints and power, the energy since 08:00 and the saving against the fans at their design
// duty, and the switch of the knob vod_enabled (POST /api/scenario {"preset": "vod_toggle"};
// «Шаг назад» in «Сценарии» undoes it like any other change).

import { postScenario } from './api.js';
import { NS, VOD_STATE, stateTone } from './dict.js';
import { DASH, clear, el, fmt, isNum, setText, withUnit } from './format.js';

const M3S = 'м³/с';
const KWH = 'кВт·ч';
const STATE_TONE = { off: 'idle', demand: 'ok', ramp: 'warn', full: 'info' };

/** «гор. +150 м» from «Горизонт +150 м (вентиляционный)». */
function levelName(thing) {
  const elevation = thing.attrs && thing.attrs.elevation_m;
  if (isNum(elevation)) return `гор. ${fmt(elevation, 0, { sign: true })} м`;
  return (thing.name || '').replace(/^Горизонт/, 'гор.');
}

/** «ВС-1» from «Вентилятор ВОД-16П (ВС-1)», else the model. */
function fanName(thing) {
  const code = (thing.name || '').match(/\(([^)]+)\)\s*$/);
  return code ? code[1] : (thing.attrs && thing.attrs.model) || thing.name || DASH;
}

function tile(k, v, unit, d, tone, title) {
  return el('div', { class: 'kpi', dataset: tone ? { tone } : {}, title: title || '' },
    el('div', { class: 'k', text: k }),
    el('div', { class: 'v' }, v, unit ? el('small', { text: ` ${unit}` }) : null),
    el('div', { class: 'd', text: d || '' }));
}

export function createVod({ onChanged }) {
  const root = document.getElementById('vod');
  const body = document.getElementById('vod-body');
  const meta = document.getElementById('vod-meta');
  if (!root || !body) return { update() {}, setParams() {} };
  let params = null;
  let busy = false;

  const button = el('button', { type: 'button', class: 'btn vod-switch', 'aria-pressed': 'false',
    text: 'Вентиляция по потребности: —' });
  const badge = el('span', { class: 'state', dataset: { tone: 'idle' }, text: DASH });
  const message = el('p', { class: 'sc-message', role: 'status', 'aria-live': 'polite' });
  const kpis = el('div', { class: 'kpis vod-kpis' });
  const levels = el('div', { class: 'vod-levels', role: 'table', 'aria-label': 'Воздух по горизонтам' });
  const fans = el('table', { class: 'vod-fans' });
  const rule = el('p', { class: 'vod-rule' });
  body.append(
    el('div', { class: 'vod-top' }, button, badge),
    message, kpis,
    el('div', { class: 'vod-grid' },
      el('div', {}, el('h3', { class: 'group', text: 'Воздух по горизонтам: подача и потребность' }), levels,
        el('div', { class: 'cap-legend' },
          el('span', {}, el('i', { class: 'lg-bar' }), 'подаётся'),
          el('span', {}, el('i', { class: 'lg-target' }), 'нужно машинам на горизонте'),
          el('span', {}, el('i', { class: 'lg-bar vod-leak' }), 'утечки (горизонт не в работе)'))),
      el('div', {}, el('h3', { class: 'group', text: 'Главные вентиляторы' }), fans)),
    rule);

  button.addEventListener('click', async () => {
    if (busy) return;
    busy = true;
    button.classList.add('is-busy');
    try {
      const result = await postScenario({ preset: 'vod_toggle' });
      message.dataset.tone = '';
      setText(message, result.message || '');
      onChanged(result);
    } catch (error) {
      message.dataset.tone = 'fail';
      setText(message, error.message);
    } finally {
      busy = false;
      button.classList.remove('is-busy');
    }
  });

  const p = (id, fallback) => (params && params[id] && isNum(params[id].value) ? params[id].value : fallback);

  function ruleText() {
    return `Правило: вентиляторы подают столько, сколько нужно машинам в работе по норме спецификации `
      + `(${fmt(p('vent.q_base', 180))} ${M3S} + ${fmt(p('vent.q_diesel', 0.06), 2)} ${M3S} на 1 кВт дизельной мощности) `
      + `плюс ${fmt(p('vod.margin_pct', 5))} %, от наименьшей до проектной подачи; подача растёт заранее — `
      + `за ${fmt(p('vod.pre_vent_min', 15))} мин до начала работы смены, снижается не раньше чем через `
      + `${fmt(p('vod.min_on_min', 30))} мин, не быстрее ${fmt(p('vod.ramp_pct_per_min', 5))} % проектной в минуту; `
      + `машина выходит в работу, только когда воздух для неё уже подан. Мощность вентилятора растёт как куб расхода; `
      + `экономия — против работы на проектном режиме, по тарифу ${fmt(p('vod.tariff_kzt_kwh', 35))} ₸/кВт·ч (допущение).`;
  }

  function update(state) {
    const things = (state && state.things) || {};
    const mine = (things[NS + 'mine'] && things[NS + 'mine'].f) || {};
    const knobs = (things[NS + 'scenario'] && things[NS + 'scenario'].f) || {};
    const enabled = isNum(knobs.vod_enabled) ? knobs.vod_enabled >= 0.5 : mine.vod_state !== 'off';
    setText(button, `Вентиляция по потребности: ${enabled ? 'вкл' : 'выкл'}`);
    button.setAttribute('aria-pressed', String(enabled));
    button.title = enabled ? 'Выключить: вентиляторы перейдут на проектный режим'
      : 'Включить: вентиляторы будут следовать потребности машин в работе';
    const token = mine.vod_state || '';
    badge.dataset.tone = STATE_TONE[token] || stateTone(token, 'mine');
    setText(badge, VOD_STATE[token] || DASH);
    setText(meta, isNum(mine.air_delivered_m3s)
      ? `подаётся ${fmt(mine.air_delivered_m3s)} из ${withUnit(fmt(mine.air_supply_m3s), M3S)}` : DASH);

    // energy: the last 24 hours give the yearly estimate (the fans run every day)
    const tariff = p('vod.tariff_kzt_kwh', null);
    const yearKwh = isNum(mine.fan_saving_day_kwh) ? mine.fan_saving_day_kwh * 365 : null;
    const yearKzt = isNum(yearKwh) && isNum(tariff) ? yearKwh * tariff : null;
    const fixedPower = Object.values(things).filter((t) => t.kind === 'main_fan' && t.f && t.f.state === 'running')
      .reduce((sum, t) => sum + (isNum(t.attrs.duty_m3s) && isNum(t.attrs.pressure_pa)
        ? t.attrs.duty_m3s * t.attrs.pressure_pa / p('vent.fan_efficiency', 0.75) / 1000 : 0), 0);
    clear(kpis).append(
      tile('Подаётся сейчас', fmt(mine.air_delivered_m3s, 0), M3S,
        isNum(mine.air_supply_m3s) ? `проектная подача ${fmt(mine.air_supply_m3s, 0)}` : ''),
      tile('Нужно машинам в работе', fmt(mine.vod_demand_m3s, 0), M3S,
        isNum(mine.vod_units_waiting) && mine.vod_units_waiting > 0
          ? `ждут набора подачи: ${fmt(mine.vod_units_waiting)}` : 'с базовой потребностью',
        isNum(mine.vod_units_waiting) && mine.vod_units_waiting > 0 ? 'warn' : null),
      tile('Мощность вентиляторов', fmt(mine.fan_power_kw, 0), 'кВт',
        fixedPower > 0 ? `на проектном режиме ${fmt(fixedPower, 0)}` : ''),
      tile('Энергия с 08:00', fmt(mine.fan_energy_today_kwh, 0), KWH,
        isNum(mine.fan_energy_shift_kwh) ? `за смену ${fmt(mine.fan_energy_shift_kwh, 0)}` : ''),
      tile('Экономия с 08:00', fmt(mine.fan_saving_today_kwh, 0), KWH,
        isNum(mine.fan_saving_today_kzt) ? withUnit(fmt(mine.fan_saving_today_kzt, 0), '₸') : ''),
      tile('Экономия за 24 ч', fmt(mine.fan_saving_day_kwh, 0), KWH,
        !enabled && !(mine.fan_saving_day_kwh > 0) ? 'выключена: работа на проектном режиме'
          : isNum(yearKwh) ? `≈ ${fmt(yearKwh / 1e6, 2)} млн ${KWH}/год${isNum(yearKzt) ? `, ${fmt(yearKzt / 1e6, 1)} млн ₸` : ''}` : '',
        null, 'Оценка за год: экономия последних 24 ч × 365 суток (вентиляторы работают каждый день)'));

    // levels: what each needs for the units working there and what it gets
    const rows = Object.entries(things)
      .filter(([, t]) => t.kind === 'level' && t.f && t.f.state !== 'planned')
      .map(([id, t]) => ({ id, thing: t, f: t.f }))
      .sort((a, b) => (b.thing.attrs.elevation_m || 0) - (a.thing.attrs.elevation_m || 0));
    const top = Math.max(1, ...rows.map((r) => Math.max(r.f.air_flow_m3s || 0, r.f.air_required_m3s || 0)));
    clear(levels).append(...rows.map(({ thing, f }) => {
      const flow = isNum(f.air_flow_m3s) ? f.air_flow_m3s : 0;
      const need = isNum(f.air_required_m3s) ? f.air_required_m3s : 0;
      const flooded = f.state === 'flooded';
      const leak = !flooded && need <= 0 && flow > 0;
      const short = need > 0 && flow < need - 0.05;
      const note = flooded ? 'затоплен: воздух не подаётся' : leak ? `утечки ${withUnit(fmt(flow, 1), M3S)}`
        : `${fmt(flow, 1)} из ${withUnit(fmt(need, 1), M3S)}`;
      const track = el('div', { class: 'cap-track vod-track', style: need > 0 ? `--target: ${(need / top) * 100}%` : '' },
        el('div', { class: `cap-fill${leak ? ' vod-leak' : ''}`, style: `width: ${(flow / top) * 100}%` }));
      if (need <= 0) track.classList.add('no-target');
      return el('div', { class: `cap-row vod-row${short ? ' is-short' : ''}`, role: 'row',
        title: `${thing.name}: подаётся ${fmt(flow, 1)} ${M3S}; нужно ${fmt(need, 1)} ${M3S}`
          + `${isNum(f.diesel_kw) && f.diesel_kw > 0 ? ` (машины на горизонте ${fmt(f.diesel_kw)} кВт)` : ''}` },
      el('span', { class: 'cap-name', role: 'cell', text: levelName(thing) }), track,
      el('span', { class: 'vod-note', role: 'cell', dataset: short ? { tone: 'warn' } : {}, text: note }));
    }));

    // fans
    const fanRows = Object.values(things)
      .filter((t) => t.kind === 'main_fan' && t.f && t.f.state !== 'planned')
      .map((t) => {
        const f = t.f;
        const duty = t.attrs && t.attrs.duty_m3s;
        const share = isNum(f.air_flow_m3s) && isNum(duty) && duty > 0 ? (f.air_flow_m3s / duty) * 100 : null;
        return el('tr', {},
          el('td', { text: fanName(t), title: t.name || '' }),
          el('td', { class: 'r num', text: f.state === 'running' ? fmt(f.air_flow_m3s, 1) : 'отказ' }),
          el('td', { class: 'r num', text: f.state === 'running' ? fmt(f.duty_setpoint_m3s, 1) : DASH }),
          el('td', { class: 'r num', text: isNum(share) && f.state === 'running' ? `${fmt(share, 0)} %` : DASH }),
          el('td', { class: 'r num', text: f.state === 'running' ? fmt(f.pressure, 0) : DASH }),
          el('td', { class: 'r num', text: f.state === 'running' ? fmt(f.power_kw, 0) : DASH }));
      });
    clear(fans).append(
      el('thead', {}, el('tr', {},
        el('th', { text: 'Вентилятор' }), el('th', { class: 'r', text: 'Расход, м³/с' }),
        el('th', { class: 'r', text: 'Уставка' }), el('th', { class: 'r', text: 'От проектного' }),
        el('th', { class: 'r', text: 'Давление, Па' }), el('th', { class: 'r', text: 'Мощность, кВт' }))),
      el('tbody', {}, ...fanRows));
    setText(rule, ruleText());
  }

  function setParams(list) {
    params = list && typeof list === 'object' ? list : null;
  }

  return { update, setParams };
}
