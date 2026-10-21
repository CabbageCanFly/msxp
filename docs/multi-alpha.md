# Local multi-stream alpha

Current follow-up: [continuous capture, safe rotation, fast offline testing and
historical browsing](continuous-alpha.md). The finite workflow below remains supported.

One coordinator runs **explicit assignments without a fixed channel-count limit**,
one capture/OCR job at a time by default, one shared SQLite database and one localhost
HTTP server. `--workers 2..8` opts
in to that many concurrent jobs, at most one per channel, with the same single SQLite
writer ([capture performance](capture-performance.md)). Counts above 4 are opt-in
experiments, not yet performance-validated on the VPS. All neural and
grammar-derived evidence remains **EXPERIMENTAL / UNVERIFIED**. Trusted Store
accounting, the OBS overlay, models, grammar policy and requirement dataset are
unchanged. No schema migration or new dependency is needed.

## Start offline

From the repository root, with existing capture dependencies, Tesseract, FFmpeg
and the private RapidOCR environment/models:

```powershell
New-Item -ItemType Directory -Force private/multi-alpha | Out-Null
Copy-Item configs/multi-alpha.example.json private/multi-alpha/config.json
.\.venv\Scripts\python tools/multi_alpha.py --config private/multi-alpha/config.json --check
.\.venv\Scripts\python tools/multi_alpha.py --config private/multi-alpha/config.json
Start-Process 'http://127.0.0.1:8765/streams'
```

Copy the example only when creating a configuration; preserve your edited file.
Its two private videos use distinct **offline assignment names**, not live Twitch
channels. Video paths must exist locally. Paths resolve from the current working
directory, so run from the repository root. Each assignment has `channel`,
`character`, `source` (`file` or `twitch`), `interval`, `count`, and optional
`experimental_neural_level` / `save_crops`. File sources have `file` and optional
`start` seconds. Intervals are 5–300s and counts 1–60 per channel. Existing capture,
freshness and OCR timeout overrides remain bounded to 1–30s.

`--check` validates configuration/tools without connecting or writing a database.
A missing video is reported; bounded runtime failures are retained if you proceed.
`--exit-after-capture` closes HTTP after the workload. Otherwise capture stops at
the configured count and the viewer stays open until Ctrl+C. Starting HTTP alone
does not start capture.

Use a **new ignored database** initially. A companion `.multi-alpha.json` ownership
marker prevents accidentally adopting a single-stream DB; an OS-released lock
prevents concurrent coordinators on the same DB. Do not copy a marker onto another
database. Existing selected characters must match exactly; mismatches fail before
changing assignments. Sessions are reused, never silently reassigned.

## Operation, recovery and saved replay

The scheduler holds one due time per lane, rotates ties fairly and skips elapsed
deadlines rather than queuing captures. File seeking advances with coordinator
elapsed time. Each channel gets one UUID run with consecutive attempt indices,
source/local receipt times, requested schedule time, delay and final summary.
Repeated failures do not starve other lanes. Existing capture/worker timeouts still
apply. Slow jobs can delay other channels: exact 15-second cadence under overload
is not promised.

Log flushes and SQLite commits are separate. The terminal and private
`operator.jsonl` distinguish acquired frames, recognized candidates and committed
attempts. New timestamp/UUID directories under `private/multi-alpha/runs/` never
overwrite evidence. Completed DB runs reject new attempts. Ctrl+C closes owned
acquisition/recognition and HTTP resources. Hard crashes can leave unfinished
runs: the in-process server can report active runs; independent readers say
**unfinished / activity unknown**, not online/offline or presumed dead.

A persistence failure stops that lane and leaves its DB run unfinished. Retain
the original log and assignment; explicitly replay complete valid lines after
fixing the cause. Review incomplete trailing lines rather than inventing events.
Otherwise preserve the interrupted evidence and restart with a new run identity.
No automatic crash repair, retry storm or historical retiming is performed.

For saved evidence, prepare a separate private configuration with `telfer1` and
`niru`, explicit matching character labels and a **new** shared DB, then:

```powershell
.\.venv\Scripts\python tools/multi_alpha.py --config private/multi-alpha/replay-config.json --replay 'telfer1=private/local-alpha/runs/telfer1-20261017T073930Z-986495bd/capture.jsonl' --replay 'niru=private/shadow-neural-level/replay-02/viewer-stream-b.jsonl'
```

Exactly one log per enabled configured channel is required. Replay does not connect or
run OCR; repeated identical replay is idempotent. Source/channel and bound
character/session checks prevent reassignment. Historical data stays stale.

To view the completed validation DB independently:

