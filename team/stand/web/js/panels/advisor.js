// «Советник по расширению»: capacity bars against the target, the next step (a repair of a
// disturbance first, then the expansion measures), conditions no measure removes, KPIs in the
// steady state, the ladder for the four targets with their economics and the ten-year
// projection with the year the tailings storage runs out.
//
// normalize() accepts the advisor report of GET /api/advisor and falls back to
// the features of the twin kz.sekis:advisor, so the bars work from the twin alone.

import { LINKS, MEASURES, NS, linkLabel } from './dict.js';
import { DASH, clear, el, fmt, isNum, setText, withUnit } from './format.js';

const KT = 'тыс. т/год';
const USD_M = 'млн долл.';
const STEADY = 'в установившемся режиме';
const num = (value) => (isNum(value) ? value : null);
const pick = (object, ...keys) => {
  for (const key of keys) {
    if (object && object[key] !== undefined && object[key] !== null) return object[key];
  }
  return null;
};

// Tokens of the twin feature next_measure for the removal of a disturbance (sekis.advisor).
const REPAIRS = {
  restore_pumps: { link: 'dewatering', knob: 'pumps_failed_p150', text: 'восстановить насосы главного водоотлива гор. +150 м' },
  restart_line: { link: 'plant', knob: 'line_down', text: 'запустить технологическую линию после ремонта' },
  open_tu1: { link: 'haulage', knob: 'tu1_closed', text: 'открыть уклон ТУ-1' },
  open_tu2: { link: 'haulage', knob: 'tu2_closed', text: 'открыть уклон ТУ-2' },
  restore_fan_vs2: { link: 'ventilation', knob: 'fan_vs2_off', text: 'восстановить вентилятор ВС-2' },
};

function normalizeStep(step) {
  if (!step) return null;
  if (typeof step === 'string') {
    if (step === 'none' || step === '') return null;
    const measure = MEASURES.find((m) => m.knob === step);
    const repair = REPAIRS[step];
    return {
      kind: repair ? 'disturbance' : 'measure',
      link: measure ? measure.link : repair ? repair.link : null,
      text: measure ? 'следующая ступень' : repair ? repair.text : step,
      knob: measure ? measure.knob : repair ? repair.knob : null,
      capBefore: null, capAfter: null,
    };
  }
  return {
    kind: step.kind || 'measure',
    link: pick(step, 'link', 'binding_link'),
    knob: typeof step.knob === 'string' ? step.knob : null,
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

function normalizeEconomics(econ) {
  if (!econ || typeof econ !== 'object') return null;
  return {
    gain: num(econ.gold_gain_koz_year), baseGold: num(econ.baseline_gold_koz_year),
    price: num(econ.gold_price_usd_oz), value: num(econ.value_usd_m_year),
    aisc: num(econ.aisc_usd_oz), marginOz: num(econ.margin_usd_oz), margin: num(econ.margin_usd_m_year),
    capex: num(econ.capex_usd_m), disclosed: Boolean(econ.capex_disclosed), payback: num(econ.payback_years),
    capexNote: econ.capex_note || '', priceBasis: econ.price_basis || '', aiscBasis: econ.aisc_basis || '',
  };
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
  const storage = projectionRaw && projectionRaw.storage_measure;

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
    conditions: r && Array.isArray(r.conditions) ? r.conditions.map((c) => c && c.text).filter(Boolean) : [],
    kpi: {
      gold: k('gold_koz_year'), goldGain: k('gold_gain_koz_year'),
      airDemand: k('air_demand_m3s') ?? num(mine.air_demand_m3s),
      airSupply: num(kpi.air_supply_m3s) ?? num(mine.air_supply_m3s),
      deficit: k('water_deficit_m3h'), discharge: k('discharge_m3h'),
      permit: num(kpi.permit_m3h) ?? num(outfall.permit_m3h),
      permitUse: num(kpi.permit_use_pct),
      tailingsYears: k('tailings_years_left'),
      // A report says null when the stockpile does not fall; the twin can only say 0.
      stockpileDays: r && r.kpi ? num(kpi.stockpile_days_left) : (twin.stockpile_days_left || null),
      stockpileTrend: kpi.stockpile_trend || null,
      stockpileNet: num(kpi.stockpile_net_tpd),
      stockpileMine: num(kpi.stockpile_mine_tpd),
      stockpilePlant: num(kpi.stockpile_plant_tpd),
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
      economics: normalizeEconomics(row.economics),
    })),
    projection: projectionRaw ? {
      rows: (projectionRaw.rows || []).map((row) => ({
        year: row.year, achievable: num(row.achievable_ktpa), binding: row.binding_link || null,
        gold: num(pick(row, 'gold_koz', 'gold_koz_year')),
        stored: num(row.tailings_stored_kt), free: num(row.tailings_free_kt),
        deficit: num(row.water_deficit_m3h), note: row.note || '',
      })),
      runsOut: projectionRaw.storage_runs_out_year ?? null,
      missed: projectionRaw.target_missed_year ?? null,
      lastYear: projectionRaw.last_year ?? null,
      storageNote: projectionRaw.storage_note || null,
      storageMeasure: storage && storage.text ? storage.text : null,
      storageWith: storage ? storage.storage_runs_out_year ?? null : null,
    } : null,
    effects: effectsRaw ? {
      label: effectsRaw.label || '', revision: num(effectsRaw.revision),
      items: (effectsRaw.items || []).map((item) => (typeof item === 'string'
        ? { text: item, trend: 'neutral' }
        : { id: item.id, text: item.text || '', trend: item.trend || 'neutral' })).filter((item) => item.text),
    } : null,
    calibration: r && Array.isArray(r.calibration) ? r.calibration : null,
  };
}

