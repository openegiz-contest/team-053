// The one place where twin tokens become Russian text: states, kinds, links,
// feature and attribute names, units. Panels and both views import from here.

import { DASH, fmt, fmtTrim, digitsFor, isNum, withUnit } from './format.js';

export const NS = 'kz.sekis:';

// Tones drive colour and marker shape: ok, warn, fail, planned, idle, flood, info.
const STATES = {
  // common
  planned: ['проект', 'planned'],
  parked: ['на стоянке', 'idle'],
  running: ['в работе', 'ok'],
  failed: ['отказ', 'fail'],
  normal: ['норма', 'ok'],
  shift_break: ['пересменка', 'idle'],
  flooded: ['затопление', 'flood'],
  standby: ['в резерве', 'idle'],
  // mine
  production: ['добыча', 'ok'],
  blast_window: ['взрывные работы', 'info'],
  restricted_air: ['ограничение по воздуху', 'warn'],
  evacuation: ['эвакуация', 'fail'],
  // level
  ventilation: ['вентиляционный', 'info'],
  mined_out: ['отработан, заложен', 'idle'],
  development: ['проходка', 'info'],
  // stope
  preparation: ['подготовка', 'idle'],
  drilling: ['бурение', 'ok'],
  charging: ['заряжание', 'ok'],
  awaiting_blast: ['ожидает взрыва', 'warn'],
  ventilating: ['проветривание', 'info'],
  mucking: ['отгрузка руды', 'ok'],
  backfilling: ['закладка', 'idle'],
  // decline, airways
  open: ['открыт', 'ok'],
  closed: ['закрыт', 'fail'],
  in_service: ['в работе', 'ok'],
  // pump station
  idle: ['ожидание', 'idle'],
  pumping: ['откачка', 'ok'],
  alarm_high: ['высокий уровень воды', 'warn'],
  // monitoring point
  warning: ['близко к лимиту', 'warn'],
  exceeded: ['лимит превышен', 'fail'],
  // truck
  descending: ['спуск порожняком', 'ok'],
  waiting_bay: ['ждёт в разминовке', 'warn'],
  tram_level: ['движение по горизонту', 'ok'],
  queue_load: ['очередь на погрузку', 'ok'],
  loading: ['погрузка', 'ok'],
  hauling_up: ['подъём с рудой', 'ok'],
  surface_haul: ['на поверхности', 'ok'],
  dumping: ['разгрузка', 'ok'],
  held_vent: ['простой: нехватка воздуха', 'warn'],
  maintenance: ['ремонт', 'fail'],
  // LHD, rig
  loading_truck: ['грузит самосвал', 'ok'],
  standby_vent: ['простой: нехватка воздуха', 'warn'],
  tramming: ['переезд', 'ok'],
  // stockpile, plant, lines
  low: ['мало руды', 'warn'],
  empty: ['руды нет', 'fail'],
  starved: ['нет руды', 'warn'],
  water_limited: ['ограничение по воде', 'warn'],
  off: ['остановлена', 'idle'],
  // tailings
  ok: ['запас достаточен', 'ok'],
  short_horizon: ['запас менее трёх лет', 'warn'],
  full: ['заполнено', 'fail'],
  active: ['заполняется', 'ok'],
  // water system
  balanced: ['баланс', 'ok'],
  deficit: ['дефицит воды', 'warn'],
  discharge_over_permit: ['сброс выше разрешённого', 'fail'],
};

// Tokens whose meaning depends on the kind of the twin.
const STATES_BY_KIND = {
  pump_station: { idle: ['насосы ждут уровня', 'ok'] },
  lhd: { idle: ['ожидание', 'idle'], mucking: ['отгрузка руды', 'ok'] },
  plant_line: { maintenance: ['плановый ремонт', 'warn'], off: ['остановлена', 'idle'] },
  level: { production: ['добычной', 'ok'], development: ['проходка', 'info'] },
  tailings_dam: { standby: ['в резерве', 'idle'] },
  haul_truck: { maintenance: ['ремонт', 'fail'] },
};

function stateEntry(token, kind) {
  return (STATES_BY_KIND[kind] && STATES_BY_KIND[kind][token]) || STATES[token];
}

/** Russian label of a state token; an unknown token is shown as it is. */
export function stateLabel(token, kind) {
  if (token === undefined || token === null || token === '') return DASH;
  const entry = stateEntry(token, kind);
  return entry ? entry[0] : String(token);
}

/** Tone of a state token: ok | warn | fail | planned | idle | flood | info. */
export function stateTone(token, kind) {
  const entry = stateEntry(token, kind);
  return entry ? entry[1] : 'idle';
}

