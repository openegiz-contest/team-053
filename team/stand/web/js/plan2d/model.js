// What the plan reads from geometry.json (and the OSM copy in osm.js): every
// drawable item as plan coordinates [x, z] in metres from the mine point
// (x east, z south, so that z grows down the screen with north up), the
// terrain for the surface test of the trucks, and the routes the trucks are
// tweened along.

import OSM from './osm.js';

const TEXTURE_URL = '/terrain/texture.jpg';
const XZ = (p) => [p[0], p[2]];

/** Bounding box [x0, z0, x1, z1] of plan points. */
export function bboxOf(points) {
  let x0 = Infinity;
  let z0 = Infinity;
  let x1 = -Infinity;
  let z1 = -Infinity;
  for (const [x, z] of points) {
    if (x < x0) x0 = x;
    if (x > x1) x1 = x;
    if (z < z0) z0 = z;
    if (z > z1) z1 = z;
  }
  return [x0, z0, x1, z1];
}

export function unionBox(boxes) {
  const live = boxes.filter(Boolean);
  if (!live.length) return null;
  return [Math.min(...live.map((b) => b[0])), Math.min(...live.map((b) => b[1])),
    Math.max(...live.map((b) => b[2])), Math.max(...live.map((b) => b[3]))];
}

/** Area centroid of a polygon, the label point of an outline. */
export function centroidOf(points) {
  let a = 0;
  let cx = 0;
  let cz = 0;
  for (let i = 0; i < points.length; i += 1) {
    const [x1, z1] = points[i];
    const [x2, z2] = points[(i + 1) % points.length];
    const cross = x1 * z2 - x2 * z1;
    a += cross;
    cx += (x1 + x2) * cross;
    cz += (z1 + z2) * cross;
  }
  if (Math.abs(a) < 1e-6) {
    const box = bboxOf(points);
    return [(box[0] + box[2]) / 2, (box[1] + box[3]) / 2];
  }
  return [cx / (3 * a), cz / (3 * a)];
}

/** Bilinear ground elevation of the terrain block, with the finer inset over the pit. */
function terrainSampler(terrain) {
  const grid = (block) => {
    if (!block || !Array.isArray(block.rows) || !block.rows.length) return null;
    const [ox, oz] = block.origin;
    const step = block.spacing;
    const rows = block.rows;
    const nz = rows.length;
    const nx = rows[0].length;
    return (x, z) => {
      const fi = (x - ox) / step;
      const fj = (z - oz) / step;
      if (fi < 0 || fj < 0 || fi > nx - 1 || fj > nz - 1) return null;
      const i = Math.min(nx - 2, Math.floor(fi));
      const j = Math.min(nz - 2, Math.floor(fj));
      const u = fi - i;
      const v = fj - j;
      const top = rows[j][i] * (1 - u) + rows[j][i + 1] * u;
      const bottom = rows[j + 1][i] * (1 - u) + rows[j + 1][i + 1] * u;
      return top * (1 - v) + bottom * v;
    };
  };
  const main = grid(terrain);
  const inset = grid(terrain && terrain.inset);
  return (x, z) => {
    const fine = inset ? inset(x, z) : null;
    if (fine !== null) return fine;
    return main ? main(x, z) : null;
  };
}

/** A 3D route (road or decline) with cumulative lengths, for tweening along it. */
function routeOf(id, points) {
  const cum = [0];
  for (let i = 1; i < points.length; i += 1) {
    const [ax, ay, az] = points[i - 1];
    const [bx, by, bz] = points[i];
    cum.push(cum[i - 1] + Math.hypot(bx - ax, by - ay, bz - az));
  }
  return {
    id,
    points,
    length: cum[cum.length - 1],
    /** Nearest point of the route: { s: metres along it, d: distance }. */
    project([px, py, pz]) {
      let best = { s: 0, d: Infinity };
      for (let i = 1; i < points.length; i += 1) {
        const [ax, ay, az] = points[i - 1];
        const [bx, by, bz] = points[i];
        const dx = bx - ax;
        const dy = by - ay;
        const dz = bz - az;
        const len2 = dx * dx + dy * dy + dz * dz;
        const t = len2 > 0 ? Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy + (pz - az) * dz) / len2)) : 0;
        const d = Math.hypot(ax + dx * t - px, ay + dy * t - py, az + dz * t - pz);
        if (d < best.d) best = { s: cum[i - 1] + t * (cum[i] - cum[i - 1]), d };
      }
      return best;
    },
    /** Point [x, y, z] at s metres along the route. */
    at(s) {
      if (s <= 0) return points[0].slice();
      for (let i = 1; i < points.length; i += 1) {
        if (s <= cum[i] || i === points.length - 1) {
          const span = cum[i] - cum[i - 1] || 1;
          const t = Math.max(0, Math.min(1, (s - cum[i - 1]) / span));
          const a = points[i - 1];
          const b = points[i];
          return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
        }
      }
      return points[points.length - 1].slice();
    },
  };
}

