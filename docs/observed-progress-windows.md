# Useful recent windows without relaxing complete comparisons

The player page and homepage now show **observed percentage progress** for the
selected 5/10/15/30-minute period, separately from complete-window comparisons.
The current/early pace remains its own recent connected estimate. Neither partial
progress nor that short pace is substituted into completed-window ranks.

## What the saved trial actually shows

Replay source: `private/multi-alpha/runs/20261018T005419Z-6d0af805/`.
Its three logs per channel contain 172 Telfer1 and 171 Shiphtur attempts, including
failures. Each prefix was inspected against a fresh SQLite database as of its
original receipt timestamp (attempt timestamp for a failed acquisition). No frame
or timestamp was recreated, and no new OCR or Twitch acquisition was run.

There is **no rotation defect**: the scheduled 60 → successor-1 link preserves
strict continuity, ownership, source identity and level context. Strict results
are unchanged at all 34 checkpoints saved before implementation.

The old blank presentation followed intentional requirements: only the latest
uninterrupted segment counts; at least three readings/30 seconds, at least 90%
span, an initial endpoint within one configured capture interval of the window's
left edge, and the latest attempt as endpoint. Thus 90% span alone is insufficient.
This trial requests 13 seconds; an initial endpoint 54 seconds after a ten-minute
boundary fails even if its 546-second span exceeds 90%.

Telfer1's first run loses numerical availability at attempts 14, 16, 30 and 43.
The first three strict segment lengths are 156.15s, 0s and 156.03s. Attempt 30
(`162,285[9.74%`) has no closing boundary. Attempts 16/43 have no HUD. Attempt 14
also has conflicting level evidence (visual 66, neural 56), so it remains a hard
boundary even for the new partial summary. After #43 the strict segment restarts
at 01:03:40 and reaches only 208.07s at #60. It extends to 220.99s at successor #1.

**01:03:14 UTC**, as-of first-run #42:

| Selection | Accepted/rejected attempts inside window | Current strict span | New observed endpoints |
|---|---:|---:|---|
| 5 min | 23 / 1 | 142.89s | +1.02 pp / 299.03s; 23 readings, 1 interruption |
| 10 min | 39 / 3 | 142.89s | +1.18 pp / 351.06s; 26 readings, 2 interruptions |
| 15 min | 39 / 3 | 142.89s | Same 351.06s of defensible endpoints |
| 30 min | 39 / 3 | 142.89s | Same 351.06s; not a 30-minute measurement |

Accepted here means existing experimental **comparison-eligible** evidence, not
independently verified numerical correctness. Counts include eligible older
segments that cannot all be joined. No scheduled attempts are removed.

**01:07:21 UTC**, immediately after rotation:

| Selection | Accepted/rejected | Current strict span | New observed endpoints |
|---|---:|---:|---|
| 5 min | 23 / 1 | 220.99s | +1.04 pp / 299.05s; 23 readings, 1 interruption |
| 10 min | 44 / 3 | 220.99s | +2.03 pp / 598.04s; 44 readings, 3 interruptions |
| 15 min | 57 / 4 | 220.99s | Same 598.04s of defensible endpoints |
| 30 min | 57 / 4 | 220.99s | Same 598.04s; not a 30-minute measurement |

At 01:07:34, successor #2 predicts neural level 56 (score 0.52955), with no visual
level. This **level conflict**, not rotation, breaks both policies. By 01:09:18,
all four selections show +0.34 pp over 90.89s from eight supported level-66 readings.
The five-minute scope contains 23 eligible and one rejected attempt; ten minutes
44/3, and fifteen/thirty 65/5, but the conflicting boundary excludes older endpoints.
The UI reports the actual 1m30s span rather than assigning it to five minutes.

Strict five-minute eligibility first appears at 01:12:46. It later disappears at
new interruptions. Ten/fifteen/thirty never qualify in this trial. In particular,
the 545.88s segment at 01:16:53 fails the ten-minute **left endpoint** condition.
There was no evidence that the window selector, API cache or polling caused these
blank metrics. The product defect was hiding all useful partial information.

Across all causal prefixes (availability counts, **not accuracy or independence**):

| Channel | Attempts | Complete 5m available (unchanged) | Observed 5m available | Complete 10/15/30m | Observed 10/15/30m |
|---|---:|---:|---:|---:|---:|
| Telfer1 | 172 | 35 | 157 | 0 each | 157 each |
| Shiphtur | 171 | 21 | 56 | 0 each | 56 each |

## Separate endpoint policy

`windows[minutes].observed` is additive read-time metadata (`observed_window_v1`).
It contains actual endpoints, event IDs, elapsed span, evidence counts, holes,
unavailable/missing counts, age and paused state. `eligibility_checks` explains
each strict condition separately. No database migration or historical rewrite.

- Require three eligible readings spanning at least 30 actual seconds, within the
  selected window. Use only the latest defensible same-level context.