// The one palette of the stope production states, shared by the 3D scene and
// the long section (both legends list them in STOPE_ORDER). Hex strings; the
// colours of awaiting_blast, standby, planned and flooded equal the page tokens
// --warn, --idle, --planned and --flood (css/tokens.css). Orange --accent is
// reserved for the binding link and is not part of the palette.
export const STOPE_COLORS = {
  drilling: '#7ea2cf',
  charging: '#a493dc',
  awaiting_blast: '#f2dc5c',
  ventilating: '#c9d2dc',
  mucking: '#d9a53a',
  backfilling: '#a87650',
  standby: '#5d6c80',
  preparation: '#8698b0',
  flooded: '#58a6e6',
  planned: '#8796ab',
};
export const STOPE_ORDER = Object.keys(STOPE_COLORS);

/** Hex colour of a stope state; an unknown token gets the colour of standby. */
export function stopeColor(state) {
  return Object.prototype.hasOwnProperty.call(STOPE_COLORS, state)
    ? STOPE_COLORS[state] : STOPE_COLORS.standby;
}

// Wording of the ring around a vehicle (waiting or held: warn tone; maintenance:
// fail tone), the same in the legends of both views.
export const VEHICLE_MARKS = { held: 'ждёт или простаивает', repair: 'ремонт' };

export const KIND_RU = {
  enterprise: 'Предприятие', mine: 'Подземный рудник', level: 'Горизонт', stope: 'Очистной блок',
  decline: 'Транспортный уклон', shaft: 'Вентиляционный ствол', raise: 'Восстающий',
  main_fan: 'Главный вентилятор', pump_station: 'Насосная станция',
  settling_pond: 'Илоотстойник', monitoring_point: 'Пост мониторинга', haul_truck: 'Самосвал',
  lhd: 'ПДМ', drill_rig: 'Буровая установка', rom_stockpile: 'Рудный склад',
  plant: 'Обогатительная фабрика', plant_line: 'Технологическая линия',
  tailings_facility: 'Хвостовое хозяйство', tailings_dam: 'Дамба хвостохранилища',
  water_system: 'Водное хозяйство', scenario_control: 'Управляющий двойник сценария',
  advisor: 'Советник по расширению',
};

export function kindLabel(kind) {
  return KIND_RU[kind] || (kind ? String(kind) : DASH);
}

// The eight links ranked by the advisor, in tie-break order.
export const LINKS = ['haulage', 'ventilation', 'stopes', 'development', 'dewatering', 'plant',
  'water', 'tailings'];
export const LINK_RU = {
  haulage: 'Откатка', ventilation: 'Вентиляция', stopes: 'Очистные блоки',
  development: 'Проходка', dewatering: 'Водоотлив', plant: 'Фабрика', water: 'Водоснабжение',
  tailings: 'Хвостохранилище',
};

export function linkLabel(link) {
  return LINK_RU[link] || (link ? String(link) : DASH);
}

// Measure knobs: name and what each stage means.
export const MEASURES = [
  { knob: 'm_plant', link: 'plant', name: 'Фабрика', design: [1000, 1200, 2000, 2500], unit: 'тыс. т/год',
    stages: ['1 000 тыс. т/год', '1 200 тыс. т/год', '2 000 тыс. т/год, линии № 4–5', '2 500 тыс. т/год, линия № 6'] },
  { knob: 'm_haul', link: 'haulage', name: 'Откатка',
    stages: ['5 самосвалов', '7 самосвалов', '10 самосвалов', '12 самосвалов'] },
  { knob: 'm_stopes', link: 'stopes', name: 'Очистные блоки',
    stages: ['4 блока, 4 ПДМ, 2 буровые', '5 блоков, 5 ПДМ, 3 буровые', '8 блоков, 8 ПДМ, 4 буровые', '10 блоков, 10 ПДМ, 5 буровых'] },
  { knob: 'm_vent', link: 'ventilation', name: 'Вентиляция', design: [322, 427, 667], unit: 'м³/с',
    stages: ['322 м³/с', '427 м³/с, вентилятор ВПВ', '667 м³/с, ствол ВС-3'] },
  { knob: 'm_dev', link: 'development', name: 'Проходка',
    stages: ['34 м глубины в год', '50 м глубины в год'] },
  { knob: 'm_water', link: 'water', name: 'Водоснабжение',
    stages: ['без оборота', 'оборот воды из хвостов', 'оборот и водозабор 150 м³/ч'] },
  { knob: 'm_tailings', link: 'tailings', name: 'Хвостохранилище',
    stages: ['действующие дамбы', 'новая карта, 6,0 млн т'] },
];

const NEXT_MEASURE = {
  none: 'не требуется', '': DASH, restore_pumps: 'восстановить насосы гор. +150 м',
};
for (const measure of MEASURES) NEXT_MEASURE[measure.knob] = measure.name.toLowerCase();

