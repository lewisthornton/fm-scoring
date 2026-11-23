"""Local immutable operational report generations. No scoring or persistence of save data."""
import hashlib
import json
import math
import os
import re
import tempfile
import time
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

FILES = ("formation.json", "tactical_assessments.json", "league_benchmarks.json",
         "optimal_xi.json", "squad_depth.json", "signing_simulations.json")
VERSION = 1


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def decode(data):
    def pairs(items):
        result = dict(items)
        require(len(result) == len(items), "Duplicate JSON key")
        return result
    def invalid(value):
        raise ValueError("Non-finite JSON number: " + value)
    def finite(value):
        number = float(value)
        require(math.isfinite(number), "Non-finite JSON number")
        return number
    return json.loads(data, object_pairs_hook=pairs, parse_constant=invalid, parse_float=finite)


def index(rows, key):
    result = {}
    for row in rows:
        ident = key(row)
        require(ident not in result, "Duplicate identity: " + str(ident))
        result[ident] = row
    return dict(sorted(result.items()))


def validate(reports, source):
    f, a, b, x, d, s = reports
    require(all(type(r["version"]) is int and r["version"] == 1 for r in reports), "Unsupported report version")
    require(a["scoring_model"]["name"] == "fm27v2.toml", "Unsupported model")
    require(re.fullmatch("[0-9a-f]{64}", a["scoring_model"]["sha256"]), "Invalid model fingerprint")
    require(a["formation"]["sha256"] == digest(canonical(f)), "Formation hash mismatch")
    for r in (b, x, d, s):
        require(all(r[k] == a[k] for k in ("career", "game_date", "scoring_model")), "Report identity mismatch")
    for r in (x, d, s):
        require(r["formation"] == a["formation"] and r["eligibility_policy"] == x["eligibility_policy"], "Formation/policy mismatch")
        require(r["objective"] == x["objective"], "Objective mismatch")
    policy = x["eligibility_policy"]
    require(policy["version"] == 2 and policy["mode"] in ("strict", "relaxed")
            and policy["phase_eligibility"] in ("context_only", "require_weighted_phases")
            and type(policy["minimum_familiarity"]) is int and 1 <= policy["minimum_familiarity"] <= 20
            and all(type(policy[k]) is bool for k in ("allow_category_evidence", "allow_unknown_availability")), "Invalid effective policy")
    require(d["baseline"] == x, "Depth baseline mismatch")
    totals = {"filled_slots": x["solver"]["filled_slots"], "outfield_total": x["outfield_total"], "goalkeeper_total": x["goalkeeper_total"]}
    require(s["baseline"] == {"xi_file": FILES[3], "depth_file": FILES[4], "totals": totals}, "Signing baseline mismatch")
    require(x["objective"]["priorities"] == ["maximum_filled_slots", "maximum_outfield_score_sum", "maximum_goalkeeper_score", "stable_id_tie_break"], "Unsupported objective")
    players = index(a["players"], lambda p: p["player_id"])
    slots = index(f["slots"], lambda p: p["id"])
    require(len(slots) == 11 and sum(p["profile"] == "GK" for p in slots.values()) == 1, "Invalid formation domains")
    members = index(source["members"], lambda p: (p["player_id"], p["cohort"]))
    require(all(row["cohort"] in ("squad", "target") for row in members.values()), "Unknown cohort")
    require(set(members) == {(pid, cohort) for pid, p in players.items() for cohort in p["cohorts"]}, "Cohort mismatch")
    accepted = source["accepted_game_date"]
    if accepted is not None:
        date.fromisoformat(accepted)
    snapshot_index = index(source["snapshots"], lambda row: row["id"])
    for snapshot in snapshot_index.values():
        for key in ("source_sha256", "selection_sha256"):
            require(re.fullmatch("[0-9a-f]{64}", snapshot[key]), "Invalid snapshot fingerprint")
        if snapshot["game_date"]:
            date.fromisoformat(snapshot["game_date"])
            require(accepted is None or snapshot["game_date"] <= accepted, "Snapshot after accepted chronology")
    evidence = {}
    for pid, p in players.items():
        identity = decode(pid)
        require(isinstance(identity, list) and len(identity) == 3 and identity[:2] == ["rangers", a["career"]] and isinstance(identity[2], str), "Invalid career/player identity")
        rows = [members[pid, cohort] for cohort in p["cohorts"]]
        require(all(r["record_game_date"] == p["record_game_date"] for r in rows), "Observation date mismatch")
        for row in rows:
            require(row["game_build"] == p["game_build"], "Observation build mismatch")
            require(re.fullmatch("[0-9a-f]{64}", row["record_sha256"]), "Invalid record fingerprint")
            if snapshot_index:
                snapshot = snapshot_index.get(row["record_snapshot_id"])
                require(snapshot and snapshot["game_date"] == row["record_game_date"] and snapshot["game_build"] == row["game_build"], "Observation snapshot mismatch")
        seen = max((r["last_seen_game_date"] for r in rows if r["last_seen_game_date"]), default=None)
        require(seen == p["last_seen_game_date"], "Last seen mismatch")
        for stamp in (p["record_game_date"], seen):
            if stamp:
                date.fromisoformat(stamp)
                require(accepted is None or stamp <= accepted, "Observation after accepted chronology")
        per_slot = index(p["slots"], lambda r: r["slot_id"])
        require(set(per_slot) == set(slots), "Incomplete player assessment")
        for sid, item in per_slot.items():
            require(item["player_id"] == pid and item["profile"] == slots[sid]["profile"], "Assessment identity mismatch")
            require(item["ip"]["observed_role_suitability"] is None and item["oop"]["observed_role_suitability"] is None, "Unsupported role evidence")
            require(item["attribute_profile_score"] is None if item["attribute_profile_reason"] else item["attribute_profile_score"] is not None, "Invalid missing score")
            evidence[pid, sid] = item
    require(a["game_date"] == max((p["last_seen_game_date"] for p in players.values() if p["last_seen_game_date"]), default=None), "Observation date mismatch")
    require(a["observed_role_suitability_source"] is None, "Unsupported role source")
    require(a["source_data"]["observed_role_suitability_available"] is False, "Unsupported role availability")
    def assignments(rows, allowed):
        ix = index(rows, lambda r: r["slot_id"])
        require(set(ix) == set(slots), "Incomplete assignment")
        selected = set()
        for sid, row in ix.items():
            pid = row["player_id"]
            if pid is None:
                require(row["attribute_profile_score"] is None, "Vacancy score must be null")
            else:
                require(pid in allowed and pid not in selected, "Invalid assignment player")
                require(players[pid]["keeper"] == (slots[sid]["profile"] == "GK"), "Assignment domain mismatch")
                require(row["attribute_profile_score"] == evidence[pid, sid]["attribute_profile_score"] and row["attribute_profile_score"] is not None, "Assignment score mismatch")
                selected.add(pid)
        return ix
    squad = {pid for pid, p in players.items() if "squad" in p["cohorts"]}
    baseline = assignments(x["assignments"], squad)
    require(sum(r["player_id"] is not None for r in baseline.values()) == totals["filled_slots"], "Filled slots mismatch")
    for sid, row in baseline.items():
        require(row["assessment"] == (evidence[row["player_id"], sid] if row["player_id"] else None), "XI evidence mismatch")
    keeper = next(row for sid, row in baseline.items() if slots[sid]["profile"] == "GK")
    require(keeper["attribute_profile_score"] == totals["goalkeeper_total"], "Goalkeeper objective mismatch")
    coverage = index(d["coverage"], lambda r: r["slot_id"])
    require(set(coverage) == set(slots), "Depth coverage mismatch")
    for sid, row in coverage.items():
        require(row["starter_id"] == baseline[sid]["player_id"] and row["profile"] == slots[sid]["profile"], "Depth starter mismatch")
        eligible = index(row["eligible_players"], lambda r: r["player_id"])
        for pid, item in eligible.items():
            require(pid in squad and item["assessment"] == evidence[pid, sid], "Depth evidence mismatch")
        require(set(row["direct_deputy_ids"]) <= set(eligible), "Invalid deputies")
    absences = index(d["starter_loss_scenarios"], lambda r: r["removed_player_id"])
    require(set(absences) == {r["player_id"] for r in baseline.values() if r["player_id"]}, "Absence membership mismatch")
    for pid, row in absences.items():
        require(row["baseline"] == totals and baseline[row["original_slot_id"]]["player_id"] == pid, "Absence baseline mismatch")
        assignments(row["assignments"], squad - {pid})
    candidates = index(s["candidates"], lambda r: r["player_id"])
    require(set(candidates) == {pid for pid, p in players.items() if "target" in p["cohorts"]}, "Candidate cohort mismatch")
    for pid, row in candidates.items():
        require(row["observed_cohorts"] == players[pid]["cohorts"] and row["observed_slot_evidence"] == players[pid]["slots"], "Candidate evidence mismatch")
        require(all(row[k] == players[pid][k] for k in ("record_game_date", "last_seen_game_date", "game_build"))
                and row["observed_availability"] == players[pid]["availability"]
                and row["observed_loan_state"] == players[pid]["loan_state"], "Candidate observation mismatch")
        if pid in squad:
            require(row["xi"] is None and row["scenario_assumed_availability"] is None, "Observed squad treated as signing")
        else:
            require(row["scenario_assumed_availability"] == "available" and row["xi"]["baseline"] == totals, "Hypothetical baseline mismatch")
            assignments(row["xi"]["assignments"], squad | {pid})
    comparisons = index(b["comparisons"] + b["native_comparisons"], lambda r: (r["player_id"], r["profile"], r["native_position"] or ""))
    expected = {(pid, profile, native) for pid in players for profile, codes in b["criteria"]["inherited_profile_position_mapping"].items() for native in ["", *codes]}
    require(set(comparisons) == expected, "Incomplete benchmark comparisons")
    if b["status"] == "available":
        age = (date.fromisoformat(b["game_date"]) - date.fromisoformat(b["extraction_game_date"])).days
        require(0 <= age < 30, "Stale benchmark provenance")
    else:
        require(bool(b["reason"]), "Missing benchmark unavailability reason")
    for row in comparisons.values():
        require(row["player_id"] in players, "Unknown benchmark player")
        if row["status"] != "available":
            require(row["percentile"] is None and row["difference_from_median"] is None and row["reason"], "Unavailable benchmark has numeric comparison")
        else:
            require(b["status"] == "available" and row["reason"] is None and row["percentile"] is not None, "Invalid available benchmark")
    def comparison_links(value):
        if isinstance(value, dict):
            if {"reference_population", "player_id", "profile", "native_position", "percentile"} <= value.keys():
                original = comparisons.get((value["player_id"], value["profile"], value["native_position"] or ""))
                require(original is not None and all(value.get(k) == v for k, v in original.items()), "Benchmark join mismatch")
            for item in value.values():
                comparison_links(item)
        elif isinstance(value, list):
            for item in value:
                comparison_links(item)
    def references(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if item is not None and (key == "player_id" or key.endswith("_player_id") or key in ("starter_id", "effective_deputy_id", "previous_slot_incumbent_id")):
                    require(item in players, "Unknown player reference: " + key)
                if item is not None and (key == "slot_id" or key.endswith("_slot_id") or key == "baseline_slot"):
                    require(item in slots, "Unknown slot reference: " + key)
                if isinstance(item, list) and (key.endswith("_player_ids") or key.endswith("_deputy_ids")):
                    require(set(item) <= set(players), "Unknown player references: " + key)
                if isinstance(item, list) and (key == "slot_ids" or key.endswith("_slot_ids")):
                    require(set(item) <= set(slots), "Unknown slot references: " + key)
                references(item)
        elif isinstance(value, list):
            for item in value:
                references(item)
    for report in (x, d, s):
        references(report)
        comparison_links(report)
    return {"players": players, "slots": slots, "assessments": evidence, "baseline": baseline,
            "depth": coverage, "absences": absences, "signings": candidates, "benchmarks": comparisons,
            "summary": {"objective": x["objective"], "solver": x["solver"], "totals": totals,
                        "depth": d["summary"], "signings": s["evaluation_coverage"],
                        "benchmark": benchmark_identity(b)}}


def source_identity(provenance, career):
    members = []
    for row in provenance["observations"]:
        members.append({"player_id": json.dumps(["rangers", career, row["player_key"]], ensure_ascii=False, separators=(",", ":")),
                        "cohort": row["cohort"], "record_sha256": digest(row["record_json"].encode("utf-8")),
                        "record_game_date": row["record_game_date"], "last_seen_game_date": row["last_seen_game_date"],
                        "game_build": row["game_build"], "record_snapshot_id": row["record_snapshot_id"],
                        "source_export": Path(row["source_export"]).name if row["source_export"] else None})
    return {"accepted_game_date": provenance["accepted_game_date"], "managed_club_uid": provenance["managed_club_uid"],
            "members": sorted(members, key=lambda r: (r["player_id"], r["cohort"])), "snapshots": provenance["snapshots"],
            "benchmark_cache_sha256": digest(canonical(provenance["benchmark_cache"])) if provenance["benchmark_cache"] is not None else None}


def replace_pointer(root, manifest):
    pointer = {"version": VERSION, "generation_id": manifest["generation_id"], "manifest_sha256": digest(canonical(manifest))}
    fd, name = tempfile.mkstemp(prefix=".current-", dir=root)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(canonical(pointer))
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(5):
            try:
                os.replace(name, root / "current.json")
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.05 * (attempt + 1))
    finally:
        Path(name).unlink(missing_ok=True)


