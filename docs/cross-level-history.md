# Cross-level recent EXP and history

Selected 5/10/15/30/60-minute periods now include independently supported EXP
intervals from all levels inside that elapsed period. **Current level only** is
off by default. It filters recent cards and charts without changing their time
axis. The 24-hour total and 24-hour chart always include all levels.

## Cause and calculation

The interval collector already retained independent intervals before and after
level changes. `responsive_pace(pool_history=True)` discarded earlier levels,
and `drawPercentageHistory()` independently filtered to the displayed level and
started its axis at that level's first point. These were presentation policies,
not missing SQLite records.

- Recent EXP sums eligible same-level intervals. A validated integer difference
  takes precedence; otherwise the percentage difference uses **that interval's**
  community level requirement. Mixed-level rates have no combined percentage/hour
  or percentage-point total.
- EXP/hour is summed EXP divided by summed eligible interval durations, multiplied
  by 3,600. This is a partial sampled rate, not necessarily a complete-window rate.
  Whole intervals must fit the selected period; boundary intervals are not split.
- Ordinary missing OCR may still have supported endpoints, including actual gap
  time. Unsafe boundaries, stale/duplicate frames, losses, contradictory numbers,
  source/character/session changes and unvalidated restarts never acquire an
  artificial endpoint difference. Independent intervals on either side survive.
- Each percentage-based interval retains separate nearest-half-up and truncation
  bounds. Integer and percentage runs are separated when combining uncertainty.
  Requirements remain community-sourced; these are not statistical error bounds.
- ETA uses the **current supported level's** remaining EXP and the selected-period
  EXP rate, even if some rate evidence came from earlier levels. A new independently
  supported level can use an earlier-level rate before its second gain endpoint.
  The API separates `estimated_at` from `rate_observed_at` and their ages. A dated
  static duration survives missing OCR, stopped capture, restart and window expiry;
  unsupported requirements, conflicting levels or nonpositive rates still withhold it.
  The OBS overlay retains its separate live ETA semantics.

No cross-level transition gain is added. The formula would be old-level remaining
EXP plus new-level accumulated EXP, but its prerequisites are not met by these
saved transitions: the old 65 endpoint lacks supported level evidence, the first
68 endpoint is conflicting, and CharE's transition is unsampled. Even synthetic
clean transitions currently retain only the independent intervals on each side.
This deliberately leaves the boundary contribution unknown.

The server now projects chart history from the existing bounded 65-minute SQLite
snapshot, rather than the 640-row latest-observation slice. Recent retrieval is
still limited to the selected character/session, with at most 4,096 projected
attempts and the existing causal-read work limits. Run restarts separate interval
anchors; validated scheduled rotation retains continuity. No migration or stored
payload change is needed. Older sessions remain in Advanced.

The percentage chart shows both levels and marks the reset; it draws no line
through a level boundary or missing/unsafe capture. Disconnected new levels say
“Lv. … seen” rather than claiming a directly observed level-up. Short EXP bar
views also follow the selected period. The separate 30-minute-bucket chart keeps
its rolling 24-hour range.

## Saved evidence, explicit UTC checkpoints

Private replay databases contain original log payloads, not new captures or
retimed observations. Native EXP/level crops were inspected together with nearest
neighbor enlargements. That inspection was AI-assisted, not independent human
adjudication. No OCR was rerun or tuned.

| Case / period | Before EXP | After EXP | Eligible elapsed | After EXP/hour |
|---|---:|---:|---:|---:|
| CharA 67→68, 5 min at Oct 19 00:36:30.840861 | 5,445 | ≈12,125 | 187.07s | ≈233,324 |
| Same checkpoint, 60 min | 5,445 | ≈54,664 | 902.46s | ≈218,060 |
| CharA 65→66, 60 min at Oct 18 00:17:30.902898 | 12,971 | ≈13,445 | 228.85s | ≈211,505 |
| CharE 56→57, 60 min at Oct 18 23:02:00 | 8,472 | 102,016 | 2,621.36s | ≈140,102 |

CharA's screenshot was reproduced exactly before the change: four level-68
readings / 82.072135s, 5,445 EXP, 238,838.68 EXP/hour and 27,817.07s ETA.
The revised 60-minute result uses 35 readings, three separate sequences and
54,663.82 EXP over 902.455609 eligible seconds. Its actual endpoint span is
1,003.172015s, **not 60 minutes of complete coverage**. Remaining level-68 EXP
uses the unchanged 1,854,143 requirement and 8,645 endpoint; ETA is 30,467.68s,
displayed as approximately 8h 30m. Current-level-only restores the 5,445 result.
The 5-minute result uses ten contributing readings, 12,124.697 EXP and ≈7h 55m ETA.

Sources:

- `20261019T001945Z-65cc75a7` and `20261019T003226Z-cbe9ba29`, CharA prefixes
  ending at the latter run's attempt 10. Crops show 67 / 99.93% at attempt 4 and
  68 / 492 EXP / 0.03% at attempt 5. Attempt 5's projected conflict and attempt 6's
  incomplete syntax remain excluded. The accepted new-level baseline starts at 7.