/** Short Russian names of the things the plan labels. */
const SHORT = {
  'decline-tu1': 'ТУ-1', 'decline-tu2': 'ТУ-2',
  'shaft-vs1': 'ВС-1', 'shaft-vs2': 'ВС-2', 'shaft-vs3': 'ВС-3',
  'raise-vpv': 'ВПВ', 'raise-vhv-tu1': 'ВХВ ТУ-1', 'raise-vhv-tu2': 'ВХВ ТУ-2', 'raise-vhv-exhaust': 'ВХВ 7, 8, 10',
  'ps-p150': 'Насосная +150', 'ps-m050': 'Насосная −50', 'ps-m200': 'Насосная −200',
  'tsf-dam4': 'Дамба № 4', 'tsf-dam2': 'Дамба № 2', 'tsf-dam3': 'Дамба № 3', 'tsf-cell5': 'Карта № 5',
  'mon-volchevka': 'Выпуск в Волчевку', 'mon-sekisovka': 'Пост на Секисовке',
  'pond-upper': 'Илоотстойник верхний', 'pond-lower': 'Илоотстойник нижний',
};

export function shortName(id) {
  return SHORT[id.replace(/^.*:/, '')] || null;
}

export function readModel(geometry) {
  const ns = (geometry.namespace || 'kz.sekis') + ':';
  const objects = geometry.objects || {};
  const scenery = geometry.scenery || {};
  const terrain = geometry.terrain || {};
  const texture = terrain.texture || {};
  const terrainAt = terrainSampler(terrain);
  const byKind = (kind) => Object.entries(objects).filter(([, o]) => o.kind === kind);
  const anchors = {};     // thing id -> [x, z], the focus and label point
  const boxes = {};       // thing id -> [x0, z0, x1, z1] of an outline
  const under = {};       // thing id -> true when it is drawn with the underground part
  const kinds = {};
  for (const [id, o] of Object.entries(objects)) {
    kinds[id] = o.kind;
    if (Array.isArray(o.anchor)) anchors[id] = XZ(o.anchor);
  }
  const surfaceAt = (p, margin = 3) => {
    const ground = terrainAt(p[0], p[2]);
    return ground === null || p[1] >= ground - margin;
  };

  // ------------------------------------------------------------- the image
  const image = {
    href: TEXTURE_URL,
    extent: texture.extent || terrain.extent || [-2000, -2000, 2000, 2000],   // x0, z0, x1, z1; north up
  };

  // ------------------------------------------------------------ the surface
  const pitItem = scenery['old-pit'] || {};
  const pit = pitItem.outline ? {
    outline: pitItem.outline,
    floorOutline: pitItem.floor_outline || [],
    floor: pitItem.floor,
    top: pitItem.top,
    benches: (pitItem.benches || []).map((bench) => ({ y: bench.y, lines: bench.lines || [] })),
    centre: XZ(pitItem.base || [0, 0, 0]),
  } : null;

  const line3 = (name) => (scenery[name] && Array.isArray(scenery[name].points) ? scenery[name].points : null);
  const haulRoads = ['road-tu1', 'road-tu2'].filter((name) => line3(name)).map((name) => ({
    name, decline: scenery[name].decline, points: scenery[name].points.map(XZ), route: routeOf(name, scenery[name].points),
  }));
  const osmRoads = (OSM.roads && OSM.roads.edges ? OSM.roads.edges : [])
    .map(([i, j]) => [OSM.roads.nodes[i], OSM.roads.nodes[j]]);
  const water = {
    stream: line3('stream-volchevka') ? line3('stream-volchevka').map(XZ) : [],
    river: line3('river-sekisovka') ? line3('river-sekisovka').map(XZ) : [],
  };
  const pipes = ['conveyor', 'pipeline-tailings', 'pipeline-water-supply', 'pipeline-discharge', 'pipeline-intake']
    .filter((name) => line3(name)).map((name) => ({ name, points: line3(name).map(XZ) }));
  const outline = (name) => (scenery[name] && scenery[name].footprint ? scenery[name].footprint : null);
  const land = {
    industrial: outline('industrial-zone'),
    yard: outline('yard'),
    cells: ['tsf-cell-south', 'tsf-cell-southeast'].map(outline).filter(Boolean),
    heaps: OSM.heaps || [],
    quarry: OSM.quarry_north || null,
  };
  const village = scenery.village && scenery.village.anchor ? XZ(scenery.village.anchor) : null;

  const ponds = byKind('settling_pond').map(([id, o]) => {
    const points = o.outline || [];
    boxes[id] = bboxOf(points);
    return { id, outline: points, centre: centroidOf(points) };
  });
  const dams = byKind('tailings_dam').map(([id, o]) => {
    const points = o.footprint || [];
    boxes[id] = bboxOf(points);
    anchors[id] = centroidOf(points);
    return { id, outline: points, centre: anchors[id], planned: !!o.planned };
  });
  const [facilityId, facilityObj] = byKind('tailings_facility')[0] || [];
  const facility = facilityId ? {
    id: facilityId, outline: facilityObj.footprint || [], distance: facilityObj.true_distance, bearing: facilityObj.bearing_deg,
  } : null;
  if (facility) boxes[facility.id] = bboxOf(facility.outline);

  const [plantId, plantObj] = byKind('plant')[0] || [];
  const plant = plantId ? { id: plantId, outline: plantObj.footprint || [] } : null;
  if (plant) {
    boxes[plant.id] = bboxOf(plant.outline);
    anchors[plant.id] = centroidOf(plant.outline);
  }
  const lines = byKind('plant_line').map(([id, o]) => {
    const [cx, , cz] = o.center;
    const [sx, , sz] = o.size;
    boxes[id] = [cx - sx / 2, cz - sz / 2, cx + sx / 2, cz + sz / 2];
    return { id, box: boxes[id], n: Number(id.split('-').pop()), planned: !!o.planned };
  });
  const [romId, romObj] = byKind('rom_stockpile')[0] || [];
  const rom = romId ? {
    id: romId, at: XZ(romObj.base), radius: romObj.radius || 30, ref: romObj.reference_t || 0,
    pad: romObj.pad || null,
  } : null;
  if (rom && rom.pad) boxes[rom.id] = bboxOf(rom.pad);

  const monitors = byKind('monitoring_point').map(([id, o]) => ({ id, at: XZ(o.anchor) }));

  // ------------------------------------------- shafts, raises, fans, portals
  const shafts = byKind('shaft').map(([id, o]) => ({ id, at: XZ(o.base), planned: !!o.planned, kind: 'shaft' }));
  const raises = byKind('raise').map(([id, o]) => {
    const top = [o.base[0], o.top, o.base[2]];
    const surface = surfaceAt(top);
    if (!surface) under[id] = true;
    return { id, at: XZ(o.base), planned: !!o.planned, surface, exhaust: o.direction === 'exhaust', kind: 'raise' };
  });
  const fans = byKind('main_fan').map(([id, o]) => {
    const surface = surfaceAt(o.anchor, 6);
    if (!surface) under[id] = true;
    return { id, at: XZ(o.anchor), planned: !!o.planned, surface, airway: (o.airway || [])[0] || null };
  });

  // ------------------------------------------------------------ underground
  const declines = byKind('decline').map(([id, o]) => {
    under[id] = true;
    const points = o.points || [];
    const plan = points.map(XZ);
    const xs = plan.map((p) => p[0]);
    const nodes = (o.nodes || []).map((node) => ({ ...node, xz: XZ(node.at) }));
    const portal = nodes.length ? nodes[0].xz : plan[0];
    // The first leg leaves the portal: the opening of the portal faces the other way.
    const next = plan.find((p) => Math.hypot(p[0] - portal[0], p[1] - portal[1]) > 1) || [portal[0] + 1, portal[1]];
    return {
      id, token: o.token, plan, nodes, portal,
      heading: Math.atan2(next[1] - portal[1], next[0] - portal[0]),
      span: [Math.min(...xs), Math.max(...xs)],
      z: plan.length ? plan[0][1] : 0,
      route: routeOf(id, points),
      bottom: o.bottom_elevation, designBottom: o.design_bottom, portalElevation: o.portal_elevation,
    };
  });
  const levels = byKind('level').map(([id, o]) => {
    under[id] = true;
    return {
      id, elevation: o.elevation, planned: !!o.planned, role: o.role,
      points: (o.points || []).map(XZ),
      links: (o.links || []).map((link) => ({ to: link.to, role: link.role, planned: !!link.planned, points: link.points.map(XZ) })),
    };
  }).sort((a, b) => b.elevation - a.elevation);
  const levelElevation = Object.fromEntries(levels.map((level) => [level.id, level.elevation]));
  const stopes = byKind('stope').map(([id, o]) => {
    under[id] = true;
    const [cx, , cz] = o.center;
    const [sx, , sz] = o.size;
    return { id, x0: cx - sx / 2, x1: cx + sx / 2, z: cz, thickness: sz, level: o.level, elevation: levelElevation[o.level] };
  });
  // Stopes stand on top of each other in plan: one column per strike position.
  const columnMap = new Map();
  for (const stope of stopes) {
    const key = Math.round((stope.x0 + stope.x1) / 2);
    if (!columnMap.has(key)) columnMap.set(key, { x0: stope.x0, x1: stope.x1, z: stope.z, stopes: [] });
    columnMap.get(key).stopes.push(stope);
  }
  const columns = [...columnMap.values()].sort((a, b) => a.x0 - b.x0);
  for (const column of columns) column.stopes.sort((a, b) => b.elevation - a.elevation);
  const pumps = byKind('pump_station').map(([id, o]) => {
    under[id] = true;
    return { id, at: XZ(o.anchor), elevation: o.elevation, planned: !!o.planned };
  }).sort((a, b) => b.elevation - a.elevation);
  const backfill = Object.entries(scenery).filter(([name]) => name.startsWith('backfill-')).map(([, o]) => o);

  // Units park in the yard; live positions are pos_x, pos_y, pos_z.
  const units = Object.fromEntries(Object.entries(objects).filter(([, o]) => o.mobile)
    .map(([id, o]) => [id, { kind: o.kind, at: XZ(o.anchor), y: o.anchor[1] }]));

  const routes = [...haulRoads.map((road) => road.route), ...declines.map((decline) => decline.route)];

  // Things without a place of their own are framed by what stands for them.
  const pitBox = pit ? bboxOf(pit.outline) : null;
  if (pitBox) {
    boxes[ns + 'mine'] = pitBox;
    anchors[ns + 'mine'] = pit.centre;
  }
  const waterBox = unionBox([...ponds.map((pond) => boxes[pond.id]), ...monitors.map((m) => [m.at[0], m.at[1], m.at[0], m.at[1]])]);
  if (waterBox) {
    boxes[ns + 'water'] = waterBox;
    anchors[ns + 'water'] = [(waterBox[0] + waterBox[2]) / 2, (waterBox[1] + waterBox[3]) / 2];
  }
  const tailBox = facility ? boxes[facility.id] : null;
  if (facility) anchors[facility.id] = centroidOf(facility.outline);

  // Default framing: the pit, the plant and the tailings, with the edge of the village.
  const home = unionBox([pitBox, plant ? boxes[plant.id] : null, tailBox,
    village ? [village[0] + 120, village[1] - 120, village[0] + 120, village[1] - 120] : null]) || image.extent;
  const presets = {
    pit: pitBox ? unionBox([pitBox, [-300, -180, 240, 220]]) : home,
    plant: unionBox([plant ? boxes[plant.id] : null, rom && rom.pad ? bboxOf(rom.pad) : null, waterBox]),
    tailings: unionBox([tailBox, ...dams.map((dam) => boxes[dam.id])]),
  };
  if (ns + 'enterprise' in kinds) boxes[ns + 'enterprise'] = home;

  return {
    ns, image, pit, haulRoads, osmRoads, water, pipes, land, village, ponds, dams, facility, plant, lines, rom,
    monitors, shafts, raises, fans, declines, levels, stopes, columns, pumps, backfill, units, routes,
    anchors, boxes, under, kinds, home, presets, terrainAt, osmTimestamp: OSM.osm_timestamp || '',
  };
}
