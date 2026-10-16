"""Create or update the Sekisovskoye twins in Ditto from model/registry.json.

Run in the container as `python -m sekis.setup_twins` (the image's default
command). Steps: wait for Ditto, make sure the policy exists, PUT every type
thing and every thing in registry order, reset `kz.sekis:scenario` to its
defaults, then count what Ditto holds. Every write is an idempotent PUT; a
second run changes nothing except the scenario `revision`, which goes up by one
so that a running simulator and advisor notice the reset.

Registry shape (written by work package A1): {"types": [<thing>, ...],
"things": [<thing>, ...]}, each <thing> a Ditto thing document with "thingId",
"policyId", "attributes", "features" (a "_meta" key, used for publishing tiers,
is dropped). The loader also accepts "types" / "things" as objects keyed by id.
Ids without a namespace get `kz.sekis.type:` or `kz.sekis:`.
Features must have the shape {"<id>": {"properties": {"value": <scalar>}}}.
"""

import argparse
import copy
import json
import os
import sys
import time

if __package__ in (None, ""):  # run as a plain script: make `sekis` importable
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sekis.ditto import Ditto, DittoError  # noqa: E402

THING_NS = "kz.sekis"
TYPE_NS = "kz.sekis.type"
POLICY_ID = "default:basic_policy"
SCENARIO_ID = f"{THING_NS}:scenario"

# The policy the platform's `init` job creates, reduced to the subject every
# Ditto user gets through nginx. It is created only when missing; an existing
# policy (made by `init`) is never replaced.
DEFAULT_POLICY = {
    "policyId": POLICY_ID,
    "entries": {
        "DEFAULT": {
            "subjects": {
                "{{ request:subjectId }}": {"type": "Ditto user authenticated via nginx"},
            },
            "resources": {
                "policy:/": {"grant": ["READ", "WRITE"], "revoke": []},
                "thing:/": {"grant": ["READ", "WRITE"], "revoke": []},
                "message:/": {"grant": ["READ", "WRITE"], "revoke": []},
            },
        }
    },
}

# Knob defaults of SPEC 3.1 (default value first in the table there).
SCENARIO_DEFAULTS = {
    "target_ktpa": 1000,
    "m_plant": 0,
    "m_haul": 0,
    "m_stopes": 0,
    "m_vent": 0,
    "m_dev": 0,
    "m_water": 0,
    "m_tailings": 0,
    "tu1_closed": 0,
    "tu2_closed": 0,
    "fan_vs2_off": 0,
    "pumps_failed_p150": 0,
    "inflow_factor": 1.0,
    "grade_gpt": 2.05,
    "line_down": 0,
    "vod_enabled": 1,          # ventilation on demand on (SPEC 3.5)
    "label": "Базовый режим",
}


class SetupError(Exception):
    """A problem that makes the setup stop with a message and exit code 1."""


def say(message):
    print(message, flush=True)


# ---------------------------------------------------------------- registry


def default_registry_path():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.environ.get("REGISTRY_FILE") or os.path.join(os.path.dirname(here), "model", "registry.json")


def _full_id(raw_id, namespace):
    return raw_id if ":" in raw_id else f"{namespace}:{raw_id}"


def _as_pairs(section, namespace, where):
    """Normalise one registry section to a list of (thing id, body) pairs."""
    if isinstance(section, dict):
        items = list(section.items())
    elif isinstance(section, list):
        items = []
        for entry in section:
            if not isinstance(entry, dict) or not entry.get("thingId"):
                raise SetupError(f"реестр: элемент списка «{where}» без поля thingId")
            items.append((entry["thingId"], entry))
    else:
        raise SetupError(f"реестр: раздел «{where}» должен быть объектом или списком")
    pairs = []
    for raw_id, body in items:
        if not isinstance(body, dict):
            raise SetupError(f"реестр: «{raw_id}» не является объектом")
        body = copy.deepcopy(body)
        body.pop("thingId", None)
        body.pop("_meta", None)  # registry bookkeeping (tiers), not part of the Ditto payload
        pairs.append((_full_id(str(raw_id), namespace), body))
    return pairs


