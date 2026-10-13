// Zoom and pan of the sheet: wheel zooms about the pointer, drag pans, the
// sheet never leaves the view. Coordinates of the sheet are pixels at zoom 1.

import { clamp } from './svg.js';

const MAX_ZOOM = 8;
const DRAG_START = 4;   // px of movement before a press becomes a drag

export function createViewport(svg, sheet, { onMove, onClick }) {
  let size = { w: 1, h: 1 };       // the container
  let page = { w: 1, h: 1 };       // the sheet at zoom 1
  let fit = 1;
  let k = 1;
  let tx = 0;
  let ty = 0;
  let press = null;

  function apply() {
    const sw = page.w * k;
    const sh = page.h * k;
    tx = sw <= size.w ? (size.w - sw) / 2 : clamp(tx, size.w - sw, 0);
    ty = sh <= size.h ? (size.h - sh) / 2 : clamp(ty, size.h - sh, 0);
    sheet.setAttribute('transform', `translate(${tx.toFixed(1)} ${ty.toFixed(1)}) scale(${k.toFixed(4)})`);
    svg.dataset.zoom = (k / fit).toFixed(2);
    if (onMove) onMove();
  }

  function zoomAt(x, y, factor) {
    const next = clamp(k * factor, fit, fit * MAX_ZOOM);
    if (next === k) return false;
    tx = x - (x - tx) * (next / k);
    ty = y - (y - ty) * (next / k);
    k = next;
    apply();
    return true;
  }

  function local(event) {
    const box = svg.getBoundingClientRect();
    return [event.clientX - box.left, event.clientY - box.top];
  }

  function onWheel(event) {
    const [x, y] = local(event);
    const step = event.deltaMode === 1 ? event.deltaY * 32 : event.deltaY;
    // At the full view a scroll down is left to the page.
    if (step > 0 && k <= fit * 1.0001) return;
    event.preventDefault();
    zoomAt(x, y, Math.exp(-step * 0.0016));
  }

  function onDown(event) {
    if (event.button !== 0) return;
    press = { x: event.clientX, y: event.clientY, tx, ty, dragging: false, id: event.pointerId };
  }

  function onMovePointer(event) {
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
    apply();
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
  svg.addEventListener('pointermove', onMovePointer);
  svg.addEventListener('pointerup', onUp);
  svg.addEventListener('pointercancel', onUp);

  return {
    /** New container or sheet size; the relative view is kept when only the size changed. */
    setSheet(containerW, containerH, sheetW, sheetH, fitZoom) {
      const zoom = k / fit;
      const centre = [(size.w / 2 - tx) / (page.w * k), (size.h / 2 - ty) / (page.h * k)];
      const keep = zoom > 1.001;
      size = { w: containerW, h: containerH };
      page = { w: sheetW, h: sheetH };
      fit = fitZoom;
      k = keep ? fit * zoom : fit;
      tx = keep ? size.w / 2 - centre[0] * page.w * k : 0;
      ty = keep ? size.h / 2 - centre[1] * page.h * k : 0;
      apply();
    },
    reset() {
      k = fit;
      tx = 0;
      ty = 0;
      apply();
    },
    zoomBy(factor) {
      zoomAt(size.w / 2, size.h / 2, factor);
    },
    /** Bring a sheet point into view; pans only when it is outside the middle of the view. */
    reveal(x, y) {
      const sx = tx + x * k;
      const sy = ty + y * k;
      const mx = Math.min(80, size.w * 0.15);
      const my = Math.min(60, size.h * 0.15);
      if (sx >= mx && sx <= size.w - mx && sy >= my && sy <= size.h - my) return;
      tx = size.w / 2 - x * k;
      ty = size.h / 2 - y * k;
      apply();
    },
    get dragging() {
      return !!(press && press.dragging);
    },
    get zoom() {
      return k / fit;
    },
    dispose() {
      svg.removeEventListener('wheel', onWheel);
      svg.removeEventListener('pointerdown', onDown);
      svg.removeEventListener('pointermove', onMovePointer);
      svg.removeEventListener('pointerup', onUp);
      svg.removeEventListener('pointercancel', onUp);
    },
  };
}
