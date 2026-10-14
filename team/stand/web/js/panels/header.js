// Top bar: enterprise name, simulated clock and shift, the live rates, the air
// state, the ore stockpile, the binding link and the freshness of the data.
//
// The three rates share one basis so that they can be set side by side: ore
// hoisted (enterprise.ore_mined_tpd), plant feed (enterprise.ore_milled_tpd) and
// gold poured (enterprise.gold_poured_oz_day) are all totals of the last 24
// simulated hours, in t/day and oz/day. A scenario change restarts the windows;
// until 24 h have passed they are the time since the change scaled to a day.
// The stockpile trend is the difference of the first two, so the header cannot
// say "the mine hoists less than the plant eats" while the stockpile grows.

import { FORMS, NS, airStatus, countText, heldUnitsText, linkLabel, plural, shiftLabel } from './dict.js';
import { DASH, el, fmt, isNum, setText, simClock, withUnit } from './format.js';

const BASIS_TITLE = 'Выдача руды, питание фабрики и золото — итоги последних 24 часов модели, '
  + 'в тоннах и унциях за сутки, поэтому их можно сравнивать между собой. После изменения сценария '
  + 'отсчёт начинается заново: пока не прошли сутки, значение — среднее с момента изменения в пересчёте на сутки.';

/** Replace the static list of index.html by the grouped, labelled one; ids are kept. */
function buildPulse() {
  const old = document.querySelector('.topbar .pulse');
  const value = (id, unit) => el('dd', {}, el('span', { id, class: 'num', text: DASH }), ' ',
    el('small', { text: unit }));
  const rates = el('div', { class: 'pulse-group', role: 'group', 'aria-label': 'Итоги последних 24 часов', title: BASIS_TITLE },
    el('p', { class: 'pulse-cap', text: 'за последние 24 ч' }),
    el('dl', { class: 'pulse-row' },
      el('div', { class: 'pulse-item', id: 'hdr-hoist-item' },
        el('dt', { text: 'Выдача руды' }), value('hdr-hoist', 'т/сут')),
      el('div', { class: 'pulse-item', id: 'hdr-feed-item' },
        el('dt', { text: 'Питание фабрики' }), value('hdr-feed', 'т/сут')),
      el('div', { class: 'pulse-item', id: 'hdr-gold-item' },
        el('dt', { text: 'Золото' }), value('hdr-gold', 'унц./сут'))));
  // Air: the caption line carries the demand against the supply.
  const air = el('div', { class: 'pulse-group pulse-air', id: 'hdr-air-item' },
    el('p', { class: 'pulse-cap', id: 'hdr-air-more' }),
    el('dl', { class: 'pulse-row' }, el('div', { class: 'pulse-item' },
      el('dt', { id: 'hdr-air-label', text: 'Запас по воздуху' }),
      el('dd', {}, el('span', { id: 'hdr-air', class: 'num', text: DASH }), ' ', el('small', { id: 'hdr-air-unit' })))));
  const stock = el('div', { class: 'pulse-group pulse-stock', id: 'hdr-stock-item' },
    el('dl', { class: 'pulse-row' }, el('div', { class: 'pulse-item' },
      el('dt', { text: 'Рудный склад' }),
      el('dd', {}, el('span', { id: 'hdr-stock', class: 'num', text: DASH }), ' ', el('small', { text: 'т' }),
        el('span', { class: 'trend num', id: 'hdr-stock-trend' })))));
  const pulse = el('div', { class: 'pulse' }, rates, air, stock);
  if (old) old.replaceWith(pulse);
  return pulse;
}