def load_registry(path):
    """Return (types, things): two lists of (thing id, body) in file order."""
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        raise SetupError(f"файл реестра не найден: {path}") from None
    except ValueError as exc:
        raise SetupError(f"файл реестра {path} не разобран как JSON: {exc}") from None
    if not isinstance(data, dict):
        raise SetupError("реестр: верхний уровень должен быть объектом")
    types = _as_pairs(data.get("types", []), TYPE_NS, "types")
    things = _as_pairs(data.get("things", []), THING_NS, "things")
    if not types or not things:
        raise SetupError(f"реестр {path}: нет типов или нет двойников "
                         f"(типов: {len(types)}, двойников: {len(things)})")
    return types, things


def validate(types, things):
    """Return a list of problems found in the registry (empty when it is fine)."""
    problems = []
    seen = {}
    for kind, pairs in (("тип", types), ("двойник", things)):
        for thing_id, _ in pairs:
            if thing_id in seen:
                problems.append(f"повторяется идентификатор {thing_id}")
            seen[thing_id] = kind
    type_ids = {thing_id for thing_id, _ in types}
    thing_ids = {thing_id for thing_id, _ in things}
    value_kind = {}  # feature id -> "string" | "number", must be one for all things

    for thing_id, body in types + things:
        features = body.get("features", {})
        if not isinstance(features, dict):
            problems.append(f"{thing_id}: features должен быть объектом")
            continue
        for feature_id, feature in features.items():
            props = feature.get("properties") if isinstance(feature, dict) else None
            if not isinstance(props, dict) or set(props) != {"value"}:
                problems.append(f"{thing_id}: признак {feature_id} должен иметь вид "
                                f'{{"properties": {{"value": ...}}}}')
                continue
            value = props["value"]
            if isinstance(value, bool) or value is None or not isinstance(value, (int, float, str)):
                problems.append(f"{thing_id}: признак {feature_id} имеет недопустимое значение {value!r} "
                                f"(нужно число или строка)")
                continue
            kind = "string" if isinstance(value, str) else "number"
            if value_kind.setdefault(feature_id, kind) != kind:
                problems.append(f"{thing_id}: признак {feature_id} здесь {kind}, "
                                f"в других двойниках {value_kind[feature_id]}")

    for thing_id, body in things:
        attrs = body.get("attributes") or {}
        if attrs.get("_isType") is not False:
            problems.append(f"{thing_id}: attributes._isType должен быть false")
        if attrs.get("type") not in type_ids:
            problems.append(f"{thing_id}: тип {attrs.get('type')!r} не найден среди типов")
        parent = attrs.get("_parents")
        if parent is not None and parent not in thing_ids:
            problems.append(f"{thing_id}: родитель {parent!r} не найден")
        for key, target in attrs.items():
            if key.startswith("link_"):
                for ref in (target if isinstance(target, list) else [target]):
                    if ref not in thing_ids:
                        problems.append(f"{thing_id}: связь {key} указывает на неизвестный {ref!r}")
    for thing_id, body in types:
        if (body.get("attributes") or {}).get("_isType") is not True:
            problems.append(f"{thing_id}: attributes._isType должен быть true")
    if SCENARIO_ID not in thing_ids:
        problems.append(f"нет управляющего двойника {SCENARIO_ID}")
    return problems


# ------------------------------------------------------------------- setup


def with_scenario_defaults(body, old_revision):
    """The scenario thing document with every knob at its default."""
    body = copy.deepcopy(body)
    features = body.setdefault("features", {})
    for name, value in SCENARIO_DEFAULTS.items():
        # Numbers are floats everywhere, so that InfluxDB sees one field type.
        features[name] = {"properties": {"value": value if isinstance(value, str) else float(value)}}
    if old_revision is None:
        revision = features.get("revision", {}).get("properties", {}).get("value", 0)
    else:
        revision = int(old_revision) + 1
    features["revision"] = {"properties": {"value": float(revision)}}
    return body


