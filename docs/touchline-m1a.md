# Touchline M1a — generation contract v1

The operational Python engine remains authoritative. This is a standalone
optional export, not a new renderer, watcher, scoring engine or website.

## Publish

From the selected checkout, with Python 3.11 or later:

```
python integrations/rangers/rangers_fm_scoring_bridge.py --fm-scoring-root . --db <scoped-database> --career <career-key> --publish-generation <separate-directory>
```

The optional `--formation`, `--xi-policy` and `--signing-depth-limit` flags
have their existing meanings. Do not combine with `--watch` or `--open`.
Use a dedicated local directory outside the operational saves and out trees.
Without this flag the legacy bridge operates as before. Publication reads
SQLite in a read-only transaction and captures records, active membership,
accepted chronology, club identity, snapshot evidence and benchmark cache
from that same transaction. Model bytes, normalized formation and effective
policy are consumed once by the existing builders. No existing sidecars are
read, and no native reports or observations are written.

## On-disk layout

- `current.json`: v1 pointer containing generation ID and manifest SHA-256.
- `generations/<generation-id>/manifest.json`: v1 manifest containing the
  career, report game date, UTC generation time, source and cohort fingerprints,
  configuration, benchmark provenance, and exact file byte lengths, hashes
  and report schema versions.
- Six existing v1 JSON reports: formation, tactical assessments, league
  benchmarks, optimal XI, squad depth, signing simulations.

Each generation has an opaque random ID even if its inputs are identical.
The source fingerprint is canonical JSON SHA-256 over active membership,
record hashes, observation snapshot IDs and dates, available snapshot evidence
and benchmark cache hash; the separate cohort fingerprint hashes sorted
career-scoped player ID/cohort pairs. F9 changes on the same game day are
therefore distinguishable. The existing snapshot table records save and
selection hashes at changed-record events only, not at every membership
refresh. Those historical hashes are evidence, not a claim that the latest
F9 export or save exists or matches the newest snapshot. Source export names
are basenames only. Older schemas lacking snapshot hash fields or accepted
chronology explicitly expose missing evidence. The accepted watermark,
record observation date, membership last-seen date, benchmark extraction
date and host generation time are distinct.

The manifest uses a normalized formation hash and the original scoring TOML
byte hash. Effective eligibility policy and signing depth limit are
recorded. Legacy JSON serialization is preserved, including platform newline
convention. Benchmarks can have an earlier valid extraction date; available
references outside the existing 30-game-day compatibility window are rejected.
Unavailable benchmarks retain their reasons, null comparisons and warnings.

## Failure handling and rollback

The publisher validates reports in memory, writes a private stage on the
destination volume, checks report bytes and cross-report contracts again,
then renames the complete directory into the immutable generation store.
The pointer is written to a closed temporary file and atomically replaced;
transient permission errors (e.g. Windows file handles) are retried. Failures
before pointer replacement preserve the old pointer. A failure after directory
promotion can leave a complete orphan generation; it is not current. Readers
must resolve the pointer once and pin its generation ID for their entire
request. No in-place edits, automatic repair, automatic pruning or concurrent
writer ordering guarantees. Use one publisher per output directory.

To validate or roll back, from the repository:

```python
from touchline_generation import read_current, read_generation, rollback
manifest, indexes = read_current("touchline-output")
rollback("touchline-output", "<validated-generation-id>")
```

Rollback verifies the target before atomically replacing the pointer. A
corrupt current generation fails closed; explicitly roll back to a known
valid generation. Older generations remain on disk indefinitely; manual
cleanup must exclude current and any generations pinned by readers.
Never edit a published generation. This is local filesystem integrity,
not authentication against a hostile filesystem or power-loss durability.

## M1b readiness — available data contracts

The minimal Python adapter is `read_current(root)` or
`read_generation(directory)`, returning (manifest, indexes). Verification
is performed before exposing any records. Indexes are detached in-memory
data, deterministic by ID, with no database or scoring calls. Treat them as
read-only; mutating the returned Python dictionaries does not affect disk.
Report schema versions and provenance are in the manifest. All indexes
belong to that generation only.

| Index | Key | Value |
| --- | --- | --- |
| players | canonical player ID | observed identity, cohort, availability, dates, evidence |
| slots | stable slot ID | normalized formation slot |
| assessments | (player ID, slot ID) | existing tactical evidence |
| baseline | slot ID | canonical XI assignment, vacancy and benchmark reasons |
| depth | slot ID | observed roster coverage and deputies |
| absences | removed player ID | hypothetical starter loss result |
| signings | candidate ID | observed candidate plus explicitly hypothetical XI/depth |
| benchmarks | (player ID, profile, native position or empty string) | comparison/status/reason |
| summary | named fields | existing engine totals, solver, objective, depth/signing summaries |

Python tuple keys are internal indexes; a future transport must serialize
them as explicit fields, not invent IDs. Player IDs are opaque career-scoped
JSON strings, never names. No cross-career joins. Preserve nulls, objective
domain separation, unsupported role evidence, and unevaluated signing depth.
M1b may consume these existing values without recalculating analytics.
Historical profiles, staff, scenario execution, transport, frontend routing,
visualizations and packaging are not provided by M1a.
