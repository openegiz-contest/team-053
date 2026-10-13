// «Советник по расширению»: capacity bars against the target, the next measure,
// KPIs, the ladder for the four targets and the ten-year projection.
//
// normalize() accepts the advisor report of GET /api/advisor and falls back to
// the features of the twin kz.sekis:advisor, so the bars work from the twin alone.

import { LINKS, MEASURES, NS, linkLabel } from './dict.js';
import { DASH, clear, el, fmt, isNum, setText, withUnit } from './format.js';

const KT = 'тыс. т/год';
const num = (value) => (isNum(value) ? value : null);
const pick = (object, ...keys) => {
  for (const key of keys) {
    if (object && object[key] !== undefined && object[key] !== null) return object[key];
  }
  return null;
};

function normalizeStep(step) {
  if (!step) return null;
  if (typeof step === 'string') {
    const measure = MEASURES.find((m) => m.knob === step);
    if (step === 'none' || step === '') return null;
    return {
      link: measure ? measure.link : step === 'restore_pumps' ? 'dewatering' : null,
      text: measure ? 'следующая ступень' : step === 'restore_pumps' ? 'восстановить насосы гор. +150 м' : step,
      capBefore: null, capAfter: null,
    };
  }
  return {
    link: pick(step, 'link', 'binding_link'),
    text: pick(step, 'text', 'measure', 'name') || '',
    capBefore: num(pick(step, 'cap_before_ktpa', 'cap_before', 'capacity_before')),
    capAfter: num(pick(step, 'cap_after_ktpa', 'cap_after', 'capacity_after')),
  };
}

function normalizeLinks(report, twin) {
  const fromReport = {};
  const list = report && (report.links || report.capacities);
  if (Array.isArray(list)) {
    for (const row of list) if (row && row.id) fromReport[row.id] = row;
  } else if (list && typeof list === 'object') {
    for (const [id, value] of Object.entries(list)) {
      fromReport[id] = typeof value === 'object' ? value : { cap_ktpa: value };
    }
  }
  const binding = pick(report, 'binding_link') || twin.binding_link || null;
  return LINKS.map((id) => {
    const row = fromReport[id] || {};
    const cap = num(pick(row, 'cap_ktpa', 'cap', 'capacity_ktpa', 'value')) ?? num(twin[`cap_${id}_ktpa`]);
    // Dewatering is reported as 0 while it does not limit the mine (spec 3.4).
    const limiting = row.limiting !== undefined ? Boolean(row.limiting)
      : !(id === 'dewatering' && (!cap || cap <= 0));
    return { id, name: linkLabel(id), cap, limiting, binding: id === binding, detail: row.detail || '' };
  });
}