const SHIFT_RU = { A: 'Смена А', B: 'Смена Б', blast: 'Взрывные работы' };
// mine.vod_state: ventilation on demand (spec 3.5).
export const VOD_STATE = {
  off: 'выключена: вентиляторы на проектном режиме',
  demand: 'по потребности',
  ramp: 'набор подачи',
  full: 'полная подача: нужна вся',
};
const TOKENS_BY_FEATURE = {
  shift: SHIFT_RU,
  decline: { tu1: 'ТУ-1', tu2: 'ТУ-2', none: DASH },
  next_measure: NEXT_MEASURE,
  vod_state: VOD_STATE,
};
const TOKENS_BY_ATTR = {
  direction: { intake: 'подача свежего воздуха', exhaust: 'исходящая струя' },
  commissioned: { existing: 'действующая', planned: 'проект', '2024-12': 'декабрь 2024 г.' },
  model: { unspecified: 'не указана' },
  _isType: { true: 'да', false: 'нет' },
};

export function shiftLabel(token) {
  return SHIFT_RU[token] || DASH;
}

export const FEATURE_RU = {
  state: 'Состояние', sim_time: 'Время симуляции', sim_day: 'Сутки симуляции', shift: 'Смена',
  ore_mined_tpd: 'Выдача руды за 24 ч', ore_milled_tpd: 'Переработка руды за 24 ч',
  gold_poured_oz_day: 'Выплавка золота', gold_poured_total_oz: 'Золото с начала симуляции',
  annual_rate_ktpa: 'Расчётная мощность по советнику (не замер)', binding_link: 'Узкое место',
  ore_hoisted_tph: 'Выдача руды, среднее за 24 ч', ore_hoisted_today_t: 'Выдано руды с 08:00',
  ore_hoisted_total_t: 'Выдано руды всего', trucks_active: 'Самосвалов в рейсе',
  diesel_kw_active: 'Дизельная мощность в работе', air_supply_m3s: 'Располагаемая подача воздуха',
  air_demand_m3s: 'Потребность в воздухе', air_margin_pct: 'Запас по воздуху',
  units_held_vent: 'Машин ждут воздуха', inflow_m3h: 'Приток воды',
  vod_state: 'Вентиляция по потребности', air_delivered_m3s: 'Подаётся воздуха сейчас',
  vod_demand_m3s: 'Потребность машин в работе (с базовой)', vod_units_waiting: 'Ждут набора подачи',
  fan_power_kw: 'Мощность главных вентиляторов', fan_energy_today_kwh: 'Энергия вентиляторов с 08:00',
  fan_saving_today_kwh: 'Экономия энергии с 08:00', fan_saving_today_kzt: 'Экономия с 08:00, тенге',
  fan_energy_shift_kwh: 'Энергия вентиляторов за смену', fan_saving_shift_kwh: 'Экономия энергии за смену',
  fan_energy_day_kwh: 'Энергия вентиляторов за 24 ч', fan_saving_day_kwh: 'Экономия энергии за 24 ч',
  duty_setpoint_m3s: 'Уставка расхода', vod_enabled: 'Вентиляция по потребности включена',
  pumped_m3h: 'Откачка', flood_volume_m3: 'Объём затопления', air_flow_m3s: 'Расход воздуха',
  air_required_m3s: 'Требуемый расход воздуха', diesel_kw: 'Дизельная мощность на горизонте',
  water_inflow_m3h: 'Приток воды', active_stopes: 'Блоков в работе', ore_today_t: 'Руды с 08:00',
  ore_remaining_t: 'Остаток руды в блоке', broken_ore_t: 'Отбитая руда', drilled_pct: 'Обурено',
  backfill_pct: 'Закладка', grade: 'Содержание золота', mucked_today_t: 'Отгружено с 08:00',
  block_no: 'Номер блока', bottom_elevation: 'Отметка забоя',
  trucks_on_ramp: 'Самосвалов на уклоне', trucks_waiting_in_bays: 'Ждут в разминовках',
  loaded_trips_today: 'Гружёных рейсов с 08:00', avg_cycle_min: 'Средний цикл рейса',
  air_velocity_ms: 'Скорость воздуха', pressure: 'Давление', power_kw: 'Потребляемая мощность',
  sump_level_pct: 'Уровень в водосборнике', pumps_running: 'Насосов в работе',
  pumps_available: 'Насосов исправно', hours_to_overflow: 'До переполнения', payload: 'Груз',
  flood_eta_min: 'До затопления следующего горизонта (мин на стенде)',
  minutes_to_permit: 'До превышения разрешения на сброс (мин на стенде)',
  speed: 'Скорость', decline: 'Уклон', chainage_m: 'Расстояние от портала', elevation: 'Отметка',
  pos_x: 'Координата X', pos_y: 'Координата Y', pos_z: 'Координата Z',
  trips_today: 'Рейсов с 08:00', tonnes_today: 'Тонн с 08:00', stope: 'Очистной блок',
  metres_today: 'Пробурено с 08:00', mine_water_m3h: 'Шахтная вода',
  site_use_m3h: 'Расход на площадке', plant_supply_m3h: 'Подача на фабрику',
  reclaim_m3h: 'Оборотная вода', extra_intake_m3h: 'Дополнительный водозабор',
  deficit_m3h: 'Дефицит воды', discharge_m3h: 'Сброс', retention_h: 'Время отстаивания',
  tss_in_mgl: 'Взвешенные вещества на входе', tss_out_mgl: 'Взвешенные вещества на выходе',
  sludge_t_year: 'Осадок', intake_m3h: 'Водозабор', tss_mgl: 'Взвешенные вещества',
  permit_use_pct: 'Использование разрешения', feed_tph: 'Питание',
  feed_grade: 'Содержание в питании', recovery_pct: 'Извлечение', capacity_ktpa: 'Мощность',
  lines_running: 'Линий в работе', water_demand_m3h: 'Потребность в воде',
  tailings_tph: 'Выход хвостов', tonnes: 'Запас руды', inflow_tph: 'Поступление руды',
  outflow_tph: 'Выдача на фабрику', days_of_feed: 'Запас в сутках питания',
  utilisation_pct: 'Загрузка', milled_today_t: 'Переработано с 08:00',
  stored_t: 'Накоплено хвостов', free_capacity_t: 'Свободная ёмкость',
  inflow_tpd: 'Поступление хвостов за 24 ч', years_left: 'Лет до заполнения', fill_pct: 'Заполнение',
  target_ktpa: 'Цель переработки', m_plant: 'Мера: фабрика', m_haul: 'Мера: откатка',
  m_stopes: 'Мера: очистные блоки', m_vent: 'Мера: вентиляция', m_dev: 'Мера: проходка',
  m_water: 'Мера: водоснабжение', m_tailings: 'Мера: хвостохранилище',
  tu1_closed: 'Уклон ТУ-1 закрыт', tu2_closed: 'Уклон ТУ-2 закрыт',
  fan_vs2_off: 'Вентилятор ВС-2 отключён', pumps_failed_p150: 'Отказавших насосов, гор. +150 м',
  inflow_factor: 'Коэффициент притока воды', grade_gpt: 'Среднее содержание золота',
  line_down: 'Остановленная линия фабрики', revision: 'Ревизия сценария',
  label: 'Название сценария', next_measure: 'Следующая мера', measures_needed: 'Осталось мер',
  achievable_ktpa: 'Достижимая производительность', cap_haulage_ktpa: 'Откатка',
  cap_ventilation_ktpa: 'Вентиляция', cap_stopes_ktpa: 'Очистные блоки',
  cap_development_ktpa: 'Проходка', cap_dewatering_ktpa: 'Водоотлив',
  dewatering_margin: 'Запас производительности насосов', cap_plant_ktpa: 'Фабрика',
  cap_water_ktpa: 'Водоснабжение', cap_tailings_ktpa: 'Хвостохранилище',
  gold_koz_year: 'Золото за год', gold_gain_koz_year: 'Прирост золота',
  water_deficit_m3h: 'Дефицит воды', tailings_years_left: 'Запас хвостохранилищ',
  stockpile_days_left: 'Запас рудного склада', report_revision: 'Ревизия отчёта',
};

