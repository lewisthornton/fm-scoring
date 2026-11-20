"""Invented formations and strict validation of the versioned contract."""
import copy
import json
import tomllib
import unittest
from pathlib import Path

import formation
import score


ROOT = Path(__file__).resolve().parents[1]
FORMATIONS = ROOT / "formations"
MODEL = tomllib.loads((ROOT / "weights/fm27v2.toml").read_text(encoding="utf-8"))
PROFILES = set(MODEL["outfield"]) | {"GK"}


class FormationTests(unittest.TestCase):
    def setUp(self):
        self.config = tomllib.loads((FORMATIONS / "default.toml").read_text(encoding="utf-8"))

    def test_default_conventional_433_and_existing_vocabulary(self):
        tactic = formation.load_formation(FORMATIONS / "default.toml", MODEL)
        self.assertEqual(tactic["version"], 1)
        self.assertEqual(tactic["name"], "Conventional 4-3-3")
        self.assertEqual(tactic["phase_weights"], {"ip": 0.5, "oop": 0.5})
        self.assertEqual(len(tactic["slots"]), 11)
        self.assertEqual({s["profile"] for s in tactic["slots"]}, PROFILES)
        self.assertEqual(formation.FM_POSITION_CODES, set(score.FM_POSITIONS))
        for phase in ("ip", "oop"):
            positions = [s[phase]["position"] for s in tactic["slots"]]
            self.assertEqual(positions.count("dc"), 2)
            self.assertEqual(positions.count("mc"), 2)
            self.assertEqual(set(positions), {"gk", "dl", "dc", "dr", "dm", "mc", "aml", "amr", "stc"})
        centre_backs = [s for s in tactic["slots"] if s["profile"] == "CB"]
        self.assertEqual([s["id"] for s in centre_backs], ["lcb", "rcb"])
        self.assertEqual([s["side"] for s in centre_backs], ["left", "right"])
        self.assertTrue(all(s[p]["suitability"] is None and s[p]["role"] is None
                            for s in tactic["slots"] for p in ("ip", "oop")))

    def test_asymmetric_4231_models_the_same_slots_in_both_phases(self):
        tactic = formation.load_formation(FORMATIONS / "asymmetric-4231.toml", MODEL)
        slots = {s["id"]: s for s in tactic["slots"]}
        self.assertEqual(len(slots), 11)
        self.assertEqual(tactic["phase_weights"], {"ip": 0.65, "oop": 0.35})
        self.assertEqual(slots["lb"]["ip"]["position"], "wbl")
        self.assertEqual(slots["rb"]["ip"]["position"], "dc")
        self.assertEqual(slots["lb"]["oop"]["position"], "dl")
        self.assertEqual(slots["rb"]["oop"]["position"], "dr")
        self.assertEqual(slots["rb"]["selection_position"], "dr")
        self.assertNotEqual(slots["lb"]["ip"]["role"], slots["rb"]["ip"]["role"])
        self.assertNotEqual(slots["lcb"]["oop"]["role"], slots["rcb"]["oop"]["role"])
        self.assertEqual(slots["am"]["ip"]["role"], "Custom pocket creator")
        self.assertNotEqual(slots["am"]["ip"]["role"], slots["am"]["oop"]["role"])
        self.assertNotEqual([s["ip"]["position"] for s in slots.values()],
                            [s["oop"]["position"] for s in slots.values()])
        self.assertTrue(all(s[p]["suitability"] is None for s in slots.values() for p in ("ip", "oop")))

    def test_explicit_selection_position_is_validated(self):
        slot = next(s for s in self.config["slots"] if s["id"] == "rw")
        slot["selection_position"] = "mr"
        tactic = formation.validate_formation(self.config, PROFILES)
        self.assertEqual(next(s for s in tactic["slots"] if s["id"] == "rw")["selection_position"], "mr")
        slot["selection_position"] = "ml"
        with self.assertRaisesRegex(ValueError, "selection_position"):
            formation.validate_formation(self.config, PROFILES)
        slot["selection_position"] = "mr"
        slot["profile"] = "CB"
        with self.assertRaisesRegex(ValueError, "profile mapping"):
            formation.validate_formation(self.config, PROFILES)

    def test_custom_labels_phase_side_and_optional_responsibilities(self):
        self.config["slots"][1]["label"] = "My unusual flank"
        self.config["slots"][1]["ip"] = {"position": "mc", "side": "centre", "role": "Custom rôle"}
        del self.config["slots"][1]["oop"]
        slot = formation.validate_formation(self.config, PROFILES)["slots"][1]
        self.assertEqual(slot["id"], "lb")
        self.assertEqual(slot["label"], "My unusual flank")
        self.assertEqual(slot["positions"], ["dl", "wbl"])
        self.assertEqual(slot["ip"], {"position": "mc", "side": "centre", "role": "Custom rôle", "suitability": None})
        self.assertEqual(slot["oop"], dict.fromkeys(("position", "side", "role", "suitability")))

    def test_serialisation_is_deterministic_and_keeps_declared_order(self):
        self.config["slots"].reverse()
        before = copy.deepcopy(self.config)
        first = formation.validate_formation(self.config, PROFILES)
        second = formation.validate_formation(self.config, PROFILES)
        self.assertEqual(self.config, before)
        self.assertEqual(json.dumps(first, allow_nan=False), json.dumps(second, allow_nan=False))
        self.assertEqual(json.loads(json.dumps(first, allow_nan=False)), first)
        self.assertEqual([s["id"] for s in first["slots"]], [s["id"] for s in self.config["slots"]])

    def test_invalid_configuration_fields(self):
        cases = [
            ("duplicate slot ID", lambda c: c["slots"][1].update(id="gk")),
            ("exactly 11", lambda c: c["slots"].pop()),
            ("exactly 11", lambda c: c["slots"].append(copy.deepcopy(c["slots"][0]))),
            ("exactly 11", lambda c: c.update(slots={})),
            ("positions", lambda c: c["slots"][1].update(positions=["unknown"])),
            ("positions", lambda c: c["slots"][1].update(positions=[])),
            ("positions", lambda c: c["slots"][1].update(positions=["dl", "dl"])),
            ("positions", lambda c: c["slots"][1].update(positions="dl")),
            ("profile", lambda c: c["slots"][1].update(profile="Fake")),
            ("side", lambda c: c["slots"][1].update(side="middle")),
            ("ip.side", lambda c: c["slots"][1]["ip"].update(side="middle")),
            ("ip.position", lambda c: c["slots"][1]["ip"].update(position="fake")),
            ("unknown fields", lambda c: c["slots"][1].update(defending={})),
            ("ip.role", lambda c: c["slots"][1]["ip"].update(role=15)),
            ("ip.role", lambda c: c["slots"][1]["ip"].update(role=" ")),
            ("ip", lambda c: c["slots"][1].update(ip="Wing-back")),
            ("missing fields", lambda c: c["slots"][1].update(ip={"role": "No position"})),
            ("unknown fields", lambda c: c["slots"][1]["ip"].update(suitability=0)),
            ("version", lambda c: c.update(version=2)),
            ("version", lambda c: c.update(version=True)),
            ("version", lambda c: c.update(version="1")),
            ("missing fields", lambda c: c.pop("version")),
            ("machine ID", lambda c: c["slots"][1].update(id="Left Back")),
            ("label", lambda c: c["slots"][1].update(label="")),
            ("missing fields", lambda c: c["slots"][1].pop("profile")),
            ("GK profile", lambda c: c["slots"][0].update(profile="CB")),
            ("exactly one GK", lambda c: c["slots"][0].update(
                profile="CB", positions=["dc"], ip={"position": "dc"}, oop={"position": "dc"})),
            ("goalkeeper and outfield", lambda c: c["slots"][1]["ip"].update(position="gk")),
        ]
        for expected, mutate in cases:
            with self.subTest(expected=expected, mutate=mutate):
                config = copy.deepcopy(self.config)
                mutate(config)
                with self.assertRaisesRegex(ValueError, expected):
                    formation.validate_formation(config, PROFILES)

    def test_invalid_phase_weights(self):
        cases = [
            {"ip": -1, "oop": 1}, {"ip": float("nan"), "oop": 1},
            {"ip": float("inf"), "oop": 1}, {"ip": 0, "oop": 0},
            {"ip": 1e308, "oop": 1e308}, {"ip": True, "oop": 1},
            {"ip": "0.5", "oop": 1}, {"ip": 1}, {"ip": 1, "oop": 1, "other": 1},
        ]
        for value in cases:
            with self.subTest(value=value):
                config = copy.deepcopy(self.config)
                config["phase_weights"] = value
                with self.assertRaisesRegex(ValueError, "phase_weights"):
                    formation.validate_formation(config, PROFILES)
        self.config["phase_weights"] = {"ip": 0, "oop": 2}
        self.assertEqual(formation.validate_formation(self.config, PROFILES)["phase_weights"], {"ip": 0.0, "oop": 2.0})

    def test_profile_references_must_exist_in_selected_model(self):
        model = {"outfield": {"CB": MODEL["outfield"]["CB"]}, "gk": MODEL["gk"]}
        with self.assertRaisesRegex(ValueError, "profile"):
            formation.load_formation(FORMATIONS / "default.toml", model)


if __name__ == "__main__":
    unittest.main()
