// Mobile equipment: trucks, loaders and drill rigs as small marks that glide
// between the 2 s samples of pos_x and pos_y. A truck is filled when loaded and
// hollow when empty; a ring marks a unit that waits or stands idle for a reason.
// Parked units stand in a rack on the surface, one tier per parking row.

import { stateTone } from '../panels/dict.js';
import { isNum } from '../panels/format.js';
import { S, set, text } from './svg.js';

const RING_STATES = new Set(['waiting_bay', 'held_vent', 'maintenance', 'standby_vent']);
const JUMP_M = 170;     // a longer step between two samples is not animated

export function buildUnits(ctx) {
  const { L, M, layers } = ctx;
  const { px, py, F } = L;
  const tw = F * 0.92;
  const th = F * 0.5;
  const tier = Math.max(2.6, F * 0.34);

  for (const [id, unit] of Object.entries(M.units)) {
    let shape;
    if (unit.kind === 'haul_truck') {
      shape = S('rect', { class: 'mark', x: -tw / 2, y: -th / 2, width: tw, height: th, rx: 1 });
    } else if (unit.kind === 'lhd') {
      shape = S('circle', { class: 'mark', r: F * 0.3 });
    } else {
      const a = F * 0.36;
      shape = S('path', { class: 'mark', d: `M${-a} ${a * 0.8}L0 ${-a}L${a} ${a * 0.8}Z` });
    }
    const number = unit.kind === 'haul_truck'
      ? text(0, -th / 2 - 2, String(Number(id.split('-').pop())), { class: 'sx-unit-no', 'text-anchor': 'middle' })
      : null;
    const g = S('g', { class: `sx-unit sx-obj ${unit.kind}`, 'data-thing': id, 'data-state': 'parked' },
      S('circle', { class: 'sx-hit-fill', r: F * 0.8 }),
      S('circle', { class: 'ring', r: F * 0.86 }),
      shape, number);
    layers.units.append(g);

    let last = null;
    ctx.on(id, (thing, state, first) => {
      const f = thing.f;
      const parked = f.state === 'parked';
      const wx = isNum(f.pos_x) ? f.pos_x : unit.x;
      const wy = isNum(f.pos_y) ? f.pos_y : M.top;
      let x = px(wx);
      let y;
      if (parked) {
        const z = isNum(f.pos_z) ? f.pos_z : unit.z;
        let row = 0;
        M.parkRows.forEach((rowZ, index) => {
          if (Math.abs(rowZ - z) < Math.abs(M.parkRows[row] - z)) row = index;
        });
        y = L.yg - 2 - tier / 2 - row * (tier + 1.2);
      } else if (wy >= M.top - 0.5) {
        y = L.yg - th / 2 - 1.5;                      // on the surface: standing on the ground line
      } else if (L.inbox) {
        // The stope boxes carry text: loaders and rigs stand on the drive, beside the truck.
        y = py(wy);
        if (unit.kind === 'lhd') x -= F * 1.0;
        if (unit.kind === 'drill_rig') x += F * 1.0;
      } else {
        y = py(wy) - (unit.kind === 'haul_truck' ? 0 : F * 0.78);
        if (unit.kind === 'drill_rig') x += F * 0.2;
      }
      const jump = !last || first || Math.hypot(wx - last[0], wy - last[1]) > JUMP_M || parked !== last[2];
      if (jump) {
        g.style.transition = 'none';
        g.style.transform = `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px)`;
        g.getBoundingClientRect();
        g.style.transition = '';
      } else {
        g.style.transform = `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px)`;
      }
      last = [wx, wy, parked];
      set(g, {
        'data-state': f.state || '',
        'data-load': isNum(f.payload) && f.payload > 0 ? 'loaded' : 'empty',
        'data-ring': RING_STATES.has(f.state) ? stateTone(f.state, unit.kind) : null,
      });
      ctx.reg(id, x, y);
    });
  }
}
