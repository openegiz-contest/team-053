"""Tests for team/model/params.json and team/model/registry.json (spec sections 1 and 2.8)."""

import json
import re
import unittest
from collections import Counter, defaultdict
from pathlib import Path

TEAM = Path(__file__).resolve().parent.parent
MODEL = TEAM / "model"
FACTS = TEAM / "research" / "sekisovskoye-facts.md"

NS = "kz.sekis"
TNS = "kz.sekis.type"
POLICY = "default:basic_policy"
STRING_FEATURES = {"state", "shift", "decline", "stope", "binding_link", "next_measure", "label", "sim_time"}
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
KIND_RE = re.compile(r"^[a-z][a-z0-9_]*$")

KINDS = [
    "enterprise", "mine", "level", "stope", "decline", "shaft", "raise", "main_fan", "pump_station",
    "settling_pond", "monitoring_point", "haul_truck", "lhd", "drill_rig", "rom_stockpile", "plant",
    "plant_line", "tailings_facility", "tailings_dam", "water_system", "scenario_control", "advisor",
]

# number of things per kind (spec 1.3 count line)
KIND_COUNTS = {
    "enterprise": 1, "mine": 1, "level": 12, "stope": 18, "decline": 2, "shaft": 3, "raise": 4, "main_fan": 5,
    "pump_station": 3, "haul_truck": 12, "lhd": 10, "drill_rig": 5, "water_system": 1, "settling_pond": 2,
    "monitoring_point": 2, "plant": 1, "rom_stockpile": 1, "plant_line": 6, "tailings_facility": 1,
    "tailings_dam": 4, "scenario_control": 1, "advisor": 1,
}


def load(path):
    with open(path, "rb") as f:
        raw = f.read()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise AssertionError(f"{path} has a BOM")
    if b"\r" in raw:
        raise AssertionError(f"{path} has CR characters")
    return json.loads(raw.decode("utf-8"))


def value_of(thing, fid):
    return thing["features"][fid]["properties"]["value"]


class RegistryCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reg = load(MODEL / "registry.json")
        cls.types = cls.reg["types"]
        cls.things = cls.reg["things"]
        cls.by_id = {t["thingId"]: t for t in cls.things}
        cls.type_by_id = {t["thingId"]: t for t in cls.types}

    def things_of(self, kind):
        return [t for t in self.things if t["attributes"]["kind"] == kind]

    def ids_of(self, kind):
        return [t["thingId"].split(":", 1)[1] for t in self.things_of(kind)]