export const ATTR_RU = {
  name: 'Название', _isType: 'Это тип', kind: 'Вид', type: 'Тип-двойник', _parents: 'Родитель',
  operator: 'Оператор', location: 'Местоположение', coordinates: 'Координаты',
  design_capacity_ktpa: 'Проектная мощность', working_days: 'Рабочих дней в году',
  shifts: 'Смен в сутки', shift_h: 'Длительность смены', elevation_m: 'Отметка',
  role: 'Назначение', block: 'Блок', ore_initial_t: 'Начальный запас руды',
  grade_gpt: 'Содержание золота', sublevel_m: 'Высота подэтажа',
  portal_elevation_m: 'Отметка портала', design_bottom_m: 'Проектная отметка дна',
  slope_deg: 'Уклон', section_m2: 'Сечение', length_m: 'Длина',
  top_elevation_m: 'Верхняя отметка', bottom_elevation_m: 'Нижняя отметка',
  direction: 'Направление струи', model: 'Модель', duty_m3s: 'Производительность',
  duty_min_m3s: 'Наименьшая производительность', duty_max_m3s: 'Наибольшая производительность',
  pressure_pa: 'Давление',
  pumps_total: 'Насосов всего', pumps_working: 'Рабочих насосов',
  pump_capacity_m3h: 'Производительность насоса', sump_volume_m3: 'Объём водосборника',
  payload_t: 'Грузоподъёмность', engine_kw: 'Мощность двигателя', bucket_t: 'Ковш',
  volume_m3: 'Объём', area_m2: 'Площадь', depth_m: 'Глубина', water_body: 'Водный объект',
  permit_m3h: 'Разрешённый сброс', permit_ref: 'Разрешение',
  nameplate_ktpa: 'Паспортная мощность', rated_tph: 'Номинальное питание',
  commissioned: 'Ввод в работу', area_km2: 'Площадь', capacity_t: 'Ёмкость',
  capacity_m3: 'Ёмкость по объёму', bulk_density: 'Насыпная плотность хвостов',
};

