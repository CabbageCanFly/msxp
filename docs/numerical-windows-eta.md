# Numerical validation, saved recent windows and next-level estimates

This is a read-time product update. Original captures, OCR strings, parser
candidates, requirements, SQLite schema and trusted accounting are unchanged.
No Twitch connection or active-coordinator restart was performed.

## Wrong Streamer_A pair

The causal replay confirms that rotated-run attempt 21 at
2026-10-18 19:25:17.685004 UTC reached the public display incorrectly. Grammar
uniquely interpreted `680.978137.80%1` as `680,978[37.80%]`. The selected level
was already 67 from prior reader support; the current neural score was only
0.47247. Arithmetic marked the integer invalid, so the product withheld it but
retained 37.80%, even constructing a percentage-derived EXP estimate. Percentage
review accepted that value as its baseline. The endpoint pace collector already
excluded the incompatible pair, but the following correct 37.69% looked like a
decrease to percentage review. Public chart and baseline behavior consequently
disagreed with pace behavior. The old conservative 24h aggregator could also use
the percentage after withholding the integer.

`experimental_level_v3` adds a whole-pair veto using a recent corroborated level
anchor: at least two supported reader observations, the existing 120-second
expiry, compatible assignment/source/run context and no competing affirmative
new-level evidence. Both existing exact display hypotheses must contradict the
pair. `exp_validity.whole_pair_rejected` retains the supporting event/time/level;
`percentage_point()` returns `arithmetic_pair_veto` before percentage review.
Thus neither field supplies a public value, estimate, chart point, percentage
baseline, recent interval or historical tracked gain. Advanced keeps the original
proposal and rejection. The veto works when the current level is weak or absent;
it cannot select a replacement level or repair either digit.

| Attempt | Before public percentage | After public percentage | Result |
|---|---|---|---|
| 20 | 37.51% | 37.51% | Accepted |
| 21 | **37.80%** | Last known **37.51%** | Whole pair excluded |
| 22 | Held incorrect 37.80% | **37.69%** | Fresh baseline |
| 23 | Held incorrect 37.80% | **37.79%** | Valid 22–23 interval resumes |
| 24 | 37.87% | 37.87% | Accepted |

Nothing subtracts from 20 to 22 across the numerical veto. Earlier independent
intervals remain useful. At 23 the five-minute endpoint replay goes from
9 readings / 218.746s / ~220,118 EXP/hour to 11 readings / 244.684s /
~222,811 EXP/hour. These are experimental estimates, not independently verified gains.

James's supplied visual correction, 660,978 / 37.60%, is evaluation evidence only.
It is not substituted into any observation. The community level-67 requirement
remains 1,757,815 with unverified build applicability. An incorrect nearby integer
such as 660,979 / 37.60% still passes arithmetic: consistency cannot verify digits.
Expired context, competing levels and missing/disputed requirements cannot create
this veto. Existing single-frame integer-withholding and separately recoverable
percentage-only evidence retain their distinct semantics.

Seven saved native EXP/level crops, 18–24, were inspected at native and nearest-
neighbor enlargement. One predeclared comparison used the installed PP-OCRv6
recognizer: ordinary RGB2 versus inverted-minimum-channel grayscale2, no search.
Both produced the **same wrong attempt-21 text**, at scores 0.94008 and 0.96036.
The alternative improved some punctuation but changed 20 to another malformed
string. No OCR preprocessing or model change was adopted. Recognition of 21 took
about 21ms and 20ms respectively; model initialization after imports was 50ms.
This familiar-sample comparison supplies no new accuracy benchmark.

## CharB level confirmation

Level evidence adjacency previously required elapsed time <=1.5 times the nominal
interval: only 30 seconds for a requested 20-second cadence. Actual 35–41-second
multi-stream captures repeatedly cleared otherwise matching level-58 evidence.
The new gate uses a **120-second maximum actual separation**, increasing ordered
timestamps, consecutive attempt indices or verified clean rotation, and the same
source/character/session. Stale, duplicate, incomplete, conflicting and suspect
frames still break confirmation. Neural confidence thresholds are unchanged;
arithmetic only corroborates reader evidence, never chooses the level.

| CharB attempts 31–42 | Before | After |
|---|---|---|
| 31, 32 | Supported 58 | Supported 58 |
| 33 | Stale; excluded | Still excluded |
| 34 | Pending | Still pending; no backfill |
| 35–38 | Pending | Supported 58 |
| 39 | Supported 58 | Supported 58 |
| 40, 41 | Pending | Supported 58 |
| 42 | Reader agreement 58 | Reader agreement 58 |

