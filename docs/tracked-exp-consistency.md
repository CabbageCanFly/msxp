# Consistent tracked EXP and minute-precision ETA

Public experimental tracked EXP now uses one eligible-interval policy for every
5/10/15/30/60-minute and rolling 24-hour total. This supersedes the older
adjacent-only 24-hour policy documented in the cross-level history audit.
Strict complete-window rankings, trusted Store accounting and raw observations
are unchanged. EXP/hour and ETA remain estimates, not accumulated EXP totals.

## Reproduced Streamer_F discrepancy

The reported values reproduce exactly at **2026-10-19 01:03:54.273738 UTC**, at
attempt 10 of rotated run `a5d68cbbfe14469abf4f7380d49a161a` under
`private/multi-alpha/runs/20261019T003226Z-cbe9ba29/streamer_f/`.
The replay also includes the saved `001842Z-5817cb05` and `001945Z-65cc75a7`
cohorts. It uses an isolated SQLite database and original capture timestamps.

| Lookback | Before | After |
|---|---:|---:|
| 5 min | 4,757 | 4,757 |
| 10 min | 9,994 | 9,994 |
| 15 min | 14,696 | 14,696 |
| 30 min | 27,764 | 27,764 |
| 60 min | 41,228 | 41,228 |
| 24 hours | 34,311 | **41,228** |

All amounts here come from saved integer endpoint differences. The new result
has 94 eligible intervals, 97 contributing readings in three sequences and
2,611 seconds of eligible elapsed time. There is no need to wait a full hour:
this history is entirely inside the selected hour, so its 60-minute and 24-hour
totals agree. The original recent rate remains approximately 56,845 EXP/hour.

The old 24-hour path used `allow_context=False` for levels and required
`boundary(...) is None` for every adjacent pair. Recent pace already allowed
bounded endpoint comparisons across missing OCR and harmless scheduling gaps.
Fourteen omitted intervals explain the **6,917 EXP** difference exactly:

| UTC interval | EXP | Old exclusion |
|---|---:|---|
| 00:20:04.627482 → 00:20:36.197222 | 602 | Actual spacing above nominal adjacency limit |
| 00:21:02.521127 → 00:21:34.780666 | 498 | Same |
| 00:21:34.780666 → 00:22:07.349886 | 473 | Same |
| 00:26:42.791613 → 00:27:19.866089 | 645 | Same |
| 00:28:42.801889 → 00:29:13.790603 | 485 | Same |
| 00:29:42.382229 → 00:30:12.829391 | 438 | Same |
| 00:37:42.294417 → 00:38:13.604524 | 91 | Same |
| 00:39:30.090126 → 00:40:00.167360 | 525 | Same |
| 00:40:55.290799 → 00:41:26.260027 | 375 | Same |
| 00:43:16.704080 → 00:43:47.823603 | 444 | Same |
| 00:46:24.247130 → 00:46:55.285563 | 506 | Same |
| 00:57:35.339241 → 00:58:29.217401 | 847 | Missing numeric attempt 57; supported endpoints 56→58 |
| 00:58:29.217401 → 00:58:55.856791 | 455 | Contextual level at endpoint 58 disabled in old replay |
| 01:02:02.257708 → 01:02:34.596263 | 533 | Actual spacing above nominal adjacency limit |

The twelve cadence intervals total 5,615 EXP. Their spacing is approximately
30.08–37.07 seconds, just beyond the old 30-second limit for a nominal 20-second
schedule. Together with 847 and 455, they account for the entire discrepancy.
This is increased consistency with the existing endpoint policy, not a new
independent OCR accuracy evaluation or digit correction.

## Shared evidence and scope

`pace_intervals.collect()` now supports streaming its causal state across run
batches. Level projection and percentage quarantine retain their existing rules;
manual restarts reset their context, scheduled rotation preserves valid context,
and the collector retains duplicate detection and subtraction boundaries.
`exp_interval()` is the shared conversion used by responsive pace and historical
aggregation. Each interval retains timestamps, IDs, ownership/source identity,
level requirement, evidence types, basis and policy `tracked_endpoint_exp_v2`.

- Use consistent direct integer EXP endpoints where supported; otherwise convert
  a same-level percentage difference using that level's supported requirement.
