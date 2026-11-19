"""Frozen numerical vectors captured before the shared scoring refactor."""
import sys
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "integrations" / "rangers"))
import score
import scoring
import rangers_fm_scoring_bridge as bridge

MODEL = tomllib.loads((ROOT / "weights/fm27v2.toml").read_text(encoding="utf-8"))
ATTRS = {
    "Acceleration": 4, "Aerial Reach": 11, "Aggression": 18, "Agility": 5,
    "Anticipation": 12, "Balance": 19, "Bravery": 6, "Command of Area": 13,
    "Communication": 20, "Composure": 7, "Concentration": 14, "Consistency": 1,
    "Crossing": 8, "Decisions": 15, "Determination": 2, "Dirtiness": 9,
    "Dribbling": 16, "Eccentricity": 3, "Finishing": 10, "First Touch": 17,
    "Flair": 4, "Handling": 11, "Heading": 18, "Important Matches": 5,
    "Injury Proneness": 12, "Jumping Reach": 19, "Kicking": 6, "Long Shots": 13,
    "Marking": 20, "Natural Fitness": 7, "Off The Ball": 14, "One on Ones": 1,
    "Pace": 8, "Passing": 15, "Positioning": 2, "Pressure": 9, "Reflexes": 16,
    "Rushing Out": 3, "Stamina": 10, "Strength": 17, "Tackling": 4, "Teamwork": 11,
    "Technique": 18, "Throwing": 5, "Vision": 12, "Work Rate": 19,
}
PARTIAL = {"Pace": 15, "Acceleration": 7, "Agility": 18, "Reflexes": 10}
PROFILES = {"GK": MODEL["gk"], **MODEL["outfield"]}
EXPECTED_WEIGHTED = {
    "GK": 9.649122807017545, "FB": 10.64516129032258, "CB": 11.387096774193548,
    "6": 11.129032258064516, "wing": 11.129032258064516,
    "10": 11.628571428571428, "9": 11.947368421052632,
}


class ScoringTests(unittest.TestCase):
    def test_native_public_api_reexports_shared_implementations(self):
        for name in ("weighted", "curve_value", "curve_scores", "win_score", "pts_value", "pts_score", "PTS_LEVELS"):
            self.assertIs(getattr(score, name), getattr(scoring, name))

    def test_weighted_complete_native_and_bridge(self):
        self.assertEqual(scoring.weighted(ATTRS, PROFILES), EXPECTED_WEIGHTED)
        for role, profile in PROFILES.items():
            with self.subTest(role=role):
                self.assertEqual(bridge.score(ATTRS, profile), EXPECTED_WEIGHTED[role])

    def test_weighted_incomplete_native_and_bridge(self):
        attrs = {key: value for key, value in ATTRS.items() if key != "Crossing"}
        expected = {role: EXPECTED_WEIGHTED[role] for role in ("GK", "CB", "6", "9")}
        self.assertEqual(scoring.weighted(attrs, PROFILES), expected)
        for role, profile in PROFILES.items():
            self.assertEqual(bridge.score(attrs, profile), expected.get(role))
        self.assertEqual(scoring.weighted({}, PROFILES), {})
        self.assertIsNone(bridge.score({}, MODEL["gk"]))

    def test_curve_interpolation_and_extrapolation(self):
        for level, expected in zip((1, 3.5, 6, 9, 12, 15, 18, 20),
                                   (-40.0, -33.4, -26.8, -13.4, 0.0, 9.7, 19.4, 25.866666666666664)):
            with self.subTest(level=level):
                self.assertAlmostEqual(scoring.curve_value(MODEL["win"]["Pace"], level), expected, places=12)

    def test_curve_based_scores_complete_and_partial(self):
        expected = {"hgCB": 10.237301796674728, "hg9": 10.433714418672025,
                    "hgOther": 9.592515842057765}
        self.assertEqual(scoring.curve_scores(ATTRS, MODEL), expected)
        self.assertEqual(scoring.curve_scores(PARTIAL, MODEL),
                         dict.fromkeys(expected, 11.073929951526225))
        self.assertEqual(scoring.curve_scores({}, MODEL), {})

    def test_experimental_win_index_complete_and_partial(self):
        self.assertAlmostEqual(scoring.win_score(ATTRS, MODEL), -68.24666666666667, places=11)
        self.assertAlmostEqual(scoring.win_score(PARTIAL, MODEL), -7.933333333333333, places=11)
        self.assertEqual(scoring.win_score({}, MODEL), 0)

    def test_goalkeeper_points_complete_partial_and_interpolation(self):
        for level, expected in zip((1, 4.5, 8, 10, 12, 14, 16, 18, 20),
                                   (-8.59, -5.61, -2.63, -1.315, 0.0, 1.025, 2.05, 3.155, 4.26)):
            with self.subTest(level=level):
                self.assertAlmostEqual(scoring.pts_value(MODEL["gk_pts"]["Agility"], level), expected, places=12)
        self.assertAlmostEqual(scoring.pts_score(ATTRS, MODEL), -3.5717857142857143, places=12)
        self.assertAlmostEqual(scoring.pts_score(PARTIAL, MODEL), 2.084285714285714, places=12)
        self.assertEqual(scoring.pts_score({}, MODEL), 0)

    def test_empty_missing_and_malformed_model_sections(self):
        self.assertEqual(scoring.weighted(ATTRS, {}), {})
        self.assertEqual(scoring.curve_scores(ATTRS, {}), {})
        self.assertEqual(scoring.curve_scores(ATTRS, {"curve_scores": {}, "curve": {}}), {})
        for model in ({}, {"win": {}, "gk_pts": {}}):
            self.assertIsNone(scoring.win_score(ATTRS, model))
            self.assertIsNone(scoring.pts_score(ATTRS, model))
        # Preserve native failure semantics for malformed configured models.
        with self.assertRaises(KeyError):
            scoring.curve_scores(ATTRS, {"curve_scores": {"bad": {}}})
        for profile in ({}, {"Pace": 0}):
            with self.assertRaises(ZeroDivisionError):
                scoring.weighted(ATTRS, {"bad": profile})
            # The existing bridge adapter treats a zero denominator as unavailable.
            self.assertIsNone(bridge.score(ATTRS, profile))

    def test_precision_without_intermediate_rounding(self):
        attributes = {"Pace": 17, "Acceleration": 9}
        profile = {"Pace": 2, "Acceleration": 5}
        expected = 11.285714285714286
        self.assertEqual(scoring.weighted(attributes, {"role": profile})["role"], expected)
        self.assertEqual(bridge.score(attributes, profile), expected)
        self.assertNotEqual(expected, round(expected, 3))


if __name__ == "__main__":
    unittest.main()
