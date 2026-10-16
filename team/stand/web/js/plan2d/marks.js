// Point symbols of the plan in screen pixels: shaft collars with their fans,
// raises, decline portals, monitoring points, pump stations and the stopes
// (one column per strike position, a stripe per level), placed at their plan
// point on every change of the view (index.js calls layout()).

import { stateLabel, stateTone, stopeColor } from '../panels/dict.js';
import { fmt, isNum, withUnit } from '../panels/format.js';
import { S, clamp, set } from './svg.js';
import { shortName } from './model.js';

const DEG = 180 / Math.PI;

/** Shaft collar: a ring with a dot, the plan symbol of a shaft. */
function shaftSymbol() {
  return [S('circle', { class: 'rim', r: 5.5 }), S('circle', { class: 'core', r: 2 })];
}

/** Fan: a housing with its impeller ring; a cross when it has failed. */
function fanSymbol() {
  return [
    S('rect', { class: 'disc', x: -4.6, y: -4.6, width: 9.2, height: 9.2, rx: 2 }),
    S('circle', { class: 'blades', r: 2.3 }),
    S('path', { class: 'cross', d: 'M-3.4 -3.4L3.4 3.4M3.4 -3.4L-3.4 3.4' }),
  ];
}

export function buildMarks(ctx) {
  const { M, layers } = ctx;
  const things = () => (ctx.state ? ctx.state.things : {});
  const flowOf = (fanId) => {
    const fan = things()[fanId];
    return fan && fan.f && isNum(fan.f.air_flow_m3s) && fan.f.state !== 'planned' ? withUnit(fmt(fan.f.air_flow_m3s), 'м³/с') : '';
  };

  // ------------------------------------------------ shafts and their fans
  const fanOf = new Map(M.fans.filter((fan) => fan.airway).map((fan) => [fan.airway, fan]));
  for (const shaft of M.shafts) {
    const g = S('g', { class: 'pl-shaft', 'data-thing': shaft.id, 'data-state': shaft.planned ? 'planned' : '', 'data-bind': 'ventilation' },
      S('circle', { class: 'pl-hit-fill', r: 8 }), shaftSymbol());
    layers.marks.append(g);
    ctx.mark({ id: shaft.id, node: g, at: shaft.at, r: 7 });
    const fan = fanOf.get(shaft.id);
    const name = shortName(shaft.id) || '';
    const label = ctx.label({ id: shaft.id, at: shaft.at, name, priority: 3, sides: ['r', 't', 'b', 'l'], gap: 10 });
    ctx.on(shaft.id, (thing) => {
      set(g, { 'data-state': thing.f.state || '', 'data-tone': stateTone(thing.f.state, 'shaft') });
      const planned = thing.f.state === 'planned';
      label.set(planned ? `${name} (проект)` : name, fan ? flowOf(fan.id) : '', stateTone(thing.f.state, 'shaft'));
    });
    if (fan) {
      const fg = S('g', { class: 'pl-fan', 'data-thing': fan.id, 'data-state': fan.planned ? 'planned' : '', 'data-bind': 'ventilation' },
        S('circle', { class: 'pl-hit-fill', r: 6.5 }), fanSymbol());
      layers.marks.append(fg);
      ctx.mark({ id: fan.id, node: fg, at: shaft.at, dx: -12, r: 6 });
      ctx.on(fan.id, (thing) => set(fg, { 'data-state': thing.f.state || '', 'data-tone': stateTone(thing.f.state, 'main_fan') }));
    }
  }

  // ------------------------------------------- raises and other fans
  for (const raise of M.raises) {
    const g = S('g', { class: `pl-raise${raise.exhaust ? ' exhaust' : ''}`, 'data-thing': raise.id, 'data-state': raise.planned ? 'planned' : '', 'data-bind': raise.surface ? 'ventilation' : '' },
      S('circle', { class: 'pl-hit-fill', r: 6 }), S('circle', { class: 'rim', r: 3.6 }),
      raise.exhaust ? S('path', { class: 'arrow', d: 'M0 -1.6L0 -8M-2.4 -5.6L0 -8L2.4 -5.6' }) : null);
    (raise.surface ? layers.marks : layers.underMarks).append(g);
    ctx.mark({ id: raise.id, node: g, at: raise.at, r: 5, under: !raise.surface });
    if (raise.surface) {
      const name = shortName(raise.id) || '';
      const label = ctx.label({ id: raise.id, at: raise.at, name, priority: 6, sides: ['r', 'b', 't'], gap: 8, minK: 0.6 });
      ctx.on(raise.id, (thing) => label.set(name, withUnit(fmt(thing.f.air_flow_m3s), 'м³/с')));
    }
    ctx.on(raise.id, (thing) => set(g, { 'data-state': thing.f.state || '', 'data-tone': stateTone(thing.f.state, 'raise') }));
  }
  for (const fan of M.fans) {
    if (fanOf.get(fan.airway) === fan && M.shafts.some((shaft) => shaft.id === fan.airway)) continue;
    const g = S('g', { class: 'pl-fan', 'data-thing': fan.id, 'data-state': fan.planned ? 'planned' : '', 'data-bind': fan.surface ? 'ventilation' : '' },
      S('circle', { class: 'pl-hit-fill', r: 6.5 }), fanSymbol());
    (fan.surface ? layers.marks : layers.underMarks).append(g);
    const onRaise = M.raises.find((raise) => raise.id === fan.airway);
    ctx.mark({ id: fan.id, node: g, at: onRaise ? onRaise.at : fan.at, dx: onRaise ? -10 : 0, r: 6, under: !fan.surface });
    ctx.on(fan.id, (thing) => set(g, { 'data-state': thing.f.state || '', 'data-tone': stateTone(thing.f.state, 'main_fan') }));
  }

  // --------------------------------------------------------------- portals
  for (const decline of M.declines) {
    // The arch opens away from the decline, towards the road.
    const rotate = (Math.atan2(-Math.sin(decline.heading), -Math.cos(decline.heading)) * DEG - 90).toFixed(1);
    const g = S('g', { class: 'pl-portal', 'data-thing': decline.id, 'data-state': 'open' },
      S('circle', { class: 'pl-hit-fill', r: 9 }),
      S('g', { transform: `rotate(${rotate})` },
        S('path', { class: 'arch', d: 'M-6 5V-1A6 6 0 0 1 6 -1V5Z' }),
        S('path', { class: 'mouth', d: 'M-3 5V0.5A3 3 0 0 1 3 0.5V5Z' })),
      S('path', { class: 'bar', d: 'M-8 -8L8 8' }));
    layers.marks.append(g);
    ctx.mark({ id: decline.id, node: g, at: decline.portal, r: 8 });
    const name = `Портал ${shortName(decline.id) || ''}`;
    const label = ctx.label({ id: decline.id, at: decline.portal, name, priority: 2, sides: decline.token === 'tu2' ? ['b', 'r', 'l'] : ['l', 't', 'b'], gap: 11 });
    ctx.on(decline.id, (thing) => {
      set(g, { 'data-state': thing.f.state || '' });
      const onRamp = isNum(thing.f.trucks_on_ramp) ? `, на уклоне ${fmt(thing.f.trucks_on_ramp)}` : '';
      label.set(name, stateLabel(thing.f.state, 'decline') + onRamp, stateTone(thing.f.state, 'decline'));
    });
  }

  // ----------------------------------------------------- monitoring points
  for (const point of M.monitors) {
    const g = S('g', { class: 'pl-monitor', 'data-thing': point.id, 'data-bind': point.id.endsWith('sekisovka') ? 'water' : 'dewatering' },
      S('circle', { class: 'pl-hit-fill', r: 8 }),
      S('circle', { class: 'alarm', r: 7 }),
      S('path', { class: 'pin', d: 'M0 -5.5L5.5 0L0 5.5L-5.5 0Z' }));
    layers.marks.append(g);
    ctx.mark({ id: point.id, node: g, at: point.at, r: 7 });
    const name = shortName(point.id) || '';
    const label = ctx.label({ id: point.id, at: point.at, name, priority: 2, sides: ['r', 'l', 'b', 't'], gap: 10 });
    ctx.on(point.id, (thing) => {
      const f = thing.f;
      const tone = stateTone(f.state, 'monitoring_point');
      set(g, { 'data-tone': tone, 'data-state': f.state || '' });
      let value;
      if (isNum(f.intake_m3h) && f.intake_m3h > 0) value = `забор ${withUnit(fmt(f.intake_m3h), 'м³/ч')}`;
      else if (isNum(f.permit_use_pct) && (f.permit_use_pct > 0 || isNum(f.discharge_m3h) && f.discharge_m3h > 0)) value = `${fmt(f.permit_use_pct, 0)} % лимита сброса`;
      else value = stateLabel(f.state, 'monitoring_point');
      if (f.state === 'exceeded') value = `лимит превышен: ${fmt(f.permit_use_pct, 0)} %`;
      label.set(name, value, tone);
    });
  }

  // -------------------------------------------------------- pump stations
  const spots = new Map();
  for (const pump of M.pumps) {
    const key = `${Math.round(pump.at[0] / 20)}:${Math.round(pump.at[1] / 20)}`;
    const index = spots.get(key) || 0;
    spots.set(key, index + 1);
    const g = S('g', { class: 'pl-pump', 'data-thing': pump.id, 'data-state': pump.planned ? 'planned' : '' },
      S('circle', { class: 'pl-hit-fill', r: 6.5 }),
      S('rect', { class: 'box', x: -4.5, y: -4.5, width: 9, height: 9, rx: 1.5 }),
      S('path', { class: 'drop', d: 'M0 -2.6C1.6 -0.6 2.2 0.4 2.2 1.2A2.2 2.2 0 0 1 -2.2 1.2C-2.2 0.4 -1.6 -0.6 0 -2.6Z' }));
    layers.underMarks.append(g);
    ctx.mark({ id: pump.id, node: g, at: pump.at, dx: index * 12, r: 6, under: true });
    const name = shortName(pump.id) || '';
    const label = ctx.label({ id: pump.id, at: pump.at, name, priority: 8, under: true, sides: ['t', 'b'], gap: 9, minK: 1.4, cls: 'under' });
    ctx.on(pump.id, (thing) => {
      set(g, { 'data-state': thing.f.state || '', 'data-tone': stateTone(thing.f.state, 'pump_station') });
      label.set(name, thing.f.state === 'planned' ? 'проект' : `зумпф ${fmt(thing.f.sump_level_pct, 0)} %`, stateTone(thing.f.state, 'pump_station'));
    });
  }

  // --------------------------------------- stopes: a stripe for each level
  for (const [index, column] of M.columns.entries()) {
    const g = S('g', { class: 'pl-stopes' });
    const frame = S('rect', { class: 'frame' });
    g.append(frame);
    const stripes = column.stopes.map((stope) => {
      const rect = S('rect', { class: 'stripe', 'data-thing': stope.id, 'data-state': '' });
      g.append(rect);
      ctx.on(stope.id, (thing) => {
        const state = thing.f.state || '';
        set(rect, { 'data-state': state, fill: state === 'planned' ? 'none' : stopeColor(state), stroke: stopeColor(state) });
      });
      return rect;
    });
    // The first column names the levels; a tag opens the card of its level.
    const tags = index === 0 ? column.stopes.map((stope) => S('text', { class: 'tag', 'data-thing': stope.level }, fmt(stope.elevation, 0, { sign: true }))) : [];
    g.append(...tags);
    tags.forEach((tag, i) => ctx.on(column.stopes[i].level, (thing) => set(tag, { 'data-state': thing.f.state || '' })));
    layers.underMarks.append(g);
    ctx.mark({
      node: g, at: [column.x0, column.z], under: true, r: 0,
      layout(sx, sy, k) {
        const w = Math.max(16, (column.x1 - column.x0) * k);
        const h = clamp(column.stopes.length ? k * 6 : 0, 3.2, 7);
        const total = h * column.stopes.length;
        const x = sx;
        const y = sy - total / 2;
        set(frame, { x: x - 1, y: y - 1, width: w + 2, height: total + 2 });
        stripes.forEach((rect, i) => set(rect, { x, y: y + i * h + 0.4, width: w, height: Math.max(1, h - 0.8) }));
        const showTags = h >= 5.5;
        tags.forEach((tag, i) => {
          set(tag, { x: x - 4, y: y + i * h + h / 2 + 3 });
          tag.style.display = showTags ? '' : 'none';
        });
        return [x - (showTags ? 30 : 2), y - 2, x + w + 2, y + total + 2];
      },
    });
  }
  if (M.columns.length) {
    const first = M.columns[0];
    const last = M.columns[M.columns.length - 1];
    ctx.label({
      at: [(first.x0 + last.x1) / 2, first.z], name: 'Очистные блоки (схема)', value: 'полосы — горизонты сверху вниз',
      priority: 7, under: true, sides: ['t'], gap: 24, minK: 0.8, cls: 'under',
    });
  }
}
