"""Validated tactical configuration, independent of observations and scoring."""
import math
import re
import tomllib


VERSION = 1
# The native fmsave vocabulary (score.py FM_POSITIONS); stc is displayed as ST.
FM_POSITION_CODES = frozenset(("gk", "sw", "dl", "dc", "dr", "dm", "ml", "mc", "mr",
                              "aml", "amc", "amr", "stc", "wbl", "wbr"))
SIDES = frozenset(("left", "centre", "right"))
PHASES = ("ip", "oop")
PROFILE_POSITION_CODES = {"GK": ("gk",), "FB": ("dl", "dr", "wbl", "wbr"), "CB": ("dc", "sw"),
                          "6": ("dm", "mc"), "wing": ("aml", "amr", "ml", "mr"), "10": ("amc", "mc"), "9": ("stc",)}


def table(value, field, required, optional=()):
    if not isinstance(value, dict):
        raise ValueError(f"{field}: expected a TOML table")
    missing = set(required) - value.keys()
    extra = value.keys() - set(required) - set(optional)
    if missing:
        raise ValueError(f"{field}: missing fields {', '.join(sorted(missing))}")
    if extra:
        raise ValueError(f"{field}: unknown fields {', '.join(sorted(extra))}")


def text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field}: expected nonempty text")
    return value.strip()


def choice(value, allowed, field):
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(f"{field}: expected one of {', '.join(sorted(allowed))}, got {value!r}")
    return value


def phase(value, field, side):
    if value is None:
        return {"position": None, "side": None, "role": None, "suitability": None}
    table(value, field, ("position",), ("side", "role"))
    return {
        "position": choice(value["position"], FM_POSITION_CODES, f"{field}.position"),
        "side": choice(value.get("side", side), SIDES, f"{field}.side"),
        "role": text(value["role"], f"{field}.role") if "role" in value else None,
        "suitability": None,
    }


def validate_formation(config, profiles):
    """Return a JSON-ready contract in declared slot order.

    Profiles are supplied by the selected scoring model; their coefficients
    are never read or modified here. Phase locations describe responsibilities,
    while accepted positions describe native FM positions permitted for a slot.
    """
    table(config, "formation", ("version", "name", "phase_weights", "slots"))
    if type(config["version"]) is not int or config["version"] != VERSION:
        raise ValueError(f"formation.version: expected {VERSION}, got {config['version']!r}")
    name = text(config["name"], "formation.name")
    weights = config["phase_weights"]
    table(weights, "phase_weights", PHASES)
    phase_weights = {}
    for key in PHASES:
        value = weights[key]
        try:
            valid = type(value) in (int, float) and math.isfinite(value) and value >= 0
        except OverflowError:
            valid = False
        if not valid:
            raise ValueError(f"phase_weights.{key}: expected a finite nonnegative number")
        phase_weights[key] = float(value)
    total = sum(phase_weights.values())
    if not math.isfinite(total) or total <= 0:
        raise ValueError("phase_weights: total must be finite and greater than zero")

    raw_slots = config["slots"]
    if not isinstance(raw_slots, list) or len(raw_slots) != 11:
        raise ValueError("formation.slots: expected exactly 11 player slots")
    slots, seen = [], set()
    for index, raw in enumerate(raw_slots, 1):
        field = f"slots[{index}]"
        table(raw, field, ("id", "label", "side", "positions", "profile"), (*PHASES, "selection_position"))
        identifier = text(raw["id"], f"{field}.id")
        if not re.fullmatch(r"[a-z][a-z0-9_-]*", identifier):
            raise ValueError(f"{field}.id: use a lowercase machine ID starting with a letter")
        if identifier in seen:
            raise ValueError(f"{field}.id: duplicate slot ID {identifier!r}")
        seen.add(identifier)
        field = f"slot {identifier!r}"
        side = choice(raw["side"], SIDES, f"{field}.side")
        label = text(raw["label"], f"{field}.label")
        profile = choice(raw["profile"], profiles, f"{field}.profile")
        accepted = raw["positions"]
        if not isinstance(accepted, list) or not accepted:
            raise ValueError(f"{field}.positions: expected a nonempty array of native FM position codes")
        positions = [choice(code, FM_POSITION_CODES, f"{field}.positions") for code in accepted]
        if len(set(positions)) != len(positions):
            raise ValueError(f"{field}.positions: duplicate position code")
        selection_position = choice(raw.get("selection_position", positions[0]), set(positions), f"{field}.selection_position")
        if (profile == "GK" and positions != ["gk"]) or (profile != "GK" and "gk" in positions):
            raise ValueError(f"{field}: GK profile and goalkeeper position must agree")
        if profile in PROFILE_POSITION_CODES and selection_position not in PROFILE_POSITION_CODES[profile]:
            raise ValueError(f"{field}.selection_position: no inherited {profile} profile mapping for {selection_position}")
        phases = {key: phase(raw.get(key), f"{field}.{key}", side) for key in PHASES}
        for key, responsibility in phases.items():
            pos = responsibility["position"]
            if pos is not None and (pos == "gk") != (profile == "GK"):
                raise ValueError(f"{field}.{key}.position: goalkeeper and outfield positions cannot be interchanged")
        slots.append({"id": identifier, "label": label, "side": side, "positions": positions,
                      "profile": profile, "selection_position": selection_position, **phases})
    if sum(slot["profile"] == "GK" for slot in slots) != 1:
        raise ValueError("formation.slots: expected exactly one GK slot")
    return {"version": VERSION, "name": name, "phase_weights": phase_weights, "slots": slots}


def load_formation(path, model):
    """Load a versioned TOML file using the existing model's profile names."""
    profiles = set(model["outfield"]) | ({"GK"} if "gk" in model else set())
    try:
        with path.open("rb") as stream:
            config = tomllib.load(stream)
        return validate_formation(config, profiles)
    except (OSError, ValueError) as exc:
        raise ValueError(f"Formation {path}: {exc}") from exc
