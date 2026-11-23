"""Invented R5B scenarios and independent small matching oracle."""
import copy
import itertools
import unittest
from fractions import Fraction

import experimental_scenarios as scenarios
import experimental_xi as xi
import tactic
from test_experimental_xi import CAREER, fixture, matrix, assignment, real_tactic


def key(name):
    return CAREER + ":" + name


def target(name, codes, **kwargs):
    return fixture(name, codes, cohorts=["target"], **kwargs)


def report(m, objective="fm27v2", candidates=()):
    return scenarios.build_report(m, objective=objective, candidate_ids=[key(p) for p in candidates],
                                  signing_policy=scenarios.SIGNING_POLICY)


def recruit(r, name):
    return next(s for s in r["recruitment_scenarios"] if s["candidate_id"] == key(name))


def absent(r, name):
    return next(s for s in r["starter_loss_scenarios"] if s["removed_player_id"] == key(name))


def cascade():
    return [fixture("left", ["dl"], display=20), fixture("right", ["dl", "dr"], display=19),
            fixture("centre", ["dr", "dc"], display=18), fixture("centre2", ["dc"], display=18),
            fixture("reserve", ["dc"], display=17), fixture("direct", ["dl"], display=10)]


def oracle(m, objective, *, remove=None, sign=None):
    """Enumerate choices independently of the solver and scenario transform."""
    slots = [s["id"] for s in m["tactic"]["slots"]]
    gk = next(s["id"] for s in m["tactic"]["slots"] if s["selection_position"] == "gk")
    edges = {}
    for r in m["rows"]:
        p = r["player_id"]
        reasons = set(r["eligibility_reasons"])
        if p == sign:
            reasons.discard("not_active_squad")
        score = r["scores"][objective]
        if p != remove and not reasons and score is not None:
            edges[p, r["slot_id"]] = Fraction(score)
    options = [[None] + sorted(p for p in m["players"] if (p, s) in edges) for s in slots]
    best = None
    for choice in itertools.product(*options):
        selected = [p for p in choice if p is not None]
        if len(selected) != len(set(selected)):
            continue
        scores = {s: edges[p, s] for s, p in zip(slots, choice) if p is not None}
        rank = (-len(selected), -sum(v for s, v in scores.items() if s != gk),
                -scores.get(gk, Fraction(-1)), tuple((p is None, p or "") for p in choice))
        if best is None or rank < best[0]:
            best = rank, choice
    return list(best[1])


