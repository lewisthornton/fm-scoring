# R2: tactic-driven role configuration (version 2)

This is a separate, experimental configuration contract. It is **not** an FM27
role catalogue or role-ability implementation. All identifiers, labels and
restrictions in `synthetic-role-catalogue.toml` are invented for structural
tests. `ROLE_ABILITY_R1.md` remains the licensing and validation gate for real
role definitions and numerical reconstruction.

`formation.py`, `--formation` on the Rangers bridge, the v1 `formation.json`,
tactical assessments, eligibility policy, scores, XI/depth/signing algorithms,
benchmarks and the standalone bridge launcher are unchanged. Nothing in the
operational scoring pipeline imports `tactic.py`. In particular, selecting a
v2 tactic does not change the formation used by the operational scorer. Do not
pass a v2 file to the old `--formation` option. This separation is intentional
until R3 and subsequent integration have been independently approved.

## Manual selection

Use Python 3.11+ from the repository checkout, without fmsave or FM installed.
The example registry contains four named configurations: two synthetic v2
tactics, and both existing v1 formations. The registry has no default or
active entry. The selection command requires an exact explicit ID:

```text
python tactic.py --registry formations/tactic-registry.example.toml --catalogue formations/synthetic-role-catalogue.toml --select synthetic-asymmetric --output selected_tactic.json
```

On Windows use `py` if that is your Python command. Choose an existing output
directory (prefer a private or gitignored directory for personal tactics).
Copy the catalogue, registry and desired configurations to a local directory
and edit them there. Paths in the registry are relative to the registry's
directory (absolute paths also work). A v2 file's `id` must equal its registry
key; a v1 file receives the explicitly selected registry ID. Other entries
are not implicitly activated or read when selecting one. Keys must be unique
(duplicate TOML keys are rejected). For example:

```toml
version = 1
[tactics]
synthetic-433 = "synthetic-433.toml"
synthetic-asymmetric = "synthetic-asymmetric.toml"
```

The command validates the chosen file and catalogue before writing a separate
JSON document. It writes a temporary file in the destination directory and
uses `os.replace` to publish, closing the temporary file first on Windows.
Invalid TOML, unknown selection, invalid catalogue or tactic and replacement
failure leave the existing valid selection intact. The parent directory must
exist. The command refuses the six established operational report filenames;
use a distinct `selected_tactic.json`. There is no watcher or UI in R2.

## Catalogue v1

Required top-level fields: `version = 1`, `id`, `origin = "synthetic"`, `source`
(nonempty provenance text), and nonempty `[[roles]]` entries. The `id` of each
role is a phase-qualified lowercase machine ID, unique across the catalogue.
The label is presentation text, not an identifier. For example:

```toml
[[roles]]
id = "ip.triangle"
label = "Triangle node"
placements = [{position = "dc", side = "right"}]
min_centre_backs = 3
```

This invented role is valid only at the listed IP position/side, with at
least three DC slots in the IP shape. The optional integer `max_centre_backs`
defaults to 10; the minimum defaults to 0. Both describe counts in the
role's own phase, not the selection formation or the opposite phase. A draft
with unknown outfield phase positions can satisfy a count restriction only
if the count is guaranteed: known DC count >= minimum and known DC plus
unresolved outfield positions <= maximum. Unknown GK positions cannot be
DC. Placements are explicit position/side pairs, not an implied cross-product.
There are no role-specific weights, attribute lists, numerical parameters or
game-verified labels in the catalogue format. Unsupported fields are rejected.
Real catalogue origins and role evidence will need an explicitly reviewed
extension after rights clearance; they are not accepted in R2.

## Tactic v2 input

The required fields are `version = 2`, stable `id`, `name`, `source`,
`phase_weights`, and exactly eleven `[[slots]]` in declared assignment order.
Example (one of eleven slots):