- `20261018T001050Z-b970792e`, CharA through attempt 42. Crops show 65 / 99.97%
  then 66 / 103 / 0.01%, but weak level evidence at old-level attempts 11–13 stays
  excluded. Earlier valid level-65 intervals now remain in longer selected periods.
- `20261018T211439Z-794bf39d`, CharE including its rotation logs, plus
  `20261019T000710Z-bda4f628`. Last saved neural 56 is Oct 18 22:42:20.774410;
  first neural 57 is 22:57:46.960569. That 15m 26s gap supplies no transition gain
  or confirmed level-up marker. At Oct 19 00:18:17.939131, level 56 is outside
  the selected hour, so the existing 90,584-EXP recent total correctly stays unchanged.

Historical note: the [tracked-EXP consistency follow-up](tracked-exp-consistency.md)
now replaces the stricter aggregation difference below. These original audit
values are retained as before-change evidence.

The then-unchanged 24-hour totals in these isolated cohorts are approximately 45,025
(CharA 68 checkpoint), 9,352 (CharA 66), and 296,981 (CharE later checkpoint).
They use the older, stricter connected-history aggregation. Therefore that total
can be smaller than a recent endpoint-supported estimate; it is not a superset
of all responsive-estimator contributions. Harmonizing those policies is separate
work, not a reason to manufacture missing gains here.

## Verification and reproduction

```powershell
.\.venv\Scripts\python -m pytest tests/test_cross_level_product.py tests/test_eta_followup.py tests/test_numerical_windows.py -q
.\.venv\Scripts\python -m pytest -q
node --test tools/*.test.mjs
node tools/product.browser.mjs http://127.0.0.1:8874 private/cross-level-check-01 --verify-cross-level streamer_a
node tools/product.browser.mjs http://127.0.0.1:8875 private/cross-level-eta-check-01 --verify-eta-followup streamer_e
```

Use fresh private output names. The browser commands start/stop their own replay
server, use real SQLite/HTTP/frontend polling, and preserve source timestamps.
The fixture advances an explicit as-of clock; this is not live capture or a speed
benchmark. Normal use is unchanged: open `/stream/CHANNEL` on the existing local
server and choose a period; no coordinator restart or database rewrite is needed.

Detailed receipts, input hashes, per-frame decisions, before/after numerical
results and screenshots are ignored under `private/cross-level-review/`.
The original source run continued recording independently during development;
regressions use fixed earlier prefixes/as-of clocks, never its moving tail.

On the isolated saved databases, ten repeated read-only snapshot + player + chart
projections took median 32.6ms / 37.96ms / 400.81ms for the CharA-68 / CharA-66 /
CharE-later cohorts. Sampled Python allocation peaks were 1.15 / 1.38 / 9.73MiB;
JSON sizes were 245 / 246 / 643KB, with 37 / 42 / 164 chart attempts. These are
local replay measurements, not 25-stream capacity or process-tree RAM claims.

Chrome verified desktop/mobile layouts, all five periods, reset markers, the
filter's fixed axis, unchanged 24h values, polling without navigation, restart,
expired-window dated ETA and the transparent 500×160 overlay. Numerical vetoes,
strict complete-window/ranking policy, trusted ingestion, raw evidence and EXP
requirements are unchanged. No new Twitch connection, commit or deployment.

Final validation: **1,596 Python tests passed, zero skipped; 78 Node tests passed,
zero skipped**. The 17 cross-level Python regressions include both saved CharA
transitions, CharE's unsampled transition, mixed conversion bounds, requirements
unavailable at the new level, restart restoration and scheduled SQLite rotation.
Three successful Chrome replays produced 12 cross-level, 16 ETA/short-gap and
14 older level-up screenshots. Representative final images are
`private/cross-level-review/browser-final/cross-level-60min-desktop.png`,
`cross-level-60min-mobile.png`, and `current-level-only-mobile.png` in that folder.
One additional older-replay launch timed out; a clean rerun exposed outdated
harness expectations for saved labels/two-reading ETA, which were corrected.
The final older replay passed with no browser exceptions or external requests.

Changed files:

- `README.md`, `docs/product-experience-principles.md`, `docs/cross-level-history.md`
- `src/exp_tracker/product.py`, `src/exp_tracker/server.py`
- `src/exp_tracker/web/player.html`, `src/exp_tracker/web/product.js`, `src/exp_tracker/web/product.css`
- `tests/test_cross_level_product.py`, `tests/test_numerical_windows.py`
- `tools/product_updates_fixture.py`, `tools/product.browser.mjs`, `tools/product.test.mjs`

The next narrowly scoped calculation investigation would be transition-edge
eligibility with genuinely complete, independently corroborated endpoints. It
should not hold up this cross-level history view or reuse ambiguous level-up
frames as proof of exact earned EXP.
