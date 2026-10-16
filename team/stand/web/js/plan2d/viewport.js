// Zoom and pan of the plan: k pixels per metre and the screen position (tx, ty)
// of the mine point, so that a plan point [x, z] is at (tx + k x, ty + k z).
// Wheel zooms about the pointer, drag pans, the view centre stays on the image.

import { clamp } from './svg.js';

const DRAG_START = 4;     // px of movement before a press becomes a drag
const MAX_K = 4;          // px per metre at the closest zoom (the image has 7.8 m pixels)
const EASE_MS = 420;

export function createViewport(svg, { extent, insets, onChange, onClick }) {
  let size = { w: 1, h: 1 };
  let k = 0.4;
  let tx = 0;
  let ty = 0;
  let minK = 0.05;
  let press = null;
  let anim = 0;

  const [ex0, ez0, ex1, ez1] = extent;

  function limit() {
    k = clamp(k, minK, MAX_K);
    // The centre of the view stays inside the image.
    const cx = clamp((size.w / 2 - tx) / k, ex0, ex1);
    const cz = clamp((size.h / 2 - ty) / k, ez0, ez1);
    tx = size.w / 2 - cx * k;
    ty = size.h / 2 - cz * k;
  }

  function changed() {
    limit();
    if (onChange) onChange();
  }

  function stopAnim() {
    cancelAnimationFrame(anim);
    anim = 0;
  }

  /**
   * k and centre that show a box [x0, z0, x1, z1] with a margin in px, inside
   * the part of the view that the tools and the legend leave free (insets()).
   */
  function fitOf(box, margin = 28) {
    const pad = margin === 0 ? { l: 0, r: 0, t: 0, b: 0 } : insets ? insets() : { l: 0, r: 0, t: 0, b: 0 };
    const m = margin || 0;
    const freeW = Math.max(40, size.w - pad.l - pad.r - 2 * m);
    const freeH = Math.max(40, size.h - pad.t - pad.b - 2 * m);
    const w = Math.max(10, box[2] - box[0]);
    const h = Math.max(10, box[3] - box[1]);
    const kk = clamp(Math.min(freeW / w, freeH / h), minK, MAX_K);
    // The box centre goes to the middle of the free part of the view.
    const sx = pad.l + m + freeW / 2;
    const sy = pad.t + m + freeH / 2;
    return { k: kk, cx: (box[0] + box[2]) / 2 - (sx - size.w / 2) / kk, cz: (box[1] + box[3]) / 2 - (sy - size.h / 2) / kk };
  }

  function setView(next) {
    k = next.k;
    tx = size.w / 2 - next.cx * k;
    ty = size.h / 2 - next.cz * k;
    changed();
  }

  /** Move to k and a centre, eased; instant when asked or when the motion is reduced. */
  function goTo(next, instant) {
    stopAnim();
    const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (instant || reduce) {
      setView(next);
      return;
    }
    const from = { k, cx: (size.w / 2 - tx) / k, cz: (size.h / 2 - ty) / k };
    const start = performance.now();
    const step = (now) => {
      const t = clamp((now - start) / EASE_MS, 0, 1);
      const e = t < 0.5 ? 2 * t * t : 1 - (2 - 2 * t) ** 2 / 2;
      // Zoom in log space, so that the scale changes evenly.
      const kk = Math.exp(Math.log(from.k) + (Math.log(next.k) - Math.log(from.k)) * e);
      setView({ k: kk, cx: from.cx + (next.cx - from.cx) * e, cz: from.cz + (next.cz - from.cz) * e });
      anim = t < 1 ? requestAnimationFrame(step) : 0;
    };
    anim = requestAnimationFrame(step);
  }

  function zoomAt(x, y, factor) {
    stopAnim();
    const next = clamp(k * factor, minK, MAX_K);
    if (next === k) return;
    tx = x - (x - tx) * (next / k);
    ty = y - (y - ty) * (next / k);
    k = next;
    changed();
  }

  function local(event) {
    const box = svg.getBoundingClientRect();
    return [event.clientX - box.left, event.clientY - box.top];
  }

  function onWheel(event) {
    const step = event.deltaMode === 1 ? event.deltaY * 32 : event.deltaY;
    // Zoomed out to the whole image, a scroll down is left to the page.
    if (step > 0 && k <= minK * 1.0001) return;
    event.preventDefault();
    const [x, y] = local(event);
    zoomAt(x, y, Math.exp(-clamp(step, -240, 240) * 0.0018));
  }

  function onDown(event) {
    if (event.button !== 0) return;
    stopAnim();
    press = { x: event.clientX, y: event.clientY, tx, ty, dragging: false, id: event.pointerId };
  }

  function onMove(event) {
    if (!press || event.pointerId !== press.id) return;
    const dx = event.clientX - press.x;
    const dy = event.clientY - press.y;
    if (!press.dragging) {
      if (Math.hypot(dx, dy) < DRAG_START) return;
      press.dragging = true;
      svg.classList.add('dragging');
      try {
        svg.setPointerCapture(press.id);
      } catch (error) {
        // the pointer is already gone
      }
    }
    tx = press.tx + dx;
    ty = press.ty + dy;
    changed();
  }

  function onUp(event) {
    if (!press || event.pointerId !== press.id) return;
    const wasDrag = press.dragging;
    press = null;
    svg.classList.remove('dragging');
    if (!wasDrag && event.type === 'pointerup' && onClick) onClick(event);
  }

  svg.addEventListener('wheel', onWheel, { passive: false });
  svg.addEventListener('pointerdown', onDown);
  svg.addEventListener('pointermove', onMove);
  svg.addEventListener('pointerup', onUp);
  svg.addEventListener('pointercancel', onUp);

  return {
    /** New container size; the centre and the scale are kept. */
    resize(w, h) {
      const cx = (size.w / 2 - tx) / k;
      const cz = (size.h / 2 - ty) / k;
      size = { w, h };
      // The closest the plan zooms out: the whole image in the view.
      minK = Math.min(w / (ex1 - ex0), h / (ez1 - ez0)) * 0.9;
      tx = w / 2 - cx * k;
      ty = h / 2 - cz * k;
      changed();
    },
    fit(box, instant, margin) {
      goTo(fitOf(box, margin), instant);
    },
    /** Centre on a point; zoom in to at least minScale px per metre. */
    centre(x, z, minScale, instant) {
      goTo({ k: Math.max(k, minScale || 0), cx: x, cz: z }, instant);
    },
    fitOf,
    zoomBy(factor) {
      zoomAt(size.w / 2, size.h / 2, factor);
    },
    get k() {
      return k;
    },
    get tx() {
      return tx;
    },
    get ty() {
      return ty;
    },
    get size() {
      return size;
    },
    get dragging() {
      return !!(press && press.dragging);
    },
    /** The plan box [x0, z0, x1, z1] in view. */
    visible() {
      return [-tx / k, -ty / k, (size.w - tx) / k, (size.h - ty) / k];
    },
    dispose() {
      stopAnim();
      svg.removeEventListener('wheel', onWheel);
      svg.removeEventListener('pointerdown', onDown);
      svg.removeEventListener('pointermove', onMove);
      svg.removeEventListener('pointerup', onUp);
      svg.removeEventListener('pointercancel', onUp);
    },
  };
}
