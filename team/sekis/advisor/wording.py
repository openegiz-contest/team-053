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


def flooded_phrase(names: Mapping[str, str], levels: Sequence[str]) -> str:
    """«затоплен горизонт −50 м» / «затоплены горизонты 0 м, −50 м» from the registry names."""
    marks = [names.get(level, level).replace("Горизонт ", "", 1) for level in levels]
    if len(marks) == 1:
        return f"затоплен горизонт {marks[0]}"
    return "затоплены горизонты " + ", ".join(marks)


# --- the state of each link ------------------------------------------------------------------

def link_detail(model: cap.Model, names: Mapping[str, str], link: str, res: cap.Result) -> str:
    """One line on what stands behind the capacity of a link in the evaluated state."""
    state = res.state
    if link == "haulage":
        by_decline = ", ".join(f"{_decline_label(names, key)}: {count}"
                               for key, count in res.haulage.trucks_by_decline.items())
        return f"самосвалов в работе: {len(res.haulage.cycles)} ({by_decline})"
    if link == "ventilation":
        return (f"подача воздуха {num(res.air.supply_m3s)} {U_M3S}, "
                f"потребность {num(res.air.demand_m3s, 1)} {U_M3S}")
    if link == "stopes":
        return (f"очистных блоков в работе: {res.stopes.n_producing}, ПДМ: {res.stopes.lhds}, "
                f"буровых установок: {res.stopes.rigs}")
    if link == "development":
        return f"проходка уклонов {num(res.dev_advance_vm_per_year)} м по вертикали в год"
    if link == "dewatering":
        text = f"запас производительности насосов ×{num(res.dewatering.margin, 2)}"
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
    """What one more stage on the knob of ``link`` consists of, as a noun phrase."""
    old, new = before.state, after.state
    if link == "haulage":
        added = [c.truck for c in after.haulage.cycles
                 if c.truck not in {b.truck for b in before.haulage.cycles}]
        noun = "самосвала" if len(added) == 1 else "самосвалов"
        return (f"ввод {noun} {numbers([int(t.rsplit('-', 1)[-1]) for t in added])} "
                f"(парк: {len(before.haulage.cycles)} {ARROW} {len(after.haulage.cycles)} машин)")
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


def apply_message(reason: str, binding: str, steps: Sequence[Any]) -> str:
    """One sentence on what ``POST /apply`` returned. ``steps`` are the steps behind the changes."""
    if reason == "target_reached":
        return "Цель достигнута, меры не требуются."
    if reason == "no_stage_left":
        return f"Узкое место {EM_DASH} {link_lower(binding)}: все ступени этого звена уже введены."
    if reason == "pumping_out":
        return f"Узкое место {EM_DASH} водоотлив: насосы исправны, идёт откачка затопленных горизонтов."
    if len(steps) == 1:
        return f"Узкое место {EM_DASH} {link_lower(steps[0].link)}. Мера: {steps[0].text}."
    return f"Мер до цели: {len(steps)} ({', '.join(link_lower(step.link) for step in steps)})."


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
    (link -> kt/yr or ``None``), ``measures_needed``, ``flooded_levels``, ``pumps_available``,
    ``pumps_total``, ``permit_exceeded`` and the KPI values of the report. Only values that
    differ at the precision they are shown with produce an item.
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
    items.append(changed_value("air_demand_m3s", "Потребность в воздухе", ROSE_F, U_M3S, 1,
                               kb["air_demand_m3s"], ka["air_demand_m3s"], higher_is_better=False))
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


def _stockpile(before: Optional[float], after: Optional[float]) -> Optional[Dict[str, Any]]:
    """Days of ROM stockpile left; ``None`` means the stockpile is not drawn down."""
    item_id, name = "stockpile_days_left", "Запас рудного склада"
    if before is None and after is None:
        return None
    if after is None:
        return _item(item_id, name, U_DAYS, before, after, BETTER,
                     "Рудный склад перестал расходоваться: фабрика перерабатывает не больше, "
                     "чем выдаёт рудник.")
    if before is None:
        return _item(item_id, name, U_DAYS, before, after, WORSE,
                     f"Рудный склад расходуется: фабрика перерабатывает больше, чем выдаёт рудник, "
                     f"запаса хватит на {num(after)} {U_DAYS}.")
    return changed_value(item_id, name, ROSE_M, U_DAYS, 0, before, after,
                         subject="Срок расходования рудного склада")


# --- calibration table -----------------------------------------------------------------------

_UNIT_RU = {"oz": "унц.", "%": "%", "m3/s": U_M3S, "t/yr": "т/год", "thousand m3/yr": "тыс. м³/год",
            "points": "п.п."}


def _decimal_commas(text: str) -> str:
    return re.sub(r"(?<=\d)\.(?=\d)", ",", text)


def tolerance_ru(tolerance: str) -> str:
    """Tolerance of a calibration check, as worded by the library, in Russian notation."""
    text = _decimal_commas(tolerance).replace("+-", "±")
    text = text.replace(" points", " п.п.").replace("% of reported", "% от отчётного")
    text = re.sub(r"(?<=\d)-(?=\d)", DASH, text)
    return text.replace("above reported", "выше отчётного")


def calibration_title(model: cap.Model, check: cap.CalibrationCheck) -> str:
    """Russian name of a calibration row; the figures in it are parameters of the check."""
    case_number = _decimal_commas(check.case.split()[0])
    if check.id in ("C1", "C2"):
        return f"Золото за {check.case.replace('FY', '')} финансовый год"
    if check.id == "C4":
        return f"Золото за первое полугодие {check.case.split()[-1]} г."
    if check.id == "C5":
        return f"Извлечение золота при содержании {case_number} {U_GPT}"
    if check.id == "C6":
        return "Потребность в воздухе базового парка (пик)"
    if check.id == "C7":
        share = model.p("calib.c7.fleet_power_share") * cap.PERCENT
        return f"Потребность в воздухе при {num(share)} % мощности базового парка"
    if check.id == "C9":
        return f"Осадок прудов-отстойников при притоке {num(model.p('water.inflow_m3h'))} {U_M3H}"
    if check.id == "C10":
        return (f"Вода на площадку и фабрику при {num(model.p('plant.nameplate_ktpa'))} {U_KTPA}")
    if check.id == "C12":
        return (f"Золото при {num(model.p('calib.c12.target_ktpa'))} {U_KTPA} и содержании "
                f"{num(model.p('plant.grade_base'), 2)} {U_GPT}")
    return f"{check.quantity} ({check.case})"


def calibration_row(model: cap.Model, check: cap.CalibrationCheck) -> Dict[str, Any]:
    """One row of «Проверка калибровки»: the library's numbers under Russian headings."""
    return {
        "id": check.id,
        "case": check.case,
        "title": calibration_title(model, check),
        "kind": "analytic",
        "unit": _UNIT_RU.get(check.unit, check.unit),
        "reported": check.reported,
        "model": round(check.model, 2),
        "deviation": round(check.deviation, 2),
        "deviation_unit": _UNIT_RU.get(check.deviation_unit, check.deviation_unit),
        "tolerance": tolerance_ru(check.tolerance),
        "passed": bool(check.ok),
    }
