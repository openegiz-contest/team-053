// Text of the sheet outside the mine body: the elevation ruler, the ruled level
// rows on both sides of the drawing (level name and air on the left; stopes,
// pump station and underground fans on the right), the mine summary line, the
// legend and the scale bar. Every label is a real <text> with a live value.

import { STOPE_ORDER, VEHICLE_MARKS, stateLabel, stateTone } from '../panels/dict.js';
import { fmt, isNum, withUnit } from '../panels/format.js';
import { S, line, set, setText, text } from './svg.js';
import { levelAir, levelLabel, shortName } from './model.js';
import { fitting } from './surface.js';
import { fanSymbol } from './underground.js';

/**
 * Name of a stope as text: the cell shows «150-1», the element reads «Блок 150-1»
 * (the word is in the DOM, not drawn, to keep three cells in a row).
 */
function stopeName(x, y, stope, cls) {
  return S('text', { x, y, class: cls }, S('tspan', { class: 'sx-pre' }, 'Блок '), stope.short);
}


export function buildTables(ctx) {
  const { L, M, layers, measure } = ctx;
  const { px, py, F, s } = L;
  const R = L.right;
  const m = (content, weight) => measure(content, F, weight);
  const lineH = L.lineH;
  const lines = L.lines;
  const base = (elevation) => py(elevation) - 3.5;
  const first = (elevation) => base(elevation) - (lines - 1) * lineH;
  // Fan cells and other two-line items use the two lines next to the rule.
  const upper = (elevation) => base(elevation) - (lines > 1 ? lineH : 0);

  // ------------------------------------------------------------------ ruler
  const rx = L.left.rulerX;
  const ruler = S('g', { class: 'sx-ruler' }, line(rx, L.yg, rx, py(M.bottom)));
  const mark = (elevation, long, drop = 0) => {
    const y = py(elevation);
    ruler.append(line(rx - (long ? 5 : 3), y, rx, y));
    if (long) {
      ruler.append(text(rx - 7, y + F * 0.34 + drop, fmt(elevation, 0, { sign: true }), { 'text-anchor': 'end' }));
    }
  };
  // The surface mark is written just under the ground line; a round mark too close to it is not numbered.
  for (let e = Math.ceil(M.bottom / 50) * 50; e < M.top; e += 50) {
    mark(e, e % 100 === 0 && (M.top - e) * s > F * 2.1);
  }
  mark(M.top, true, F * 0.62);
  if (s >= 0.8) {
    for (let e = Math.ceil(M.bottom / 10) * 10; e < M.top; e += 10) {
      if (e % 50 !== 0) ruler.append(line(rx - 1.5, py(e), rx, py(e)));
    }
  }
  layers.grid.append(ruler);

  // ------------------------------------------------------------- level rows
  const stopeLevels = new Set(M.stopes.map((stope) => stope.e));
  const stationLevels = new Set(M.stations.map((station) => station.e));
  const fanLevel = (fan) => Math.floor(fan.y / 10) * 10;
  const fanLevels = new Set(M.fans.filter((fan) => !fan.surface).map(fanLevel));
  const topStopeLevel = stopeLevels.size ? Math.max(...stopeLevels) : null;
  const headerLevel = topStopeLevel !== null
    ? M.levels.map((level) => level.e).filter((e) => e > topStopeLevel).sort((a, b) => a - b)[0] : undefined;
  const busy = (e) => stopeLevels.has(e) || stationLevels.has(e) || fanLevels.has(e);
  const summaryLevel = headerLevel !== undefined
    ? M.levels.map((level) => level.e).filter((e) => e > headerLevel && !busy(e)).sort((a, b) => a - b)[0] : undefined;

  for (const level of M.levels) {
    const y = py(level.e);
    layers.grid.append(line(rx, y, px(level.x0), y, { class: 'sx-guide' }));
    const full = stopeLevels.has(level.e) || fanLevels.has(level.e) || level.e === headerLevel || level.e === summaryLevel;
    if (full) {
      layers.grid.append(line(px(level.x1), y, R.x1, y, { class: 'sx-guide' }));
    } else {
      layers.grid.append(line(px(level.x1), y, R.x0 - 3, y, { class: 'sx-guide' }));
      if (stationLevels.has(level.e)) layers.grid.append(line(R.stationX, y, R.x1, y, { class: 'sx-guide' }));
    }

    const nameX = L.left.nameX + F * 0.85;
    const nameY = first(level.e);
    const value = lines === 3 ? text(nameX, nameY + lineH, '', { class: 'sx-value' })
      : text(L.left.valueX, nameY, '', { class: 'sx-value', 'text-anchor': 'end' });
    const sub = lines > 1 ? text(nameX, base(level.e), '', { class: 'sx-sub' }) : null;
    const g = S('g', { class: 'sx-label sx-row sx-obj', 'data-thing': level.id, 'data-kind': 'level' },
      S('rect', { class: 'sx-hit-fill', x: rx + 2, y: nameY - F, width: L.left.valueX - rx - 2, height: base(level.e) - nameY + F * 1.3 }),
      S('circle', { class: 'dot', cx: L.left.nameX + F * 0.3, cy: nameY - F * 0.34, r: F * 0.25 }),
      text(nameX, nameY, levelLabel(level.e), { class: 'sx-name' }), value, sub);
    layers.labels.append(g);
    ctx.on(level.id, (thing, state) => {
      const f = thing.f;
      const air = levelAir(thing, state, M);
      const short = air !== 'ok';
      const tone = f.state === 'flooded' ? 'flood' : f.state === 'planned' ? 'planned' : short ? 'warn' : 'idle';
      set(g, { 'data-tone': tone });
      const flow = withUnit(fmt(f.air_flow_m3s, 1), 'м³/с');
      const role = stateLabel(f.state, 'level');
      if (sub) {
        setText(value, flow);
        const lack = air === 'cut' ? (lines === 3 ? 'нет подачи' : 'подача воздуха нарушена')
          : lines === 3 ? 'мало воздуха' : `мало воздуха: нужно ${fmt(f.air_required_m3s, 1)}`;
        setText(sub, short ? lack : lines === 3 && f.state === 'mined_out' ? 'отработан' : role);
      } else {
        setText(value, f.state === 'flooded' ? role : flow);
      }
    });
  }

  // ---------------------------------------------------- stope cells (right)
  const nameW = m('−100-1', 600);
  for (const stope of M.stopes) {
    if (!L.inbox) break;
    // Large boxes carry their own text: name and ore left, the state under them.
    const x = px(stope.x0) + 5;
    const y = py(stope.y1) + F * 1.05;
    const value = text(x + m(stope.short, 600) + R.gap, y, '', { class: 'sx-value halo' });
    const state = text(x, y + lineH, '', { class: 'sx-sub halo' });
    const g = S('g', { class: 'sx-label sx-inbox sx-obj', 'data-thing': stope.id, 'data-kind': 'stope' },
      stopeName(x, y, stope, 'sx-name halo'), value, state);
    layers.labels.append(g);
    ctx.on(stope.id, (thing) => {
      const f = thing.f;
      setText(value, withUnit(fmt(isNum(f.ore_remaining_t) ? f.ore_remaining_t / 1000 : NaN, 1), 'тыс. т'));
      setText(state, stateLabel(f.state, 'stope'));
    });
  }
  for (const stope of M.stopes) {
    if (L.inbox || stope.n > R.cols.length) continue;
    const x = R.cols[stope.n - 1];
    const top = first(stope.e);
    const value = lines === 3 ? text(x + R.swatch, top + lineH, '', { class: 'sx-value' })
      : text(x + R.chip, top, '', { class: 'sx-value', 'text-anchor': 'end' });
    let state = null;
    if (lines > 1) state = text(x + R.swatch, base(stope.e), '', { class: 'sx-sub' });
    else if (L.variant === 'oneState') state = text(x + R.swatch + nameW + R.gap, top, '', { class: 'sx-sub' });
    const side = F * 0.74;
    const g = S('g', { class: 'sx-label sx-chip sx-obj', 'data-thing': stope.id, 'data-kind': 'stope', 'data-state': stope.planned ? 'planned' : 'standby' },
      S('rect', { class: 'sx-hit-fill', x: x - 2, y: top - F, width: R.chip + 4, height: base(stope.e) - top + F * 1.3 }),
      S('rect', { class: 'swatch', x, y: top - side + 0.5, width: side, height: side }),
      stopeName(x + R.swatch, top, stope, 'sx-name'), value, state);
    layers.labels.append(g);
    ctx.on(stope.id, (thing) => {
      const f = thing.f;
      const kt = fmt(isNum(f.ore_remaining_t) ? f.ore_remaining_t / 1000 : NaN, 1);
      set(g, { 'data-state': f.state || 'standby' });
      setText(value, L.variant === 'oneState' ? kt : withUnit(kt, 'тыс. т'));
      if (state) setText(state, stateLabel(f.state, 'stope'));
    });
  }
  if (headerLevel !== undefined) {
    const y = base(headerLevel);
    const unit = L.variant === 'oneState' ? 'остаток руды, тыс. т' : 'остаток руды';
    if (!L.inbox) layers.labels.append(text(R.cols[0], y, `ОЧИСТНЫЕ БЛОКИ · ${unit}`, { class: 'sx-head' }));
    layers.labels.append(
      text(R.stationX, y, fitting(['ВОДООТЛИВ · уровень в водосборнике, откачка', 'ВОДООТЛИВ · уровень, откачка', 'ВОДООТЛИВ'],
        R.stationW, (content) => measure(content, F * 0.9) * 1.06), { class: 'sx-head' }));
  }

  // ------------------------------------------------- pump stations (right)
  for (const station of M.stations) {
    const x = R.stationX;
    const textX = x + F * 0.85;
    const top = first(station.e);
    // Like a stope cell: name and figures on the first line, the state word under them.
    const title = 'насосная';
    const valueX = lines === 3 ? textX : textX + m(title, 600) + F * 0.5;
    const value = text(valueX, lines === 3 ? top + lineH : top, '', { class: 'sx-value' });
    const sub = lines > 1 ? text(textX, base(station.e), '', { class: 'sx-sub' }) : null;
    const g = S('g', { class: 'sx-label sx-chip sx-obj', 'data-thing': station.id, 'data-kind': 'pump_station' },
      S('rect', { class: 'sx-hit-fill', x: x - 2, y: top - F, width: R.stationW, height: base(station.e) - top + F * 1.3 }),
      S('circle', { class: 'dot', cx: x + F * 0.3, cy: top - F * 0.34, r: F * 0.25 }),
      text(textX, top, title, { class: 'sx-name' }), value, sub);
    layers.labels.append(g);
    const room = R.x1 - valueX;
    ctx.on(station.id, (thing) => {
      const f = thing.f;
      const state = stateLabel(f.state, 'pump_station');
      set(g, { 'data-tone': stateTone(f.state, 'pump_station') });
      if (f.state === 'planned') {
        setText(value, state);
        if (sub) setText(sub, levelLabel(station.e));
        return;
      }
      const sump = withUnit(fmt(f.sump_level_pct), '%');
      const flow = f.pumped_m3h > 0 ? withUnit(fmt(f.pumped_m3h), 'м³/ч') : null;
      const down = f.state === 'failed' || f.state === 'alarm_high';
      const overflow = f.hours_to_overflow > 0 && f.state !== 'pumping'
        ? `до переполнения ${withUnit(fmt(f.hours_to_overflow, 1), 'ч')}` : null;
      const fit = (lists, width) => fitting(lists.map((parts) => parts.filter(Boolean).join(' · ')), width, (content) => m(content));
      if (sub) {
        setText(value, fit([[sump, flow], [sump]], room));
        setText(sub, fit([[state, overflow], [state]], R.x1 - textX));
      } else {
        setText(value, fit(down ? [[state, sump, overflow], [state, sump], [sump, flow], [sump]]
          : [[sump, flow || state], [sump, flow], [sump]], room));
      }
    });
  }

  // --------------------------------------------- underground fans (right)
  const cursor = {};
  for (const fan of M.fans.filter((item) => !item.surface)) {
    const e = fanLevel(fan);
    const x = cursor[e] === undefined ? R.cols[0] : cursor[e];
    const top = upper(e);
    const title = `вент. ${shortName(fan.id) || ''}`.trim();
    const textX = x + F * 1.15;
    const titleW = m(title, 600);
    const valueX = lines > 1 ? textX : textX + titleW + F * 0.5;
    const value = text(valueX, base(e), '', { class: 'sx-value' });
    const width = F * 1.15 + (lines > 1 ? Math.max(titleW, m('в работе · 102 м³/с')) : titleW + F * 0.5 + m('102 м³/с'));
    const g = S('g', { class: 'sx-label sx-chip sx-fan sx-obj', 'data-thing': fan.id, 'data-kind': 'main_fan', 'data-state': fan.planned ? 'planned' : '' },
      S('rect', { class: 'sx-hit-fill', x: x - 2, y: top - F, width: width + 4, height: base(e) - top + F * 1.3 }),
      fanSymbol(x + F * 0.45, top - F * 0.34, F * 0.44),
      text(textX, top, title, { class: 'sx-name' }), value);
    layers.labels.append(g);
    cursor[e] = x + width + F * 1.8;
    ctx.on(fan.id, (thing) => {
      const f = thing.f;
      const state = stateLabel(f.state, 'main_fan');
      set(g, { 'data-state': f.state || '', 'data-tone': stateTone(f.state, 'main_fan') });
      const flow = withUnit(fmt(f.air_flow_m3s, 0), 'м³/с');
      setText(value, f.state !== 'running' ? state : lines > 1 ? `${state} · ${flow}` : flow);
    });
  }

  // ---------------------------------- declines (first line under the ground)
  const bandY = L.yg + F * 2.55;
  const fanTop = Math.min(...[...fanLevels].map((e) => upper(e) - F), py(M.levels[0] ? M.levels[0].e : M.bottom) - F);
  if (M.declines.length && bandY + 2 < fanTop) {
    const lead = 'Уклоны:';
    const half = F * 0.85;
    const need = half * 2 + F * 1.5 + m('ТУ-1', 600) + m('открыт · на уклоне: 12');
    // Side by side on one line, or one under another where the gutter is narrow.
    const stacked = (R.x1 - R.x0 - m(lead) - F * 0.8) / M.declines.length < need
      && bandY + lineH * (M.declines.length - 1) + 2 < fanTop;
    if (!stacked) layers.labels.append(text(R.x0, bandY, lead, { class: 'sx-sub' }));
    const start = stacked ? R.x0 : R.x0 + m(lead) + F * 0.8;
    const slot = stacked ? R.x1 - start : (R.x1 - start) / M.declines.length;
    M.declines.forEach((decline, index) => {
      const x = stacked ? start : start + Math.min(slot, m('открыт · на уклоне: 12, ждут: 3') + F * 6.5) * index;
      const lineY = stacked ? bandY + lineH * index : bandY;
      const double = index % 2 === 1;
      const title = shortName(decline.id) || decline.token;
      const titleX = x + half * 2 + F * 0.5;
      const valueX = titleX + m(title, 600) + F * 0.45;
      const value = text(valueX, lineY, '', { class: 'sx-value' });
      const icon = S('g', {
        class: `sx-decline ${double ? 'double' : 'single'}`, 'data-state': 'open',
        transform: `translate(${(x + half).toFixed(1)} ${(lineY - F * 0.34).toFixed(1)})`,
      }, S('path', { class: 'way', d: `M${-half} 0H${half}` }),
      double ? S('path', { class: 'core', d: `M${-half} 0H${half}` }) : null);
      const g = S('g', { class: 'sx-label sx-obj', 'data-thing': decline.id, 'data-kind': 'decline' },
        S('rect', { class: 'sx-hit-fill', x: x - 2, y: lineY - F, width: slot - F, height: F * 1.3 }),
        icon, text(titleX, lineY, title, { class: 'sx-name' }), value);
      layers.labels.append(g);
      const room = x + slot - F - valueX;
      ctx.on(decline.id, (thing) => {
        const f = thing.f;
        const state = stateLabel(f.state, 'decline');
        set(icon, { 'data-state': f.state || 'open' });
        const waiting = f.trucks_waiting_in_bays > 0 ? `, ждут: ${fmt(f.trucks_waiting_in_bays)}` : '';
        const candidates = f.state === 'closed'
          ? [`${state} · движения нет`, state]
          : [`${state} · на уклоне: ${fmt(f.trucks_on_ramp)}${waiting}`, `${state} · на уклоне: ${fmt(f.trucks_on_ramp)}`,
            `${state} · ${fmt(f.trucks_on_ramp)}`];
        setText(value, fitting(candidates, room, (content) => m(content)));
      });
    });
  }

  // ------------------------------- mine summary (the free row above the header)
  if (summaryLevel !== undefined) {
    // One line, or two where the rows are tall: state and air, then water.
    const y = upper(summaryLevel);
    const mineId = ctx.id('mine');
    const title = 'Рудник:';
    const value = text(R.x0 + m(title, 600) + F * 0.5, y, '', { class: 'sx-value' });
    const second = lines > 1 ? text(R.x0, base(summaryLevel), '', { class: 'sx-value' }) : null;
    const g = S('g', { class: 'sx-label sx-obj sx-summary', 'data-thing': mineId, 'data-kind': 'mine' },
      S('rect', { class: 'sx-hit-fill', x: R.x0 - 2, y: y - F, width: R.x1 - R.x0, height: base(summaryLevel) - y + F * 1.3 }),
      text(R.x0, y, title, { class: 'sx-name' }), value, second);
    layers.labels.append(g);
    const room = R.x1 - R.x0 - m(title, 600) - F * 0.5;
    ctx.on(mineId, (thing) => {
      const f = thing.f;
      set(g, { 'data-tone': stateTone(f.state, 'mine') });
      const state = stateLabel(f.state, 'mine');
      const air = `воздух ${fmt(f.air_demand_m3s, 0)} из ${withUnit(fmt(f.air_supply_m3s, 0), 'м³/с')}`;
      const held = f.units_held_vent > 0 ? `ждут воздуха: ${fmt(f.units_held_vent)}` : null;
      const flood = f.flood_volume_m3 > 0 ? `затоплено ${withUnit(fmt(f.flood_volume_m3), 'м³')}` : null;
      const inflow = `приток ${withUnit(fmt(f.inflow_m3h), 'м³/ч')}`;
      const pumped = `откачка ${withUnit(fmt(f.pumped_m3h), 'м³/ч')}`;
      const join = (lists) => lists.map((parts) => parts.filter(Boolean).join(' · '));
      if (second) {
        setText(value, fitting(join([[state, air, held], [state, held || air], [held || state]]), room, (content) => m(content)));
        setText(second, fitting(join([[inflow, pumped, flood], [flood || inflow, pumped], [flood || pumped]]),
          R.x1 - R.x0, (content) => m(content)));
      } else {
        setText(value, fitting(join([[state, air, held, inflow, pumped, flood], [state, air, held, flood || inflow],
          [state, held || flood || air], [flood || held || state]]), room, (content) => m(content)));
      }
    });
  }

  // ----------------------------------------------------------------- legend
  const lowStope = stopeLevels.size ? Math.min(...stopeLevels) : M.bottom;
  const box = L.inbox ? {
    // Under the drawing, across the sheet.
    x0: L.left.nameX, x1: L.W - 8,
    y0: py(M.bottom) + L.padBottom + F * 1.3, y1: py(M.bottom) + L.padBottom + L.legendH,
  } : {
    x0: R.cols[0], x1: Math.max(R.stationX - F, R.cols[0] + 3 * R.chip),
    // Down to the foot of the drawing, or further where the sheet has room below it.
    y0: py(lowStope) + F * 1.6, y1: Math.max(py(M.bottom) + L.padBottom - 3, L.H - 32),
  };
  const legend = S('g', { class: 'sx-legend' });
  const iconW = F * 1.9;
  const titleW = m('Выработки') + F * 0.9;
  let cx = box.x0;
  let cy = box.y0;
  let open = true;
  const place = (width) => {
    if (cx + width > box.x1 && cx > box.x0 + titleW) {
      cx = box.x0 + titleW;
      cy += lineH * 1.08;
    }
    if (cy > box.y1) open = false;
    return open;
  };
  const group = (title, items) => {
    if (!open) return;
    if (cx !== box.x0) {
      cx = box.x0;
      cy += lineH * 1.08;
    }
    if (cy > box.y1) {
      open = false;
      return;
    }
    legend.append(text(cx, cy, title, { class: 'sx-note' }));
    cx += titleW;
    for (const [icon, label] of items) {
      const width = iconW + m(label) + F * 1.1;
      if (!place(width)) return;
      const holder = S('g', { transform: `translate(${(cx + iconW / 2 - F * 0.2).toFixed(1)} ${(cy - F * 0.34).toFixed(1)})` }, icon);
      legend.append(holder, text(cx + iconW, cy, label, { class: 'sx-key' }));
      cx += width;
    }
  };
  const tw = F * 0.92;
  const th = F * 0.5;
  const truck = (load, ring) => S('g', { class: 'sx-unit haul_truck', 'data-load': load, 'data-state': 'legend', 'data-ring': ring || null },
    ring ? S('circle', { class: 'ring', r: F * 0.6 }) : null,
    S('rect', { class: 'mark', x: -tw / 2, y: -th / 2, width: tw, height: th, rx: 1 }));
  const tri = F * 0.36;
  const half = iconW / 2 - 1;
  const way = (cls, state, double) => S('g', { class: `sx-decline ${double ? 'double' : 'single'} ${cls || ''}`, 'data-state': state },
    S('path', { class: 'way', d: `M${-half} 0H${half}` }), double ? S('path', { class: 'core', d: `M${-half} 0H${half}` }) : null);

  group('Блоки', STOPE_ORDER.map((token) => [
    S('g', { class: 'sx-chip', 'data-state': token },
      S('rect', { class: 'swatch', x: -F * 0.37, y: -F * 0.37, width: F * 0.74, height: F * 0.74 })),
    stateLabel(token, 'stope')]));
  group('Техника', [
    [truck('loaded'), 'самосвал с рудой'],
    [truck('empty'), 'порожний'],
    [truck('empty', 'warn'), VEHICLE_MARKS.held],
    [truck('empty', 'fail'), VEHICLE_MARKS.repair],
    [S('g', { class: 'sx-unit lhd', 'data-state': 'legend' }, S('circle', { class: 'mark', r: F * 0.3 })), 'ПДМ'],
    [S('g', { class: 'sx-unit drill_rig', 'data-state': 'legend' },
      S('path', { class: 'mark', d: `M${-tri} ${tri * 0.8}L0 ${-tri}L${tri} ${tri * 0.8}Z` })), 'буровая'],
  ]);
  group('Выработки', [
    [way('', 'open', false), 'уклон ТУ-1'],
    [way('', 'open', true), 'уклон ТУ-2'],
    [way('', 'closed', false), 'уклон закрыт'],
    [S('g', { class: 'sx-airway', 'data-flow': '1' },
      S('path', { class: 'way', d: `M${-half} 0H${half}` }),
      S('path', { class: 'flow', d: `M${-half} 0H${half}`, 'stroke-width': 2.4 })), 'воздух, по стрелке'],
    [S('g', { class: 'sx-station', 'data-flow': '1', 'data-tone': 'ok' },
      S('path', { class: 'pipe', d: `M${-half} 0H${half}` }),
      S('path', { class: 'pipe-flow', d: `M${-half} 0H${half}` })), 'водоотлив'],
    [S('g', { class: 'sx-airway' }, S('path', { class: 'way design', d: `M${-half} 0H${half}` })), 'проект'],
    M.pit ? [S('path', { class: 'sx-pit', d: `M${-half} 0H${half}` }), 'контур карьера, в проекции'] : null,
  ].filter(Boolean));
  layers.labels.append(legend);

  // -------------------------------------------------------------- scale bar
  const by = py(M.bottom) + 6;
  const bx = px(M.mineX0 + 45);
  const unit = 100 * s;
  const textY = by + 4 + F * 1.0;
  const bar = S('g', { class: 'sx-scale' },
    S('path', { d: `M${bx} ${by}v4M${bx + unit} ${by}v4M${bx + 2 * unit} ${by}v4M${bx} ${by + 4}h${2 * unit}` }),
    text(bx, textY, '0', { 'text-anchor': 'middle' }),
    text(bx + unit, textY, '100', { 'text-anchor': 'middle' }),
    text(bx + 2 * unit, textY, '200 м', { 'text-anchor': 'middle' }));
  const noteX = bx + 2 * unit + m('200 м') / 2 + F * 1.5;
  const note = fitting([
    'продольная проекция, вид с юга · вертикальный и горизонтальный масштабы равны',
    'вид с юга · масштабы по осям равны', 'вид с юга', ''],
  px(M.mineX1) - noteX - F * 2, (content) => measure(content, F * 0.92));
  bar.append(text(noteX, textY, note, { class: 'sx-note' }),
    text(px(M.mineX0) + 2, textY, 'З', { class: 'sx-note' }),
    text(px(M.mineX1) - 2, textY, 'В', { class: 'sx-note', 'text-anchor': 'end' }));
  layers.labels.append(bar);
}
