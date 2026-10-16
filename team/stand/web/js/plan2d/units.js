// Trucks (and parked loaders and rigs) on the plan: each sample of pos_x,
// pos_y, pos_z is reached in one poll interval, along the haul road or the
// decline both samples lie on, otherwise in a straight line. A truck is a
// small box turned along its way, filled when loaded and hollow when empty; a
// ring marks one that waits or stands for a reason. A unit below the ground
// belongs to the underground part of the plan.

import { stateTone } from '../panels/dict.js';
import { isNum } from '../panels/format.js';
import { S, set } from './svg.js';

const RING_STATES = new Set(['waiting_bay', 'held_vent', 'maintenance', 'standby_vent']);
const ON_ROUTE_M = 6;       // a sample this close to a road or decline lies on it
const JUMP_M = 1800;        // a longer step between two samples is not animated
const COVER_M = 4;          // a unit this far under the ground at its position is underground

export function buildUnits(ctx, pollMs) {
  const { M, layers } = ctx;
  const units = [];

  for (const [id, unit] of Object.entries(M.units)) {
    const truck = unit.kind === 'haul_truck';
    const body = truck
      ? S('rect', { class: 'body', x: -5.5, y: -3, width: 11, height: 6, rx: 1.2 })
      : S('circle', { class: 'body', r: 2.6 });
    const cab = truck ? S('rect', { class: 'cab', x: 2.6, y: -3, width: 2.9, height: 6, rx: 0.8 }) : null;
    const turn = S('g', { class: 'turn' }, body, cab);
    const number = truck ? S('text', { class: 'no', x: 7, y: -6 }, String(Number(id.split('-').pop()))) : null;
    const g = S('g', { class: `pl-unit ${unit.kind}`, 'data-thing': id, 'data-state': 'parked' },
      S('circle', { class: 'pl-hit-fill', r: 8 }), S('circle', { class: 'ring', r: 8.5 }), turn, number);
    layers.units.append(g);
    const u = {
      id, kind: unit.kind, truck, g, turn,
      from: null, to: null, t0: 0, t1: 0, route: null, heading: 0, surface: true, parked: true, shown: false,
      position(now) {
        if (!this.to) return [unit.at[0], unit.y, unit.at[1]];
        const s = this.t1 > this.t0 ? Math.max(0, Math.min(1, (now - this.t0) / (this.t1 - this.t0))) : 1;
        if (this.route) return this.route.r.at(this.route.s0 + (this.route.s1 - this.route.s0) * s);
        return [0, 1, 2].map((i) => this.from[i] + (this.to[i] - this.from[i]) * s);
      },
      moving(now) {
        return this.to && now < this.t1 && (this.from[0] !== this.to[0] || this.from[2] !== this.to[2]);
      },
    };
    units.push(u);

    ctx.on(id, (thing, state, first) => {
      const f = thing.f;
      const now = performance.now();
      const target = [
        isNum(f.pos_x) ? f.pos_x : unit.at[0],
        isNum(f.pos_y) ? f.pos_y : unit.y,
        isNum(f.pos_z) ? f.pos_z : unit.at[1],
      ];
      const parked = f.state === 'parked';
      const here = u.to ? u.position(now) : target;
      const far = Math.hypot(target[0] - here[0], target[2] - here[2]) > JUMP_M;
      if (first || !u.to || far || parked !== u.parked) {
        u.from = target;
        u.to = target;
        u.route = null;
        u.t0 = u.t1 = now;
      } else {
        u.from = here;
        u.to = target;
        u.t0 = now;
        u.t1 = now + pollMs;
        u.route = null;
        let best = Infinity;
        for (const r of M.routes) {
          const a = r.project(here);
          const b = r.project(target);
          const straight = Math.hypot(target[0] - here[0], target[1] - here[1], target[2] - here[2]);
          if (a.d < ON_ROUTE_M && b.d < ON_ROUTE_M && Math.abs(b.s - a.s) <= straight * 4 + 60 && a.d + b.d < best) {
            best = a.d + b.d;
            u.route = { r, s0: a.s, s1: b.s };
          }
        }
      }
      u.parked = parked;
      set(g, {
        'data-state': f.state || '',
        'data-load': isNum(f.payload) && f.payload > 0 ? 'loaded' : 'empty',
        'data-ring': RING_STATES.has(f.state) ? stateTone(f.state, unit.kind) : null,
      });
    });
  }

  return {
    units,
    /** Place every unit for the time now; returns true while any of them still moves. */
    layout(now, toScreen, k) {
      let moving = false;
      for (const u of units) {
        const [x, y, z] = u.position(now);
        const ground = M.terrainAt(x, z);
        const surface = ground === null || y >= ground - COVER_M;
        if (surface !== u.surface) {
          u.surface = surface;
          u.g.classList.toggle('pl-under', !surface);
        }
        // Loaders and rigs are drawn only while they stand in the yard.
        const visible = u.truck || (u.parked && surface);
        if (visible !== u.shown) {
          u.shown = visible;
          u.g.style.display = visible ? '' : 'none';
        }
        if (!visible) continue;
        if (u.moving(now)) {
          moving = true;
          const [ax, , az] = u.position(now - 120);
          const [bx, , bz] = u.position(now + 120);
          if (Math.hypot(bx - ax, bz - az) > 0.05) u.heading = Math.atan2(bz - az, bx - ax);
        }
        const [sx, sy] = toScreen(x, z);
        u.screen = [sx, sy];
        u.g.setAttribute('transform', `translate(${sx.toFixed(1)} ${sy.toFixed(1)})`);
        u.turn.setAttribute('transform', `rotate(${(u.heading * 180 / Math.PI).toFixed(1)})${u.parked ? ' scale(0.62)' : ''}`);
        u.g.classList.toggle('near', k >= 1.6);
      }
      return moving;
    },
    /** Plan point of a unit now, for focus and the selection ring. */
    at(id, now) {
      const u = units.find((item) => item.id === id);
      if (!u || !u.shown) return null;
      const [x, , z] = u.position(now);
      return [x, z];
    },
    isUnder(id) {
      const u = units.find((item) => item.id === id);
      return !!u && !u.surface;
    },
  };
}