// ---------------------------------------------------------------- side panel

function stockpileTile(kpi) {
  const days = kpi.stockpileDays;
  const net = kpi.stockpileNet;
  const flows = isNum(kpi.stockpileMine) && isNum(kpi.stockpilePlant)
    ? `рудник ${fmt(kpi.stockpileMine)} т/сут, фабрика ${fmt(kpi.stockpilePlant)} т/сут, ${STEADY}` : STEADY;
  if (isNum(days)) {
    return { value: fmt(days), unit: 'сут',
      detail: (isNum(net) ? `расход ${fmt(-net)} т/сут` : 'до исчерпания') + ' при расчётной мощности',
      title: `Запас рудного склада кончится через ${fmt(days)} сут: ${flows}`, tone: days < 30 ? 'warn' : null };
  }
  if (kpi.stockpileTrend === 'grows' || (isNum(net) && net > 0)) {
    return { value: 'растёт', unit: '', detail: isNum(net) ? `+${fmt(net)} т/сут` : 'фабрика берёт меньше',
      title: `Рудник выдаёт больше, чем перерабатывает фабрика: ${flows}`, tone: null };
  }
  return { value: 'не меняется', unit: '', detail: 'рудник = фабрика', title: flows, tone: null };
}

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
    const conditions = el('div', { class: 'adv-conditions' });
    const next = el('div', { class: 'next' });
    const kpis = el('div', { class: 'kpis' });
    const steady = el('p', { class: 'muted', style: 'margin: 6px 0 0; font-size: 11px; line-height: 1.35' });
    clear(body).append(summary, axis, caps, legend, conditions, next, kpis, steady);
    return { rows, axis, axisLabel, caps, summary, conditions, next, kpis, steady };
  }

  function kpiTile(label, value, unit, detail, tone, title) {
    return el('div', { class: 'kpi', dataset: tone ? { tone } : {}, title: title || null },
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

    // Disturbances no measure removes: stated as conditions.
    clear(built.conditions);
    if (model.conditions.length) {
      built.conditions.append(el('div', { class: 'next',
        style: 'background: transparent; border-left-color: var(--warn); padding: 6px 10px' },
      el('div', { class: 'k', text: 'Условия, которые мерами не снимаются' }),
      model.conditions.map((text) => el('div', { class: 'd', style: 'color: var(--text); margin-top: 2px', text }))));
    }

    const next = model.next;
    const repair = next && next.kind === 'disturbance';
    built.next.classList.toggle('is-done', !next);
    built.next.style.borderLeftColor = repair ? 'var(--warn)' : '';
    clear(built.next);
    if (next) {
      const gain = isNum(next.capBefore) && isNum(next.capAfter)
        ? `${fmt(next.capBefore)} → ${withUnit(fmt(next.capAfter), KT)}` : '';
      const left = isNum(model.measuresNeeded) ? `шагов до цели: ${fmt(model.measuresNeeded)}` : '';
      built.next.append(
        el('div', { class: 'k', text: repair ? 'Сначала устранить нарушение' : 'Следующая мера' }),
        el('div', { class: 'v', text: `${linkLabel(next.link)}: ${next.text}` }),
        el('div', { class: 'd num', style: 'white-space: normal', text: [gain, left].filter(Boolean).join(' · ') }));
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
    const stock = stockpileTile(kpi);
    const permitShare = isNum(kpi.permitUse) ? `${fmt(kpi.permitUse, 0)} % разрешённого` : '';
    clear(built.kpis).append(
      kpiTile('Золото', fmt(kpi.gold, 1), 'тыс. унц./год',
        isNum(kpi.goldGain) ? `${fmt(kpi.goldGain, 1, { sign: true })}${base}` : ''),
      kpiTile('Воздух', `${fmt(kpi.airDemand, 0)} / ${fmt(kpi.airSupply, 0)}`, 'м³/с',
        'потребность всего парка / подача', airShort ? 'warn' : null),
      kpiTile('Хвосты', fmt(kpi.tailingsYears, 1), 'лет', 'до заполнения',
        isNum(kpi.tailingsYears) && kpi.tailingsYears < 3 ? 'warn' : null),
      kpiTile('Дефицит воды*', fmt(kpi.deficit, 1), 'м³/ч',
        !isNum(kpi.deficit) ? '' : kpi.deficit > 0.05 ? 'фабрике не хватает' : 'воды хватает',
        isNum(kpi.deficit) && kpi.deficit > 0.05 ? 'warn' : null, `Дефицит технической воды ${STEADY}`),
      kpiTile('Сброс в Волчевку*', fmt(kpi.discharge, 1), 'м³/ч',
        isNum(kpi.permit) ? `${permitShare || 'разрешено ' + fmt(kpi.permit, 1)}` : '', overPermit ? 'fail' : null,
        isNum(kpi.permit) ? `Сброс ${STEADY}; разрешено ${fmt(kpi.permit, 1)} м³/ч` : ''),
      kpiTile('Рудный склад*', stock.value, stock.unit, stock.detail, stock.tone, stock.title));
    setText(built.steady, `* ${STEADY.charAt(0).toUpperCase() + STEADY.slice(1)} выбранного варианта; `
      + 'на двойниках — текущие значения (вода — средние за 1 ч, темпы — с момента смены сценария).');
  }

  return { update };
}

// ------------------------------------------------- ladder and projection (wide)

function economicsBlock(econ) {
  if (!econ) return null;
  const gain = isNum(econ.gain) && econ.gain > 0;
  const capex = econ.disclosed && isNum(econ.capex) ? withUnit(`≈${fmt(econ.capex)}`, USD_M) : 'не раскрыто';
  const facts = [
    ['Прирост золота', withUnit(fmt(econ.gain, 1, { sign: true }), 'тыс. унц./год'), ''],
    ['Стоимость прироста', withUnit(fmt(econ.value, 1), USD_M + '/год'),
      `по цене ${fmt(econ.price)} долл./унц.: ${econ.priceBasis}`],
    ['Маржа прироста', withUnit(fmt(econ.margin, 1), USD_M + '/год'),
      `цена минус AISC ${fmt(econ.aisc)} долл./унц. = ${fmt(econ.marginOz)} долл./унц.; ${econ.aiscBasis}`],
    ['Капзатраты', capex, econ.capexNote],
    ['Простая окупаемость', isNum(econ.payback) ? `${fmt(econ.payback, 1)} года` : DASH,
      isNum(econ.payback) ? 'капзатраты / маржа прироста' : 'капзатраты не раскрыты'],
  ];
  return el('div', {},
    el('div', { class: 'rung-head', style: 'padding: 6px 10px 0; border-bottom: 0' },
      el('div', { class: 't', text: 'Экономика по отчётам компании' })),
    el('dl', { class: 'rung-facts' }, facts.map(([k, v, title]) => [
      el('dt', { text: k, title: title || null }),
      el('dd', { class: 'num', text: gain || k === 'Прирост золота' ? v : DASH, title: title || null })])));
}

export function createPlan() {
  const body = document.getElementById('plan-body');
  const meta = document.getElementById('plan-meta');
  let signature = '';

  function rung(row, currentTarget) {
    const facts = [
      ['Золото', withUnit(fmt(row.gold, 1), 'тыс. унц./год')],
      ['Потребность в воздухе', withUnit(fmt(row.airDemand, 0), 'м³/с')],
      ['Дефицит воды*', withUnit(fmt(row.deficit, 1), 'м³/ч')],
      ['Сброс в Волчевку*', withUnit(fmt(row.discharge, 1), 'м³/ч')],
      ['Запас хвостохранилищ', withUnit(fmt(row.tailingsYears, 1), 'лет')],
    ];
    return el('div', { class: 'rung' + (row.target === currentTarget ? ' is-current' : '') },
      el('div', { class: 'rung-head' },
        el('div', { class: 't', text: `Цель ${fmt(row.target)} ${KT}` + (row.target === currentTarget ? ' · выбрана' : '') }),
        el('div', { class: 'v num' }, fmt(row.achievable), el('small', {}, ` ${KT} достижимо`)),
        el('span', { class: 'state', dataset: { tone: row.reached ? 'ok' : 'accent' },
          text: row.reached ? `шагов: ${fmt(row.steps.length)}` : `предел: ${linkLabel(row.binding).toLowerCase()}` })),
      el('dl', { class: 'rung-facts' }, facts.map(([k, v]) => [el('dt', { text: k }), el('dd', { class: 'num', text: v })])),
      economicsBlock(row.economics),
      el('ol', { class: 'rung-steps', style: 'border-top: 1px solid var(--line)' }, row.steps.length
        ? row.steps.map((step) => el('li', {}, el('div', {},
          el('b', { text: step.kind === 'disturbance' ? `${linkLabel(step.link)}, ремонт` : linkLabel(step.link),
            style: step.kind === 'disturbance' ? 'color: var(--warn)' : null }),
          el('span', { class: 'num', text: isNum(step.capBefore) ? ` ${fmt(step.capBefore)} → ` : ' → ' }),
          el('span', { text: step.text }))))
        : el('li', {}, el('span', { text: 'меры не нужны' }))));
  }

  function storageBanner(projection) {
    if (!projection.runsOut) return null;
    const stops = projection.rows.find((row) => row.achievable === 0);
    const head = `Хвостохранилище заполнится в ${projection.runsOut} г.`
      + (stops ? ` С ${stops.year} г. фабрика стоит: нет ёмкости для хвостов.` : '');
    let measure;
    if (projection.storageMeasure) {
      measure = `Мера: ${projection.storageMeasure}; с ней `
        + (projection.storageWith ? `ёмкость закончится в ${projection.storageWith} г.`
          : `ёмкости хватит до конца прогноза${projection.lastYear ? ` (${projection.lastYear} г.)` : ''}`) + '.';
    } else {
      measure = 'Все ступени меры по хвостохранилищу уже введены: нужна ёмкость сверх новой карты.';
    }
    return el('div', { class: 'next', style: 'margin: 0 0 8px; border-left-color: var(--fail)' },
      el('div', { class: 'v', text: head }),
      el('div', { class: 'd', text: measure }));
  }

  function update(model) {
    const next = JSON.stringify([model && model.ladder, model && model.projection, model && model.target,
      model && model.baseline]);
    if (next === signature) return;
    signature = next;
    clear(body);
    if (!model || (!model.ladder.length && !model.projection)) {
      setText(meta, DASH);
      body.append(el('p', { class: 'empty', text: 'Лестница мер и прогноз появятся с отчётом советника.' }));
      return;
    }
    setText(meta, 'шаги от базового набора мер при текущих нарушениях; прогноз для текущего набора мер');
    const notes = [el('span', {}, 'Число перед стрелкой: пропускная способность узкого места до шага, тыс. т/год. '
      + '«Ремонт» — устранение нарушения, оно идёт раньше мер расширения.'),
    el('span', {}, `* ${STEADY}. Экономика: прирост золота к устойчивой базе по цене реализации и AISC `
      + 'первого полугодия 2026 г.; капзатраты — только опубликованные компанией.')];
    if (model.baseline && model.baseline.text) notes.push(el('span', {}, model.baseline.text));
    const left = el('div', {}, el('h3', { class: 'sub-title', text: 'Лестница мер по четырём целям' }),
      el('div', { class: 'ladder' }, model.ladder.map((row) => rung(row, model.target))),
      el('p', { class: 'plan-notes' }, notes));
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
          el('td', {}, el('span', { class: 'state', dataset: { tone: row.note ? 'fail' : 'accent' },
            text: linkLabel(row.binding).toLowerCase() }),
          row.note ? el('div', { class: 'muted', style: 'white-space: normal; font-size: 11px; line-height: 1.3',
            text: row.note }) : null),
          el('td', { class: 'r num', text: fmt(row.gold, 1) }),
          el('td', { class: 'r num', text: fmt(row.stored) }),
          el('td', { class: 'r num', text: fmt(row.free) }),
          el('td', { class: 'r num', text: fmt(row.deficit, 1) })))));
      const notesRight = el('div', { class: 'plan-notes' },
        el('span', {}, 'Цель переработки не достигается: ',
          el('b', { text: model.projection.missed ? `с ${model.projection.missed} г.` : 'достигается все десять лет' })),
        el('span', {}, 'Работы уходят вглубь по мере добычи; откатка каждый год пересчитывается для новой глубины.'));
      right.append(storageBanner(model.projection) || el('div', { class: 'plan-notes', style: 'margin: 0 0 8px' },
        el('span', {}, 'Ёмкости хвостохранилищ хватает до конца прогноза.')),
      el('div', { class: 'scroll' }, table), notesRight);
    } else {
      right.append(el('p', { class: 'empty', text: 'Прогноз в отчёте отсутствует.' }));
    }
    body.append(el('div', { class: 'plan' }, left, right));
  }

  return { update };
}
