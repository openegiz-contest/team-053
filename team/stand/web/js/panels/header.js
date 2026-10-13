// Top bar: enterprise name, simulated clock and shift, a few live rates, the
// binding link and the freshness of the data.

import { NS, linkLabel, shiftLabel } from './dict.js';
import { DASH, fmt, isNum, setText, simClock, withUnit } from './format.js';

export function createHeader() {
  const $ = (id) => document.getElementById(id);
  const nodes = {
    name: $('hdr-name'), time: $('hdr-time'), date: $('hdr-date'), shift: $('hdr-shift'),
    day: $('hdr-day'), hoist: $('hdr-hoist'), feed: $('hdr-feed'), gold: $('hdr-gold'),
    air: $('hdr-air'), stock: $('hdr-stock'), bindingName: $('hdr-binding-name'),
    bindingCap: $('hdr-binding-cap'), conn: $('conn'), connText: $('conn-text'),
  };

  function update(state, advisor) {
    const things = (state && state.things) || {};
    const f = (name) => (things[NS + name] && things[NS + name].f) || {};
    const enterprise = things[NS + 'enterprise'];
    if (enterprise && enterprise.name) setText(nodes.name, enterprise.name);

    const clock = simClock(state && state.sim_time);
    setText(nodes.time, clock.time);
    setText(nodes.date, clock.date);
    const shift = f('enterprise').shift;
    setText(nodes.shift, shiftLabel(shift));
    nodes.shift.dataset.shift = shift || '';
    const day = f('enterprise').sim_day;
    setText(nodes.day, isNum(day) ? `сутки ${fmt(Math.floor(day) + 1)}` : `сутки ${DASH}`);

    setText(nodes.hoist, fmt(f('mine').ore_hoisted_tph, 0));
    setText(nodes.feed, fmt(f('plant').feed_tph, 0));
    setText(nodes.gold, fmt(f('enterprise').gold_poured_oz_day, 0));
    setText(nodes.air, fmt(f('mine').air_margin_pct, 1, { sign: true }));
    setText(nodes.stock, fmt(f('rom-stockpile').tonnes, 0));

    const binding = advisor && advisor.binding;
    setText(nodes.bindingName, binding ? linkLabel(binding) : DASH);
    setText(nodes.bindingCap, advisor ? withUnit(fmt(advisor.achievable, 0), 'тыс. т/год') : DASH);
  }

  /** status: 'ok' | 'stale' | 'down'. */
  function connection(status, text) {
    nodes.conn.dataset.status = status;
    nodes.conn.title = text;
    setText(nodes.connText, text);
  }

  return { update, connection };
}
