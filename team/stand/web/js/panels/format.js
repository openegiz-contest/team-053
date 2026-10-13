// Number, time and DOM helpers shared by every panel and by the views.
// Russian formatting: no-break space between thousands, comma as decimal mark,
// a real minus sign, and an em dash for a missing value.

export const DASH = '—';
const NBSP = ' ';
const MINUS = '−';

export function isNum(value) {
  return typeof value === 'number' && Number.isFinite(value);
}

/** Format a number with a fixed count of decimals; anything else gives the dash. */
export function fmt(value, digits = 0, { sign = false } = {}) {
  if (!isNum(value)) return DASH;
  const rounded = Number(value.toFixed(digits));
  const [whole, fraction] = Math.abs(rounded).toFixed(digits).split('.');
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, NBSP);
  const prefix = rounded < 0 ? MINUS : sign && rounded > 0 ? '+' : '';
  return prefix + grouped + (fraction ? ',' + fraction : '');
}

/** Decimals that suit the magnitude: 1 234, 56,7, 2,05. */
export function digitsFor(value) {
  if (!isNum(value) || Number.isInteger(value)) return 0;
  const size = Math.abs(value);
  return size >= 1000 ? 0 : size >= 100 ? 1 : size >= 1 ? 2 : 3;
}

export function fmtAuto(value) {
  return fmt(value, digitsFor(value));
}

/** At most `max` decimals, without trailing zeros: 8,5 and 0,811 and 1 726. */
export function fmtTrim(value, max = 3) {
  if (!isNum(value)) return DASH;
  let digits = 0;
  while (digits < max && Math.abs(value - Number(value.toFixed(digits))) > 1e-9) digits += 1;
  return fmt(value, digits);
}

/** Number with a unit, joined by a no-break space; the dash stands alone. */
export function withUnit(text, unit) {
  return text === DASH || !unit ? text : text + NBSP + unit;
}

const MONTHS = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа',
  'сентября', 'октября', 'ноября', 'декабря'];

/** '2027-01-13T10:24:00' -> { date: '13 января 2027 г.', time: '10:24' }. */
export function simClock(iso) {
  const match = typeof iso === 'string' && iso.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
  if (!match) return { date: DASH, time: DASH };
  const [, year, month, day, hour, minute] = match;
  return { date: `${Number(day)} ${MONTHS[Number(month) - 1]} ${year} г.`, time: `${hour}:${minute}` };
}

/** Create an element: el('div', { class: 'a', dataset: { id: 1 }, onclick }, child, 'text'). */
export function el(tag, props, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key === 'dataset') Object.assign(node.dataset, value);
    else if (key === 'text') node.textContent = value;
    else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else if (key === 'style') node.style.cssText = value;
    else node.setAttribute(key, value === true ? '' : value);
  }
  append(node, children);
  return node;
}

export function append(node, children) {
  for (const child of children.flat(Infinity)) {
    if (child === undefined || child === null || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

export function clear(node) {
  node.replaceChildren();
  return node;
}

/** Write text only when it changed, so that polling does not disturb selection or hover. */
export function setText(node, text) {
  if (node && node.textContent !== text) node.textContent = text;
}

export function setAttr(node, name, value) {
  if (node && node.getAttribute(name) !== value) node.setAttribute(name, value);
}
