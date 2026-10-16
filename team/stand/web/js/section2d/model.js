// Reads /api/geometry into what the long section draws: every object projected
// onto the X-Y plane (x east, y elevation), grouped by kind, and the ground of
// the section (the terrain profile along the ore zone, with the old pit
// projected onto it). Nothing here knows about pixels; ids are full thing ids.

import { NS } from '../panels/dict.js';
import { fmt, isNum } from '../panels/format.js';

const xy = (point) => [point[0], point[1]];
const span = (pairs) => {
  const xs = pairs.map((pair) => pair[0]);
  return [Math.min(...xs), Math.max(...xs)];
};

// Short Russian names for labels on the sheet (the full names are in the twins).
const SHORT = {
  'fan-vs1': 'ВС-1', 'fan-vs2': 'ВС-2', 'fan-vs3': 'ВС-3', 'fan-ug-p320': 'AL18-4500V', 'fan-vpv': 'ВПВ',
  'shaft-vs1': 'ствол ВС-1', 'shaft-vs2': 'ствол ВС-2', 'shaft-vs3': 'ствол ВС-3',
  'raise-vpv': 'ВПВ', 'raise-vhv-tu1': 'ВХВ ТУ-1', 'raise-vhv-tu2': 'ВХВ ТУ-2',
  'raise-vhv-exhaust': 'ВХВ 7, 8, 10',
  'decline-tu1': 'ТУ-1', 'decline-tu2': 'ТУ-2',
  'tsf-dam2': '№ 2', 'tsf-dam3': '№ 3', 'tsf-dam4': '№ 4', 'tsf-cell5': '№ 5',
  'mon-volchevka': 'выпуск в руч. Волчевка', 'mon-sekisovka': 'пост р. Секисовка',
};

export function shortName(id) {
  return SHORT[id.slice(NS.length)] || null;
}

/**
 * Air state of a level: 'short' when its flow is below the requirement, 'cut' when
 * the main fan of its intake airway has failed, otherwise 'ok'.
 */
export function levelAir(thing, state, M) {
  const f = thing.f;
  if (f.state === 'planned' || f.state === 'flooded') return 'ok';
  const intake = thing.attrs && thing.attrs.link_air_intake;
  const fanId = intake && M.fanByAirway[intake];
  const fan = fanId && state.things[fanId];
  if (fan && fan.f && fan.f.state === 'failed') return 'cut';
  const short = typeof f.air_flow_m3s === 'number' && typeof f.air_required_m3s === 'number'
    && f.air_required_m3s > 0 && f.air_flow_m3s < f.air_required_m3s - 0.05;
  return short ? 'short' : 'ok';
}

export function levelLabel(elevation) {
  return `гор. ${fmt(elevation, 0, { sign: true })} м`;
}

/** Linear interpolation of y over [x, y] pairs sorted by x, clamped at the ends. */
function interpolator(pairs) {
  if (!pairs.length) return () => null;
  return (x) => {
    if (x <= pairs[0][0]) return pairs[0][1];
    const last = pairs[pairs.length - 1];
    if (x >= last[0]) return last[1];
    let low = 0;
    let high = pairs.length - 1;
    while (high - low > 1) {
      const mid = (low + high) >> 1;
      if (pairs[mid][0] <= x) low = mid; else high = mid;
    }
    const [xa, ya] = pairs[low];
    const [xb, yb] = pairs[high];
    return xb === xa ? ya : ya + (yb - ya) * (x - xa) / (xb - xa);
  };
}

/** Elevation of a polyline [[x, y]] (sorted by x) at x inside its span, else null. */
export function along(pairs, x) {
  for (let i = 1; i < pairs.length; i += 1) {
    const [xa, ya] = pairs[i - 1];
    const [xb, yb] = pairs[i];
    if ((x - xa) * (x - xb) > 0) continue;
    return xb === xa ? Math.min(ya, yb) : ya + (yb - ya) * (x - xa) / (xb - xa);
  }
  return null;
}

