// «Советник по расширению»: capacity bars against the target, the next step (a repair of a
// disturbance first, then the expansion measures) with the time it would really be in service,
// conditions no measure removes, KPIs in the steady state, and the wide panel with the ladder
// for the four targets over the 2027–2036 horizon (schedule with lead times, the year each target
// is held to, the binding link by year, the ten-year economics after tax) and the horizon of the
// current state.
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
      capBefore: null, capAfter: null, inService: '', inServiceYear: null,
    };
  }
  return {
    kind: step.kind || 'measure',
    link: pick(step, 'link', 'binding_link'),
    knob: typeof step.knob === 'string' ? step.knob : null,
    text: pick(step, 'text', 'measure', 'name') || '',
    capBefore: num(pick(step, 'cap_before_ktpa', 'cap_before', 'capacity_before')),
    capAfter: num(pick(step, 'cap_after_ktpa', 'cap_after', 'capacity_after')),
    inService: step.in_service_text || '',
    inServiceWhen: step.in_service_when || '',
    inServiceYear: num(step.in_service_year),
    // a step whose trucks or LHDs wait for the air they need: when its lead time would have allowed it
    deferredWhen: step.deferred_when || '',
    inHorizon: step.in_horizon !== false,
  };
}

// When a step of the ladder is in service, in parts the line may break between: «сразу», «с 2028»,
// «с 2028» + «ждёт воздуха с II пол. 2027».
function serviceWhen(step) {
  if (step.kind === 'disturbance') return ['сразу'];
  if (!step.inHorizon) return ['не вводится:', 'технике не хватит воздуха'];
  return [`с ${step.inServiceWhen}`].concat(step.deferredWhen ? [`ждёт воздуха с ${step.deferredWhen}`] : []);
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

function normalizeVariant(variant) {
  const v = variant || {};
  const pre = v.pre_tax || {};
  return {
    capex: num(v.capex_usd_m), cash: num(v.cash_usd_m), npv: num(v.npv_usd_m),
    payback: num(v.payback_year), paybackText: v.payback_text || '',
    pre: { cash: num(pre.cash_usd_m), npv: num(pre.npv_usd_m), payback: num(pre.payback_year) },
  };
}

function normalizeEconomics(econ) {
  if (!econ || typeof econ !== 'object' || !econ.totals) return null;
  const t = econ.totals;
  const variants = econ.variants || {};
  return {
    first: econ.first_year, last: econ.last_year, holds: Boolean(econ.holds),
    price: num(econ.gold_price_usd_oz), aisc: num(econ.aisc_usd_oz), marginOz: num(econ.margin_usd_oz),
    cit: num(econ.cit_rate_pct), rate: num(econ.discount_rate_pct),
    totals: {
      gold: num(t.gold_koz), refGold: num(t.reference_gold_koz), gain: num(t.gain_koz), revenue: num(t.revenue_usd_m),
      margin: num(t.margin_usd_m), tax: num(t.tax_usd_m), marginAfter: num(t.margin_after_tax_usd_m),
      capexPub: num(t.capex_published_usd_m), capexAss: num(t.capex_assumed_usd_m),
    },
    disclosed: normalizeVariant(variants.disclosed), assumed: normalizeVariant(variants.with_assumed),
    years: (econ.years || []).map((y) => ({
      year: y.year, gain: num(y.gain_koz), cum: num(y.cumulative_usd_m), cumAss: num(y.cumulative_with_assumed_usd_m),
      cumPre: num(y.cumulative_pre_tax_usd_m),
    })),
    capexDisclosed: Boolean(econ.capex_disclosed), capex: num(econ.capex_usd_m),
    capexNote: econ.capex_note || '', assumedNote: econ.assumed_note || '', priceBasis: econ.price_basis || '',
    aiscBasis: econ.aisc_basis || '', taxBasis: econ.tax_basis || '', discountBasis: econ.discount_basis || '',
    caveats: econ.caveats || '', referenceText: econ.reference_text || '',
    notCosted: (econ.not_costed || []).map((e) => e && e.text).filter(Boolean),
  };
}

function normalizeHorizon(h) {
  if (!h || typeof h !== 'object' || !Array.isArray(h.rows)) return null;
  return {
    first: h.first_year ?? null, last: h.last_year ?? null, target: num(h.target_ktpa),
    label: h.label || '', text: h.text || '',
    reached: h.reached_year ?? null, heldTo: h.held_to_year ?? null, holds: Boolean(h.holds),
    lostYear: h.lost_year ?? null, bestYear: h.best_year ?? null, best: num(h.best_ktpa),
    rows: h.rows.map((row) => ({
      year: row.year, achievable: num(row.achievable_ktpa), mined: num(row.mined_ktpa),
      binding: row.binding_link || null, met: Boolean(row.target_met), mineLink: row.mine_link || null,
      mineCap: num(row.mine_ktpa), centroid: num(row.centroid_m), trucks: num(row.trucks),
      gold: num(pick(row, 'gold_koz', 'gold_koz_year')), stored: num(row.tailings_stored_kt),
      free: num(row.tailings_free_kt), deficit: num(row.water_deficit_m3h), note: row.note || '',
      measures: (row.measures || []).map((m) => ({ link: m.link, text: m.text || '', when: m.when_short || '',
        origin: m.origin || '', kind: m.kind || '' })),
    })),
    schedule: (h.schedule || []).map((e) => ({
      time: num(e.time), when: e.when_short || '', link: e.link, kind: e.kind || '', origin: e.origin || '',
      text: e.text || '', inService: e.in_service_text || '', deferredWhen: e.deferred_from_short || '',
      inHorizon: e.in_horizon !== false,
    })),
    runs: (h.binding_runs && h.binding_runs.text) || '',
    depthRule: (h.depth_rule && h.depth_rule.text) || '',
    storageNote: h.storage_note || '',
    trucksEnd: num(h.trucks_end), depthTrucks: num(h.depth_trucks), beyond: num(h.trucks_beyond_registry),
    economics: normalizeEconomics(h.economics),
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
    conditions: r && Array.isArray(r.conditions) ? r.conditions.map((c) => c && c.text).filter(Boolean) : [],
    kpi: {
      gold: k('gold_koz_year'), goldGain: k('gold_gain_koz_year'),
      airDemand: k('air_demand_m3s') ?? num(mine.air_demand_m3s),
      airSupply: num(kpi.air_supply_m3s) ?? num(mine.air_supply_m3s),
      deficit: k('water_deficit_m3h'), discharge: k('discharge_m3h'),
      permit: num(kpi.permit_m3h) ?? num(outfall.permit_m3h),
      permitUse: num(kpi.permit_use_pct),
      // the same balance with every plant line running, the value the live 1-hour means show
      // between the planned line stops (decision 11.4)
      deficitLines: num(kpi.water_deficit_all_lines_m3h), dischargeLines: num(kpi.discharge_all_lines_m3h),
      permitUseLines: num(kpi.permit_use_all_lines_pct), waterBasis: kpi.water_basis || '',
      tailingsYears: k('tailings_years_left'),
      // A report says null when the stockpile does not fall; the twin can only say 0.
      stockpileDays: r && r.kpi ? num(kpi.stockpile_days_left) : (twin.stockpile_days_left || null),
      stockpileTrend: kpi.stockpile_trend || null,
      stockpileNet: num(kpi.stockpile_net_tpd),
      stockpileMine: num(kpi.stockpile_mine_tpd),
      stockpilePlant: num(kpi.stockpile_plant_tpd),
      margin: k('dewatering_margin'),
      marginNext: num(kpi.dewatering_margin_next_failure),
      standby: num(kpi.pumps_standby),
      reserve: kpi.dewatering_reserve || '',
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
      horizon: normalizeHorizon(row.horizon),
      economics: normalizeEconomics(row.economics),
    })),
    projection: r && r.projection ? normalizeHorizon(r.projection) : null,
    effects: effectsRaw ? {
      label: effectsRaw.label || '', revision: num(effectsRaw.revision),
      items: (effectsRaw.items || []).map((item) => (typeof item === 'string'
        ? { text: item, trend: 'neutral' }
        : { id: item.id, text: item.text || '', trend: item.trend || 'neutral' })).filter((item) => item.text),
    } : null,
    calibration: r && Array.isArray(r.calibration) ? r.calibration : null,
  };
}

