// The plan in metres: the satellite image and the vector overlays drawn in the
// world group (x east, z south; strokes keep their screen width), with their
// live updates. Point symbols and labels are in screen pixels (marks.js).

import { stateLabel, stateTone } from '../panels/dict.js';
import { fmt, isNum, withUnit } from '../panels/format.js';
import { S, clamp, pathOf, set } from './svg.js';
import { shortName } from './model.js';

/** «осталось 3,1 года»: the noun follows the fraction. */
export function yearsLeft(value) {
  if (!isNum(value)) return '';
  if (value >= 20) {
    const n = Math.round(value);
    const word = n % 10 === 1 && n % 100 !== 11 ? 'год'
      : [2, 3, 4].includes(n % 10) && ![12, 13, 14].includes(n % 100) ? 'года' : 'лет';
    return `осталось ${fmt(n)} ${word}`;
  }
  return `осталось ${fmt(value, 1)} года`;
}

const hit = (d, id, extra) => S('path', { class: `pl-hit ${extra || ''}`, d, 'data-thing': id });

export function buildBase(ctx) {
  const { M, layers } = ctx;
  const [x0, z0, x1, z1] = M.image.extent;
  layers.base.append(
    S('rect', { class: 'pl-tone', x: x0, y: z0, width: x1 - x0, height: z1 - z0 }),
    S('image', {
      class: 'pl-image', href: M.image.href, x: x0, y: z0, width: x1 - x0, height: z1 - z0,
      preserveAspectRatio: 'none', 'aria-hidden': 'true',
    }),
    S('rect', { class: 'pl-shade', x: x0, y: z0, width: x1 - x0, height: z1 - z0 }),
    S('rect', { class: 'pl-neatline', x: x0, y: z0, width: x1 - x0, height: z1 - z0 }));
}

