// The surface strip on the ground line: plant lines, ROM stockpile, settling
// ponds, monitoring points, and the tailings dams. Objects east of the workings
// keep their real x (compressed with the strip when it does not fit to scale,
// layout.js) and stand on the ground line of the section; heights are true
// where they read and schematic where they would be too small. The tailings
// facility lies 1.5 km north-east and overlaps the pit, the ponds and the plant
// in projection, so it takes the east end of the sheet past a break mark, as a
// row of dams in their west-to-east order on their own ground, with the
// distance and bearing from the geometry under it.
// Labels: two text lines above the structures, moved apart where they touch;
// the ponds and the monitoring points are labelled in rows under the ground.

import { stateLabel, stateTone } from '../panels/dict.js';
import { fmt, isNum, withUnit } from '../panels/format.js';
import { S, clamp, line, pathOf, set, setText, text } from './svg.js';
import { shortName } from './model.js';
import { maxBetween, minBetween, soilBand } from './underground.js';

// The shortest names of the monitoring points, where two labels share a row.
const COMPACT = { 'mon-volchevka': 'руч. Волчевка', 'mon-sekisovka': 'р. Секисовка' };
const COMPASS = ['к северу', 'к северо-востоку', 'к востоку', 'к юго-востоку', 'к югу', 'к юго-западу', 'к западу', 'к северо-западу'];

/** «осталось 3,1 года»: the noun follows the fraction. */
function yearsLeft(value) {
  if (!isNum(value)) return null;
  if (value >= 20) {
    const n = Math.round(value);
    const word = n % 10 === 1 && n % 100 !== 11 ? 'год'
      : [2, 3, 4].includes(n % 10) && ![12, 13, 14].includes(n % 100) ? 'года' : 'лет';
    return `осталось ${fmt(n)} ${word}`;
  }
  return `осталось ${fmt(value, 1)} года`;
}

/** The first candidate that fits the width; the last one if none does. */
export function fitting(candidates, width, measureAt) {
  return candidates.find((candidate) => measureAt(candidate) <= width) || candidates[candidates.length - 1];
}