def publish(root, reports, provenance):
    root = Path(root)
    source = source_identity(provenance, reports[1]["career"])
    validate(reports, source)
    generation_id = uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=True)
    generations = root / "generations"
    generations.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".staging-", dir=root) as tmp:
        stage = Path(tmp) / generation_id
        stage.mkdir()
        files = {}
        for name, report in zip(FILES, reports):
            (stage / name).write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
            body = (stage / name).read_bytes()
            files[name] = {"sha256": digest(body), "bytes": len(body), "version": report["version"]}
        a, b, x, s = reports[1], reports[2], reports[3], reports[5]
        config = {"scoring_model": a["scoring_model"], "formation": a["formation"], "eligibility_policy": x["eligibility_policy"], "depth_limit": s["depth_limit"]}
        manifest = {"version": VERSION, "generation_id": generation_id, "generated_utc": datetime.now(timezone.utc).isoformat(),
                    "career": a["career"], "game_date": a["game_date"], "source": source,
                    "source_sha256": digest(canonical(source)), "cohort_sha256": digest(canonical([[r["player_id"], r["cohort"]] for r in source["members"]])), "configuration": config,
                    "benchmark": benchmark_identity(b),
                    "files": files}
        (stage / "manifest.json").write_bytes(canonical(manifest))
        read_generation(stage)
        os.rename(stage, generations / generation_id)
    replace_pointer(root, manifest)
    return generation_id