export function buildSurface(ctx) {
  const { M, layers } = ctx;

  // ------------------------------------------------- land: zone, heaps, yard
  if (M.land.industrial) {
    layers.land.append(S('path', { class: 'pl-zone', d: pathOf(M.land.industrial, true) },
      S('title', {}, 'Промышленная зона (OpenStreetMap)')));
  }
  for (const heap of M.land.heaps) {
    layers.land.append(S('path', { class: 'pl-heap', d: pathOf(heap, true), fill: `url(#${ctx.uid}-heap)` },
      S('title', {}, 'Отвал (OpenStreetMap)')));
  }
  if (M.land.quarry) {
    layers.land.append(S('path', { class: 'pl-quarry', d: pathOf(M.land.quarry, true) },
      S('title', {}, 'Выемка к северу от карьера (OpenStreetMap, назначение не известно)')));
  }
  if (M.land.yard) {
    layers.plant.append(S('path', { class: 'pl-yard', d: pathOf(M.land.yard, true) },
      S('title', {}, 'Стоянка техники (схема)')));
  }
  if (M.land.heaps.length) {
    // The largest heap carries the word once.
    const big = M.land.heaps.reduce((a, b) => (b.length > a.length ? b : a));
    const [hx0, hz0, hx1, hz1] = [Math.min(...big.map((p) => p[0])), Math.min(...big.map((p) => p[1])),
      Math.max(...big.map((p) => p[0])), Math.max(...big.map((p) => p[1]))];
    ctx.label({ at: [(hx0 + hx1) / 2, (hz0 + hz1) / 2], name: 'отвалы', priority: 9, cls: 'quiet', minK: 0.5, sides: ['c'] });
  }

  // ------------------------------------------------------------- tailings
  for (const cell of M.land.cells) {
    layers.tailings.append(S('path', { class: 'pl-cell', d: pathOf(cell, true) },
      S('title', {}, 'Карта хвостохранилища (номер не опубликован)')));
  }
  if (M.facility) {
    const facility = S('path', { class: 'pl-facility', d: pathOf(M.facility.outline, true), 'data-bind': 'tailings' });
    layers.tailings.append(facility, hit(pathOf(M.facility.outline, true), M.facility.id, 'edge'));
    ctx.thing(M.facility.id, facility);
    const label = ctx.label({
      id: M.facility.id, at: () => [M.boxes[M.facility.id][0], (M.boxes[M.facility.id][1] + M.boxes[M.facility.id][3]) / 2],
      name: 'Хвостохранилище', priority: 2, sides: ['l'], gap: 10,
    });
    ctx.on(M.facility.id, (thing) => label.set('Хвостохранилище', yearsLeft(thing.f.years_left), stateTone(thing.f.state, 'tailings_facility')));
  }
  for (const dam of M.dams) {
    const d = pathOf(dam.outline, true);
    const fill = S('path', { class: 'pl-dam-fill', d, 'fill-opacity': dam.planned ? 0 : 0.1 });
    const edge = S('path', { class: 'pl-dam', d, 'data-thing': dam.id, 'data-state': dam.planned ? 'planned' : '', 'data-bind': 'tailings' });
    const g = S('g', { class: 'pl-damg' }, fill, edge);
    layers.tailings.append(g);
    ctx.thing(dam.id, edge);
    const name = shortName(dam.id) || '';
    const label = ctx.label({ id: dam.id, at: dam.centre, name, priority: 2, sides: ['c'], gauge: true });
    ctx.on(dam.id, (thing) => {
      const f = thing.f;
      const share = isNum(f.fill_pct) ? clamp(f.fill_pct / 100, 0, 1) : 0;
      set(fill, { 'fill-opacity': f.state === 'planned' ? 0 : (0.1 + 0.62 * share).toFixed(3) });
      set(edge, { 'data-state': f.state || '', 'data-tone': stateTone(f.state, 'tailings_dam') });
      const value = f.state === 'planned' ? 'проект' : `${stateLabel(f.state, 'tailings_dam')}: ${fmt(f.fill_pct, 0)} %`;
      label.set(name, value, stateTone(f.state, 'tailings_dam'), f.state === 'planned' ? null : share);
    });
  }

  // ---------------------------------------------------------------- water
  if (M.water.river.length) {
    layers.water.append(S('path', { class: 'pl-river', d: pathOf(M.water.river) }));
    ctx.flowLabel(M.water.river, 'р. Секисовка');
  }
  if (M.water.stream.length) {
    layers.water.append(S('path', { class: 'pl-stream', d: pathOf(M.water.stream) }));
    ctx.flowLabel(M.water.stream, 'руч. Волчевка', 0.55);
  }
  for (const pond of M.ponds) {
    const node = S('path', { class: 'pl-pond', d: pathOf(pond.outline, true), 'data-thing': pond.id, 'data-bind': 'dewatering' });
    layers.water.append(node);
    ctx.thing(pond.id, node);
    ctx.on(pond.id, (thing) => set(node, { 'data-tone': stateTone(thing.f.state, 'settling_pond') }));
  }
  if (M.ponds.length) {
    const z0 = Math.min(...M.ponds.map((p) => M.boxes[p.id][1]));
    const z1 = Math.max(...M.ponds.map((p) => M.boxes[p.id][3]));
    const label = ctx.label({
      id: M.ponds[0].id, at: [Math.max(...M.ponds.map((p) => M.boxes[p.id][2])), (z0 + z1) / 2],
      name: 'Илоотстойники', priority: 4, sides: ['r', 'l', 't'], gap: 6,
    });
    ctx.on(M.ponds[0].id, (thing) => label.set('Илоотстойники', `приток ${withUnit(fmt(thing.f.inflow_m3h), 'м³/ч')}`));
  }

  // ------------------------------------------------------------------ pit
  if (M.pit) {
    const g = S('g', { class: 'pl-pit' });
    for (const bench of M.pit.benches) {
      for (const lineAt of bench.lines) g.append(S('path', { class: 'bench', d: pathOf(lineAt) }));
    }
    if (M.pit.floorOutline.length) g.append(S('path', { class: 'floor', d: pathOf(M.pit.floorOutline, true) }));
    g.append(S('path', { class: 'rim', d: pathOf(M.pit.outline, true) }));
    layers.pit.append(g);
    const box = M.boxes[M.ns + 'mine'];
    ctx.label({
      at: [(box[0] + box[2]) / 2, box[3]], name: 'Карьер (отработан)',
      value: `дно ${fmt(M.pit.floor, 0, { sign: true })} м`, priority: 2, sides: ['b', 'r', 'l'], gap: 5,
    });
  }

  // ---------------------------------------------------------------- roads
  const osm = M.osmRoads.map(([a, b]) => `M${a[0]} ${a[1]}L${b[0]} ${b[1]}`).join('');
  if (osm) {
    layers.roads.append(S('path', { class: 'pl-road-case', d: osm }), S('path', { class: 'pl-road', d: osm }));
  }
  for (const road of M.haulRoads) {
    const d = pathOf(road.points);
    layers.roads.append(
      S('path', { class: 'pl-haul-case', d, 'data-bind': 'haulage' }),
      S('path', { class: 'pl-haul', d }));
  }

  // -------------------------------------------- pipelines and the conveyor
  for (const pipe of M.pipes) {
    const kind = pipe.name === 'conveyor' ? 'conveyor' : pipe.name.replace('pipeline-', '');
    const title = {
      conveyor: 'Конвейер от рудного склада на фабрику (схема)',
      tailings: 'Пульпопровод на хвостохранилище (схема)',
      'water-supply': 'Водовод на фабрику (схема)',
      discharge: 'Сброс очищенной воды в ручей (схема)',
      intake: 'Водозабор из реки (схема)',
    }[kind] || '';
    const bind = { conveyor: 'plant', tailings: 'tailings', 'water-supply': 'water', intake: 'water', discharge: 'dewatering' }[kind] || '';
    layers.pipes.append(S('path', { class: `pl-pipe ${kind}`, d: pathOf(pipe.points), 'data-bind': bind }, S('title', {}, title)));
  }

  // --------------------------------------------------- plant and the pad
  if (M.plant) {
    const node = S('path', { class: 'pl-plant', d: pathOf(M.plant.outline, true), 'data-thing': M.plant.id, 'data-bind': 'plant' });
    layers.plant.append(node);
    ctx.thing(M.plant.id, node);
    const box = M.boxes[M.plant.id];
    const label = ctx.label({
      id: M.plant.id, at: [box[2], (box[1] + box[3]) / 2], name: 'Фабрика', priority: 1, sides: ['r', 't', 'b'], gap: 8,
    });
    ctx.on(M.plant.id, (thing) => {
      const f = thing.f;
      set(node, { 'data-tone': stateTone(f.state, 'plant') });
      const lines = isNum(f.lines_running) ? `, линий ${fmt(f.lines_running)}` : '';
      label.set('Фабрика', `${withUnit(fmt(f.feed_tph, 1), 'т/ч')}${lines}`, stateTone(f.state, 'plant'));
    });
  }
  for (const item of M.lines) {
    const [bx0, bz0, bx1, bz1] = item.box;
    const box = S('rect', { class: 'box', x: bx0, y: bz0, width: bx1 - bx0, height: bz1 - bz0 });
    const fill = S('rect', { class: 'fill', x: bx0, y: bz1, width: bx1 - bx0, height: 0 });
    const g = S('g', { class: 'pl-line', 'data-thing': item.id, 'data-state': item.planned ? 'planned' : '' }, box, fill);
    layers.plant.append(g);
    ctx.thing(item.id, g);
    ctx.label({ id: item.id, at: [(bx0 + bx1) / 2, (bz0 + bz1) / 2], name: String(item.n), priority: 8, minK: 2.2, sides: ['c'], cls: 'tag' });
    ctx.on(item.id, (thing) => {
      const f = thing.f;
      const share = isNum(f.utilisation_pct) ? clamp(f.utilisation_pct / 100, 0, 1) : 0;
      const h = (bz1 - bz0) * share;
      set(fill, { y: bz1 - h, height: h });
      set(g, { 'data-state': f.state || '', 'data-tone': stateTone(f.state, 'plant_line') });
    });
  }
  if (M.rom) {
    const pad = M.rom.pad ? S('path', { class: 'pad', d: pathOf(M.rom.pad, true) }) : null;
    const heap = S('circle', { class: 'heap', cx: M.rom.at[0], cy: M.rom.at[1], r: M.rom.radius });
    const g = S('g', { class: 'pl-rom', 'data-thing': M.rom.id }, pad, heap);
    layers.plant.append(g);
    ctx.thing(M.rom.id, g);
    const label = ctx.label({ id: M.rom.id, at: M.rom.at, name: 'Рудный склад', priority: 4, sides: ['b', 't', 'l', 'r'], gap: 14 });
    ctx.on(M.rom.id, (thing) => {
      const f = thing.f;
      const share = isNum(f.tonnes) && M.rom.ref > 0 ? clamp(f.tonnes / M.rom.ref, 0.02, 2) : 1;
      set(heap, { r: Math.max(4, M.rom.radius * Math.sqrt(share)) });
      set(g, { 'data-tone': stateTone(f.state, 'rom_stockpile') });
      label.set('Рудный склад', withUnit(fmt(isNum(f.tonnes) ? f.tonnes / 1000 : NaN, 1), 'тыс. т'), stateTone(f.state, 'rom_stockpile'));
    });
  }
  if (M.village) {
    ctx.label({ at: M.village, name: 'с. Секисовка', priority: 5, sides: ['c'], cls: 'place' });
  }
}

