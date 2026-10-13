// «Данные и допущения»: every parameter of model/params.json by group, with its
// value, unit and source. A fact and an assumption differ by tag, edge and filter.

import { unitLabel } from './dict.js';
import { DASH, clear, el, fmt, fmtTrim, isNum, setText } from './format.js';
import { GROUPS, PARAM_RU } from './params-ru.js';

function valueText(value) {
  if (value === undefined || value === null) return DASH;
  if (isNum(value)) return fmtTrim(value, 4);
  if (Array.isArray(value)) {
    const nested = value.some(Array.isArray);
    return value.map(valueText).join(nested ? ' | ' : '; ');
  }
  if (typeof value === 'object') {
    return Object.entries(value).map(([key, item]) => `${key}: ${valueText(item)}`).join('; ');
  }
  return String(value);
}

function sourceOf(entry) {
  const source = String(entry.source_ru || entry.source || '');
  if (/^FACT\b/.test(source)) return { kind: 'fact', tag: 'Факт', text: source.replace(/^FACT\s*/, '') };
  if (/^ASSUMPTION\b/.test(source)) return { kind: 'assumption', tag: 'Допущение', text: source.replace(/^ASSUMPTION:?\s*/, '') };
  return { kind: 'other', tag: 'Без пометки', text: source };
}

export function createAssumptions() {
  const body = document.getElementById('prm-body');
  const meta = document.getElementById('prm-meta');
  let rows = [];
  let groups = [];
  let filter = 'all';

  const search = el('input', { class: 'field', type: 'search', placeholder: 'Поиск по названию, идентификатору или источнику',
    'aria-label': 'Поиск по параметрам' });
  const seg = el('div', { class: 'seg', role: 'group', 'aria-label': 'Вид источника' });
  const shown = el('span', { class: 'muted' });
  const list = el('div', {});

  function apply() {
    const query = search.value.trim().toLowerCase();
    let hits = 0;
    for (const row of rows) {
      const ok = (filter === 'all' || row.kind === filter)
        && (!query || query.split(/\s+/).every((word) => row.text.includes(word)));
      row.tr.hidden = !ok;
      if (ok) hits += 1;
    }
    for (const group of groups) {
      const visible = group.rows.filter((row) => !row.tr.hidden).length;
      group.node.hidden = visible === 0;
      if (query || filter !== 'all') group.node.open = true;
    }
    setText(shown, query || filter !== 'all' ? `показано: ${fmt(hits)}` : '');
    for (const button of seg.children) button.setAttribute('aria-pressed', String(button.dataset.filter === filter));
  }

  function render(params) {
    clear(body);
    const ids = Object.keys(params || {}).filter((id) => !id.startsWith('_') && params[id] && typeof params[id] === 'object' && 'value' in params[id]);
    if (!ids.length) {
      setText(meta, DASH);
      body.append(el('p', { class: 'empty', text: 'Файл параметров не получен.' }));
      return;
    }
    const known = new Set(GROUPS.map(([prefix]) => prefix));
    const titles = new Map(GROUPS);
    const prefixes = [...GROUPS.map(([prefix]) => prefix),
      ...new Set(ids.map((id) => id.split('.')[0]).filter((prefix) => !known.has(prefix)))];
    rows = [];
    groups = [];
    let facts = 0;
    let assumptions = 0;
    clear(list);
    for (const prefix of prefixes) {
      const members = ids.filter((id) => id.split('.')[0] === prefix);
      if (!members.length) continue;
      const groupRows = members.map((id) => {
        const entry = params[id];
        const source = sourceOf(entry);
        if (source.kind === 'fact') facts += 1;
        if (source.kind === 'assumption') assumptions += 1;
        const title = entry.title_ru || entry.name_ru || PARAM_RU[id] || id;
        const tr = el('tr', { dataset: { kind: source.kind } },
          el('td', { class: 'name' }, title, el('span', { class: 'mono', text: id })),
          el('td', { class: 'val num', text: valueText(entry.value) }),
          el('td', { class: 'unit', text: unitLabel(entry.unit) }),
          el('td', { class: 'src' }, el('span', { class: 'tag', dataset: { kind: source.kind }, text: source.tag }), source.text));
        const row = { tr, kind: source.kind, text: [title, id, source.text, entry.unit].join(' ').toLowerCase() };
        rows.push(row);
        return row;
      });
      const groupFacts = groupRows.filter((row) => row.kind === 'fact').length;
      const node = el('details', { class: 'prm-group', open: true },
        el('summary', {}, titles.get(prefix) || prefix,
          el('span', { class: 'muted num', text: `параметров: ${fmt(members.length)} · фактов: ${fmt(groupFacts)} · допущений: ${fmt(members.length - groupFacts)}` })),
        el('table', { class: 'prm' }, el('tbody', {}, groupRows.map((row) => row.tr))));
      groups.push({ node, rows: groupRows });
      list.append(node);
    }
    clear(seg).append(
      el('button', { type: 'button', dataset: { filter: 'all' }, text: `Все (${fmt(ids.length)})` }),
      el('button', { type: 'button', dataset: { filter: 'fact' }, text: `Факты (${fmt(facts)})` }),
      el('button', { type: 'button', dataset: { filter: 'assumption' }, text: `Допущения (${fmt(assumptions)})` }));
    setText(meta, `параметров: ${fmt(ids.length)} · фактов из опубликованных источников: ${fmt(facts)} · допущений: ${fmt(assumptions)}`);
    body.append(el('div', { class: 'twins-bar' }, search, seg, shown), list);
    apply();
  }

  search.addEventListener('input', apply);
  seg.addEventListener('click', (event) => {
    const button = event.target.closest('button');
    if (button) { filter = button.dataset.filter; apply(); }
  });

  return { render };
}
