# Touchline M1b — optional local preview

For the optional Windows launcher, current cache policy and deployment
verification, see [M1c](touchline-m1c.md). The M1b limits below describe the
original M1b baseline.

M1b uses only validated M1a generations. It does not read saves or SQLite,
publish new generations, run scoring, or change the existing launcher.

## Build and run

From the checkout, install Node 22+ for **build/development only**:

```text
cd touchline
npm ci
npm run build
cd ..
python touchline_server.py --generations <dedicated-M1a-output> --career <career-key>
```

Open the printed `http://127.0.0.1:8765` URL, not localhost or a network
address. The server binds loopback exclusively. Once built, the static
`touchline/dist` directory and Python source suffice; no Node or internet is
needed at runtime. Stop with Ctrl+C. Do not put private generated data in git.
The existing M1a publishing command remains the separate opt-in action.
See [M1a documentation](touchline-m1a.md).

For invented data only:

```text
python tests/touchline_fixture.py <new-dedicated-temporary-directory>
python touchline_server.py --generations <that-directory> --career invented-career
```

## Workflow and contracts

Overview links to vacancies, shared cover and absence scenarios. The
tactical pitch and assignment table select the same stable slot. The
position panel links to the scoped F9 recruitment cohort; eligibility is
the engine's hypothetical eligibility, not a frontend ranking or position
match. Compare the incumbent and candidate quality and inspect the existing
signing case, with separate GK and outfield totals and explicit unevaluated
depth. Candidate selection remains in the URL fragment when switching
workspaces or using browser history.

The API accepts only GET and exact route/parameter sets:

| Route | Parameters | Purpose |
|---|---|---|
| /api/current | none | validated current pointer identity |
| /api/generation | generation | validated pinned identity |
| /api/overview | generation | compact summary, player directory, slots, coverage |
| /api/slot | generation, slot | existing slot assessment, deputies, absence |
| /api/candidates | generation, slot | existing slot-specific candidate evidence, engine order |
| /api/signing | generation, player | selected precomputed hypothetical results |

Generation-specific responses always include generation ID and compact
provenance. IDs are query values, never filenames (generation IDs alone
select a strictly constrained directory). The server rejects unmatched
career IDs, invalid/missing generations, nonallowlisted static assets,
and disallowed Host/Origin values. The browser checks response generation
identity, aborts stale view requests, and never changes generation on polling.
Switching validates the new overview first and clears missing selections.
If pinned data disappears, no fallback is substituted. Refresh checks run
every ten seconds. No persistent browser storage, remote assets,
write endpoints or wildcard CORS.

M1a's read indexes were extended additively with original report order,
bench matching capacity/dependencies, signing assumptions and limitations.
Manifest bytes, generation hashes, report schemas and publisher behavior
remain unchanged. No analytical calculations were added.

## Verification and M1c boundaries

Python tests use genuine generated reports from invented observations.
Frontend tests cover opaque route identity, switching and order-preserving
filters. The separate Touchline workflow builds TypeScript, serves the
production bundle through Python with Node absent from its PATH, runs
Chromium workflow/keyboard/axe tests, and uploads responsive screenshots
and measured browser/API timings. Existing Python CI remains unchanged.

```text
python -m unittest discover -s tests -v
python tests/touchline_runtime_smoke.py
cd touchline
npm test
npx playwright install chromium
npm run browser
```

Current design limits: one configured career/store per server, no generation
retention scheduler, complete validation on each request (no cache), scoped
current observations only, no historical profile/scouting/staff workspaces.
The small-screen pitch retains a horizontally scrollable table alternative.
Full manual accessibility coverage, Windows packaging, launcher transition
and representative real-save performance evaluation belong to M1c.
The invented-data timings are observations, not real-save performance guarantees.
