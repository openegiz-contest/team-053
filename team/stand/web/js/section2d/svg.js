// SVG helpers of the long section: element creation, path strings, text width.

let svgNamespace = null;

/** The SVG namespace, read from a parsed element so that no address is spelled in the sources. */
function namespace() {
  if (!svgNamespace) {
    const probe = document.createElement('div');
    probe.innerHTML = '<svg></svg>';
    svgNamespace = probe.firstChild.namespaceURI;
  }
  return svgNamespace;
}

export const n1 = (value) => Math.round(value * 10) / 10;

/** Set attributes; numbers are rounded to 0.1, null or false removes the attribute. */
export function set(node, attrs) {
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === undefined || value === null || value === false) {
      node.removeAttribute(key);
      continue;
    }
    const text = typeof value === 'number' ? String(n1(value)) : String(value);
    if (node.getAttribute(key) !== text) node.setAttribute(key, text);
  }
  return node;
}

/** Create an SVG element: S('g', { class: 'a' }, child, 'text'). */
export function S(tag, attrs, ...children) {
  const node = document.createElementNS(namespace(), tag);
  set(node, attrs);
  for (const child of children.flat(Infinity)) {
    if (child === undefined || child === null || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

/** Path data of a polyline through [x, y] points. */
export function pathOf(points, close = false) {
  return points.map((p, i) => (i ? 'L' : 'M') + n1(p[0]) + ' ' + n1(p[1])).join('') + (close ? 'Z' : '');
}

export function line(x1, y1, x2, y2, attrs) {
  return S('line', { x1, y1, x2, y2, ...attrs });
}

export function text(x, y, content, attrs) {
  return S('text', { x, y, ...attrs }, content);
}

/** Write text only when it changed. */
export function setText(node, content) {
  if (node && node.textContent !== content) node.textContent = content;
}

/** Text width in px for the page font, measured on a canvas (works while the view is hidden). */
export function createMeasure(fontFamily) {
  const context = document.createElement('canvas').getContext('2d');
  const cache = new Map();
  return (content, size, weight = 400) => {
    const key = weight + '|' + content;
    let unit = cache.get(key);
    if (unit === undefined) {
      if (context) {
        context.font = `${weight} 100px ${fontFamily}`;
        unit = context.measureText(content).width / 100;
      } else {
        unit = content.length * 0.58;
      }
      cache.set(key, unit);
    }
    return unit * size * 1.03;
  };
}

export const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