export function normalize(report, state) {
  const things = (state && state.things) || {};
  const twin = (things[NS + 'advisor'] && things[NS + 'advisor'].f) || {};
  const mine = (things[NS + 'mine'] && things[NS + 'mine'].f) || {};
  const outfall = (things[NS + 'mon-volchevka'] && things[NS + 'mon-volchevka'].attrs) || {};
  const r = report && typeof report === 'object' ? report : null;
  const kpi = (r && r.kpi) || {};
  const links = normalizeLinks(r, twin);
  const target = num(pick(r, 'target_ktpa')) ?? num(twin.target_ktpa);
  const achievable = num(pick(r, 'achievable_ktpa')) ?? num(twin.achievable_ktpa);
  const ladderRaw = r && r.ladder ? (Array.isArray(r.ladder) ? r.ladder : Object.values(r.ladder)) : [];
  const projectionRaw = r && r.projection
    ? (Array.isArray(r.projection) ? { rows: r.projection } : r.projection) : null;
  const effectsRaw = r && r.effects ? (Array.isArray(r.effects) ? { items: r.effects } : r.effects) : null;
  const k = (key, twinKey) => num(kpi[key]) ?? num(twin[twinKey || key]);

  return {
    hasReport: Boolean(r),
    hasData: links.some((link) => link.cap !== null),
    revision: num(pick(r, 'report_revision')) ?? num(twin.report_revision),
    target,
    achievable,
    binding: (links.find((link) => link.binding) || {}).id || null,
    links,
    next: normalizeStep(r && r.next_measure !== undefined ? r.next_measure : twin.next_measure),
    measuresNeeded: num(pick(r, 'measures_needed')) ?? num(twin.measures_needed),
    kpi: {
      gold: k('gold_koz_year'), goldGain: k('gold_gain_koz_year'),
      airDemand: k('air_demand_m3s') ?? num(mine.air_demand_m3s),
      airSupply: num(kpi.air_supply_m3s) ?? num(mine.air_supply_m3s),
      deficit: k('water_deficit_m3h'), discharge: k('discharge_m3h'),
      permit: num(kpi.permit_m3h) ?? num(outfall.permit_m3h),
      tailingsYears: k('tailings_years_left'),
      // A report says null when the stockpile grows; the twin can only say 0.
      stockpileDays: r && r.kpi ? num(kpi.stockpile_days_left) : (twin.stockpile_days_left || null),
      margin: k('dewatering_margin'),
    },
    baseline: (r && r.sustainable_baseline) || null,
    ladder: ladderRaw.filter(Boolean).map((row) => ({
      target: num(row.target_ktpa), achievable: num(row.achievable_ktpa),
      binding: row.binding_link || null,
      reached: row.reached !== undefined ? Boolean(row.reached)
        : isNum(row.achievable_ktpa) && isNum(row.target_ktpa) && row.achievable_ktpa >= row.target_ktpa,
      gold: num(row.gold_koz_year), goldGain: num(row.gold_gain_koz_year),
      airDemand: num(row.air_demand_m3s), deficit: num(row.water_deficit_m3h),
      discharge: num(row.discharge_m3h), tailingsYears: num(row.tailings_years_left),
      steps: (row.steps || row.sequence || []).map(normalizeStep).filter(Boolean),
    })),
    projection: projectionRaw ? {
      rows: (projectionRaw.rows || []).map((row) => ({
        year: row.year, achievable: num(row.achievable_ktpa), binding: row.binding_link || null,
        gold: num(pick(row, 'gold_koz', 'gold_koz_year')),
        stored: num(row.tailings_stored_kt), free: num(row.tailings_free_kt),
        deficit: num(row.water_deficit_m3h),
      })),
      runsOut: projectionRaw.storage_runs_out_year ?? null,
      missed: projectionRaw.target_missed_year ?? null,
    } : null,
    effects: effectsRaw ? {
      label: effectsRaw.label || '', revision: num(effectsRaw.revision),
      items: (effectsRaw.items || []).map((item) => (typeof item === 'string'
        ? { text: item, trend: 'neutral' }
        : { text: item.text || '', trend: item.trend || 'neutral' })).filter((item) => item.text),
    } : null,
    calibration: r && Array.isArray(r.calibration) ? r.calibration : null,
  };
}

// ---------------------------------------------------------------- side panel

