"""R5A invented comparisons; no save-derived observations."""
import copy
import itertools
import unittest

import experimental_xi as exp
import optimal_xi
import role_ability
import tactic
from test_role_ability import CATALOGUE, real_tactic, player
from test_optimal_xi import MODEL, person, report


CAREER = "invented:r5a"


def fixture(key, codes, *, raw=50, ca=150, display=12, keeper=False, **overrides):
    p = player(raw, ca, dict.fromkeys(codes, 20))
    p.update(career=CAREER, player_id=CAREER + ":" + key,
             source={"kind": "invented_fixture"}, keeper=keeper,
             cohorts=["squad"], availability="available",
             attrs=person(key, codes, score=display, keeper=keeper)["attrs"])
    p.update(overrides)
    return p


def matrix(people, config=None, policy=None):
    return exp.build_matrix(config or real_tactic(), CATALOGUE, MODEL, people,
                            career=CAREER, policy=policy)


def assignment(result, slot):
    return next(r for r in result["assignments"] if r["slot_id"] == slot)


def row(m, key, slot):
    return next(r for r in m["rows"] if r["player_id"] == CAREER + ":" + key and r["slot_id"] == slot)


def comparison_fixture():
    return [fixture("legacy", ["stc"], raw=45, ca=110, display=19),
            fixture("rating", ["stc"], raw=85, ca=120, display=14),
            fixture("ability", ["stc"], raw=55, ca=180, display=12),
            fixture("keeper", ["gk"], keeper=True)]