/**
 * Ground of the terrain block at (x, z): bilinear on the main grid, or on the
 * finer inset over the old pit (which carries the carved pit). Null outside.
 */
function terrainSampler(terrain) {
  if (!terrain || !Array.isArray(terrain.rows) || !terrain.origin) return () => null;
  const grid = (block) => (x, z) => {
    const rows = block.rows;
    const fi = (x - block.origin[0]) / block.spacing;
    const fj = (z - block.origin[1]) / block.spacing;
    if (!rows.length || fi < 0 || fj < 0 || fj > rows.length - 1 || fi > rows[0].length - 1) return null;
    const i = Math.min(Math.floor(fi), rows[0].length - 2);
    const j = Math.min(Math.floor(fj), rows.length - 2);
    const u = fi - i;
    const v = fj - j;
    return (rows[j][i] * (1 - u) + rows[j][i + 1] * u) * (1 - v)
      + (rows[j + 1][i] * (1 - u) + rows[j + 1][i + 1] * u) * v;
  };
  const main = grid(terrain);
  const inset = terrain.inset && Array.isArray(terrain.inset.rows) && terrain.inset.origin ? grid(terrain.inset) : null;
  return (x, z) => {
    const fine = inset ? inset(x, z) : null;
    return fine !== null ? fine : main(x, z);
  };
}

