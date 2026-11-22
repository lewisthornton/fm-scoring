"""Non-operational FM27 27.0.0 role ability reference port.

Adapted from Napas/fm-mcp (pinned below), with user-supplied redistribution
permission. See formations/THIRD_PARTY_ROLE_ABILITY.md. No game validation
or later-build equivalence is claimed. No operational scorer imports this.
"""
from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
import struct
from typing import Mapping

import tactic


FM27_MODEL_ID = "fm27-role-ability-r3"
REFERENCE_REVISION = "4f19a3f0d1130e47d604173a78ff01642f538d52"
CATALOGUE_SHA256 = "51488bd5bbab4c0420c0c3408b969b271e7ee49d748a5e71cc002cad91147689"
MODEL = {"id": FM27_MODEL_ID, "version": 1, "origin": "fm27_reference",
         "catalogue_sha256": CATALOGUE_SHA256, "upstream_revision": REFERENCE_REVISION,
         "supported_builds": [{"game_build": "27.0.0", "database_version": 3754}],
         "evidence_status": "reference_matched", "independently_game_validated": False,
         "arithmetic_version": "fm27-2700-reference-v1"}
MODEL_SHA256 = tactic.canonical_sha256(MODEL)
MODELS = {FM27_MODEL_ID: MODEL}

# Reference classifier flags and thresholds; separate IP/OOP bit namespaces.
IP_BLEND = ((0x48000000000000, "full_back"), (0x10000000000000, "dc"),
            (0x2080008000000, "amc"), (0x10000000000, "false_nine"), (0x4000, "dm"))
OOP_BLEND = ((0x1c0, "full_back"), (0x1000080400, "wing_back"), (0x8020002000, "wide_mid"),
             (0x10000, "dc"), (0x80020000, "mc"), (0x90008000000, "amc"), (0x200200000000, "wide_attack"))


def f32(value):
    """Round at the same explicit IEEE binary32 boundaries as the Go reference."""
    return struct.unpack("!f", struct.pack("!f", value))[0]


def position_penalty(rating):
    if not _exact(rating, 1, 20):
        raise ValueError("Invalid effective position rating")
    if rating >= 15:
        return 20 - rating
    if rating >= 12:
        return (20 - rating) * 5 // 2
    return (20 - rating) * 4


def _threshold(bit, *, ability):
    if ability and bit & 0x100000:
        return 120
    if bit & 0x600100000000:
        return 100
    if bit & (0x9a000004000 if ability else 0x90000004000):
        return 80
    if bit & 0x4800000000:
        return 60
    return 0


def scale_ability(rating, best, ca):
    """FM27 float32 final scale step (before role threshold)."""
    return int(f32(min(f32(rating / best), 1.0) * f32(ca)))


def _scaled_role_ability(rating, best, ca, phase, bit):
    # No best eligible role is a known zero, not a missing denominator.
    if best == 0:
        return rating
    adjusted = rating
    if best > rating:
        distance = max(f32(1 - rating / best), 0)
        adjusted += (best - rating) // (int(f32(distance * 800) / 100) + 2)
    value = ca if adjusted == best else scale_ability(adjusted, best, ca)
    if phase == "ip" and value < _threshold(bit, ability=True):
        value //= 2
    return value


def _issue(field, reason):
    return {"field": field, "reason": reason}


def _exact(value, low, high):
    return type(value) is int and low <= value <= high


def _numeric_evidence(mapping, key, field, low, high, *, category=None):
    if not isinstance(mapping, Mapping):
        return None, _issue(field, "invalid_mapping")
    value = mapping.get(key)
    if value is None:
        return None, _issue(field, "category_only" if category is not None else "missing")
    if type(value) is not int:
        return None, _issue(field, "invalid_type")
    if not low <= value <= high:
        return None, _issue(field, "unsupported_value")
    return value, None