```toml
version = 2
id = "synthetic-asymmetric"
name = "Synthetic asymmetric 4-2-3-1"
source = {kind = "manual", reference = "Invented R2 example"}
phase_weights = {ip = 0.65, oop = 0.35}

[[slots]]
id = "rb"
label = "Right-back"
side = "right"
selection_position = "dr"
positions = ["dr", "wbr"]
legacy_profile = "FB"
ip = {position = "dc", side = "right", role_status = "user_defined", role_id = "ip.triangle"}
oop = {position = "dr", side = "right", role_status = "user_defined", role_id = "oop.base"}
```

Slot IDs are unique lowercase machine identifiers starting with a letter;
reuse the same ID for the same eventual player across both phases. `side`
describes the selection slot, independently of each phase's side. The native
position vocabulary is shared with `formation.py` (including `stc`, not `st`).
Flank positions require their corresponding side; GK and SW require centre;
other central codes allow left, centre or right. Each known GK phase must
belong to the one GK selection slot; outfield/GK interchange is rejected.
An optional `positions` list preserves accepted positions for relaxed
eligibility, defaulting to just `selection_position`. It must include that
position and contain unique native codes in the same GK/outfield domain.
`legacy_profile` is optional context, with the inherited profile-position
mapping validated if supplied. It does not score a role.

Both phase tables must exist. Exact geometry (`position`, `side`) is
required to configure a role. Omit unknown geometry fields and give a
`geometry_reason`; output represents missing values as JSON null. Phase
weights are finite nonnegative numbers with positive finite total and are
preserved, not normalized. A zero-weight phase may remain unresolved without
blocking configuration for the positively weighted phases. The phase weights
are provisional configuration, not calibrated performance coefficients.

| Role status | `role_id` | Evidence |
| --- | --- | --- |
| `user_defined` | Explicit synthetic catalogue key in the correct phase | Manual configuration, not game observation |
| `unknown` | null | No established identity |
| `ambiguous` | null | Multiple plausible interpretations |
| `unsupported` | null | Source reports a role outside supported decoding |

For unresolved statuses supply a nonempty `role_reason`; optionally retain
`raw_role_token` and descriptive `role_label`. For example:

```toml
oop = {position = "dr", side = "right", role_status = "ambiguous", role_reason = "Role bits do not identify a unique role", raw_role_token = "invented-token"}
```

A token that happens to look like a catalogue key remains a token. A known
key cannot be assigned to an unresolved phase; there is no position-based or
label-based role inference. `game_observed` is deliberately rejected in R2:
no source capable of verifying actual game identities has been integrated.
Manual instructions may optionally be an ordered array of nonempty text;
they are descriptive and annotated `instruction_source=user_defined`.
Imported instructions, if present, are marked `unverified_import`. Neither
affects scoring. Unknown fields, invalid types and context combinations fail
validation rather than being silently ignored.

## Legacy compatibility

The existing v1 loader remains unchanged, including backwards-compatible
selection-position defaults, custom role labels and output hashes. The new
selector also accepts the existing v1 TOML files for the seven inherited
profiles and projects them into the separate v2 output: `input_version=1`,
`source.kind=legacy_v1`, preserved slot/position/side/weight/profile data and
descriptive labels, with **all** exact `role_id` values null and role reason
`legacy_descriptive_role_only`. A missing legacy phase stays unknown. It does
not retrospectively impose v2 role or side rules on v1 files. The standalone
v1 loader retains its existing custom-profile support.

## Output, canonical identity and R3 interface

`tactic.select_tactic(registry_path, catalogue_path, selected_id)` returns a
JSON-ready selection envelope without writing anything. The related pure
functions are `validate_catalogue`, `validate_tactic`, `load_tactic` and
`tactic_sha256`. `publish_selection` performs the explicit atomic write.