export function createHeader() {
  buildPulse();
  const $ = (id) => document.getElementById(id);
  const nodes = {
    name: $('hdr-name'), time: $('hdr-time'), date: $('hdr-date'), shift: $('hdr-shift'),
    day: $('hdr-day'), hoist: $('hdr-hoist'), feed: $('hdr-feed'), gold: $('hdr-gold'),
    airItem: $('hdr-air-item'), airLabel: $('hdr-air-label'), air: $('hdr-air'),
    airUnit: $('hdr-air-unit'), airMore: $('hdr-air-more'),
    stockItem: $('hdr-stock-item'), stock: $('hdr-stock'), stockTrend: $('hdr-stock-trend'),
    binding: $('hdr-binding'), bindingName: $('hdr-binding-name'), bindingCap: $('hdr-binding-cap'),
    conn: $('conn'), connText: $('conn-text'),
  };

  /** «Предприятие «Секисовское»»: the kind word is a span that narrow pages hide. */
  function setName(name) {
    if (nodes.name.dataset.name === name) return;
    nodes.name.dataset.name = name;
    const match = name.match(/^(\S+\s+)(«.+»)$/);
    nodes.name.replaceChildren(...(match
      ? [el('span', { class: 'brand-kind', text: match[1] }), match[2]] : [name]));
  }

  function updateAir(things, advisor) {
    const air = airStatus(things, advisor);
    nodes.airItem.dataset.tone = air.short ? 'warn' : '';
    if (air.short) {
      setText(nodes.airLabel, 'Воздуха не хватает');
      setText(nodes.air, air.held > 0
        ? `${plural(air.held, ['ждёт', 'ждут', 'ждут'])} ${countText(air.held, FORMS.unit)}`
        : 'ограничение');
      setText(nodes.airUnit, '');
      setText(nodes.airMore, isNum(air.fleetDemand) && isNum(air.supply)
        ? `парку нужно ${fmt(air.fleetDemand, 0)} м³/с, подача ${fmt(air.supply, 0)}` : '');
      const who = heldUnitsText(air.counts);
      nodes.airItem.title = [
        isNum(air.fleetDemand) ? `Потребность всего парка: ${fmt(air.fleetDemand, 1)} м³/с.` : '',
        isNum(air.supply) ? `Подача: ${fmt(air.supply, 1)} м³/с.` : '',
        air.held > 0 ? `Ждут воздуха: ${who || countText(air.held, FORMS.unit)}.` : '',
        isNum(air.workingDemand) ? `Потребность работающих машин: ${fmt(air.workingDemand, 1)} м³/с.` : '',
      ].filter(Boolean).join(' ');
    } else {
      setText(nodes.airLabel, 'Запас по воздуху');
      setText(nodes.air, fmt(air.margin, 1, { sign: true }));
      setText(nodes.airUnit, isNum(air.margin) ? '%' : '');
      setText(nodes.airMore, isNum(air.workingDemand) && isNum(air.supply)
        ? `нужно ${fmt(air.workingDemand, 0)} м³/с, подача ${fmt(air.supply, 0)}` : '');
      nodes.airItem.title = isNum(air.workingDemand) && isNum(air.supply)
        ? `Потребность работающих машин: ${fmt(air.workingDemand, 1)} м³/с при подаче ${fmt(air.supply, 1)} м³/с; `
          + 'все машины парка работают, ни одна не ждёт воздуха.' : '';
    }
  }

  function updateStock(tonnes, mined, milled) {
    setText(nodes.stock, fmt(tonnes, 0));
    const delta = isNum(mined) && isNum(milled) ? mined - milled : null;
    // Below 1 % of the feed the stockpile is called steady.
    const steady = delta === null || Math.abs(delta) < 0.01 * Math.max(milled || 0, 1);
    const trend = delta === null ? '' : steady ? 'steady' : delta < 0 ? 'down' : 'up';
    const days = trend === 'down' && isNum(tonnes) ? tonnes / -delta : null;
    nodes.stockItem.dataset.trend = trend;
    nodes.stockItem.dataset.tone = isNum(days) && days < 7 ? 'warn' : '';
    setText(nodes.stockTrend, trend === 'down' ? `▼ ${fmt(-delta, 0)} т/сут`
      : trend === 'up' ? `▲ ${fmt(delta, 0)} т/сут` : trend === 'steady' ? '≈ без изменений' : '');
    nodes.stockItem.title = delta === null ? 'Запас руды на складе у фабрики' : [
      `Запас руды на складе у фабрики: ${withUnit(fmt(tonnes, 0), 'т')}.`,
      `За последние 24 ч выдано ${fmt(mined, 0)} т, фабрика переработала ${fmt(milled, 0)} т:`,
      trend === 'down' ? `склад убывает на ${fmt(-delta, 0)} т/сут; при этих темпах запаса хватит примерно на ${fmt(days, 0)} сут.`
        : trend === 'up' ? `склад растёт на ${fmt(delta, 0)} т/сут.` : 'склад почти не меняется.',
    ].join(' ');
  }

  function update(state, advisor) {
    const things = (state && state.things) || {};
    const f = (name) => (things[NS + name] && things[NS + name].f) || {};
    const enterprise = things[NS + 'enterprise'];
    if (enterprise && enterprise.name) setName(enterprise.name);

    const clock = simClock(state && state.sim_time);
    setText(nodes.time, clock.time);
    setText(nodes.date, clock.date);
    const shift = f('enterprise').shift;
    setText(nodes.shift, shiftLabel(shift));
    nodes.shift.dataset.shift = shift || '';
    const day = f('enterprise').sim_day;
    setText(nodes.day, isNum(day) ? `сутки ${fmt(Math.floor(day) + 1)}` : `сутки ${DASH}`);
    nodes.day.title = 'Сутки модели, считая от начала симуляции';

    // One basis for the three rates: totals of the last 24 h (see the module comment).
    const ent = f('enterprise');
    const mineTph = f('mine').ore_hoisted_tph;
    const mined = isNum(ent.ore_mined_tpd) ? ent.ore_mined_tpd : isNum(mineTph) ? mineTph * 24 : null;
    const milled = isNum(ent.ore_milled_tpd) ? ent.ore_milled_tpd : null;
    setText(nodes.hoist, fmt(mined, 0));
    setText(nodes.feed, fmt(milled, 0));
    setText(nodes.gold, fmt(ent.gold_poured_oz_day, 0));
    updateStock(f('rom-stockpile').tonnes, mined, milled);
    updateAir(things, advisor);

    const binding = advisor && advisor.binding;
    setText(nodes.bindingName, binding ? linkLabel(binding) : DASH);
    setText(nodes.bindingCap, advisor ? withUnit(fmt(advisor.achievable, 0), 'тыс. т/год') : DASH);
    nodes.binding.title = advisor && isNum(advisor.achievable)
      ? `Звено, которое сейчас ограничивает производительность. Цепочка рудника и фабрики может дать `
        + `${fmt(advisor.achievable, 0)} тыс. т руды в год (около ${fmt(advisor.achievable * 1000 / 360, 0)} т/сут `
        + 'при 360 рабочих днях рудника).'
      : 'Звено, которое сейчас ограничивает производительность';
  }

  setName(nodes.name.textContent.trim());

  /** status: 'ok' | 'stale' | 'down'. */
  function connection(status, text) {
    nodes.conn.dataset.status = status;
    nodes.conn.title = text;
    setText(nodes.connText, text);
  }

  return { update, connection };
}
