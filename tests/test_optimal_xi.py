"""Invented XI fixtures and independent exhaustive matching oracle."""
import itertools
import json
import random
import tomllib
import unittest
from pathlib import Path

import formation
import optimal_xi as xi
import scoring
import tactical_assessment as tactical


ROOT = Path(__file__).resolve().parents[1]
MODEL = tomllib.loads((ROOT / "weights/fm27v2.toml").read_text(encoding="utf-8"))
DEFAULT = formation.load_formation(ROOT / "formations/default.toml", MODEL)
ASYM = formation.load_formation(ROOT / "formations/asymmetric-4231.toml", MODEL)


def person(key, codes, *, score=12, keeper=False, cohorts=("squad",), availability="available", loan="permanent", name=None):
    attrs = {a: score for profile in [MODEL["gk"], *MODEL["outfield"].values()] for a in profile}
    raw = {"name": name or key, **{"positions_" + c: 1 for c in formation.FM_POSITION_CODES}}
    raw.update({"positions_" + c: 20 for c in codes})
    return {"player_id": key, "name": raw["name"], "club": "Invented club", "keeper": keeper, "attrs": attrs,
            "raw": raw, "cohorts": cohorts, "availability": availability, "loan_state": loan,
            "last_seen_game_date": "2027-01-01"}


def report(people, shape=DEFAULT, benchmark=None, policy=None):
    assessment = tactical.build_assessments(shape, MODEL, people, codes=formation.FM_POSITION_CODES,
                                            scorer=scoring.weighted, career="invented", formation_source="fixture",
                                            model_sha256="model")
    return xi.build_optimal_xi(shape, assessment, benchmark, policy=policy)


def eleven(shape):
    return [person(slot["id"], [slot["positions"][0]], keeper=slot["profile"] == "GK") for slot in shape["slots"]]


def assignments(result):
    return {r["slot_id"]: r for r in result["assignments"]}


