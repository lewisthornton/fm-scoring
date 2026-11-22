"""R1 test-only validation utilities; no FM role model or role tables.

The expected records must be prepared independently of the implementation
under test. This module neither reads saves nor grants a validation status.
"""
from __future__ import annotations

import math
import struct


EVIDENCE_KINDS = {"synthetic", "upstream_reference", "game_observation", "game_numeric"}
POSITIONS = frozenset("gk sw dl dc dr dm ml mc mr aml amc amr stc wbl wbr".split())


def exact_int(value, low, high):
    """A typed observation is not a category, rounded guess or truth value."""
    return type(value) is int and low <= value <= high


def input_gaps(record, required_attributes):
    """Candidate R3 input preflight, not a production input adapter."""
    gaps = []
    if record.get("attribute_scale") != "raw_1_100":
        gaps.append("raw_scale_unconfirmed")
    attributes = record.get("raw_attributes", {})
    for name in sorted(required_attributes):
        if not exact_int(attributes.get(name), 1, 100):
            gaps.append(f"raw_attributes.{name}")
    positions = record.get("positions", {})
    for code in sorted(POSITIONS):
        if not exact_int(positions.get(code), 1, 20):
            gaps.append(f"positions.{code}")
    if not exact_int(record.get("current_ability"), 1, 200):
        gaps.append("current_ability")
    if not record.get("game_build"):
        gaps.append("game_build")
    return gaps


def pair_defending_slots(slots):
    """Check a normalized test export's explicit defending permutation.

    Each row is in IP order; its OOP payload is in *stored* order. Unknown
    roles stay unknown, including a raw token that happens to be nonzero.
    Do not use this as an FM byte parser.
    """
    if len(slots) != 11:
        raise ValueError("expected eleven stored slots")
    indices = [row.get("defending_index") for row in slots]
    if not all(exact_int(i, 0, 10) for i in indices) or set(indices) != set(range(11)):
        raise ValueError("defending indexes must form a complete permutation")
    ids = [row["slot_id"] for row in slots]
    if len(set(ids)) != 11:
        raise ValueError("duplicate slot IDs")
    return [{"slot_id": row["slot_id"], "ip": row["ip"],
             "oop": slots[index]["oop"]} for row, index in zip(slots, indices)]


def compare_numeric(expected, actual):
    """Compare two distinct outputs without averaging errors or tolerances.

    Explicit null is an expected outcome; absent keys are not null. Both
    metrics are compared for each snapshot/player/slot/phase/model/build key.
    Fixture provenance is reviewed separately from numerical agreement.
    """
    def index(rows):
        result = {}
        for row in rows:
            key = tuple(row[field] for field in (
                "case_id", "game_build", "model_id", "player_id", "slot_id", "phase"))
            if any(not isinstance(value, str) or not value for value in key):
                raise ValueError("missing case identity")
            if row["phase"] not in {"ip", "oop"} or key in result:
                raise ValueError("invalid phase or duplicate numeric case")
            if row.get("evidence_kind") not in EVIDENCE_KINDS or not row.get("source"):
                raise ValueError("missing evidence provenance")
            for metric in ("role_rating", "role_ability"):
                value = row[metric]
                if value is not None and not exact_int(value, 0, 200):
                    raise ValueError(f"invalid {metric}")
            result[key] = row
        return result

    left, right = index(expected), index(actual)
    mismatches = []
    for key in sorted(left.keys() | right.keys()):
        if key not in left or key not in right:
            mismatches.append((key, "missing_case"))
            continue
        for metric in ("role_rating", "role_ability"):
            if left[key][metric] != right[key][metric]:
                mismatches.append((key, metric))
    return mismatches


def f32(value):
    """Portable binary32 conversion for numerical test instrumentation."""
    if not math.isfinite(value):
        raise ValueError("non-finite test value")
    return struct.unpack("!f", struct.pack("!f", value))[0]
