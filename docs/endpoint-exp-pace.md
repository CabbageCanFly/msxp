# Recent EXP/hour from cumulative endpoints

This policy supersedes the responsive estimator's earlier prohibition on using
elapsed time and net EXP across unreadable captures. Strict completed windows,
rankings, chart connections/bars, 24-hour totals and trusted accounting retain
their existing policies. Raw captures, parsers, requirements and SQLite schema
are unchanged.

## The defect and replacement

Previously `observed_sequence()` returned the latest safe context; a hard break
removed earlier contexts from consideration. `responsive_pace_v4` then selected
only adjacent `contiguous_diagnostic_endpoints` comparisons within that context.
It could pool several pieces across benign holes/reacquisition, but omitted the
net changes **and elapsed time** inside those holes. An unsafe observation could
erase earlier unrelated intervals. Extending its missing-frame allowance could
not fix these two conceptual problems.

`endpoint_pace_v1` uses a separate bounded interval collector and the existing
sanitized reading decoder, level projection and causal percentage-review decisions:

- **Direct:** consecutive eligible cumulative endpoints.
- **Endpoint-supported:** eligible same-level/context endpoints around unreadable
  or missing captures. Their net difference and **whole actual elapsed time**
  contribute. Intermediate values and gain timing are not invented.
- **Unsafe:** quarantine, incompatible EXP, suspect/ambiguous crops, stale/duplicate
  frames, conflicting or unsupported level evidence and invalid timestamps prevent
  subtraction across the boundary. Earlier safe intervals remain; later safe
  intervals can contribute independently. No overlapping time is counted twice.

Explicit character/session/source changes, confirmed level changes and
unvalidated run restarts establish a separate context. Rates
from different such contexts are not blended. Clean validated scheduled rotation
preserves context. Weak level evidence is usable only if the existing level policy
supports it; matching pending reacquisition may be skipped but is not an endpoint.
Neither assigned character nor same-level evidence authenticates broadcast identity.
Elapsed time uses saved local decoder-receipt timestamps, not independently
verified broadcast presentation times or latency.
Confirmed loss starts a new subtraction baseline. Valid positive intervals before
and after that same-level boundary may remain separate rate samples; no negative
difference or return to the old baseline is counted as a cross-boundary gain.

The rate is `sum(eligible net gains) * 3600 / sum(eligible elapsed seconds)`.
Compatible numerical EXP endpoints are preferred, including punctuation-only
interpretations; otherwise percentage movement uses the supported community
requirement. Percentage-only rates remain possible when numerical conversion is
unavailable. Rounding/truncation bounds remain separate, excluding OCR/table errors.
An unseen loss followed by recovery inside a gap can only yield **net** movement;
this is not gross EXP earned or an authoritative session total.

## Required timeline, reproduced

The synthetic fixture explicitly supplies a 10,000,000-EXP requirement. It is not
a new game-table entry. All six actual observations remain unchanged.

| Endpoint interval | Net EXP | Elapsed | Category |
|---|---:|---:|---|
| 00:00–00:20 | 100,000 | 20s | Direct |
| 00:20–01:00 | 200,000 | 40s | Endpoint-supported; missing 00:40 |
| 01:00–01:40 | 200,000 | 40s | Endpoint-supported; missing 01:20 |
| 01:40–02:00 | 100,000 | 20s | Direct |
| 02:00–02:20 | 100,000 | 20s | Direct |

**700,000 EXP / 140 seconds = 18,000,000 EXP/hour.** No points are generated at
00:40 or 01:20. The API/UI reports **6 readings / 140s elapsed · 2 missing readings**.

The old estimator coincidentally also returned 18,000,000 EXP/hour on this uniform
example, but used only **5 endpoints, 300,000 EXP and 60 seconds**. A regression
variant changes the real 01:40 observation to 650,000: old selection gives
250,000/60s = 15,000,000/hour; the correct net average remains 700,000/140s =
18,000,000/hour. This tests the denominator rather than merely the final number.

## Rolling age and missing captures