export const LINK_ATTR_RU = {
  link_level: 'Горизонт', link_ore_route: 'Руда выдаётся по уклонам',
  link_declines: 'Уклоны горизонта', link_drains_to: 'Вода стекает к станции',
  link_air_intake: 'Свежий воздух поступает по', link_air_exhaust: 'Исходящая струя уходит по',
  link_levels: 'Обслуживаемые горизонты', link_portal_to: 'Руда с портала идёт на',
  link_fan: 'Вентилятор', link_airway: 'Выработка', link_discharges_to: 'Откачка идёт в',
  link_overflows_to: 'Перелив идёт в', link_home_decline: 'Закреплён за уклоном',
  link_feeds: 'Питает линии', link_tailings_to: 'Хвосты уходят в',
  link_water_from: 'Вода поступает из', link_active_dam: 'Заполняемая дамба',
  link_ponds: 'Илоотстойники', link_points: 'Посты мониторинга',
};

// Features whose meaning differs between kinds of twin (the same id, another basis).
const FEATURE_RU_BY_KIND = {
  mine: { air_demand_m3s: 'Потребность парка на полной нагрузке (без ждущих воздуха)' },
  advisor: { air_demand_m3s: 'Потребность всего парка в воздухе' },
  enterprise: { gold_poured_oz_day: 'Выплавка золота за 24 ч' },
  plant: { gold_poured_oz_day: 'Выплавка золота, темп последних 2 ч', feed_tph: 'Питание сейчас' },
  plant_line: { feed_tph: 'Питание сейчас' },
};

/** Russian name of a feature; `kind` picks the wording where the basis differs by kind. */
export function featureLabel(id, kind) {
  const byKind = kind && FEATURE_RU_BY_KIND[kind];
  return (byKind && byKind[id]) || FEATURE_RU[id] || id;
}

export function attrLabel(id) {
  return ATTR_RU[id] || LINK_ATTR_RU[id] || id;
}

const UNIT_RU = {
  '': '', '-': '', 't': 'т', 't/h': 'т/ч', 't/d': 'т/сут', 't/yr': 'т/год', 'kt/yr': 'тыс. т/год',
  'oz': 'унц.', 'oz/d': 'унц./сут', 'oz/yr': 'унц./год', 'koz/yr': 'тыс. унц./год', 'g/t': 'г/т',
  'g/oz': 'г/унц.', 'm': 'м', 'km': 'км', 'm2': 'м²', 'm3': 'м³', 'm3/s': 'м³/с', 'm3/h': 'м³/ч',
  'm3/t': 'м³/т', 'm/s': 'м/с', 'km/h': 'км/ч', 'kW': 'кВт', 'Pa': 'Па', '%': '%', 'h': 'ч',
  'min': 'мин', 's': 'с', 'day': 'сут', 'days': 'сут', 'years': 'лет', 'units': 'ед.',
  'trips': 'рейсов', 'mg/l': 'мг/л', 'stage': 'ступень', 'flag': '', 'pumps': 'шт.',
  'factor': 'крат', 'line no.': '№ линии', 'steps': 'мер', 'ratio': 'крат', 'deg': '°',
  't/m3': 'т/м³', 'kg/m3': 'кг/м³', 'm/s2': 'м/с²', 'fraction': 'доля', 'stopes': 'блоков',
  'shifts': 'смен', 'shifts/day': 'смен/сут', 'days/yr': 'сут/год', 'h of day': 'ч суток',
  'h per day': 'ч/сут', 'simulated s per real s': 'с модели за 1 с', 'simulated s': 'с модели',
  'real s': 'с', 'simulated h': 'ч модели', 'simulated days': 'сут модели', 'ISO 8601': '',
  'm of elevation': 'м по высоте', 'slots per node': 'мест на узел',
  'productive shifts': 'продуктивных смен', 'm of depth/yr': 'м глубины/год',
  't per m of depth': 'т на 1 м глубины', 'min per extra truck on the decline': 'мин на самосвал',
  'm3/s per kW': 'м³/с на 1 кВт', '% sump level': '% уровня', 'thousand m3/yr': 'тыс. м³/год',
  'kWh': 'кВт·ч', 'KZT': '₸', 'KZT/kWh, excl. VAT': '₸/кВт·ч без НДС', 'share of duty_m3s': 'доля проектной',
  'share of vent.q_base': 'доля базовой', '% of the air demand': '% потребности',
  '% of duty_m3s per minute': '% проектной в минуту', 'x mine clock': 'раз быстрее часов рудника',
  '% of permit': '% разрешения', 'm3/t milled': 'м³/т', '% per g/t': '% на 1 г/т',
  't each': 'т каждая', 'messages/s': 'сообщ./с', 'percentage points': 'п.п.',
  '% of reported': '% отчёта', 'share of the baseline fleet power': 'доля мощности парка',
  'producing stopes per drill rig': 'блоков на установку',
  'active trucks by stage of m_haul': 'самосвалов по ступеням',
  'producing stopes by stage of m_stopes': 'блоков по ступеням',
  'active LHDs by stage of m_stopes': 'ПДМ по ступеням',
  'drill rigs in service by stage of m_stopes': 'буровых по ступеням',
  'names of the running main fans by stage of m_vent': 'вентиляторы по ступеням',
  'kt/yr by stage of m_plant': 'тыс. т/год по ступеням',
  'plant lines in service by stage of m_plant': 'линий по ступеням',
  'm of depth/yr by stage of m_dev': 'м глубины/год по ступеням',
  'm3/t milled by stage of m_water': 'м³/т по ступеням',
  'm3/h by stage of m_water': 'м³/ч по ступеням',
  'names of the built tailings dams in fill order, by stage of m_tailings': 'дамбы по ступеням',
};

