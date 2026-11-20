"""Pure position evidence and tactical slot assessments for a validated formation."""
import hashlib
import json
import re
from typing import Literal, TypedDict


Availability = Literal["available", "unavailable", "unknown"]
LoanState = Literal["permanent", "incoming", "outgoing", "unknown"]


class PositionEvidence(TypedDict):
    position: str
    status: Literal["observed", "inferred_category", "missing"]
    rating: int | None
    category: Literal["natural", "accomplished", "below_accomplished"] | None
    lower_bound: int | None
    upper_bound: int | None
    source: str | None
    reason: str | None


class PhaseAssessment(TypedDict):
    position: str | None
    side: str | None
    role: str | None
    familiarity: PositionEvidence | None
    position_fit: int | None
    position_fit_reason: str | None
    observed_role_suitability: None


class SlotAssessment(TypedDict):
    player_id: str
    slot_id: str
    label: str
    side: str
    profile: str
    selection_position: str
    availability: Availability
    accepted_positions: dict[str, PositionEvidence]
    ip: PhaseAssessment
    oop: PhaseAssessment
    attribute_profile_score: float | None
    attribute_profile_reason: str | None
    missing_attributes: list[str]
    combined_position_fit: float | None
    combined_position_fit_reason: str | None
    missing_weighted_phases: list[str]
    missing_evidence: list[str]


class PlayerAssessment(TypedDict):
    player_id: str
    name: str
    display_name: str
    club: str
    cohorts: list[str]
    availability: Availability
    loan_state: LoanState
    keeper: bool
    record_game_date: str | None
    last_seen_game_date: str | None
    game_build: str | None
    position_evidence: dict[str, PositionEvidence]
    slots: list[SlotAssessment]


class FormationProvenance(TypedDict):
    name: str
    version: int
    source: str
    sha256: str


class ModelProvenance(TypedDict):
    name: str
    sha256: str


class AssessmentReport(TypedDict):
    version: int
    career: str
    game_date: str | None
    formation: FormationProvenance
    scoring_model: ModelProvenance
    position_evidence_source: str
    position_fit_units: str
    attribute_profile_units: str
    observed_role_suitability_source: None
    source_limitations: list[str]
    source_data: dict[str, bool]
    players: list[PlayerAssessment]


def category_codes(value):
    """Read the native position tokens from legacy text or fmsave sequences."""
    if isinstance(value, str):
        tokens = re.split(r"[;,/|\s]+", value.strip().lower())
    elif isinstance(value, (list, tuple)):
        tokens = [token.strip().lower() for token in value if isinstance(token, str)]
    else:
        tokens = []
    return {"stc" if token == "st" else token for token in tokens}


def exact_rating(value):
    """Accept integer ratings only; reject fractional, boolean and invalid input."""
    if isinstance(value, str):
        value = value.strip()
        if not re.fullmatch(r"[0-9]{1,2}", value):
            return None
        value = int(value)
    return value if type(value) is int and 1 <= value <= 20 else None


def position_evidence(raw, codes) -> dict[str, PositionEvidence]:
    """Independent exact ratings or explicitly bounded category evidence per code."""
    natural = category_codes(raw.get("natural_positions"))
    accomplished = category_codes(raw.get("accomplished_positions"))
    evidence = {}
    for code in sorted(codes):
        field = "positions_" + code
        raw_value = raw.get(field)
        rating = exact_rating(raw_value)
        missing = raw_value is None or (isinstance(raw_value, str) and not raw_value.strip())
        entry: PositionEvidence = {
            "position": code, "status": "missing", "rating": None, "category": None,
            "lower_bound": None, "upper_bound": None, "source": None,
            "reason": "missing_position_rating",
        }
        if rating is not None:
            category = "natural" if rating >= 18 else "accomplished" if rating >= 15 else "below_accomplished"
            entry.update(status="observed", rating=rating, category=category, source=field, reason=None)
        elif not missing:
            entry.update(source=field, reason="invalid_position_rating")
        elif code in natural and code in accomplished:
            entry.update(source="natural_positions,accomplished_positions", reason="conflicting_categories")
        elif code in natural:
            entry.update(status="inferred_category", category="natural", lower_bound=18, upper_bound=20,
                         source="natural_positions", reason="category_only")
        elif code in accomplished:
            entry.update(status="inferred_category", category="accomplished", lower_bound=15, upper_bound=17,
                         source="accomplished_positions", reason="category_only")
        evidence[code] = entry
    return evidence