Only whole intervals starting within the genuine five-minute lookback contribute
to the recent rate; intervals are not split at the cutoff. There is no missing-
attempt-count reset. Tests with 1, 2, 5 and 10 consecutive 20-second missing
attempts retain prior evidence and use the very next validated endpoint, including
the entire gap duration. No new adjacent-pair warm-up is imposed by missing data.

A single endpoint interval longer than five minutes cannot support this five-minute
rate. It is excluded rather than shortened or assigned its gain to the window.
The next independently valid pair can seed new recent evidence. Meanwhile the
last supported rate stays dated. Expiry depends on timestamps, not failure count.

During an outage, hold the last percentage and **last observed** rate with age and
sample extent. The earlier no-new-gain decay has been removed: unreadable captures
are not zero-gain observations. Old intervals expire as the clock advances. Once
no recent intervals remain, the dated historical sample remains inspectable; a
running capture's public rate pauses after 30 minutes without eligible evidence.
Completed/stopped views retain dated history. Missing/historical samples never
keep ETA active or qualify for strict rankings.

`coverage_seconds` is retained for API compatibility but now means eligible
**endpoint elapsed time**, including supported gaps. `interval_counts`, interval
IDs/timestamps/gains/bases, missing event IDs and unrecorded-index counts disclose
the calculation. Separate unsafe pieces can have a larger overall span than
their summed eligible elapsed time. Unrecorded IDs are never fabricated.

## Conditional `X` → `%`

Ordinary `interpret_exp()` and strict parsers still reject a missing literal `%`.
The existing bounded `symbol_hypotheses` supplies a unique full-field candidate;
the new `conditional_percent_v1` can admit it **only for experimental current
display and responsive endpoint evidence**, requiring:

1. One whole-field interpretation, complete numeric grammar and at most four
   punctuation edits. No digit insertion/substitution or broad `X` replacement.
2. Two prior supported matching-level reader observations, **both within 120s**,
   plus distinct hashes for both supporting frames and the current frame.
   Recovered `X` frames cannot seed/renew their own level support.
3. Fresh unique HUD/source evidence, no known crop damage, duplicates, stale time,
   current competing level or assignment/source discontinuity.
4. A supported requirement and full-pair compatibility under an unchanged display
   hypothesis. Arithmetic supports a prior visual level; it never chooses a level.
5. Nondecreasing EXP/percentage relative to a validated temporal reference, below
   the existing large-change boundary. No repair from 22.25 to 22.75.

A bad numerical observation invalidates subtraction, not necessarily earlier
reader agreement. An otherwise corroborated `X` interpretation may establish a
**new baseline** after it, without a gain across the rejected observation. Strong
level conflict or identity/source uncertainty clears that corroboration instead.

Eligible/rejected decisions retain raw text, interpretation, every edit, support
event IDs, arithmetic evidence, policy, reason and baseline status. Public values
use `~` and a tooltip; Advanced shows the conditional result beside unchanged raw
OCR. The API exposes `conditional_recoveries` and per-row `conditional_percent`.
Original diagnostic percentage reviews and strict candidates remain unchanged.
Conditional endpoints cannot supply strict windows, chart gains, 24-hour totals,
trusted observations or ETA. Derivation is reproducible after server restart.

## Saved evidence

Read-only inspection confirmed all 60 source attempts and exact #10–13 raw strings
in the live SQLite database. That connection closed promptly; no coordinator was
interrupted. Before/after comparisons use the existing frozen **first 55** Streamer_A
attempts and CharB's **41-frame** saved run, in a new ignored replay database.
Inputs were hash-checked unchanged. Counts below describe eligibility, not verified
accuracy; there are no saved #12 source pixels to independently verify its `X`.

| Checkpoint | Before: readings / seconds / EXP/hour | After |
|---|---|---|
| Streamer_A #10 | 10 / 179.65 / 207,826 | 10 / 179.65 / 210,248; numerical endpoint preference |
| Streamer_A #12 | Old sample retained; no usable #12 percentage | Conditional 401,128 / 22.82%; **new baseline**, no #10→12 interval |
| Streamer_A #13 | Inactive 10 / 179.65 / 207,826 | Active 12 / 199.65 / 210,659; includes #12→13 |
| Streamer_A #14 | 2 / 19.96 / 158,490 | 13 / 219.62 / 207,099 |
| Streamer_A #23 | Inactive 9 / 159.90 / 186,000 | Active 13 / 239.85 / 191,158; includes net endpoint interval around unavailable #22 |
| CharB #41 | 40 / 273.15 / 171,389 | Identical |