Supported progress points increase from 4/12 to 10/12. Some pending frames had
already supplied an unknown-level public number; their public level-% chart dots,
pace intervals and historical gains were unavailable. They now carry supported
levels. At 42 the recent five-minute projection has 8 readings over 249.309s,
12,315 EXP in supported intervals, ~177,828 EXP/hour and ~3h10m to next level.
Strict chart connections, 24h interval rules and completed windows still enforce
their existing cadence/gap gates; this does not relabel late sampling as contiguous.
The cadence-independent level fix also applies to Streamer_A and CharE. Regression
tests cover actual separations 20, 35, 40, 60 and 90 seconds, including reacquisition
after stale frames and known high-confidence wrong level-50/51 controls.

## One selected period for the player cards

The character page provides **5 / 10 / 15 / 30 / 60 min**. Its main EXP/hour,
recent EXP, coverage, age and ETA basis all use the selected period. They are
separate from strict completed-window comparisons and leaderboard eligibility.
The overlay retains its compact default five-minute responsive rate.

`Diagnostics.recent_snapshot()` queries saved runs by real time for the selected
character/session and reuses the sanitized decoder. Clean rotation chains replay
from their original roots so level and quarantine state cannot restart at a query
boundary. Only the recent 65 minutes are retained in memory; older rows supply
causal context only. The existing 1,024-run / 65,536-attempt / 128MiB source limits
remain; recent retained rows also have a 4,096 bound. Limits return explicit
`history_limit`, never an incomplete total. Raw historical rows are not sent as a
second oversized browser history. Directory projections invalidate on revision,
interval expiry or a ten-second refresh while current window data exists.

The existing endpoint collector provides disjoint eligible intervals. Ordinary
unreadable attempts can lie inside an endpoint-supported interval of at most
300 seconds; all actual elapsed time is included. Unsafe numerical evidence,
stale/duplicate frames, identity changes and unvalidated restarts prohibit
subtraction. Valid intervals on both sides of a restart may still contribute
independently. Only the latest supported level/context contributes to these recent
cards; a display-only carried level never chooses their calculation level.
The separate 24h total can include independently valid older levels/sessions of
the selected character under its existing more conservative interval policy.

For each window, EXP/hour = sum of eligible interval gains * 3600 / sum of their
actual durations. Consistent numerical endpoints take precedence over percentage
conversion; percentage conversion retains both quantization hypotheses. No
interval is split to manufacture a reading at the left window boundary. Recent
EXP is the sum over those intervals, not necessarily an end-to-end net gain.
Coverage and sequences disclose partial sampling. No gain or time is assigned
between unrelated intervals. Strict completed-window/ranking rules are unchanged.

A read-only SQLite backup was used for cross-restart checks. At 20:28:48.740 UTC:

| Streamer_A card | Previous latest-sequence window projection | New saved-window sum |
|---|---:|---:|
| 30 min | ~65,742 EXP | **~106,801 EXP / 1,756.264s** |
| 60 min | No selection | **~205,503 EXP / 3,342.330s** |

The earlier window projection is compared with corrected shared validation held
constant, isolating the window-policy change. Restart timestamps are preserved;
there is no subtraction over the process-start gap. At the later 20:40 checkpoint,
the sums are ~112,767 and ~212,300 EXP. CharE and CharB are included in the private
SQLite audit. A 720-attempt fast-video synthetic history proves the new query is
not truncated to the browser's 640-row chart limit. Closing/reopening the database
reproduces the same sums and leaves trusted observations empty.

As the real clock advances, old intervals expire. If a selected period has no
current intervals, any retained same-period rate is explicitly dated; its gain
card remains unavailable. It is never replaced with a different current period's
rate. The default five-minute view can retain its existing dated last-observed
fallback. No ETA continues while readings are stale, stopped, quarantined or
otherwise unsuitable.

## Stable cards and ETA

All four card containers are always rendered: EXP/hour, recent EXP, tracked 24h
and next level. Next level shows a dash/building-history state when unavailable.
Two supported readings over at least five actual seconds can produce an **Early
estimate**, with reading count. Supported positive integer endpoint rates use
remaining EXP and the selected rate, even if both percentages occupy the same
display bin; percentage-only estimates retain their existing positive lower-bound
checks under both display hypotheses. Table/OCR uncertainty remains unquantified.
These are rounded presentation estimates, not countdowns or earned EXP accounting.
Conditional X-symbol recovery still cannot generate ETA. A supported requirement
and fresh eligible same-level evidence are required.

The layout-changing last-seen-level paragraph is removed. Level age/provenance
stay in the level tooltip. Desktop uses four stable cards; mobile uses two rows.
An independent 6h/24h ETA-source selector is deferred; 60 min already supplies a
one-hour selection. No hourly source is silently mixed with a different gain card.

## Validation and local use

Run existing tests and the actual SQLite/Chrome replay without contacting Twitch:

