// The mine body of the long section: ground line and soil, the old pit, levels,
// stopes, declines, airways with their fans, the dewatering cascade.
// Each builder draws the static shape once and registers a function that
// applies the twin's features on every update.

import { stateLabel, stateTone } from '../panels/dict.js';
import { fmt, isNum, withUnit } from '../panels/format.js';
import { S, clamp, line, pathOf, set, text } from './svg.js';
import { levelAir, pumpStates, shortName } from './model.js';

const AIR_MIN = 0.5;   // m3/s below which an airway shows no flow

/** Elevation of a decline polyline at x inside [y0, y1], or null. */
function crossing(declines, x, y0, y1) {
  for (const decline of declines) {
    const pts = decline.points;
    for (let i = 1; i < pts.length; i += 1) {
      const [xa, ya] = pts[i - 1];
      const [xb, yb] = pts[i];
      if ((x - xa) * (x - xb) > 0 || xa === xb) continue;
      const y = ya + (yb - ya) * (x - xa) / (xb - xa);
      if (y > y0 && y < y1) return y;
    }
  }
  return null;
}

/** Split a descending polyline at an elevation: [built part, part below]. */
function splitAt(points, elevation) {
  const upper = [points[0]];
  for (let i = 1; i < points.length; i += 1) {
    const [xa, ya] = points[i - 1];
    const [xb, yb] = points[i];
    if (yb >= elevation) {
      upper.push(points[i]);
      continue;
    }
    const t = ya === yb ? 0 : (ya - elevation) / (ya - yb);
    const cut = [xa + (xb - xa) * t, elevation];
    upper.push(cut);
    return [upper, [cut, ...points.slice(i)]];
  }
  return [upper, []];
}

/** Ground points [x, y] of the profile from x0 to x1, with both ends interpolated. */
export function groundLine(M, x0, x1) {
  const inside = M.profile.filter(([x]) => x > x0 && x < x1);
  return [[x0, M.groundAt(x0)], ...inside, [x1, M.groundAt(x1)]];
}

/**
 * The soil band under a ground line on the sheet: strips of the same depth
 * that fade downwards, so that the band follows the ground at every x.
 */
export function soilBand(points, s) {
  const depth = Math.max(12, 36 * s);
  const steps = [0.3, 0.2, 0.12, 0.06];
  const band = S('g', { class: 'sx-soil' });
  steps.forEach((opacity, index) => {
    const a = (depth * index) / steps.length;
    const b = (depth * (index + 1)) / steps.length;
    const top = points.map(([x, y]) => [x, y + a]);
    const bottom = points.slice().reverse().map(([x, y]) => [x, y + b]);
    band.append(S('path', { d: pathOf([...top, ...bottom], true), 'fill-opacity': opacity }));
  });
  return band;
}

/** x of every crossing of a polyline [[x, y]] with the elevation y, west to east. */
function crossings(points, y) {
  const hits = [];
  for (let i = 1; i < points.length; i += 1) {
    const [xa, ya] = points[i - 1];
    const [xb, yb] = points[i];
    if (ya === yb || (ya - y) * (yb - y) > 0) continue;
    hits.push(xa + (xb - xa) * (y - ya) / (yb - ya));
  }
  return hits.sort((a, b) => a - b);
}

/** Largest and smallest y of a sheet polyline over the px range [a, b] (its ends interpolated). */
function rangeOf(points, a, b) {
  const ys = points.filter(([x]) => x >= a && x <= b).map(([, y]) => y);
  for (const x of [a, b]) {
    for (let i = 1; i < points.length; i += 1) {
      const [xa, ya] = points[i - 1];
      const [xb, yb] = points[i];
      if ((x - xa) * (x - xb) <= 0 && xa !== xb) ys.push(ya + (yb - ya) * (x - xa) / (xb - xa));
    }
  }
  return ys;
}
export const maxBetween = (points, a, b) => Math.max(...rangeOf(points, a, b));
export const minBetween = (points, a, b) => Math.min(...rangeOf(points, a, b));

