// Russian texts of the scene labels: a short name, the state and one key value
// per twin. State words come from the shared dictionary of the panels.

import { thingState } from '../panels/dict.js';
import { DASH, fmt, isNum, withUnit } from '../panels/format.js';

const MINUS = '−';

/** +150, 0, −50: an elevation with its sign. */
export function elevationText(metres) {
  if (!isNum(metres)) return DASH;
  const rounded = Math.round(metres);
  return (rounded > 0 ? '+' : rounded < 0 ? MINUS : '') + Math.abs(rounded);
}

/** «3,1 года», «5 лет», «1 год». */
export function yearsText(value) {
  if (!isNum(value)) return DASH;
  const rounded = Number(value.toFixed(1));
  let word = 'лет';
  if (!Number.isInteger(rounded)) word = 'года';
  else {
    const n = Math.abs(rounded) % 100;
    if (n % 10 === 1 && n !== 11) word = 'год';
    else if (n % 10 >= 2 && n % 10 <= 4 && (n < 12 || n > 14)) word = 'года';
  }
  return withUnit(fmt(rounded, Number.isInteger(rounded) ? 0 : 1), word);
}

const NUMBERED = { haul_truck: 'Самосвал', lhd: 'ПДМ', drill_rig: 'Буровая', plant_line: 'Линия', tailings_dam: 'Дамба' };

/** A name short enough for a label; the full name stays in the tooltip and the card. */
export function shortName(thingId, things) {
  const thing = things && things[thingId];
  if (!thing || !thing.name) return thingId.split(':').pop();
  const attrs = thing.attrs || {};
  const full = String(thing.name).replace(/\s*\([^)]*\)\s*$/, '');
  const number = /№\s*(\d+)/.exec(thing.name);
  if (NUMBERED[thing.kind] && number) return `${NUMBERED[thing.kind]} № ${number[1]}`;
  switch (thing.kind) {
    case 'level':
      return isNum(attrs.elevation_m) ? `Гор. ${elevationText(attrs.elevation_m)} м` : full;
    case 'decline':
      return full.replace(/^Транспортный уклон/, 'Уклон');
    case 'shaft': {
      const code = /ВС-\d+/.exec(full);
      return code ? `Ствол ${code[0]}` : full;
    }
    case 'raise':
      return full.replace(/^Вытяжные восстающие/, 'Восстающие');
    case 'main_fan': {
      const host = things[thing.parent];
      if (host && host.kind === 'level' && host.attrs && isNum(host.attrs.elevation_m)) {
        return `Вентилятор гор. ${elevationText(host.attrs.elevation_m)} м`;
      }
      const code = host && /(ВС-\d+|ВПВ|ВХВ[^(]*)/.exec(host.name || '');
      return code ? `Вентилятор ${code[1].trim()}` : full;
    }
    case 'pump_station':
      return isNum(attrs.elevation_m) ? `Насосная ${elevationText(attrs.elevation_m)} м` : full;
    case 'monitoring_point':
      return full.replace(/\s*№\s*\d+/, '').replace('ручей', 'руч.').replace('на реке', 'на р.');
    case 'plant':
      return 'Фабрика';
    case 'tailings_facility':
      return 'Хвостохранилище';
    case 'tailings_dam':
      return full.replace(/\s*хвостохранилища$/, '');
    default:
      return full;
  }
}

const unit = (value, digits, text) => withUnit(fmt(value, digits), text);

/** The one value shown next to the state in a label; '' when there is none. */
export function keyValue(thing, { gradeMode = false } = {}) {
  const f = (thing && thing.f) || {};
  if (f.state === 'planned' || f.state === 'parked') return '';
  switch (thing && thing.kind) {
    case 'stope':
      if (gradeMode && isNum(f.grade)) return unit(f.grade, 2, 'г/т');
      return isNum(f.ore_remaining_t) ? unit(f.ore_remaining_t / 1000, 1, 'тыс. т') : '';
    case 'haul_truck':
      if (!isNum(f.payload)) return '';
      if (f.payload > 0) return unit(f.payload, 0, 'т');
      return f.state === 'surface_haul' || f.state === 'tram_level' || f.state === 'queue_load' ? 'порожний' : '';
    case 'lhd':
      return isNum(f.tonnes_today) ? unit(f.tonnes_today, 0, 'т за сутки') : '';
    case 'drill_rig':
      return isNum(f.metres_today) ? unit(f.metres_today, 0, 'м за сутки') : '';
    case 'decline': {
      if (!isNum(f.trucks_on_ramp)) return '';
      const waiting = isNum(f.trucks_waiting_in_bays) && f.trucks_waiting_in_bays > 0
        ? `, ждут: ${fmt(f.trucks_waiting_in_bays)}` : '';
      return `на уклоне: ${fmt(f.trucks_on_ramp)}${waiting}`;
    }
    case 'shaft':
    case 'raise':
    case 'main_fan':
      return isNum(f.air_flow_m3s) ? unit(f.air_flow_m3s, 0, 'м³/с') : '';
    case 'level':
      if (!isNum(f.air_flow_m3s) || !isNum(f.air_required_m3s)) return '';
      return `воздух ${fmt(f.air_flow_m3s, 1)} из ${unit(f.air_required_m3s, 1, 'м³/с')}`;
    case 'pump_station':
      if ((f.state === 'failed' || f.state === 'alarm_high') && isNum(f.hours_to_overflow) && f.hours_to_overflow > 0) {
        return `до перелива ${unit(f.hours_to_overflow, 1, 'ч')}`;
      }
      return isNum(f.sump_level_pct) ? `водосборник ${unit(f.sump_level_pct, 0, '%')}` : '';
    case 'settling_pond':
      return isNum(f.inflow_m3h) ? unit(f.inflow_m3h, 0, 'м³/ч') : '';
    case 'monitoring_point':
      // A point with a discharge permit reports the discharge, the other one the intake.
      if (thing.attrs && isNum(thing.attrs.permit_m3h)) {
        return isNum(f.discharge_m3h) ? `сброс ${unit(f.discharge_m3h, 0, 'м³/ч')}` : '';
      }
      return isNum(f.intake_m3h) ? `водозабор ${unit(f.intake_m3h, 0, 'м³/ч')}` : '';
    case 'plant':
      return isNum(f.feed_tph) ? `питание ${unit(f.feed_tph, 1, 'т/ч')}` : '';
    case 'plant_line':
      return isNum(f.feed_tph) ? unit(f.feed_tph, 1, 'т/ч') : '';
    case 'rom_stockpile':
      return isNum(f.tonnes) ? unit(f.tonnes, 0, 'т') : '';
    case 'tailings_facility':
      return isNum(f.years_left) ? `осталось ${yearsText(f.years_left)}` : '';
    case 'tailings_dam':
      return isNum(f.fill_pct) ? unit(f.fill_pct, 0, '%') : '';
    default:
      return '';
  }
}

/** Second line of a label: «state · value». */
export function statusLine(thing, options) {
  const state = thingState(thing);
  const value = keyValue(thing, options);
  if (state.label === DASH) return { text: value || DASH, tone: state.tone };
  return { text: value ? `${state.label} · ${value}` : state.label, tone: state.tone };
}