/** Russian unit for a unit string of the registry or the parameter file. */
export function unitLabel(unit) {
  if (unit === undefined || unit === null) return '';
  return Object.prototype.hasOwnProperty.call(UNIT_RU, unit) ? UNIT_RU[unit] : String(unit);
}

// Units of attributes are read from the suffix of the attribute id.
const ATTR_SUFFIX_UNITS = [
  ['_ktpa', 'тыс. т/год'], ['_m3h', 'м³/ч'], ['_m3s', 'м³/с'], ['_km2', 'км²'], ['_tph', 'т/ч'],
  ['_gpt', 'г/т'], ['_deg', '°'], ['_m2', 'м²'], ['_m3', 'м³'], ['_kw', 'кВт'], ['_pa', 'Па'],
  ['_m', 'м'], ['_t', 'т'], ['_h', 'ч'],
];

export function attrUnit(id) {
  if (id === 'bulk_density') return 'т/м³';
  const found = ATTR_SUFFIX_UNITS.find(([suffix]) => id.endsWith(suffix));
  return found ? found[1] : '';
}

const FEATURE_DIGITS = {
  sim_day: 1, grade: 2, feed_grade: 2, grade_gpt: 2, recovery_pct: 2, inflow_factor: 2,
  dewatering_margin: 2, gold_koz_year: 1, gold_gain_koz_year: 1, tailings_years_left: 1,
  years_left: 1, air_margin_pct: 1, tss_out_mgl: 2, tss_mgl: 2, tss_in_mgl: 3,
  hours_to_overflow: 1, retention_h: 1, avg_cycle_min: 1, air_velocity_ms: 1, flood_eta_min: 1, minutes_to_permit: 1,
  air_demand_m3s: 1, air_flow_m3s: 1, air_required_m3s: 1, feed_tph: 1, days_of_feed: 0,
  air_delivered_m3s: 1, vod_demand_m3s: 1, duty_setpoint_m3s: 1, fan_power_kw: 0, fan_energy_today_kwh: 0,
  fan_saving_today_kwh: 0, fan_saving_today_kzt: 0, fan_energy_shift_kwh: 0, fan_saving_shift_kwh: 0,
  fan_energy_day_kwh: 0, fan_saving_day_kwh: 0,
};
const FLAG_FEATURES = new Set(['tu1_closed', 'tu2_closed', 'fan_vs2_off', 'vod_enabled']);
const REFERENCE_FEATURES = new Set(['stope']);

/**
 * Text of a feature value. `things` (the state's things map) lets a reference
 * such as stope = 'stp-p150-1' be shown by the Russian name of that twin.
 */
