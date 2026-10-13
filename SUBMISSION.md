# SUBMISSION

<!-- Fill in every section. The AI Jury studies this file together with the code, the Build Report, the presentation and the Stand's interface. Accepted languages: English, Kazakh, Russian. These hint comments may be deleted. -->

## Concept

<!-- Written by the Team before the code: your own choice, a few sentences per answer. Everything else in the Submission follows from it. -->

**Enterprise:** Секисовское — действующий подземный золотой рудник компании AltynGold PLC (оператор — ДТОО «ГРП BAURGOLD») в Глубоковском районе Восточно-Казахстанской области, в 40 км от Усть-Каменогорска. Двойник охватывает всю цепочку предприятия: забои, откатку руды по двум транспортным уклонам, вентиляцию и водоотлив, обогатительную фабрику на 1 млн т руды в год и хвостохранилище.

**Users:** Главный инженер рудника и отдел планирования горных работ: они отвечают за то, сколько руды рудник поднимет и переработает. Второй пользователь — эколог предприятия, которому важны вода и хвосты.

**Decision:** Наращивать ли переработку с 1 до 2,0–2,5 млн т руды в год и какими ступенями. Компания изучает это расширение: по полугодовому отчёту от 29 сентября 2026 года инвестиционное решение ещё не принято, а ближайшая ступень — прибавка около 200 тыс. т в год на существующей фабрике. Двойник показывает, какое звено первым ограничит выпуск на каждой ступени — забои, откатка по уклонам, вентиляция, водоотлив, фабрика или хвостохранилище — и сколько золота каждая ступень добавляет.

**Why this choice:** Это настоящее решение, которое предприятие ещё не приняло, и по нему есть публичные цифры для проверки модели. Секисовское — площадка казахстанско-японского проекта SATREPS «Smart Mining+» (Университет Хоккайдо и Назарбаев Университет, 2025–2030), где цифровой двойник строят ради снижения нагрузки на окружающую среду, поэтому каждый сценарий показывает не только золото, но и воду и хвосты. Подземный рудник выбран и потому, что его узкие места — уклоны, воздух и вода — не видны на обычном дашборде и требуют пространственной модели.

**Real or fictional:** Реальный объект. Источники цифр: годовые отчёты AltynGold за 2024 и 2025 годы, полугодовой отчёт за первое полугодие 2026 года, отчёт компетентного лица по стандарту JORC (EY, 2019) и природоохранные документы рудника на ecoportal.kz. Работа независимая, использует только открытые данные и не согласована с AltynGold или участниками проекта SATREPS. План подземных выработок в открытых источниках не опубликован: схема построена по опубликованным отметкам, все допущения перечислены в разделе «Data and Assumptions».

## Team

<!-- GitHub usernames of the Participants. Other personal data are not required: the repository becomes public after the Freeze (Rules, section 15). -->

| GitHub |
|---|
| Tomiyato |

## Mine

<!-- Which part of a mining enterprise the Submission represents (open pit, underground mine, processing plant…), which objects are twins in OpenEgiz, how they are related, and where they are defined in the code. -->

## Modules and What-if Scenarios

<!-- Modules: functions on top of the twin, from the Mine Map or your own. What-if Scenarios: changes of an operating condition that can be run on the Stand without changing the code (close a road, stop equipment…). Only what works on the Stand is taken into account. -->

| Module or What-if Scenario | What it does | How to see it on the Stand | How to undo it (scenarios) |
|---|---|---|---|
|  |  |  |  |

## What works and what does not

<!-- What has been verified, what is unfinished, which bugs are known. -->

## Data and Assumptions

<!--
- Synthetic and real data.
- Sources of parameters: equipment data sheets, reference literature, industrial safety regulations, datasets.
- Datasets: source, license, how they are provided (in the repository or downloaded per the README).
Confidential data of organizations and personal data are prohibited.
-->

## Mine visualization

<!-- Address on the Stand, dashboard or scene; what it shows. -->

## Limitations

## Presentation

`presentation.pdf` in the repository root. Video (optional): <link>

---

Platform: OpenEgiz v1.0.4.