class TestRegistryStructure(RegistryCase):
    def test_schema_documented(self):
        self.assertIn("_schema", self.reg)
        self.assertIsInstance(self.reg["_schema"], dict)
        self.assertEqual(self.reg["namespace"], NS)
        self.assertEqual(self.reg["type_namespace"], TNS)
        self.assertEqual(self.reg["policy_id"], POLICY)

    def test_counts(self):
        self.assertEqual(len(self.things), 96)
        self.assertEqual(len(self.types), 22)

    def test_ids_unique(self):
        thing_ids = [t["thingId"] for t in self.things]
        type_ids = [t["thingId"] for t in self.types]
        self.assertEqual(len(thing_ids), len(set(thing_ids)))
        self.assertEqual(len(type_ids), len(set(type_ids)))

    def test_type_ids_follow_namespace_rules(self):
        self.assertEqual(sorted(t["thingId"] for t in self.types), sorted(f"{TNS}:{k}" for k in KINDS))
        for t in self.types:
            kind = t["thingId"].split(":", 1)[1]
            self.assertTrue(KIND_RE.match(kind), kind)
            self.assertEqual(t["policyId"], POLICY)
            a = t["attributes"]
            self.assertIs(a["_isType"], True)
            self.assertTrue(a["name"].strip())
            self.assertTrue(a["description"].strip())
            self.assertIn(t["_meta"]["tier"], {"S", "M", "L", "on_change", "on_change_and_30s"})

    def test_thing_ids_follow_namespace_rules(self):
        for t in self.things:
            ns, _, name = t["thingId"].partition(":")
            self.assertEqual(ns, NS, t["thingId"])
            self.assertTrue(NAME_RE.match(name), t["thingId"])
            self.assertEqual(t["policyId"], POLICY, t["thingId"])
            self.assertNotIn("_meta", t)

    def test_common_attributes(self):
        for t in self.things:
            a = t["attributes"]
            tid = t["thingId"]
            self.assertTrue(a["name"].strip(), tid)
            self.assertIs(a["_isType"], False, tid)
            self.assertIn(a["kind"], KINDS, tid)
            self.assertEqual(a["type"], f"{TNS}:{a['kind']}", tid)
            self.assertIn(a["type"], self.type_by_id, tid)
            self.assertIsInstance(a["units"], dict, tid)

    def test_display_names_are_russian(self):
        cyr = re.compile("[Ѐ-ӿ]")
        for t in self.things:
            self.assertTrue(cyr.search(t["attributes"]["name"]), t["thingId"])
        for t in self.types:
            self.assertTrue(cyr.search(t["attributes"]["name"]), t["thingId"])
            self.assertTrue(cyr.search(t["attributes"]["description"]), t["thingId"])

    def test_parents_resolve_and_form_one_tree(self):
        roots = [t for t in self.things if "_parents" not in t["attributes"]]
        self.assertEqual([r["thingId"] for r in roots], [f"{NS}:enterprise"])
        position = {t["thingId"]: i for i, t in enumerate(self.things)}
        for t in self.things:
            p = t["attributes"].get("_parents")
            if p is None:
                continue
            self.assertIsInstance(p, str, t["thingId"])
            self.assertIn(p, self.by_id, f"{t['thingId']} parent {p}")
            self.assertLess(position[p], position[t["thingId"]], f"parent after child: {t['thingId']}")
        for t in self.things:  # every chain ends at the root
            seen, cur = set(), t["thingId"]
            while "_parents" in self.by_id[cur]["attributes"]:
                self.assertNotIn(cur, seen)
                seen.add(cur)
                cur = self.by_id[cur]["attributes"]["_parents"]
            self.assertEqual(cur, f"{NS}:enterprise")

    def test_link_attributes_resolve(self):
        n_links = 0
        for t in self.things:
            for key, val in t["attributes"].items():
                if not key.startswith("link_"):
                    continue
                targets = val if isinstance(val, list) else [val]
                self.assertTrue(targets, f"{t['thingId']}.{key} is empty")
                for target in targets:
                    n_links += 1
                    self.assertIsInstance(target, str, f"{t['thingId']}.{key}")
                    self.assertIn(target, self.by_id, f"{t['thingId']}.{key} -> {target}")
        self.assertGreater(n_links, 100)

    def test_link_attributes_exist_where_the_spec_requires_them(self):
        required = {
            "stope": ["link_level", "link_ore_route"],
            "level": ["link_declines", "link_drains_to", "link_air_intake", "link_air_exhaust"],
            "decline": ["link_levels", "link_portal_to"],
            "main_fan": ["link_airway"],
            "pump_station": ["link_discharges_to"],
            "settling_pond": ["link_overflows_to"],
            "haul_truck": ["link_home_decline"],
            "rom_stockpile": ["link_feeds"],
            "plant": ["link_tailings_to", "link_water_from"],
            "tailings_facility": ["link_active_dam"],
            "water_system": ["link_ponds", "link_points"],
        }
        for kind, keys in required.items():
            for t in self.things_of(kind):
                for key in keys:
                    self.assertIn(key, t["attributes"], f"{t['thingId']} lacks {key}")

    def test_link_target_kinds(self):
        def kind(tid):
            return self.by_id[tid]["attributes"]["kind"]

        def targets(t, key):
            v = t["attributes"][key]
            return v if isinstance(v, list) else [v]

        for t in self.things_of("stope"):
            self.assertEqual(kind(t["attributes"]["link_level"]), "level")
            self.assertEqual(t["attributes"]["link_level"], t["attributes"]["_parents"])
            for d in targets(t, "link_ore_route"):
                self.assertEqual(kind(d), "decline")
        for t in self.things_of("level"):
            for d in targets(t, "link_declines"):
                self.assertEqual(kind(d), "decline")
            self.assertEqual(kind(t["attributes"]["link_drains_to"]), "pump_station")
            self.assertEqual(kind(t["attributes"]["link_air_intake"]), "shaft")
            self.assertEqual(kind(t["attributes"]["link_air_exhaust"]), "raise")
        for t in self.things_of("decline"):
            for lv in targets(t, "link_levels"):
                self.assertEqual(kind(lv), "level")
                self.assertIn(t["thingId"], targets(self.by_id[lv], "link_declines"))
            self.assertEqual(kind(t["attributes"]["link_portal_to"]), "rom_stockpile")
        for t in self.things_of("shaft") + self.things_of("raise"):
            if "link_fan" in t["attributes"]:
                fan = self.by_id[t["attributes"]["link_fan"]]
                self.assertEqual(fan["attributes"]["kind"], "main_fan")
                self.assertEqual(fan["attributes"]["link_airway"], t["thingId"])
        for t in self.things_of("main_fan"):
            for a in targets(t, "link_airway"):
                self.assertIn(kind(a), {"shaft", "raise", "decline"})
        for t in self.things_of("pump_station"):
            self.assertIn(kind(t["attributes"]["link_discharges_to"]), {"pump_station", "settling_pond"})
        for t in self.things_of("haul_truck"):
            self.assertEqual(kind(t["attributes"]["link_home_decline"]), "decline")
        for t in self.things_of("rom_stockpile"):
            for line in targets(t, "link_feeds"):
                self.assertEqual(kind(line), "plant_line")
        plant = self.by_id[f"{NS}:plant"]["attributes"]
        self.assertEqual(plant["link_tailings_to"], f"{NS}:tailings")
        self.assertEqual(plant["link_water_from"], f"{NS}:water")
        self.assertEqual(self.by_id[f"{NS}:tailings"]["attributes"]["link_active_dam"], f"{NS}:tsf-dam4")
        pond = self.by_id[f"{NS}:pond-upper"]["attributes"]
        self.assertEqual(pond["link_overflows_to"], f"{NS}:pond-lower")
        self.assertEqual(self.by_id[f"{NS}:pond-lower"]["attributes"]["link_overflows_to"], f"{NS}:water")

    def test_level_link_rules(self):
        for t in self.things_of("level"):
            a = t["attributes"]
            elev = a["elevation_m"]
            want_ps = f"{NS}:ps-p150" if elev >= 150 else f"{NS}:ps-m050"
            want_shaft = f"{NS}:shaft-vs1" if elev >= 150 else f"{NS}:shaft-vs2"
            self.assertEqual(a["link_drains_to"], want_ps, t["thingId"])
            self.assertEqual(a["link_air_intake"], want_shaft, t["thingId"])
            self.assertEqual(a["link_air_exhaust"], f"{NS}:raise-vhv-exhaust")
            self.assertIn(f"{NS}:decline-tu1", a["link_declines"])
            self.assertEqual(f"{NS}:decline-tu2" in a["link_declines"], 0 <= elev <= 300, t["thingId"])