class ExperimentalScenarioTests(unittest.TestCase):
    def test_direct_signing_and_depth_only_and_unavailable(self):
        m = matrix([fixture("starter", ["stc"], display=15), fixture("keeper", ["gk"], keeper=True),
                    target("upgrade", ["stc"], display=19), target("backup", ["stc"], display=14),
                    target("wrong", ["stc"], keeper=True, display=20),
                    target("unavailable", ["stc"], availability="unavailable", display=20)])
        r = report(m, candidates=("upgrade", "backup", "wrong", "unavailable"))
        up = recruit(r, "upgrade")
        self.assertEqual(up["selected_slot_id"], "st")
        self.assertEqual(up["impact"]["outfield_score_change"], 4)
        self.assertEqual(up["impact"]["displaced_player_ids"], [key("starter")])
        self.assertTrue(recruit(r, "backup")["cover_without_xi_improvement"])
        for p in ("wrong", "unavailable"):
            self.assertFalse(recruit(r, p)["enters_xi"])
            self.assertFalse(recruit(r, p)["depth_improved"])
        self.assertNotIn(key("upgrade"), [a["player_id"] for a in r["baseline"]["assignments"]])

    def test_cascade_absence_and_unavoidable_vacancy(self):
        r = report(matrix(cascade()))
        event = absent(r, "left")
        self.assertEqual(event["replacement_assignment"]["player_id"], key("right"))
        self.assertGreaterEqual(event["impact"]["positional_change_count"], 2)
        self.assertIn(key("reserve"), event["impact"]["promoted_player_ids"])
        self.assertEqual(event["filled_slot_loss"], 0)
        self.assertAlmostEqual(event["outfield_score_loss"], 3)
        self.assertTrue(event["impact"]["weaker_slot_ids"])
        r = report(matrix([fixture("solo", ["stc"])]))
        event = absent(r, "solo")
        self.assertEqual(event["impact"]["newly_vacant_slot_ids"], ["st"])
        self.assertIsNone(event["outfield_score_loss"])
        self.assertEqual(event["filled_slot_loss"], 1)

    def test_versatile_signing_indirect_reassignment(self):
        people = cascade()[:4]
        people[0]["attrs"] = fixture("low", ["dl"], display=10)["attrs"]
        people += [fixture("pivot1", ["dm"], display=20), fixture("pivot2", ["dm"], display=20)]
        m = matrix(people + [target("versatile", ["dc", "dm"], display=17)])
        result = recruit(report(m, candidates=("versatile",)), "versatile")
        self.assertTrue(result["enters_xi"])
        self.assertGreaterEqual(result["impact"]["positional_change_count"], 2)
        self.assertTrue(result["impact"]["objective_improved"])

    def test_shared_cover_and_versatile_backup_loss(self):
        m = matrix([fixture("left", ["dl"], display=18), fixture("right", ["dr"], display=18),
                    fixture("utility", ["dl", "dr"], display=10)])
        r = report(m)
        depth = r["depth"]
        self.assertEqual(depth["bench_matching_capacity"]["outfield"], 1)
        dep = next(d for d in depth["bench_dependencies"] if d["player_id"] == key("utility"))
        self.assertEqual(dep["newly_uncovered_slot_ids"], ["lb", "rb"])
        self.assertEqual(dep["capacity_without_player"]["outfield"], 0)

    def test_goalkeeper_domain_and_cardinality_gain(self):
        m = matrix([fixture("st", ["stc"]), fixture("g", ["gk"], keeper=True, display=10),
                    target("g2", ["gk"], keeper=True, display=18)])
        e = recruit(report(m, candidates=("g2",)), "g2")
        self.assertEqual(e["impact"]["goalkeeper_score_change"], 8)
        self.assertEqual(e["impact"]["outfield_score_change"], 0)
        self.assertEqual([c["slot_id"] for c in e["impact"]["changes"]], ["gk"])
        m = matrix([fixture("st", ["stc"]), target("g2", ["gk"], keeper=True)])
        e = recruit(report(m, candidates=("g2",)), "g2")
        self.assertEqual(e["impact"]["filled_slot_change"], 1)
        self.assertIsNone(e["impact"]["goalkeeper_score_change"])

    def test_three_objective_reversals(self):
        m = matrix([fixture("base", ["stc"], raw=65, ca=140, display=15),
                    target("legacy", ["stc"], raw=45, ca=110, display=19),
                    target("rating", ["stc"], raw=85, ca=120, display=14),
                    target("ability", ["stc"], raw=55, ca=180, display=12)])
        comparison = scenarios.compare_objectives(m, candidate_ids=[key(n) for n in ("legacy", "rating", "ability")],
                                                 signing_policy=scenarios.SIGNING_POLICY)
        for objective, name in [("fm27v2", "legacy"), ("role_rating", "rating"), ("role_ability", "ability")]:
            r = comparison["reports"][objective]
            self.assertEqual([e["candidate_id"] for e in r["recruitment_scenarios"] if e["impact"]["objective_improved"]], [key(name)])
            self.assertEqual(r["baseline_matrix_sha256"], m["sha256"])

    def test_phase_weight_changes_recruitment_priority(self):
        p = fixture("base", ["dr"], raw=60)
        p["positions"]["dc"] = 14
        c = target("new", ["dr"], raw=80)
        config = real_tactic()
        for weights, expected in [({"ip": 1, "oop": 0}, False), ({"ip": 0, "oop": 1}, True)]:
            config["phase_weights"] = weights
            r = report(matrix([p, c], config), "role_rating", ("new",))
            self.assertEqual(recruit(r, "new")["impact"]["objective_improved"], expected)

    def test_missing_score_and_unsupported_build(self):
        m = matrix([fixture("base", ["stc"]), target("bad", ["stc"], game_build="27.1.0+2505117", database_version=3756),
                    target("missing", ["stc"], current_ability=None), target("ineligible", ["dr"], raw=90)])
        for objective in ("role_rating", "role_ability"):
            r = report(m, objective, ("bad", "missing", "ineligible"))
            self.assertEqual(recruit(r, "bad")["eligible_slot_ids"], [])
            self.assertNotIn("st", recruit(r, "ineligible")["eligible_slot_ids"])
            self.assertEqual("st" in recruit(r, "missing")["eligible_slot_ids"], objective == "role_rating")
            self.assertTrue(any(e["player_id"] == key("bad") and not e["build_compatible"] for e in r["unavailable_edges"]))
        # Even a self-consistent content hash cannot authorise unsupported scores.
        corrupted = copy.deepcopy(m)
        next(r for r in corrupted["rows"] if r["player_id"] == key("bad"))["scores"]["role_rating"] = 100
        corrupted.pop("sha256")
        corrupted["sha256"] = tactic.canonical_sha256(corrupted)
        with self.assertRaises(ValueError):
            report(corrupted, "role_rating", ("bad",))

    def test_exact_oracle_all_objectives_scenario_isolation_and_order(self):
        p = [fixture("a", ["dc", "dr"], display=15), fixture("b", ["dc"], display=12),
             fixture("c", ["dr"], display=11), target("new", ["dc", "dr"], display=17)]
        m = matrix(p)
        snapshot = copy.deepcopy(m)
        for objective in xi.OBJECTIVES:
            r = report(m, objective, ("new",))
            self.assertEqual(r, report(matrix(list(reversed(p))), objective, ("new",)))
            self.assertEqual([a["player_id"] for a in r["baseline"]["assignments"]], oracle(m, objective))
            for event in r["starter_loss_scenarios"]:
                self.assertEqual([a["player_id"] for a in event["reoptimised"]["assignments"]],
                                 oracle(m, objective, remove=event["removed_player_id"]))
            e = recruit(r, "new")
            self.assertEqual([a["player_id"] for a in e["reoptimised"]["assignments"]], oracle(m, objective, sign=key("new")))
            for event in e["original_starter_absences"]:
                self.assertEqual([a["player_id"] for a in event["signing_without_player"]["assignments"]],
                                 oracle(m, objective, sign=key("new"), remove=event["removed_player_id"]))
        self.assertEqual(m, snapshot)

    def test_policy_and_scope_validation(self):
        m = matrix([fixture("st", ["stc"]), target("new", ["stc"])])
        with self.assertRaises(ValueError):
            scenarios.build_report(m, objective="fm27v2", candidate_ids=[key("new")])
        for candidates in (("st",), ("missing",), ("new", "new")):
            with self.assertRaises(ValueError):
                report(m, candidates=candidates)
        m["rows"][0]["source"] = {"kind": "save_export"}
        m.pop("sha256")
        m["sha256"] = tactic.canonical_sha256(m)
        with self.assertRaises(ValueError):
            report(m)

    def test_operational_report_hashes_unchanged(self):
        from test_optimal_xi import person
        from test_squad_depth import report as operational_depth
        from test_signing_simulations import build as operational_signing, target as operational_target
        p = [person("left", ["dl"], score=18), person("right", ["dr"], score=17),
             person("utility", ["dl", "dr"], score=10), operational_target("new", ["dl"], score=19)]
        def normalise(v):
            if isinstance(v, float):
                return round(v, 9) or 0.0
            if isinstance(v, dict):
                return {k: normalise(x) for k, x in v.items()}
            if isinstance(v, list):
                return [normalise(x) for x in v]
            return v
        report(matrix([fixture("left", ["dl"]), target("new", ["dl"])]), candidates=("new",))
        depth = operational_depth(p)
        signing = operational_signing(p)
        self.assertEqual([tactic.canonical_sha256(normalise(r)) for r in (depth["baseline"], depth, signing)], [
            "585f891645cebae4c511b077758082f32fc7275b1ff56e75dee68fc987645204",
            "1ca438b28cd27a1c08c4d0bd922044ceea80791c3c03905f354097c737363af6",
            "c9a8bd726342c2c42f72b2b41012fd77d4ec18931ef1a2ae77655c7dd1c282dc"])
