# Touchline M1c — optional Windows deployment and measured hardening

## Offline launch (Windows, no administrator or Node runtime)

1. Check out the same merged revision as the prebuilt frontend. Download the
   `touchline-production-dist` artifact from its successful Touchline frontend
   CI run (or build once with Node 22+ using `cd touchline; npm ci; npm run build`).
   Extract the artifact so `touchline/dist/index.html` and
   `touchline/dist/assets/` exist in the checkout. The bundle is revision-matched;
   do not mix a bundle with a different server revision.
2. Have Python 3.11+ available through the Windows Python launcher or PATH.
3. Explicitly choose an existing M1a output directory and career key. From
   PowerShell, e.g.:

   ```powershell
   & "C:\Users\Your Name\fm-scoring\launch-touchline.cmd" --generations "C:\Users\Your Name\Touchline generations" --career invented-career
   ```

   The arguments are examples, not auto-discovery. The launcher validates the
   current generation, checks the bundle, binds exclusively to loopback, then
   opens the default browser. For a port conflict close the existing server or
   pass `--port 8766`. Use `--no-browser` to open the printed URL yourself.
   Keep the console open; Ctrl+C stops only Touchline. No installation into the
   Windows system directories, background service, watcher, FM save discovery,
   SQLite access or network downloads are performed by this launcher.
   The original external Rangers launcher and default workflow are untouched.

To publish a new generation, independently invoke the existing M1a command
with your intentionally selected scoped database and career:

```powershell
python integrations/rangers/rangers_fm_scoring_bridge.py --fm-scoring-root . --db "<scoped-database>" --career "<career-key>" --publish-generation "<dedicated-directory>"
```

Touchline keeps the current decision pinned; select **Switch generation**
when a new validated generation is announced. If the chosen player or slot
disappears, it clears that selection and explains why. Invalid pointers do
not silently replace the pinned view. Retry the same pinned generation or
use M1a's explicit rollback procedure; never edit published report bytes.

## Performance experiment

Run `python tests/touchline_benchmark.py --size small|medium|large` separately
for each size (use one option, not the literal pipe). The fixture generator
uses the unchanged operational Python builders, synthetic observations,
an intentionally narrow eligible-position distribution, and depth limit 2.
Small = 9 squad / 19 active targets; medium = 45 / 80; large = 60 / 500
(one squad/target overlap). No personal data.

Local Linux/Python 3.12 measurements: median of three in-process calls
including JSON serialization; no transport/browser overhead. Compared with
the same fixture and cache disabled. Milliseconds:

| Fixture | Full validation | Overview before → after | Slot | Candidates | Signing |
|---|---:|---:|---:|---:|---:|
| Small | 46.89 | 46.47 → 3.74 | 48.08 → 2.95 | 48.60 → 3.15 | 54.52 → 3.45 |
| Medium | 257.37 | 277.16 → 18.65 | 245.47 → 13.39 | 260.07 → 13.58 | 240.02 → 12.36 |
| Large | 1271.32 | 1374.57 → 1438.51 | 1415.49 → 1422.71 | 1347.75 → 1459.01 | 1756.66 → 1383.47 |

The large fixture exceeded the 32 MiB serialized admission budget and did
not benefit from caching. This is intentional; repeated full validation is
the safe fallback. Large timings vary and are not evidence of a speedup.
Generation construction (both generations) took 0.44 / 6.72 / 37.75 s.

| Fixture | Overview bytes | Slot bytes | Candidates bytes | Signing bytes | Warm switch to second generation, ms |
|---|---:|---:|---:|---:|---:|
| Small | 26,206 | 14,197 | 35,360 | 62,912 | 1.15 |
| Medium | 74,184 | 34,098 | 146,171 | 94,912 | 3.67 |
| Large | 278,384 | 41,760 | 905,706 | 99,311 | 5.26 |

The second generation has no targets. The switch number is a median of
three calls (includes cold and warm calls), not a browser-switch guarantee.
Tracemalloc peak during initial load: 8.7 / 35.0 / 175.5 MB; retained traced
allocations: 4.1 / 17.1 / 45.7 MB. These are Python traced allocations, not
process RSS. The earlier M1b small-fixture browser evidence was 188 ms
initial render / 15 ms filter. M1c browser timings and four viewport
screenshots are produced by the frontend CI artifact (see PR evidence).
No real-save or physical Windows device performance guarantee is made.

### Cache integrity

Each request reads and hashes the actual manifest and all six reports.
Cache hits require matching generation ID, manifest digest and every
report digest. A miss validates the same captured bytes, never a different
second read. A previously seen generation ID cannot change manifest identity
within one server process, even after eviction. Current pointer identity is
checked independently on each current request. Missing or corrupt files
fail closed; no cached fallback is served. One Store belongs to one career.
The LRU holds at most two fully validated index sets within a shared 32 MiB
serialized-input budget. Decoded objects are larger than their input;
the budget is not a hard RSS limit. A lightweight manifest fingerprint
ledger retains one ID/hash pair per validated generation for the process
lifetime. Oversized inputs are validated without admission. Restarting
Touchline clears the cache and ledger; no disk cache or operational writes.

## Accessibility and deployment verification

The browser tests exercise the full keyboard recruitment flow, exact XI
assignments and unavailable numbers, generation pinning/switching (including
a removed slot), browser history, reduced motion and WCAG A/AA axe checks.
Responsive 1440/1280/768/390 CSS-pixel screenshots and a 720px reflow
approximation of 200% zoom are generated. The latter is not a test of
browser chrome zoom. Candidate pagination retains canonical engine order;
classification is explicitly whole-XI impact, with selected-slot eligibility
and actual hypothetical assignment separately shown. Expanded baseline
assignments remain available on demand.

The Windows CI launcher smoke tests paths containing spaces, bundle
prerequisites, explicit career, duplicate-port handling and shutdown using
the real production frontend. Node is excluded from the child process PATH,
not uninstalled from the test machine. For a manual check on your own
Windows desktop: launch normally, confirm default browser opens only after
the ready message, navigate with Tab/Enter, try browser zoom at 200%,
read status and table labels with your preferred screen reader, then
Ctrl+C and confirm the URL is no longer served. Automated axe success
does not establish full WCAG compliance; physical desktop and screen-reader
validation remain manual acceptance checks.

## M2 readiness (not implemented)

- Profile/history: stable player IDs and shared generation context exist;
  scoped native profile DTOs, historical observation/transfer joins and
  lazy history endpoints still need design and verification.
- Squad analysis: existing tactical and recruitment reports are available;
  a dedicated squad overview/profile navigation, risk and depth comparisons
  beyond M1 and accessible charts remain M2 work.
- Historical evidence: M1 preserves chronology, provenance and missingness;
  historical player data is not currently exposed to the browser. M2 must
  retain career isolation, late observations, availability and explicit
  unavailable evidence, without inventing new scoring.
- Performance: oversized generations remain deliberately uncached; evaluate
  larger-cohort payload/index strategies using measured real-world-shaped
  synthetic cases before adding history.

Squad, Analysis and Staff workspaces remain placeholders. No M2 product
functionality, analytical changes or default-launcher transition in M1c.
