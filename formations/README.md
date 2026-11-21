# Tactical formation configuration (version 1)

The default is an invented conventional 4-3-3 using the seven existing
fm27v2 scoring profiles. `asymmetric-4231.toml` is an invented alternative
with an overlapping left-back, a conservative right-back and different IP/OOP
locations. Copy either TOML file to a local location to make your own formation.

## Format

```toml
version = 1
name = "My tactic"

[phase_weights]
ip = 0.65
oop = 0.35

[[slots]]
id = "lb"
label = "Attacking left-back"
side = "left"
positions = ["dl", "wbl"]
selection_position = "dl"
profile = "FB"
ip = { position = "wbl", role = "Overlap and cross" }
oop = { position = "dl", role = "Recover to back four" }
```

Supply exactly 11 slot tables, including one goalkeeper. Slot IDs are unique
lowercase machine identifiers starting with a letter; keep them stable when a
label, scoring profile or tactical responsibility changes. A slot is one
eventual player assignment across both phases. Two CB slots can have distinct
IDs, labels and responsibilities despite using the same scoring profile.

- `side` is `left`, `centre` or `right`. The accepted `positions` array uses
  the existing native FM codes:
  `gk, sw, dl, dc, dr, dm, ml, mc, mr, aml, amc, amr, stc, wbl, wbr`.
  The striker code is `stc` (displayed as ST in the native dashboard).
  `selection_position` is the single native position being assigned and must
  occur in `positions`. Legacy TOML omitting it uses the first listed position.
  Other listed positions supply context, not an eligibility substitute.
- `profile` references the selected model's existing `GK`, `FB`, `CB`,
  `6`, `wing`, `10` or `9` scoring profile. No weights are defined here.
- The optional `ip` and `oop` tables each require a native FM `position` and
  may include a custom human-readable `role` and a phase-specific `side`.
  The side defaults to the slot side. Phase locations may differ from the
  accepted positions: they describe the responsibility in the tactical shape,
  not the player's current position familiarity. Omitting a phase leaves its
  responsibilities unknown; omitting a role leaves the role label unknown.
- Phase weights are finite nonnegative numbers with a finite positive total.
  They are preserved as configured (they do not need to sum to one).
  They determine the combined positional familiarity when both weighted
  phase positions have observed numeric ratings, not the XI objective.

Unknown fields, invalid values, malformed roles, duplicate IDs, unsupported
versions and invalid slot counts are rejected before publishing new output.

## Selecting a formation in Rangers

The existing launcher defaults to the selected checkout's
`formations/default.toml`. Pass an explicit local TOML path to choose another:

```powershell
py C:\FMAnalytics\rangers_fm_scoring_bridge.py --fm-scoring-root "C:\path\to\fm-scoring" --formation "C:\path\to\my-formation.toml" --watch
```

Relative explicit paths are resolved from the launcher's working directory.
Watch mode notices edits to the selected file. Invalid edits leave the last
valid output intact and are retried on the next polling cycle. The selected
checkout must contain `formation.py` and the default TOML when no path is
supplied; no additional Python module is needed beside the standalone bridge.

After successful generation, the bridge publishes deterministic
`out/<slug>/formation.json` containing the validated formation name, version,
phase weights and ordered slots. All roles have `suitability: null` because no
FM role suitability measurements are available in this milestone. The existing
positional score is a separate weighted attribute score. Existing recruitment
and native dashboard HTML remains unchanged for either formation. The separate
[tactical assessment contract](ASSESSMENTS.md) exposes position-based fit and
attribute scores per player and slot. No player assignment or FM role suitability
inference takes place in the formation loader; the separate XI optimiser
uses the validated selection position and attribute profile score.

In Python, `formation.load_formation(path, model)` loads TOML and returns a
JSON-ready dictionary. `formation.validate_formation(config, profiles)` validates
a parsed dictionary against the supplied profile names. Neither requires
player observations, SQLite or fmsave.
