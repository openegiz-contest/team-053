// HTML labels over the scene (CSS2DRenderer): the short name of a twin, its
// state in Russian and one key value. At most MAX_LABELS are shown; candidates
// are ranked, projected to the screen and placed greedily so that no two
// labels overlap.

import * as THREE from 'three';
import { CSS2DObject, CSS2DRenderer } from 'three/addons/renderers/CSS2DRenderer.js';
import { el, setAttr, setText } from '../panels/format.js';

export const MAX_LABELS = 30;
const MARGIN = 3;

export function createLabels(root, scene) {
  const renderer = new CSS2DRenderer();
  renderer.domElement.className = 's3d-labels';
  root.append(renderer.domElement);

  const pool = [];             // { object, tag, label, name, line, id }
  const byThing = new Map();   // thing id -> pool entry
  const projected = new THREE.Vector3();

  // Text widths are measured with the fonts of the label style sheet (ui.js),
  // so that the placement works with the real size of a label.
  const family = getComputedStyle(root).fontFamily || 'sans-serif';
  const ruler = document.createElement('canvas').getContext('2d');
  const widths = new Map();
  function textWidth(text, font) {
    const key = font + text;
    let width = widths.get(key);
    if (width === undefined) {
      if (widths.size > 4000) widths.clear();
      ruler.font = font;
      width = ruler.measureText(text).width;
      widths.set(key, width);
    }
    return width;
  }
  const NAME_FONT = `600 10.5px ${family}`;
  const LINE_FONT = `10px ${family}`;

  function entry() {
    const name = el('b');
    const line = el('span');
    const label = el('div', { class: 's3d-label' }, name, line);
    const tag = el('div', { class: 's3d-tag' }, label);
    const object = new CSS2DObject(tag);
    object.visible = false;
    scene.add(object);
    const item = { object, tag, label, name, line, id: null };
    pool.push(item);
    return item;
  }

  /**
   * Decide which labels are shown. `candidates`: [{ id, position (Vector3),
   * score, name, line, tone, title, align, selected }], any order.
   * `reserved`: screen rectangles [x, y, w, h] that must stay free.
   */
  function layout(candidates, camera, width, height, reserved) {
    const placed = reserved.map((r) => r.slice());
    const chosen = [];
    const sorted = candidates.slice().sort((a, b) => b.score - a.score);
    for (const c of sorted) {
      if (chosen.length >= MAX_LABELS) break;
      projected.copy(c.position).project(camera);
      if (projected.z < -1 || projected.z > 1) continue;
      const sx = (projected.x * 0.5 + 0.5) * width;
      const sy = (-projected.y * 0.5 + 0.5) * height;
      if (sx < 4 || sx > width - 4 || sy < 4 || sy > height - 4) continue;
      const w = 19 + Math.max(textWidth(c.name, NAME_FONT), textWidth(c.line, LINE_FONT));
      const h = 30;
      const rect = c.align === 'right' ? [sx + 12, sy - h / 2, w, h] : [sx - w / 2, sy - h - 9, w, h];
      if (!c.selected) {
        if (rect[0] < 2 || rect[1] < 2 || rect[0] + w > width - 2 || rect[1] + h > height - 2) continue;
        let free = true;
        for (const p of placed) {
          if (rect[0] < p[0] + p[2] + MARGIN && rect[0] + w + MARGIN > p[0]
            && rect[1] < p[1] + p[3] + MARGIN && rect[1] + h + MARGIN > p[1]) {
            free = false;
            break;
          }
        }
        if (!free) continue;
      }
      placed.push(rect);
      chosen.push(c);
    }

    const keep = new Set(chosen.map((c) => c.id));
    const spare = [];
    for (const item of pool) {
      if (item.id !== null && !keep.has(item.id)) {
        byThing.delete(item.id);
        item.id = null;
        item.object.visible = false;
      }
      if (item.id === null) spare.push(item);
    }
    for (const c of chosen) {
      let item = byThing.get(c.id);
      if (!item) {
        item = spare.pop() || entry();
        item.id = c.id;
        byThing.set(c.id, item);
        setAttr(item.label, 'data-thing', c.id);
      }
      setText(item.name, c.name);
      setText(item.line, c.line);
      setAttr(item.label, 'data-tone', c.tone);
      setAttr(item.label, 'data-selected', c.selected ? '1' : '0');
      setAttr(item.label, 'title', c.title);
      setAttr(item.tag, 'data-align', c.align === 'right' ? 'right' : 'above');
      if (c.align === 'right') item.object.center.set(0, 0.5);
      else item.object.center.set(0.5, 1);
      item.object.position.copy(c.position);
      item.object.visible = true;
    }
    return chosen.length;
  }

  return {
    layout,
    isShown: (id) => byThing.has(id),
    /** Move the label of a thing that travels (called every frame for vehicles). */
    move(id, position) {
      const item = byThing.get(id);
      if (item) item.object.position.copy(position);
    },
    setSize: (width, height) => renderer.setSize(width, height),
    render: (camera) => renderer.render(scene, camera),
    count: () => byThing.size,
    dispose() {
      for (const item of pool) scene.remove(item.object);
      renderer.domElement.remove();
    },
  };
}
