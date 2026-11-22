"""Offline R4.5 evidence register and exact comparison; never a runtime gate."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

# A null numeric database version means it has not been established.
# The release-only R3 key is not an executable build identifier.
BUILD_EVIDENCE = (
    ("27.0.0", 3754, "reference_matched", "r3_release_label_only"),
    ("27.0.0+2486695", None, "unsupported", "fmsave_layout_only"),
    ("27.0.0+2493426", 3754, "unsupported", "save_layout_and_release_family_reference"),
    ("27.0.1+2494687", None, "unsupported", "fmsave_partial_reader_evidence"),
    ("27.0.1+2494769", None, "unsupported", "match_lab_engine_observations_only"),
    ("27.0.1+2503222", None, "unsupported", "match_lab_engine_observations_only"),
    ("27.1.0+2505117", 3756, "unsupported", "save_layout_only"),
)


def build_evidence(build, database_version):
    """Exact evidence lookup; never coerce a parser string or alias a suffix."""
    if type(build) is str and type(database_version) is int:
        for version, db, status, reason in BUILD_EVIDENCE:
            if (version, db) == (build, database_version):
                return {"status": status, "reason": reason}
    return {"status": "unsupported", "reason": "exact_numeric_build_pair_not_established"}


def parser_identity(info):
    """Preserve fmsave metadata without claiming it identifies the numeric DB."""
    return {"game": info.get("game"), "save_writer_build": info.get("build"),
            "parser_database_version": info.get("db_version"),
            "parser_known_build": info.get("known_build"),
            "parser_version": info.get("fmsave_version"),
            "numeric_database_version": None}


def _digest(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _cases(bundle):
    if type(bundle.get("schema_version")) is not int or bundle["schema_version"] != 1:
        raise ValueError("unsupported validation schema")
    if not isinstance(bundle.get("build"), str) or not re.fullmatch(
            r"\d+\.\d+\.\d+\+\d+", bundle["build"]):
        raise ValueError("full target build required")
    if type(bundle.get("database_version")) is not int or bundle["database_version"] <= 0:
        raise ValueError("numeric database version required")
    for field in ("model_sha256", "catalogue_sha256", "artifact_sha256"):
        if not _digest(bundle.get(field)):
            raise ValueError(f"invalid {field}")
    rows = bundle.get("cases")
    if not isinstance(rows, list) or not rows:
        raise ValueError("nonempty cases required")
    result = {}
    for row in rows:
        key = row.get("case_id")
        if not isinstance(key, str) or not key or key in result:
            raise ValueError("missing or duplicate case ID")
        if not _digest(row.get("input_sha256")):
            raise ValueError("invalid input digest")
        for field in ("role_rating", "best_role_rating", "role_ability"):
            if field not in row or (row[field] is not None and
                                    (type(row[field]) is not int or not 0 <= row[field] <= 200)):
                raise ValueError(f"invalid or missing {field}")
        result[key] = row
    return result


def compare_numeric(expected, actual):
    """Compare frozen numeric bundles without promoting any evidence status.

    The input digest binds complete raw player, context, phase and role inputs.
    Source declarations and artifact hashes require independent human review.
    """
    if expected.get("source_kind") not in ("synthetic", "upstream_reference", "game_numeric"):
        raise ValueError("stars/order/other observations are not numeric references")
    if actual.get("source_kind") != "candidate":
        raise ValueError("candidate bundle required")
    if not isinstance(expected.get("capture_method"), str) or not expected["capture_method"].strip():
        raise ValueError("expected capture method required")
    left, right = _cases(expected), _cases(actual)
    for field in ("build", "database_version", "model_sha256", "catalogue_sha256"):
        if expected[field] != actual[field]:
            raise ValueError(f"bundle mismatch: {field}")
    if left.keys() != right.keys():
        raise ValueError("case sets differ")
    mismatches = []
    for key in sorted(left):
        if left[key]["input_sha256"] != right[key]["input_sha256"]:
            raise ValueError(f"input mismatch: {key}")
        for field in ("role_rating", "best_role_rating", "role_ability"):
            if left[key][field] != right[key][field]:
                mismatches.append({"case_id": key, "metric": field,
                                   "expected": left[key][field], "actual": right[key][field]})
    return {"case_count": len(left), "source_kind": expected["source_kind"],
            "numeric_agreement": not mismatches, "mismatches": mismatches,
            "evidence_promoted": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("expected", type=Path)
    parser.add_argument("actual", type=Path)
    args = parser.parse_args()
    result = compare_numeric(json.loads(args.expected.read_text(encoding="utf-8")),
                             json.loads(args.actual.read_text(encoding="utf-8")))
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0 if result["numeric_agreement"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