export function readModel(geometry) {
  const objects = (geometry && geometry.objects) || {};
  const scenery = (geometry && geometry.scenery) || {};
  // frame.surface is a reference value (the TU1 portal); the drawn ground is the profile.
  const surfaceY = (geometry && geometry.frame && geometry.frame.surface) || 430;
  const profile = geometry && geometry.profile && Array.isArray(geometry.profile.points)
    ? geometry.profile.points.map(xy).sort((a, b) => a[0] - b[0]) : [];
  const M = {
    surfaceY, levels: [], stopes: [], declines: [], airways: [], fans: [], stations: [],
    backfill: [], plantLines: [], dams: [], ponds: [], monitors: [], roads: [],
    rom: null, pit: null, plant: null, tailings: null, units: {}, kinds: {}, info: {},
    profile, sourced: !!(geometry && geometry.profile && geometry.profile.sourced),
  };
  const profileAt = interpolator(profile);
  // The ground line of the section: the profile (the reference surface without one).
  M.groundAt = (x) => {
    const y = profileAt(x);
    return y === null ? surfaceY : y;
  };
  M.terrainAt = terrainSampler(geometry && geometry.terrain);

  for (const [id, o] of Object.entries(objects)) {
    M.kinds[id] = o.kind;
    if (o.kind === 'level') {
      const [x0, x1] = span(o.points);
      M.levels.push({ id, e: o.elevation, x0, x1, planned: !!o.planned });
    } else if (o.kind === 'stope') {
      M.stopes.push({
        id, level: o.level, planned: !!o.planned,
        x0: o.center[0] - o.size[0] / 2, x1: o.center[0] + o.size[0] / 2,
        y0: o.center[1] - o.size[1] / 2, y1: o.center[1] + o.size[1] / 2,
      });
      M.info[id] = { size: o.size };
    } else if (o.kind === 'decline') {
      M.declines.push({
        id, token: o.token, points: o.points.map(xy), bottom: o.bottom_elevation,
        nodes: (o.nodes || []).map((n) => ({ x: n.at[0], y: n.at[1], type: n.type })),
      });
    } else if (o.kind === 'shaft' || o.kind === 'raise') {
      M.airways.push({
        id, kind: o.kind, x: o.base[0], top: o.top, bottom: o.base[1], direction: o.direction,
        plannedBelow: o.planned_below, planned: !!o.planned,
      });
      if (isNum(o.documented_top)) M.info[id] = { top: o.top, documentedTop: o.documented_top };
    } else if (o.kind === 'main_fan') {
      M.fans.push({
        id, x: o.center[0], y: o.center[1], airways: o.airway || [], planned: !!o.planned,
        surface: o.center[1] >= surfaceY,
      });
    } else if (o.kind === 'pump_station') {
      M.stations.push({
        id, x: o.center[0], e: o.elevation, pipe: o.pipe || [], to: o.discharges_to,
        planned: !!o.planned,
      });
    } else if (o.kind === 'settling_pond') {
      // The mapped pond outline gives its extent along the section.
      const [x0, x1] = Array.isArray(o.outline) && o.outline.length > 2 ? span(o.outline)
        : [o.center[0] - o.size[0] / 2, o.center[0] + o.size[0] / 2];
      M.ponds.push({ id, x0, x1 });
    } else if (o.kind === 'monitoring_point') {
      M.monitors.push({ id, x: o.anchor[0] });
    } else if (o.kind === 'plant') {
      const [x0, x1] = span(o.footprint);
      M.plant = { id, x0, x1 };
    } else if (o.kind === 'plant_line') {
      M.plantLines.push({
        id, x0: o.center[0] - o.size[0] / 2, x1: o.center[0] + o.size[0] / 2, height: o.size[1], planned: !!o.planned,
      });
    } else if (o.kind === 'rom_stockpile') {
      const pad = Array.isArray(o.pad) && o.pad.length > 2 ? span(o.pad) : [o.base[0] - o.radius, o.base[0] + o.radius];
      M.rom = { id, x: o.base[0], radius: o.radius, height: o.height, ref: o.reference_t, pad };
    } else if (o.kind === 'tailings_facility') {
      M.tailings = { id, distance: o.true_distance, bearing: o.bearing_deg };
      M.info[id] = { distance: o.true_distance, bearing: o.bearing_deg };
    } else if (o.kind === 'tailings_dam') {
      const [x0, x1] = span(o.footprint);
      M.dams.push({ id, x0, x1, planned: !!o.planned, bottom: o.bottom, top: o.top });
    } else if (o.mobile) {
      M.units[id] = { kind: o.kind, x: o.anchor[0], z: o.anchor[2] };
    }
  }

  for (const [name, o] of Object.entries(scenery)) {
    if (name === 'old-pit' && o.primitive === 'pit' && Array.isArray(o.section) && o.section.length > 1) {
      M.pit = {
        section: o.section.map(xy).sort((a, b) => a[0] - b[0]),
        floor: o.floor, top: o.top,
        benches: (o.benches || []).map((bench) => bench.y).filter(isNum).sort((a, b) => a - b),
      };
    } else if (name.startsWith('backfill-') && o.primitive === 'box') {
      M.backfill.push({
        x0: o.center[0] - o.size[0] / 2, x1: o.center[0] + o.size[0] / 2,
        y0: o.center[1] - o.size[1] / 2, y1: o.center[1] + o.size[1] / 2,
      });
    } else if (name.startsWith('road-') && o.primitive === 'polyline') {
      M.roads.push({ decline: o.decline, points: o.points.map(xy) });
    }
  }

  // A discharge pipe runs on the ground from the collar of its shaft on: there the
  // section draws it on its own ground line (the pipe's ground lies off the section).
  for (const station of M.stations) {
    let surface = false;
    station.pipe = station.pipe.map(([x, y, z]) => {
      const ground = M.terrainAt(x, z);
      surface = surface || (ground !== null && y >= ground - 3);
      return surface ? [x, M.groundAt(x)] : [x, y];
    });
  }

  M.levels.sort((a, b) => b.e - a.e);
  M.dams.sort((a, b) => a.x0 - b.x0);
  M.plantLines.sort((a, b) => a.x0 - b.x0);
  M.plantLines.forEach((item, index) => { item.n = index + 1; });
  M.ponds.sort((a, b) => a.x0 - b.x0);
  M.monitors.sort((a, b) => a.x - b.x);

  const levelById = Object.fromEntries(M.levels.map((level) => [level.id, level]));
  const perLevel = {};
  M.stopes.sort((a, b) => a.x0 - b.x0);
  for (const stope of M.stopes) {
    const level = levelById[stope.level];
    perLevel[stope.level] = (perLevel[stope.level] || 0) + 1;
    stope.n = perLevel[stope.level];
    stope.e = level ? level.e : stope.y0;
    stope.short = `${fmt(stope.e)}-${stope.n}`;
  }
  // The stope block as the section sees it, face-on: along strike x height.
  M.stopeW = M.stopes.length ? Math.min(...M.stopes.map((stope) => stope.x1 - stope.x0)) : 106;
  M.stopeH = M.stopes.length ? Math.min(...M.stopes.map((stope) => stope.y1 - stope.y0)) : 50;

  // Extents: the underground workings, and everything that stands on the surface.
  const mineXs = [
    ...M.levels.flatMap((level) => [level.x0, level.x1]),
    ...M.declines.flatMap((decline) => decline.points.map((p) => p[0])),
    ...M.airways.map((airway) => airway.x),
  ];
  const surfaceXs = [
    ...(M.plant ? [M.plant.x0, M.plant.x1] : []),
    ...M.plantLines.flatMap((item) => [item.x0, item.x1]),
    ...(M.rom ? M.rom.pad : []),
    ...M.ponds.flatMap((pond) => [pond.x0, pond.x1]),
    ...M.monitors.map((item) => item.x),
    ...Object.values(M.units).map((unit) => unit.x),
  ];
  M.mineX0 = (mineXs.length ? Math.min(...mineXs) : -330) - 15;
  M.mineX1 = (mineXs.length ? Math.max(...mineXs) : 386) + 14;
  M.worldX0 = Math.min(M.mineX0, ...surfaceXs) - 12;
  // The surface east of the workings (ponds, stockpile, yard, plant) is drawn up to here.
  M.eastX1 = Math.max(M.mineX1, ...surfaceXs) + 12;
  // Stretches of ground that objects stand on: they keep their width when the strip is compressed.
  M.surfaceSpans = [
    ...(M.plant ? [[M.plant.x0, M.plant.x1]] : []),
    ...(M.rom ? [M.rom.pad] : []),
    ...M.ponds.map((pond) => [pond.x0, pond.x1]),
    ...M.monitors.map((item) => [item.x - 4, item.x + 4]),
    ...(Object.keys(M.units).length ? [span(Object.values(M.units).map((unit) => [unit.x]))] : []),
  ];

  // The old pit projected on the section: its lowest ground at x, or null outside it.
  M.pitAt = (x) => (M.pit ? along(M.pit.section, x) : null);

  // The top of the drawing: the highest ground drawn (the sheet may show up to
  // 500 m of ground west of the workings) and the feet of the tailings dams.
  let top = profile.length ? -Infinity : surfaceY;
  for (const [x, y] of profile) {
    if (x >= M.mineX0 - 500 && x <= M.eastX1) top = Math.max(top, y);
  }
  for (const dam of M.dams) if (isNum(dam.bottom)) top = Math.max(top, dam.bottom);
  M.top = Math.ceil(Number.isFinite(top) ? top : surfaceY);
  M.bottom = M.levels.length ? Math.min(...M.levels.map((level) => level.e)) : -300;
  // The deepest developed level at the start: airways are design only below it.
  const developed = M.levels.filter((level) => !level.planned).map((level) => level.e);
  M.developedBottom = developed.length ? Math.min(...developed) : M.bottom;
  M.parkRows = [...new Set(Object.values(M.units).map((unit) => unit.z))].sort((a, b) => a - b);
  // A fan that serves one airway: its failure stops the air of that airway.
  M.fanByAirway = {};
  for (const fan of M.fans) {
    if (fan.airways.length === 1) M.fanByAirway[fan.airways[0]] = fan.id;
  }
  return M;
}