- Ordinary unreadable captures can have independently supported endpoints up to
  the existing 300-second interval limit. Count the net difference and actual
  elapsed time, never an invented intermediate observation or hourly-rate gain.
- Do not subtract across level changes, confirmed losses, quarantine, contradictory
  numbers, stale/duplicate frames, source/identity switches or unvalidated restarts.
  Keep independent intervals on either side. Negative differences are never
  subtracted from gross tracked gains. Unknown level-up gains remain unknown.
- Reject unsupported requirements, prevent overlapping interval contributions,
  and preserve the existing numerical vetoes, including CharA's wrong whole pair.
- The common public scope is the explicitly selected **character ID**, across
  its explicitly assigned sessions and sources. Each session/source contributes
  only its own eligible intervals. No subtraction crosses those identities;
  similar names, levels or percentages never merge characters. Assignment is
  not authentication of the character displayed by every stream frame.
    Operators must assign a different character ID when the actual character changes.

For a fixed as-of time, include an entire interval only when
`window_start <= interval_start < interval_end <= as_of`. Exclude a window-start
crossing interval in full; never prorate its gain into the total. Because the
same nonnegative intervals and ownership scope are used, nested totals follow
from set inclusion. No totals are capped or inflated after calculation. No
eligible intervals means unavailable; a genuinely observed zero remains zero.

The current-level-only filter selects the latest supported level for recent
totals and bars. The 24-hour total and 24-hour chart always include all supported
levels. Percentage line charts retain their existing raw gaps and level markers.

## HTTP, charts and bounds

The existing cached history query now returns all tracked-window totals, level
filtered totals and 24-hour bars in one packet with one `as_of`. The player API
includes that packet; both cards consume it together. Existing `recent_windows`
gain/observation fields receive those totals, while their pace and ETA calculations
remain separate. The homepage uses the same cached totals. Credentials, crops,
raw logs and private source paths are not added to HTTP output.

The cache is bounded to the configured maximum of 25 channels, invalidates on
character/revision changes and refreshes after 30 seconds without revisions.
Cached totals retain their actual as-of timestamp; they do not pretend to have
been recomputed at every poll. History-limit results clear all gain totals rather
than falling back to an incomplete recent subset. Current pace/dated ETA can
remain available independently when a full-history gain query reaches its limit.
Public recent-window start/end metadata follows that common tracked as-of clock;
`pace_as_of` separately records the rate projection clock. Refreshing an existing
cache entry does not evict unrelated channels.

Short EXP charts use the same bounded interval summaries and whole-window
inclusion. Bars may allocate a supported net gain uniformly *inside its interval*
as a visualization estimate; this does not assert its intermediate trajectory.
Endpoint-supported gaps produce partial bars. Missing unsupported intervals remain
unknown, and the percentage graph does not connect across missing frames. Bar
amounts sum to the corresponding selected-window total, within display floating
point precision; server arithmetic remains exact fractions.

Work bounds remain 1,024 runs, 65,536 attempts and 128 MiB of raw source payload.
Unexpected oversized runs are unavailable rather than truncated. Only 4,096 recent
chart summaries may be returned; an oversized recent chart is explicitly marked
`chart_status=history_limit`, without turning a complete scalar total into a
partial one. No schema migration, destructive retention or historical edits.

## ETA display only

The formatter rounds to the nearest whole minute, including days and remaining
hours/minutes. Below 30 seconds it shows `~<1m`. Full duration stays in the title;
measured space pressure may abbreviate a multi-day value to days/hours. OBS uses
the same formatter. ETA arithmetic, dated/static retention, refresh and inactive
OBS semantics are unchanged.

| Duration | Former display | New full display |
|---|---|---|
| 24m 12s | ~25m | ~24m |
| 24m 31s | ~25m | ~25m |
| 1h 22m 12s | ~1h 25m | ~1h 22m |
| 7h 43m 28s | ~7h 45m | ~7h 43m |
| 2d 14h 7m | ~2d 14h | ~2d 14h 7m |

## Verification and reproduction