def run(ditto, types, things, verbose=False, wait_s=300.0, count_wait_s=60.0):
    """Write the registry to Ditto. Raises DittoError or SetupError."""
    say(f"Ожидание Ditto ({ditto.url}) ...")
    ditto.wait_ready(timeout=wait_s)

    state = ditto.ensure_policy(POLICY_ID, DEFAULT_POLICY)
    say(f"Политика {POLICY_ID}: {'создана' if state == 'created' else 'уже есть'}")

    for label, pairs in (("Типы", types), ("Двойники", things)):
        created = updated = 0
        for thing_id, body in pairs:
            body = copy.deepcopy(body)
            body.setdefault("policyId", POLICY_ID)
            if thing_id == SCENARIO_ID:
                old = ditto.feature_value(thing_id, "revision")
                body = with_scenario_defaults(body, old if isinstance(old, (int, float)) else None)
            try:
                result = ditto.put_thing(thing_id, body)
            except DittoError as exc:
                raise SetupError(f"не удалось записать {thing_id}: {exc}") from exc
            created += result == "created"
            updated += result == "updated"
            if verbose:
                say(f"  {'создан' if result == 'created' else 'обновлён'}  {thing_id}")
        say(f"{label}: записано {len(pairs)} (создано {created}, обновлено {updated})")

    scenario = ditto.get_thing(SCENARIO_ID) or {}
    knobs = {name: feature.get("properties", {}).get("value")
             for name, feature in (scenario.get("features") or {}).items()}
    wrong = [name for name, value in SCENARIO_DEFAULTS.items() if knobs.get(name) != value]
    if wrong:
        raise SetupError(f"сценарий не сброшен к значениям по умолчанию: {', '.join(wrong)}")
    say(f"Сценарий сброшен к значениям по умолчанию (ревизия {int(knobs.get('revision') or 0)})")

    # The search index trails the thing store by a few seconds: wait a little,
    # and report a mismatch as a warning only, since every PUT above succeeded.
    want = (len(types), len(things))
    deadline = time.monotonic() + count_wait_s
    while True:
        try:
            have = (ditto.count_things(f'like(thingId,"{TYPE_NS}:*")'),
                    ditto.count_things(f'like(thingId,"{THING_NS}:*")'))
        except DittoError:
            have = None
        if have == want or time.monotonic() >= deadline:
            break
        time.sleep(3)
    if have == want:
        say(f"Ditto: {have[1]} двойников и {have[0]} типов найдено в поиске")
    else:
        say(f"ПРЕДУПРЕЖДЕНИЕ: поиск Ditto показывает {have} (типов, двойников), "
            f"ожидалось {want}; индекс поиска мог ещё не обновиться")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--registry", default=default_registry_path(), help="путь к registry.json")
    parser.add_argument("--verbose", action="store_true", default=bool(os.environ.get("SETUP_VERBOSE")),
                        help="печатать каждый записанный двойник")
    parser.add_argument("--wait", type=float, default=float(os.environ.get("DITTO_WAIT_S", "300")),
                        help="сколько секунд ждать Ditto")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # Russian text on any console encoding
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        types, things = load_registry(args.registry)
        problems = validate(types, things)
        if problems:
            shown = "\n  ".join(problems[:20])
            more = f"\n  ... и ещё {len(problems) - 20}" if len(problems) > 20 else ""
            raise SetupError(f"реестр {args.registry} содержит ошибки ({len(problems)}):\n  {shown}{more}")
        say(f"Реестр {args.registry}: {len(types)} типов, {len(things)} двойников")
        run(Ditto.from_env(), types, things, verbose=args.verbose, wait_s=args.wait)
    except (SetupError, DittoError) as exc:
        print(f"ОШИБКА: {exc}", file=sys.stderr, flush=True)
        return 1
    say("Двойники «Секисовского» готовы.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