| Output field | Contract |
| --- | --- |
| `version` | Selection-envelope version 1 |
| `selected_id` | Explicit registry key |
| `tactic` | Normalized v2 contract, including `input_version`, ID, name, source, phase weights and slots in declared order |
| `tactic.source` | Kind and reference; for file input, SHA-256 of exact input file bytes |
| `tactic_sha256` | SHA-256 of compact sorted-key UTF-8 JSON of version, name, normalized phase weights and ordered slots |
| `catalogue` | ID, version, synthetic origin, source text and SHA-256 of normalized catalogue |
| `configuration_status` | `configured` for all positively weighted responsibilities resolved; `draft` otherwise |
| `unresolved_weighted_phases` | Ordered slot-ID/phase records for unresolved positive-weight responsibilities |
| `role_scoring_available` | Always false in R2, even when configured |

Canonical hashes preserve slot order (tie-breaking order matters), accepted
position order (relaxed eligibility order matters), instructions and all
normalized responsibility evidence. Source path, exact file hash, source
metadata and registry ID are deliberately separate from canonical tactic
content; key order, whitespace and integer-versus-float weight spelling do
not change content identity. Catalogue role and placement order is
canonicalized; catalogue contents are hashed independently. Use both hashes
when binding a role model to an assessment. Neither hash is a signature or
proof of game validity. The output is a read-only normalized contract rather
than a TOML input document to round-trip through the validator.

For R3, the future pure numerical engine will receive the normalized tactic,
the validated catalogue and its matching hash, player raw-input contract from
R1, and an explicitly selected model/build version. Enumerate all eleven
stable slot IDs and `ip`/`oop` independently. Resolve each phase by the exact
role ID (not its label), position, side and context. Reject unknown or
unsupported catalogue/model/build combinations, and never invent missing
observations. Attach role rating and CA-scaled role ability separately with
evidence status, and combine only supported positively weighted phases using
the configured weights. A missing positive phase yields null; no implicit
renormalization. Keep familiarity-based eligibility independent; do not add
an unexplained positional penalty. The existing operational model, policy
and numerical reports are not consumers of this R2 selection envelope.

## Future save adapter

`adapt_save_tactic(snapshot, expected_team, catalogue, tactic_id=..., weights=...)`
is a boundary for normalized parser data, **not a binary or fmsave reader**.
It requires `source.kind=save_import` plus career, club ID, first-team ID,
game build, parser version, source save SHA-256 and nonnegative `stored_index`,
and `team_slot=0`. The caller supplies the independently established managed
career/club/team IDs in `expected_team`; mismatches fail closed. Nothing
infers the active tactic from stored index or list order. No save is opened.

Each of the eleven ordered input rows includes stable ID, label, native
selection position, side, IP/OOP responsibility tables and a numeric
`defending_index`. Positions/sides must already be reliably normalized by
the caller, otherwise remain unknown for the phase; no raw mask or side
mapping is guessed. The selection position and selection side must be known
to form a valid tactic. Before pairing, all indexes must form a permutation
of 0 through 10. For IP row `i`, take the **entire** OOP responsibility from
stored row `defending_index[i]`, retaining row `i`'s slot ID. Never invert
the permutation or pair merely by row order. Role IDs cannot be resolved by
this adapter; retain explicit unknown/ambiguous/unsupported roles and raw
tokens. Import evidence cannot claim a user-defined role or game-observed
identity. The manual registry refuses imported-source claims; this adapter
requires explicit expected team identity instead. Later integration must
verify fmsave version, reader completeness, position bits, side mapping,
selection correspondence, rights and actual role decoding before it can
publish game-observed role IDs. R2's tests only use constructed records.

## Verification

```text
python -m unittest discover -s tests -p test_tactic.py -v
python -m unittest discover -s tests -v
```

The existing Windows/Ubuntu Python 3.11/3.12 matrix automatically includes
the new tests; no requirements or CI changes are necessary. Licensing and
independent game-numeric validation remain outstanding per R1. The synthetic
catalogue is for configuration tests only, not a substitute scoring model.
