# Gaming companion statistics and EXP history

The public player page follows the supplied private chart references: compact
EXP/hour, recent EXP and next-level cards above orange/gold bars. It retains the
existing MapleStory-inspired palette, progress bar, OBS layout and Advanced views.
Session average and EXP today are intentionally absent: their coverage is not established.

## Familiar units

Selected 5/10/15/30-minute observed summaries now include `estimated_exp`: an exact
rational conversion of the same-level percentage endpoint difference using the
supported community requirement. Separate half-up/truncation outer quantization
bounds and requirement provenance remain in the API. Public copy shows, for
example, `+17K EXP`, with the percentage, source and missing-interval explanation
in the tooltip. This is approximate **net endpoint change**, not exact earned EXP
or a session total. Missing/disputed requirements fall back to `+0.14%`.

Current absolute EXP remains separate. Public numerical EXP uses consistent K/M/B
formatting (up to three significant digits); original integers remain in tooltips
and raw API evidence. Recovered/percentage-derived absolute values retain `≈`.
Complete-window rankings and their eligibility are unchanged; progress sorting
still compares displayed percentage change, explicitly labeled as level progress.

## Recent pace

The [HUD resilience follow-up](hud-resilience-and-twitch-status.md) introduces
`responsive_pace_v3`: a bounded longer unreadable context for presentation-only
pooling and a separate no-new-gain aging display. The v2 results below remain the
historical record; strict windows, chart gains and trusted accounting are unchanged.

`responsive_pace_v2` remains a read-only consumer projection:

- Two eligible readings with at least five captured seconds can seed a first rate.
- Grow the sample to at most **five recent minutes**, using only whole, existing
  comparable intervals. Never split a rate interval at the rolling boundary.
- Within the existing bounded observed context, sum gains and elapsed time from
  the connected pieces only. **Missing intervals contribute neither gain nor time.**
  This is sampled pace, not a measurement of activity inside missing coverage.
- Prefer strict consistent numerical EXP differences when every contributing
  endpoint supports them; otherwise use percentage differences and the supported
  requirement. Percentage/hour remains available without an EXP requirement.
- Weight by captured duration, not by the number of frames. Combine quantization
  bins at each connected piece's endpoints, retaining both display hypotheses.
- During a short hole retain the dated previous rate. The first resumed reading
  does not invent a comparison; the next eligible interval can update the pooled
  rate promptly. A stale/paused rate retains its age and loses ETA.
- Existing hard boundaries remain: loss, quarantine/anomaly, ambiguous or suspect
  capture, unsupported/conflicting level, source/character/session/restart changes,
  or more than two unavailable attempts / 60 seconds between endpoints. Scheduled
  rotation can preserve continuity only through the existing validated link.
- Strict fixed-window comparisons, diagnostic pace and rankings do not consume
  this pooled rate. No trusted accounting is written. A visible strict integer
  decrease is excluded from bar gains and starts a new pace sample, even if display
  precision leaves the percentage unchanged; no loss cause is inferred.

`span_seconds` describes the full sample extent; `coverage_seconds` is the actual
denominator. Piece count, evidence counts, basis, timestamps, age and policy version
remain queryable. Short rates are still noisy; the longer sample is not a claim of
prediction accuracy. Next-level estimates require the existing positive bounds,
three readings/30 captured seconds and fresh evidence; they remain conditional.

## Bars and time coverage

`history[].gain` adds a value and exact original endpoints only for existing
contiguous, nonnegative, same-level comparisons with safe crops and a supported
requirement. It retains direct-EXP versus percentage-derived provenance. No gain
interval is emitted across missing observations, quarantines, losses, level-ups,
session boundaries or unvalidated run transitions.

The client offers fixed-duration UTC views:

| Time per bar | Axis span |
|---|---|
| 1 minute (default) | Last 30 minutes |
| 5 minutes | Last 2 hours |
| 30 minutes | Last 24 hours (server-aggregated; see follow-up) |

Axes end at the boundary enclosing the latest real attempt, not at a stretched
first-to-last reading. Stale captures remain saved history. For visualization
only, a captured interval that straddles a bucket boundary is distributed uniformly
by overlap duration. The source cannot establish the actual instant of its gains;
this allocation is never used by pace, rankings, observed-window sums or accounting.
Amounts are conserved within the displayed range. Original exact interval arithmetic
remains in the API; browser plotting uses ordinary floating-point coordinates.

Solid orange means covered intervals; faded bars mean partial coverage. A short
muted baseline dash means **unknown**, not zero. An orange zero tick requires an
actual comparable zero-change interval; displayed zero does not prove zero actual
EXP beneath percentage precision. Focusable bars have time/value/coverage labels.
The **Level %** button preserves the existing guarded line chart and window controls.