class TestFeatures(RegistryCase):
    def test_every_thing_has_exactly_its_type_features(self):
        for t in self.things:
            ty = self.type_by_id[t["attributes"]["type"]]
            self.assertEqual(list(t["features"]), list(ty["features"]), t["thingId"])
            self.assertEqual(list(t["attributes"]["units"]), list(t["features"]), t["thingId"])

    def test_feature_shape(self):
        for t in self.types + self.things:
            for fid, f in t["features"].items():
                self.assertTrue(re.match(r"^[a-z][a-z0-9_]*$", fid), fid)
                self.assertEqual(list(f), ["properties"], f"{t['thingId']}.{fid}")
                self.assertEqual(list(f["properties"]), ["value"], f"{t['thingId']}.{fid}")

    def test_each_feature_id_has_one_value_type(self):
        kinds = defaultdict(set)
        for t in self.types + self.things:
            for fid, f in t["features"].items():
                v = f["properties"]["value"]
                self.assertFalse(isinstance(v, bool), f"{t['thingId']}.{fid} is boolean")
                self.assertIsNotNone(v, f"{t['thingId']}.{fid} is null")
                self.assertNotIsInstance(v, (list, dict), f"{t['thingId']}.{fid}")
                kinds[fid].add("string" if isinstance(v, str) else "number")
        for fid, ks in kinds.items():
            self.assertEqual(len(ks), 1, f"feature {fid} has value types {ks}")
        for fid, ks in kinds.items():
            want = "string" if fid in STRING_FEATURES else "number"
            self.assertEqual(ks, {want}, fid)

    def test_numbers_are_json_floats(self):
        for t in self.types + self.things:
            for fid, f in t["features"].items():
                v = f["properties"]["value"]
                if fid not in STRING_FEATURES:
                    self.assertIsInstance(v, float, f"{t['thingId']}.{fid}")

    def test_each_feature_id_has_one_unit(self):
        units = defaultdict(set)
        for t in self.things:
            for fid, u in t["attributes"]["units"].items():
                self.assertIsInstance(u, str)
                units[fid].add(u)
        for fid, us in units.items():
            self.assertEqual(len(us), 1, f"feature {fid} has units {us}")
            if fid in STRING_FEATURES:
                self.assertEqual(us, {""}, fid)
        for fid in ("revision", "report_revision", "block_no"):
            self.assertEqual(units[fid], {""})
        for fid, us in units.items():
            if fid not in STRING_FEATURES and fid not in {"revision", "report_revision", "block_no"}:
                self.assertNotEqual(us, {""}, f"numeric feature {fid} has no unit")

    def test_spec_feature_lists(self):
        def feats(kind):
            return list(self.type_by_id[f"{TNS}:{kind}"]["features"])

        self.assertEqual(feats("enterprise"), ["sim_time", "sim_day", "shift", "ore_mined_tpd", "ore_milled_tpd",
                                               "gold_poured_oz_day", "gold_poured_total_oz", "annual_rate_ktpa",
                                               "binding_link"])
        self.assertEqual(len(feats("mine")), 13)
        self.assertEqual(len(feats("level")), 7)
        self.assertEqual(len(feats("stope")), 8)
        self.assertEqual(len(feats("decline")), 7)
        self.assertEqual(feats("shaft"), feats("raise"))
        self.assertEqual(feats("haul_truck"), ["state", "payload", "grade", "speed", "decline", "chainage_m",
                                               "elevation", "pos_x", "pos_y", "pos_z", "trips_today",
                                               "tonnes_today"])
        self.assertEqual(len(feats("advisor")), 22)
        self.assertEqual(feats("scenario_control")[-2:], ["revision", "label"])
        self.assertEqual(len(feats("scenario_control")), 17)  # 15 knobs + revision + label

    def test_state_tokens_of_baseline(self):
        allowed = {
            "mine": {"production", "blast_window", "restricted_air", "evacuation"},
            "level": {"ventilation", "mined_out", "production", "development", "planned", "flooded"},
            "stope": {"planned", "preparation", "standby", "drilling", "charging", "awaiting_blast", "ventilating",
                      "mucking", "backfilling", "flooded"},
            "decline": {"open", "closed"},
            "shaft": {"in_service", "planned"},
            "raise": {"in_service", "planned"},
            "main_fan": {"running", "failed", "planned"},
            "pump_station": {"idle", "pumping", "alarm_high", "failed", "planned"},
            "settling_pond": {"in_service"},
            "monitoring_point": {"normal", "warning", "exceeded"},
            "haul_truck": {"parked", "descending", "waiting_bay", "tram_level", "queue_load", "loading", "hauling_up",
                           "surface_haul", "dumping", "held_vent", "maintenance", "shift_break"},
            "lhd": {"parked", "idle", "mucking", "loading_truck", "standby_vent", "shift_break"},
            "drill_rig": {"parked", "drilling", "tramming", "shift_break"},
            "rom_stockpile": {"normal", "low", "empty"},
            "plant": {"running", "starved", "water_limited"},
            "plant_line": {"running", "starved", "maintenance", "water_limited", "off", "planned"},
            "tailings_facility": {"ok", "short_horizon", "full"},
            "tailings_dam": {"active", "standby", "full", "planned"},
            "water_system": {"balanced", "deficit", "discharge_over_permit"},
        }
        for kind, tokens in allowed.items():
            for t in self.things_of(kind) + [self.type_by_id[f"{TNS}:{kind}"]]:
                self.assertIn(value_of(t, "state"), tokens, t["thingId"])


