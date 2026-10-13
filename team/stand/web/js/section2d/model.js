// Reads /api/geometry into what the long section draws: every object projected
// onto the X-Y plane (x east, y elevation), grouped by kind. Nothing here knows
// about pixels; ids are full thing ids.

import { NS } from '../panels/dict.js';
import { fmt } from '../panels/format.js';

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

export function readModel(geometry) {
  const objects = (geometry && geometry.objects) || {};
  const scenery = (geometry && geometry.scenery) || {};
  const surfaceY = (geometry && geometry.frame && geometry.frame.surface) || 430;
  const M = {
    surfaceY, levels: [], stopes: [], declines: [], airways: [], fans: [], stations: [],
    backfill: [], plantLines: [], dams: [], ponds: [], monitors: [], roads: [],
    rom: null, pit: null, plant: null, tailings: null, units: {}, kinds: {},
  };

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
    } else if (o.kind === 'main_fan') {
      M.fans.push({
        id, x: o.center[0], y: o.center[1], airways: o.airway || [], planned: !!o.planned,
        surface: o.center[1] >= surfaceY,
      });
    } else if (o.kind === 'pump_station') {
      M.stations.push({
        id, x: o.center[0], e: o.elevation, pipe: (o.pipe || []).map(xy), to: o.discharges_to,
        planned: !!o.planned,
      });
    } else if (o.kind === 'settling_pond') {
      M.ponds.push({ id, x0: o.center[0] - o.size[0] / 2, x1: o.center[0] + o.size[0] / 2 });
    } else if (o.kind === 'monitoring_point') {
      M.monitors.push({ id, x: o.anchor[0] });
    } else if (o.kind === 'plant') {
      const [x0, x1] = span(o.footprint);
      M.plant = { id, x0, x1 };
    } else if (o.kind === 'plant_line') {
      M.plantLines.push({
        id, x0: o.center[0] - o.size[0] / 2, x1: o.center[0] + o.size[0] / 2, planned: !!o.planned,
      });
    } else if (o.kind === 'rom_stockpile') {
      M.rom = { id, x: o.base[0], radius: o.radius, height: o.height, ref: o.reference_t };
    } else if (o.kind === 'tailings_facility') {
      M.tailings = { id, distance: o.true_distance, bearing: o.bearing_deg };
    } else if (o.kind === 'tailings_dam') {
      const [x0, x1] = span(o.footprint);
      M.dams.push({ id, x0, x1, planned: !!o.planned });
    } else if (o.mobile) {
      M.units[id] = { kind: o.kind, x: o.anchor[0], z: o.anchor[2] };
    }
  }

  for (const [name, o] of Object.entries(scenery)) {
    if (name === 'old-pit' && o.primitive === 'frustum') {
      M.pit = { cx: o.base[0], floor: o.base[1], rFloor: o.radius_base, top: o.top, rTop: o.radius_top };
    } else if (name.startsWith('backfill-') && o.primitive === 'box') {
      M.backfill.push({
        x0: o.center[0] - o.size[0] / 2, x1: o.center[0] + o.size[0] / 2,
        y0: o.center[1] - o.size[1] / 2, y1: o.center[1] + o.size[1] / 2,
      });
    } else if (name.startsWith('road-') && o.primitive === 'polyline') {
      M.roads.push({ decline: o.decline, points: o.points.map(xy) });
    }
  }

  M.levels.sort((a, b) => b.e - a.e);
  M.dams.sort((a, b) => a.x0 - b.x0);
  M.plantLines.sort((a, b) => a.x0 - b.x0);
  M.plantLines.forEach((item, index) => { item.n = index + 1; });
  M.ponds.sort((a, b) => a.x0 - b.x0);

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

  // Extents: the underground workings, and everything that stands on the surface.
  const mineXs = [
    ...M.levels.flatMap((level) => [level.x0, level.x1]),
    ...M.declines.flatMap((decline) => decline.points.map((p) => p[0])),
    ...M.airways.map((airway) => airway.x),
  ];
  const surfaceXs = [
    ...M.plantLines.flatMap((item) => [item.x0, item.x1]),
    ...(M.rom ? [M.rom.x - M.rom.radius, M.rom.x + M.rom.radius] : []),
    ...M.monitors.map((item) => item.x),
  ];
  M.mineX0 = (mineXs.length ? Math.min(...mineXs) : -330) - 15;
  M.mineX1 = (mineXs.length ? Math.max(...mineXs) : 386) + 14;
  M.worldX0 = Math.min(M.mineX0, ...(surfaceXs.length ? surfaceXs : [M.mineX0])) - 12;
  M.top = surfaceY;
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
