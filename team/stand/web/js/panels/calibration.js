// «Проверка калибровки»: the checks C1–C12, model against the reported value.

import { DASH, clear, el, fmt, fmtTrim, isNum, setText, withUnit } from './format.js';

function value(v, unit) {
  if (!isNum(v)) return DASH;
  const text = unit === '%' ? fmt(v, 2) : fmtTrim(v, Math.abs(v) >= 100 ? 1 : 2);
  return withUnit(text, unit || '');
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
    const analytic = checks.filter((c) => (c.kind || 'analytic') === 'analytic');
    const passed = analytic.filter((c) => c.passed === true).length;
    const pending = checks.filter((c) => c.passed !== true && c.passed !== false).length;
    setText(meta, `расчётных проверок в допуске: ${fmt(passed)} из ${fmt(analytic.length)}`
      + (pending ? ` · по прогону симулятора: ${fmt(pending)}` : ''));

    let previous = null;
    const rows = checks.map((check) => {
      const result = check.passed === true ? 'pass' : check.passed === false ? 'fail' : 'none';
      const text = result === 'pass' ? 'в допуске' : result === 'fail' ? 'вне допуска'
        : check.kind === 'simulator' ? 'считается прогоном симулятора' : 'нет значения';
      const deviation = isNum(check.deviation)
        ? withUnit(fmt(check.deviation, 2, { sign: true }), check.deviation_unit || '%') : DASH;
      const first = check.id !== previous;
      previous = check.id;
      return el('tr', {},
        el('td', { class: 'mono', text: first ? (check.id || '') : '' }),
        el('td', { class: 'title', text: check.title || check.name || '' }),
        el('td', { class: 'r num', text: value(check.reported, check.unit) }),
        el('td', { class: 'r num', text: value(check.model, check.unit) }),
        el('td', { class: 'r num dev', text: deviation }),
        el('td', { class: 'num', text: check.tolerance || DASH }),
        el('td', {}, el('span', { class: 'result', dataset: { result }, text })),
        el('td', { class: 'muted', text: check.source || '' }));
    });
    body.append(el('div', { class: 'scroll' }, el('table', { class: 'cal' },
      el('thead', {}, el('tr', {}, el('th', { text: '№' }), el('th', { text: 'Показатель' }),
        el('th', { class: 'r', text: 'Отчёт' }), el('th', { class: 'r', text: 'Модель' }),
        el('th', { class: 'r', text: 'Отклонение' }), el('th', { text: 'Допуск' }),
        el('th', { text: 'Результат' }), el('th', { text: 'Источник' }))),
      el('tbody', {}, rows))));
  }

  return { update };
}
