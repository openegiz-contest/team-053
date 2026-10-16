// Labels of the plan in screen pixels: a name and one value line, placed on
// one of the sides of their anchor that is still free (greedy, by priority),
// so that labels never overlap each other, the point symbols or the map
// furniture. Water courses carry an italic name along the line.

import { S, set, setText } from './svg.js';

const MAX_LABELS = 34;
const NAME_PX = 12;
const VALUE_PX = 11;
const LINE_H = 13;

const overlaps = (a, b) => a[0] < b[2] && a[2] > b[0] && a[1] < b[3] && a[3] > b[1];

export function createLabels(layer, measure) {
  const items = [];

  function add(spec) {
    const node = S('g', { class: `pl-label ${spec.cls || ''}`, visibility: 'hidden' });
    if (spec.id) node.setAttribute('data-thing', spec.id);
    const name = S('text', { class: 'name' });
    const value = S('text', { class: 'value' });
    node.append(name, value);
    // A gauge under the text: the share of a whole (the fill of a tailings dam).
    const track = spec.gauge ? S('rect', { class: 'track', height: 4, rx: 1 }) : null;
    const bar = spec.gauge ? S('rect', { class: 'bar', height: 4, rx: 1 }) : null;
    if (track) node.append(track, bar);
    layer.append(node);
    const item = {
      ...spec, node, nameNode: name, valueNode: value,
      name: spec.name || '', value: spec.value || '', tone: spec.tone || '', share: null, track, bar,
      sides: spec.sides || ['r', 'l', 't', 'b'], gap: spec.gap === undefined ? 9 : spec.gap,
      priority: spec.priority === undefined ? 5 : spec.priority, dirty: true, w: 0, h: 0,
      set(nameText, valueText, tone, share) {
        const next = share === undefined ? null : share;
        if (nameText === this.name && (valueText || '') === this.value && (tone || '') === this.tone && next === this.share) return;
        this.name = nameText;
        this.value = valueText || '';
        this.tone = tone || '';
        this.share = next;
        this.dirty = true;
      },
    };
    items.push(item);
    return item;
  }

  function addFlow(points, name, fraction) {
    const node = S('text', { class: 'pl-flow', visibility: 'hidden' }, name);
    layer.append(node);
    const item = { flow: points, fraction, node, name, w: measure(name, 11, 400), priority: 6 };
    items.push(item);
    return item;
  }

  function measureItem(item) {
    if (!item.dirty) return;
    setText(item.nameNode, item.name);
    setText(item.valueNode, item.value);
    item.valueNode.style.display = item.value ? '' : 'none';
    set(item.node, { 'data-tone': item.tone || null });
    const nameSize = item.cls && item.cls.includes('tag') ? 10.5 : item.cls && item.cls.includes('place') ? 13 : NAME_PX;
    const weight = item.cls && item.cls.includes('quiet') ? 400 : 600;
    item.w = Math.max(measure(item.name, nameSize, weight), item.value ? measure(item.value, VALUE_PX) : 0);
    item.h = (item.value ? LINE_H * 2 : LINE_H) + (item.track && item.share !== null ? 7 : 0);
    if (item.track) {
      item.track.style.display = item.share === null ? 'none' : '';
      item.bar.style.display = item.share === null ? 'none' : '';
    }
    item.dirty = false;
  }

  function box(item, side, sx, sy) {
    const { w, h, gap } = item;
    switch (side) {
      case 'r': return [sx + gap, sy - h / 2, sx + gap + w, sy + h / 2];
      case 'l': return [sx - gap - w, sy - h / 2, sx - gap, sy + h / 2];
      case 't': return [sx - w / 2, sy - gap - h, sx + w / 2, sy - gap];
      case 'b': return [sx - w / 2, sy + gap, sx + w / 2, sy + gap + h];
      default: return [sx - w / 2, sy - h / 2, sx + w / 2, sy + h / 2];
    }
  }

  function draw(item, side, rect) {
    const anchor = side === 'r' ? 'start' : side === 'l' ? 'end' : 'middle';
    const x = side === 'r' ? rect[0] : side === 'l' ? rect[2] : (rect[0] + rect[2]) / 2;
    set(item.nameNode, { x, y: rect[1] + 10, 'text-anchor': anchor });
    set(item.valueNode, { x, y: rect[1] + 10 + LINE_H, 'text-anchor': anchor });
    if (item.track && item.share !== null) {
      const w = Math.max(40, Math.min(70, rect[2] - rect[0]));
      const x0 = side === 'r' ? rect[0] : side === 'l' ? rect[2] - w : (rect[0] + rect[2]) / 2 - w / 2;
      const y = rect[3] - 5;
      set(item.track, { x: x0, y, width: w });
      set(item.bar, { x: x0, y, width: Math.max(0, w * Math.min(1, item.share)) });
    }
  }

  /** The point of a water course to carry its name: in view, near the wanted share of its length. */
  function flowSpot(item, view, toScreen, size) {
    const pts = item.flow;
    let best = null;
    const want = item.fraction === undefined ? null : Math.floor((pts.length - 1) * item.fraction);
    const centre = [size.w / 2, size.h / 2];
    for (let i = 1; i < pts.length - 1; i += 1) {
      const [sx, sy] = toScreen(pts[i][0], pts[i][1]);
      if (sx < 40 || sy < 30 || sx > size.w - 40 || sy > size.h - 30) continue;
      const score = want !== null ? Math.abs(i - want) : Math.hypot(sx - centre[0], sy - centre[1]);
      if (!best || score < best.score) best = { i, sx, sy, score };
    }
    if (!best) return null;
    const a = toScreen(...pts[Math.max(0, best.i - 2)]);
    const b = toScreen(...pts[Math.min(pts.length - 1, best.i + 2)]);
    let angle = Math.atan2(b[1] - a[1], b[0] - a[0]) * 180 / Math.PI;
    if (angle > 90) angle -= 180;
    if (angle < -90) angle += 180;
    // Too steep to read: keep it level.
    if (Math.abs(angle) > 70) angle = 0;
    return { sx: best.sx, sy: best.sy, angle };
  }

  return {
    add,
    addFlow,
    /**
     * Place every label: ctx gives toScreen, k, the view size, the obstacles
     * (screen boxes of symbols and furniture) and the flags of the layers.
     */
    place({ toScreen, k, size, obstacles, showUnder, selected, forced }) {
      const taken = obstacles.slice();
      let shown = 0;
      const order = items.slice().sort((a, b) => {
        const pa = a.id && (a.id === selected || (forced && forced.has(a.id))) ? -1 : a.priority;
        const pb = b.id && (b.id === selected || (forced && forced.has(b.id))) ? -1 : b.priority;
        return pa - pb;
      });
      for (const item of order) {
        const hide = () => set(item.node, { visibility: 'hidden' });
        if (item.flow) {
          const spot = k >= 0.25 ? flowSpot(item, null, toScreen, size) : null;
          if (!spot) { hide(); continue; }
          const half = item.w / 2 + 2;
          const rect = [spot.sx - half, spot.sy - 9, spot.sx + half, spot.sy + 5];
          if (taken.some((t) => overlaps(t, rect))) { hide(); continue; }
          taken.push(rect);
          set(item.node, {
            x: spot.sx, y: spot.sy - 3, 'text-anchor': 'middle', visibility: 'visible',
            transform: `rotate(${spot.angle.toFixed(1)} ${spot.sx.toFixed(1)} ${spot.sy.toFixed(1)})`,
          });
          continue;
        }
        const important = item.id && (item.id === selected || (forced && forced.has(item.id)));
        if ((item.under && !showUnder) || !item.name || (!important && (k < (item.minK || 0) || k > (item.maxK || Infinity)))) {
          hide();
          continue;
        }
        if (!important && shown >= MAX_LABELS) { hide(); continue; }
        measureItem(item);
        const at = typeof item.at === 'function' ? item.at() : item.at;
        if (!at) { hide(); continue; }
        const [sx, sy] = toScreen(at[0], at[1]);
        let placed = null;
        for (const side of item.sides) {
          const rect = box(item, side, sx, sy);
          if (rect[0] < 2 || rect[1] < 2 || rect[2] > size.w - 2 || rect[3] > size.h - 2) continue;
          if (!important && taken.some((t) => overlaps(t, rect))) continue;
          placed = { side, rect };
          break;
        }
        if (!placed) { hide(); continue; }
        taken.push([placed.rect[0] - 2, placed.rect[1] - 1, placed.rect[2] + 2, placed.rect[3] + 1]);
        draw(item, placed.side, placed.rect);
        set(item.node, { visibility: 'visible' });
        shown += 1;
      }
    },
  };
}
