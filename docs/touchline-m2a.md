# Touchline M2a — identity and historical evidence

## Source review and limits

M1a captures active cohort membership, latest record bytes, snapshots,
career chronology, managed-club identity and the benchmark cache in one
read-only SQLite transaction; M1b/M1c serve validated immutable reports.
The M1a source digest binds those inputs; PR #27 allows explicitly
unverified historical selection fingerprints, never replacement hashes.
The watcher compares the raw `important()` record hash with `player_latest`
and appends `player_versions` only for changes. `snapshots.changed_count`
counts persisted versions, not all observed players. Membership updates
and chronology advance even when no versions change. Snapshot IDs are
revision order, not game-time intervals. `cohort_membership` retains only
active/inactive state and last seen per cohort; it is not a membership log.
`career_benchmark` is a current reference aggregate, not a benchmark history.
The canonical player ID is the existing opaque JSON string containing
namespace, career and stable player key. Names are recorded values only.

These findings follow from the watcher `SCHEMA`, `important`, `identity`
and `import_selection`, bridge `get_database`, tactical and benchmark
builders, M1 generation/server contracts and snapshot replay/identity tests.
We cannot reconstruct complete daily observations, individual membership
events, transfers, injury events, availability changes or intervening
attribute movement. Even an identical record hash does not prove a new
observation was captured. The invented regression starts with 45 squad
versions, then 80 newly selected targets on the same in-game date and
unchanged squad record pointers to snapshot 1, which has a malformed
historical selection fingerprint. Snapshot 2 has missing selection evidence.

## Package compatibility and integrity

New publications capture all career-scoped versions, latest pointers,
active/inactive membership, snapshot counts and import timestamps inside
the existing transaction. No watcher or schema changes. A single canonical
`player_history.json` v1 artifact is staged with the existing six reports.
Its byte length, exact SHA-256 and schema version are stored in a new
top-level `history` descriptor in the existing v1 manifest, **not** in its
six-report `files` map. The artifact identifies the exact generation,
career and existing source digest. The manifest hash in the pointer binds
the descriptor. No report bytes, report schemas, source/cohort hashes,
configuration checks or existing cache identities are redefined.

Old v1 readers ignore the additive descriptor and continue to verify the
same six report files. New readers never retrofit a historical dataset to
an old generation: absence of the descriptor means history unavailable.
Legacy schemas without necessary snapshot columns omit the artifact.
Relationship errors (including inconsistent counts, career, identity,
record hashes, latest pointers or active membership versus M1) reject
publication before pointer replacement. The reader verifies exact artifact
bytes and the same relationships before exposing history. Missing/corrupt
declared history fails the new endpoints with `history_invalid` (422), not
a stale cache or mutable database fallback. M1 endpoints remain available
because the independently verified six reports are still intact; the M1
loader deliberately does not promise historical validation. Python consumers
must call `read_history(directory, manifest)` with a validated manifest.

## Data contracts and API v1

All new routes are GET-only, generation-pinned, exact parameter sets:

| Route | Parameters | Response data |
| --- | --- | --- |
| `/api/profile` | `generation`, `player` | last captured observation, last-seen membership and existing tactical assessment |
| `/api/history` | `generation`, `player`, `offset`, `limit` | page of actual versions, total, next offset, status/reason |
| `/api/benchmark` | `generation`, `player` | existing benchmark reference and player comparisons |

Every response has the existing generation/provenance envelope and a data
object with `version`, `career`, `player_id`. New-route provenance includes
the exact `history_artifact` descriptor (null for old generations). The history page is ordered
by increasing snapshot ID; offset is zero-based and limit 1–50. Equal
game dates retain distinct snapshot IDs, and import UTC is host import time,
not simulated time. A one-version player has one point. No player IDs are
used as filesystem paths. The per-response serialized maximum is 512 KiB;
oversize evidence fails explicitly. No all-player history endpoint exists.

Observation fields: player/career, snapshot ID, in-game date, import UTC,
game build, record SHA-256 (of original UTF-8 `record_json`), snapshot
source SHA-256 and selection fingerprint status using PR #27 semantics.
`record` is the decoded captured watcher record, with original raw parser
values (including attribute and position keys), not a new scoring model.
Missing keys have `not_recorded` semantics; `field_states` explicitly marks
core identity, club, contract and position fields. Unsupported evidence is
listed separately. Do not replace missing values with zero, reinterpret
raw parser values as normalized attributes, or manufacture historical
role suitability. The selection/source hashes are historical evidence,
not independently verified access to the original files.

Profile `current_observation` means latest **stored** version, not an
assertion the player was observed at accepted chronology. `membership` is
the captured current membership state, including inactive entries, not
historical affiliation. Active profiles include the unchanged tactical
report assessment, including position familiarity, availability and loan
direction; inactive players have null assessment. Benchmark comparisons
are the existing generation's comparisons for that player only; no
historical benchmark scoring or comparisons for inactive players. Old M1
generations return assessment where available, null raw observation and
membership, and `generation_has_no_history_artifact`; no invented data.
Unknown or cross-career player IDs return 404. Existing Host/Origin,
loopback and no-write rules remain in force.

## M2b readiness

Use the overview's canonical player IDs, pin the generation at navigation,
and fetch profile, history pages and benchmark comparisons on demand.
Distinguish last observation, last seen, accepted chronology and generation
time. Plot only recorded points with equal-date revisions distinguished;
do not interpolate, infer transfers or recompute existing scores. Treat
null, unavailable, inactive and unsupported as distinct states. A pinned
generation may remain valid for M1 analysis even if its declared history
is unavailable or corrupt. Do not silently switch generations.

The server rechecks the artifact on each new route (no unbounded history
cache); the browser receives only a per-player response. The history
artifact is decoded in memory, so large career histories can increase
server latency and memory. This is not a claim of constant-time historical
access or a real-save performance guarantee. No frontend workspace or
new analytical feature is implemented in M2a.

## Verification and performance

Run `python -m unittest discover -s tests -v` and
`python tests/touchline_benchmark.py --size large`. The new regression
fixture covers the 45/80 same-date split, namesakes/rename, both loan
directions, missing fields, overlap/inactivity, career isolation, missing
and malformed fingerprints, bad relationships, legacy absence, artifact
loss/corruption and pinned requests. It compares all six report bytes
against publication without the history artifact. The HTTP tests cover
exact parameters, read-only methods and origin checks.

Local Linux benchmark (60 squad, 500 targets, one overlap, 559 stored
versions), median of three in-process calls including serialization:

| Route | Median | Serialized bytes |
| --- | ---: | ---: |
| Profile | 1,560 ms | 23,704 |
| History (one observation) | 1,625 ms | 4,156 |
| Benchmark | 2,070 ms | 13,291 |

History artifact: 986,756 bytes. The large M1 generation exceeded the
existing 32 MiB cache admission budget; the baseline full validation alone
took 1,416 ms. These measurements include full M1 validation and history
verification, and predate the final additive history-artifact provenance
descriptor in the response envelope (which adds a small fixed byte cost).
They are not network/browser or real-save timings. Smaller pages do not
require transmission of the whole corpus. Future optimization should
preserve exact-byte integrity and pinning rather than relaxing them.