// The tone of a horizon outcome: held to the end, lost on the way, never reached.
function holdTone(h) {
  if (!h) return null;
  return h.holds ? 'ok' : h.reached !== null ? 'warn' : 'fail';
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

// Note on the dewatering bar while it does not limit: the pump margin and the standby, so that a
// single pump failure shows (×2,54 with a standby; without it, ×1,27 after the next failure).
function dewateringNote(kpi) {
  if (!isNum(kpi.margin)) return { text: 'не ограничивает', warn: false };
  if (isNum(kpi.standby) && kpi.standby <= 0 && isNum(kpi.marginNext)) {
    return { text: `без резерва: при отказе ×${fmt(kpi.marginNext, 2)}`, warn: true };
  }
  const reserve = isNum(kpi.standby) ? `, резерв ${fmt(kpi.standby)}` : '';
  return { text: `запас насосов ×${fmt(kpi.margin, 2)}${reserve}`, warn: false };
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
    const horizon = el('div', { class: 'd', style: 'margin: -4px 0 8px; font-size: 12px; color: var(--text-2)' });
    const legend = el('div', { class: 'cap-legend' },
      el('span', {}, el('i', { class: 'lg-bind' }), 'узкое место'),
      el('span', {}, el('i', { class: 'lg-target' }), 'цель'),
      el('span', {}, el('i', { class: 'lg-bar' }), 'пропускная способность звена'));
    const conditions = el('div', { class: 'adv-conditions' });
    const next = el('div', { class: 'next' });
    const kpis = el('div', { class: 'kpis' });
    const steady = el('p', { class: 'muted', style: 'margin: 6px 0 0; font-size: 11px; line-height: 1.35' });
    clear(body).append(summary, horizon, axis, caps, legend, conditions, next, kpis, steady);
    return { rows, axis, axisLabel, caps, summary, horizon, conditions, next, kpis, steady };
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

    // The same target over the horizon, with lead times: one message with the wide panel.
    const h = model.projection;
    clear(built.horizon);
    if (h && h.label) {
      built.horizon.title = h.text;
      built.horizon.append(el('span', { class: 'state', dataset: { tone: holdTone(h) },
        text: `${h.first}–${h.last}: цель ${h.label}` }),
      h.reached && !h.holds ? ` · достигается в ${h.reached} г.` : h.reached && h.reached > h.first ? ` · с ${h.reached} г.` : '');
    }

    // One scale for the eight bars; a bar longer than the scale is cut and marked.
    const caps = model.links.filter((link) => link.limiting && isNum(link.cap)).map((link) => link.cap);
    const top = Math.max(...caps, target || 0, 1);
    const scale = Math.min(top, Math.max((target || top) * 2.2, Math.min(...caps, top) * 1.3)) * 1.04;
    const targetPos = isNum(target) ? Math.min(100, (target / scale) * 100) : null;
    built.caps.style.setProperty('--target', targetPos === null ? '-10%' : targetPos + '%');
    built.axis.style.setProperty('--target', targetPos === null ? '-10%' : targetPos + '%');
    setText(built.axisLabel, isNum(target) ? `цель ${fmt(target)}` : '');

    const pumps = dewateringNote(model.kpi);
    for (const link of model.links) {
      const { row, fill, note, value } = built.rows[link.id];
      const over = link.limiting && isNum(link.cap) && link.cap > scale;
      row.classList.toggle('is-binding', link.binding);
      row.classList.toggle('is-off', !link.limiting);
      fill.classList.toggle('is-over', over);
      fill.style.width = link.limiting && isNum(link.cap) ? Math.min(100, (link.cap / scale) * 100) + '%' : '0%';
      setText(value, link.limiting ? fmt(link.cap) : DASH);
      const dewatering = link.id === 'dewatering';
      setText(note, link.limiting ? '' : dewatering ? pumps.text : 'не ограничивает');
      note.style.color = !link.limiting && dewatering && pumps.warn ? 'var(--warn)' : '';
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
        el('div', { class: 'd num', style: 'white-space: normal', text: [gain, left].filter(Boolean).join(' · ') }),
        next.inService ? el('div', { class: 'd', style: 'white-space: normal; color: var(--text)',
          text: next.inService.charAt(0).toUpperCase() + next.inService.slice(1) }) : null);
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
        !isNum(kpi.deficit) ? '' : isNum(kpi.deficitLines) && Math.abs(kpi.deficitLines - kpi.deficit) >= 0.05
          ? `все линии ${fmt(kpi.deficitLines, 1)}`
          : kpi.deficit > 0.05 ? 'фабрике не хватает' : 'воды хватает',
        isNum(kpi.deficit) && kpi.deficit > 0.05 ? 'warn' : null,
        `Дефицит технической воды ${STEADY}, в среднем за цикл ремонтов линий`
          + `${isNum(kpi.deficitLines) ? `; при всех линиях в работе ${fmt(kpi.deficitLines, 1)} м³/ч` : ''}`
          + `${kpi.waterBasis ? `. Темпы: ${kpi.waterBasis}` : ''}`),
      kpiTile('Сброс в Волчевку*', fmt(kpi.discharge, 1), 'м³/ч',
        isNum(kpi.dischargeLines) && Math.abs(kpi.dischargeLines - kpi.discharge) >= 0.05
          ? `все линии ${fmt(kpi.dischargeLines, 1)}`
          : isNum(kpi.permit) ? `${permitShare || 'разрешено ' + fmt(kpi.permit, 1)}` : '', overPermit ? 'fail' : null,
        isNum(kpi.permit) ? `Сброс ${STEADY}, в среднем за цикл ремонтов линий: ${fmt(kpi.discharge, 1)} м³/ч`
          + `${permitShare ? ` (${permitShare})` : ''}`
          + `${isNum(kpi.dischargeLines) ? `; при всех линиях в работе ${fmt(kpi.dischargeLines, 1)} м³/ч`
            + `${isNum(kpi.permitUseLines) ? ` (${fmt(kpi.permitUseLines, 0)} % разрешённого)` : ''}` : ''}`
          + `; разрешено ${fmt(kpi.permit, 1)} м³/ч${kpi.waterBasis ? `. Темпы: ${kpi.waterBasis}` : ''}` : ''),
      kpiTile('Рудный склад*', stock.value, stock.unit, stock.detail, stock.tone, stock.title));
    setText(built.steady, `* ${STEADY.charAt(0).toUpperCase() + STEADY.slice(1)} выбранного варианта; `
      + 'на двойниках — текущие значения (вода — средние за 1 ч, темпы — с момента смены сценария). '
      + 'Ручки Стенда переключают меры сразу; сроки ввода — в прогнозе на десять лет.');
  }

  return { update };
}