export function createAdvisor() {
  const body = document.getElementById('adv-body');
  const meta = document.getElementById('adv-meta');
  let built = null;

  function build() {
    const rows = {};
    const axisLabel = el('span', {});
    const axis = el('div', { class: 'cap-axis' }, el('span', {}),
      el('div', { class: 'scale' }, axisLabel), el('span', { class: 'unit', text: 'тыс. т/год' }));
    const caps = el('div', { class: 'caps', role: 'table', 'aria-label': 'Пропускная способность звеньев, тыс. т/год' });
    for (const id of LINKS) {
      const fill = el('div', { class: 'cap-fill' });
      const note = el('span', { class: 'cap-note' });
      const value = el('span', { class: 'cap-value num', role: 'cell' });
      const row = el('div', { class: 'cap-row', role: 'row', dataset: { link: id } },
        el('span', { class: 'cap-name', role: 'cell', text: linkLabel(id) }),
        el('div', { class: 'cap-track', role: 'cell' }, fill, note), value);
      rows[id] = { row, fill, note, value };
      caps.append(row);
    }
    const summary = el('div', { class: 'adv-summary' });
    const legend = el('div', { class: 'cap-legend' },
      el('span', {}, el('i', { class: 'lg-bind' }), 'узкое место'),
      el('span', {}, el('i', { class: 'lg-target' }), 'цель'),
      el('span', {}, el('i', { class: 'lg-bar' }), 'пропускная способность звена'));
    const next = el('div', { class: 'next' });
    const kpis = el('div', { class: 'kpis' });
    clear(body).append(summary, axis, caps, legend, next, kpis);
    return { rows, axis, axisLabel, caps, summary, next, kpis };
  }

  function kpiTile(label, value, unit, detail, tone) {
    return el('div', { class: 'kpi', dataset: tone ? { tone } : {} },
      el('div', { class: 'k', text: label }),
      el('div', { class: 'v num' }, value, unit && value !== DASH ? el('small', {}, ' ' + unit) : null),
      el('div', { class: 'd', text: detail || '' }));
  }

  function update(model) {
    if (!model || !model.hasData) {
      built = null;
      clear(body).append(el('p', { class: 'empty', text: 'Отчёт советника пока не получен.' }));
      setText(meta, DASH);
      return;
    }
    built = built || build();
    const { target, achievable } = model;
    setText(meta, isNum(model.revision) ? `отчёт для ревизии ${fmt(model.revision)}` : DASH);

    const reached = isNum(target) && isNum(achievable) && achievable >= target;
    clear(built.summary).append(
      el('div', {}, el('span', { class: 'k', text: 'Цель' }),
        el('span', { class: 'v num' }, fmt(target), el('small', {}, ' ' + KT))),
      el('div', {}, el('span', { class: 'k', text: 'Достижимо' }),
        el('span', { class: 'v num' }, fmt(achievable), el('small', {}, ' ' + KT))),
      el('span', { class: 'state', dataset: { tone: reached ? 'ok' : 'accent' },
        text: reached ? 'цель достигается' : 'ниже цели' }));

    // One scale for the eight bars; a bar longer than the scale is cut and marked.
    const caps = model.links.filter((link) => link.limiting && isNum(link.cap)).map((link) => link.cap);
    const top = Math.max(...caps, target || 0, 1);
    const scale = Math.min(top, Math.max((target || top) * 2.2, Math.min(...caps, top) * 1.3)) * 1.04;
    const targetPos = isNum(target) ? Math.min(100, (target / scale) * 100) : null;
    built.caps.style.setProperty('--target', targetPos === null ? '-10%' : targetPos + '%');
    built.axis.style.setProperty('--target', targetPos === null ? '-10%' : targetPos + '%');
    setText(built.axisLabel, isNum(target) ? `цель ${fmt(target)}` : '');

    for (const link of model.links) {
      const { row, fill, note, value } = built.rows[link.id];
      const over = link.limiting && isNum(link.cap) && link.cap > scale;
      row.classList.toggle('is-binding', link.binding);
      row.classList.toggle('is-off', !link.limiting);
      fill.classList.toggle('is-over', over);
      fill.style.width = link.limiting && isNum(link.cap) ? Math.min(100, (link.cap / scale) * 100) + '%' : '0%';
      setText(value, link.limiting ? fmt(link.cap) : DASH);
      setText(note, link.limiting ? '' : isNum(model.kpi.margin)
        ? `не ограничивает, запас насосов ×${fmt(model.kpi.margin, 2)}` : 'не ограничивает');
      const hint = [link.name, link.limiting ? withUnit(fmt(link.cap), KT) : 'не ограничивает',
        link.binding ? 'узкое место' : '', link.detail].filter(Boolean).join(' · ');
      row.title = hint;
    }

    const next = model.next;
    built.next.classList.toggle('is-done', !next);
    clear(built.next);
    if (next) {
      const gain = isNum(next.capBefore) && isNum(next.capAfter)
        ? `${fmt(next.capBefore)} → ${withUnit(fmt(next.capAfter), KT)}` : '';
      const left = isNum(model.measuresNeeded) ? `мер до цели: ${fmt(model.measuresNeeded)}` : '';
      built.next.append(
        el('div', { class: 'k', text: 'Следующая мера' }),
        el('div', { class: 'v', text: `${linkLabel(next.link)}: ${next.text}` }),
        el('div', { class: 'd num', text: [gain, left].filter(Boolean).join(' · ') }));
    } else {
      built.next.append(
        el('div', { class: 'k', text: 'Следующая мера' }),
        el('div', { class: 'v', text: reached ? 'Не требуется: все звенья не ниже цели'
          : 'Ступени мер на узком месте исчерпаны' }),
        el('div', { class: 'd num', text: withUnit(`достижимо ${fmt(achievable)}`, KT) }));
    }

    const kpi = model.kpi;
    const airShort = isNum(kpi.airDemand) && isNum(kpi.airSupply) && kpi.airDemand > kpi.airSupply;
    const overPermit = isNum(kpi.discharge) && isNum(kpi.permit) && kpi.discharge > kpi.permit;
    const base = model.baseline && isNum(model.baseline.gold_koz_year)
      ? ` к базе ${fmt(model.baseline.gold_koz_year, 1)}` : ' к базе';
    clear(built.kpis).append(
      kpiTile('Золото', fmt(kpi.gold, 1), 'тыс. унц./год',
        isNum(kpi.goldGain) ? `${fmt(kpi.goldGain, 1, { sign: true })}${base}` : ''),
      kpiTile('Воздух', `${fmt(kpi.airDemand, 0)} / ${fmt(kpi.airSupply, 0)}`, 'м³/с',
        'спрос / подача', airShort ? 'warn' : null),
      kpiTile('Хвосты', fmt(kpi.tailingsYears, 1), 'лет', 'до заполнения',
        isNum(kpi.tailingsYears) && kpi.tailingsYears < 3 ? 'warn' : null),
      kpiTile('Дефицит воды', fmt(kpi.deficit, 1), 'м³/ч',
        !isNum(kpi.deficit) ? '' : kpi.deficit > 0.05 ? 'фабрике не хватает' : 'воды хватает',
        isNum(kpi.deficit) && kpi.deficit > 0.05 ? 'warn' : null),
      kpiTile('Сброс в Волчевку', fmt(kpi.discharge, 1), 'м³/ч',
        isNum(kpi.permit) ? `разрешено ${fmt(kpi.permit, 1)}` : '', overPermit ? 'fail' : null),
      kpiTile('Рудный склад', isNum(kpi.stockpileDays) ? fmt(kpi.stockpileDays) : DASH, 'сут',
        isNum(kpi.stockpileDays) ? 'до исчерпания' : 'запас растёт'));
  }

  return { update };
}