```powershell
.\.venv\Scripts\python -m pytest tests/test_tracked_exp_totals.py tests/test_rolling_history.py tests/test_eta_followup.py tests/test_cross_level_product.py -q
.\.venv\Scripts\python -m pytest -q
node --test tools/*.test.mjs
node tools/product.browser.mjs http://127.0.0.1:8874 private/tracked-exp-check-01 --verify-tracked-exp streamer_f
node tools/product.browser.mjs http://127.0.0.1:8875 private/tracked-exp-cross-01 --verify-cross-level streamer_a
node tools/product.browser.mjs http://127.0.0.1:8876 private/tracked-exp-eta-01 --verify-eta-followup streamer_e
```

Use new private directory names. Browser commands start their own read-only HTTP
server with isolated replay SQLite, original source times and an explicit as-of
clock; they do not connect to Twitch. They check polling, all five selectors,
bar/card sums, level filtering, unchanged 24h scope, restart/aging and desktop,
mobile and 500×160 OBS layouts. Multi-day screenshots are visibly labeled
**ETA FORMAT TEST** and are synthetic client formatting controls, not measured ETAs.

Deterministic regressions include newly tracked 35-minute histories (60 min =24h),
two-hour histories (24h >60 min), all nested periods, integer and percentage-only
evidence, 1/2/5/10 missing captures, scheduled rotation, restarts, sessions/sources,
level changes, losses/quarantine, contradictions, duplicates/staleness, expiry,
whole-boundary exclusion, streaming/full replay parity and coherent HTTP cache
timestamps. Tracked gains do not wait for the pace minimum duration.

Private receipts, before/after results, the exact 14-interval difference and
screenshots are under `private/tracked-exp-review/`. The Streamer_F query measured
median 25.5ms over ten reads, a 1.45MiB Python allocation peak and approximately
52KB JSON. A synthetic 4,321-attempt/73-run full-day query measured median 1.39s
over three reads, an 8.24MiB allocation peak and 77KB JSON. Those are local query
costs, not acquisition throughput, process-tree RAM or a 25-stream VPS prediction.
Long histories still cost a full bounded replay on cache invalidation; sustained
25-channel operation should be profiled before making a capacity claim.

The active capture database, original logs, OCR models, numerical grammar,
requirements, strict comparisons and trusted accounting were not modified.

Validation: **1,620 full Python tests passed; 81 Node tests passed; zero skips**.
The focused total/history/ETA/cross-level suite also passes. Chrome's saved
Streamer_F, CharA cross-level and CharE ETA replays passed, producing 13, 12 and
16 screenshots respectively. Representative final images are
`private/tracked-exp-review/browser-final/tracked-exp-desktop.png`,
`tracked-exp-mobile.png` and `eta-multiday-overlay-formatting-control.png`.
The Streamer_F browser check verifies all five totals, equal recent/24h as-of clocks,
bar/card sum equality, polling after real saved attempts are committed, aged
history, the unchanged level filter and static ETA retention.

Additional saved checkpoints remain nested: CharA's level-68 cohort has
54,663.82 EXP for both 60 minutes and 24 hours; its earlier 65→66 cohort has
13,444.9739 for both. CharE's later checkpoint has 90,584 EXP for 60 minutes and
311,344.4504 for 24 hours. None includes an invented level-up boundary gain.

Remaining limits: OCR can still produce numerically consistent wrong digits;
community requirements and configured character identity are not independent
verification. Long continuous rotation chains may hit existing causal work
limits and then return unavailable. No new live capture, schema change,
commit, push or deployment was performed.

Changed files:

- `src/exp_tracker/pace_intervals.py`: shared streaming eligibility, EXP conversion and window summaries.
- `src/exp_tracker/rolling_history.py`: same policy for all totals and bars; visit only overlapping buckets.
- `src/exp_tracker/product.py`: shared gain conversion and coherent public statistics packet.
- `src/exp_tracker/diagnostics.py`, `src/exp_tracker/server.py`: atomic read/cache reuse and bounded packet delivery.
- `src/exp_tracker/web/product.js`: consistent cards/bars and minute-precision responsive ETA formatting.
- `tests/test_tracked_exp_totals.py`, `tests/test_rolling_history.py`, `tests/test_endpoint_pace.py`: focused regressions and explicit replacement of the former adjacent-only expectation.
- `tools/product.test.mjs`, `tools/product.browser.mjs`, `tools/product_updates_fixture.py`: frontend tests and actual saved-log SQLite/browser replay.
- `README.md`, `docs/product-experience-principles.md`, `docs/cross-level-history.md`, this document: policy and reproduction notes.
