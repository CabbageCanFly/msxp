# Recent pace across level reacquisition

The [endpoint pace policy](endpoint-exp-pace.md) supersedes the missing-interval
exclusion in this historical report; its original measurements are unchanged.

`responsive_pace_v4` retains separately eligible captured intervals across a
temporary missing HUD and matching-level reacquisition. It changes only the
experimental consumer pace projection. No OCR, level acceptance, grammar,
requirements, schema, trusted accounting, chart connections or strict window/rank
policy changes are involved.

## Bounded policy

The existing `observed_sequence()` context builder has an opt-in pace-only flag.
A reacquisition frame can preserve prior interval context only when:

- The existing level policy reports `pending / neural_confirmation_pending`.
- Its neural level matches the previously supported level, with no competing
  visual level. This does **not** accept or assign a level to that frame.
- Existing percentage review allows public display, with no quarantine or break.
- The percentage is nondecreasing and below the existing large-change boundary.
- The existing consistency helper finds no full-integer contradiction at the
  earlier supported level. This is a veto, not numerical or level confirmation.
- Source, session, character, time, freshness, HUD and crop guards remain intact.

Pending frames never enter the endpoint set. The first subsequently confirmed
frame starts a new connected sequence; only its next eligible comparison can
contribute. Only comparisons already marked `contiguous_diagnostic_endpoints`
can supply gain or time. A missing interval supplies neither. Strict consistent
integer EXP differences remain preferred when every contributing endpoint
supports them; otherwise the existing percentage conversion is used.

The pooled rate is `sum(valid gains) * 3600 / sum(valid captured seconds)`.
Percentage quantization bounds are summed separately for each connected group's
endpoints under half-up and truncation. Groups never include the percentage jump
inside a hole. These bounds exclude OCR, requirement and identity uncertainty.

Actual level changes, unresolved competing levels (even without a readable
percentage), confirmed losses, quarantines, unsafe crops, duplicated images,
stale frames, identity/session/source changes and unvalidated restarts clear the
pool. The existing validated scheduled-rotation link remains supported. A
configured character still does not authenticate the character in every frame.

Whole intervals must start within the actual five-minute lookback at projection
time. Unreadable captures and advancing time expire older edges; intervals are
never split or assigned gain/time from the missing period. This intentionally
replaces v3's cutoff anchored to the last contributing edge. Existing aging uses
the remaining sampled coverage, then pauses when no recent pool remains or the
last eligible interval is five minutes old. Dated historical rates may remain
inspectable after expiry/completion, explicitly inactive; they do not seed a new
current sample or become eligible window measurements.
Directory caching also rebuilds a card when its oldest contributing interval
expires, even without a new SQLite revision; unchanged polls otherwise reuse it.

## Saved Niru checkpoint

Read-only SQLite replay at **2026-10-18 10:01:43.587889 UTC**, rotated-run attempt
43, exactly reproduces the investigation's predicted result:

| | Before | After |
|---|---:|---:|
| Contributing readings | 4 | 11 |
| Connected sequences | 1 | 2 |
| Valid sampled seconds | 59.761925 | 179.750444 |
| Full sample extent | 59.761925s | 240.285252s |
| Diagnostic EXP/hour | 111,562.67 | 136,228.87 |
| Strict 15-minute eligible | No | No |

The two contributing pieces are **09:57:43–09:59:43** and
**10:00:43–10:01:43**, containing 6,802 EXP of existing strict, consistent endpoint
differences. No difference is taken between the pieces. Agreement with the
investigation is exact before presentation rounding; this is not independent OCR
accuracy verification or an assertion about earnings during the gap.

At 09:46:23, another checkpoint increases from four readings / 59.49s to eleven
readings / 158.93s across three sequences (~107,753 EXP/hour). At 09:47:03,
old stationary edges have expired: the inactive sample is eight readings /
119.21s, rather than the investigation's eleven / 158.93s calculation anchored to
the last valid edge. This difference is the requested genuine rolling cutoff.
At the scheduled rotation's next-run attempt 1, ten readings / 139.04s remain
available across three groups. All four replay checkpoints retain identical
strict window objects and historical chart data compared with the pre-change code.

