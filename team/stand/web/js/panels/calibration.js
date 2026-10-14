// «Проверка калибровки»: the checks C1–C16, model against the reported value.
// Each row says whether the model was fitted to the figure («подгонка»), not fitted to it
// («независимая») or holds it by construction («тождество»), and where the figure comes from.
// The simulator rows carry the values of a headless baseline run made by the advisor.

import { DASH, clear, el, fmt, fmtTrim, isNum, setText, withUnit } from './format.js';

const GROUPS = [
  ['analytic', 'Расчётные проверки (аналитическая модель)'],
  ['simulator', 'Проверки симулятора'],
  ['out_of_sample', 'Проверки вне подгонки: отчётные цифры, по которым ничего не подбиралось'],
];
const BASIS_TONE = { fit: 'idle', independent: 'ok', identity: 'info' };

function value(v, unit) {
  if (!isNum(v)) return DASH;
  const text = unit === '%' ? fmt(v, 2) : fmtTrim(v, Math.abs(v) >= 100 ? 1 : 2);
  return withUnit(text, unit || '');
}

function reported(check) {
  if (isNum(check.reported) && isNum(check.reported_max)) {
    return withUnit(`${fmtTrim(check.reported, 1)}–${fmtTrim(check.reported_max, 1)}`, check.unit || '');
  }
  return value(check.reported, check.unit);
}

/** «investegate.co.uk/…/9542769» from the full address, for a compact link text. */
function shortUrl(url) {
  const match = String(url).match(/^https?:\/\/(?:www\.)?([^/]+)(?:\/.*\/([^/]+))?\/?$/);
  return match ? (match[2] ? `${match[1]}/…/${match[2]}` : match[1]) : url;
}

function sourceCell(check) {
  const urls = Array.isArray(check.source_urls) ? check.source_urls : [];
  return el('td', { class: 'muted', style: 'white-space: normal; min-width: 220px; font-size: 11.5px' },
    el('div', { text: check.source || DASH }),
    urls.map((url) => el('div', {}, el('a', { href: url, target: '_blank', rel: 'noopener noreferrer',
      title: url, style: 'color: inherit', text: shortUrl(url) }))),
    check.run ? el('div', { style: 'margin-top: 2px', text: check.run }) : null);
}

export function createCalibration() {
  const body = document.getElementById('cal-body');
  const meta = document.getElementById('cal-meta');
  let signature = '';

  function update(checks) {
    const next = JSON.stringify(checks || null);
    if (next === signature) return;
    signature = next;
    clear(body);
    if (!Array.isArray(checks) || !checks.length) {
      setText(meta, DASH);
      body.append(el('p', { class: 'empty', text: 'Таблица калибровки появится с отчётом советника.' }));
      return;
    }
    const kindOf = (c) => c.kind || 'analytic';
    const count = (kind) => {
      const rows = checks.filter((c) => kindOf(c) === kind);
      return [rows.filter((c) => c.passed === true).length, rows.length];
    };
    const [aPass, aAll] = count('analytic');
    const [sPass, sAll] = count('simulator');
    const [oPass, oAll] = count('out_of_sample');
    const fitted = checks.filter((c) => c.basis === 'fit').length;
    setText(meta, [`расчётных в допуске: ${fmt(aPass)} из ${fmt(aAll)}`,
      sAll ? `симулятор: ${fmt(sPass)} из ${fmt(sAll)}` : '',
      oAll ? `вне подгонки: ${fmt(oPass)} из ${fmt(oAll)}` : '',
      `строк с подгонкой: ${fmt(fitted)} из ${fmt(checks.length)}`].filter(Boolean).join(' · '));

    const rows = [];
    for (const [kind, title] of GROUPS) {
      const group = checks.filter((c) => kindOf(c) === kind);
      if (!group.length) continue;
      rows.push(el('tr', {}, el('td', { colspan: '9',
        style: 'padding-top: 10px; font-weight: 650; color: var(--text-2); background: var(--surface-2)', text: title })));
      let previous = null;
      for (const check of group) {
        const result = check.passed === true ? 'pass' : check.passed === false ? 'fail' : 'none';
        const text = result === 'pass' ? 'в допуске' : result === 'fail' ? 'вне допуска'
          : kind === 'simulator' ? 'нет значения прогона' : 'нет значения';
        const deviation = isNum(check.deviation)
          ? withUnit(fmt(check.deviation, 2, { sign: true }), check.deviation_unit || '%') : DASH;
        const first = check.id !== previous;
        previous = check.id;
        rows.push(el('tr', {},
          el('td', { class: 'mono', text: first ? (check.id || '') : '' }),
          el('td', { class: 'title', style: 'white-space: normal' }, el('div', { text: check.title || check.name || '' }),
            check.basis_note ? el('div', { class: 'muted', style: 'font-size: 11px; line-height: 1.3; margin-top: 2px',
              text: check.basis_note }) : null),
          el('td', {}, check.basis_name ? el('span', { class: 'state',
            dataset: { tone: BASIS_TONE[check.basis] || 'idle' }, text: check.basis_name }) : DASH),
          el('td', { class: 'r num', text: reported(check) }),
          el('td', { class: 'r num', text: value(check.model, check.unit) }),
          el('td', { class: 'r num dev', text: deviation }),
          el('td', { class: 'num', text: check.tolerance || DASH }),
          el('td', {}, el('span', { class: 'result', dataset: { result }, text })),
          sourceCell(check)));
      }
    }
    body.append(el('div', { class: 'scroll' }, el('table', { class: 'cal' },
      el('thead', {}, el('tr', {}, el('th', { text: '№' }), el('th', { text: 'Показатель и основа' }),
        el('th', { text: 'Основа' }),
        el('th', { class: 'r', text: 'Отчёт' }), el('th', { class: 'r', text: 'Модель' }),
        el('th', { class: 'r', text: 'Отклонение' }), el('th', { text: 'Допуск' }),
        el('th', { text: 'Результат' }), el('th', { text: 'Источник' }))),
      el('tbody', {}, rows))));
  }

  return { update };
}
