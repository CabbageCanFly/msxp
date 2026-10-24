# Window statistics and percentage ETA

The API's additive `statistics` field comes from `Store.state()` in its existing
SQLite snapshot. [statistics.py](../src/exp_tracker/statistics.py) reads persisted
validated intervals; it does not validate new OCR, write observations, recalculate
session totals or change schema 2. No dependency, game EXP table or gain-rate cap
is added.

## Definitions

| Overlay | API field | Meaning |
| --- | --- | --- |
| Last 5 min | `statistics.last_5_min.exp` | Sum of accepted net gains whose entire trusted endpoint interval is inside the last 300 seconds |
| EXP/h · 30m | `statistics.exp_per_hour_30m.exp_per_hour` | Accepted net gains in qualifying intervals in the last 1,800 seconds × 3,600 / their endpoint-spanned seconds |
| This session | `observed_session_exp` | Existing session total, with its unchanged accounting rules |
| To next level | `statistics.to_next_level.seconds` | Approximate remaining time at the same-level percentage pace of the qualifying 30-minute intervals |

Each window is anchored to **request time**, not the last successful reading.
Only the current explicitly selected character/open session is eligible. Starting
from the last trusted observation, follow its interval-start links backwards in
the same session and level. Stop at a baseline, missing legacy interval metadata
or a broken link. Older disconnected segments are not pooled to create coverage.
The query is limited to accepted interval ends in the last 30 minutes and uses
the existing character-history index; no growing in-memory history is retained.

## Coverage and missing data

For a window to be meaningful, the connected history must reach its cutoff:
**five minutes of history for Last 5 min, thirty minutes for pace and ETA**.
Then include only whole intervals starting at/after the cutoff and ending at/
before now. Require at least **80% endpoint-span coverage**: 240 seconds for the
five-minute window or 1,440 seconds for thirty minutes. This is a history-quality
rule, not an EXP gain/rate bound. It prevents a mostly unobserved window from
producing a deceptively precise result.

- A boundary-crossing interval is excluded **whole**. No gain is prorated to an
  arbitrary timestamp, even if most of the interval lies inside the window.
- A bridged interval wholly inside the window counts its stored net gain and
  elapsed endpoint span. Missing-frame counts remain visible in API metadata.
  This says nothing about when gains occurred inside that span or whether gains
  were continuously observed.
- Unobserved time after the last reading, and excluded leading time, contribute
  neither gains nor zero-activity seconds. Pace divides by the included span,
  not the full nominal window with missing time silently filled as zero.
- The five-minute count is marked `~` when either edge is trimmed. This is the
  **known included net gain**, an incomplete representation of the nominal
  window, not an estimate of excluded gains or a proven mathematical lower bound.
  Exact-boundary counts use `+`. The developer overlay marks pace/ETA with `~`; public
  pages show them unmarked and say they are estimates in the hover text.
- Insufficient history/coverage yields JSON `null` and a dash, not zero. Verified
  unchanged endpoint intervals may produce genuine zero net gain/pace.
- Offline, hard pause/reset/level ambiguity, no current-session reading, future
  reading or age over the existing 120 seconds makes window metrics unavailable.
  A later baseline starts new window history; it cannot silently borrow pre-break
  gains. Soft OCR failures preserve eligible endpoint statistics until freshness
  or coverage becomes insufficient. No rejected candidate is ever a gain source.

Windows expose `reason`, `window_seconds`, `covered_seconds`, `start_at`, `end_at`,
`missing_observations`, `boundary_trimmed`, and `percentage_gained_bp`. Here
**coverage means the span between validated endpoints**, including permitted
bridges; it does not mean uninterrupted frame recognition. Insufficient history
reports no usable span; insufficient coverage reports the span found but a null
gain. Old accepted rows without interval links stay in session totals but cannot
support window statistics.

The frontend also hides window metrics on request failure, locally expired
freshness, offline/review states or a character/session mismatch. It retains
the last level/EXP/percentage, session total and their original update age.
It does not keep an old rolling count visible as if it belonged to the new window.

## ETA without an EXP table

The HUD already provides level and percentage to two decimal places. On the
same level, if that percentage is the fraction of the level's EXP target, a
recent percentage pace supports:

```
ETA seconds = (10000 - latest_percentage_bp) * included_seconds / gained_percentage_bp
```

Use the same connected, eligible thirty-minute sample as EXP/h. Require at least
**10 basis points = 0.10 percentage points** of progression; otherwise display a
dash. A difference of two quantized percentages has roughly one basis point of
rounding uncertainty, so a one-tick change would be too noisy to project. The
minimum reduces that denominator error to about 10%; it does not promise total
forecast accuracy, especially very close to the next level.

