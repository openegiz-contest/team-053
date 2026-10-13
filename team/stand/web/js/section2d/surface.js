// The surface strip above the ground line: plant lines, ROM stockpile, settling
// ponds, monitoring points, and the tailings dams. Objects stand at their real x
// with schematic heights. The tailings facility lies 1.5 km away from the mine
// and overlaps the old pit in projection, so it is drawn past a break mark, east
// of the pit, as a row of dams in their west-to-east order.
// Labels are two text lines above the structures, moved apart where they touch.

import { stateLabel, stateTone } from '../panels/dict.js';
import { fmt, isNum, withUnit } from '../panels/format.js';
import { S, clamp, line, pathOf, set, setText, text } from './svg.js';
import { shortName } from './model.js';

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
  const { px, F, yg, structH, s } = L;
  const m = (content, weight) => measure(content, F, weight);

  // ------------------------------------------------------------------ plant
  if (M.plant) {
    const hp = structH * 0.82;
    const x0 = px(M.plant.x0);
    const x1 = px(M.plant.x1);
    const plantGroup = S('g', { class: 'sx-plant sx-obj', 'data-thing': M.plant.id },
      S('rect', { class: 'frame', x: x0, y: yg - hp - 3, width: x1 - x0, height: hp + 3 }));
    layers.back.append(plantGroup);
    ctx.reg(M.plant.id, (x0 + x1) / 2, yg - hp / 2);
    for (const item of M.plantLines) {
      const x = px(item.x0) + 0.5;
      const w = px(item.x1) - px(item.x0) - 1;
      const fill = S('rect', { class: 'fill', x: x + 0.5, width: w - 1, y: yg, height: 0 });
      const g = S('g', { class: 'sx-pline sx-obj', 'data-thing': item.id, 'data-state': item.planned ? 'planned' : '' },
        S('rect', { class: 'box', x, y: yg - hp, width: w, height: hp }), fill);
      if (w >= F * 0.75) {
        g.append(text(x + w / 2, yg - hp / 2 + F * 0.3, String(item.n), { class: 'sx-tag small', 'text-anchor': 'middle' }));
      }
      layers.water.append(g);
      ctx.reg(item.id, x + w / 2, yg - hp / 2);
      ctx.on(item.id, (thing) => {
        const f = thing.f;
        const share = isNum(f.utilisation_pct) ? clamp(f.utilisation_pct / 100, 0, 1) : 0;
        const filled = (hp - 1) * share;
        set(fill, { y: yg - 0.5 - filled, height: filled });
        set(g, { 'data-state': f.state || '', 'data-tone': stateTone(f.state, 'plant_line') });
      });
    }
    const label = ctx.skyLabel({
      thing: M.plant.id, kind: 'plant', x: (x0 + x1) / 2, top: yg - hp - 3, sample: ['Фабрика', '124,1 т/ч'],
    });
    ctx.on(M.plant.id, (thing) => {
      set(plantGroup, { 'data-tone': stateTone(thing.f.state, 'plant') });
      label.set('Фабрика', withUnit(fmt(thing.f.feed_tph, 1), 'т/ч'));
    });
  }

  // -------------------------------------------------------------- stockpile
  if (M.rom) {
    const x = px(M.rom.x);
    const heap = S('path', { class: 'heap' });
    const g = S('g', { class: 'sx-rom sx-obj', 'data-thing': M.rom.id }, heap);
    if (M.plant) {
      layers.back.append(line(x, yg - structH * 0.2, px(M.plant.x1), yg - structH * 0.6, { class: 'sx-conveyor' }));
    }
    layers.water.append(g);
    ctx.reg(M.rom.id, x, yg - structH * 0.3);
    const label = ctx.skyLabel({
      thing: M.rom.id, kind: 'rom_stockpile', x, top: yg - structH * 0.75, sample: ['Рудный склад', '34,0 тыс. т'],
    });
    ctx.on(M.rom.id, (thing) => {
      const f = thing.f;
      const share = isNum(f.tonnes) && M.rom.ref > 0 ? clamp(f.tonnes / M.rom.ref, 0.03, 1.7) : 1;
      const k = Math.sqrt(share);
      const half = clamp(M.rom.radius * s * L.west, F * 0.9, F * 2.4) * k;
      const h = structH * 0.6 * k;
      set(heap, { d: `M${(x - half).toFixed(1)} ${yg}L${x} ${(yg - h).toFixed(1)}L${(x + half).toFixed(1)} ${yg}Z` });
      set(g, { 'data-tone': stateTone(f.state, 'rom_stockpile') });
      label.set('Рудный склад', withUnit(fmt(isNum(f.tonnes) ? f.tonnes / 1000 : NaN, 1), 'тыс. т'));
    });
  }

  // ------------------------------------------------------------------ ponds
  if (M.ponds.length) {
    for (const pond of M.ponds) {
      const g = S('g', { class: 'sx-pond sx-obj', 'data-thing': pond.id },
        S('rect', { class: 'basin', x: px(pond.x0), y: yg - 2.5, width: Math.max(4, (pond.x1 - pond.x0) * s), height: 5.5 }));
      layers.water.append(g);
      ctx.reg(pond.id, px((pond.x0 + pond.x1) / 2), yg);
    }
    // The ponds are small and stand between the shaft collars: their label goes under them.
    const first = M.ponds[0];
    const title = 'илоотстойники';
    let mid = px((first.x0 + M.ponds[M.ponds.length - 1].x1) / 2);
    // Keep clear of the shaft that stands just west of the ponds.
    const west = M.airways.map((airway) => airway.x).filter((x) => x < first.x0 && x > first.x0 - 150);
    if (west.length) mid = Math.max(mid, px(Math.max(...west)) + F * 0.9 + m(title, 600) / 2);
    const value = text(mid, yg + F * 2.5, '', { class: 'sx-value halo', 'text-anchor': 'middle' });
    layers.labels.append(S('g', { class: 'sx-label sx-obj', 'data-thing': first.id, 'data-kind': 'settling_pond' },
      text(mid, yg + F * 1.3, title, { class: 'sx-name halo', 'text-anchor': 'middle' }), value));
    ctx.on(first.id, (thing) => setText(value, withUnit(fmt(thing.f.inflow_m3h), 'м³/ч')));
  }

  // ------------------------------------------------------ monitoring points
  for (const point of M.monitors) {
    const x = px(point.x);
    const r = F * 0.45;
    const west = point.x < M.mineX0;
    const marker = S('path', { class: 'pin', d: `M${x} ${yg - r}L${x + r} ${yg}L${x} ${yg + r}L${x - r} ${yg}Z` });
    const name = text(0, yg + F * 1.3, '', { class: 'sx-name' });
    const value = text(0, yg + F * 1.3, '', { class: 'sx-value' });
    const g = S('g', { class: 'sx-monitor sx-obj sx-label', 'data-thing': point.id, 'data-kind': 'monitoring_point' },
      S('circle', { class: 'sx-hit-fill', cx: x, cy: yg, r: r + 4 }), marker, name, value);
    layers.labels.append(g);
    ctx.reg(point.id, x, yg);
    const room = west ? px(M.mineX0) - 6 - (L.left.rulerX + 6) : L.right.x1 - (x + F);
    ctx.on(point.id, (thing) => {
      const f = thing.f;
      set(g, { 'data-tone': stateTone(f.state, 'monitoring_point') });
      const full = shortName(point.id) || thing.name;
      const state = stateLabel(f.state, 'monitoring_point');
      const body = thing.attrs && thing.attrs.water_body;
      const title = !body || m(full + ':', 600) + F * 0.4 + m(state) <= room ? full : body;
      const flow = f.discharge_m3h > 0 ? `сброс ${withUnit(fmt(f.discharge_m3h, 1), 'м³/ч')}`
        : f.intake_m3h > 0 ? `водозабор ${withUnit(fmt(f.intake_m3h, 1), 'м³/ч')}` : null;
      const permit = isNum(f.permit_use_pct) && f.permit_use_pct > 0 ? `${fmt(f.permit_use_pct)} % разрешённого` : null;
      const candidates = [[state, flow, permit], [state, flow], [state]]
        .map((parts) => parts.filter(Boolean).join(' · '));
      const nameW = m(title + ':', 600) + F * 0.4;
      const chosen = fitting(candidates, room - nameW, (content) => m(content));
      setText(name, title + ':');
      setText(value, chosen);
      const start = west ? px(M.mineX0) - 6 - nameW - m(chosen) : x + F;
      set(name, { x: start });
      set(value, { x: start + nameW });
    });
  }

  // ------------------------------------------------- labels above the strip
  const sky = ctx.sky.slice().sort((a, b) => a.x - b.x);
  for (const label of sky) {
    label.w = Math.max(m(label.sample[0], 600), m(label.sample[1]));
    label.c = label.x;
  }
  const pad = F * 0.9;
  const pitRight = M.pit ? px(M.pit.cx + M.pit.rTop) : px(M.mineX1);
  const lowBound = 3;
  const highBound = Math.max(pitRight + F * 3, L.W * 0.62);
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
  let skyRight = 0;
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
    skyRight = Math.max(skyRight, label.c + label.w / 2);
  }

  // --------------------------------------------------------------- tailings
  if (M.dams.length) {
    const gap = F * 0.9;
    const tx0 = Math.max(pitRight + F * 2.2, skyRight + F * 2.4);
    const available = L.W - 8 - tx0;
    const sample = (dam) => (dam.planned ? stateLabel('planned', 'tailings_dam') : '100 %');
    const beside = M.dams.map((dam) => m(shortName(dam.id) || '№ 0', 600) + F * 0.4 + m(sample(dam)) + 5);
    // In a narrow strip the number stands above the dam and the value inside it.
    const inside = beside.reduce((sum, w) => sum + w, 0) + gap * (M.dams.length - 1) > available;
    const minimum = inside
      ? M.dams.map((dam) => Math.max(m(shortName(dam.id) || '№ 0', 600), m(sample(dam))) + 9)
      : beside;
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
    const hd = structH * 0.86;

    // Break mark on the ground line: what follows is off the section and not to scale.
    const bx = tx0 - F * 1.1;
    layers.back.append(S('rect', { class: 'sx-break-gap', x: bx - 3, y: yg - 2, width: 6, height: 4 }),
      S('path', { class: 'sx-break', d: `M${bx - 5} ${yg + 5}L${bx - 1} ${yg - 5}M${bx + 1} ${yg + 5}L${bx + 5} ${yg - 5}` }));

    let x = tx0;
    const facility = M.tailings;
    M.dams.forEach((dam, index) => {
      const w = Math.max(minimum[index], natural[index] * k) * squeeze;
      const slope = Math.min(5, w * 0.12);
      const left = x;
      const shape = (h) => {
        const e = slope * (h / hd);
        return pathOf([[left, yg], [left + e, yg - h], [left + w - e, yg - h], [left + w, yg]], true);
      };
      const body = S('path', { class: 'fill' });
      const name = text(x + w / 2 - F * 0.2, L.skyLine2, '', { class: 'sx-name', 'text-anchor': inside ? 'middle' : 'end' });
      const value = inside
        ? text(x + w / 2, yg - hd / 2 + F * 0.34, '', { class: 'sx-value halo', 'text-anchor': 'middle' })
        : text(x + w / 2 + F * 0.2, L.skyLine2, '', { class: 'sx-value' });
      const g = S('g', { class: 'sx-dam sx-obj sx-label', 'data-thing': dam.id, 'data-kind': 'tailings_dam', 'data-state': dam.planned ? 'planned' : '' },
        S('path', { class: 'box', d: shape(hd) }), body, name, value);
      layers.water.append(g);
      ctx.reg(dam.id, x + w / 2, yg - hd / 2);
      const centre = x + w / 2;
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
        setText(value, figure);
        if (inside) {
          set(name, { x: centre });
        } else {
          // Centre the pair «name value» over the dam.
          const shift = (m(title, 600) - m(figure)) / 2;
          set(name, { x: centre - F * 0.2 + shift });
          set(value, { x: centre + F * 0.2 + shift });
        }
      });
      x += w + gap;
    });
    const tx1 = x - gap;

    if (facility) {
      const name = text(tx0, L.skyLine1, '', { class: 'sx-name' });
      const value = text(tx0, L.skyLine1, '', { class: 'sx-value' });
      const g = S('g', { class: 'sx-label sx-obj sx-tailings', 'data-thing': facility.id, 'data-kind': 'tailings_facility' },
        S('rect', { class: 'sx-hit-fill', x: tx0, y: L.skyLine1 - F, width: tx1 - tx0, height: F * 1.3 }), name, value);
      layers.labels.append(g);
      ctx.reg(facility.id, (tx0 + tx1) / 2, yg - hd / 2);
      const away = isNum(facility.distance) ? `${fmt(facility.distance / 1000, 1)} км к северо-востоку` : 'вне разреза';
      ctx.on(facility.id, (thing, state) => {
        const f = thing.f;
        const water = state.things[ctx.id('water')];
        const reclaim = water && isNum(water.f.reclaim_m3h) && water.f.reclaim_m3h > 0
          ? `оборот воды ${withUnit(fmt(water.f.reclaim_m3h), 'м³/ч')}` : null;
        const left = yearsLeft(f.years_left) || stateLabel(f.state, 'tailings_facility');
        const room = L.W - 8 - tx0;
        const titles = [`Хвостовое хозяйство (${away})`, 'Хвостовое хозяйство', 'Хвосты'];
        const values = [[left, reclaim].filter(Boolean).join(' · '), left];
        let chosen = [titles[titles.length - 1], values[values.length - 1]];
        search:
        for (const figure of values) {
          for (const title of titles) {
            if (m(title + ':', 600) + F * 0.5 + m(figure) <= room) {
              chosen = [title, figure];
              break search;
            }
          }
        }
        setText(name, chosen[0] + ':');
        setText(value, chosen[1]);
        set(value, { x: tx0 + m(chosen[0] + ':', 600) + F * 0.5 });
        set(g, { 'data-tone': stateTone(f.state, 'tailings_facility') });
      });
    }
  }
}