```powershell
.\.venv\Scripts\python -m pytest
node --test tools/*.test.mjs
node tools/product.browser.mjs http://127.0.0.1:18262 private/numerical-windows/browser-NEW --verify-numerical-windows streamer_a
```

Use a new ignored output directory for each browser run. The fixture starts its
own server/database, commits unchanged saved attempts in causal order and marks
its as-of clock/runtime activity as simulated. Chrome checks five window
selections, wrong-pair rejection, recovery, polling without navigation, stale ETA
suppression, stable cards and 500x160 OBS. Screenshots inspected under
`private/numerical-windows/browser-final/` and `browser-streamer_b-02/` show the rejected
Streamer_A value held safely, recovery, supported CharB 58 and populated ETA.
One initial standalone browser connection failed because its server and client
were in different sandbox contexts; the reachable isolated replay passed.

To inspect the current database without changing or restarting capture:

```powershell
.\.venv\Scripts\python -m exp_tracker.server --db private/multi-alpha/live-local.sqlite3 --diagnostic-dashboard --port 8766
Start-Process 'http://127.0.0.1:8766/stream/streamer_a'
Start-Process 'http://127.0.0.1:8766/dashboard/streamer_a'
```

This separate server cannot claim ownership of the existing capture worker;
running/stopped status and ETA therefore retain the existing truthful activity
gates. Apply code to the coordinator-owned server on a later controlled restart.

Detailed before/after checkpoints, model outputs, source review sheet, SQLite
copy, query audit and measurements are ignored under `private/numerical-windows/`.
Graphs still load at most 640 attempts; high-cadence 60-minute card statistics can
therefore include more supported data than the raw graph. No new holdout labels,
source identity authentication or numerical-trust promotion were established.

Five uncached full player/history projections per channel on the private SQLite
copy measured median **290ms Streamer_A / 448ms CharB / 413ms CharE**, including
recent-query decoding and all five window summaries, excluding capture/OCR and
HTTP transport. Work receipts were 242/241/240 source attempts across five runs,
including older causal rotation context. Separate `tracemalloc` calls peaked at
**13.94 / 12.49 / 10.19 MiB** of Python allocations. These small local measurements
were made while the existing coordinator/test workload continued; they are not
isolated capacity or VPS benchmarks. Cold projections cost more as a clean
rotation chain grows; limits fail closed, and 25-channel query load is untested.
The actual 120-second confirmation-gap limit also remains deliberate: more
streamers cannot make arbitrarily old level evidence fresh. Measure sustainable
cadence before expanding a sequential roster.

Changed implementation files:

- `src/exp_tracker/diagnostic_evidence.py`, `diagnostic_progress.py`: level v3,
  duplicate/suspect-frame guard and shared whole-pair veto.
- `src/exp_tracker/diagnostics.py`, `rolling_history.py`, `server.py`: shared
  bounded run decoder, causal recent query, cache expiry and product API wiring.
- `src/exp_tracker/product.py`: interval pooling per selected period, separate
  dated per-period fallback, exact numerical ETA and shared aging.
- `src/exp_tracker/web/player.html`, `product.css`, `product.js`, `shadow.js`:
  five choices, stable cards, paired card updates, tooltips and rejection wording.
- `tests/test_numerical_windows.py` (new), `test_gap_level_resilience.py`,
  `test_responsive_product.py`: actual-source and synthetic regressions; old
  assertions explicitly updated for the whole-pair veto, tentative ETA and
  duplicate-frame confirmation boundary.
- `tools/product.test.mjs`, `product.browser.mjs`, `product_updates_fixture.py`:
  selection/aging tests and causal saved-input polling fixture.
- `README.md`, `docs/product-experience-principles.md`,
  `docs/exp-validity-level-policy.md`, this report.

The next useful manual check is the same three-stream roster at a sustainable
cadence with saved crops: inspect arithmetic vetoes, level reacquisition and
window changes across a controlled restart. Consistent wrong digit pairs remain
a recognition limitation requiring independent source review.

Final validation: **1,500 Python passes in 166.94s, zero skips; 76 Node passes,
zero skips**. The new focused numerical/window module has 25 cases, including
optional real-source regressions; both private inputs were present. Chrome passed
the five causal polling stages and all five selections (19 screenshots), plus
the separate CharB checkpoint (7 screenshots). Representative desktop/mobile,
stale and OBS images were inspected; no overflow, navigation reload or console
failure was found. All test servers were closed. `git diff --check` passed and
the new private outputs are ignored. JSONL and compared EXP-crop hashes remained
unchanged.

One preceding full run had 1,499 passes and an intermittent existing Windows
`test_real_neural_timeout_reaps_worker` failure: immediate PID visibility after
timeout. Its isolated rerun passed, the PID was absent on subsequent inspection,
and the complete rerun passed without changing worker code or weakening its test.
No commits, pushes or hook-owned report edits were made.