ETA assumes recent **net** percentage progression continues. Idle time, deaths,
route changes and future changes in pace can invalidate that assumption. Display
whole minutes, rounded up; do not count down between readings or subtract
elapsed time as if unseen EXP had been earned. No target EXP total, level-up
formula or cross-level gain is inferred. Automatic level confirmation and exact
cross-level accounting remain deferred. A new session/confirmed level needs new
history; ETA may remain unavailable for fast level-ups or very slow progress.

## Reproducible synthetic history

Choose a **fresh ignored database path**; the tool refuses to overwrite any file:
stop any older HTTP server with Ctrl+C first so it loads the new statistics code.

```powershell
.\.venv\Scripts\python tools/demo_statistics.py artifacts/statistics-preview.sqlite3
.\.venv\Scripts\python -m exp_tracker.server --db artifacts/statistics-preview.sqlite3
# In another terminal; refresh an already-open old overlay once to load new assets.
Start-Process 'http://127.0.0.1:8765/overlay/demo'
```

The tool writes 35 minutes of synthetic history at 30-second spacing using the
actual guard and `Store.ingest`, including one unreadable frame and its later
4,000 EXP bridge. Its invented EXP-to-percent scale is **not game data or a game
EXP table**. Nothing uses private screenshots, calibration or OCR answers.

At the final observation's exact timestamp, expected results are:

| Value | Result |
| --- | ---: |
| Current EXP / percentage | 240,000 / 24.00% |
| Last 5 min | 20,000 over 300 seconds |
| Thirty-minute net gain / pace | 120,000 over 1,800 seconds / 240,000 EXP/h |
| This session | 140,000 |
| Percentage-based ETA | 11,400 seconds, displayed `~3h 10m` |

Just after seeding, the first 30-second interval crosses the moving cutoff, so
Last 5 min becomes **~18K over 270 seconds**; the constant synthetic pace and ETA
stay ~240K/h and ~3h 10m. This deliberate stepwise behaviour avoids interpolation.
The seed keeps its timestamps, eventually loses coverage, then becomes stale.
To reproduce exact test time use `--at 2026-01-01T01:00:00Z` and inspect
`Store.state('demo', as_of=that_aware_timestamp)`. An HTTP server at today's time
correctly shows that historical seed as stale. Never retime real observations.

Browser checks (after starting the server above):

```powershell
node tools/overlay.browser.mjs http://127.0.0.1:8765/overlay/demo
```

Sixteen actual Edge cases verify fixed dimensions, four equal columns, label/
metric fit, header identity, optional synthetic rank, SVG centring, missing metrics
and real API polling. Images/measurements are private ignored artifacts under
`artifacts/overlay-statistics/`. Backend tests cover window/coverage boundaries,
bridges, unverified fallbacks, gaps/offline/resets, large gains, zero pace, character
and level/session changes, duplicate replay, restart and read-only persistence.

Validation: targeted Python checks passed, then the full suite passed **333 tests,
zero skipped** (including all private-sample tests and localhost transport).
All **11 Node renderer checks** and **16 real Edge cases** passed. Original private
OCR profiles and real replay totals were preserved. Screenshot dimensions/alpha
were checked with Pillow; current overlay compositing in OBS and Linux execution
remain manual checks. No commits or pushes were made.

```powershell
.\.venv\Scripts\python -m pytest -q tests/test_statistics.py tests/test_server.py tests/test_store.py --basetemp=artifacts/pytest-statistics-targeted -rs
.\.venv\Scripts\python -m pytest -q --basetemp=artifacts/pytest-statistics-full -rs
```

## Future ranking

No leaderboard exists and the API emits **no ranking field**. The optional header
badge is hidden. The renderer is prepared for a future
`ranking: {rank: <positive integer>, authoritative: true}` from a trusted ranking
service; it never calculates a rank from local session statistics. The `#7` in
`synthetic-rank*.png` comes only from explicit browser-test fixtures, not SQLite,
a real streamer ranking, a URL parameter or demo API data.

A real leaderboard first needs an agreed metric (raw EXP/h, level, percentage
pace, etc.), eligible consenting streamers/characters and game worlds/rulesets,
a common time window, freshness/coverage requirements, handling for sessions and
level changes, and tie-breaking. Local partial-window estimates are not yet a
fair authoritative ranking basis. No scoring/backend work is included here.