Streamer_A #11 remains withheld: its EXP and 22.25% contradict the supported level-67
requirement. #12 now uses prior reader-supported 67, unique punctuation syntax,
compatible arithmetic and noncontradictory numbers; it does not erase #11 or
guess 22.75%. The ordinary parser still has no #12 strict candidate. All **96
checkpoint window objects are identical** before/after; raw chart rules and trusted
accounting are unchanged. Small wrong digits can still fit a percentage bin:
the controlled 401,129 / 22.82% counterexample also passes conditional gating.
This is explicitly experimental recovery, not numerical or pixel verification.

## Validation and commands

```powershell
.\.venv\Scripts\python -m pytest tests/test_endpoint_pace.py tests/test_pace_reacquisition.py tests/test_hud_resilience.py tests/test_companion_statistics.py tests/test_percentage_quarantine.py -q
.\.venv\Scripts\python -m pytest -q -rs
node --test tools/*.test.mjs

# New ignored directory and unused port; saved-data workflow, no live capture.
node tools/product.browser.mjs http://127.0.0.1:18975 private/endpoint-pace/browser-new --verify-resilience streamer_a

# Separate read-only server; does not start or interrupt capture.
.\.venv\Scripts\python -m exp_tracker.server --db private/multi-alpha/live-local.sqlite3 --diagnostic-dashboard --port 8766
Start-Process 'http://127.0.0.1:8766/stream/streamer_a'
```

Private audit scripts/results are under `private/endpoint-pace/`: before/final
checkpoints, synthetic baseline comparison, input hashes and read-only source
check. Thirty player projections measured Streamer_A 10.50ms median / 11.95ms p95
(55 rows), CharB 5.79ms / 6.13ms (41 rows), excluding acquisition/model loading.
The collector uses the existing 640-row bound; no full-history browser transfer
or schema change was added. These timings do not establish VPS throughput.

Chrome verified five polled gap/recovery/pause/restart/finish stages without
navigation. `browser-x12` and `browser-gap23` show actual replay values on desktop,
390px mobile, homepage and 500×160 OBS. Runtime activity/as-of clocks are explicitly
simulated in private fixtures; source timestamps and images are not retimed.
No new Twitch capture, OCR inference or independent accuracy evaluation occurred.

Changed implementation files: `src/exp_tracker/pace_intervals.py` (new collector
and conditional recovery), `product.py` (rate projection/current display),
`server.py` (read-only Advanced annotations), and `web/product.js` /
`web/shadow.js` (elapsed-time disclosure and recovery provenance).
Tests: new `tests/test_endpoint_pace.py`; updated `test_companion_statistics.py`,
`test_gap_level_resilience.py`, `test_historical_product.py`, `test_hud_resilience.py`,
`test_pace_reacquisition.py`, `test_responsive_product.py`, `tools/product.test.mjs`
and `tools/product.browser.mjs`. Old assertions that excluded all gap time or
discarded earlier intervals were explicitly replaced; strict history/window
assertions and frozen fixtures were not weakened. README/product principles link
this policy; the two prior pace reports carry supersession notices without
rewriting their historical results.

Final checks: **1,475 Python passes in 160.65s, zero skips; 74 Node passes**.
SQLite-backed Chrome checks passed for the five polling/recovery stages and both
actual Streamer_A checkpoints, including desktop/mobile/OBS screenshots. Inspected
screenshots show readable values and no horizontal overflow. `git diff --check`
passed. Test servers were shut down; the active coordinator was left running.
The next useful authorized trial is a saved-crop run with independent review of
conditional recoveries, particularly nearby wrong digits that arithmetic cannot
reject. No new capture is required to use this implementation.