def phase_assessment(responsibility, evidence) -> PhaseAssessment:
    code = responsibility["position"]
    familiarity = evidence[code] if code is not None else None
    return {
        "position": code, "side": responsibility["side"], "role": responsibility["role"],
        "familiarity": familiarity,
        "position_fit": familiarity["rating"] if familiarity is not None else None,
        "position_fit_reason": familiarity["reason"] if familiarity is not None else "phase_position_unspecified",
        # Supported fmsave player exports contain no role-specific measurements.
        "observed_role_suitability": None,
    }


def assess_player(formation, model, player, evidence, *, scorer) -> list[SlotAssessment]:
    """Assess every slot independently, without assigning players or ranking them."""
    profiles = {"GK": model["gk"], **model["outfield"]}
    applicable = {"GK": profiles["GK"]} if player["keeper"] else model["outfield"]
    scores = scorer(player["attrs"], applicable)
    weights = formation["phase_weights"]
    total = sum(weights.values())
    slots = []
    for slot in formation["slots"]:
        profile = slot["profile"]
        accepted = {code: evidence[code] for code in slot["positions"]}
        phases = {phase: phase_assessment(slot[phase], evidence) for phase in ("ip", "oop")}
        missing_weighted = [phase for phase, result in phases.items()
                            if weights[phase] > 0 and result["position_fit"] is None]
        combined = None if missing_weighted else sum(
            weights[phase] / total * phases[phase]["position_fit"]
            for phase in phases if weights[phase] > 0
        )
        missing_attrs = [name for name in profiles[profile] if name not in player["attrs"]]
        score_reason = ("incompatible_player_type" if profile not in applicable else
                        "missing_attributes" if missing_attrs else None)
        missing = [f"accepted:{code}:{item['reason']}" for code, item in accepted.items() if item["reason"]]
        missing.extend(f"{phase}:{result['position_fit_reason']}" for phase, result in phases.items()
                       if result["position_fit_reason"])
        if score_reason == "missing_attributes":
            missing.extend(f"attribute:{name}" for name in missing_attrs)
        missing.append("observed_role_suitability:unsupported_source")
        slots.append({
            "player_id": player["player_id"], "slot_id": slot["id"], "label": slot["label"],
            "side": slot["side"], "profile": profile, "availability": player["availability"],
            "selection_position": slot.get("selection_position", slot["positions"][0]),
            "accepted_positions": accepted, **phases,
            "attribute_profile_score": scores.get(profile), "attribute_profile_reason": score_reason,
            "missing_attributes": missing_attrs, "combined_position_fit": combined,
            "combined_position_fit_reason": "missing_numeric_phase_evidence" if missing_weighted else None,
            "missing_weighted_phases": missing_weighted, "missing_evidence": missing,
        })
    return slots


def build_assessments(formation, model, people, *, codes, scorer, career, formation_source, model_sha256) -> AssessmentReport:
    """Return a deterministic JSON-ready report over already scoped player records."""
    players = []
    for person in sorted(people, key=lambda p: p["player_id"]):
        evidence = position_evidence(person["raw"], codes)
        players.append({
            "player_id": person["player_id"], "name": person["raw"]["name"],
            "display_name": person["name"], "club": person["club"], "cohorts": sorted(person["cohorts"]),
            "availability": person["availability"], "loan_state": person["loan_state"],
            "keeper": person["keeper"], "record_game_date": person.get("record_game_date"),
            "last_seen_game_date": person.get("last_seen_game_date"), "game_build": person.get("game_build"),
            "position_evidence": evidence,
            "slots": assess_player(formation, model, person, evidence, scorer=scorer),
        })
    canonical = json.dumps(formation, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    game_date = max((p["last_seen_game_date"] for p in players if p["last_seen_game_date"]), default=None)
    return {
        "version": 1, "career": career, "game_date": game_date,
        "formation": {"name": formation["name"], "version": formation["version"], "source": formation_source,
                      "sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest()},
        "scoring_model": {"name": "fm27v2.toml", "sha256": model_sha256},
        "position_evidence_source": "fmsave player export",
        "position_fit_units": "FM position rating scale (1–20)",
        "attribute_profile_units": "weighted attribute mean (1–20)",
        "observed_role_suitability_source": None,
        "source_limitations": ["Save-file attributes may include values hidden by in-game scouting knowledge.", "Role labels are configuration only; observed role suitability is unsupported.", "Phase familiarity is contextual, not the assignment objective."],
        "source_data": {"may_include_unscouted_attributes": True, "observed_role_suitability_available": False},
        "players": players,
    }