class OptimalXITests(unittest.TestCase):
    def test_complete_433_and_two_cbs(self):
        people = eleven(DEFAULT)
        result = report(people)
        self.assertEqual(result["solver"]["status"], "complete")
        self.assertEqual([a["slot_id"] for a in result["assignments"]], [s["id"] for s in DEFAULT["slots"]])
        self.assertEqual(len({a["player_id"] for a in result["assignments"]}), 11)
        self.assertEqual(assignments(result)["lcb"]["player_id"], "lcb")
        self.assertEqual(assignments(result)["rcb"]["player_id"], "rcb")
        self.assertAlmostEqual(result["outfield_total"], 120)
        self.assertAlmostEqual(result["goalkeeper_total"], 12)

    def test_asymmetric_inverted_back_and_left_right(self):
        people = eleven(ASYM)
        result = report(people, ASYM)
        rb = assignments(result)["rb"]
        self.assertEqual(result["solver"]["status"], "complete")
        self.assertEqual(rb["player_id"], "rb")
        self.assertEqual(rb["assessment"]["ip"]["familiarity"]["rating"], 1)
        self.assertEqual(rb["assessment"]["oop"]["familiarity"]["rating"], 20)
        self.assertIn("ip_familiarity_below_threshold", rb["warnings"])
        self.assertIsNone(rb["assessment"]["ip"]["observed_role_suitability"])
        only_left = report([person("left", ["dl"])], ASYM)
        self.assertEqual(assignments(only_left)["lb"]["player_id"], "left")
        self.assertIsNone(assignments(only_left)["rb"]["player_id"])

    def test_greedy_loses_and_no_duplicate_player(self):
        edges = {"versatile": {"a": 20, "b": 19}, "specialist": {"a": 18}, "backup": {"b": 1}}
        self.assertEqual(xi.solve_assignment(["a", "b"], edges), {"a": "specialist", "b": "versatile"})
        one = xi.solve_assignment(["a", "b"], {"one": {"a": 10, "b": 10}})
        self.assertEqual(one, {"a": "one", "b": None})
        result = report([person("only", ["dc", "dr"])])
        self.assertEqual(result["solver"]["filled_slots"], 1)
        self.assertIn("eligible_players_assigned_elsewhere", {a["vacancy_reason"] for a in result["assignments"]})

    def test_selection_mode_and_explicit_phase_gate_are_independent(self):
        rb = person("rb", ["dr"])
        for mode in ("strict", "relaxed"):
            contextual = report([rb], ASYM, policy={"mode": mode})
            self.assertEqual(assignments(contextual)["rb"]["player_id"], "rb")
            self.assertEqual(contextual["eligibility_policy"]["mode"], mode)
            gated = report([rb], ASYM, policy={"mode": mode, "phase_eligibility": "require_weighted_phases"})
            self.assertIsNone(assignments(gated)["rb"]["player_id"])
            self.assertIn("ip_phase_familiarity_not_confirmed", gated["excluded_or_uncertain_players"][0]["slot_exclusions"]["rb"])
        unknown = person("unknown", ["dr"])
        unknown["raw"]["positions_dc"] = ""
        self.assertIsNone(assignments(report([unknown], ASYM, policy={"phase_eligibility": "require_weighted_phases"}))["rb"]["player_id"])
        alternate = person("wide", ["mr"])
        self.assertIsNone(assignments(report([alternate], policy={"version": 1}))["rw"]["player_id"])
        relaxed = assignments(report([alternate], policy={"mode": "relaxed"}))["rw"]
        self.assertEqual(relaxed["eligibility_position"], "mr")
        self.assertEqual(relaxed["selection_position"], "amr")
        self.assertIn("relaxed_alternative_position_eligibility", relaxed["warnings"])
        import copy
        zero = copy.deepcopy(ASYM)
        zero["phase_weights"] = {"ip": 0.0, "oop": 1.0}
        self.assertEqual(assignments(report([rb], zero, policy={"phase_eligibility": "require_weighted_phases"}))["rb"]["player_id"], "rb")

    def test_loans_cohorts_availability(self):
        people = [person("incoming", ["dc"], loan="incoming"), person("outgoing", ["dc"], score=20, loan="outgoing", availability="unavailable"),
                  person("target", ["dc"], score=20, cohorts=("target",)), person("both", ["dc"], cohorts=("squad", "target")),
                  person("uncertain", ["dc"], score=20, availability="unknown")]
        result = report(people)
        self.assertEqual({a["player_id"] for a in result["assignments"] if a["player_id"]}, {"incoming", "both"})
        rejected = {p["player_id"]: p["slot_exclusions"]["lcb"] for p in result["excluded_or_uncertain_players"]}
        self.assertIn("not_active_squad", rejected["target"])
        self.assertIn("unavailable", rejected["outgoing"])
        self.assertIn("unknown_availability", rejected["uncertain"])
        permissive = report(people, policy={"allow_unknown_availability": True})
        self.assertIn("uncertain", {a["player_id"] for a in permissive["assignments"]})

    def test_category_unknown_and_incomplete_attributes(self):
        category = person("category", [])
        category["raw"].update(positions_dr="", accomplished_positions="DR")
        unknown = person("unknown", [], score=20)
        unknown["raw"]["positions_dr"] = ""
        incomplete = person("incomplete", ["dr"], score=20)
        incomplete["attrs"].clear()
        result = report([category, unknown, incomplete])
        rb = assignments(result)["rb"]
        self.assertEqual(rb["player_id"], "category")
        self.assertIsNone(rb["assessment"]["accepted_positions"]["dr"]["rating"])
        self.assertEqual(rb["assessment"]["accepted_positions"]["dr"]["lower_bound"], 15)
        self.assertIsNone(rb["assessment"]["combined_position_fit"])
        self.assertEqual(report([category], policy={"minimum_familiarity": 16})["solver"]["status"], "infeasible")
        self.assertEqual(report([category], policy={"allow_category_evidence": False})["solver"]["status"], "infeasible")
        self.assertIn("incomplete_attribute_profile", next(e for e in result["excluded_or_uncertain_players"] if e["player_id"] == "incomplete")["slot_exclusions"]["rb"])

    def test_keeper_separation_and_infeasible(self):
        people = [person("keeper", ["dc", "gk"], keeper=True), person("field", ["gk", "dc"], score=20),
                  person("better_keeper", ["gk"], keeper=True, score=18)]
        result = report(people)
        self.assertEqual(assignments(result)["gk"]["player_id"], "better_keeper")
        self.assertEqual(assignments(result)["lcb"]["player_id"], "field")
        self.assertAlmostEqual(result["goalkeeper_total"], 18)
        self.assertAlmostEqual(result["outfield_total"], 20)
        empty = report([])
        self.assertEqual(empty["solver"]["status"], "infeasible")
        self.assertEqual(len(empty["assignments"]), 11)
        self.assertIsNone(empty["goalkeeper_total"])

    def test_namesakes_input_order_and_ties(self):
        people = [person("career:2", ["dc"], name="Same Name"), person("career:1", ["dc"], name="Same Name")]
        a, b = report(people), report(list(reversed(people)))
        self.assertEqual(json.dumps(a), json.dumps(b))
        self.assertEqual(assignments(a)["lcb"]["player_id"], "career:1")
        self.assertEqual(assignments(a)["rcb"]["player_id"], "career:2")

    def test_exhaustive_oracle(self):
        rng = random.Random(17)
        slots = ["a", "b", "c"]
        players = ["p0", "p1", "p2", "p3"]
        for _ in range(80):
            edges = {p: {s: rng.randrange(1, 6) for s in slots if rng.random() < .6} for p in players}
            candidates = []
            for choice in itertools.product([*players, None], repeat=len(slots)):
                used = [p for p in choice if p is not None]
                if len(used) != len(set(used)) or any(p is not None and s not in edges[p] for s, p in zip(slots, choice)):
                    continue
                score = sum(edges[p][s] for s, p in zip(slots, choice) if p is not None)
                candidates.append((-len(used), -score, tuple(p or "~" for p in choice), choice))
            best = min(candidates)[3]
            self.assertEqual(xi.solve_assignment(slots, edges), dict(zip(slots, best)))
        # Full cardinality outranks score; binary float sums are not rounded to display precision.
        self.assertEqual(xi.solve_assignment(["a", "b"], {"x": {"a": 20, "b": 1}, "y": {"a": 1}}), {"a": "y", "b": "x"})

    def test_benchmarks_context_only_and_stale(self):
        people = [person("a", ["dc"])]
        base = report(people)
        benchmark = {"version": 1, "status": "available", "career": "invented", "game_date": "2027-01-01",
                     "scoring_model": base["scoring_model"], "competition": {"id": "100"}, "extraction_game_date": "2026-12-15",
                     "comparisons": [{"player_id": "a", "profile": "CB", "reason": None, "percentile": 70,
                                      "sample_size": 40, "season_start_year": 2026, "difference_from_median": 1, "warnings": []}]}
        self.assertIsNone(assignments(report(people, benchmark=benchmark))["lcb"]["league_benchmark"])
        benchmark["native_comparisons"] = [dict(benchmark["comparisons"][0], native_position="dc", reference_population="native_position")]
        contextual = report(people, benchmark=benchmark)
        self.assertEqual(assignments(contextual)["lcb"]["league_benchmark"]["percentile"], 70)
        self.assertEqual(contextual["outfield_total"], base["outfield_total"])
        for stale in (dict(benchmark, game_date="2026-12-31"), dict(benchmark, career="other"), dict(benchmark, extraction_game_date="2026-11-01")):
            self.assertIsNone(assignments(report(people, benchmark=stale))["lcb"]["league_benchmark"])
        self.assertIsNone(assignments(base)["lcb"]["league_benchmark"])

    def test_html_escaped_and_policy_validated(self):
        view = xi.render_html(report([person("test", ["dc"], name="<script>bad</script>")]))
        self.assertIn("&lt;script&gt;", view)
        self.assertNotIn("<script>", view)
        self.assertIn("VACANT", view)
        for policy in ({"version": 3}, {"minimum_familiarity": 0}, {"allow_category_evidence": 1}, {"extra": True}):
            with self.assertRaises(ValueError):
                xi.eligibility_policy(policy)


if __name__ == "__main__":
    unittest.main()