class TestCountsPerKind(RegistryCase):
    def test_kind_counts(self):
        self.assertEqual(sum(KIND_COUNTS.values()), 96)
        got = Counter(t["attributes"]["kind"] for t in self.things)
        self.assertEqual(dict(got), KIND_COUNTS)
        self.assertEqual(set(KIND_COUNTS), set(KINDS))

    def test_names_per_kind(self):
        self.assertEqual(self.ids_of("haul_truck"), [f"truck-{n:02d}" for n in range(1, 13)])
        self.assertEqual(self.ids_of("lhd"), [f"lhd-{n:02d}" for n in range(1, 11)])
        self.assertEqual(self.ids_of("drill_rig"), [f"rig-{n:02d}" for n in range(1, 6)])
        self.assertEqual(self.ids_of("plant_line"), [f"plant-line-{n}" for n in range(1, 7)])
        self.assertEqual(self.ids_of("tailings_dam"), ["tsf-dam4", "tsf-dam2", "tsf-dam3", "tsf-cell5"])
        self.assertEqual(self.ids_of("main_fan"), ["fan-vs1", "fan-ug-p320", "fan-vs2", "fan-vpv", "fan-vs3"])
        self.assertEqual(self.ids_of("pump_station"), ["ps-p150", "ps-m050", "ps-m200"])
        self.assertEqual(self.ids_of("decline"), ["decline-tu1", "decline-tu2"])
        self.assertEqual(self.ids_of("shaft"), ["shaft-vs1", "shaft-vs2", "shaft-vs3"])
        self.assertEqual(self.ids_of("raise"), ["raise-vpv", "raise-vhv-tu1", "raise-vhv-tu2", "raise-vhv-exhaust"])
        self.assertEqual(self.ids_of("monitoring_point"), ["mon-volchevka", "mon-sekisovka"])
        self.assertEqual(self.ids_of("settling_pond"), ["pond-upper", "pond-lower"])

    def test_levels(self):
        levels = self.things_of("level")
        roles = Counter(t["attributes"]["role"] for t in levels)
        self.assertEqual(roles, Counter({"ventilation": 1, "mined_out": 2, "production": 4, "development": 1,
                                         "planned": 4}))
        elevs = [t["attributes"]["elevation_m"] for t in levels]
        self.assertEqual(elevs, [320, 250, 200, 150, 100, 50, 0, -50, -100, -150, -200, -300])
        for t in levels:
            self.assertEqual(value_of(t, "state"), t["attributes"]["role"])
            self.assertEqual(t["attributes"]["_parents"], f"{NS}:mine")

    def test_stopes(self):
        stopes = self.things_of("stope")
        per_level = Counter(t["attributes"]["link_level"].split(":", 1)[1] for t in stopes)
        self.assertEqual(per_level, Counter({"lvl-p150": 3, "lvl-p100": 3, "lvl-p050": 3, "lvl-000": 3,
                                             "lvl-m050": 3, "lvl-m100": 3}))
        for t in stopes:
            self.assertEqual(t["attributes"]["ore_initial_t"], 90000)
            self.assertEqual(value_of(t, "ore_remaining_t"), 90000.0)
            self.assertEqual(value_of(t, "grade"), t["attributes"]["grade_gpt"])
        states = Counter(value_of(t, "state") for t in stopes)
        self.assertEqual(states, Counter({"drilling": 4, "standby": 8, "preparation": 3, "planned": 3}))
        grades = {}
        for t in stopes:
            grades.setdefault(t["attributes"]["link_level"].split(":", 1)[1], set()).add(t["attributes"]["grade_gpt"])
        self.assertEqual({k: sorted(v) for k, v in grades.items()},
                         {"lvl-p150": [1.75], "lvl-p100": [1.95], "lvl-p050": [2.15], "lvl-000": [2.35],
                          "lvl-m050": [2.45], "lvl-m100": [2.55]})
        # stopes below -34 m are reachable by TU1 only
        for t in stopes:
            if t["attributes"]["link_level"] in (f"{NS}:lvl-m050", f"{NS}:lvl-m100"):
                self.assertEqual(t["attributes"]["link_ore_route"], [f"{NS}:decline-tu1"])

    def test_fleet(self):
        trucks = self.things_of("haul_truck")
        active = [t for t in trucks if value_of(t, "state") != "parked"]
        self.assertEqual([t["thingId"].split(":")[1] for t in active], [f"truck-{n:02d}" for n in range(1, 6)])
        self.assertEqual(sum(1 for t in trucks if t["attributes"]["payload_t"] == 30), 4)
        self.assertEqual(sum(1 for t in trucks if t["attributes"]["payload_t"] == 45), 8)
        home = {t["thingId"].split(":")[1]: t["attributes"]["link_home_decline"].split("-")[1] for t in trucks}
        self.assertEqual([n for n, d in home.items() if d == "tu2"],
                         ["truck-01", "truck-02", "truck-03", "truck-04", "truck-09", "truck-10", "truck-12"])
        self.assertEqual([n for n, d in home.items() if d == "tu1"],
                         ["truck-05", "truck-06", "truck-07", "truck-08", "truck-11"])
        lhds = self.things_of("lhd")
        self.assertEqual(sum(1 for t in lhds if value_of(t, "state") != "parked"), 4)
        self.assertEqual(sum(1 for t in lhds if t["attributes"]["bucket_t"] == 6.8), 3)
        self.assertEqual(sum(1 for t in lhds if t["attributes"]["bucket_t"] == 15), 7)
        rigs = self.things_of("drill_rig")
        self.assertEqual(sum(1 for t in rigs if value_of(t, "state") != "parked"), 2)

    def test_fans_and_pumps(self):
        fans = self.things_of("main_fan")
        running = [t for t in fans if value_of(t, "state") == "running"]
        planned = [t for t in fans if value_of(t, "state") == "planned"]
        self.assertEqual(len(running), 3)
        self.assertEqual(len(planned), 2)
        self.assertEqual(sum(t["attributes"]["duty_m3s"] for t in running), 322)
        self.assertEqual(sum(t["attributes"]["duty_m3s"] for t in planned), 345)  # 105 + 240
        pumps = {t["thingId"].split(":")[1]: t["attributes"] for t in self.things_of("pump_station")}
        self.assertEqual(pumps["ps-p150"]["pumps_total"] * pumps["ps-p150"]["pump_capacity_m3h"], 900)
        self.assertEqual(pumps["ps-m050"]["pumps_total"] * pumps["ps-m050"]["pump_capacity_m3h"], 300)
        self.assertEqual(value_of(self.by_id[f"{NS}:ps-m200"], "state"), "planned")
        for a in pumps.values():
            self.assertLessEqual(a["pumps_working"], a["pumps_total"])

    def test_plant_and_tailings(self):
        lines = self.things_of("plant_line")
        self.assertEqual(sum(1 for t in lines if value_of(t, "state") == "running"), 3)
        self.assertEqual(sum(1 for t in lines if value_of(t, "state") == "planned"), 3)
        dams = {t["thingId"].split(":")[1]: t for t in self.things_of("tailings_dam")}
        self.assertEqual(value_of(dams["tsf-dam4"], "state"), "active")
        self.assertEqual(value_of(dams["tsf-dam2"], "state"), "standby")
        self.assertEqual(value_of(dams["tsf-dam3"], "state"), "standby")
        self.assertEqual(value_of(dams["tsf-cell5"], "state"), "planned")
        self.assertEqual(dams["tsf-dam4"]["attributes"]["capacity_t"], 3181950)
        self.assertEqual(dams["tsf-dam4"]["attributes"]["capacity_m3"], 2357000)
        free = sum(value_of(d, "free_capacity_t") for d in dams.values())
        self.assertAlmostEqual(free, 3172095.0, places=0)  # about 3.2 Mt at the epoch
        stored4 = value_of(dams["tsf-dam4"], "stored_t")
        self.assertAlmostEqual(stored4 / dams["tsf-dam4"]["attributes"]["capacity_t"], 0.90, places=6)
        self.assertAlmostEqual(value_of(self.by_id[f"{NS}:tailings"], "free_capacity_t"), free, places=0)
        for d in dams.values():
            a = d["attributes"]
            self.assertAlmostEqual(a["capacity_t"] / a["bulk_density"], a["capacity_m3"], delta=1.0)
        self.assertEqual(value_of(self.by_id[f"{NS}:rom-stockpile"], "tonnes"), 94264.0)  # stockpile.start_t, derivation in params.json

    def test_scenario_defaults(self):
        s = self.by_id[f"{NS}:scenario"]
        defaults = {"target_ktpa": 1000.0, "m_plant": 0.0, "m_haul": 0.0, "m_stopes": 0.0, "m_vent": 0.0,
                    "m_dev": 0.0, "m_water": 0.0, "m_tailings": 0.0, "tu1_closed": 0.0, "tu2_closed": 0.0,
                    "fan_vs2_off": 0.0, "pumps_failed_p150": 0.0, "inflow_factor": 1.0, "grade_gpt": 2.05,
                    "line_down": 0.0, "revision": 0.0}
        for k, v in defaults.items():
            self.assertEqual(value_of(s, k), v, k)
        self.assertEqual(len(defaults), 16)
        self.assertTrue(value_of(s, "label"))

    def test_hierarchy_parents(self):
        def parent(name):
            return self.by_id[f"{NS}:{name}"]["attributes"].get("_parents")

        self.assertEqual(parent("mine"), f"{NS}:enterprise")
        self.assertEqual(parent("fan-vs1"), f"{NS}:shaft-vs1")
        self.assertEqual(parent("fan-ug-p320"), f"{NS}:lvl-p320")
        self.assertEqual(parent("fan-vpv"), f"{NS}:raise-vpv")
        self.assertEqual(parent("ps-m050"), f"{NS}:lvl-m050")
        self.assertEqual(parent("pond-upper"), f"{NS}:water")
        self.assertEqual(parent("mon-volchevka"), f"{NS}:water")
        self.assertEqual(parent("water"), f"{NS}:enterprise")
        self.assertEqual(parent("plant"), f"{NS}:enterprise")
        self.assertEqual(parent("rom-stockpile"), f"{NS}:plant")
        self.assertEqual(parent("plant-line-6"), f"{NS}:plant")
        self.assertEqual(parent("tailings"), f"{NS}:enterprise")
        self.assertEqual(parent("tsf-cell5"), f"{NS}:tailings")
        self.assertEqual(parent("scenario"), f"{NS}:enterprise")
        self.assertEqual(parent("advisor"), f"{NS}:enterprise")
        for t in self.things_of("stope"):
            self.assertEqual(t["attributes"]["_parents"], t["attributes"]["link_level"])


class ParamsCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.params = load(MODEL / "params.json")


class TestParams(ParamsCase):
    def test_every_parameter_has_value_unit_source(self):
        self.assertGreater(len(self.params), 100)
        for pid, entry in self.params.items():
            self.assertEqual(sorted(entry), ["source", "unit", "value"], pid)
            self.assertIsNotNone(entry["value"], pid)
            self.assertIsInstance(entry["unit"], str, pid)
            self.assertTrue(entry["unit"].strip(), pid)
            src = entry["source"]
            self.assertIsInstance(src, str, pid)
            self.assertTrue(src.startswith("FACT ") or src.startswith("ASSUMPTION: "), f"{pid}: {src[:30]}")
            self.assertGreater(len(src), 30, pid)
            self.assertTrue(re.match(r"^[a-zA-Z0-9_]+(\.[a-zA-Z0-9_]+)+$", pid), pid)

    def test_fact_sources_cite_a_facts_file_row(self):
        if not FACTS.exists():
            self.skipTest("facts file not present")
        facts = FACTS.read_text(encoding="utf-8")
        n_fact = 0
        for pid, entry in self.params.items():
            src = entry["source"]
            if not src.startswith("FACT "):
                continue
            n_fact += 1
            m = re.match(r"^FACT ([A-D]\d*) '", src)
            self.assertIsNotNone(m, f"{pid}: FACT source must name the facts-file section and a quoted row: {src}")
            quotes = re.findall(r"'([^']+)'", src)
            self.assertTrue(quotes, pid)
            for q in quotes:
                self.assertTrue(q in facts, f"{pid}: row text not found in the facts file: {q!r}")
        self.assertGreater(n_fact, 40)

    def test_assumptions_are_substantial(self):
        n = sum(1 for e in self.params.values() if e["source"].startswith("ASSUMPTION: "))
        self.assertGreater(n, 50)

    def test_spec_28_values(self):
        v = {k: e["value"] for k, e in self.params.items()}
        self.assertEqual((v["regime.working_days"], v["regime.shifts"], v["regime.shift_h"]), (360, 2, 11))
        self.assertEqual(v["regime.productive_h"], 8.5)
        self.assertEqual((v["decline.tu1.portal_m"], v["decline.tu1.design_bottom_m"]), (430, -300))
        self.assertEqual((v["decline.tu2.portal_m"], v["decline.tu2.design_bottom_m"]), (320, -200))
        self.assertEqual((v["decline.slope_deg"], v["decline.section_m2"]), (8, 18.0))
        self.assertEqual((v["decline.tu1.bottom_m"], v["decline.tu2.bottom_m"]), (-50, -34))
        self.assertEqual(v["decline.length_factor"], 1.15)
        self.assertEqual(v["decline.bay_spacing_vm"], 25)
        self.assertEqual((v["decline.tu1.surface_km"], v["decline.tu2.surface_km"]), (0.8, 1.5))
        self.assertEqual(v["level.floor_height_m"], 50)
        self.assertEqual(v["stope.sublevel_m"], [13, 16])
        self.assertEqual(v["stope.capacity_design_ktpa"], 1023.5)
        self.assertEqual(v["stope.producing_base"], 4)
        self.assertAlmostEqual(v["stope.capacity_design_ktpa"] / v["stope.producing_base"], 255.875)
        self.assertEqual((v["stope.cycle_shifts"], v["stope.blast_t"]), (4, 1421.5))
        self.assertEqual(v["stope.ore_initial_t"], 90000)
        self.assertEqual((v["stope.backfill_days"], v["stope.preparation_days"]), (20, 5))
        self.assertEqual(list(v["stope.grade_by_level"].values()), [1.75, 1.95, 2.15, 2.35, 2.45, 2.55])
        self.assertEqual(v["ore.density"], 2.83)
        self.assertEqual((v["dev.advance_vm_per_year"], v["dev.advance_boosted"], v["dev.t_per_vm"]), (34, 50, 51462))
        self.assertEqual((v["truck.AD30.payload_t"], v["truck.AD30.engine_kw"]), (30, 304))
        self.assertEqual((v["truck.AD45.payload_t"], v["truck.AD45.engine_kw"]), (45, 439))
        self.assertEqual((v["lhd.R1300.bucket_t"], v["lhd.R1300.engine_kw"]), (6.8, 123))
        self.assertEqual((v["lhd.R1700.bucket_t"], v["lhd.R1700.engine_kw"]), (15, 263))
        self.assertEqual((v["truck.speed_up_loaded_kmh"], v["truck.speed_down_empty_kmh"],
                          v["truck.speed_flat_loaded_kmh"], v["truck.speed_flat_empty_kmh"]), (9, 16, 15, 20))
        self.assertEqual((v["truck.load_min"], v["truck.dump_min"], v["truck.manoeuvre_min"]), (5, 1.5, 1.5))
        self.assertEqual((v["truck.availability"], v["truck.mtbf_h"], v["truck.mttr_h"]), (0.80, 40, 10))
        self.assertAlmostEqual(v["truck.mtbf_h"] / (v["truck.mtbf_h"] + v["truck.mttr_h"]), v["truck.availability"])
        self.assertEqual(v["haul.K_BAY"], 0.75)
        self.assertAlmostEqual(v["haul.K_HAUL"], 0.811, places=3)
        self.assertEqual(v["sim.op_delay_factor"], 0.785)  # tuned by the simulator, spec 10 item 3
        self.assertLessEqual(v["sim.op_delay_factor_min"], v["sim.op_delay_factor"])
        self.assertLessEqual(v["sim.op_delay_factor"], v["sim.op_delay_factor_max"])
        self.assertEqual((v["vent.supply_2022"], v["vent.supply_base"]), (252, 322))
        self.assertEqual((v["vent.q_base"], v["vent.q_diesel"]), (180, 0.06))
        self.assertEqual((v["vent.measure_V1.delta_m3s"], v["vent.measure_V2.delta_m3s"]), (105, 240))
        self.assertEqual(v["vent.measure_V1.raise_section_m2"] * v["vent.velocity_limit_ms"],
                         v["vent.measure_V1.delta_m3s"])
        self.assertEqual(v["vent.measure_V2.shaft_section_m2"] * v["vent.velocity_limit_ms"],
                         v["vent.measure_V2.delta_m3s"])
        self.assertEqual((v["vent.fan_efficiency"], v["vent.pressure_vs1_pa"], v["vent.reentry_min"]),
                         (0.75, 2500, 30))
        self.assertEqual((v["vent.fan_vs2.duty_min_m3s"], v["vent.fan_vs2.duty_max_m3s"],
                          v["vent.fan_vs2.pressure_pa"]), (63, 88, 3000))
        self.assertEqual(v["vent.split_fan_vs1_m3s"] + v["vent.split_fan_ug_p320_m3s"],
                         v["vent.supply_2022"])
        self.assertEqual(v["vent.split_fan_vs1_m3s"] + v["vent.split_fan_ug_p320_m3s"] + v["vent.fan_vs2.duty_m3s"],
                         v["vent.supply_base"])
        self.assertEqual((v["water.inflow_m3h"], v["water.inflow_design_m3h"]), (197, 430))
        self.assertAlmostEqual(v["water.mine_water_kth_m3yr"] * 1000 / 8760, v["water.inflow_m3h"], delta=0.01)
        self.assertEqual(v["water.upper_share"], 0.60)
        self.assertEqual((v["water.ps_p150.pumps"], v["water.ps_p150.pump_m3h"], v["water.ps_p150.sump_m3"]),
                         (3, 300, 1800))
        self.assertEqual((v["water.ps_m050.pumps"], v["water.ps_m050.pump_m3h"], v["water.ps_m050.sump_m3"]),
                         (2, 150, 600))
        self.assertEqual((v["water.flood_threshold_m050_m3"], v["water.flood_threshold_000_m3"]), (300, 1500))
        self.assertEqual((v["water.pump_efficiency"], v["water.head_ps_p150_m"], v["water.head_ps_m050_m"]),
                         (0.70, 280, 200))
        self.assertEqual((v["pond.volume_m3"], v["pond.area_m2"], v["pond.depth_m"], v["pond.settling_h"]),
                         (4530, 755, 3, 6))
        self.assertEqual((v["pond.tss_in_mgl"], v["pond.efficiency"]), (39.563, 0.949))
        self.assertEqual((v["water.site_use_kth_m3yr"], v["water.plant_supply_kth_m3yr"]), (602.688, 1123.032))
        self.assertEqual((v["water.site_m3_per_t"], v["water.plant_m3_per_t"]), (0.603, 1.123))
        self.assertAlmostEqual(v["water.site_m3_per_t"] * 1000 + v["water.plant_m3_per_t"] * 1000,
                               v["water.mine_water_kth_m3yr"], delta=0.5)  # 0.603 + 1.123 are rounded per-tonne figures
        self.assertEqual(v["water.permit_m3h"], 218.8)
        self.assertAlmostEqual(1917.1123 * 1000 / 8760, v["water.permit_m3h"], delta=0.1)
        self.assertEqual((v["water.measure_W1.reclaim_m3_per_t"], v["water.measure_W2.extra_intake_m3h"]),
                         (0.6, 150))
        self.assertEqual((v["plant.nameplate_ktpa"], v["plant.lines"]), (1000, 3))
        self.assertEqual(v["plant.availability"], 0.92)
        self.assertAlmostEqual(1 / v["plant.maintenance_period_days"], 1 - v["plant.availability"])
        self.assertEqual(v["plant.stages_ktpa"], [1200, 2000, 2500])
        self.assertEqual(v["plant.line45_ktpa"] * 2 + 1200, 2000)
        self.assertEqual(v["plant.line6_ktpa"] + 2000, 2500)
        self.assertEqual((v["plant.recovery.intercept_pct"], v["plant.recovery.slope_pct_per_gpt"],
                          v["plant.recovery.min_pct"], v["plant.recovery.max_pct"]), (81.616, 1.637, 80, 88))
        self.assertEqual((v["plant.grade_base"], v["plant.grade_h1_2026"]), (2.05, 1.76))
        self.assertEqual(v["stockpile.start_t"], 94264)
        self.assertEqual((v["tsf.dam4_capacity_t"], v["tsf.dam4_capacity_m3"], v["tsf.bulk_density"]),
                         (3181950, 2357000, 1.35))
        self.assertEqual(v["tsf.dam4_fill_start"], 0.90)
        self.assertEqual(v["tsf.dam23_free_t"], 1426950)
        self.assertEqual(v["tsf.dam23_free_t"], v["tsf.dam4_capacity_t"] - 1755000)
        self.assertEqual((v["tsf.measure_X1_t"], v["tsf.min_years"]), (6000000, 3.0))
        self.assertEqual(v["gold.g_per_oz"], 31.1035)
        self.assertEqual(v["sim.speedup"], 60)
        self.assertEqual(v["sim.seed"], 53)
        self.assertEqual(v["publish.max_msg_per_s"], 20)

    def test_mandatory_mixed_sources(self):
        # facts are FACT, design choices are ASSUMPTION
        src = {k: e["source"] for k, e in self.params.items()}
        for pid in ("regime.working_days", "decline.tu1.portal_m", "decline.slope_deg", "level.floor_height_m",
                    "stope.capacity_design_ktpa", "ore.density", "vent.supply_2022", "vent.supply_base",
                    "water.inflow_m3h", "water.inflow_design_m3h", "pond.volume_m3", "water.permit_m3h",
                    "plant.nameplate_ktpa", "plant.grade_base", "tsf.dam4_capacity_t", "fleet.base.trucks_ad30",
                    "fleet.base.lhd_r1300", "decline.tu1.bottom_m"):
            self.assertTrue(src[pid].startswith("FACT "), pid)
        for pid in ("regime.productive_h", "decline.tu2.bottom_m", "stope.ore_initial_t", "dev.t_per_vm",
                    "haul.K_HAUL", "haul.K_BAY", "sim.op_delay_factor", "vent.q_base", "vent.q_diesel",
                    "water.upper_share", "water.ps_p150.sump_m3", "plant.availability", "plant.recovery.intercept_pct",
                    "stockpile.start_t", "tsf.dam4_fill_start", "tsf.dam23_free_t", "tsf.min_years",
                    "fleet.base.trucks_ad45", "fleet.base.rigs", "truck.AD30.payload_t"):
            self.assertTrue(src[pid].startswith("ASSUMPTION: "), pid)