export function buildSurface(ctx) {
  const { L, M, layers, measure } = ctx;
  const { px, py, F, yg, structH, s } = L;
  const m = (content, weight) => measure(content, F, weight);
  const ground = (x) => L.groundY(x);
  const tailX0 = M.dams.length ? L.tail.x0 : L.W - 8;

  // ------------------------------------------------------------------ plant
  if (M.plant) {
    const x0 = px(M.plant.x0);
    const x1 = px(M.plant.x1);
    const base = ground((M.plant.x0 + M.plant.x1) / 2);
    const lineH = (item) => clamp((item.height || 16) * s, F * 1.1, structH * 0.85);
    const hp = Math.max(...M.plantLines.map(lineH), F * 1.1);
    const plantGroup = S('g', { class: 'sx-plant sx-obj', 'data-thing': M.plant.id },
      S('rect', { class: 'frame', x: x0, y: base - hp - 3, width: Math.max(4, x1 - x0), height: hp + 3 }),
      line(x0, base, x1, base, { class: 'pad' }));
    layers.back.append(plantGroup);
    ctx.reg(M.plant.id, (x0 + x1) / 2, base - hp / 2);
    for (const item of M.plantLines) {
      const h = lineH(item);
      const x = px(item.x0) + 0.5;
      const w = Math.max(2, px(item.x1) - px(item.x0) - 1);
      const fill = S('rect', { class: 'fill', x: x + 0.5, width: Math.max(1, w - 1), y: base, height: 0 });
      const g = S('g', { class: 'sx-pline sx-obj', 'data-thing': item.id, 'data-state': item.planned ? 'planned' : '' },
        S('rect', { class: 'box', x, y: base - h, width: w, height: h }), fill);
      if (w >= F * 0.75) {
        g.append(text(x + w / 2, base - h / 2 + F * 0.3, String(item.n), { class: 'sx-tag small', 'text-anchor': 'middle' }));
      }
      layers.water.append(g);
      ctx.reg(item.id, x + w / 2, base - h / 2);
      ctx.on(item.id, (thing) => {
        const f = thing.f;
        const share = isNum(f.utilisation_pct) ? clamp(f.utilisation_pct / 100, 0, 1) : 0;
        const filled = (h - 1) * share;
        set(fill, { y: base - 0.5 - filled, height: filled });
        set(g, { 'data-state': f.state || '', 'data-tone': stateTone(f.state, 'plant_line') });
      });
    }
    const label = ctx.skyLabel({
      thing: M.plant.id, kind: 'plant', x: (x0 + x1) / 2, top: base - hp - 3, sample: ['Фабрика', '124,1 т/ч'],
    });
    ctx.on(M.plant.id, (thing) => {
      set(plantGroup, { 'data-tone': stateTone(thing.f.state, 'plant') });
      label.set('Фабрика', withUnit(fmt(thing.f.feed_tph, 1), 'т/ч'));
    });
  }

  // -------------------------------------------------------------- stockpile
  if (M.rom) {
    const x = px(M.rom.x);
    const base = ground(M.rom.x);
    const heap = S('path', { class: 'heap' });
    const g = S('g', { class: 'sx-rom sx-obj', 'data-thing': M.rom.id }, heap);
    if (M.plant) {
      // The conveyor to the plant (schematic route).
      const to = M.plant.x0 > M.rom.x ? M.plant.x0 : M.plant.x1;
      layers.back.append(line(x, base - structH * 0.2, px(to), ground(to) - structH * 0.45, { class: 'sx-conveyor' }));
    }
    layers.water.append(g);
    ctx.reg(M.rom.id, x, base - structH * 0.3);
    const label = ctx.skyLabel({
      thing: M.rom.id, kind: 'rom_stockpile', x, top: base - structH * 0.75, sample: ['Рудный склад', '34,0 тыс. т'],
    });
    const fullH = clamp((M.rom.height || 20) * s, F * 0.9, structH * 0.75);
    ctx.on(M.rom.id, (thing) => {
      const f = thing.f;
      const share = isNum(f.tonnes) && M.rom.ref > 0 ? clamp(f.tonnes / M.rom.ref, 0.03, 1.7) : 1;
      const k = Math.sqrt(share);
      const half = clamp((px(M.rom.x + M.rom.radius) - px(M.rom.x - M.rom.radius)) / 2, F * 0.9, F * 2.4) * k;
      const h = fullH * k;
      set(heap, { d: `M${(x - half).toFixed(1)} ${base.toFixed(1)}L${x} ${(base - h).toFixed(1)}L${(x + half).toFixed(1)} ${base.toFixed(1)}Z` });
      set(g, { 'data-tone': stateTone(f.state, 'rom_stockpile') });
      label.set('Рудный склад', withUnit(fmt(isNum(f.tonnes) ? f.tonnes / 1000 : NaN, 1), 'тыс. т'));
    });
  }

  // ---------------------------------------------- ponds and monitoring points
  // Their labels are rows under the ground, the easternmost on the top row, so
  // that every leader runs west of the rows above it.
  const rows = [];
  if (M.ponds.length) {
    for (const pond of M.ponds) {
      const x0 = px(pond.x0);
      const w = Math.max(4, px(pond.x1) - x0);
      const y = ground((pond.x0 + pond.x1) / 2);
      const g = S('g', { class: 'sx-pond sx-obj', 'data-thing': pond.id },
        S('rect', { class: 'basin', x: x0, y: y - 2.5, width: w, height: 5.5 }));
      layers.water.append(g);
      ctx.reg(pond.id, x0 + w / 2, y);
    }
    const first = M.ponds[0];
    const last = M.ponds[M.ponds.length - 1];
    const cx = (first.x0 + last.x1) / 2;
    rows.push({ id: first.id, kind: 'settling_pond', ax: px(cx), ay: ground(cx) + 3, title: 'илоотстойники' });
  }
  for (const point of M.monitors) {
    const x = px(point.x);
    const y = ground(point.x);
    const r = F * 0.45;
    const marker = S('path', { class: 'pin', d: `M${x} ${y - r}L${x + r} ${y}L${x} ${y + r}L${x - r} ${y}Z` });
    const g = S('g', { class: 'sx-monitor sx-obj', 'data-thing': point.id, 'data-kind': 'monitoring_point' },
      S('circle', { class: 'sx-hit-fill', cx: x, cy: y, r: r + 4 }), marker);
    layers.water.append(g);
    ctx.reg(point.id, x, y);
    rows.push({ id: point.id, kind: 'monitoring_point', ax: x, ay: y + r, monitor: true });
  }
  const stripX0 = px(M.mineX1);
  const lowest = rows.length ? maxBetween(ctx.groundPx, stripX0, L.eastPx1) : yg;
  const step = L.lineH * 1.05;
  const rowY = (k) => lowest + F * 1.3 + k * step;
  // The tailings caption carries the distance and bearing where it has room; else a note under the tailings does.
  const place = tailingsPlace(M);
  const captionRoom = L.W - 8 - tailX0;
  const noteNeeded = M.dams.length > 0 && !!place
    && m(`Хвостовое хозяйство (${place.where}):`, 600) + F * 0.5 + m('осталось 3,1 года') > captionRoom;
  const tailNoteY = M.dams.length
    ? py(Math.min(...M.dams.map((dam) => (isNum(dam.bottom) ? dam.bottom : M.top)))) + F * 1.3 : null;
  const limitAt = (y) => (noteNeeded && Math.abs(y - tailNoteY) < L.lineH ? tailX0 - F : L.right.x1);
  // The rows end above the first row of the right gutter, with a line left for the declines.
  const firstRow = M.levels.length ? py(M.levels[0].e) - 3.5 - (L.lines - 1) * L.lineH - F : L.H;
  const bottomLimit = firstRow - L.lineH * 1.3;
  const minState = m(stateLabel('exceeded', 'monitoring_point'));
  for (const row of rows) {
    const full = row.monitor ? shortName(row.id) || 'пост' : row.title;
    const compact = row.monitor ? COMPACT[row.id.slice(row.id.indexOf(':') + 1)] || full : row.title;
    const value = row.monitor ? minState : m('1 000 м³/ч');
    row.needFull = m(full + ':', 600) + F * 0.4 + value;
    row.needCompact = m(compact + ':', 600) + F * 0.4 + value;
    row.compactTitle = compact;
  }
  // Layouts in the order of preference: one row where the labels fit side by
  // side (west to east, leaders slanting to them), else one row each, the
  // easternmost on top; the ponds' row is left out where the rows do not fit
  // above the gutter (their inflow is in the mine summary and the hover card).
  const pack = (items, compact) => {
    const sorted = items.slice().sort((a, b) => a.ax - b.ax);
    let cursor = -Infinity;
    const out = sorted.map((row) => {
      const need = compact ? row.needCompact : row.needFull;
      const start = Math.max(row.ax + F * 0.55, cursor);
      cursor = start + need + F * 1.4;
      return { row, start, need, y: rowY(0) };
    });
    const last = out[out.length - 1];
    if (!last || last.start + last.need > limitAt(rowY(0))) return null;
    out.forEach((item, index) => {
      item.limit = index + 1 < out.length ? out[index + 1].start - F * 1.4 : limitAt(item.y);
    });
    return out;
  };
  const stack = (items, anyway) => {
    const sorted = items.slice().sort((a, b) => b.ax - a.ax);
    if (!anyway && sorted.length && rowY(sorted.length - 1) > bottomLimit) return null;
    return sorted.map((row, k) => ({ row, start: row.ax + F * 0.55, y: rowY(k), limit: limitAt(rowY(k)) }));
  };
  const monitorsOnly = rows.filter((row) => row.monitor);
  const placedRows = pack(rows, false) || stack(rows) || pack(rows, true)
    || pack(monitorsOnly, false) || stack(monitorsOnly) || pack(monitorsOnly, true)
    || stack(monitorsOnly, true);
  for (const item of placedRows) {
    Object.assign(item.row, { y: item.y, start: item.start, limit: item.limit });
    item.row.compact = item.row.needFull > item.limit - item.start;
  }
  rows.splice(0, rows.length, ...placedRows.map((item) => item.row));
  rows.forEach((row) => {
    const { y, start } = row;
    const room = row.limit - start;
    const leader = pathOf([[row.ax, row.ay + 1], [row.ax, Math.max(row.ay + 1, y - F * 1.6)], [start - F * 0.25, y - F * 0.85]]);
    row.leader = leader;
    const name = text(start, y, '', { class: 'sx-name halo' });
    const value = text(start, y, '', { class: 'sx-value halo' });
    const g = S('g', { class: 'sx-label sx-obj', 'data-thing': row.id, 'data-kind': row.kind },
      S('path', { class: 'sx-leader', d: leader }),
      S('rect', { class: 'sx-hit-fill', x: start - 2, y: y - F, width: Math.max(10, room), height: F * 1.3 }),
      name, value);
    layers.labels.append(g);
    ctx.on(row.id, (thing) => {
      const f = thing.f;
      let title;
      let candidates;
      if (row.monitor) {
        set(g, { 'data-tone': stateTone(f.state, 'monitoring_point') });
        const full = shortName(row.id) || thing.name;
        const state = stateLabel(f.state, 'monitoring_point');
        const body = thing.attrs && thing.attrs.water_body;
        title = row.compact ? row.compactTitle : !body || m(full + ':', 600) + F * 0.4 + m(state) <= room ? full : body;
        const flow = f.discharge_m3h > 0 ? `сброс ${withUnit(fmt(f.discharge_m3h, 1), 'м³/ч')}`
          : f.intake_m3h > 0 ? `водозабор ${withUnit(fmt(f.intake_m3h, 1), 'м³/ч')}` : null;
        const permit = isNum(f.permit_use_pct) && f.permit_use_pct > 0 ? `${fmt(f.permit_use_pct)} % разрешённого` : null;
        candidates = [[state, flow, permit], [state, flow], [state]].map((parts) => parts.filter(Boolean).join(' · '));
      } else {
        title = row.title;
        candidates = [withUnit(fmt(f.inflow_m3h), 'м³/ч')];
      }
      const nameW = m(title + ':', 600) + F * 0.4;
      setText(name, title + ':');
      setText(value, fitting(candidates, room - nameW, (content) => m(content)));
      set(value, { x: start + nameW });
    });
  });
  // The rows below the ground end here; the decline row of the right gutter starts under them.
  ctx.underBottom = rows.length ? Math.max(...rows.map((row) => row.y)) : null;

  // ------------------------------------------------- labels above the strip
  const sky = ctx.sky.slice().sort((a, b) => a.x - b.x);
  for (const label of sky) {
    label.w = Math.max(m(label.sample[0], 600), m(label.sample[1]));
    label.c = label.x;
  }
  const pad = F * 0.9;
  const lowBound = 3;
  const highBound = M.dams.length ? tailX0 - F * 1.6 : L.W - 8;
  for (let pass = 0; pass < 80; pass += 1) {
    for (let i = 1; i < sky.length; i += 1) {
      const overlap = (sky[i - 1].c + sky[i - 1].w / 2 + pad) - (sky[i].c - sky[i].w / 2);
      if (overlap > 0) {
        sky[i - 1].c -= overlap / 2;
        sky[i].c += overlap / 2;
      }
    }
    if (sky.length) {
      sky[0].c = Math.max(sky[0].c, lowBound + sky[0].w / 2);
      const lastLabel = sky[sky.length - 1];
      lastLabel.c = Math.min(lastLabel.c, highBound - lastLabel.w / 2);
    }
  }
  for (const label of sky) {
    const leaderTop = L.skyLine2 + 3;
    const nodes = [
      text(label.c, L.skyLine1, label.lines[0], { class: 'sx-name', 'text-anchor': 'middle' }),
      text(label.c, L.skyLine2, label.lines[1], { class: 'sx-value', 'text-anchor': 'middle' }),
    ];
    const g = S('g', { class: 'sx-label sky', 'data-thing': label.thing, 'data-kind': label.kind });
    if (label.top - 2 - leaderTop > 2.5) {
      g.append(S('path', { class: 'sx-leader', d: pathOf([[label.c, leaderTop], [label.x, label.top - 2]]) }));
    }
    g.append(...nodes);
    layers.labels.append(g);
    label.nodes = nodes;
  }

  groundCaption(ctx, sky);

  // --------------------------------------------------------------- tailings
  if (M.dams.length) {
    const gap = L.tail.gap;
    const tx0 = L.tail.x0;
    const available = L.tail.x1 - tx0;
    const sample = (dam) => (dam.planned ? stateLabel('planned', 'tailings_dam') : '100 %');
    const beside = M.dams.map((dam) => m(shortName(dam.id) || '№ 0', 600) + F * 0.4 + m(sample(dam)) + 5);
    // In a narrow strip the number stands above the dam and the value inside it;
    // in the narrowest the dam shows its fill only (the value is in the hover card).
    const within = M.dams.map((dam) => Math.max(m(shortName(dam.id) || '№ 0', 600), m(sample(dam))) + 9);
    const bareW = M.dams.map((dam) => m(shortName(dam.id) || '№ 0', 600) + 7);
    const sum = (list) => list.reduce((total, w) => total + w, 0) + gap * (M.dams.length - 1);
    const mode = sum(beside) <= available ? 'beside' : sum(within) <= available ? 'inside' : 'bare';
    const inside = mode !== 'beside';
    const minimum = mode === 'beside' ? beside : mode === 'inside' ? within : bareW;
    const natural = M.dams.map((dam) => (dam.x1 - dam.x0) * s);
    // Dam widths keep their proportions as far as the strip allows.
    let k = 1;
    const total = (factor) => natural.reduce((sum, w, i) => sum + Math.max(minimum[i], w * factor), 0)
      + gap * (M.dams.length - 1);
    if (total(1) > available) {
      let low = 0;
      let high = 1;
      for (let i = 0; i < 24; i += 1) {
        k = (low + high) / 2;
        if (total(k) > available) high = k; else low = k;
      }
      k = low;
    }
    const squeeze = Math.min(1, available / total(k));
    // Each dam stands on its own ground (the lowest under its footprint) and keeps
    // its true height where that reads; the value inside needs a minimum.
    const heightOf = (dam) => clamp(isNum(dam.top) && isNum(dam.bottom) ? (dam.top - dam.bottom) * s : structH * 0.86,
      mode === 'inside' ? F * 1.45 : F * 1.1, structH);
    const baseOf = (dam) => (isNum(dam.bottom) ? py(dam.bottom) : yg);

    // The ground of the tailings strip: through the dams' feet.
    let x = tx0;
    const stub = [];
    const placed = M.dams.map((dam, index) => {
      const w = Math.max(minimum[index], natural[index] * k) * squeeze;
      const item = { dam, left: x, w, base: baseOf(dam), hd: heightOf(dam) };
      stub.push([x, item.base], [x + w, item.base]);
      x += w + gap;
      return item;
    });
    const tx1 = x - gap;
    const bx = tx0 - F * 1.25;
    stub.unshift([bx + 4, stub[0][1]]);
    stub.push([Math.min(L.W - 4, tx1 + F * 0.6), stub[stub.length - 1][1]]);
    layers.grid.append(soilBand(stub, s), S('path', { class: 'sx-ground stub', d: pathOf(stub) }));
    // Break mark between the section's ground and the tailings: what follows is off the section, not to scale.
    const groundEnd = ground(M.eastX1);
    const yMid = (groundEnd + stub[0][1]) / 2;
    const half = Math.max(5, Math.abs(groundEnd - stub[0][1]) / 2 + 4);
    layers.back.append(
      S('rect', { class: 'sx-break-gap', x: bx - 3, y: yMid - half, width: 6, height: half * 2 }),
      S('path', { class: 'sx-break', d: `M${bx - 5} ${yMid + half}L${bx - 1} ${yMid - half}M${bx + 1} ${yMid + half}L${bx + 5} ${yMid - half}` }));

    for (const item of placed) {
      const { dam, left, w, base, hd } = item;
      const slope = Math.min(5, w * 0.12);
      const shape = (h) => {
        const e = slope * (h / hd);
        return pathOf([[left, base], [left + e, base - h], [left + w - e, base - h], [left + w, base]], true);
      };
      const body = S('path', { class: 'fill' });
      const centre = left + w / 2;
      const name = text(centre - F * 0.2, L.skyLine2, '', { class: 'sx-name', 'text-anchor': inside ? 'middle' : 'end' });
      const value = inside
        ? text(centre, base - hd / 2 + F * 0.34, '', { class: 'sx-value halo', 'text-anchor': 'middle' })
        : text(centre + F * 0.2, L.skyLine2, '', { class: 'sx-value' });
      const g = S('g', { class: 'sx-dam sx-obj sx-label', 'data-thing': dam.id, 'data-kind': 'tailings_dam', 'data-state': dam.planned ? 'planned' : '' },
        S('path', { class: 'box', d: shape(hd) }), body, name, value);
      layers.water.append(g);
      ctx.reg(dam.id, centre, base - hd / 2);
      ctx.on(dam.id, (thing) => {
        const f = thing.f;
        const planned = f.state === 'planned';
        const share = !planned && isNum(f.fill_pct) ? clamp(f.fill_pct / 100, 0, 1) : 0;
        set(body, { d: share > 0.005 ? shape(Math.max(1.5, hd * share)) : null });
        set(g, { 'data-state': f.state || '', 'data-tone': stateTone(f.state, 'tailings_dam') });
        const short = shortName(dam.id) || thing.name;
        const figure = planned ? stateLabel(f.state, 'tailings_dam') : withUnit(fmt(f.fill_pct), '%');
        const word = dam.planned ? 'карта' : 'дамба';
        const long = `${word} ${short}`;
        const title = m(long, 600) + (inside ? 0 : F * 0.4 + m(figure)) + 6 <= w ? long : short;
        setText(name, title);
        setText(value, mode === 'bare' ? '' : figure);
        if (inside) {
          set(name, { x: centre });
        } else {
          // Centre the pair «name value» over the dam.
          const shift = (m(title, 600) - m(figure)) / 2;
          set(name, { x: centre - F * 0.2 + shift });
          set(value, { x: centre + F * 0.2 + shift });
        }
      });
    }

    const facility = M.tailings;
    if (facility) {
      const name = text(tx0, L.skyLine1, '', { class: 'sx-name' });
      const value = text(tx0, L.skyLine1, '', { class: 'sx-value' });
      // Where the facility really is (distance and bearing from the mine point): in
      // the caption where it has room, else in a note under the tailings ground.
      const noteText = place ? fitting([`вне разреза: ${place.where}, ${place.azimuth}`, `${place.where}, ${place.azimuth}`,
        `${place.away}, ${place.azimuth}`, place.away], L.W - 6 - bx, (content) => measure(content, F * 0.92)) : 'вне разреза';
      const note = text(bx - 2, tailNoteY, '', { class: 'sx-note halo' });
      const g = S('g', { class: 'sx-label sx-obj sx-tailings', 'data-thing': facility.id, 'data-kind': 'tailings_facility' },
        S('rect', { class: 'sx-hit-fill', x: tx0, y: L.skyLine1 - F, width: tx1 - tx0, height: F * 1.3 }), name, value, note);
      layers.labels.append(g);
      ctx.reg(facility.id, (tx0 + tx1) / 2, yg - structH / 2);
      ctx.on(facility.id, (thing, state) => {
        const f = thing.f;
        const water = state.things[ctx.id('water')];
        const reclaim = water && isNum(water.f.reclaim_m3h) && water.f.reclaim_m3h > 0
          ? `оборот воды ${withUnit(fmt(water.f.reclaim_m3h), 'м³/ч')}` : null;
        const left = yearsLeft(f.years_left) || stateLabel(f.state, 'tailings_facility');
        const room = L.W - 8 - tx0;
        // The place first, then the reclaim water; «осталось N лет» always.
        const titles = [...(place ? [place.title, `Хвостовое хозяйство (${place.where})`] : []), 'Хвостовое хозяйство', 'Хвосты'];
        const values = [[left, reclaim].filter(Boolean).join(' · '), left];
        let chosen = [titles[titles.length - 1], values[values.length - 1]];
        search:
        for (const title of titles) {
          for (const figure of values) {
            if (m(title + ':', 600) + F * 0.5 + m(figure) <= room) {
              chosen = [title, figure];
              break search;
            }
          }
        }
        setText(name, chosen[0] + ':');
        setText(value, chosen[1]);
        set(value, { x: tx0 + m(chosen[0] + ':', 600) + F * 0.5 });
        setText(note, place && chosen[0].startsWith(`Хвостовое хозяйство (${place.where}`) ? '' : noteText);
        set(g, { 'data-tone': stateTone(f.state, 'tailings_facility') });
      });
    }
  }
}