def input_evidence(player, *, required_attributes=(), required_positions=(), require_ca=False):
    """Check explicit dependencies; never infer exact inputs from display data.

    A numerical provider must supply its requested-role and best-role dependency
    closure separately. The latter can require more fields than the former.
    """
    issues = []
    attributes, positions = {}, {}
    scale = player.get("attribute_scale")
    if scale != "raw_1_100" and required_attributes:
        issues.append(_issue("attribute_scale", "missing" if scale is None else "unsupported_scale"))
    for name in sorted(set(required_attributes)):
        value, issue = _numeric_evidence(player.get("raw_attributes", {}), name, "raw_attributes." + name, 1, 100)
        if issue:
            issues.append(issue)
        elif scale == "raw_1_100":
            attributes[name] = value
    categories = player.get("position_categories", {})
    for code in sorted(set(required_positions)):
        if code not in tactic.POSITIONS:
            raise ValueError("Unknown position dependency")
        category = categories.get(code) if isinstance(categories, Mapping) else None
        value, issue = _numeric_evidence(player.get("positions", {}), code, "positions." + code, 1, 20,
                                         category=category)
        if issue:
            issues.append(issue)
        else:
            positions[code] = value
    ca = None
    if require_ca:
        ca, issue = _numeric_evidence(player, "current_ability", "current_ability", 1, 200)
        if issue:
            issues.append(issue)
    return {"raw_attributes": attributes, "positions": positions, "current_ability": ca, "issues": issues}


def _neighbours(bit, phase, position, side, base):
    if base < 12:
        return (), False
    if position in tactic.LEFT:
        side = "left"
    elif position in tactic.RIGHT:
        side = "right"
    rules = IP_BLEND if phase == "ip" else OOP_BLEND
    for mask, destination in rules:
        if not bit & mask:
            continue
        if destination == "false_nine":
            return ("amc",), True
        if destination in ("full_back", "wing_back", "wide_mid", "wide_attack"):
            pair = {"full_back": ("dl", "dr"), "wing_back": ("wbl", "wbr"),
                    "wide_mid": ("ml", "mr"), "wide_attack": ("aml", "amr")}[destination]
            if side in ("left", "right"):
                return (pair[side == "right"],), False
            return (pair if destination == "full_back" else ()), False
        return (destination,), False
    return (), False


