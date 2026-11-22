"""Invented R1 fixtures: test the validation machinery, not game accuracy."""
import unittest

from role_validation import (POSITIONS, compare_numeric, f32, input_gaps,
                             pair_defending_slots)


def observation(**overrides):
    return {"attribute_scale": "raw_1_100", "raw_attributes": {"pace": 72, "passing": 73},
            "positions": dict.fromkeys(POSITIONS, 1) | {"dr": 20},
            "current_ability": 115, "game_build": "invented-build", **overrides}


def case(**overrides):
    # Arbitrary comparator values, NOT calculated or observed FM outputs.
    return {"case_id": "mock", "game_build": "invented-build", "model_id": "mock-model",
            "player_id": "invented:1", "slot_id": "rb", "phase": "ip",
            "role_rating": 111, "role_ability": 109,
            "evidence_kind": "synthetic", "source": "invented comparator fixture", **overrides}


def tactic_rows():
    # Invented adapter-level export with a non-self-inverse three-cycle.
    permutation = [0, 4, 2, 3, 9, 5, 6, 7, 8, 1, 10]
    return [{"slot_id": f"slot-{i}", "defending_index": index,
             "ip": {"position": "dc", "side": "left", "role_id": None},
             "oop": {"position": "mc", "side": "right", "role_id": None,
                     "raw_token": i + 100}} for i, index in enumerate(permutation)]


class RoleValidationTests(unittest.TestCase):
    def test_exact_input_preflight(self):
        self.assertEqual(input_gaps(observation(), {"pace", "passing"}), [])
        for value in (None, 0, 101, True, 72.0, "72"):
            with self.subTest(value=value):
                self.assertIn("raw_attributes.pace", input_gaps(
                    observation(raw_attributes={"pace": value, "passing": 73}), {"pace", "passing"}))

    def test_rounded_values_and_category_are_not_exact(self):
        gaps = input_gaps(observation(attribute_scale="display_1_20", raw_attributes={},
                                      positions={"dr": "natural"}, current_ability=None), {"pace"})
        self.assertIn("raw_scale_unconfirmed", gaps)
        self.assertIn("raw_attributes.pace", gaps)
        self.assertIn("positions.dr", gaps)
        self.assertIn("positions.gk", gaps)
        self.assertIn("current_ability", gaps)

    def test_same_display_value_can_have_distinct_raw_observations(self):
        # 73 and 74 both display 15 but remain separate raw observations.
        a, b = observation(raw_attributes={"pace": 73}), observation(raw_attributes={"pace": 74})
        self.assertEqual((73 + 2) // 5, (74 + 2) // 5)
        self.assertNotEqual(a, b)

    def test_pairing_preserves_player_slot_identity_and_unknown_roles(self):
        rows = tactic_rows()
        result = pair_defending_slots(rows)
        self.assertEqual([row["slot_id"] for row in result], [row["slot_id"] for row in rows])
        self.assertEqual([result[i]["oop"]["raw_token"] for i in (1, 4, 9)], [104, 109, 101])
        self.assertIsNone(result[1]["oop"]["role_id"])
        self.assertEqual(result[1]["oop"]["side"], "right")

    def test_invalid_defending_permutations_fail_closed(self):
        for value in (None, 0, 11, -1, True, "6"):
            rows = tactic_rows()
            rows[6]["defending_index"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                pair_defending_slots(rows)
        with self.assertRaises(ValueError):
            pair_defending_slots(tactic_rows()[:-1])

    def test_comparison_is_phase_and_build_specific_and_exact(self):
        expected = [case(), case(phase="oop", role_ability=112)]
        self.assertEqual(compare_numeric(expected, list(reversed(expected))), [])
        actual = [case(role_rating=112), case(phase="oop", role_ability=111)]
        self.assertEqual([field for _, field in compare_numeric(expected, actual)], ["role_rating", "role_ability"])
        self.assertEqual(len(compare_numeric([case()], [case(game_build="other-build")])), 2)

    def test_explicit_null_and_missing_rows_and_duplicates(self):
        absent = case(role_rating=None, role_ability=None)
        self.assertEqual(compare_numeric([absent], [absent]), [])
        self.assertEqual(len(compare_numeric([absent], [case()])), 2)
        self.assertEqual(compare_numeric([absent], [])[0][1], "missing_case")
        with self.assertRaises(ValueError):
            compare_numeric([case(), case()], [case()])
        with self.assertRaises(ValueError):
            compare_numeric([case(source=None)], [case()])

    def test_binary32_instrumentation_distinguishes_precision(self):
        # IEEE-754 spacing around 1, independent of any role calculation.
        self.assertEqual(f32(1 + 2**-25), 1.0)
        self.assertEqual(f32(1 + 2**-23), 1 + 2**-23)
        self.assertNotEqual(f32(1 + 2**-25), 1 + 2**-25)


if __name__ == "__main__":
    unittest.main()