export function featureText(id, value, { kind, unit, things } = {}) {
  if (value === undefined || value === null || value === '') return DASH;
  if (id === 'state') return stateLabel(value, kind);
  if (id === 'binding_link') return linkLabel(value).toLowerCase();
  if (TOKENS_BY_FEATURE[id]) return TOKENS_BY_FEATURE[id][value] || String(value);
  if (FLAG_FEATURES.has(id)) return value ? 'да' : 'нет';
  if (REFERENCE_FEATURES.has(id)) {
    if (value === 'none') return DASH;
    const thing = things && things[NS + value];
    return thing && thing.name ? thing.name : String(value);
  }
  if (id === 'sim_time' && typeof value === 'string') return value.replace('T', ' ');
  if (isNum(value)) {
    const digits = id in FEATURE_DIGITS ? FEATURE_DIGITS[id] : Math.min(1, digitsFor(value));
    return withUnit(fmt(value, digits), unitLabel(unit));
  }
  return String(value);
}

/** Text of an attribute value (numbers, tokens, arrays of numbers). */
export function attrText(id, value) {
  if (value === undefined || value === null || value === '') return DASH;
  if (id === 'role') return stateLabel(value, 'level');
  if (id === 'kind') return kindLabel(value);
  if (TOKENS_BY_ATTR[id] && TOKENS_BY_ATTR[id][String(value)] !== undefined) {
    return TOKENS_BY_ATTR[id][String(value)];
  }
  if (isNum(value)) return withUnit(fmtTrim(value), attrUnit(id));
  if (Array.isArray(value) && value.every(isNum)) {
    return withUnit(value.map((v) => fmtTrim(v)).join('–'), attrUnit(id));
  }
  if (typeof value === 'boolean') return value ? 'да' : 'нет';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

// Two or three values that say the most about a twin of each kind (twin table).
export const KEY_FEATURES = {
  enterprise: ['ore_mined_tpd', 'ore_milled_tpd', 'gold_poured_oz_day'],
  mine: ['ore_hoisted_tph', 'air_margin_pct', 'trucks_active'],
  level: ['air_flow_m3s', 'active_stopes', 'water_inflow_m3h'],
  stope: ['ore_remaining_t', 'broken_ore_t', 'grade'],
  decline: ['trucks_on_ramp', 'trucks_waiting_in_bays', 'ore_today_t'],
  shaft: ['air_flow_m3s', 'air_velocity_ms'],
  raise: ['air_flow_m3s', 'air_velocity_ms'],
  main_fan: ['air_flow_m3s', 'power_kw'],
  pump_station: ['sump_level_pct', 'pumped_m3h', 'pumps_available'],
  settling_pond: ['inflow_m3h', 'retention_h', 'tss_out_mgl'],
  monitoring_point: ['discharge_m3h', 'intake_m3h', 'permit_use_pct'],
  haul_truck: ['payload', 'elevation', 'trips_today'],
  lhd: ['stope', 'tonnes_today'],
  drill_rig: ['stope', 'metres_today'],
  rom_stockpile: ['tonnes', 'grade', 'days_of_feed'],
  plant: ['feed_tph', 'recovery_pct', 'gold_poured_oz_day'],
  plant_line: ['feed_tph', 'utilisation_pct'],
  tailings_facility: ['free_capacity_t', 'years_left', 'inflow_tpd'],
  tailings_dam: ['fill_pct', 'free_capacity_t'],
  water_system: ['mine_water_m3h', 'deficit_m3h', 'discharge_m3h'],
  scenario_control: ['target_ktpa', 'revision', 'label'],
  advisor: ['binding_link', 'achievable_ktpa', 'next_measure'],
};

/** Feature that carries the state of a twin, or a stand-in for twins without one. */
export function thingState(thing) {
  if (!thing || !thing.f) return { label: DASH, tone: 'idle' };
  if (typeof thing.f.state === 'string') {
    return { label: stateLabel(thing.f.state, thing.kind), tone: stateTone(thing.f.state, thing.kind) };
  }
  if (thing.kind === 'enterprise') return { label: shiftLabel(thing.f.shift), tone: 'info' };
  if (thing.kind === 'advisor' && thing.f.binding_link) {
    return { label: 'узкое место: ' + linkLabel(thing.f.binding_link).toLowerCase(), tone: 'accent' };
  }
  if (thing.kind === 'scenario_control' && isNum(thing.f.revision)) {
    return { label: 'ревизия ' + fmt(thing.f.revision), tone: 'info' };
  }
  return { label: DASH, tone: 'idle' };
}

// ------------------------------------------------------------ counts of units

/** Russian plural form: plural(2, ['машина', 'машины', 'машин']) -> 'машины'. */
export function plural(n, [one, few, many]) {
  const k = Math.abs(Math.round(n)) % 100;
  if (k % 10 === 1 && k !== 11) return one;
  if (k % 10 >= 2 && k % 10 <= 4 && (k < 12 || k > 14)) return few;
  return many;
}

/** '2 машины', '1 самосвал', '5 ПДМ'. */
export function countText(n, forms) {
  return `${fmt(n)} ${plural(n, forms)}`;
}

export const FORMS = {
  unit: ['машина', 'машины', 'машин'],
  truck: ['самосвал', 'самосвала', 'самосвалов'],
  lhd: ['ПДМ', 'ПДМ', 'ПДМ'],
};

const OFF_FLEET = new Set(['parked', 'planned']);
const HELD = new Set(['held_vent', 'standby_vent']);

/**
 * The one definition of the truck and LHD counts shown on the page, read from
 * the states of the unit twins:
 *   fleet       trucks of the present stage of m_haul (not parked, not planned);
 *   inService   «самосвалов в работе»: the fleet less the trucks in maintenance;
 *   held        trucks in service that wait for air (held_vent);
 *   onTrip      «в рейсе»: in service and not waiting for air (= mine.trucks_active);
 *   maintenance trucks under repair; lhdHeld: LHDs waiting for air (standby_vent);
 *   heldUnits   trucks and LHDs waiting for air (= mine.units_held_vent).
 */
export function unitCounts(things) {
  const c = { fleet: 0, inService: 0, held: 0, onTrip: 0, maintenance: 0, lhdHeld: 0, heldUnits: 0, heldTrucks: [], heldLhds: [] };
  let seen = false;
  for (const [id, thing] of Object.entries(things || {})) {
    const state = thing && thing.f && thing.f.state;
    if (typeof state !== 'string') continue;
    const number = id.replace(/^.*-0*/, '');
    if (thing.kind === 'haul_truck') {
      seen = true;
      if (OFF_FLEET.has(state)) continue;
      c.fleet += 1;
      if (state === 'maintenance') c.maintenance += 1;
      else if (HELD.has(state)) { c.held += 1; c.heldTrucks.push(number); }
    } else if (thing.kind === 'lhd' && HELD.has(state)) {
      c.lhdHeld += 1;
      c.heldLhds.push(number);
    }
  }
  c.inService = c.fleet - c.maintenance;
  c.onTrip = c.inService - c.held;
  c.heldUnits = c.held + c.lhdHeld;
  if (!seen) {   // no unit twins yet: fall back to the mine twin
    const mine = (things && things[NS + 'mine'] && things[NS + 'mine'].f) || {};
    c.onTrip = isNum(mine.trucks_active) ? mine.trucks_active : null;
    c.heldUnits = isNum(mine.units_held_vent) ? mine.units_held_vent : 0;
    c.fleet = c.inService = null;
  }
  return c;
}

/** «самосвалы № 6, 7 и ПДМ № 4»: which units wait for air. */
export function heldUnitsText(counts) {
  const parts = [];
  if (counts.heldTrucks.length) parts.push(`${counts.heldTrucks.length > 1 ? 'самосвалы' : 'самосвал'} № ${counts.heldTrucks.join(', ')}`);
  if (counts.heldLhds.length) parts.push(`ПДМ № ${counts.heldLhds.join(', ')}`);
  return parts.join(' и ');
}

/**
 * Air of the mine as the page states it. The air now is `delivered`
 * (mine.air_delivered_m3s, what the main fans deliver under ventilation on demand)
 * against `inWork` (mine.vod_demand_m3s, the demand of the units in work now; in a
 * blast window or between the blocks only the base demand). The design figures of
 * the hold rule are named apart: `supply` (mine.air_supply_m3s, the fans at their
 * design duty), `workingDemand` (mine.air_demand_m3s, every unit not held at full
 * work) and «потребность всего парка» `fleetDemand` (the advisor's demand of every
 * unit in service). Without the ventilation-on-demand features (an older state)
 * the delivered air falls back to the supply and the demand in work to
 * workingDemand. `short` is true while any unit waits for air or the mine is
 * restricted_air.
 */
export function airStatus(things, advisor) {
  const mine = (things && things[NS + 'mine'] && things[NS + 'mine'].f) || {};
  const counts = unitCounts(things);
  const held = counts.heldUnits || (isNum(mine.units_held_vent) ? mine.units_held_vent : 0);
  const fleetDemand = advisor && advisor.kpi && isNum(advisor.kpi.airDemand) ? advisor.kpi.airDemand : null;
  const supply = isNum(mine.air_supply_m3s) ? mine.air_supply_m3s : null;
  const workingDemand = isNum(mine.air_demand_m3s) ? mine.air_demand_m3s : null;
  return {
    short: held > 0 || mine.state === 'restricted_air',
    held,
    counts,
    supply,
    workingDemand,
    fleetDemand,
    delivered: isNum(mine.air_delivered_m3s) ? mine.air_delivered_m3s : supply,
    inWork: isNum(mine.vod_demand_m3s) ? mine.vod_demand_m3s : workingDemand,
    vod: typeof mine.vod_state === 'string' ? mine.vod_state : null,
    margin: isNum(mine.air_margin_pct) ? mine.air_margin_pct : null,
  };
}