/** Distance and bearing of the tailings facility from the mine point, as words. */
function tailingsPlace(M) {
  const facility = M.tailings;
  if (!facility || !isNum(facility.distance)) return null;
  const away = `${fmt(facility.distance / 1000, 1)} км`;
  if (!isNum(facility.bearing)) return { away, where: away, azimuth: '', title: `Хвостовое хозяйство (${away})` };
  const side = COMPASS[Math.round((((facility.bearing % 360) + 360) % 360) / 45) % 8];
  const where = `${away} ${side}`;
  const azimuth = `азимут ${fmt(facility.bearing)}°`;
  return { away, where, azimuth, title: `Хвостовое хозяйство (${where}, ${azimuth})` };
}

/**
 * «поверхность по рельефу Copernicus DEM (план — схема подземной части)», once,
 * small, just above the ground line: in the widest stretch west of the pit that
 * no surface fan or label leader takes; on two lines where one is too long, and
 * shortened down to «рельеф Copernicus DEM» on a narrow sheet.
 */
function groundCaption(ctx, sky) {
  const { L, M, layers, measure } = ctx;
  const { px, F } = L;
  const size = F * 0.92;
  const parts = ['поверхность по рельефу Copernicus DEM', '(план — схема подземной части)'];
  // Shorter forms for a narrow sheet: the ground line keeps its source; the
  // note on the plan is also in the page footer.
  const [lead, source] = parts[0].split(/ (?=Copernicus)/);      // «поверхность по рельефу», the data set
  const forms = [[parts.join(' ')], parts, [parts[0]], [lead, source], [`рельеф ${source}`]];
  const east = M.pit ? px(M.pit.section[0][0]) - F * 0.6 : px(M.mineX1);
  const stops = [L.left.rulerX + 6, east];
  for (const label of sky) stops.push(label.x, label.c);
  for (const airway of M.airways) if (airway.top >= M.groundAt(airway.x) - 30) stops.push(px(airway.x));
  const marks = stops.filter((x) => x >= stops[0] && x <= east).sort((a, b) => a - b);
  let best = null;
  for (let i = 1; i < marks.length; i += 1) {
    const a = marks[i - 1] + F * 0.7;
    const b = marks[i] - F * 0.7;
    if (!best || b - a > best[1] - best[0]) best = [a, b];
  }
  const linesFor = (width) => forms.find((lines) => Math.max(...lines.map((part) => measure(part, size))) <= width) || null;
  const step = L.lineH * 0.95;
  const draw = (x, top, lines) => layers.labels.append(S('g', { class: 'sx-ground-note' },
    ...lines.map((part, i) => text(x, top + i * step, part, { class: 'sx-note halo' }))));
  // Above the ground, centred in the gap.
  if (best) {
    const width = best[1] - best[0];
    const lines = linesFor(width);
    if (lines) {
      const textW = Math.max(...lines.map((part) => measure(part, size)));
      const x = best[0] + (width - textW) / 2;
      const top = minBetween(ctx.groundPx, x, x + textW) - 5 - (lines.length - 1) * step;
      if (top - F >= L.skyLine2 + 2) {
        draw(x, top, lines);
        return;
      }
    }
  }
  // Else under the ground in the left gutter, above the first level row.
  const x0 = L.left.rulerX + 6;
  const lines = linesFor(L.ox - 6 - x0);
  if (!lines) return;
  const textW = Math.max(...lines.map((part) => measure(part, size)));
  const top = maxBetween(ctx.groundPx, x0, x0 + textW) + F * 1.1;
  const firstRow = M.levels.length ? L.py(M.levels[0].e) - 3.5 - (L.lines - 1) * L.lineH - F * 1.2 : L.H;
  if (top + (lines.length - 1) * step <= firstRow) draw(x0, top, lines);
}