// ------------------------------------------------- ladder and projection (wide)

const usd = (value, digits = 1) => withUnit(fmt(value, digits), USD_M);
const shortText = (text) => (text || '').split(/ \(|; /)[0];

// Measures entering service in a year, grouped by half-year and link: «II пол.: откатка ×3, фабрика».
function measuresCell(measures) {
  const halves = new Map();
  for (const m of measures) {
    const half = m.when.startsWith('II') ? 'II пол.' : 'I пол.';
    const links = halves.get(half) || new Map();
    const name = m.kind === 'disturbance' ? `${linkLabel(m.link).toLowerCase()}, ремонт` : linkLabel(m.link).toLowerCase();
    links.set(name, (links.get(name) || 0) + 1);
    halves.set(half, links);
  }
  return [...halves.entries()].sort(([a], [b]) => a.length - b.length)
    .map(([half, links]) => `${half}: ` + [...links.entries()].map(([name, n]) => (n > 1 ? `${name} ×${n}` : name)).join(', '))
    .join('; ');
}

// Ten cells, one per year: green when the target is met, orange when short, red when the plant
// stands for want of storage; the tooltip names what limits the year.
function yearStrip(h) {
  const cells = h.rows.map((row) => {
    const stop = row.binding === 'tailings';
    const bg = row.met ? 'rgba(62, 199, 154, 0.22)' : stop ? 'rgba(220, 64, 70, 0.28)' : 'var(--accent-soft)';
    const fg = row.met ? 'var(--text)' : stop ? 'var(--fail-text)' : 'var(--accent)';
    const title = `${row.year}: переработано ${fmt(row.achievable)} тыс. т, узкое место — ${linkLabel(row.binding).toLowerCase()}`
      + `; рудник: ${linkLabel(row.mineLink).toLowerCase()} ${fmt(row.mineCap)} тыс. т/год; центр добычи ${fmt(row.centroid)} м`
      + (row.note ? `; ${row.note}` : '');
    return el('span', { class: 'num', title,
      style: `display: block; text-align: center; font-size: 10.5px; line-height: 16px; border-radius: 2px; background: ${bg}; color: ${fg}` },
    String(row.year).slice(2));
  });
  return el('div', { style: 'display: grid; grid-template-columns: repeat(10, minmax(0, 1fr)); gap: 2px' }, cells);
}

function economicsBlock(econ) {
  if (!econ) return null;
  const t = econ.totals;
  const d = econ.disclosed;
  const a = econ.assumed;
  const capex = econ.capexDisclosed && isNum(econ.capex) ? withUnit(`≈${fmt(econ.capex)}`, USD_M) : 'не раскрыто';
  const facts = [
    ['Прирост золота к базе', withUnit(fmt(t.gain, 1, { sign: true }), 'тыс. унц.'),
      `${econ.referenceText}; золото плана ${fmt(t.gold, 1)}, базы ${fmt(t.refGold, 1)} тыс. унц.`],
    ['Маржа после налога', usd(t.marginAfter),
      `до налога ${usd(t.margin)}; налог ${usd(t.tax)}: ${econ.taxBasis}. Цена ${fmt(econ.price)} долл./унц. `
      + `(${econ.priceBasis}) минус AISC ${fmt(econ.aisc)} долл./унц.: ${econ.aiscBasis}`],
    ['Капзатраты раскрытые', capex, econ.capexNote],
    ['С оценкой (не опубл.)', usd(a.capex), econ.assumedNote],
    [`NPV ${fmt(econ.rate)} %, раскр. / с оц.`, `${fmt(d.npv, 0)} / ${fmt(a.npv, 0)}`,
      `чистая приведённая стоимость после налога, ${USD_M}; до налога ${fmt(d.pre.npv, 0)} / ${fmt(a.pre.npv, 0)}. `
      + `${econ.discountBasis}`],
    ['Денежный поток за 10 лет', usd(d.cash, 0),
      `после налога, раскрытые капзатраты; с оценкой ${usd(a.cash, 0)}; до налога ${usd(d.pre.cash, 0)}`],
  ];
  const payback = isNum(d.payback) ? `окупается в ${d.payback} г.`
    : isNum(a.payback) ? `с оценкой затрат окупается в ${a.payback} г.; раскрытых капзатрат нет`
      : d.paybackText;
  return el('div', {},
    el('div', { class: 'rung-head', style: 'padding: 6px 10px 0; border-bottom: 0' },
      el('div', { class: 't', text: `Экономика ${econ.first}–${econ.last} гг. после налога` })),
    el('dl', { class: 'rung-facts', style: 'border-bottom: 0; padding-bottom: 2px' },
      facts.map(([k, v, title]) => [el('dt', { text: k, title: title || null }),
        el('dd', { class: 'num', text: v, title: title || null })])),
    el('div', { class: 'd', style: 'padding: 0 10px 8px; font-size: 12px; color: var(--text-2); border-bottom: 1px solid var(--line)',
      title: econ.caveats, text: `Окупаемость: ${payback}` }));
}

const ORIGIN_RU = { horizon: 'по ходу горизонта', current: 'текущий набор мер', ladder: '' };

export function createPlan() {
  const body = document.getElementById('plan-body');
  const meta = document.getElementById('plan-meta');
  let signature = '';

  function scheduleList(row) {
    const h = row.horizon;
    const steps = row.steps.map((step) => el('li', { title: step.inService || null }, el('div', {},
      el('b', { text: step.kind === 'disturbance' ? `${linkLabel(step.link)}, ремонт` : linkLabel(step.link),
        style: step.kind === 'disturbance' ? 'color: var(--warn)' : null }),
      el('span', { class: 'num', text: isNum(step.capBefore) ? ` ${fmt(step.capBefore)} → ` : ' → ' }),
      el('span', { text: step.text }),
      // the space before each part stays outside its no-wrap span, so the line may break there
      step.inServiceWhen ? serviceWhen(step).map((part) => [' ', el('span', { class: 'num',
        style: `color: ${step.deferredWhen || !step.inHorizon ? 'var(--warn)' : 'var(--text)'}; white-space: nowrap`,
        text: `· ${part}` })]) : null)));
    const later = h ? h.schedule.filter((e) => e.origin === 'horizon' && e.inHorizon) : [];
    const list = el('ol', { class: 'rung-steps', style: 'border-top: 1px solid var(--line)' },
      steps.length ? steps : el('li', {}, el('span', { text: 'меры к 2027 г. не нужны' })));
    if (!later.length) return list;
    return el('div', {}, list,
      el('div', { style: 'padding: 0 10px 10px; display: grid; gap: 3px; font-size: 12px' },
        el('div', { style: 'color: var(--text-3); font-size: 11px', text: 'Добавляется по ходу горизонта (глубина, заполнение хвостов):' }),
        later.map((e) => el('div', { style: 'display: grid; grid-template-columns: 76px minmax(0, 1fr)',
          title: `${e.text}; ${e.inService}` },
        el('span', { class: 'num', style: `color: ${e.deferredWhen ? 'var(--warn)' : 'var(--text)'}`, text: e.when }),
        el('div', {}, el('b', { style: 'font-weight: 600', text: linkLabel(e.link) }),
          el('span', { style: 'color: var(--text-2)', text: ` ${shortText(e.text)}` }))))));
  }

  function rung(row, currentTarget) {
    const h = row.horizon;
    const current = row.target === currentTarget;
    const tone = holdTone(h);
    const facts = h ? [
      h.reached ? ['Достигается', `${h.reached} г.`]
        : ['Ближе всего', isNum(h.best) ? `${h.bestYear} г.: ${withUnit(fmt(h.best), 'тыс. т')}` : 'нет'],
      ['Самосвалов к ' + h.last + ' г.', h.beyond ? `${fmt(h.trucksEnd)} (сверх реестра ${fmt(h.beyond)})` : fmt(h.trucksEnd)],
      ['Золото за 10 лет', withUnit(fmt(row.economics ? row.economics.totals.gold : null, 1), 'тыс. унц.')],
      ['Воздух, весь парк*', withUnit(fmt(row.airDemand, 0), 'м³/с')],
    ] : [];
    return el('div', { class: 'rung' + (current ? ' is-current' : '') },
      el('div', { class: 'rung-head', title: h ? h.text : null },
        el('div', { class: 't', text: `Цель ${fmt(row.target)} ${KT}` + (current ? ' · выбрана' : '') }),
        el('div', { class: 'v', style: 'font-size: 15px; white-space: normal' }, h ? h.label : DASH),
        el('span', { class: 'state', dataset: { tone: tone || 'accent' },
          text: h ? (h.holds ? `цель с ${h.reached} г.` : h.reached ? `с ${h.reached} г., с ${h.lostYear} г. ниже цели`
            : 'цель не достигается') : `шагов: ${fmt(row.steps.length)}` })),
      h ? el('div', { style: 'padding: 6px 10px 6px; border-bottom: 1px solid var(--line)' }, yearStrip(h),
        el('div', { class: 'muted', style: 'margin-top: 4px; font-size: 11px; line-height: 1.3', text: `Узкое место: ${h.runs}` }),
        h.holds ? null : el('div', { style: 'margin-top: 3px; font-size: 11.5px; line-height: 1.3; color: var(--text)', text: h.text }))
        : null,
      el('dl', { class: 'rung-facts' }, facts.map(([k, v]) => [el('dt', { text: k }), el('dd', { class: 'num', text: v })])),
      economicsBlock(row.economics),
      scheduleList(row));
  }

  function projectionTable(h) {
    const econ = h.economics;
    const cumulative = new Map((econ ? econ.years : []).map((y) => [y.year, y]));
    return el('table', { class: 'proj', style: 'font-size: 12px' },
      el('thead', {}, el('tr', {},
        el('th', { text: 'Год' }), el('th', { class: 'r', text: 'Перераб., тыс. т' }),
        el('th', { text: 'Узкое место' }), el('th', { text: 'Вводится' }),
        el('th', { class: 'r', text: 'Центр добычи, м', title: 'отметка центра добычи на конец года' }),
        el('th', { class: 'r', text: 'Самосвалов' }),
        el('th', { class: 'r', text: 'Золото, тыс. унц.' }),
        el('th', { class: 'r', text: 'Своб. ёмкость хвостов, тыс. т' }),
        el('th', { class: 'r', text: 'Поток накопл., млн долл.', title: 'накопленный денежный поток прироста после налога, раскрытые капзатраты' }))),
      el('tbody', {}, h.rows.map((row) => {
        const y = cumulative.get(row.year) || {};
        return el('tr', { class: row.met ? '' : 'is-short' },
          el('td', { class: 'num', text: String(row.year ?? DASH) }),
          el('td', { class: 'r num', text: fmt(row.achievable) }),
          el('td', {}, el('span', { class: 'state', dataset: { tone: row.met ? 'ok' : row.binding === 'tailings' ? 'fail' : 'accent' },
            text: linkLabel(row.binding).toLowerCase() }),
          row.note ? el('div', { class: 'muted', style: 'white-space: normal; font-size: 11px; line-height: 1.3', text: row.note }) : null),
          el('td', { style: 'white-space: normal; font-size: 11px; line-height: 1.3; color: var(--text-2); min-width: 120px',
            title: row.measures.map((m) => `${m.when}: ${linkLabel(m.link).toLowerCase()} — ${m.text}`).join('\n') || null },
          measuresCell(row.measures)),
          el('td', { class: 'r num', text: fmt(row.centroid, 0) }),
          el('td', { class: 'r num', text: fmt(row.trucks) }),
          el('td', { class: 'r num', text: fmt(row.gold, 1) }),
          el('td', { class: 'r num', text: fmt(row.free) }),
          el('td', { class: 'r num', title: isNum(y.cumAss) ? `с оценочными затратами ${fmt(y.cumAss, 0)}; до налога ${fmt(y.cumPre, 0)}` : null,
            text: fmt(y.cum, 0) }));
      })));
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
    setText(meta, 'меры вводятся после срока ввода от решения в начале 2027 г.; шаг расчёта — полгода');
    const notes = [el('span', {}, 'Число перед стрелкой: пропускная способность узкого места до шага, тыс. т/год, '
      + 'при глубине 2027 г.; после шага — с какого времени мера в работе. «Ремонт» — устранение нарушения, оно идёт раньше мер расширения.'),
    el('span', {}, 'Клетки годов: зелёная — цель выполнена, оранжевая — ниже цели, красная — фабрике некуда складировать хвосты. '
      + 'По ходу горизонта советник добавляет самосвалы по мере углубления '
      + 'и ступени хвостохранилища по мере заполнения. '
      + 'Самосвалы и ПДМ вводятся, когда на них хватает воздуха: до ввода вентиляторов ВПВ и ВС-3 мера ждёт, '
      + 'даже если срок её ввода прошёл («ждёт воздуха с …» — когда она была бы готова по сроку ввода).'),
    el('span', {}, `* ${STEADY}. Экономика: прирост золота к базе по цене реализации и AISC первого полугодия 2026 г., `
      + 'минус налог на прибыль; капзатраты — опубликованные компанией и отдельно оценочные (не опубликовано); '
      + 'окупаемость не указывается для цели, которая не удерживается до 2036 г.')];
    if (model.baseline && model.baseline.text) notes.push(el('span', {}, model.baseline.text));
    const left = el('div', {}, el('h3', { class: 'sub-title', text: 'Лестница мер по четырём целям на 2027–2036 годы' }),
      el('div', { class: 'ladder' }, model.ladder.map((row) => rung(row, model.target))),
      el('p', { class: 'plan-notes' }, notes));
    const h = model.projection;
    const right = el('div', {}, el('h3', { class: 'sub-title',
      text: h ? `Прогноз на ${h.first}–${h.last} годы: цель ${fmt(h.target)} ${KT} из текущего состояния` : 'Прогноз' }));
    if (h && h.rows.length) {
      const tone = holdTone(h);
      const econ = h.economics;
      right.append(
        el('div', { class: 'next', style: `margin: 0 0 8px; border-left-color: var(--${tone === 'ok' ? 'ok' : tone === 'warn' ? 'warn' : 'fail'})` },
          el('div', { class: 'v', text: `Цель ${h.label}` }),
          el('div', { class: 'd', style: 'white-space: normal', text: h.text }),
          el('div', { class: 'd', style: 'white-space: normal; margin-top: 3px', text: h.storageNote })),
        el('div', { class: 'scroll' }, projectionTable(h)),
        el('div', { class: 'plan-notes' },
          econ ? el('span', {}, el('b', { text: 'Экономика плана после налога: ' }),
            `золото ${fmt(econ.totals.gold, 1)} тыс. унц. (${fmt(econ.totals.gain, 1, { sign: true })} к базе), маржа `
            + `${usd(econ.totals.marginAfter)} (до налога ${usd(econ.totals.margin)}), NPV ${fmt(econ.rate)} % `
            + `${usd(econ.disclosed.npv, 0)} с раскрытыми капзатратами и ${usd(econ.assumed.npv, 0)} с оценочными; `
            + `окупаемость: ${isNum(econ.disclosed.payback) ? econ.disclosed.payback + ' г.' : isNum(econ.assumed.payback)
              ? 'с оценкой затрат ' + econ.assumed.payback + ' г.' : econ.disclosed.paybackText}`.replace(/\.?$/, '.')) : null,
          h.depthRule ? el('span', {}, h.depthRule) : null,
          econ && econ.caveats ? el('span', {}, `Оговорки: ${econ.caveats}.`) : null));
    } else {
      right.append(el('p', { class: 'empty', text: 'Прогноз в отчёте отсутствует.' }));
    }
    body.append(el('div', { class: 'plan' }, left, right));
  }

  return { update };
}