The recent-observation API loads at most **640 attempts** from one selected session. It
does not guarantee coverage of those entire chart axes (at 13s cadence, about 2h18m;
at the 3s offline floor, about 32m). Absent older portions stay unknown.

The [rolling-history follow-up](rolling-exp-history.md) now supplies a separate
bounded, causal server aggregation for the 24h view and EXP tracked summary.
That view follows current UTC instead of the latest attempt. It preserves unknown
periods and never establishes exact all-day earnings, daily totals or session averages.

## Actual saved evidence and validation

Replayed all 172 Streamer_A / 171 CharB attempts from
`private/multi-alpha/runs/20261018T005419Z-6d0af805/` without new inference/capture.
All six input hashes match the prior audit. Strict five-minute availability remains
35 / 21 checkpoints; strict ten/fifteen/thirty remain unavailable. These are
availability counts on familiar data, not independent OCR accuracy measurements.

| Streamer_A UTC | Five-minute recent EXP | Previous short pace | New sampled pace |
|---|---|---:|---:|
| 01:03:14 | +1.02 pp → ~16,998 EXP (`+17K`) | ~220K/h | ~209K/h; 273 captured seconds in 299s, 23 readings |
| 01:04:58 | +1.04 pp → ~17,332 EXP | ~216K/h | ~211K/h; short gaps excluded |
| 01:07:21 | +1.04 pp → ~17,332 EXP | ~200K/h | ~207K/h; 273 captured seconds in 299s |
| 01:09:18 | +0.34 pp → ~5,666 EXP | ~224K/h | ~224K/h; 91s since the level-reader conflict |

The level-56/66 contradiction still resets context; neither smoothing nor bars
join it. Existing loss/quarantine browser checks passed, including retained values,
confirmation and recovery. A separate saved level-up replay verifies new-level
display and first estimates without cross-level gain intervals.

```powershell
# Serve existing actual data. Starting HTTP does not initiate Twitch capture.
.\.venv\Scripts\python -m exp_tracker.server --db private/multi-alpha/live-local.sqlite3 --diagnostic-dashboard --port 8766
Start-Process 'http://127.0.0.1:8766/stream/streamer_a'
Start-Process 'http://127.0.0.1:8766/live/overlay/streamer_a'

# Choose new private output directories. Actual SQLite + HTTP polling, no API mocks.
node tools/product.browser.mjs http://127.0.0.1:8781 private/gaming-companion/review-new --verify-windows streamer_a
node tools/product.browser.mjs http://127.0.0.1:8782 private/gaming-companion/loss-new --verify-quarantine streamer_a
node tools/product.browser.mjs http://127.0.0.1:8783 private/gaming-companion/level-up-new --verify-level-up streamer_a
.\.venv\Scripts\python -m pytest -q -rs
node --test tools/*.test.mjs
```

Private detailed results: `private/gaming-companion/replay/audit.json` (reproduced
with `python private/observed-windows/audit.py private/gaming-companion/replay-new`).
Median product projection cost over measured checkpoints was ~11.8ms under concurrent
test load; this is workstation presentation cost, not capture throughput or VPS capacity.
No query expansion, dependency, OCR model or database migration was required.

Validation: **1,284 Python tests passed, zero skipped**; **63 Node tests passed**.
The final focused Python run passed 59 tests. SQLite-backed Chrome checks passed
for all statistics windows, all three bucket controls, secondary chart switching,
polling without navigation, stale/paused states, desktop/mobile layout and the
transparent 500×160 overlay. The saved level-up and existing loss/quarantine
workflows also passed. No console errors, external browser requests or horizontal
overflow were observed. `git diff --check` passed.

Private screenshots: `private/gaming-companion/browser-reviewed/exp-bars-desktop.png`,
`exp-bars-mobile.png`, `observed-homepage.png`, `secondary-level-chart.png`, and
`observed-overlay.png`. Additional level-up evidence is under
`private/gaming-companion/level-up/`; loss controls under `quarantine-01/`.
The browser test's clock is explicitly as-of the saved captures, not a claim of
current livestream freshness. No fresh livestream or actual OBS session was tested.

Changed files: `src/exp_tracker/product.py`; `web/product.js`, `product.css`,
`player.html`, `tracker.html`, `live-overlay.html`; `tests/test_companion_statistics.py`,
`test_responsive_product.py`; `tools/product.test.mjs`, `product.browser.mjs`;
`docs/product-experience-principles.md`, this guide, and `README.md`.