The source SQLite connection used read-only mode and closed before in-memory
checkpoint processing. Original JSONL hashes were checked unchanged. Private
audit: `private/pace-pooling/niru-audit-final.json`; script:
`private/pace-pooling/audit_niru.py` (choose a new result filename to repeat).
Twenty 109-observation in-memory projections, including snapshot copying, measured
18.20ms median / 19.55ms p95 on this workstation. This excludes OCR/acquisition and
does not establish deployment capacity.

## Public presentation

The current-rate subtitle now says, for example,
**recent trend · 11 readings / 180s sampled · 2 sequences**. A small sample retains
the **first estimate** label. Tooltips use captured coverage rather than the full
extent containing holes. Aging/paused/saved statuses remain distinct.

The level-percentage chart still plots every original gap and guarded connection.
Its caption now counts visible numerical points, with unavailable attempts
separate. The Niru screenshot changes from **44 readings / 860s** to
**38 readings · 6 unavailable · 860s displayed**; no points were removed.

## Verification and reproduction

```powershell
.\.venv\Scripts\python -m pytest tests/test_pace_reacquisition.py tests/test_companion_statistics.py tests/test_hud_resilience.py tests/test_responsive_product.py tests/test_percentage_quarantine.py tests/test_diagnostic_history.py -q
.\.venv\Scripts\python -m pytest -q -rs
node --test tools/*.test.mjs

# Saved-data browser resilience fixture; creates its own NEW private test DB.
# Use a new output name and an unused localhost port on each run.
node tools/product.browser.mjs http://127.0.0.1:18967 private/pace-pooling/browser-new --verify-resilience telfer1

# View existing saved data independently; does not start capture or mutate SQLite.
.\.venv\Scripts\python -m exp_tracker.server --db private/multi-alpha/live-telfer-shiphtur.sqlite3 --diagnostic-dashboard --port 8766
Start-Process 'http://127.0.0.1:8766/stream/niru'
```

The focused suite includes missing-HUD/reacquisition, exact integer and percentage
sums, group rounding bounds, conflicting levels, contradictory pending integers,
duplicate/stale frames, losses/quarantine, session/source/restart boundaries,
rotation and expiry with/without new captures. Existing expiry tests were updated
to assert removal of old intervals rather than v3's frozen sample; their evidence
fixtures remain unchanged.

Final validation: **122 focused Python passes**, including diagnostics, **17 new
regression cases**, **1,413 full-suite passes, zero skips**, in 120.42s, and **72
Node passes**. `git diff --check` passed. One intermediate full run had an
intermittent existing `test_real_neural_timeout_reaps_worker` PID-presence failure;
the PID was subsequently absent, the isolated check passed, and the final full
rerun passed. Capture-worker code/tests were not altered to mask it.

Actual Chrome checks used unchanged saved data in a **new isolated replay DB**,
with an explicitly simulated as-of clock and coordinator activity, plus the
existing two-stream resilience fixture. No Twitch capture/status request occurred.
Desktop/mobile, 500x160 overlay, repeated polling, gap/aging/recovery/paused/restart
states, chart counts and no horizontal overflow passed. Representative screenshots
were inspected under `private/pace-pooling/browser-niru-final/`; polling/recovery
evidence is under `browser-resilience-final/` (five update stages / 20 screenshots;
Niru: seven screenshots). A sandbox loopback separation initially
blocked the private replay browser; running that isolated server and Chrome with
localhost access resolved it. The active coordinator was not stopped or modified.

Changed files: `src/exp_tracker/product.py`, `src/exp_tracker/diagnostics.py`, `src/exp_tracker/web/product.js`,
`tests/test_pace_reacquisition.py`, `tests/test_companion_statistics.py`,
`tests/test_hud_resilience.py`, `tools/product.test.mjs`,
`tools/product.browser.mjs`, `README.md`, and this guide.

Remaining limits: sampled pace can be biased by which gameplay is readable and
still inherits correlated OCR errors. It is not elapsed-window earnings. No new
human labels, image verification, live capture, model tuning or trusted promotion
was performed. Restart the application manually when ready to load the changes.
