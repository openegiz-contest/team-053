"""Russian wording of the Expansion Advisor: link names, numbers, measures, effects.

Everything a person reads in the advisor report is produced here. The functions take values
that ``sekis.capacity`` computed (or parameters and thing names of the model files) and put
them into words; no figure is invented in this module. Standard library only.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from .. import capacity as cap

NBSP = "\u00a0"    # thousands separator, and the gap after the number sign
MINUS = "\u2212"
DASH = "\u2013"    # number ranges
EM_DASH = "\u2014" # between the parts of a sentence
ARROW = "\u2192"   # before -> after
NO_VALUE = EM_DASH

#: Link -> name on the Stand.
LINK_RU: Dict[str, str] = {
    "haulage": "Откатка",
    "ventilation": "Вентиляция",
    "stopes": "Очистные блоки",
    "development": "Проходка",
    "dewatering": "Водоотлив",
    "plant": "Фабрика",
    "water": "Водоснабжение",
    "tailings": "Хвостохранилище",
}

U_KTPA = "тыс. т/год"
U_KOZ = "тыс. унц./год"
U_M3S = "м³/с"
U_M3H = "м³/ч"
U_GPT = "г/т"
U_YEARS = "года"     # used with one decimal: «3,4 года»
U_DAYS = "сут"

BETTER, WORSE, NEUTRAL = "better", "worse", "neutral"


def num(value: Optional[float], digits: int = 0) -> str:
    """Russian number: no-break space between thousands, comma as the decimal mark."""
    if value is None:
        return NO_VALUE
    rounded = round(float(value), digits)
    text = f"{abs(rounded):,.{digits}f}".replace(",", NBSP).replace(".", ",")
    return (MINUS if rounded < 0 else "") + text


def link_name(link: str) -> str:
    return LINK_RU[link]


def link_lower(link: str) -> str:
    return LINK_RU[link].lower()


def numbers(values: Sequence[int]) -> str:
    """Unit numbers after the number sign: «№ 6», «№ 6–7»."""
    values = sorted(values)
    if not values:
        return ""
    if len(values) == 1:
        return f"№{NBSP}{values[0]}"
    if values == list(range(values[0], values[-1] + 1)):
        return f"№{NBSP}{values[0]}{DASH}{values[-1]}"
    return f"№{NBSP}" + ", ".join(str(v) for v in values)


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:]


def _names(names: Mapping[str, str], things: Iterable[str]) -> str:
    """Registry names of things inside a sentence: lower-case start, no bracketed remark."""
    return ", ".join(_lower_first(re.sub(r"\s*\([^)]*\)", "", names.get(thing, thing))) for thing in things)


def _decline_label(names: Mapping[str, str], key: str) -> str:
    """«ТУ-1» from the registry name «Транспортный уклон ТУ-1»."""
    name = names.get(f"decline-{key}")
    return name.split()[-1] if name else key.upper()


def _unit_numbers(units: Iterable[str]) -> List[int]:
    return [int(str(unit).rsplit("-", 1)[-1]) for unit in units]


def held_phrase(trucks: Iterable[str], lhds: Iterable[str]) -> str:
    """Units that wait for air, by number: «самосвалы № 6–7», «самосвалы № 3–5 и ПДМ № 4».

    Empty when nothing is held. The phrase is in the nominative, for use after a colon.
    """
    truck_numbers, lhd_numbers = _unit_numbers(trucks), _unit_numbers(lhds)
    parts = []
    if truck_numbers:
        parts.append(f"{'самосвал' if len(truck_numbers) == 1 else 'самосвалы'} {numbers(truck_numbers)}")
    if lhd_numbers:
        parts.append(f"ПДМ {numbers(lhd_numbers)}")
    return " и ".join(parts)


def _held(air: cap.Air) -> str:
    return held_phrase(air.held_trucks, air.held_lhds)


def flooded_phrase(names: Mapping[str, str], levels: Sequence[str]) -> str:
    """«затоплен горизонт −50 м» / «затоплены горизонты 0 м, −50 м» from the registry names."""
    marks = [names.get(level, level).replace("Горизонт ", "", 1) for level in levels]
    if len(marks) == 1:
        return f"затоплен горизонт {marks[0]}"
    return "затоплены горизонты " + ", ".join(marks)


def _plural(count: int, one: str, few: str, many: str) -> str:
    """Russian noun form after a whole number: 1 насос, 2 насоса, 5 насосов."""
    if count % 10 == 1 and count % 100 != 11:
        return one
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return few
    return many


def reserve_phrase(dewatering: cap.Dewatering) -> str:
    """Standby of the main pumping station: «резерв: 1 насос», or «резерва нет: при отказе ещё
    одного насоса ×1,27» once a failed pump has used the standby up."""
    if dewatering.standby_pumps > 0:
        count = dewatering.standby_pumps
        return f"резерв: {count} {_plural(count, 'насос', 'насоса', 'насосов')}"
    return f"резерва нет: при отказе ещё одного насоса ×{num(dewatering.margin_next_failure, 2)}"


def decline_label(names: Mapping[str, str], key: str) -> str:
    """«ТУ-1» from the registry name «Транспортный уклон ТУ-1»."""
    return _decline_label(names, key)


# --- the state of each link ------------------------------------------------------------------

def link_detail(model: cap.Model, names: Mapping[str, str], link: str, res: cap.Result) -> str:
    """One line on what stands behind the capacity of a link in the evaluated state."""
    state = res.state
    if link == "haulage":
        by_decline = ", ".join(f"{_decline_label(names, key)}: {count}"
                               for key, count in res.haulage.trucks_by_decline.items())
        return f"парк самосвалов: {len(res.haulage.cycles)} ({by_decline})"
    if link == "ventilation":
        air = res.air
        text = (f"подача воздуха {num(air.supply_m3s)} {U_M3S}, "
                f"потребность парка {num(air.demand_m3s, 1)} {U_M3S}")
        if air.restricted:      # whole units wait; the units left working need less than is supplied
            return (f"{text}; в ожидании воздуха: {_held(air)}; работающей технике нужно "
                    f"{num(air.used_m3s, 1)} {U_M3S}")
        return f"{text}, запас {num(air.spare_m3s, 1)} {U_M3S}"
    if link == "stopes":
        return (f"очистных блоков в работе: {res.stopes.n_producing}, ПДМ: {res.stopes.lhds}, "
                f"буровых установок: {res.stopes.rigs}")
    if link == "development":
        return f"проходка уклонов {num(res.dev_advance_vm_per_year)} м по вертикали в год"
    if link == "dewatering":
        text = f"запас производительности насосов ×{num(res.dewatering.margin, 2)}; {reserve_phrase(res.dewatering)}"
        if res.dewatering.flooded_levels:
            text += f"; {flooded_phrase(names, res.dewatering.flooded_levels)}"
        return text
    if link == "plant":
        running = [line.number for line in res.plant.lines if line.state == "running"]
        stopped = [line.number for line in res.plant.lines if line.state == "off"]
        text = f"линий в работе: {len(running)}"
        if stopped:
            text += f"; в ремонте линия {numbers(stopped)}"
        return text
    if link == "water":
        reclaim = model.p("ladder.m_water.reclaim_m3_per_t")[state.m_water]
        intake = model.p("ladder.m_water.extra_intake_m3h")[state.m_water]
        parts = [f"оборотная вода {num(reclaim, 1)} м³/т" if reclaim else "без оборотной воды"]
        if intake:
            parts.append(f"дополнительный водозабор до {num(intake)} {U_M3H}")
        return ", ".join(parts)
    if link == "tailings":
        return f"свободная ёмкость {num(res.tailings.free_t / cap.KILO)} тыс. т"
    raise KeyError(link)


# --- measures --------------------------------------------------------------------------------

def measure_text(model: cap.Model, names: Mapping[str, str], link: str,
                 before: cap.Result, after: cap.Result) -> str:
    """What one more stage on the knob of ``link`` consists of, as a noun phrase.

    The phrase also says what the stage does to the units that wait for air (spec 2.6). A
    ventilation stage names the units it returns to work and those that still wait. Any other
    stage names the units that will wait once it is taken, when the fleet it brings in needs more
    air than is supplied.
    """
    return _stage_text(model, names, link, before, after) + held_note(link, before.air, after.air)


def held_note(link: str, before: cap.Air, after: cap.Air) -> str:
    """Tail of a measure text: what a stage on ``link`` does to the units that wait for air.

    Empty when the stage holds and releases nothing. Starts with «; », to follow the stage text.
    """
    held_before = set(before.held_trucks) | set(before.held_lhds)
    held_after = set(after.held_trucks) | set(after.held_lhds)
    if link == "ventilation":
        note = ""
        released = held_phrase([t for t in before.held_trucks if t not in held_after],
                               [u for u in before.held_lhds if u not in held_after])
        if released:
            note += f"; в работу возвращаются: {released}"
        if after.restricted:
            note += f"; в ожидании воздуха остаются: {_held(after)}"
        return note
    waiting = held_phrase([t for t in after.held_trucks if t not in held_before],
                          [u for u in after.held_lhds if u not in held_before])
    if waiting:
        return f"; воздуха на весь парк не хватит, до меры по вентиляции в ожидании: {waiting}"
    return ""


def _stage_text(model: cap.Model, names: Mapping[str, str], link: str,
                before: cap.Result, after: cap.Result) -> str:
    """The stage itself, without its effect on the units that wait for air."""
    old, new = before.state, after.state
    if link == "haulage":
        added = [c for c in after.haulage.cycles if c.truck not in {b.truck for b in before.haulage.cycles}]
        noun = "самосвала" if len(added) == 1 else "самосвалов"
        fleet = f"парк: {len(before.haulage.cycles)} {ARROW} {len(after.haulage.cycles)} машин"
        beyond = [c for c in added if c.truck not in names]
        if beyond:   # trucks beyond the registry: the haulage stage that keeps pace with depth
            declines = sorted({_decline_label(names, c.decline) for c in beyond})
            return (f"ввод {noun} {model.p('ladder.depth_trucks.model')} "
                    f"{numbers([int(c.truck.rsplit('-', 1)[-1]) for c in added])} на уклоне {', '.join(declines)} "
                    f"сверх парка реестра ({fleet})")
        return f"ввод {noun} {numbers([int(c.truck.rsplit('-', 1)[-1]) for c in added])} ({fleet})"
    if link == "ventilation":
        added = [fan for fan in after.air.fans_running if fan not in before.air.fans_running]
        return (f"ввод в работу: {_names(names, added)} (подача воздуха "
                f"{num(before.air.supply_m3s)} {ARROW} {num(after.air.supply_m3s)} {U_M3S})")
    if link == "stopes":
        return (f"расширение очистного фронта (блоков {before.stopes.n_producing} {ARROW} "
                f"{after.stopes.n_producing}, ПДМ {before.stopes.lhds} {ARROW} {after.stopes.lhds}, "
                f"буровых установок {before.stopes.rigs} {ARROW} {after.stopes.rigs})")
    if link == "development":
        return (f"ускорение проходки уклонов ({num(before.dev_advance_vm_per_year)} {ARROW} "
                f"{num(after.dev_advance_vm_per_year)} м по вертикали в год)")
    if link == "plant":
        lines = model.p("ladder.m_plant.lines")
        totals = model.p("ladder.m_plant.capacity_ktpa")
        change = f"мощность фабрики {num(totals[old.m_plant])} {ARROW} {num(totals[new.m_plant])} {U_KTPA}"
        if lines[new.m_plant] > lines[old.m_plant]:
            added = list(range(lines[old.m_plant] + 1, lines[new.m_plant] + 1))
            noun = "технологической линии" if len(added) == 1 else "технологических линий"
            return f"пуск {noun} {numbers(added)} ({change})"
        return (f"повышение производительности линий {numbers(list(range(1, lines[new.m_plant] + 1)))} "
                f"({change})")
    if link == "water":
        reclaim = model.p("ladder.m_water.reclaim_m3_per_t")
        intake = model.p("ladder.m_water.extra_intake_m3h")
        parts = []
        if reclaim[new.m_water] != reclaim[old.m_water]:
            parts.append(f"оборотное водоснабжение из хвостохранилища "
                         f"({num(reclaim[new.m_water], 1)} м³ на тонну руды)")
        if intake[new.m_water] != intake[old.m_water]:
            parts.append(f"дополнительный водозабор (до {num(intake[new.m_water])} {U_M3H})")
        return ", ".join(parts)
    if link == "tailings":
        stages = model.p("ladder.m_tailings.dams")
        added = [dam for dam in stages[new.m_tailings] if dam not in stages[old.m_tailings]]
        return (f"ввод ёмкости: {_names(names, added)} (свободная ёмкость "
                f"{num(before.tailings.free_t / cap.KILO)} {ARROW} "
                f"{num(after.tailings.free_t / cap.KILO)} тыс. т)")
    if link == "dewatering":
        flooded = flooded_phrase(names, before.dewatering.flooded_levels)
        if old.pumps_failed_p150:
            return f"восстановление насосов главного водоотлива и откачка воды ({flooded})"
        return f"откачка воды исправными насосами ({flooded})"
    raise KeyError(link)


def _last_word(names: Mapping[str, str], thing: str, fallback: str) -> str:
    """Short label of a thing from its registry name: «ВС-2» from «Вентиляционный ствол ВС-2»."""
    name = names.get(thing)
    return name.split()[-1] if name else fallback


def disturbance_text(model: cap.Model, names: Mapping[str, str], knob: str,
                     before: cap.Result, after: cap.Result) -> str:
    """The operational action that removes a disturbance, as an imperative phrase."""
    old = before.state
    if knob == "line_down":
        return (f"запустить технологическую линию №{NBSP}{old.line_down} после ремонта (мощность фабрики "
                f"{num(before.plant.capacity_ktpa)} {ARROW} {num(after.plant.capacity_ktpa)} {U_KTPA})")
    if knob in ("tu1_closed", "tu2_closed"):
        key = knob.split("_", 1)[0]
        label = _decline_label(names, key)
        home = [c.truck for c in after.haulage.cycles
                if any(t.name == c.truck and t.home_decline == key for t in model.trucks)]
        back = ""
        if home:
            noun = "самосвал" if len(home) == 1 else "самосвалы"
            verb = "возвращается" if len(home) == 1 else "возвращаются"
            back = f"{noun} {numbers(_unit_numbers(home))} {verb} на свой уклон; "
        return (f"открыть уклон {label} ({back}откатка {num(before.capacity_rounded['haulage'])} {ARROW} "
                f"{num(after.capacity_rounded['haulage'])} {U_KTPA})")
    if knob == "fan_vs2_off":
        label = _last_word(names, "shaft-vs2", "ВС-2")
        return (f"восстановить вентилятор {label} (подача воздуха {num(before.air.supply_m3s)} {ARROW} "
                f"{num(after.air.supply_m3s)} {U_M3S})" + held_note("ventilation", before.air, after.air))
    if knob == "pumps_failed_p150":
        total = model.p("water.ps_p150.pumps")
        failed = old.pumps_failed_p150
        noun = "отказавший насос" if failed == 1 else "отказавшие насосы"
        text = (f"восстановить {noun} главной водоотливной станции гор. +150{NBSP}м "
                f"(исправных {total - failed} {ARROW} {total} из {total})")
        if before.dewatering.flooded_levels:
            text += f" и откачать воду ({flooded_phrase(names, before.dewatering.flooded_levels)})"
        return text
    raise KeyError(knob)


def grade_condition(grade: float, base: float, res: cap.Result) -> str:
    """A lower ore grade: a property of the ore, not something a measure removes."""
    return (f"Содержание золота в руде {num(grade, 2)} {U_GPT} вместо {num(base, 2)} {U_GPT} {EM_DASH} "
            f"свойство руды, мерами не снимается; золото считается при этом содержании "
            f"({num(res.gold.oz_per_year / cap.KILO, 1)} {U_KOZ}).")


def water_basis(rates: Mapping[str, float]) -> str:
    """The rates the water KPIs are taken at (decision 11.4), for the tooltip of the tiles."""
    return (f"рудник {num(rates['mine_ktpa'])} {U_KTPA}, фабрика {num(rates['plant_ktpa'])} {U_KTPA} "
            f"(в среднем с плановыми остановками линий; при всех линиях в работе "
            f"{num(rates['all_lines_tph'], 1)} т/ч)")


def inflow_condition(model: cap.Model, names: Mapping[str, str], res: cap.Result,
                     water: Optional[cap.WaterBalance] = None, lines: Optional[cap.WaterBalance] = None) -> str:
    """A flood inflow: an external condition; what it does to the pumps and to the outfall.

    ``water`` and ``lines`` are the balances of ``Advisor.water_regime`` (the mean over the line
    stops and every line running, decision 11.4); without them the balance of ``res`` is used."""
    dewatering = res.dewatering
    water = water or res.water
    pumps = (f"насосы главного водоотлива справляются (запас ×{num(dewatering.margin, 2)})"
             if dewatering.margin >= 1 else
             f"насосов главного водоотлива не хватает (запас ×{num(dewatering.margin, 2)})")
    water_body = names.get("water_body", "водный объект")
    permit = model.p("water.permit_m3h")
    discharge = (f"сброс в {water_body} в установившемся режиме в среднем {num(water.discharge_m3h, 1)} {U_M3H} "
                 f"({num(water.permit_use_pct)} % разрешённых {num(permit, 1)} {U_M3H})")
    if lines is not None and round(lines.discharge_m3h, 1) != round(water.discharge_m3h, 1):
        discharge += (f", при всех линиях фабрики в работе {num(lines.discharge_m3h, 1)} {U_M3H} "
                      f"({num(lines.permit_use_pct)} %)")
    return (f"Приток воды в рудник {num(dewatering.inflow_m3h)} {U_M3H} вместо "
            f"{num(model.p('water.inflow_m3h'))} {U_M3H} (паводок) {EM_DASH} мерами не снимается; {pumps}; "
            f"{discharge}.")


def apply_message(reason: str, binding: str, steps: Sequence[Any]) -> str:
    """One sentence on what ``POST /apply`` returned. ``steps`` are the steps behind the changes."""
    if reason == "target_reached":
        return "Цель достигнута, меры не требуются."
    if reason == "no_stage_left":
        return f"Узкое место {EM_DASH} {link_lower(binding)}: все ступени этого звена уже введены."
    if reason == "pumping_out":
        return f"Узкое место {EM_DASH} водоотлив: насосы исправны, идёт откачка затопленных горизонтов."
    if len(steps) == 1:
        if getattr(steps[0], "kind", "") == "disturbance":
            return f"Сначала устраняется нарушение: {steps[0].text}."
        return f"Узкое место {EM_DASH} {link_lower(steps[0].link)}. Мера: {steps[0].text}."
    parts = [f"{link_lower(step.link)} (нарушение)" if getattr(step, "kind", "") == "disturbance"
             else link_lower(step.link) for step in steps]
    return f"Мер до цели: {len(steps)} ({', '.join(parts)})."


# --- economics, horizon, baseline ------------------------------------------------------------

U_USD_M = "млн долл."
U_USD_OZ = "долл./унц."
_EPS = 1.0e-9   # comparison of times


def years_phrase(value: float) -> str:
    """«0,5 года», «1 год», «1,5 года», «2 года», «5 лет»."""
    if abs(value - round(value)) < _EPS:
        count = int(round(value))
        return f"{count} {_plural(count, 'год', 'года', 'лет')}"
    return f"{num(value, 1)} года"


def _moment(time: float) -> str:
    """«начала 2029 г.», «середины 2027 г.» for a time on the half-year grid."""
    year = int(time + _EPS)
    return f"середины {year} г." if time - year > _EPS else f"начала {year} г."


def when_text(time: float, first: float) -> str:
    """When a measure enters service: «с начала 2029 г.», «с середины 2027 г.»."""
    return f"с {_moment(time)}"


def when_short(time: float, first: float) -> str:
    """Compact form for tables: «2029», «II пол. 2027»."""
    year = int(time + _EPS)
    return f"II пол. {year}" if time - year > _EPS else str(year)


def in_service_text(time: float, lead: float, first: float) -> str:
    """«в работе с середины 2027 г. (срок ввода 0,5 года, решение не позднее начала 2027 г.)»."""
    if lead <= _EPS:
        return f"сразу, с {_moment(time)}: операционное действие"
    return (f"в работе с {_moment(time)} (срок ввода {years_phrase(lead)}, решение не позднее "
            f"{_moment(time - lead)})")


def storage_stage_text(before: cap.Result, after: cap.Result, size_t: float) -> str:
    """The second tailings stage, which no document of the company describes."""
    return (f"вторая ступень хвостохранилища после новой карты: {num(size_t / cap.KILO)} тыс. т "
            f"(допущение, проект не опубликован; свободная ёмкость {num(before.tailings.free_t / cap.KILO)} "
            f"{ARROW} {num(after.tailings.free_t / cap.KILO)} тыс. т)")


def horizon_note(link: str, shown: Optional[int], mine: Optional[int], crossed: Sequence[Any]) -> str:
    """Why a year of the horizon falls short because of storage, and the declines whose design
    bottom the centroid passes that year; empty otherwise."""
    parts = []
    if link == "tailings":
        parts.append("фабрика стоит: нет ёмкости хвостохранилища" if not shown else
                     f"хвостохранилище заполнено в этом году: переработано {num(shown)} тыс. т")
    for label, bottom in crossed:
        parts.append(f"центр добычи ниже проектного дна уклона {label} ({num(bottom)} м): формула откатки "
                     f"считает горизонт доступным")
    return "; ".join(parts)


def binding_runs(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """The binding link of each year in runs: «2027–2028: вентиляция; 2029–2036: фабрика»."""
    runs: List[Dict[str, Any]] = []
    for row in rows:
        if runs and runs[-1]["link"] == row["binding_link"] and runs[-1]["to"] == row["year"] - 1:
            runs[-1]["to"] = row["year"]
        else:
            runs.append({"from": row["year"], "to": row["year"], "link": row["binding_link"],
                         "name": link_name(row["binding_link"])})
    text = "; ".join((f"{r['from']}" if r["from"] == r["to"] else f"{r['from']}{DASH}{r['to']}")
                     + f": {r['name'].lower()}" for r in runs)
    return {"runs": runs, "text": text}


_FAILURE_RU = {
    "ventilation": "воздуха на новые самосвалы не хватает, а все ступени вентиляции уже введены (ствол ВС-3)",
    "tailings": "ёмкость хвостохранилища исчерпана: нужна ёмкость сверх второй ступени",
    "plant": "мощность фабрики на последней ступени",
    "stopes": "все ступени очистного фронта уже введены",
    "development": "проходка уклонов на последней ступени",
    "water": "все ступени водоснабжения уже введены",
    "haulage": "откатке не хватает самосвалов, а новые не повышают выдачу",
    "dewatering": "водоотлив ограничивает добычу",
}


def hold_label(hold: Mapping[str, Any], last_year: int) -> str:
    """«держится до 2036 г.», «держится до 2031 г.», «не достигается до 2036 г.»."""
    if hold["reached_year"] is None:
        return f"не достигается до {last_year} г."
    return f"держится до {hold['held_to_year']} г."


def hold_text(target: float, hold: Mapping[str, Any], last_year: int, row: Optional[Mapping[str, Any]],
              pending: Optional[Mapping[str, Any]]) -> str:
    """One sentence on when the target is reached, how long it holds and what ends it."""
    head = f"Цель {num(target)} {U_KTPA}"
    reason = ""
    if row is not None:
        reason = (f"узкое место {EM_DASH} {row['binding_link_name'].lower()} "
                  f"({num(row['achievable_ktpa'])} тыс. т за год)")
        if hold.get("failure_link"):
            reason += f": {_FAILURE_RU.get(hold['failure_link'], link_lower(hold['failure_link']))}"
        elif pending:
            reason += f": мера ещё не введена {EM_DASH} {pending['text']} ({pending['in_service_text']})"
    if hold["reached_year"] is None:
        return f"{head} не достигается до {last_year} г.: {reason}."
    text = f"{head} достигается в {hold['reached_year']} г. и держится до {hold['held_to_year']} г."
    if hold["holds"]:
        return text
    text += f" В {hold['lost_year']} г. {reason}."
    if hold.get("again_year"):
        text += f" Снова достигается в {hold['again_year']} г."
    return text


def depth_rule_text(rule: Mapping[str, Any], depth_m: float) -> str:
    """The rule that keeps haulage up with depth, and the metres per truck from the haulage formula."""
    text = (f"Когда откатка на глубине полугодия опускается ниже нужного фабрике, вводится ещё один самосвал: "
            f"следующий по реестру, а сверх 12 машин реестра {EM_DASH} {rule['model']} (допущение).")
    if rule.get("metres_per_truck"):
        text += (f" По формуле откатки при парке {rule['fleet_trucks']} машин на отметке {num(depth_m)} м каждые "
                 f"≈{num(rule['metres_per_truck'])} м понижения центра добычи отнимают тоннаж одного самосвала "
                 f"({num(rule['truck_ktpa'])} тыс. т/год).")
    return text


def storage_horizon_note(stages: Sequence[Mapping[str, Any]], runs_out: Optional[int], last_year: int,
                         short_kt: int = 0) -> str:
    """The storage stages of the horizon, whether storage lasts to its end and, if not, the ore
    the plant could still have milled had there been room for its tailings."""
    if not stages:
        text = "Хвостохранилище: новых ступеней не требуется."
    else:
        parts = []
        for stage in stages:
            what = ("новая карта" if stage["kind"] == "measure"
                    else "вторая ступень (допущение, проект не опубликован)")
            parts.append(f"{what} {EM_DASH} в работе с {_moment(stage['time'])} (решение не позднее "
                         f"{_moment(stage['decided'])})")
        text = "Хвостохранилище: " + "; ".join(parts) + "."
    if runs_out is not None:
        text += f" В {runs_out} г. ёмкость кончается: нужна ёмкость сверх второй ступени"
        if short_kt > 0:
            text += f" (до {last_year} г. ещё ≈{num(short_kt)} тыс. т)"
        return text + "."
    return text + f" Ёмкости хватает до {last_year} г."


def payback_text(variant: Mapping[str, Any], last_year: int, disclosed: bool) -> str:
    """The payback year of a variant of the ten-year cash, or why there is none."""
    reason = variant["payback_reason"]
    if reason == "paid_back":
        return f"окупается в {variant['payback_year']} г."
    if reason == "not_held":
        return f"не указывается: цель не удерживается до {last_year} г."
    if reason == "no_outlay":
        return ("не считается: капзатраты не раскрыты" if disclosed
                else "не считается: денежный поток ни в одном году не отрицателен")
    return f"не окупается до {last_year} г."


def horizon_economics_notes(model: cap.Model, econ: Mapping[str, Any]) -> Dict[str, str]:
    """Russian notes of the ten-year economics: bases, capex, caveats and a summary."""
    first_step = model.p("plant.stages_ktpa")[0]
    if econ["capex_disclosed"]:
        capex = (f"≈{num(econ['capex_usd_m'])} {U_USD_M} {EM_DASH} расчётная стоимость расширения до "
                 f"2{DASH}2,5 млн т/год по данным компании (3-й квартал 2025 г.), распределена поровну на срок "
                 f"ввода линий; разбивки по ступеням и состава затрат нет")
    elif econ["target_ktpa"] == first_step:
        capex = ("не раскрыто: в отчёте за первое полугодие 2026 г. сказано, что новое дробильное и мельничное "
                 "оборудование для ступени +200 тыс. т/год заказано, сумма не приводится")
    else:
        capex = "не раскрыто: в отчётах компании нет суммы для мер этой цели"
    assumed = (f"оценка, не опубликовано: самосвал {num(model.p('econ.truck_capex_usd_m'), 1)} {U_USD_M}, "
               f"ёмкость хвостохранилища {num(model.p('econ.tsf_capex_usd_per_t'), 1)} долл. за тонну "
               f"(за вычетом ёмкости, которая нужна и без расширения)")
    totals = econ["totals"]
    summary = (f"за {econ['first_year']}{DASH}{econ['last_year']} гг. золота {num(totals['gold_koz'], 1)} тыс. унц., "
               f"к базе {'+' if totals['gain_koz'] > 0 else ''}{num(totals['gain_koz'], 1)} тыс. унц.")
    return {
        "price_basis": "средняя цена реализации золота за первое полугодие 2026 г. (без серебра)",
        "aisc_basis": ("AISC за первое полугодие 2026 г. в пересчитанной базе: за вычетом выручки от серебра, "
                       "без разовых статей и невозмещаемого НДС; принят неизменным при росте выпуска. НДПИ входит "
                       "в AISC: компания считает AISC от себестоимости реализации и называет НДПИ среди её "
                       "составляющих (отчёт за первое полугодие 2026 г.)"),
        "tax_basis": (f"корпоративный подоходный налог {num(econ['cit_rate_pct'])} % с маржи прироста "
                      f"(Налоговый кодекс РК, ст. 357; капзатраты из базы налога не вычитаются)"),
        "discount_basis": (f"ставка дисконтирования {num(econ['discount_rate_pct'])} % в реальном выражении "
                           f"(допущение), поток года {EM_DASH} на его конец, приведение к началу "
                           f"{econ['first_year']} г."),
        "capex_note": capex,
        "assumed_note": assumed,
        "reference_text": ("база сравнения: рудник без мер расширения и без нарушений, хвостохранилище "
                           "расширяется по мере заполнения"),
        "caveats": ("цена золота и AISC постоянны; без финансирования, оборотного капитала и амортизации; "
                    "стоимость вентиляции, очистного фронта, проходки, водоснабжения и ступени +200 тыс. т "
                    "не раскрыта и в расчёт не входит"),
        "summary": summary,
    }


def economics_item(row: Mapping[str, Any]) -> Dict[str, Any]:
    """Item of «Что изменилось» for a new target: how long it holds and its ten-year economics."""
    econ, horizon = row["economics"], row["horizon"]
    totals, after = econ["totals"], econ["variants"]["disclosed"]
    target = num(row["target_ktpa"])
    text = (f"Цель {target} {U_KTPA}: {horizon['label']}; за {econ['first_year']}{DASH}{econ['last_year']} гг. "
            f"золота {'+' if totals['gain_koz'] > 0 else ''}{num(totals['gain_koz'], 1)} тыс. унц. к базе, маржа "
            f"после налога {num(totals['margin_after_tax_usd_m'], 1)} {U_USD_M}")
    if econ["capex_disclosed"]:
        text += (f", капитальные затраты ≈{num(econ['capex_usd_m'])} {U_USD_M} (по расчёту компании, 3-й кв. "
                 f"2025 г.), чистая приведённая стоимость {num(after['npv_usd_m'], 1)} {U_USD_M} при "
                 f"{num(econ['discount_rate_pct'])} %; окупаемость {after['payback_text'].rstrip('.')}.")
    else:
        text += f"; капитальные затраты не раскрыты; окупаемость {after['payback_text'].rstrip('.')}."
    return _item("economics", "Экономика цели", U_USD_M, None, after["npv_usd_m"], NEUTRAL, text)


def baseline_text(row: Mapping[str, Any]) -> str:
    """The sustainable baseline in one sentence, with the stockpile that keeps the plant at nameplate."""
    text = (f"Устойчивая база: {num(row['ktpa'])} {U_KTPA} ({link_lower(row['binding_link'])}), "
            f"{num(row['gold_koz_year'], 1)} {U_KOZ} при {num(row['grade_gpt'], 2)} {U_GPT}.")
    if row["stockpile_days_left"] is not None:
        text += (f" Фабрика перерабатывает {num(row['plant_ktpa'])} {U_KTPA}, пока не кончится рудный склад: "
                 f"{num(row['stockpile_t'] / cap.KILO, 1)} тыс. т на начало, расход "
                 f"{num(-row['stockpile_net_tpd'])} т/сут, хватит на {num(row['stockpile_days_left'])} {U_DAYS}.")
    return text


# --- effects of the last change --------------------------------------------------------------

def _trend(old: float, new: float, higher_is_better: Optional[bool]) -> str:
    if higher_is_better is None or old == new:
        return NEUTRAL
    return BETTER if (new > old) == higher_is_better else WORSE


def _item(item_id: str, name: str, unit: str, before: Any, after: Any, trend: str, text: str) -> Dict[str, Any]:
    return {"id": item_id, "name": name, "unit": unit, "before": before, "after": after,
            "trend": trend, "text": text}


def changed_value(item_id: str, name: str, verbs: Sequence[str], unit: str, digits: int,
                  before: Optional[float], after: Optional[float], higher_is_better: Optional[bool] = True,
                  subject: Optional[str] = None, tail: str = "") -> Optional[Dict[str, Any]]:
    """Item «<subject> <rose|fell>: before → after unit», or ``None`` when the shown value is the same.

    ``verbs`` is the pair (rose, fell) in the gender of the subject. A value without a limit
    (``None``) on either side gives no item.
    """
    if before is None or after is None or round(before, digits) == round(after, digits):
        return None
    verb = verbs[0] if after > before else verbs[1]
    unit_part = f" {unit}" if unit else ""
    text = f"{subject or name} {verb}: {num(before, digits)} {ARROW} {num(after, digits)}{unit_part}{tail}."
    return _item(item_id, name, unit, before, after, _trend(before, after, higher_is_better), text)


ROSE_F = ("выросла", "снизилась")
ROSE_M = ("вырос", "снизился")
ROSE_N = ("выросло", "снизилось")


def effect_items(names: Mapping[str, str], before: Mapping[str, Any], after: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Sentences for the panel «Что изменилось» from two snapshots of the advisor.

    A snapshot holds ``target_ktpa``, ``binding_link``, ``achievable_ktpa``, ``capacities``
    (link -> kt/yr or ``None``), ``measures_needed``, ``flooded_levels``, ``held_trucks``,
    ``held_lhds``, ``pumps_available``, ``pumps_total``, ``permit_exceeded`` and the KPI values of
    the report. Only values that differ at the precision they are shown with produce an item.
    """
    items: List[Optional[Dict[str, Any]]] = []
    kb, ka = before["kpi"], after["kpi"]

    items.append(changed_value("target_ktpa", "Цель по переработке", ("повышена", "снижена"), U_KTPA, 0,
                               before["target_ktpa"], after["target_ktpa"], higher_is_better=None))
    if before["binding_link"] != after["binding_link"]:
        old, new = before["binding_link"], after["binding_link"]
        items.append(_item("binding_link", "Узкое место", "", old, new, NEUTRAL,
                           f"Узкое место сместилось: {link_lower(old)} {ARROW} {link_lower(new)}."))
    items.append(changed_value("achievable_ktpa", "Достижимая производительность", ROSE_F, U_KTPA, 0,
                               before["achievable_ktpa"], after["achievable_ktpa"],
                               subject="Достижимая производительность цепочки"))

    for link in cap.LINKS:
        old, new = before["capacities"][link], after["capacities"][link]
        item_id, name = f"cap_{link}_ktpa", link_name(link)
        if old is None and new is None:
            continue
        if old is None:
            flooded = flooded_phrase(names, after["flooded_levels"])
            items.append(_item(item_id, name, U_KTPA, old, new, WORSE,
                               f"{name}: {flooded}, добыча из оставшихся блоков "
                               f"ограничена {num(new)} {U_KTPA}."))
        elif new is None:
            items.append(_item(item_id, name, U_KTPA, old, new, BETTER,
                               f"{name}: затопление снято, звено не ограничивает добычу."))
        else:
            items.append(changed_value(item_id, name, ROSE_F, U_KTPA, 0, old, new,
                                       subject=f"Мощность звена «{name.lower()}»"))

    items.append(changed_value("measures_needed", "Число мер до цели", ROSE_N, "", 0,
                               before["measures_needed"], after["measures_needed"], higher_is_better=False))
    items.append(changed_value("grade_gpt", "Содержание золота в руде", ROSE_N, U_GPT, 2,
                               kb["grade_gpt"], ka["grade_gpt"]))
    items.append(changed_value("recovery_pct", "Извлечение золота", ROSE_N, "%", 2,
                               kb["recovery_pct"], ka["recovery_pct"]))
    items.append(changed_value("gold_koz_year", "Выпуск золота", ROSE_M, U_KOZ, 1,
                               kb["gold_koz_year"], ka["gold_koz_year"]))
    items.append(changed_value("air_supply_m3s", "Подача воздуха", ROSE_F, U_M3S, 0,
                               kb["air_supply_m3s"], ka["air_supply_m3s"]))
    items.append(changed_value("air_demand_m3s", "Потребность всего парка в воздухе", ROSE_F, U_M3S, 1,
                               kb["air_demand_m3s"], ka["air_demand_m3s"], higher_is_better=False))
    items.append(held_item(before, after))
    items.append(changed_value("water_deficit_m3h", "Дефицит технической воды", ROSE_M, U_M3H, 1,
                               kb["water_deficit_m3h"], ka["water_deficit_m3h"], higher_is_better=False))
    over_permit = (f"; разрешённый сброс {num(ka['permit_m3h'], 1)} {U_M3H} превышен"
                   if after["permit_exceeded"] else "")
    water_body = names.get("water_body", "водный объект")
    items.append(changed_value("discharge_m3h", f"Сброс в {water_body}", ROSE_M, U_M3H, 1,
                               kb["discharge_m3h"], ka["discharge_m3h"], higher_is_better=False,
                               tail=over_permit))
    items.append(changed_value("tailings_years_left", "Срок до заполнения хвостохранилища", ROSE_M, U_YEARS, 1,
                               kb["tailings_years_left"], ka["tailings_years_left"]))
    items.append(_stockpile(kb["stockpile_days_left"], ka["stockpile_days_left"]))
    items.append(changed_value("dewatering_margin", "Запас производительности насосов", ROSE_M, "", 2,
                               kb["dewatering_margin"], ka["dewatering_margin"],
                               subject="Запас производительности насосов главного водоотлива (кратность)"))
    if before["pumps_available"] != after["pumps_available"]:
        old, new = before["pumps_available"], after["pumps_available"]
        station = names.get("ps-p150", "ps-p150")
        items.append(_item("pumps_available", "Исправные насосы", "шт.", old, new, _trend(old, new, True),
                           f"{station}: исправных насосов {old} {ARROW} {new} из {after['pumps_total']}."))
    return [item for item in items if item is not None]