/** Level drives, accesses, crosscuts and airway links, and the two declines, in plan. */
export function buildUnderground(ctx) {
  const { M, layers } = ctx;
  const g = layers.under;
  // Deeper levels are drawn fainter; the levels stand on top of each other in plan.
  const deep = M.levels.length ? M.levels[M.levels.length - 1].elevation : -300;
  const top = M.levels.length ? M.levels[0].elevation : 320;
  const fade = (elevation) => (0.95 - 0.55 * (top - elevation) / Math.max(1, top - deep)).toFixed(2);
  for (const backfill of M.backfill) {
    const [cx, , cz] = backfill.center;
    const [sx, , sz] = backfill.size;
    g.append(S('rect', { class: 'pl-backfill', x: cx - sx / 2, y: cz - sz / 2, width: sx, height: sz }));
  }
  // The levels stand on top of each other in plan: one drive line for the
  // developed levels (planned extensions dashed), and the accesses, crosscuts
  // and chambers of every level, deeper ones fainter (one line where they coincide).
  const span = (list) => {
    const xs = list.flatMap((level) => level.points.map((p) => p[0]));
    return xs.length ? [Math.min(...xs), Math.max(...xs)] : null;
  };
  const built = M.levels.filter((level) => !level.planned);
  const driveZ = M.levels.length && M.levels[0].points.length ? M.levels[0].points[0][1] : 0;
  const builtSpan = span(built);
  const designSpan = span(M.levels.filter((level) => level.planned));
  if (designSpan) {
    for (const [a, b] of [[designSpan[0], builtSpan ? builtSpan[0] : designSpan[1]], [builtSpan ? builtSpan[1] : designSpan[0], designSpan[1]]]) {
      if (b - a > 1) g.append(S('path', { class: 'pl-drive design', d: `M${a} ${driveZ}L${b} ${driveZ}` }));
    }
  }
  if (builtSpan) g.append(S('path', { class: 'pl-drive', d: `M${builtSpan[0]} ${driveZ}L${builtSpan[1]} ${driveZ}` }));
  const drawn = new Set();
  for (const level of M.levels) {
    for (const link of level.links) {
      if (link.role === 'airway') continue;
      const d = pathOf(link.points);
      if (drawn.has(d)) continue;
      drawn.add(d);
      g.append(S('path', {
        class: `pl-link ${link.role}${link.planned ? ' design' : ''}`, d, style: `opacity: ${fade(level.elevation)}`,
      }));
    }
  }
  // Airway links of the top level reach the shafts and raises.
  const first = M.levels[0];
  if (first) {
    for (const link of first.links.filter((l) => l.role === 'airway')) {
      g.append(S('path', { class: `pl-airlink${link.planned ? ' design' : ''}`, d: pathOf(link.points) }));
    }
  }
  for (const decline of M.declines) {
    const [sx0, sx1] = decline.span;
    const d = `M${sx0} ${decline.z}L${sx1} ${decline.z}`;
    const way = S('path', { class: 'way', d });
    const nodes = S('g', { class: 'nodes' });
    for (const node of decline.nodes) {
      if (node.type === 'portal') continue;
      nodes.append(S('path', { class: `node ${node.type}${node.planned ? ' design' : ''}`, d: `M${node.xz[0]} ${node.xz[1] - 5}L${node.xz[0]} ${node.xz[1] + 5}` }));
    }
    const dg = S('g', { class: 'pl-decline', 'data-thing': decline.id, 'data-state': 'open' }, way, nodes, hit(d, decline.id));
    g.append(dg);
    ctx.thing(decline.id, dg);
    const name = shortName(decline.id) || '';
    const label = ctx.label({
      id: decline.id, at: [sx1, decline.z], name: `${name} (схема)`, priority: 6, under: true, minK: 0.8,
      sides: decline.token === 'tu1' ? ['b', 'r'] : ['r', 'b'], gap: 8, cls: 'under',
    });
    ctx.on(decline.id, (thing) => {
      set(dg, { 'data-state': thing.f.state || '' });
      label.set(`${name} (схема)`, `забой ${fmt(thing.f.bottom_elevation, 0, { sign: true })} м`, stateTone(thing.f.state, 'decline'));
    });
  }
}