```powershell
.\.venv\Scripts\python -m exp_tracker.server --db private/multi-alpha-evaluation/replay-01/shared.sqlite3 --diagnostic-dashboard --port 8765
Start-Process 'http://127.0.0.1:8765/streams'
```

## Experimental progress policy

The read-only projection derives **one** percentage per immutable attempt:
strict full pair, otherwise strict percentage-only, otherwise unique grammar
percentage proposal. Full and percentage proposals from one frame never count
twice. Original payloads/candidates stay unchanged. V2 grammar provenance remains
queryable, reproduced from durable raw events with the installed versioned policy.

A point can remain visible without qualifying for comparison. Segments require
fresh acquired frames, one HUD, explicit matching channel/character/session,
available matching **Tesseract visual levels**, no conflicting neural/arithmetic
level evidence, consecutive attempt indices and increasing receipt timestamps.
Neural/arithmetic levels never replace missing visual evidence. Channel/source,
character/session, run and level changes break continuity. So do missing indices,
failed/stale/ambiguous attempts, explicit interruption, non-increasing timestamps,
percentage decreases and gaps over **min(120s, 1.5 × configured cadence)**.
Decreases establish a new baseline, never an inferred level-up. Unknown level
points cannot establish same-level progress. Assignment does not authenticate
the on-screen character's identity.

Differences use integer basis points (one basis point = 0.01 percentage point).
Elapsed time/rates use exact fractions. Pace requires **three contiguous readings
spanning at least 30 seconds**:
`percentage points/hour = difference_basis_points × 36 / elapsed_seconds`.
Missing attempts are breaks, not interpolated activity. Zero displayed change is
not proof of zero EXP. Current pace disappears when data becomes stale, even if
capture/polling stops. Historical eligible segments are explicitly not current.

Nearest-half-up endpoint errors `[-0.5,+0.5)` basis points and truncation errors
`[0,1)` are reported separately, bounded at 0/100%. These are outer bounds for
**display quantization**, not OCR confidence or statistical intervals. They exclude
image freshness, source timing and character identity errors. Neither hypothesis
is selected.

Two or more stable comparable endpoints may show an optional estimated EXP
**range**, multiplying the change bounds by a supported community requirement /
10,000. Visual level provenance and provisional requirement status are explicit.
Disputed/missing requirements suppress conversion, not percentage progress. The
unchanged dataset supports levels 1–200 structurally; agreed provisional
requirements 1–89, disputed 90–99 and unavailable later requirements. No exact
earned totals, current EXP reconstruction or cross-level gains are inferred.

The original strict-only `tools/percentage_progress.py` remains a separate
historical policy; only exact quantization helpers are shared. Trusted gains,
statistics, pace, ETA and overlay consume none of this evidence.

## Directory and dashboard

The player-facing `/` and `/streams` now use the [real-data product UI](product-preview.md).
The original advanced directory at `/dev/streams` and `/dev/api/streams` is still
opt-in with the diagnostic dashboard. Advanced cards
show configured channels even before success, explicit character/session, latest
capture/run status and age, strict/recovered percentage/full EXP, separate level
evidence, experimental movement and `/dashboard/CHANNEL` links. No online status,
leaderboard rank or authoritative rate is invented. The dashboard adds gated
movement, segment counts, pace/bounds and optional EXP ranges beside unchanged
strict/recovered charts. Cached failures preserve and age values; previously
active worker status becomes unknown.

HTTP stays localhost-only, GET-only and SQLite read-only with existing CSP/security
headers. No private log/crop/model/path endpoints were added. Directory responses
are bounded to 25 streamers, cached compact cards and at most 120 selected-session
attempts per changed card. Unchanged polls do not reload full channel histories.
All histories/segments are explicitly bounded, not session-wide trusted totals.

## Offline evidence and limits

Private evidence lives at `private/multi-alpha-evaluation/` (`validation-report.json`,
`offline-01/`, `failure-01/`, `replay-01/`, browser screenshots). These are familiar
recording functionality checks, not independent OCR accuracy or Twitch freshness.

| Workload | Actual result |
|---|---|
| Two videos, three attempts each, 15s requested | 6/6 frames and commits; 5 unique HUDs, 5 strict pairs, 4 available visual levels |
| Restart same DB, one each | 2/2 additional attempts; original sessions/history retained; four distinct runs total |
| Healthy + missing video, two each, 5s requested | Healthy 2/2 frames; failed source 0/2; all four attempts persisted; deadlines skipped |
| Two historical logs | 42 attempts in separate sessions; duplicate replay inserted zero records |