class ExperimentalTests(unittest.TestCase):
    def test_objective_reversal_and_domain(self):
        m = matrix(comparison_fixture())
        result = exp.compare(m)["results"]
        for objective, expected in [("fm27v2", "legacy"), ("role_rating", "rating"),
                                    ("role_ability", "ability")]:
            self.assertEqual(assignment(result[objective], "st")["player_id"], CAREER + ":" + expected)
            self.assertEqual(assignment(result[objective], "gk")["player_id"], CAREER + ":keeper")
            self.assertEqual(result[objective]["filled_slots"], 2)
        self.assertGreater(row(m, "rating", "st")["scores"]["role_rating"],
                           row(m, "ability", "st")["scores"]["role_rating"])
        self.assertLess(row(m, "rating", "st")["scores"]["role_ability"],
                        row(m, "ability", "st")["scores"]["role_ability"])

    def test_deterministic_integrity_and_explicit_objective(self):
        players = comparison_fixture()
        m = matrix(players)
        self.assertEqual(m, matrix(list(reversed(players))))
        self.assertEqual(len(m["rows"]), 44)
        self.assertEqual(m["model_sha256"], role_ability.MODEL_SHA256)
        self.assertEqual(m["tactic_sha256"], tactic.tactic_sha256(m["tactic"]))
        with self.assertRaises(ValueError):
            exp.optimise(m, objective="auto")
        broken = copy.deepcopy(m)
        broken["rows"].pop()
        with self.assertRaises(ValueError):
            exp.optimise(broken, objective="role_rating")
        with self.assertRaises(ValueError):
            matrix(players + players[:1])

    def test_unsupported_build_and_missing_ca_no_fallback(self):
        bad = fixture("bad", ["stc"], game_build="27.1.0+2505117", database_version=3756)
        m = matrix([bad])
        self.assertEqual(row(m, "bad", "st")["model_unavailable_reason"], "unsupported_game_build")
        self.assertEqual(exp.optimise(m, objective="role_rating")["filled_slots"], 0)
        self.assertEqual(exp.optimise(m, objective="fm27v2")["filled_slots"], 1)
        missing = fixture("missing", ["stc"], current_ability=None)
        m = matrix([missing])
        self.assertIsNotNone(row(m, "missing", "st")["scores"]["role_rating"])
        self.assertIsNone(row(m, "missing", "st")["scores"]["role_ability"])
        self.assertEqual(exp.optimise(m, objective="role_ability")["filled_slots"], 0)

    def test_unresolved_phase_and_zero_weight(self):
        config = real_tactic()
        st = next(s for s in config["slots"] if s["id"] == "st")
        st["oop"] = {"position": "stc", "side": "centre", "role_status": "unknown",
                     "role_reason": "invented missing role"}
        p = fixture("st", ["stc"])
        m = matrix([p], config)
        self.assertIsNone(row(m, "st", "st")["scores"]["role_rating"])
        self.assertEqual(exp.optimise(m, objective="fm27v2")["filled_slots"], 1)
        config["phase_weights"] = {"ip": 1, "oop": 0}
        m = matrix([p], config)
        self.assertEqual(row(m, "st", "st")["scores"]["role_rating"], row(m, "st", "st")["ip"]["role_rating"])
        self.assertEqual(exp.optimise(m, objective="role_ability")["filled_slots"], 1)

    def test_eligibility_separate_from_rating(self):
        p = fixture("rb", ["dr"])
        m = matrix([p])
        self.assertEqual(row(m, "rb", "rb")["eligibility_reasons"], [])
        self.assertIsNotNone(row(m, "rb", "rb")["scores"]["role_rating"])
        m = matrix([p], policy={"phase_eligibility": "require_weighted_phases"})
        self.assertIn("ip_phase_familiarity_not_confirmed", row(m, "rb", "rb")["eligibility_reasons"])
        m = matrix([fixture("alt", ["wbr"])], policy={"mode": "relaxed"})
        self.assertEqual(row(m, "alt", "rb")["eligibility_position"], "wbr")
        for p in [fixture("out", ["stc"], availability="unavailable"),
                  fixture("target", ["stc"], cohorts=["targets"]),
                  fixture("wrong", ["stc"], keeper=True)]:
            self.assertEqual(exp.optimise(matrix([p]), objective="role_rating")["filled_slots"], 0)

    def test_phase_weight_reversal_without_cardinality_change(self):
        a = fixture("a", ["dr"], raw=60)
        a["positions"]["dc"] = 14
        b = fixture("b", ["dr"], raw=80)
        config = real_tactic()
        for weights, expected in [({"ip": 1, "oop": 0}, "a"), ({"ip": 0, "oop": 1}, "b")]:
            config["phase_weights"] = weights
            m = matrix([a, b], config)
            result = exp.optimise(m, objective="role_rating")
            self.assertEqual(result["filled_slots"], 1)
            self.assertEqual(assignment(result, "rb")["player_id"], CAREER + ":" + expected)

    def test_missing_legacy_profile_does_not_block_role_objective(self):
        p = fixture("st", ["stc"], attrs={})
        m = matrix([p])
        self.assertEqual(exp.optimise(m, objective="fm27v2")["filled_slots"], 0)
        self.assertEqual(exp.optimise(m, objective="role_rating")["filled_slots"], 1)
        self.assertEqual(exp.optimise(m, objective="role_ability")["filled_slots"], 1)

    def test_complete_and_missing_raw_attributes(self):
        config = real_tactic()
        players = [fixture(s["id"], [s["selection_position"]], keeper=s["selection_position"] == "gk")
                   for s in config["slots"]]
        for result in exp.compare(matrix(players, config))["results"].values():
            self.assertEqual(result["status"], "complete")
            self.assertEqual(len({a["player_id"] for a in result["assignments"]}), 11)
        p = fixture("missing", ["stc"], raw_attributes={})
        m = matrix([p])
        self.assertIsNone(row(m, "missing", "st")["scores"]["role_rating"])
        self.assertTrue(row(m, "missing", "st")["score_unavailable_reasons"]["role_rating"])

    def test_legacy_parity_and_exhaustive_assignment(self):
        config = real_tactic()
        people = [fixture("a", ["dc", "dr"], display=15), fixture("b", ["dc"], display=12),
                  fixture("c", ["dr"], display=11)]
        m = matrix(people, config)
        shape = {"version": 1, "name": config["name"], "phase_weights": config["phase_weights"],
                 "slots": [{**{k:s[k] for k in ("id","label","side","selection_position")},
                            "positions": s.get("positions", [s["selection_position"]]),
                            "profile": s["legacy_profile"],
                            **{phase: {"position": s[phase]["position"], "side": s[phase]["side"], "role": None}
                               for phase in ("ip","oop")}} for s in config["slots"]]}
        baseline = report([person(p["player_id"], [k for k,v in p["positions"].items() if v == 20],
                                  score=p["attrs"][next(iter(p["attrs"]))]) for p in people], shape)
        actual = exp.optimise(m, objective="fm27v2")
        self.assertEqual([r["player_id"] for r in actual["assignments"]], [r["player_id"] for r in baseline["assignments"]])
        self.assertEqual(actual["outfield_total"], baseline["outfield_total"])
        for objective in exp.OBJECTIVES:
            result = exp.optimise(m, objective=objective)
            ids = ["lcb", "rcb", "rb"]
            edges = {(r["player_id"], r["slot_id"]): r["scores"][objective] for r in m["rows"]
                     if not r["eligibility_reasons"] and r["scores"][objective] is not None}
            candidates = []
            for choices in itertools.product([None]+m["players"], repeat=3):
                used = [p for p in choices if p is not None]
                if len(set(used)) != len(used) or any(p is not None and (p,s) not in edges for p,s in zip(choices,ids)):
                    continue
                candidates.append((len(used), sum(edges[p,s] for p,s in zip(choices,ids) if p is not None)))
            self.assertEqual((result["filled_slots"], result["outfield_total"]), max(candidates))

    def test_source_restrictions(self):
        p = fixture("st", ["stc"], source={"kind": "save_export"})
        with self.assertRaises(ValueError):
            matrix([p])
        with self.assertRaises(ValueError):
            exp.build_matrix(real_tactic(), CATALOGUE, MODEL, [], career="real")