def read_generation(directory):
    """Verify exact bytes, then expose deterministic, generation-local indexes."""
    directory = Path(directory)
    manifest = decode((directory / "manifest.json").read_bytes())
    require(manifest["version"] == VERSION and manifest["generation_id"] == directory.name, "Invalid manifest identity")
    timestamp = datetime.fromisoformat(manifest["generated_utc"])
    require(timestamp.utcoffset() is not None and timestamp.utcoffset().total_seconds() == 0, "Invalid generation timestamp")
    require(set(manifest["files"]) == set(FILES), "Incomplete manifest")
    require(manifest["source_sha256"] == digest(canonical(manifest["source"])), "Source fingerprint mismatch")
    require(manifest["cohort_sha256"] == digest(canonical([[r["player_id"], r["cohort"]] for r in manifest["source"]["members"]])), "Cohort fingerprint mismatch")
    reports = []
    for name in FILES:
        body = (directory / name).read_bytes()
        meta = manifest["files"][name]
        require(meta["sha256"] == digest(body) and meta["bytes"] == len(body), "Report hash mismatch: " + name)
        report = decode(body)
        require(meta["version"] == report["version"], "Schema mismatch")
        reports.append(report)
    a = reports[1]
    require(manifest["career"] == a["career"] and manifest["game_date"] == a["game_date"], "Manifest identity mismatch")
    require(manifest["configuration"] == {"scoring_model": a["scoring_model"], "formation": a["formation"], "eligibility_policy": reports[3]["eligibility_policy"], "depth_limit": reports[5]["depth_limit"]}, "Manifest configuration mismatch")
    require(manifest["benchmark"] == benchmark_identity(reports[2]), "Benchmark manifest mismatch")
    return manifest, validate(reports, manifest["source"])


def benchmark_identity(report):
    return {k: report.get(k) for k in ("source", "status", "reason", "extraction_game_date", "scoring_model",
                                     "competition", "season_start_year", "provenance", "warnings")}


def read_current(root):
    root = Path(root)
    pointer = decode((root / "current.json").read_bytes())
    gid = pointer["generation_id"]
    require(pointer["version"] == VERSION and re.fullmatch("[0-9a-f]{32}", gid), "Invalid pointer")
    manifest, indexes = read_generation(root / "generations" / gid)
    require(pointer["manifest_sha256"] == digest((root / "generations" / gid / "manifest.json").read_bytes()), "Manifest hash mismatch")
    return manifest, indexes


def rollback(root, generation_id):
    require(re.fullmatch("[0-9a-f]{32}", generation_id), "Invalid generation ID")
    root = Path(root)
    manifest, _ = read_generation(root / "generations" / generation_id)
    replace_pointer(root, manifest)