def _rating(player, role, phase, position, side):
    """Reference rating at a known role/position; dependency-aware, no CA needed."""
    attributes = [a for group in ("key_attributes", "preferable_attributes", "negative_attributes") for a in role[group]]
    evidence = input_evidence(player, required_attributes=attributes, required_positions=[position])
    base = evidence["positions"].get(position)
    neighbours, false_nine = _neighbours(role["role_bit"], phase, position, side, base) if base is not None else ((), False)
    adjacent = input_evidence(player, required_positions=neighbours)
    issues = evidence["issues"] + adjacent["issues"]
    effective = None
    if base is not None and not adjacent["issues"]:
        effective = base
        if neighbours:
            other = max(adjacent["positions"].values())
            if false_nine:
                other = other // 2 if other < 15 else other
                effective = (base + other) // 2 if other else base
            elif other > base:
                effective = (base + other) // 2
    positional = {"position": position, "rating": base, "neighbours": adjacent["positions"],
                  "effective_rating": effective, "penalty_percent": position_penalty(effective) if effective is not None else None}
    if issues:
        return None, positional, issues
    values = evidence["raw_attributes"]
    key, pref, neg = (role[group] for group in ("key_attributes", "preferable_attributes", "negative_attributes"))
    # Class means and explicit rounding mirror the pinned reference; empty
    # classes contribute neither a sum nor a denominator weight.
    k = sum(values[a] for a in key) / len(key)
    p = 4 * sum(values[a] for a in pref) / len(pref) if pref else 0
    n = sum(max(100 - values[a], 1) for a in neg) / len(neg) if neg else 0
    weight = 16 + (4 if pref else 0) + (3 if neg else 0)
    v = f32(k * 16 + p)
    v = f32(v + n * 3)
    rating = int(f32(v / weight) * 2)
    return max(rating - rating * position_penalty(effective) // 100, 1), positional, []


def _distinct_issues(issues):
    return [_issue(field, reason) for field, reason in sorted({(i["field"], i["reason"]) for i in issues})]


def _best_rating(player, catalogue, phase):
    """Phase-local best role at unsided offered positions, as in the reference.

    Do not limit the denominator to the selected tactic or the user's XI
    eligibility threshold. Every possible offered position must be known;
    unknown candidate scores cannot be ignored even if another is known.
    """
    candidates = [(key, role, sorted({p["position"] for p in role["placements"]}))
                  for key, role in sorted(catalogue["roles"].items()) if key.startswith(phase + ".")]
    positions = {pos for _, _, offered in candidates for pos in offered}
    evidence = input_evidence(player, required_positions=positions)
    issues = list(evidence["issues"])
    best = 0
    ties = []
    for key, role, offered in candidates:
        for pos in offered:
            if evidence["positions"].get(pos, 0) < 10:
                continue
            rating, _, missing = _rating(player, role, phase, pos, "centre")
            issues.extend(missing)
            if rating is None or (phase == "ip" and rating < _threshold(role["role_bit"], ability=False)):
                continue
            if rating > best:
                best, ties = rating, []
            if rating == best:
                ties.append({"role_id": key, "position": pos})
    return (None, [], _distinct_issues(issues)) if issues else (best, ties, [])


def combine_abilities(phase_abilities, weights):
    """Provisional weighted mean, not a game formula; no missing-weight renormalization."""
    weights = tactic.phase_weights(weights)
    missing = [phase for phase in tactic.PHASES if weights[phase] > 0 and phase_abilities.get(phase) is None]
    if missing:
        return None, missing
    values = []
    for phase in tactic.PHASES:
        if weights[phase] == 0:
            continue
        ability = phase_abilities[phase]
        if not _exact(ability, 0, 200):
            raise ValueError("Invalid numeric role ability")
        values.append((Fraction(weights[phase]), ability))
    return float(sum(w * a for w, a in values) / sum(w for w, _ in values)), []


def _empty_phase(slot, phase, player, reason):
    part = slot[phase]
    pos = part["position"]
    evidence = input_evidence(player, required_positions=[pos] if pos is not None else [])
    return {"slot_id": slot["id"], "phase": phase, "position": pos, "side": part["side"],
            "role_id": part["role_id"], "role_status": part["role_status"],
            "role_rating": None, "role_ability": None, "rating_reason": reason, "ability_reason": reason,
            "position_evidence": {"position": pos, "rating": evidence["positions"].get(pos),
                                  "effective_rating": None},
            "rating_input_issues": evidence["issues"], "ability_input_issues": [],
            "best_role_rating": None, "best_role_ties": []}


def _gate(model, catalogue, player, build, database_version):
    if catalogue.get("origin") != "fm27_reference":
        return "unsupported_catalogue_origin"
    if model["catalogue_sha256"] != tactic.canonical_sha256(catalogue):
        return "model_catalogue_mismatch"
    if type(database_version) is not int or {"game_build": build, "database_version": database_version} not in model["supported_builds"]:
        return "unsupported_game_build"
    if (player.get("game_build") != build or type(player.get("database_version")) is not int or
            player["database_version"] != database_version):
        return "observation_build_mismatch"
    if type(player.get("schema_version")) is not int or player["schema_version"] != 1:
        return "unsupported_observation_schema"
    return None


def _placement_reason(catalogue, role_id, phase, position, side, dc_count, unknown_dc=0):
    if not isinstance(role_id, str) or not role_id.startswith(phase + ".") or role_id not in catalogue["roles"]:
        return "unknown_or_wrong_phase_role"
    role = catalogue["roles"][role_id]
    if {"position": position, "side": side} not in role["placements"]:
        return "unsupported_role_placement"
    if role["min_centre_backs"] > 0 or role["max_centre_backs"] < 10:
        if dc_count is None or dc_count < role["min_centre_backs"] or dc_count + unknown_dc > role["max_centre_backs"]:
            return "unconfirmed_formation_context"
    return None


def _evaluate(player, catalogue, role_id, phase, position, side, best):
    role = catalogue["roles"][role_id]
    rating, positional, rating_issues = _rating(player, role, phase, position, side)
    best_rating, ties, best_issues = best
    ca_evidence = input_evidence(player, require_ca=True)
    ability_issues = _distinct_issues(rating_issues + best_issues + ca_evidence["issues"])
    ability = None if ability_issues or rating is None or best_rating is None else _scaled_role_ability(
        rating, best_rating, ca_evidence["current_ability"], phase, role["role_bit"])
    ability_reason = None if ability is not None else ("role_rating_unavailable" if rating is None else
                     "best_role_search_incomplete" if best_rating is None else "current_ability_unavailable")
    return {"role_rating": rating, "role_ability": ability,
            "rating_reason": "rating_inputs_unavailable" if rating is None else None,
            "ability_reason": ability_reason, "position_evidence": positional,
            "rating_input_issues": rating_issues, "ability_input_issues": ability_issues,
            "best_role_rating": best_rating, "best_role_ties": ties}


def evaluate_role(player, catalogue, role_id, phase, position, side, *, model_id, game_build,
                  database_version, centre_back_count=None):
    """Pure single-role API for an explicitly permitted tactical placement."""
    model = MODELS.get(model_id)
    reason = "unknown_model" if model is None else _gate(model, catalogue, player, game_build, database_version)
    if phase not in tactic.PHASES or position not in tactic.POSITIONS or side not in tactic.SIDES:
        raise ValueError("Invalid role phase, position or side")
    if centre_back_count is not None and not _exact(centre_back_count, 0, 10):
        raise ValueError("Invalid formation context")
    reason = reason or _placement_reason(catalogue, role_id, phase, position, side, centre_back_count)
    slot = {"id": None, phase: {"position": position, "side": side, "role_id": role_id, "role_status": "user_defined"}}
    result = _empty_phase(slot, phase, player, reason)
    if reason is None:
        result.update(_evaluate(player, catalogue, role_id, phase, position, side, _best_rating(player, catalogue, phase)))
    return {**result, "model_id": model_id, "model_sha256": MODEL_SHA256 if model else None,
            "evidence_status": model["evidence_status"] if model and reason is None else None}


def assess_tactic(selection, catalogue, player, *, model_id, game_build, database_version):
    """Return one report over eleven R2 slots, with explicit per-phase results.

    Accept the validated selection envelope (including catalogue/tactic hashes).
    No automatic model selection or fallback. This is not an operational report.
    """
    if type(selection.get("version")) is not int or selection["version"] != 1:
        raise ValueError("Unsupported selection envelope")
    config = selection["tactic"]
    if type(config.get("version")) is not int or config["version"] != 2 or len(config["slots"]) != 11:
        raise ValueError("Expected validated R2 tactic")
    if len({s["id"] for s in config["slots"]}) != 11:
        raise ValueError("Duplicate tactical slot ID")
    if selection["tactic_sha256"] != tactic.tactic_sha256(config):
        raise ValueError("Tactic hash mismatch")
    digest = tactic.canonical_sha256(catalogue)
    if selection["catalogue"]["sha256"] != digest:
        raise ValueError("Catalogue hash mismatch")
    if not isinstance(player, Mapping) or not isinstance(player.get("player_id"), str) or not player["player_id"]:
        raise ValueError("Missing stable player identity")
    model = MODELS.get(model_id)
    if model is None:
        reason = "unknown_model"
        metadata = {"id": model_id, "version": None, "sha256": None, "evidence_status": None}
    else:
        reason = _gate(model, catalogue, player, game_build, database_version)
        metadata = {**deepcopy(model), "sha256": MODEL_SHA256}
    best = {phase: _best_rating(player, catalogue, phase) for phase in tactic.PHASES} if reason is None else {}
    context = {phase: (sum(s[phase]["position"] == "dc" for s in config["slots"]),
                      sum(s[phase]["position"] is None and s["selection_position"] != "gk" for s in config["slots"]))
               for phase in tactic.PHASES}
    slots = []
    for slot in config["slots"]:
        phases = {}
        for phase in tactic.PHASES:
            part = slot[phase]
            unresolved = (part["role_status"] != "user_defined" or part["role_id"] is None or
                          part["position"] is None or part["side"] is None)
            phase_reason = "unresolved_role_or_geometry" if unresolved else reason
            if phase_reason is None:
                phase_reason = _placement_reason(catalogue, part["role_id"], phase, part["position"], part["side"], *context[phase])
            result = _empty_phase(slot, phase, player, phase_reason)
            if phase_reason is None:
                result.update(_evaluate(player, catalogue, part["role_id"], phase, part["position"], part["side"], best[phase]))
            result["model_id"] = model_id
            result["model_sha256"] = metadata["sha256"]
            result["evidence_status"] = metadata["evidence_status"] if phase_reason is None else None
            phases[phase] = result
        combined, missing = combine_abilities({p: phases[p]["role_ability"] for p in tactic.PHASES}, config["phase_weights"])
        slots.append({"slot_id": slot["id"], **phases, "combined_role_ability": combined,
                      "missing_weighted_phases": missing})
    return {"version": 1, "player_id": player["player_id"], "career": player.get("career"),
            "record_game_date": player.get("record_game_date"), "observation_source": deepcopy(player.get("source")), "game_build": game_build,
            "database_version": database_version, "tactic_sha256": selection["tactic_sha256"],
            "catalogue_sha256": digest, "model": metadata, "model_unavailable_reason": reason,
            "phase_weights": config["phase_weights"], "aggregation": "provisional_weighted_mean",
            "slots": slots}