// ------------------------------------------------- ladder and projection (wide)

export function createPlan() {
  const body = document.getElementById('plan-body');
  const meta = document.getElementById('plan-meta');
  let signature = '';

  function rung(row, currentTarget) {
    const facts = [
      ['Золото', withUnit(fmt(row.gold, 1), 'тыс. унц./год')],
      ['Прирост к базе', withUnit(fmt(row.goldGain, 1, { sign: true }), 'тыс. унц.')],
      ['Потребность в воздухе', withUnit(fmt(row.airDemand, 0), 'м³/с')],
      ['Дефицит воды', withUnit(fmt(row.deficit, 1), 'м³/ч')],
      ['Сброс в Волчевку', withUnit(fmt(row.discharge, 1), 'м³/ч')],
      ['Запас хвостохранилищ', withUnit(fmt(row.tailingsYears, 1), 'лет')],
    ];
    return el('div', { class: 'rung' + (row.target === currentTarget ? ' is-current' : '') },
      el('div', { class: 'rung-head' },
        el('div', { class: 't', text: `Цель ${fmt(row.target)} ${KT}` + (row.target === currentTarget ? ' · выбрана' : '') }),
        el('div', { class: 'v num' }, fmt(row.achievable), el('small', {}, ` ${KT} достижимо`)),
        el('span', { class: 'state', dataset: { tone: row.reached ? 'ok' : 'accent' },
          text: row.reached ? `мер: ${fmt(row.steps.length)}` : `предел: ${linkLabel(row.binding).toLowerCase()}` })),
      el('dl', { class: 'rung-facts' }, facts.map(([k, v]) => [el('dt', { text: k }), el('dd', { class: 'num', text: v })])),
      el('ol', { class: 'rung-steps' }, row.steps.length
        ? row.steps.map((step) => el('li', {}, el('div', {},
          el('b', { text: linkLabel(step.link) }),
          el('span', { class: 'num', text: isNum(step.capBefore) ? ` ${fmt(step.capBefore)} → ` : ' → ' }),
          el('span', { text: step.text }))))
        : el('li', {}, el('span', { text: 'меры не нужны' }))));
  }

  function update(model) {
    const next = JSON.stringify([model && model.ladder, model && model.projection, model && model.target]);
    if (next === signature) return;
    signature = next;
    clear(body);
    if (!model || (!model.ladder.length && !model.projection)) {
      setText(meta, DASH);
      body.append(el('p', { class: 'empty', text: 'Лестница мер и прогноз появятся с отчётом советника.' }));
      return;
    }
    setText(meta, 'меры от базового набора при текущих нарушениях; прогноз для текущего набора мер');
    const left = el('div', {}, el('h3', { class: 'sub-title', text: 'Лестница мер по четырём целям' }),
      el('div', { class: 'ladder' }, model.ladder.map((row) => rung(row, model.target))),
      el('p', { class: 'plan-notes' }, el('span', {},
        'Число перед стрелкой: пропускная способность узкого места до меры, тыс. т/год.')));
    const right = el('div', {}, el('h3', { class: 'sub-title', text: 'Прогноз на 2027–2036 годы' }));
    if (model.projection && model.projection.rows.length) {
      const table = el('table', { class: 'proj' },
        el('thead', {}, el('tr', {},
          el('th', { text: 'Год' }), el('th', { class: 'r', text: 'Достижимо, тыс. т' }),
          el('th', { text: 'Узкое место' }), el('th', { class: 'r', text: 'Золото, тыс. унц.' }),
          el('th', { class: 'r', text: 'Хвосты накоплено, тыс. т' }),
          el('th', { class: 'r', text: 'Свободная ёмкость, тыс. т' }),
          el('th', { class: 'r', text: 'Дефицит воды, м³/ч' }))),
        el('tbody', {}, model.projection.rows.map((row) => el('tr',
          { class: isNum(model.target) && isNum(row.achievable) && row.achievable < model.target ? 'is-short' : '' },
          el('td', { class: 'num', text: String(row.year ?? DASH) }),
          el('td', { class: 'r num', text: fmt(row.achievable) }),
          el('td', {}, el('span', { class: 'state', dataset: { tone: 'accent' }, text: linkLabel(row.binding).toLowerCase() })),
          el('td', { class: 'r num', text: fmt(row.gold, 1) }),
          el('td', { class: 'r num', text: fmt(row.stored) }),
          el('td', { class: 'r num', text: fmt(row.free) }),
          el('td', { class: 'r num', text: fmt(row.deficit, 1) })))));
      const notes = el('div', { class: 'plan-notes' },
        el('span', {}, 'Ёмкость хвостохранилищ исчерпывается: ',
          el('b', { text: model.projection.runsOut ? `в ${model.projection.runsOut} г.` : 'не раньше 2037 г.' })),
        el('span', {}, 'Цель переработки не достигается: ',
          el('b', { text: model.projection.missed ? `с ${model.projection.missed} г.` : 'достигается все десять лет' })),
        el('span', {}, 'Работы уходят вглубь по мере добычи; откатка каждый год пересчитывается для новой глубины.'));
      right.append(el('div', { class: 'scroll' }, table), notes);
    } else {
      right.append(el('p', { class: 'empty', text: 'Прогноз в отчёте отсутствует.' }));
    }
    body.append(el('div', { class: 'plan' }, left, right));
  }

  return { update };
}