class TestParamsAgainstRegistry(RegistryCase, ParamsCase):
    @classmethod
    def setUpClass(cls):
        RegistryCase.setUpClass.__func__(cls)
        ParamsCase.setUpClass.__func__(cls)

    def v(self, pid):
        return self.params[pid]["value"]

    def test_declines(self):
        for tu in ("tu1", "tu2"):
            a = self.by_id[f"{NS}:decline-{tu}"]["attributes"]
            self.assertEqual(a["portal_elevation_m"], self.v(f"decline.{tu}.portal_m"))
            self.assertEqual(a["design_bottom_m"], self.v(f"decline.{tu}.design_bottom_m"))
            self.assertEqual(a["slope_deg"], self.v("decline.slope_deg"))
            self.assertEqual(a["section_m2"], self.v("decline.section_m2"))
            self.assertEqual(value_of(self.by_id[f"{NS}:decline-{tu}"], "bottom_elevation"),
                             float(self.v(f"decline.{tu}.bottom_m")))

    def test_fleet_attributes(self):
        for t in self.things_of("haul_truck"):
            model = t["attributes"]["model"].split()[-1]
            self.assertEqual(t["attributes"]["payload_t"], self.v(f"truck.{model}.payload_t"))
            self.assertEqual(t["attributes"]["engine_kw"], self.v(f"truck.{model}.engine_kw"))
        for t in self.things_of("lhd"):
            model = t["attributes"]["model"].split()[-1]
            self.assertEqual(t["attributes"]["bucket_t"], self.v(f"lhd.{model}.bucket_t"))
            self.assertEqual(t["attributes"]["engine_kw"], self.v(f"lhd.{model}.engine_kw"))
        active = [t for t in self.things_of("haul_truck") if value_of(t, "state") != "parked"]
        self.assertEqual(sum(1 for t in active if t["attributes"]["model"] == "CAT AD30"),
                         self.v("fleet.base.trucks_ad30"))
        self.assertEqual(sum(1 for t in active if t["attributes"]["model"] == "CAT AD45"),
                         self.v("fleet.base.trucks_ad45"))
        lhd_active = [t for t in self.things_of("lhd") if value_of(t, "state") != "parked"]
        self.assertEqual(sum(1 for t in lhd_active if t["attributes"]["model"] == "CAT R1300"),
                         self.v("fleet.base.lhd_r1300"))
        self.assertEqual(sum(1 for t in lhd_active if t["attributes"]["model"] == "CAT R1700"),
                         self.v("fleet.base.lhd_r1700"))
        rigs_active = [t for t in self.things_of("drill_rig") if value_of(t, "state") != "parked"]
        self.assertEqual(len(rigs_active), self.v("fleet.base.rigs"))
        # baseline fleet power gives the baseline air demand of the reference table (317.2 m3/s)
        fleet_kw = sum(t["attributes"]["engine_kw"] for t in active + lhd_active)
        demand = self.v("vent.q_base") + self.v("vent.q_diesel") * fleet_kw
        self.assertAlmostEqual(demand, 317.2, delta=0.05)  # 317.22 before rounding in the spec table
        self.assertGreaterEqual(demand / self.v("vent.supply_base"), 0.95)

    def test_stopes_and_levels(self):
        by_level = self.v("stope.grade_by_level")
        for t in self.things_of("stope"):
            code = t["attributes"]["link_level"].split("lvl-")[1]
            self.assertEqual(t["attributes"]["grade_gpt"], by_level[code])
            self.assertEqual(t["attributes"]["ore_initial_t"], self.v("stope.ore_initial_t"))
            self.assertEqual(t["attributes"]["sublevel_m"], self.v("stope.sublevel_m"))
        elevs = sorted(t["attributes"]["elevation_m"] for t in self.things_of("level"))
        steps = [b - a for a, b in zip(elevs[:], elevs[1:]) if 0 <= a <= 250 and b <= 250]
        self.assertTrue(all(s == self.v("level.floor_height_m") for s in steps), steps)
        self.assertEqual(len([t for t in self.things_of("stope")
                              if value_of(t, "state") == "drilling"]), self.v("stope.producing_base"))

    def test_ventilation(self):
        fans = {t["thingId"].split(":")[1]: t["attributes"] for t in self.things_of("main_fan")}
        self.assertEqual(fans["fan-vs1"]["duty_m3s"], self.v("vent.split_fan_vs1_m3s"))
        self.assertEqual(fans["fan-ug-p320"]["duty_m3s"], self.v("vent.split_fan_ug_p320_m3s"))
        self.assertEqual(fans["fan-vs2"]["duty_m3s"], self.v("vent.fan_vs2.duty_m3s"))
        self.assertEqual(fans["fan-vs2"]["duty_max_m3s"], self.v("vent.fan_vs2.duty_max_m3s"))
        self.assertEqual(fans["fan-vs2"]["pressure_pa"], self.v("vent.fan_vs2.pressure_pa"))
        self.assertEqual(fans["fan-vs1"]["pressure_pa"], self.v("vent.pressure_vs1_pa"))
        self.assertEqual(fans["fan-vpv"]["duty_m3s"], self.v("vent.measure_V1.delta_m3s"))
        self.assertEqual(fans["fan-vs3"]["duty_m3s"], self.v("vent.measure_V2.delta_m3s"))
        mine = self.by_id[f"{NS}:mine"]
        self.assertEqual(value_of(mine, "air_supply_m3s"), float(self.v("vent.supply_base")))
        self.assertEqual(self.by_id[f"{NS}:raise-vpv"]["attributes"]["section_m2"],
                         self.v("vent.measure_V1.raise_section_m2"))
        self.assertEqual(self.by_id[f"{NS}:shaft-vs3"]["attributes"]["section_m2"],
                         self.v("vent.measure_V2.shaft_section_m2"))
        for t in self.things_of("main_fan"):
            if value_of(t, "state") == "running":
                a = t["attributes"]
                want = a["duty_m3s"] * a["pressure_pa"] / self.v("vent.fan_efficiency") / 1000
                self.assertAlmostEqual(value_of(t, "power_kw"), want, delta=0.06)

    def test_water(self):
        p150 = self.by_id[f"{NS}:ps-p150"]["attributes"]
        self.assertEqual(p150["pumps_total"], self.v("water.ps_p150.pumps"))
        self.assertEqual(p150["pumps_working"], self.v("water.ps_p150.pumps_working"))
        self.assertEqual(p150["pump_capacity_m3h"], self.v("water.ps_p150.pump_m3h"))
        self.assertEqual(p150["sump_volume_m3"], self.v("water.ps_p150.sump_m3"))
        m050 = self.by_id[f"{NS}:ps-m050"]["attributes"]
        self.assertEqual(m050["pumps_total"], self.v("water.ps_m050.pumps"))
        self.assertEqual(m050["pumps_working"], self.v("water.ps_m050.pumps_working"))
        self.assertEqual(m050["pump_capacity_m3h"], self.v("water.ps_m050.pump_m3h"))
        self.assertEqual(m050["sump_volume_m3"], self.v("water.ps_m050.sump_m3"))
        ponds = self.things_of("settling_pond")
        self.assertEqual(sum(t["attributes"]["volume_m3"] for t in ponds), self.v("pond.volume_m3"))
        self.assertEqual(sum(t["attributes"]["area_m2"] for t in ponds), self.v("pond.area_m2"))
        for t in ponds:
            self.assertEqual(t["attributes"]["depth_m"], self.v("pond.depth_m"))
            self.assertEqual(value_of(t, "tss_in_mgl"), self.v("pond.tss_in_mgl"))
        self.assertEqual(self.by_id[f"{NS}:mon-volchevka"]["attributes"]["permit_m3h"], self.v("water.permit_m3h"))
        self.assertEqual(value_of(self.by_id[f"{NS}:mine"], "inflow_m3h"), float(self.v("water.inflow_m3h")))

    def test_plant_and_tailings(self):
        self.assertEqual(self.by_id[f"{NS}:plant"]["attributes"]["nameplate_ktpa"], self.v("plant.nameplate_ktpa"))
        self.assertEqual(len(self.things_of("plant_line")) - 3, self.v("plant.lines"))
        base = self.v("plant.nameplate_ktpa") * 1000 / self.v("plant.lines") / 8760 / self.v("plant.availability")
        for n in (1, 2, 3):
            self.assertAlmostEqual(self.by_id[f"{NS}:plant-line-{n}"]["attributes"]["rated_tph"], base, places=2)
        k45 = self.v("plant.line45_ktpa") * 1000 / 8760 / self.v("plant.availability")
        for n in (4, 5):
            self.assertAlmostEqual(self.by_id[f"{NS}:plant-line-{n}"]["attributes"]["rated_tph"], k45, places=2)
        k6 = self.v("plant.line6_ktpa") * 1000 / 8760 / self.v("plant.availability")
        self.assertAlmostEqual(self.by_id[f"{NS}:plant-line-6"]["attributes"]["rated_tph"], k6, places=2)
        rom = self.by_id[f"{NS}:rom-stockpile"]
        self.assertEqual(value_of(rom, "tonnes"), float(self.v("stockpile.start_t")))
        dam4 = self.by_id[f"{NS}:tsf-dam4"]
        self.assertEqual(dam4["attributes"]["capacity_t"], self.v("tsf.dam4_capacity_t"))
        self.assertEqual(dam4["attributes"]["capacity_m3"], self.v("tsf.dam4_capacity_m3"))
        self.assertAlmostEqual(value_of(dam4, "fill_pct") / 100, self.v("tsf.dam4_fill_start"))
        for n in (2, 3):
            self.assertEqual(value_of(self.by_id[f"{NS}:tsf-dam{n}"], "free_capacity_t"),
                             float(self.v("tsf.dam23_free_t")))
        self.assertEqual(self.by_id[f"{NS}:tsf-cell5"]["attributes"]["capacity_t"], self.v("tsf.measure_X1_t"))
        for t in self.things_of("tailings_dam"):
            self.assertEqual(t["attributes"]["bulk_density"], self.v("tsf.bulk_density"))

    def test_baseline_capacity_reference(self):
        # baseline tailings capacity of the reference table: free capacity / 3 years = 1057 kt/yr
        free_kt = value_of(self.by_id[f"{NS}:tailings"], "free_capacity_t") / 1000
        self.assertAlmostEqual(free_kt / self.v("tsf.min_years"), 1057, delta=1.0)
        # baseline haulage capacity with the formula of 2.3 reproduces 926 kt/yr (+-1 %)
        v = self.v
        hours = v("regime.working_days") * v("regime.shifts") * v("regime.shift_h")
        z = v("stope.centroid_baseline_m")
        trucks = [t for t in self.things_of("haul_truck") if value_of(t, "state") != "parked"]
        n_on = Counter(t["attributes"]["link_home_decline"].split("-")[1] for t in trucks)
        total = 0.0
        sin8 = __import__("math").sin(__import__("math").radians(v("decline.slope_deg")))
        for t in trucks:
            tu = t["attributes"]["link_home_decline"].split("-")[1]
            length_km = (v(f"decline.{tu}.portal_m") - z) / sin8 * v("decline.length_factor") / 1000
            s = v(f"decline.{tu}.surface_km")
            minutes = (v("truck.load_min") + v("truck.dump_min") + v("truck.manoeuvre_min")
                       + 60 * length_km / v("truck.speed_up_loaded_kmh")
                       + 60 * length_km / v("truck.speed_down_empty_kmh")
                       + 60 * s / v("truck.speed_flat_loaded_kmh") + 60 * s / v("truck.speed_flat_empty_kmh")
                       + v("haul.K_BAY") * (n_on[tu] - 1))
            total += (t["attributes"]["payload_t"] * 60 / minutes * hours
                      * (v("regime.productive_h") / v("regime.shift_h")) * v("truck.availability")
                      * v("haul.K_HAUL") / 1000)
        self.assertAlmostEqual(total, 926.4, delta=926.4 * 0.01)


class TestFileHygiene(unittest.TestCase):
    def test_files_utf8_lf_no_bom(self):
        for path in (MODEL / "params.json", MODEL / "registry.json", Path(__file__)):
            raw = path.read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), path.name)
            self.assertNotIn(b"\r", raw, path.name)
            raw.decode("utf-8")
            self.assertTrue(raw.endswith(b"\n"), path.name)


if __name__ == "__main__":
    unittest.main()
