// «Двойники»: a searchable tree table of every twin by hierarchy, and the twin
// card with all features, attributes, links and the Ditto thing id.

import {
  KEY_FEATURES, LINK_ATTR_RU, NS, attrLabel, attrText, featureLabel, featureText, kindLabel,
  thingState,
} from './dict.js';
import { DASH, clear, el, fmt, setText } from './format.js';

const HIDDEN_ATTRS = new Set(['name', 'units', '_parents', 'kind']);

export function createTwins({ onSelect }) {
  const body = document.getElementById('twins-body');
  const meta = document.getElementById('twins-meta');
  const card = document.getElementById('twin-card');

  const search = el('input', { class: 'field', type: 'search', placeholder: 'Поиск: название, тип, состояние или идентификатор',
    'aria-label': 'Поиск по двойникам' });
  const kindFilter = el('select', { class: 'field', 'aria-label': 'Тип двойника' }, el('option', { value: '', text: 'Все типы' }));
  const expandAll = el('button', { type: 'button', class: 'btn', text: 'Развернуть всё' });
  const collapseAll = el('button', { type: 'button', class: 'btn', text: 'Свернуть до участков' });
  const shown = el('span', { class: 'muted' });
  const tbody = el('tbody', {});
  const wrap = el('div', { class: 'twins-wrap scroll' }, el('table', { class: 'twins-table' },
    el('thead', {}, el('tr', {}, el('th', { text: 'Двойник' }), el('th', { text: 'Тип' }),
      el('th', { text: 'Состояние' }), el('th', { text: 'Ключевые показатели' }),
      el('th', { text: 'Идентификатор в Ditto' }))), tbody));
  body.append(el('div', { class: 'twins-bar' }, search, kindFilter, expandAll, collapseAll, shown), wrap);

  let things = {};
  let order = [];              // thing ids in tree order
  let children = {};           // id -> child ids
  let depth = {};
  const rows = {};             // id -> row nodes
  const collapsed = new Set();
  let structure = '';
  let selected = null;

  function buildTree() {
    children = {};
    const ids = Object.keys(things);
    for (const id of ids) {
      const parent = things[id].parent && things[things[id].parent] ? things[id].parent : null;
      (children[parent || ''] = children[parent || ''] || []).push(id);
    }
    order = [];
    depth = {};
    const walk = (id, level) => {
      order.push(id);
      depth[id] = level;
      for (const child of children[id] || []) walk(child, level + 1);
    };
    for (const root of children[''] || []) walk(root, 0);
  }

  function buildRows() {
    clear(tbody);
    for (const key of Object.keys(rows)) delete rows[key];
    const kinds = new Set();
    for (const id of order) {
      const thing = things[id];
      kinds.add(thing.kind);
      const kids = children[id] || [];
      const toggle = kids.length
        ? el('button', { type: 'button', class: 'tw-toggle', 'aria-expanded': 'true', 'aria-label': 'Свернуть или развернуть', dataset: { toggle: id } })
        : el('span', { class: 'tw-leaf' });
      const name = el('span', { text: thing.name || id });
      const state = el('span', { class: 'state' });
      const values = el('td', {});
      const tr = el('tr', { dataset: { id }, tabindex: '0' },
        el('td', {}, el('div', { class: 'tw-name', style: `--depth: ${depth[id]}` }, toggle, name,
          kids.length ? el('span', { class: 'tw-count num', text: String(kids.length) }) : null)),
        el('td', { class: 'kind', text: kindLabel(thing.kind) }),
        el('td', {}, state), values, el('td', { class: 'id mono', text: id }));
      rows[id] = { tr, toggle, name, state, values, valueNodes: {} };
      tbody.append(tr);
    }
    const current = kindFilter.value;
    clear(kindFilter).append(el('option', { value: '', text: 'Все типы' }),
      [...kinds].sort((a, b) => kindLabel(a).localeCompare(kindLabel(b), 'ru'))
        .map((kind) => el('option', { value: kind, text: kindLabel(kind) })));
    kindFilter.value = current;
  }

  function updateRows() {
    for (const id of order) {
      const thing = things[id];
      const row = rows[id];
      const state = thingState(thing);
      setText(row.state, state.label);
      row.state.dataset.tone = state.tone;
      const units = (thing.attrs && thing.attrs.units) || {};
      for (const key of KEY_FEATURES[thing.kind] || []) {
        if (!row.valueNodes[key]) {
          const value = el('span', { class: 'v num' });
          row.values.append(el('span', { class: 'kv' }, el('span', { class: 'k', text: featureLabel(key) }), value));
          row.valueNodes[key] = value;
        }
        setText(row.valueNodes[key], featureText(key, thing.f ? thing.f[key] : undefined,
          { kind: thing.kind, unit: units[key], things }));
      }
    }
  }

  function matches(id, query, kind) {
    const thing = things[id];
    if (kind && thing.kind !== kind) return false;
    if (!query) return true;
    const text = [thing.name, id, thing.kind, kindLabel(thing.kind), thingState(thing).label,
      thing.f && thing.f.state].join(' ').toLowerCase();
    return query.split(/\s+/).every((word) => text.includes(word));
  }

  function applyFilter() {
    const query = search.value.trim().toLowerCase();
    const kind = kindFilter.value;
    const filtering = Boolean(query || kind);
    const visible = new Set();
    if (filtering) {
      for (const id of order) {
        if (!matches(id, query, kind)) continue;
        for (let at = id; at; at = things[at] && things[at].parent) visible.add(at);  // keep the path
      }
    }
    let hits = 0;
    for (const id of order) {
      let show;
      if (filtering) {
        show = visible.has(id);
        if (show && matches(id, query, kind)) hits += 1;
      } else {
        show = true;
        for (let at = things[id].parent; at && things[at]; at = things[at].parent) {
          if (collapsed.has(at)) { show = false; break; }
        }
      }
      rows[id].tr.hidden = !show;
      if (rows[id].toggle.dataset.toggle) {
        rows[id].toggle.setAttribute('aria-expanded', String(filtering || !collapsed.has(id)));
      }
    }
    setText(shown, filtering ? `найдено: ${fmt(hits)}` : '');
  }

  function select(id, { scroll = false } = {}) {
    if (selected && rows[selected]) rows[selected].tr.classList.remove('is-selected');
    selected = id && things[id] ? id : null;
    if (selected) {
      const row = rows[selected].tr;
      for (let at = things[selected].parent; at && things[at]; at = things[at].parent) collapsed.delete(at);
      applyFilter();
      row.classList.add('is-selected');
      if (scroll && !row.hidden) {  // scroll inside the table only, never the page
        const top = row.offsetTop - wrap.clientHeight / 2 + row.offsetHeight / 2;
        wrap.scrollTop = Math.max(0, top);
      }
    }
    renderCard();
  }

  // ------------------------------------------------------------------ the card

  let cardNodes = null;

  function chip(id) {
    const thing = things[id];
    return el('button', { type: 'button', class: 'chip', title: id, dataset: { open: id },
      text: thing && thing.name ? thing.name : id });
  }

  function renderCard() {
    if (!selected || !things[selected]) {
      card.hidden = true;
      cardNodes = null;
      return;
    }
    const thing = things[selected];
    const attrs = thing.attrs || {};
    const units = attrs.units || {};
    const state = el('span', { class: 'state' });
    const featureCells = {};
    const featureRows = Object.keys(thing.f || {}).map((key) => {
      const value = el('td', { class: 'num' });
      featureCells[key] = value;
      return el('tr', {}, el('td', {}, featureLabel(key), el('span', { class: 'mono', text: key })), value);
    });
    const plain = Object.keys(attrs).filter((key) => !HIDDEN_ATTRS.has(key) && !key.startsWith('link_') && key !== 'type' && key !== '_isType');
    const links = Object.keys(attrs).filter((key) => key.startsWith('link_'));
    const kids = Object.keys(things).filter((id) => things[id].parent === selected);

    clear(card).append(
      el('div', { class: 'tc-head' },
        el('div', {}, el('h2', { text: thing.name || selected }), el('div', { class: 'kind', text: kindLabel(thing.kind) })),
        el('button', { type: 'button', class: 'btn tc-close', 'aria-label': 'Закрыть карточку', text: '×', dataset: { close: '1' } })),
      el('div', { class: 'tc-id' }, el('span', { class: 'mono', text: selected, title: 'Идентификатор двойника в Eclipse Ditto' }), state),
      el('div', { class: 'tc-body scroll' },
        el('h3', { class: 'group', text: 'Иерархия' }),
        el('table', { class: 'tc-table' }, el('tbody', {},
          el('tr', {}, el('td', { text: 'Родитель' }), el('td', {}, thing.parent ? el('div', { class: 'chips' }, chip(thing.parent)) : DASH)),
          kids.length ? el('tr', {}, el('td', { text: `Дочерние двойники (${kids.length})` }),
            el('td', {}, el('div', { class: 'chips' }, kids.map(chip)))) : null,
          el('tr', {}, el('td', { text: 'Тип-двойник' }), el('td', { class: 'mono', text: attrs.type || DASH })))),
        el('h3', { class: 'group', text: `Признаки (${featureRows.length})` }),
        el('table', { class: 'tc-table' }, el('tbody', {}, featureRows)),
        links.length ? [el('h3', { class: 'group', text: 'Связи' }),
          el('table', { class: 'tc-table' }, el('tbody', {}, links.map((key) => el('tr', {},
            el('td', {}, LINK_ATTR_RU[key] || key, el('span', { class: 'mono', text: key })),
            el('td', {}, el('div', { class: 'chips' }, [].concat(attrs[key]).map(chip)))))))] : null,
        plain.length ? [el('h3', { class: 'group', text: 'Атрибуты' }),
          el('table', { class: 'tc-table' }, el('tbody', {}, plain.map((key) => el('tr', {},
            el('td', {}, attrLabel(key), el('span', { class: 'mono', text: key })),
            el('td', { class: 'num', text: attrText(key, attrs[key]) })))))] : null));
    card.hidden = false;
    cardNodes = { id: selected, state, featureCells, units };
    updateCard();
  }

  function updateCard() {
    if (!cardNodes || !things[cardNodes.id]) return;
    const thing = things[cardNodes.id];
    const state = thingState(thing);
    setText(cardNodes.state, state.label);
    cardNodes.state.dataset.tone = state.tone;
    for (const [key, cell] of Object.entries(cardNodes.featureCells)) {
      setText(cell, featureText(key, thing.f ? thing.f[key] : undefined,
        { kind: thing.kind, unit: cardNodes.units[key], things }));
    }
  }

  // -------------------------------------------------------------------- events

  tbody.addEventListener('click', (event) => {
    const toggle = event.target.closest('[data-toggle]');
    if (toggle) {
      const id = toggle.dataset.toggle;
      if (collapsed.has(id)) collapsed.delete(id); else collapsed.add(id);
      applyFilter();
      return;
    }
    const row = event.target.closest('tr[data-id]');
    if (row) onSelect(row.dataset.id);
  });
  tbody.addEventListener('keydown', (event) => {
    const row = event.target.closest('tr[data-id]');
    if (row && event.target === row && (event.key === 'Enter' || event.key === ' ')) {
      event.preventDefault();
      onSelect(row.dataset.id);
    }
  });
  card.addEventListener('click', (event) => {
    if (event.target.closest('[data-close]')) return onSelect(null);
    const open = event.target.closest('[data-open]');
    if (open) onSelect(open.dataset.open);
    return undefined;
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && selected) onSelect(null);
  });
  search.addEventListener('input', applyFilter);
  kindFilter.addEventListener('change', applyFilter);
  expandAll.addEventListener('click', () => { collapsed.clear(); applyFilter(); });
  collapseAll.addEventListener('click', () => {
    collapsed.clear();
    for (const id of order) if (depth[id] >= 1 && (children[id] || []).length) collapsed.add(id);
    applyFilter();
  });

  function update(state) {
    things = (state && state.things) || {};
    const next = Object.keys(things).map((id) => `${id}<${things[id].parent || ''}`).join('|');
    if (next !== structure) {
      structure = next;
      buildTree();
      buildRows();
      if (selected && !things[selected]) selected = null;
      if (selected) rows[selected].tr.classList.add('is-selected');
    }
    updateRows();
    applyFilter();
    updateCard();
    const count = Object.keys(things).length;
    const kinds = new Set(Object.values(things).map((thing) => thing.kind)).size;
    setText(meta, count ? `${fmt(count)} двойников · ${fmt(kinds)} типа · пространство имён ${NS.slice(0, -1)}` : DASH);
  }

  return { update, select, selected: () => selected };
}