def held_item(before: Mapping[str, Any], after: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """Units that wait for air (spec 2.6): named whenever the set of held units changed."""
    old = (tuple(before["held_trucks"]), tuple(before["held_lhds"]))
    new = (tuple(after["held_trucks"]), tuple(after["held_lhds"]))
    if old == new:
        return None
    n_old, n_new = len(old[0]) + len(old[1]), len(new[0]) + len(new[1])
    if not n_old:
        text = f"Воздуха не хватает на весь парк, в ожидании воздуха: {held_phrase(*new)}."
    elif not n_new:
        text = f"Воздуха снова хватает на весь парк, в работу возвращаются: {held_phrase(*old)}."
    else:
        text = f"В ожидании воздуха: {held_phrase(*old)} {ARROW} {held_phrase(*new)}."
    return _item("units_held_vent", "Техника в ожидании воздуха", "ед.", n_old, n_new,
                 _trend(n_old, n_new, False), text)


def _stockpile(before: Optional[float], after: Optional[float]) -> Optional[Dict[str, Any]]:
    """Days of ROM stockpile left; ``None`` means the stockpile is not drawn down."""
    item_id, name = "stockpile_days_left", "Запас рудного склада"
    if before is None and after is None:
        return None
    if after is None:
        return _item(item_id, name, U_DAYS, before, after, BETTER,
                     "Рудный склад перестал расходоваться: в установившемся режиме фабрика "
                     "перерабатывает не больше, чем выдаёт рудник.")
    if before is None:
        return _item(item_id, name, U_DAYS, before, after, WORSE,
                     f"Рудный склад расходуется: в установившемся режиме фабрика перерабатывает больше, "
                     f"чем выдаёт рудник, запаса хватит на {num(after)} {U_DAYS}.")
    return changed_value(item_id, name, ROSE_M, U_DAYS, 0, before, after,
                         subject="Срок расходования рудного склада")


# --- calibration table -----------------------------------------------------------------------

_UNIT_RU = {"oz": "унц.", "%": "%", "m3/s": U_M3S, "t/yr": "т/год", "thousand m3/yr": "тыс. м³/год",
            "points": "п.п.", "t": "т"}

#: Kind of row -> Russian group name on the Stand.
KIND_RU = {"analytic": "расчётная", "simulator": "симулятор", "out_of_sample": "вне подгонки"}
#: Basis of a row -> Russian label (decision 11.3).
BASIS_RU = {cap.FIT: "подгонка", cap.INDEPENDENT: "независимая", cap.IDENTITY: "тождество"}


def _decimal_commas(text: str) -> str:
    return re.sub(r"(?<=\d)\.(?=\d)", ",", text)


def tolerance_ru(tolerance: str) -> str:
    """Tolerance of a calibration check, as worded by the library, in Russian notation."""
    text = _decimal_commas(tolerance).replace("+-", "±")
    text = text.replace(" points", " п.п.").replace("% of reported", "% от отчётного")
    text = re.sub(r"(?<=\d)-(?=\d)", DASH, text)
    text = text.replace("inside the reported range", "в пределах прогноза")
    text = text.replace(cap.REFERENCE_TOLERANCE, "справочно, без допуска")
    return text.replace("above reported", "выше отчётного")


def calibration_title(model: cap.Model, check_id: str, case: str = "", quantity: str = "") -> str:
    """Russian name of a calibration row; the figures in it are parameters of the check."""
    p = model.p
    case_number = _decimal_commas(case.split()[0]) if case else ""
    if check_id in ("C1", "C2"):
        return f"Золото за {case.replace('FY', '')} финансовый год"
    if check_id == "C3":
        return "Добыча руды: прогон симулятора, в пересчёте на год"
    if check_id == "C4":
        return f"Золото за первое полугодие {case.split()[-1]} г."
    if check_id == "C5":
        return f"Извлечение золота при содержании {case_number} {U_GPT}"
    if check_id == "C6":
        return "Потребность в воздухе базового парка (пик)"
    if check_id == "C7":
        share = p("calib.c7.fleet_power_share") * cap.PERCENT
        return f"Потребность в воздухе при {num(share)} % мощности базового парка"
    if check_id == "C8":
        return "Переработка руды: прогон симулятора, в пересчёте на год"
    if check_id == "C9":
        return f"Осадок прудов-отстойников при притоке {num(p('water.inflow_m3h'))} {U_M3H}"
    if check_id == "C10":
        return f"Вода на площадку и фабрику при {num(p('plant.nameplate_ktpa'))} {U_KTPA}"
    if check_id == "C11":
        if "tailings" in quantity:
            return "Баланс массы за прогон: переработано = прирост хвостов"
        return "Баланс массы за прогон: выдано = прирост склада + переработано"
    if check_id == "C12":
        return (f"Золото при {num(p('calib.c12.target_ktpa'))} {U_KTPA} и содержании "
                f"{num(p('plant.grade_base'), 2)} {U_GPT}")
    if check_id == "C13":
        return "Добыча первого полугодия 2026 г. в пересчёте на год против устойчивой мощности модели"
    if check_id == "C14":
        return (f"Прогноз компании на 2026 г. против золота модели при {num(p('plant.nameplate_ktpa'))} "
                f"{U_KTPA} и содержании первого полугодия 2026 г. ({num(p('plant.grade_h1_2026'), 2)} {U_GPT})")
    if check_id == "C15":
        lines = num(p("calib.c15.lines_running"))
        return f"Переработка 2024 г. против мощности {lines} линий в модели (третья пущена в декабре 2024 г.)"
    if check_id == "C16":
        return "Переработка первого полугодия 2026 г. в пересчёте на год против мощности фабрики в модели"
    return f"{quantity} ({case})"


def _grade_for_gold(model: cap.Model, milled_t: float, gold_oz: float) -> float:
    """Feed grade at which ``milled_t`` gives ``gold_oz`` (bisection; gold rises with grade)."""
    low, high = 0.0, 10.0
    for _ in range(60):
        mid = (low + high) / 2
        if cap.gold_oz(model, milled_t, mid) < gold_oz:
            low = mid
        else:
            high = mid
    return (low + high) / 2


def basis_note(model: cap.Model, check_id: str) -> str:
    """Why a row is fitted, independent or an identity, with the figures that say so."""
    p = model.p
    if check_id in ("C1", "C2", "C4", "C5"):
        return ("извлечение R(g) подобрано наименьшими квадратами по 2024 и 2025 гг. "
                "и первым полугодиям 2025 и 2026 гг.")
    if check_id == "C3":
        return (f"коэффициент откатки K_HAUL = {num(p('haul.K_HAUL'), 3)} подобран под добычу 2025 г.; "
                f"коэффициент задержек симулятора {num(p('sim.op_delay_factor'), 3)} настроен по этой проверке")
    if check_id in ("C6", "C7"):
        return (f"базовая потребность {num(p('vent.q_base'))} {U_M3S} подобрана под пару "
                f"{num(p('calib.c7.reported_m3s'))} / {num(p('calib.c6.reported_m3s'))} {U_M3S}; "
                f"{num(p('vent.q_diesel'), 2)} {U_M3S} на кВт {EM_DASH} норма Онтарио (Reg. 854, s.183.1(1)); "
                f"в правилах РК (приказ № 352, п. 1063) коэффициент вынесен в приложение 25-1, которого нет "
                f"в открытых копиях")
    if check_id == "C8":
        return (f"производительность линий задана паспортной мощностью фабрики "
                f"({num(p('plant.nameplate_ktpa'))} {U_KTPA})")
    if check_id == "C9":
        return (f"расчёт по исходным данным ОВОС: приток, взвесь {num(p('pond.tss_in_mgl'), 3)} мг/л, "
                f"осаждение {num(p('pond.efficiency') * cap.PERCENT, 1)} %; ничего не подбиралось")
    if check_id == "C10":
        return (f"удельный расход воды на тонну получен делением этих объёмов на "
                f"{num(p('plant.nameplate_ktpa'))} {U_KTPA}")
    if check_id == "C11":
        return "баланс массы симулятора; выполняется по построению модели"
    if check_id == "C12":
        return f"заявление компании о расширении до 2{DASH}2,5 млн т/год; в подгонке не участвовало"
    if check_id == "C13":
        return "K_HAUL подобран по добыче 2025 г.; добыча первого полугодия 2026 г. в подгонке не участвовала"
    if check_id == "C14":
        milled = p("plant.nameplate_ktpa") * cap.KILO
        low, high = (_grade_for_gold(model, milled, koz * cap.KILO) for koz in p("calib.c14.guidance_koz"))
        grade = p("plant.grade_h1_2026")
        return (f"прогноз компании соответствует содержанию {num(low, 2)}{DASH}{num(high, 2)} {U_GPT} "
                f"при {num(milled / 1e6)} млн т; модель при содержании первого полугодия 2026 г. "
                f"({num(grade, 2)} {U_GPT}) даёт {num(cap.gold_oz(model, milled, grade) / cap.KILO, 1)} тыс. унц.")
    if check_id == "C15":
        lines = p("calib.c15.lines_running")
        two_lines_t = sum(cap._line_capacities(model, 0)[:lines]) * cap.KILO
        return (f"в 2024 г. фабрика работала ниже паспортной мощности двух линий "
                f"({num(p('calib.c15.milled_t') / two_lines_t * cap.PERCENT)} %); модель принимает паспортную "
                f"мощность {EM_DASH} это допущение завышает переработку на 3{DASH}11 % (2025 г.: 96,7 %)")
    if check_id == "C16":
        return "мощность фабрики задана паспортом; переработка первого полугодия 2026 г. в подгонке не участвовала"
    return ""


_URL = re.compile(r"https?://[^\s;,]+")
_FACT_ROW = re.compile(r"\b([A-D]\d?) '([^']+)'")


def source_of(sources: Mapping[str, str], params: Sequence[str]) -> Dict[str, Any]:
    """Facts-file sections, rows and URLs behind the reported figure of a row.

    ``text`` reads «факты B: «Gold poured»; D1: «…»»; ``urls`` lists the documents.
    """
    rows: Dict[str, List[str]] = {}
    urls: List[str] = []
    for pid in params:
        source = sources.get(pid, "")
        for section, row in _FACT_ROW.findall(source):
            if row not in rows.setdefault(section, []):
                rows[section].append(row)
        for url in _URL.findall(source):
            url = url.rstrip(").")
            if url not in urls:
                urls.append(url)
    if not rows:
        return {"text": "тождество баланса массы", "urls": urls}
    parts = [f"{section}: " + ", ".join(f"«{row}»" for row in names) for section, names in rows.items()]
    return {"text": "факты " + "; ".join(parts), "urls": urls}


def simulator_run(days: float, seed: Any) -> str:
    return f"прогон симулятора {num(days)} сут базового режима (зерно {seed}), выполнен советником при запуске"


def simulator_run_failed(exc: BaseException) -> str:
    return f"прогон симулятора не выполнен ({type(exc).__name__}); значения проверки здесь не показаны"


def calibration_row(model: cap.Model, sources: Mapping[str, str], check: Optional[cap.CalibrationCheck],
                    kind: str, check_id: Optional[str] = None, run: Optional[str] = None) -> Dict[str, Any]:
    """One row of «Проверка калибровки»: the numbers of a check under Russian headings.

    ``kind`` is ``analytic``, ``simulator`` or ``out_of_sample``. ``check`` may be ``None`` for a
    simulator row whose run failed; ``check_id`` then names it.
    """
    check_id = check.id if check is not None else check_id
    basis, params = cap.CALIBRATION_BASIS[check_id]
    source = source_of(sources, params)
    row = {
        "id": check_id,
        "case": check.case if check else "",
        "title": calibration_title(model, check_id, check.case if check else "", check.quantity if check else ""),
        "kind": kind,
        "kind_name": KIND_RU[kind],
        "basis": basis,
        "basis_name": BASIS_RU[basis],
        "basis_note": basis_note(model, check_id),
        "unit": _UNIT_RU.get(check.unit, check.unit) if check else "",
        "reported": check.reported if check else None,
        "reported_max": check.reported_max if check else None,
        "model": round(check.model, 2) if check else None,
        "deviation": round(check.deviation, 2) if check else None,
        "deviation_unit": _UNIT_RU.get(check.deviation_unit, check.deviation_unit) if check else "%",
        "tolerance": tolerance_ru(check.tolerance) if check else "",
        "passed": None if check is None or check.ok is None else bool(check.ok),
        "reference": bool(check is not None and check.ok is None),
        "source": source["text"],
        "source_urls": source["urls"],
    }
    if run is not None:
        row["run"] = run
    return row