The six-attempt video run took **43.195s**, sampled **14.969 CPU-seconds** and
**199.19 MiB peak process-tree RSS** (50ms sampling including HTTP/capture/OCR).
Mean whole attempt was **6.845s**: acquisition/close **4.205s**, localization
**1.247s**, neural bridge **0.959s**, visual level **0.424s**. Stage means divide
by all six attempts, including one without OCR. Short-lived peaks may be missed.
These workstation measurements do not validate a 1-vCPU/1-GB VPS. Two channels
use much of a 15s sequential budget; five may require slower capture.

The fresh three-reading segment spans **29.999820s**, so correctly lacks pace.
Saved Telfer1 history contains one qualifying **seven-reading / 41.947711s /
+0.17 percentage-point** segment (two strict and five recovered). Its final two
readings lack sufficient history and current values are stale. Source B's missing
visual levels prevent eligible segments; neural levels do not fill them.
All new DBs have **zero trusted observations**. All recorded frozen-input hash
checks passed (**66 unique files**, including the original live DB/crops/logs),
as did exact original replay payload comparisons. `validation-final.json` records
the deduplicated count; the earlier private report counted repeated references.

Two-card directory measurements: cold **5.291ms**, warm median **0.035ms** / p95
**0.070ms** over 50 in-process reads; **3,063-byte JSON**. These exclude HTTP/model
startup and are not a VPS capacity promise.

## Later manually authorized live trial

Create a new private config/DB with two permitted channels and explicit characters.
For each set `source:"twitch"`, remove file/start, use `authorized:true`,
`interval:15`, `count:12`, neural diagnostics and optional saved crops. Run
`--check`, then James can run the coordinator without that flag. Review both
dashboard routes, per-channel capture/HUD/OCR/commit outcomes, skipped deadlines,
freshness limits and memory. Freeze human-reviewed references before numerical
scoring. No live connection was initiated during development; authorization and
platform restrictions still apply. Clipped digits, level errors, correlated neural
errors and uncertain character/broadcast identity still block trusted ingestion.

## Validation and changed files

Final checks: **122 focused Python tests**, **1,108 full-suite passes** in 102.03s,
**zero skips/failures**; **37 Node tests** passed. Actual localhost Chrome checks
verified two directory cards and all 30 saved dashboard observations, repeated
polling, cached errors, empty/gap states and **13 desktop/mobile screenshots**.
Directory mobile and populated dashboard screenshots were visually inspected.
`--check` passed without capture/database writes; `git diff --check` passed.
No new Twitch connection, commit, push or deployment occurred.

```powershell
.\.venv\Scripts\python -m pytest tests/test_multi_alpha.py tests/test_diagnostic_progress.py tests/test_diagnostics.py tests/test_server.py -q
.\.venv\Scripts\python -m pytest -q
node --test tools/overlay.test.mjs tools/shadow.test.mjs tools/streams.test.mjs tools/leaderboard.test.mjs
# With the validation replay server running on port 8765; use new private output directories:
node tools/shadow.browser.mjs http://127.0.0.1:8765/dev/streams private/multi-alpha/browser-directory
node tools/shadow.browser.mjs http://127.0.0.1:8765/dashboard/telfer1 private/multi-alpha/browser-dashboard
```

Exact public changed-file scope:

- Coordinator/capture: `tools/multi_alpha.py`, `tools/shadow_capture.py`,
  `configs/multi-alpha.example.json`. The old standalone shadow/local-alpha CLIs
  retain their behavior; the single-attempt operation and configuration header are
  reused rather than launching complete CLIs per frame.
- Read-only diagnostics: `src/exp_tracker/diagnostic_progress.py`,
  `src/exp_tracker/diagnostics.py`, `src/exp_tracker/shadow_view.py`,
  `src/exp_tracker/server.py`, `tools/percentage_progress.py`.
- Web assets: `src/exp_tracker/web/streams.html`, `streams.js`, `shadow.html`,
  `shadow.js`, `shadow.css`.
- Tests/harness: `tests/test_multi_alpha.py`, `test_diagnostic_progress.py`,
  `test_diagnostics.py`, `test_server.py`; `tools/streams.test.mjs`,
  `shadow.test.mjs`, `shadow.browser.mjs`.
- Documentation: `README.md`, `docs/design.md`, `docs/local-alpha.md`,
  `docs/extended-diagnostics.md`, `docs/grammar-progress-diagnostics.md`, this guide.

No Store/schema, production recognizer/guard, accounting/statistics, EXP table,
grammar rules/model weights, OBS overlay or leaderboard files were changed.

Roster changes: see [streamer-roster.md](streamer-roster.md) for atomic CLI edits, disabled assignments and controlled restart.