export function fanSymbol(cx, cy, r) {
  const a = r * 0.72;
  const b = r * 0.46;
  return S('g', { class: 'sx-fan-symbol' },
    S('circle', { class: 'rim', cx, cy, r }),
    S('path', {
      class: 'blades',
      d: `M${cx} ${cy}L${cx - a} ${cy - b}L${cx - a} ${cy + b}ZM${cx} ${cy}L${cx + a} ${cy - b}L${cx + a} ${cy + b}Z`,
    }),
    S('path', {
      class: 'cross',
      d: `M${cx - r} ${cy - r}L${cx + r} ${cy + r}M${cx + r} ${cy - r}L${cx - r} ${cy + r}`,
    }));
}

export function buildUnderground(ctx) {
  const { L, M, layers, measure } = ctx;
  const { px, py, s, F } = L;
  const roomy = L.lines >= 2;

  // ------------------------------------------------- ground, soil, old pit
  // The ground line is the terrain profile along the ore zone, from the ruler to
  // the east end of the surface strip; a soil band under it fades downwards. The
  // old pit lies off the section plane: its lowest ground (pit.section) is cut
  // out of the soil band and drawn as a dashed contour with bench ticks.
  const westX = M.mineX0 - (L.ox - L.left.rulerX) / (s * (L.west || 1));
  const ground = groundLine(M, westX, M.eastX1).map(([x, y]) => [px(x), py(y)]);
  if (L.groundEndPx > ground[ground.length - 1][0] + 1) ground.push([L.groundEndPx, ground[ground.length - 1][1]]);
  layers.grid.append(soilBand(ground, s));
  if (M.pit) {
    const pit = M.pit;
    const section = pit.section;
    const x0 = section[0][0];
    const x1 = section[section.length - 1][0];
    const lid = groundLine(M, x0, x1).reverse();
    const contour = section.map(([x, y]) => [px(x), py(y)]);
    layers.grid.append(S('path', { class: 'sx-pit-cut', d: pathOf([...contour, ...lid.map(([x, y]) => [px(x), py(y)])], true) }));
    layers.back.append(S('path', { class: 'sx-pit', d: pathOf(contour) }));
    // A tick at each bench crest on both walls, where the benches are far enough apart to read.
    const benchStep = pit.benches.length > 1 ? pit.benches[1] - pit.benches[0] : 15;
    if (benchStep * s >= 7) {
      const tick = Math.max(3, 7 * s);
      const ticks = [];
      for (const y of pit.benches) {
        const hits = crossings(section, y);
        if (hits.length < 2) continue;
        const [left, right] = [hits[0], hits[hits.length - 1]];
        ticks.push(`M${(px(left) - tick).toFixed(1)} ${py(y).toFixed(1)}h${tick.toFixed(1)}`,
          `M${px(right).toFixed(1)} ${py(y).toFixed(1)}h${tick.toFixed(1)}`);
      }
      if (ticks.length) layers.back.append(S('path', { class: 'sx-bench', d: ticks.join('') }));
    }
    // The pit ramp of TU2: the part of its road that runs below the section's ground.
    for (const road of M.roads) {
      const ramp = [];
      for (const point of road.points) {
        if (M.pitAt(point[0]) === null || point[1] > M.groundAt(point[0]) - 2) break;
        ramp.push(point);
      }
      if (ramp.length > 2) {
        layers.back.append(S('path', { class: 'sx-road', d: pathOf(ramp.map(([x, y]) => [px(x), py(y)])) }));
      }
    }
    if (roomy) {
      // The caption stands in the upper part of the cut, under the ground line.
      const caption = 'карьер (в проекции)';
      const width = measure(caption, F * 0.92);
      const cx0 = px(x0 + (x1 - x0) * 0.15);
      const y = maxBetween(ground, cx0, cx0 + width) + F * 1.25;
      if (y + 3 < minBetween(contour, cx0, cx0 + width)) {
        layers.labels.append(text(cx0, y, caption, { class: 'sx-note halo' }));
      }
    }
  }
  layers.grid.append(S('path', { class: 'sx-ground', d: pathOf(ground) }));
  ctx.groundPx = ground;

  // ----------------------------------------------------------------- levels
  const water = S('g', { class: 'sx-water' },
    S('rect', { class: 'body' }), S('line', { class: 'top' }));
  layers.bands.append(water);
  const levelState = {};
  for (const level of M.levels) {
    const y = py(level.e);
    const band = S('rect', {
      class: 'sx-band', x: px(level.x0), y: py(level.e + 40), width: (level.x1 - level.x0) * s, height: 40 * s,
    });
    layers.bands.append(band);
    const g = S('g', { class: 'sx-level sx-obj', 'data-thing': level.id, 'data-state': level.planned ? 'planned' : '' },
      line(px(level.x0), y, px(level.x1), y, { class: 'sx-drive' }),
      line(px(level.x0), y, px(level.x1), y, { class: 'sx-hit' }));
    layers.drives.append(g);
    ctx.reg(level.id, px((level.x0 + level.x1) / 2), y);
    ctx.on(level.id, (thing, state) => {
      const f = thing.f;
      const short = levelAir(thing, state, level.id) !== 'ok';
      set(g, { 'data-state': f.state || '', 'data-air': short ? 'short' : 'ok' });
      set(band, { 'data-air': short ? 'short' : 'ok' });
      levelState[level.id] = f.state;
    });
  }

  // The water band covers the flooded levels and rises with them.
  const waterBody = water.querySelector('.body');
  const waterTop = water.querySelector('.top');
  ctx.onState((state) => {
    const flooded = M.levels.filter((level) => levelState[level.id] === 'flooded');
    const mine = state.things[ctx.id('mine')];
    const volume = mine && isNum(mine.f.flood_volume_m3) ? mine.f.flood_volume_m3 : 0;
    let low;
    let top;
    let wet = flooded;
    if (flooded.length) {
      low = Math.min(...flooded.map((level) => level.e)) - 7;
      top = Math.max(...flooded.map((level) => level.e)) + 14;
    } else if (volume > 0) {
      wet = M.levels.filter((level) => level.e === M.developedBottom);
      low = M.developedBottom - 7;
      top = low + 3 + Math.min(1, volume / 300) * 6;
    } else {
      set(water, { 'data-on': '0' });
      waterBody.style.transform = 'scaleY(0)';
      return;
    }
    const x0 = px(Math.min(...wet.map((level) => level.x0)) - 6);
    const x1 = px(Math.max(...wet.map((level) => level.x1)) + 6);
    const yLow = py(low);
    set(waterBody, { x: x0, y: yLow - 1, width: x1 - x0, height: 1 });
    waterBody.style.transformOrigin = `${x0}px ${yLow}px`;
    waterBody.style.transform = `scaleY(${Math.max(1, yLow - py(top)).toFixed(1)})`;
    set(waterTop, { x1: x0, x2: x1, y1: 0, y2: 0 });
    waterTop.style.transform = `translateY(${py(top).toFixed(1)}px)`;
    set(water, { 'data-on': '1' });
  });

  // ---------------------------------------------------- backfill and stopes
  // A block fills the floor between two levels: a small inset keeps the level drive visible between them.
  const inset = L.stopeInset;
  for (const box of M.backfill) {
    layers.stopes.append(S('rect', {
      class: 'sx-backfill', x: px(box.x0), y: py(box.y1) + inset, width: (box.x1 - box.x0) * s,
      height: Math.max(1, (box.y1 - box.y0) * s - 2 * inset), fill: `url(#${ctx.uid}-backfill)`,
    }));
  }
  const tagW = measure('−100-1', F * 0.92, 600) + 8;
  for (const stope of M.stopes) {
    const x = px(stope.x0);
    const y = py(stope.y1) + inset;
    const w = (stope.x1 - stope.x0) * s;
    const h = Math.max(1, (stope.y1 - stope.y0) * s - 2 * inset);
    const fill = S('rect', { class: 'fill', x: x + 0.5, width: w - 1, y: y + h, height: 0 });
    const g = S('g', { class: 'sx-stope sx-obj', 'data-thing': stope.id, 'data-state': stope.planned ? 'planned' : 'standby' },
      S('rect', { class: 'box', x, y, width: w, height: h }),
      fill,
      S('rect', { class: 'hatch', x, y, width: w, height: h, fill: `url(#${ctx.uid}-blast)` }),
      S('rect', { class: 'flash', x, y, width: w, height: h }),
      S('rect', { class: 'frame', x, y, width: w, height: h }));
    if (!L.inbox && w >= tagW && h >= F * 2.1) {
      // The block name goes into the half of the box that no decline crosses.
      const hit = crossing(M.declines, (stope.x0 + stope.x1) / 2, stope.y0, stope.y1);
      const low = hit !== null && hit > (stope.y0 + stope.y1) / 2;
      g.append(text(x + 4, low ? y + h - F * 0.42 : y + F * 1.02, stope.short, { class: 'sx-tag' }));
    }
    layers.stopes.append(g);
    ctx.reg(stope.id, x + w / 2, y + h / 2);
    let previous = null;
    ctx.on(stope.id, (thing, state, first) => {
      const f = thing.f;
      const initial = thing.attrs && thing.attrs.ore_initial_t;
      const share = isNum(f.ore_remaining_t) && isNum(initial) && initial > 0
        ? clamp(f.ore_remaining_t / initial, 0, 1) : 1;
      const filled = Math.max(0, (h - 1) * share);
      set(fill, { y: y + h - 0.5 - filled, height: filled });
      set(g, { 'data-state': f.state || 'standby' });
      if (!first && previous === 'awaiting_blast' && f.state && f.state !== 'awaiting_blast') {
        g.classList.remove('blast');
        g.getBoundingClientRect();      // restart the animation
        g.classList.add('blast');
      }
      previous = f.state;
    });
  }

  // ---------------------------------------------------------------- airways
  const fanByAirway = M.fanByAirway;
  const airwayX = {};
  const airwayTop = {};
  for (const airway of M.airways) {
    const x = px(airway.x);
    airwayX[airway.id] = airway.x;
    airwayTop[airway.id] = airway.top;
    const solid = S('path', { class: 'way' });
    const design = S('path', { class: 'way design' });
    const flow = S('path', { class: 'flow' });
    const head = S('path', { class: 'head' });
    const g = S('g', { class: 'sx-airway sx-obj', 'data-thing': airway.id, 'data-dir': airway.direction },
      design, solid, flow, head,
      line(x, py(airway.top), x, py(airway.bottom), { class: 'sx-hit' }));
    if (roomy) {
      const name = shortName(airway.id);
      const mid = py(Math.max(airway.bottom, airway.top - Math.min(60, (airway.top - airway.bottom) / 2)));
      if (name) {
        g.append(text(0, 0, name, {
          class: 'sx-tag small', 'text-anchor': 'middle', transform: `translate(${(x - 3.5).toFixed(1)} ${mid.toFixed(1)}) rotate(-90)`,
        }));
      }
    }
    layers.air.append(g);
    ctx.reg(airway.id, x, py((airway.top + Math.max(airway.bottom, M.developedBottom)) / 2));
    ctx.on(airway.id, (thing, state) => {
      const f = thing.f;
      const planned = f.state === 'planned';
      let builtTo = airway.top;
      if (!planned) {
        builtTo = isNum(airway.plannedBelow) ? airway.plannedBelow
          : airway.planned ? M.developedBottom : airway.bottom;
        builtTo = Math.max(builtTo, airway.bottom);
      }
      set(solid, { d: builtTo < airway.top ? `M${x} ${py(airway.top)}V${py(builtTo)}` : null });
      set(design, { d: builtTo > airway.bottom ? `M${x} ${py(builtTo)}V${py(airway.bottom)}` : null });
      const fanThing = fanByAirway[airway.id] && state.things[fanByAirway[airway.id]];
      const fanDown = fanThing && fanThing.f.state === 'failed';
      const value = !planned && !fanDown && isNum(f.air_flow_m3s) ? f.air_flow_m3s : 0;
      const on = value > AIR_MIN && builtTo < airway.top;
      set(g, { 'data-state': f.state || '', 'data-flow': on ? '1' : '0' });
      if (!on) {
        set(flow, { d: null });
        set(head, { d: null });
        return;
      }
      const width = clamp(1 + value / 85, 1.2, 4.6);
      const from = airway.direction === 'exhaust' ? builtTo : airway.top;
      const to = airway.direction === 'exhaust' ? airway.top : builtTo;
      set(flow, { d: `M${x} ${py(from)}V${py(to)}`, 'stroke-width': width });
      // One arrowhead in the upper part of the airway, pointing with the air.
      const at = py(airway.top - Math.min(34, (airway.top - builtTo) * 0.45));
      const size = clamp(width * 1.25 + 2.2, 3.4, 9);
      const sign = airway.direction === 'exhaust' ? -1 : 1;
      set(head, { d: `M${x - size} ${at - sign * size * 0.6}L${x} ${at + sign * size * 0.9}L${x + size} ${at - sign * size * 0.6}Z` });
    });
  }

  // ------------------------------------------------------------------- fans
  const fanR = F * 0.62;
  for (const fan of M.fans) {
    const single = fan.airways.length === 1 && airwayX[fan.airways[0]] !== undefined;
    const cx = px(single ? airwayX[fan.airways[0]] : fan.x);
    // A surface fan stands on the collar of its airway (the DEM ground there), or on the ground line.
    const collar = single ? airwayTop[fan.airways[0]] : M.groundAt(fan.x);
    const cy = (fan.surface ? py(collar) : py(Math.floor(fan.y / 10) * 10)) - fanR - 1.5;
    const g = S('g', { class: 'sx-fan sx-obj', 'data-thing': fan.id, 'data-state': fan.planned ? 'planned' : '' },
      S('circle', { class: 'sx-hit-fill', cx, cy, r: fanR + 4 }),
      fanSymbol(cx, cy, fanR));
    layers.water.append(g);
    ctx.reg(fan.id, cx, cy);
    const short = shortName(fan.id);
    const label = fan.surface
      ? ctx.skyLabel({ thing: fan.id, kind: 'main_fan', x: cx, top: cy - fanR, sample: [`вент. ${short || 'ВС-1'}`, '150,0 м³/с'] })
      : null;
    ctx.on(fan.id, (thing) => {
      const f = thing.f;
      set(g, { 'data-state': f.state || '', 'data-tone': stateTone(f.state, 'main_fan') });
      if (label) {
        label.set(`вент. ${short || thing.name}`,
          f.state === 'running' ? withUnit(fmt(f.air_flow_m3s, 0), 'м³/с') : stateLabel(f.state, 'main_fan'));
      }
    });
  }

  // ------------------------------------------------------------- dewatering
  const gaugeW = F * 0.62;
  const gaugeH = Math.min(F * 1.7, 36 * s);
  const pumpR = F * 0.5;
  for (const station of M.stations) {
    const cx = px(station.x);
    const y = py(station.e);
    const route = [];
    for (const point of station.pipe) {
      const last = route[route.length - 1];
      if (!last || last[0] !== point[0] || last[1] !== point[1]) route.push(point);
    }
    // The pipe is drawn beside the drive and the shaft it follows.
    const d = pathOf(route.map(([wx, wy]) => [px(wx) + 3, py(wy) - 3]));
    const level = S('rect', { class: 'level', x: cx - gaugeW / 2 + 0.6, width: gaugeW - 1.2, y: y + 2 + gaugeH, height: 0 });
    // The pumps in a row, each coloured by its own state (in place of the one pump symbol).
    const row = S('g', { class: 'pumps' });
    const g = S('g', { class: 'sx-station sx-obj', 'data-thing': station.id, 'data-state': station.planned ? 'planned' : '' },
      S('path', { class: 'pipe', d }),
      S('path', { class: 'pipe-flow', d }),
      S('path', { class: 'sx-hit', d }),
      S('rect', { class: 'gauge', x: cx - gaugeW / 2, y: y + 2, width: gaugeW, height: gaugeH }),
      level,
      S('circle', { class: 'sx-hit-fill', cx, cy: y - pumpR - 1, r: pumpR + 4 }),
      S('circle', { class: 'pump', cx, cy: y - pumpR - 1.5, r: pumpR }),
      S('path', {
        class: 'pump-mark',
        d: `M${cx - pumpR * 0.55} ${y - pumpR * 0.6 - 1.5}L${cx} ${y - pumpR * 1.75 - 1.5}L${cx + pumpR * 0.55} ${y - pumpR * 0.6 - 1.5}Z`,
      }),
      row);
    layers.water.append(g);
    ctx.reg(station.id, cx, y);
    ctx.on(station.id, (thing) => {
      const f = thing.f;
      const share = isNum(f.sump_level_pct) ? clamp(f.sump_level_pct / 100, 0, 1) : 0;
      const filled = (gaugeH - 1.2) * share;
      set(level, { y: y + 2 + gaugeH - 0.6 - filled, height: filled });
      const pumping = isNum(f.pumped_m3h) && f.pumped_m3h > 0;
      set(g, {
        'data-state': f.state || '', 'data-tone': stateTone(f.state, 'pump_station'),
        'data-flow': pumping ? '1' : '0',
      });
      g.style.setProperty('--pipe-w', `${clamp(1.1 + (f.pumped_m3h || 0) / 400, 1.2, 2.8).toFixed(2)}px`);
      const pumps = pumpStates(thing);
      if (row.childNodes.length !== pumps.length) {
        const r = Math.max(2.2, pumpR * 0.62);
        row.replaceChildren(...pumps.map((_, i) => S('circle', {
          class: 'unit', cx: cx + (i - (pumps.length - 1) / 2) * r * 2.6, cy: y - r - 1.5, r,
        })));
      }
      pumps.forEach((token, i) => set(row.childNodes[i], { 'data-pump': token }));
      set(g, { 'data-pumps': pumps.length ? '1' : '0' });
    });
  }

  // --------------------------------------------------------------- declines
  M.declines.forEach((decline, index) => {
    const double = index % 2 === 1;      // the second decline is drawn as a double line
    const built = S('path', { class: 'way' });
    const core = double ? S('path', { class: 'core' }) : null;
    const design = S('path', { class: 'way design' });
    const hit = S('path', { class: 'sx-hit' });
    const nodes = S('g', { class: 'nodes' });
    const [portalX, portalY] = [px(decline.points[0][0]), py(decline.points[0][1])];
    const r = Math.max(2.4, F * 0.32);
    const g = S('g', {
      class: `sx-decline sx-obj ${double ? 'double' : 'single'}`, 'data-thing': decline.id, 'data-state': 'open',
    }, design, built, core, nodes,
    S('rect', { class: 'portal', x: portalX - r, y: portalY - r, width: r * 2, height: r * 2 }),
    S('path', {
      class: 'barrier',
      d: `M${portalX - r * 2} ${portalY - r * 2}L${portalX + r * 2} ${portalY + r * 2}M${portalX + r * 2} ${portalY - r * 2}L${portalX - r * 2} ${portalY + r * 2}`,
    }),
    hit);
    layers.declines.append(g);
    ctx.reg(decline.id, portalX, portalY);
    // A short tag at the portal; the live row of the decline is in the table on the right.
    const atSurface = decline.points[0][1] >= M.groundAt(decline.points[0][0]) - 8;
    g.append(text(portalX + r * 2.4, atSurface ? portalY + F * 1.15 : portalY - r - 2.5,
      shortName(decline.id) || decline.token, { class: 'sx-tag' }));
    let drawnBottom = null;
    ctx.on(decline.id, (thing) => {
      const f = thing.f;
      const bottom = isNum(f.bottom_elevation) ? f.bottom_elevation : decline.bottom;
      if (bottom !== drawnBottom) {
        drawnBottom = bottom;
        const [upper, lower] = splitAt(decline.points, bottom);
        const d = pathOf(upper.map(([x, y]) => [px(x), py(y)]));
        set(built, { d });
        if (core) set(core, { d });
        set(hit, { d });
        set(design, { d: lower.length > 1 ? pathOf(lower.map(([x, y]) => [px(x), py(y)])) : null });
        nodes.replaceChildren(...decline.nodes
          .filter((node) => node.y >= bottom - 0.5 && (node.type === 'bay' || node.type === 'access'))
          .map((node) => S('circle', { class: node.type, cx: px(node.x), cy: py(node.y), r: node.type === 'bay' ? r * 0.9 : r * 0.7 })));
      }
      set(g, { 'data-state': f.state || 'open' });
    });
  });
}