- Permit at most **two consecutive unavailable/missing attempts** and at most
  **60 seconds between supported endpoints**, inclusive. These are conservative
  presentation limits, not empirically validated identity guarantees.
- A malformed numeric field can be a disclosed hole. A failed acquisition can
  be a hole within the same explicit assignment/source. A missing-HUD capture
  requires the explicit `missing_hud` result and local receipt age ≤15s. Multiple
  HUDs, stale frames, suspect crops, conflicting/readable unsupported levels,
  malformed candidate metadata and uncertain numerical readings are boundaries.
- Preserve all ownership/source/session boundaries, out-of-order/duplicate events,
  restart boundaries, confirmed loss and excluded OCR-anomaly intervals. The
  existing validated scheduled-rotation exception is reused unchanged.
- Same-level endpoints must be nondecreasing; known quarantine and large-change
  safeguards still apply. No bypass using display-only carried levels.
- These are **net displayed endpoint differences**, not accumulated observed gains
  inside holes. Hidden loss/recovery or character changes inside missing frames
  cannot be ruled out; character identity remains unverified.
- No rate, EXP allocation, interpolation, ETA or ranking is derived from this
  summary. Charts retain their existing disconnected edges through gaps.
- A trailing short interruption or expired freshness retains an explicitly aged,
  paused summary. Hard boundaries clear comparison context; old endpoints are
  not borrowed to conceal a new level, restart or unresolved numerical event.

Public copy emphasizes `+1.04 pp`, actual duration, readings and interruptions.
The complete-window EXP/hour field says `Not complete yet`, `Paused`, or shows a
genuinely eligible comparison. The main recent pace stays above it, unchanged.
Homepage rows gain the observed summary; ranking continues to require strict windows.
The experimental OBS overlay's calculation and strict semantics are unchanged.

## OCR scope

All three supplied examples already yield unique full and percentage hypotheses
under unchanged `bounded_exp_v3`:
`175,298110.52%1` → `175,298[10.52%]`,
`178,991[10.74%1` → `178,991[10.74%]`, and
`183,340[11.00%1` → `183,340[11.00%]`.
They were not responsible for the empty windows. Missing actual boundaries such
as the first-run #30 remain unavailable. No punctuation rule or numerical label
was changed, and this work establishes no new OCR accuracy claim.

## Reproduce and verify

```powershell
# Serve the existing actual database; this does not start capture.
.\.venv\Scripts\python -m exp_tracker.server --db private/multi-alpha/live-telfer-shiphtur.sqlite3 --diagnostic-dashboard --port 8766
Start-Process 'http://127.0.0.1:8766/stream/telfer1'

# Real saved two-stream SQLite replay, causal as-of clock, all window buttons,
# rotation, live DOM polling, stale states and desktop/mobile screenshots.
# Choose a NEW private output directory each time.
node tools/product.browser.mjs http://127.0.0.1:8781 private/observed-windows/review-new --verify-windows telfer1
node tools/product.browser.mjs http://127.0.0.1:8782 private/observed-windows/quarantine-new --verify-quarantine telfer1
.\.venv\Scripts\python -m pytest -q -rs
node --test tools/*.test.mjs
```

Private detailed audit/reproduction script: `private/observed-windows/audit.py`;
run `python private/observed-windows/audit.py private/observed-windows/audit-new`.
`all-prefixes/audit.json` retains input SHA256s, per-frame decisions, segment breaks,
checkpoints and availability counts. All six original log hashes were unchanged;
the fresh replay contains zero trusted observations. Median product projection
cost was approximately 6–11ms across the measured checkpoints under varying test
load; no extra SQL query, dependency, OCR inference or capture process was added.

Chrome screenshots in `private/observed-windows/browser-03/` include all four
desktop/mobile selections, post-rotation and stale summaries, homepage and overlay.
The independent existing quarantine browser regression is in
`private/observed-windows/quarantine-browser-01/`. Both use actual HTTP/SQLite data;
the latter also retains its clearly synthetic complete-window/loss control.
No full-page navigation, console errors, external browser requests or horizontal
overflow were observed. Actual OBS and new livestreams were not tested.

Validation: **1,272 Python tests passed, zero skipped**; **60 Node tests passed**.
Focused checks passed 47 Python tests. Chrome's observed-window check passed with
18 screenshots, and the unchanged quarantine/loss workflow passed with 11.
`git diff --check` passed. An initial sandboxed pytest run could not create its
default temporary directory; the final suites used a private workspace basetemp
and completed without environmental skips or failures.

Changed files: `src/exp_tracker/product.py`, `web/product.js`, `web/product.css`,
`tests/test_observed_windows.py`, `tools/product.test.mjs`, `tools/product.browser.mjs`,
`tools/product_updates_fixture.py`, `README.md`, and this guide. Private audit tools,
databases, raw evidence comparisons and screenshots remain ignored.

The next useful product check is to inspect these summaries during a manually
authorized 15–20s two-stream trial; evaluate level-56/66 conflicts separately rather
than weakening continuity to obtain long-window ranks.
