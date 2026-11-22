"""Version 2 tactic configuration and explicit selection; no role scoring.

This experimental layer is deliberately not imported by the operational bridge.
The existing formation.py loader and version 1 output contracts are unchanged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import tomllib

import formation


PHASES = formation.PHASES
POSITIONS = formation.FM_POSITION_CODES
SIDES = formation.SIDES
UNRESOLVED = frozenset({"unknown", "ambiguous", "unsupported"})
LEFT = frozenset({"dl", "wbl", "ml", "aml"})
RIGHT = frozenset({"dr", "wbr", "mr", "amr"})
LEGACY_PROFILES = frozenset(formation.PROFILE_POSITION_CODES)


def canonical_sha256(value):
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def identifier(value, field):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9_-]*", value):
        raise ValueError(f"{field}: expected a stable lowercase machine ID")
    return value


def version(value, expected, field):
    if type(value) is not int or value != expected:
        raise ValueError(f"{field}: expected version {expected}")


def read_toml(path):
    return read_toml_with_hash(path)[0]


def read_toml_with_hash(path):
    try:
        data = Path(path).read_bytes()
        return tomllib.loads(data.decode("utf-8")), hashlib.sha256(data).hexdigest()
    except (OSError, ValueError) as exc:
        raise ValueError(f"{path}: {exc}") from exc


def side_allowed(position, side):
    if position in LEFT:
        return side == "left"
    if position in RIGHT:
        return side == "right"
    if position in {"gk", "sw"}:
        return side == "centre"
    return side in SIDES


def validate_catalogue(config):
    """Normalize a synthetic catalogue; placements are exact position/side pairs.

    An optional phase-local DC count constraint models formation context without
    assuming any real FM role restrictions. No weights or attributes are allowed.
    """
    formation.table(config, "catalogue", ("version", "id", "origin", "source", "roles"))
    version(config["version"], 1, "catalogue.version")
    identifier(config["id"], "catalogue.id")
    if config["origin"] != "synthetic":
        raise ValueError("R2 catalogue.origin: only synthetic definitions are supported")
    source = formation.text(config["source"], "catalogue.source")
    if not isinstance(config["roles"], list) or not config["roles"]:
        raise ValueError("catalogue.roles: expected nonempty role array")
    roles = {}
    for row in config["roles"]:
        formation.table(row, "role", ("id", "label", "placements"), ("min_centre_backs", "max_centre_backs"))
        key = row["id"]
        if not isinstance(key, str) or not re.fullmatch(r"(?:ip|oop)\.[a-z][a-z0-9_-]*", key):
            raise ValueError("role.id: expected ip.<id> or oop.<id>")
        if key in roles:
            raise ValueError(f"duplicate role ID {key}")
        if not isinstance(row["placements"], list) or not row["placements"]:
            raise ValueError(f"{key}: expected nonempty placements")
        placements = set()
        for place in row["placements"]:
            formation.table(place, key + ".placement", ("position", "side"))
            pos = formation.choice(place["position"], POSITIONS, key + ".position")
            side = formation.choice(place["side"], SIDES, key + ".side")
            if not side_allowed(pos, side) or (pos, side) in placements:
                raise ValueError(f"{key}: invalid or duplicate placement {pos}/{side}")
            placements.add((pos, side))
        lo, hi = row.get("min_centre_backs", 0), row.get("max_centre_backs", 10)
        if any(type(n) is not int for n in (lo, hi)) or not 0 <= lo <= hi <= 10:
            raise ValueError(f"{key}: invalid centre-back count range")
        roles[key] = {"label": formation.text(row["label"], key + ".label"),
                      "placements": [{"position": p, "side": s} for p, s in sorted(placements)],
                      "min_centre_backs": lo, "max_centre_backs": hi}
    return {"version": 1, "id": config["id"], "origin": "synthetic", "source": source, "roles": roles}


def load_catalogue(path):
    return validate_catalogue(read_toml(path))


def phase_weights(raw):
    formation.table(raw, "phase_weights", PHASES)
    normalized = {}
    for phase in PHASES:
        value = raw[phase]
        try:
            valid = type(value) in (int, float) and math.isfinite(value) and value >= 0
        except OverflowError:
            valid = False
        if not valid:
            raise ValueError(f"phase_weights.{phase}: expected finite nonnegative number")
        normalized[phase] = float(value) if value else 0.0
    if not math.isfinite(sum(normalized.values())) or sum(normalized.values()) <= 0:
        raise ValueError("phase_weights: expected positive finite total")
    return normalized


def source_record(raw):
    extra = ("career", "club_id", "team_id", "game_build", "parser_version", "save_sha256", "stored_index")
    formation.table(raw, "source", ("kind", "reference"), extra)
    kind = formation.choice(raw["kind"], {"manual", "save_import"}, "source.kind")
    result = {"kind": kind, "reference": formation.text(raw["reference"], "source.reference")}
    if kind == "manual" and set(raw) - {"kind", "reference"}:
        raise ValueError("manual source cannot claim imported save provenance")
    if kind == "save_import":
        if not set(extra) <= raw.keys():
            raise ValueError("save import source requires complete team/build/parser provenance")
        for key in extra[:-1]:
            result[key] = formation.text(raw[key], "source." + key)
        if not re.fullmatch(r"[0-9a-f]{64}", result["save_sha256"]):
            raise ValueError("source.save_sha256: expected SHA-256")
        if type(raw["stored_index"]) is not int or raw["stored_index"] < 0:
            raise ValueError("source.stored_index: expected nonnegative integer")
        result["stored_index"] = raw["stored_index"]
    return result


def responsibility(raw, field, phase, source_kind, catalogue):
    formation.table(raw, field, ("role_status",), ("position", "side", "role_id", "role_label",
                    "role_reason", "raw_role_token", "geometry_reason", "instructions"))
    pos = raw.get("position")
    side = raw.get("side")
    if pos is not None:
        formation.choice(pos, POSITIONS, field + ".position")
    if side is not None:
        formation.choice(side, SIDES, field + ".side")
    if pos is not None and side is not None and not side_allowed(pos, side):
        raise ValueError(f"{field}: position and side disagree")
    geometry_reason = raw.get("geometry_reason")
    if pos is None or side is None:
        geometry_reason = formation.text(geometry_reason, field + ".geometry_reason")
    elif geometry_reason is not None:
        raise ValueError(f"{field}: known geometry cannot have an unknown-geometry reason")
    status = formation.choice(raw["role_status"], UNRESOLVED | {"user_defined"}, field + ".role_status")
    role_id = raw.get("role_id")
    reason = raw.get("role_reason")
    token = raw.get("raw_role_token")
    label = raw.get("role_label")
    if token is not None:
        token = formation.text(token, field + ".raw_role_token")
    if label is not None:
        label = formation.text(label, field + ".role_label")
    if status == "user_defined":
        if source_kind != "manual" or token is not None or reason is not None:
            raise ValueError(f"{field}: user-defined roles require manual provenance, not parser tokens")
        if not isinstance(role_id, str) or not role_id.startswith(phase + ".") or role_id not in catalogue["roles"]:
            raise ValueError(f"{field}: unavailable or wrong-phase role ID {role_id!r}")
        role = catalogue["roles"][role_id]
        if {"position": pos, "side": side} not in role["placements"]:
            raise ValueError(f"{field}: role {role_id} not offered at {pos}/{side}")
        if label is not None and label != role["label"]:
            raise ValueError(f"{field}: role label conflicts with catalogue")
        label = role["label"]
    else:
        if role_id is not None:
            raise ValueError(f"{field}: unresolved role cannot have an exact role ID")
        reason = formation.text(reason, field + ".role_reason")
    instructions = raw.get("instructions", [])
    if not isinstance(instructions, list):
        raise ValueError(f"{field}.instructions: expected array of descriptive text")
    instructions = [formation.text(item, field + ".instructions") for item in instructions]
    return {"position": pos, "side": side, "geometry_reason": geometry_reason,
            "role_id": role_id, "role_status": status, "role_reason": reason,
            "role_label": label, "raw_role_token": token, "instructions": instructions,
            "instruction_source": "user_defined" if instructions and source_kind == "manual" else
            "unverified_import" if instructions else None}


def validate_tactic(config, catalogue):
    """Validate v2, including phase-specific context. Drafts retain unknowns."""
    formation.table(config, "tactic", ("version", "id", "name", "source", "phase_weights", "slots"))
    version(config["version"], 2, "tactic.version")
    source = source_record(config["source"])
    weights = phase_weights(config["phase_weights"])
    if not isinstance(config["slots"], list) or len(config["slots"]) != 11:
        raise ValueError("tactic.slots: expected exactly 11 slots")
    slots, ids = [], set()
    for raw in config["slots"]:
        formation.table(raw, "slot", ("id", "label", "side", "selection_position", *PHASES),
                        ("positions", "legacy_profile"))
        key = identifier(raw["id"], "slot.id")
        if key in ids:
            raise ValueError(f"duplicate slot ID {key}")
        ids.add(key)
        pos = formation.choice(raw["selection_position"], POSITIONS, key + ".selection_position")
        side = formation.choice(raw["side"], SIDES, key + ".side")
        if not side_allowed(pos, side):
            raise ValueError(f"{key}: selection position and side disagree")
        positions = raw.get("positions", [pos])
        if not isinstance(positions, list) or not positions:
            raise ValueError(f"{key}.positions: expected nonempty position array")
        positions = [formation.choice(p, POSITIONS, key + ".positions") for p in positions]
        if len(set(positions)) != len(positions) or pos not in positions or any((p == "gk") != (pos == "gk") for p in positions):
            raise ValueError(f"{key}: invalid accepted positions")
        profile = raw.get("legacy_profile")
        if profile is not None:
            formation.choice(profile, LEGACY_PROFILES, key + ".legacy_profile")
            if pos not in formation.PROFILE_POSITION_CODES[profile]:
                raise ValueError(f"{key}: incompatible legacy profile")
        phases = {p: responsibility(raw[p], f"{key}.{p}", p, source["kind"], catalogue) for p in PHASES}
        for phase, part in phases.items():
            if part["position"] is not None and (part["position"] == "gk") != (pos == "gk"):
                raise ValueError(f"{key}.{phase}: goalkeeper and outfield cannot interchange")
        slots.append({"id": key, "label": formation.text(raw["label"], key + ".label"),
                      "side": side, "selection_position": pos, "positions": positions,
                      "legacy_profile": profile, **phases})
    if sum(s["selection_position"] == "gk" for s in slots) != 1:
        raise ValueError("tactic requires exactly one goalkeeper selection slot")
    for phase in PHASES:
        count = sum(s[phase]["position"] == "dc" for s in slots)
        unknown = sum(s[phase]["position"] is None and s["selection_position"] != "gk" for s in slots)
        for s in slots:
            role_id = s[phase]["role_id"]
            if role_id is not None:
                rule = catalogue["roles"][role_id]
                if count < rule["min_centre_backs"] or count + unknown > rule["max_centre_backs"]:
                    raise ValueError(f"{s['id']}.{phase}: role {role_id} formation context not confirmed")
    return {"version": 2, "input_version": 2, "id": identifier(config["id"], "tactic.id"),
            "name": formation.text(config["name"], "tactic.name"), "source": source,
            "phase_weights": weights, "slots": slots}


def legacy_tactic(config, tactic_id):
    """Explicit v1 projection; do not reinterpret legacy descriptive role labels."""
    legacy = formation.validate_formation(config, LEGACY_PROFILES)
    slots = []
    for old in legacy["slots"]:
        slot = {k: old[k] for k in ("id", "label", "side", "positions", "selection_position")}
        slot["legacy_profile"] = old["profile"]
        for phase in PHASES:
            part = old[phase]
            slot[phase] = {"position": part["position"], "side": part["side"],
                           "geometry_reason": "legacy_phase_unspecified" if part["position"] is None else None,
                           "role_id": None, "role_status": "unknown", "role_reason": "legacy_descriptive_role_only",
                           "role_label": part["role"], "raw_role_token": None, "instructions": [], "instruction_source": None}
        slots.append(slot)
    return {"version": 2, "input_version": 1, "id": identifier(tactic_id, "tactic.id"), "name": legacy["name"],
            "source": {"kind": "legacy_v1", "reference": "validated version 1 formation"},
            "phase_weights": phase_weights(legacy["phase_weights"]), "slots": slots}


def tactic_sha256(tactic):
    """Canonical content excludes identity and source location/provenance."""
    return canonical_sha256({key: tactic[key] for key in ("version", "name", "phase_weights", "slots")})


def load_tactic(path, catalogue, *, tactic_id):
    config, digest = read_toml_with_hash(path)
    if type(config.get("version")) is int and config["version"] == 1:
        result = legacy_tactic(config, tactic_id)
    else:
        result = validate_tactic(config, catalogue)
        if result["source"]["kind"] != "manual":
            raise ValueError("manual registry requires manual provenance; use the team-checked adapter for imports")
    if result["id"] != tactic_id:
        raise ValueError("registry ID does not match tactic.id")
    result["source"]["file_sha256"] = digest
    return result


def adapt_save_tactic(snapshot, expected_team, catalogue, *, tactic_id, weights):
    """Future adapter boundary for NORMALIZED parser records, not a save parser.

    The caller supplies independently decoded native positions/sides and evidence.
    Raw tokens cannot create exact role identities, even if they resemble IDs.
    No active index or first tactic is inferred.
    """
    formation.table(snapshot, "snapshot", ("source", "team_slot", "name", "slots"))
    source = source_record(snapshot["source"])
    formation.table(expected_team, "expected_team", ("career", "club_id", "team_id"))
    if source["kind"] != "save_import" or type(snapshot["team_slot"]) is not int or snapshot["team_slot"] != 0 or any(
            source[k] != expected_team[k] for k in expected_team):
        raise ValueError("save tactic does not belong to the expected managed first team")
    rows = snapshot["slots"]
    if not isinstance(rows, list) or len(rows) != 11 or any(not isinstance(row, dict) for row in rows):
        raise ValueError("expected eleven stored tactic slots")
    for row in rows:
        formation.table(row, "stored slot", ("id", "label", "side", "selection_position", "ip", "oop", "defending_index"),
                        ("positions", "legacy_profile"))
    indices = [row.get("defending_index") for row in rows]
    if any(type(i) is not int for i in indices) or set(indices) != set(range(11)):
        raise ValueError("defending indexes must form a complete 0–10 permutation")
    paired = [{**{k: v for k, v in row.items() if k not in {"defending_index", "oop"}},
               "oop": rows[i]["oop"]} for row, i in zip(rows, indices)]
    return validate_tactic({"version": 2, "id": tactic_id, "name": snapshot["name"],
                            "source": source, "phase_weights": weights, "slots": paired}, catalogue)


def select_tactic(registry_path, catalogue_path, selected_id):
    """Explicit ID only; no default, no reliance on table insertion order."""
    selected_id = identifier(selected_id, "selected tactic ID")
    registry_path = Path(registry_path)
    registry = read_toml(registry_path)
    formation.table(registry, "registry", ("version", "tactics"))
    version(registry["version"], 1, "registry.version")
    entries = registry["tactics"]
    if not isinstance(entries, dict) or not entries:
        raise ValueError("registry.tactics: expected named tactic paths")
    for key, path in entries.items():
        identifier(key, "registry tactic ID")
        formation.text(path, "registry tactic path")
    if selected_id not in entries:
        raise ValueError(f"unknown selected tactic {selected_id!r}")
    catalogue = load_catalogue(catalogue_path)
    selected_path = registry_path.parent / entries[selected_id]
    tactic = load_tactic(selected_path, catalogue, tactic_id=selected_id)
    missing = [{"slot_id": s["id"], "phase": phase} for s in tactic["slots"] for phase in PHASES
               if tactic["phase_weights"][phase] > 0 and (s[phase]["role_id"] is None or s[phase]["position"] is None or s[phase]["side"] is None)]
    return {"version": 1, "selected_id": selected_id, "tactic": tactic,
            "tactic_sha256": tactic_sha256(tactic),
            "catalogue": {"id": catalogue["id"], "version": catalogue["version"], "origin": catalogue["origin"], "source": catalogue["source"],
                          "sha256": canonical_sha256(catalogue)},
            "configuration_status": "draft" if missing else "configured", "unresolved_weighted_phases": missing,
            "role_scoring_available": False}


def publish_selection(registry_path, catalogue_path, selected_id, output_path):
    """Validate before replacing the separate selection file atomically."""
    report = select_tactic(registry_path, catalogue_path, selected_id)
    output = Path(output_path)
    if output.suffix.lower() != ".json":
        raise ValueError("selection output must be a separate JSON file")
    if output.name.lower() in {"formation.json", "tactical_assessments.json", "optimal_xi.json", "league_benchmarks.json",
                       "squad_depth.json", "signing_simulations.json"}:
        raise ValueError("selection output must not replace an operational report")
    payload = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=output.parent,
                                         prefix=".tactic-", suffix=".tmp", delete=False) as stream:
            temp = Path(stream.name)
            stream.write(payload)
        os.replace(temp, output)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--catalogue", type=Path, required=True)
    parser.add_argument("--select", required=True, help="explicit tactic ID from registry")
    parser.add_argument("--output", type=Path, required=True, help="separate selection JSON (existing parent directory)")
    args = parser.parse_args(argv)
    try:
        report = publish_selection(args.registry, args.catalogue, args.select, args.output)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(f"Selected {report['selected_id']}: {report['configuration_status']} (role scoring disabled)")


if __name__ == "__main__":
    main()
