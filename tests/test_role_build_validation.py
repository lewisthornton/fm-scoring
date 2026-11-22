"""R4.5 invented-only validation infrastructure; never new game evidence."""
import copy
import unittest

import role_ability as ra
import role_build_validation as validation
from test_role_ability import evaluate, player


def bundles():
    expected = {"schema_version": 1, "build": "27.1.0+2505117",
                "database_version": 3756, "model_sha256": ra.MODEL_SHA256,
                "catalogue_sha256": ra.CATALOGUE_SHA256,
                "artifact_sha256": "a" * 64, "source_kind": "synthetic",
                "capture_method": "invented comparator fixture",
                "cases": [{"case_id": "ip", "input_sha256": "b" * 64,
                           "role_rating": 100, "best_role_rating": 120, "role_ability": 125},
                          {"case_id": "oop", "input_sha256": "c" * 64,
                           "role_rating": 80, "best_role_rating": 100, "role_ability": None}]}
    actual = copy.deepcopy(expected)
    actual.update(source_kind="candidate", artifact_sha256="d" * 64)
    return expected, actual


class BuildValidationTests(unittest.TestCase):
    def test_registry_and_hashes_frozen(self):
        self.assertEqual(ra.MODEL["supported_builds"],
                         [{"game_build": "27.0.0", "database_version": 3754}])
        self.assertEqual(ra.MODEL_SHA256,
                         "f6049ec4cb93184b3bc9349d5d6f800e5d6e3f6bbac76b37ed6ee2c9f3a53e17")
        self.assertEqual(validation.build_evidence("27.0.0", 3754)["status"], "reference_matched")

    def test_full_builds_refused(self):
        for build, db, status, _ in validation.BUILD_EVIDENCE[1:]:
            with self.subTest(build=build):
                self.assertEqual(status, "unsupported")
                self.assertEqual(validation.build_evidence(build, db)["status"], "unsupported")
                p = player(positions={"gk": 20})
                p.update(game_build=build, database_version=db)
                result = evaluate(p, "ip.goalkeeper", "gk", game_build=build, database_version=db)
                self.assertIsNone(result["role_rating"])
                self.assertIsNone(result["role_ability"])

    def test_exact_pair_and_parser_identity(self):
        for build, db in [("27.0.0", "3754"), ("27.0.0 ", 3754),
                          ("27.0.0", 3756), ("27.1.0", 3756), ("27.0.1", 3754),
                          ("27.0.0", True), ("27.0.0+2493426", 3754)]:
            self.assertEqual(validation.build_evidence(build, db)["status"], "unsupported")
        info = {"game": "FM27", "build": "27.0.0+2486695", "db_version": "3754",
                "known_build": True, "fmsave_version": "0.14.3"}
        parsed = validation.parser_identity(info)
        self.assertEqual(parsed["save_writer_build"], info["build"])
        self.assertEqual(parsed["parser_database_version"], "3754")
        self.assertIsNone(parsed["numeric_database_version"])
        self.assertTrue(parsed["parser_known_build"])

    def test_agreement_does_not_promote_and_order_is_irrelevant(self):
        expected, actual = bundles()
        actual["cases"].reverse()
        result = validation.compare_numeric(expected, actual)
        self.assertTrue(result["numeric_agreement"])
        self.assertFalse(result["evidence_promoted"])
        self.assertEqual(result["case_count"], 2)

    def test_discrepancies_include_null_zero_and_single_point(self):
        expected, actual = bundles()
        actual["cases"][0]["role_rating"] += 1
        actual["cases"][1]["role_ability"] = 0
        result = validation.compare_numeric(expected, actual)
        self.assertFalse(result["numeric_agreement"])
        self.assertEqual(result["mismatches"], [
            {"case_id": "ip", "metric": "role_rating", "expected": 100, "actual": 101},
            {"case_id": "oop", "metric": "role_ability", "expected": None, "actual": 0}])

    def test_mismatched_identity_rejected(self):
        for field, value in [("build", "27.0.0+2493426"), ("database_version", 3754),
                             ("model_sha256", "e" * 64), ("catalogue_sha256", "f" * 64)]:
            expected, actual = bundles()
            actual[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validation.compare_numeric(expected, actual)
        expected, actual = bundles()
        actual["cases"][0]["input_sha256"] = "f" * 64
        with self.assertRaises(ValueError):
            validation.compare_numeric(expected, actual)

    def test_missing_and_duplicate_cases_rejected(self):
        for change in ("missing", "duplicate", "metric", "bool"):
            expected, actual = bundles()
            if change == "missing":
                actual["cases"].pop()
            elif change == "duplicate":
                actual["cases"].append(actual["cases"][0])
            elif change == "metric":
                del actual["cases"][0]["role_ability"]
            else:
                actual["cases"][0]["role_rating"] = True
            with self.subTest(change=change), self.assertRaises(ValueError):
                validation.compare_numeric(expected, actual)

    def test_stars_and_order_not_numeric_evidence(self):
        for source in ("stars", "game_observation", "role_order"):
            expected, actual = bundles()
            expected["source_kind"] = source
            with self.assertRaises(ValueError):
                validation.compare_numeric(expected, actual)
