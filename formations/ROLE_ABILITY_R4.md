# R4 — Scoped raw observations and opt-in role assessments

Base: `67d0a84e58908ad2c23eb707969f95d0104af50e`.
R4 connects the existing watcher to the R3 reference engine through a **separate
read-only report command**. It does not activate that engine. The existing
watcher command, standalone Windows launcher, bridge, v1 formations, operational
JSON/HTML, fm27v2 scoring, optimiser, depth, simulations and benchmarks retain
their behaviour. No schema migration, private save or game installation is
required for verification.

## Evidence and compatibility

The parser contract is pinned to `rhiever/fmsave` 0.14.3 revision
`755fe9c566bb0497d4ad6ef6e1ac1fd2fde7351b`:

- [Player records](https://github.com/rhiever/fmsave/blob/755fe9c566bb0497d4ad6ef6e1ac1fd2fde7351b/src/fmsave/models/players.py): raw/display attribute groups, separate raw feet, CA, 15 native positions, team ID and slot.
- [Tactic records](https://github.com/rhiever/fmsave/blob/755fe9c566bb0497d4ad6ef6e1ac1fd2fde7351b/src/fmsave/models/tactics.py): per-team stored tactics, 11 ordered slots, nested unknown role bits, defending index, named position codes; the selected tactic is not known.
- [Club records](https://github.com/rhiever/fmsave/blob/755fe9c566bb0497d4ad6ef6e1ac1fd2fde7351b/src/fmsave/models/clubs.py): club's ordered teams and affiliate flag.
- [CLI](https://github.com/rhiever/fmsave/blob/755fe9c566bb0497d4ad6ef6e1ac1fd2fde7351b/src/fmsave/cli.py), [export](https://github.com/rhiever/fmsave/blob/755fe9c566bb0497d4ad6ef6e1ac1fd2fde7351b/src/fmsave/export.py): `info --json` keys `game`, `build`, `db_version`, `fmsave_version`, `known_build`, `game_date`; CSV group names are flattened, JSON without `--columns` is nested and coded values use both label and `_code` fields.
- [fm-mcp position masks](https://github.com/Napas/fm-mcp/blob/4f19a3f0d1130e47d604173a78ff01642f538d52/internal/savefile/tacticnames.go): reference side flags `0x100000` / `0x200000`; see [R3 attribution](THIRD_PARTY_ROLE_ABILITY.md). No role-token interpretation is derived from this.

These are inspected source contracts, not an independent real-save parsing or
FM game-numeric validation. The integration suite constructs invented data
matching the documented export shape and mocks the external invocation.
Neither parser installation nor personal data is used in CI. Exact role
identity and several position bits remain unconfirmed by the parser.

The four independent compatibility questions are:

| Gate | Diagnostic |
| --- | --- |
| Parser contract | `captured_supported_contract` only for v1 raw metadata from FM27 fmsave 0.14.3; preserve its `known_build` flag separately. Older/missing/other parser metadata is explicitly unverified or legacy. |
| Player evidence | Exact numeric status per raw attribute, position, CA and foot; R3 separately checks actual requested-role and best-search dependencies. |
| Tactic identity | Revalidated manually confirmed v2 selection, exact role IDs/catalogue, position/side/context, unresolved weighted phases. Stored parser drafts are not active or game-observed. |
| Numerical model | Unchanged R3 registry, `fm27-role-ability-r3`, only `27.0.0` + database `3754`; exact same pair in the observed record; per-player `numerical_build_compatibility` independently reports the pair gate, while `model_unavailable_reason` reports overall availability. |

Do not trim build suffixes or infer compatibility from a parser-known build.
For example, a parser-reported `27.0.0+2486695`, `27.0.1` or `27.1.0`
remains unsupported by R3. The report emits null metrics if the build is
unsupported. R3's build registry, formula, thresholds, and model/catalogue
hashes are unchanged. New build support requires independently checked
numeric evidence and a deliberately versioned model update; parser support
alone is insufficient. R3 checked reference vectors, not the installed game.

## Raw player capture and history

The existing full-world CSV stays private and temporary, exactly as before.
`choose_rows` still selects only the managed squad and matched active F9
targets. `important` now preserves the CSV `raw_attributes_*`, `raw_left_foot`
and `raw_right_foot` verbatim in the selected `record_json`. Existing
`ability_current`, `positions_*`, display attributes, identity fields and
cohorts are unchanged. No extra world records are persisted. Nothing derives
raw attributes from the displayed 1–20 scale.

When available, the `role_evidence` subobject contains version 1, exact
`game_build`, `database_version` (from `db_version`), `parser_version`,
`parser_known_build` and `game`. These are stable parser metadata, not a
new SQLite table. The existing canonical per-player JSON hash includes the
raw values and parser metadata. A raw-only change, even when the displayed
attribute is unchanged, appends a new immutable observation; a repeated
identical observation remains idempotent. Source-save hash, date, selection
hash and snapshot ID are obtained from the existing snapshot join. They are
not duplicated into the hashed record content: unchanged autosaves still
advance membership/chronology without creating unnecessary player versions.
Historical records are not rewritten or backfilled. The report records both
the last changed record's date/source and current cohort last-seen date.

The report converts CSV decimal integer syntax to exact integers; malformed
strings, bool, fractional values and values outside supported domain are not
rounded or coerced. For all 52 raw attributes, the pinned fmsave fields map
directly to the reference snake-case names except `penalty_taking` →
`penalties`, `free_kick_taking` → `free_kicks`, `punching` →
`tendency_to_punch` (these three are not used by R3). The 39 used attributes
match the reference names, including `one_on_ones`, `command_of_area` and
`rushing_out`. Separate raw foot values are retained but not role modifiers.
The engine receives exact 1–100 attributes, 1–20 positions, 1–200 CA, and
separate category bounds. Blank or absent cells are `missing`; noninteger
values are `invalid_type`; out-of-domain integers (including 0 or edited
values >100) are `unsupported_value`; inferred position categories remain
`category_only`. Legacy rows and unverified parser versions are unavailable
for numeric scoring, not retroactively reconstructed. R3 still diagnoses
the narrower conditional dependencies for each role independently.

## Read-only stored tactic inventory

From a repository checkout, after the existing watcher has accepted a save:

```powershell
py rangers_role_assessment.py extract-tactics --db C:\FMAnalytics\fm_rangers_scoped.sqlite3 --career rangers --save "C:\path\to\accepted-save.fm" --catalogue formations/fm27-role-catalogue.toml --output-dir "C:\FMAnalytics"
```

The command takes a consistent SQLite read-only snapshot; requires the existing
career-club/manager binding and current chronology, and validates active
player record hashes and identities. The save is copied into a private temp
directory and the copy hash must be an accepted snapshot at the current
career date. It invokes only `info`, strict managed-club, club and tactics
exports on that copy. It verifies the managed ID and manager against the
binding, obtains the one non-affiliate slot-0 team from the club record,
and corroborates the team ID with scoped same-save squad registration records
(`club_uid`, `team_id`, `team_slot=0`). Wrong team/club/manager IDs fail
closed. Non-first-team tactic copies are excluded; conflicting first-team
IDs are rejected. No world player export or persistence is needed here.

Because the existing schema deliberately does not add snapshot rows for an
unchanged accepted save, a newer unchanged autosave may have no accepted source
hash or same-source registration evidence. In that case extraction refuses
to claim the identity. This is an intentional conservative limitation: use a
save with an evidenced accepted snapshot at the current career date or
configure the tactic manually. Do not rebuild the DB or create fake snapshots.
No guarantee of automatic tactic selection is made even for an evidenced copy.

`stored_tactics.json` contains the explicit career, club, team, source hash,
game date/build/database and parser provenance, the stored name/index,
raw slot evidence and optional normalized R2 **draft**. Stored index is a
save-local list position, not an active tactic or durable cross-date identity.
All exact roles remain null (`ambiguous` for present raw role bits, `unknown`
otherwise); parser tokens and unconfirmed instruction units are retained
only as raw evidence. `active_tactic_id` is always null. Tactics are sorted by
stored index, not inferred preference. The parser's 12 named position bits
are accepted only as singleton with corroborating label and mask. Unknown
bits 1, 5, 6, other bits, multiple positions, conflicting side flags or labels
are unresolved; no unsupported wingback/sweeper decoding is invented. IP
selection geometry must be known to normalize a v2 draft; unknown OOP
geometry may be retained in the draft. Eleven stored rows with numbers 0–10
and a complete defending permutation are required. R2 pairs the IP slot with
the indicated stored OOP payload (not the inverse permutation); invalid
permutations remain unavailable with explicit reason. Geometry/side mapping
is reference-supported, not independently screen-validated here.

If identity/parser validation fails, the command exits with an explicit error
and does not replace a previously published inventory. A valid but unresolved
tactic is retained as an unavailable/draft item; zero stored first-team tactics
is an explicit unavailable inventory. Output is local/private and separate
from production reports.

## Manual confirmation and separate role report

Copy `formations/r4-manual-example.toml` and
`formations/r4-role-tactics.example.toml` to a private directory (the example
is invented and uses actual reference catalogue IDs, not a real Rangers tactic).
Edit the formation using verified geometry from the draft, or the formation
visible in the game. Preserve each stable IP slot ID with its paired OOP
responsibility rather than assigning separate players to each phase. Choose
selection positions explicitly, confirm exact phase role IDs in the reference
catalogue, record the manual source/reference, and register the file under its
matching ID. If geometry/role identity is uncertain, use `unknown` or
`ambiguous` with reason and no ID. Never infer a role from the position or
raw token. Manual assignments stay `user_defined`, not `game_observed`.
The R2 manual source constraint does not allow adding fabricated save-import
provenance; the separately retained inventory provides the source evidence.

Select a named tactic explicitly and publish only the new report:

```powershell
py rangers_role_assessment.py assess --db C:\FMAnalytics\fm_rangers_scoped.sqlite3 --career rangers --registry "C:\FMAnalytics\role-tactics.toml" --catalogue formations/fm27-role-catalogue.toml --select my-tactic --model fm27-role-ability-r3 --output-dir "C:\FMAnalytics"
```

Optionally add `--selected-tactic path/to/selected_tactic.json` if the R2
selector already published the envelope. This is **not** a standalone trusted
configuration source: the command always reloads the explicitly requested
registry entry and catalogue and validates the original TOML. It compares the
entire canonical envelope (including source file hash, IDs, status and
catalogue hash) with the supplied JSON. A forged self-consistent hash is not
enough; mismatch refuses before writing. The report boundary additionally
reconstructs and revalidates the normalized contract and rejects unsupported
source kinds, role placements, geometry, context and identity mismatches.
Only the pinned R3 reference catalogue is accepted; synthetic and altered
catalogues cannot be passed off as the model. The manual selection applies to
the explicitly supplied career; it is not an assertion of a save-derived
active tactic. The report reader rejects unbound careers, hash/identity
conflicts, observation/chronology mismatches and incomplete scope joins.

### Output contract

`role_assessments.json` v1 is non-operational. Root fields: career, club ID,
latest game date, selected tactic ID, normalized tactic/source, tactic hash,
catalogue identity/hash, R3 model identity/hash and evidence status,
configuration status, parser/numeric compatibility counts, `operational_scoring`
false, scoped players and `status` (`complete` when every combined slot in a
nonempty report is available, `partial` when some are available, otherwise
`unavailable`). These are assessment coverage labels, not selection eligibility.

Each player has the established stable career-scoped ID, player key/name,
cohorts, club-level loan availability, record and last-seen date, snapshot and
record/source/selection hashes, exact observed build/database/parser metadata,
parser gate and raw field coverage including feet. Each of 11 ordered slots
contains the R3 IP and OOP outputs: native positions/sides, exact role ID
and status, rating, CA-scaled ability, best rating/ties, effective position
evidence, missing/invalid reasons, model hash and evidence level. Row-level
`model_unavailable_reason` distinguishes unsupported builds and parser/input
schema failures. Unknown positive-weight phase => null combined result; zero
weight does not block the result. Phase weights are the selected tactic's,
not empirically calibrated. No score is extrapolated from missing data.
The report measures role fit, not selection eligibility, match readiness,
registration, affordability or predicted outcomes. Cohort/availability and
future optimiser policy remain separate; no starting XI is selected.

The command uses existing output directories, deterministic sorted keys and
stable order, writes to a temporary file in the output directory, closes it
and atomically replaces only the dedicated R4 filename. Invalid input or
write failure preserves the previous output. No other report/launcher file
is changed. Private data remains local; do not commit either generated JSON.

## Verification and R5 readiness

Run from checkout:

```text
python -m unittest discover -s tests -p test_rangers_role_assessment.py -v
python -m unittest discover -s tests -v
```

The new tests exercise invented fmsave CSV and nested tactics JSON, actual
watcher scoped writes, immutable history/idempotence, raw-only hash changes,
missing/invalid data, read-only identity validation, non-involutory defending
permutation, manual source/selection revalidation (including forged matching
hashes), unsupported builds/parser versions, weighted unresolved phases,
atomic publication and unchanged existing tactical assessment/optimal XI after
a raw-only change. Existing frozen output regression tests remain unchanged.

| R5 readiness requirement | R4 status |
| --- | --- |
| Scoped precise player inputs and provenance | Implemented for newly accepted snapshots with supported parser contract; historical coverage may be missing. |
| Explicit selected tactic, exact phase IDs and stable slot joins | Implemented for manual v2 selection; reference-supported extraction of unresolved geometry only. |
| Pure role scores and report | Implemented through R3, reference-matched only; no production objective changes. |
| Actual game numerical validation | Not established; independent numeric FM27 evidence needed, not just stars/order or reference agreement. |
| Current game build support | Blocked unless exact R3 pair; separately validate patch/build and version the model. |
| Operational selection semantics | Requires explicit R5 approval, shared score matrix, exact same policy and objective for XI/depth/signings, GK vs outfield treatment and eligibility preserved. Compare legacy and role-model numerical results before any switch. |
| UI/launch | No change; separate local CLI only. |

R5 should not consume this report as a production decision until compatible
build evidence, usable raw coverage and selected roles are confirmed and the
objective/policy change is explicitly approved. No benchmark or simulation
mathematics or UI work in R4.
