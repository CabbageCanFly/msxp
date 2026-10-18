# Pace through gaps and bounded level context

The responsive no-gap and no-new-gain-decay rules below are historical. The
[endpoint pace update](endpoint-exp-pace.md) supersedes them and adds conditional
`X` recovery; the original findings/counts remain preserved here.

This update changes read-time experimental interpretation and public presentation.
It does not change capture, models, strict parsers, SQLite payloads/schema,
requirements, character assignment or trusted accounting.

## Saved Telfer1 reproduction

The source is the `20261018T181128Z-26a1d13b` multi-stream run. Its coordinator
was still appending during inspection, so the audit freezes attempts **1–55**,
rather than treating a moving log as a fixed benchmark. The original SQLite
connection was read-only and closed before replay. All subsequent writes and
browser checks use new private replay databases. No coordinator was interrupted.

There are **no saved source crops in this run directory**. Geometry and raw OCR
are available; pixel identity, the apparent `X`, and a possible 22.75% at #11
cannot be verified. No new capture or inference was run.

| Attempt | Original exclusion/status | New read-time result |
|---|---|---|
| 10: `398,923122.69%1` | Grammar proposal, both level readers 67; accepted, but earlier level conflicts left pace on an old 3-reading sequence | Same numerical proposal; recent eligible context now supplies 10 readings / 179.65 captured seconds |
| 11: `399.979122.25%1` | Grammar succeeds; Tesseract 67 versus neural 57 at 0.68772 produces a level conflict; decreasing percentage is withheld | Recent corroborated 67 is retained as contextual evidence. Full EXP contradicts 22.25% under both hypotheses. Decrease stays pending/quarantined; no displayed update or gain. **Never changed to 22.75%.** |
| 12: `401.128122.82X1` | No literal `%`, neither level reader usable; grammar rejects, no numerical endpoint | Same exclusion. Separate review-only `401,128[22.82%]` hypothesis records every punctuation edit. It never enters ordinary recovery, progress, charts or accounting |
| 13: `402.319[22.89%]` | Strict full pair, but neural 57 at 0.71207 is pending and visual level unavailable; public number available but no progress endpoint | Prior corroborated 67 plus compatible full pair supports a contextual level. Integer is conditionally consistent; starts a **new baseline**, not a gain across #11–12 |

The recorded #11 crop is displaced relative to #10/#12. Without its pixels,
that is not proof of a crop-caused digit error. A plausible corrected percentage
is not evidence for changing the OCR text.

Across the frozen 55 attempts:

| Diagnostic quantity | Before | After |
|---|---:|---:|
| Public-eligible percentages | 52 | 52 |
| Progress-eligible points | 48 | 52 |
| Connected captured intervals | 43 | 49 |
| New usable points | — | #4, #8, #9, #13 |
| Lost usable points | — | None |

At #10, the old inactive 3-reading / 39.93s rate (~190,191 EXP/hour) becomes
an active 10-reading / 179.65s rate (~207,826 EXP/hour). At #11–13 the latter
remains a **dated historical estimate**, with no ETA. #14 supplies the first new
eligible interval after #13. No gain or elapsed time is supplied for #11–12.
These are availability/evidence comparisons, not human-verified accuracy counts.

## Context policy

`experimental_level_v2` retains the original reader decision alongside contextual
evidence. Two supported same-level reader observations establish a hypothesis.
Agreement, or existing strong provisional neural evidence, can renew it;
contextual readings cannot renew themselves. The existing 0.90 seed-quality gate
separates weak contradictory neural evidence; it is not calibrated correctness.

Context expires after **120 real seconds**, with at most **two weak competing
neural observations**. A current matching accepted visual level can support the
hypothesis. Otherwise a full pair must be compatible with that already-supported
level under at least one unchanged display hypothesis, and orderly relative to
the anchor. Arithmetic never enumerates/selects a replacement level. Missing
percentages, resets and numerical contradictions cannot supply this corroboration.

Strong competing levels, changed accepted visual levels, invalid reader records,
unsafe/multiple HUDs, known suspect crops, duplicate images, stale captures,
out-of-order time, assignment/source changes and unlinked restarts stop this
context. Clean validated scheduled rotation remains eligible. A genuine new
level goes through existing new-level confirmation, never an assumed level-up.
Missing captures still break numerical comparisons; a carried display badge
does not supply an endpoint.

Context-only points cannot complete a strict 5/10/15/30-minute window or seed its
rank. The 24-hour tracked-EXP replay explicitly retains the prior reader policy;
this milestone does not revise historical totals. Detailed diagnostic progress
and short-term presentation may use the separately labeled contextual evidence.
Raw reader outputs and original saved candidates remain accessible in Advanced.

`bounded_exp_v4` adds only a separate `symbol_hypotheses` field for a whole-field,
bounded terminal `X1` hypothesis. It requires existing decimal digits, a unique
full-field interpretation and at most four punctuation edits. No digits are
inserted/substituted, incomplete reviewed sources abstain, and a missing literal
`%` never becomes an ordinary percentage proposal. The existing v1 full-EXP
experiment and all ordinary strict parsing remain unchanged.

## Pace while readings are missing

Current pace still pools only independently eligible captured intervals in the
actual five-minute lookback: sum of their gains divided by sum of their captured
durations. No endpoint subtraction or elapsed time is added across a hole.
Unsafe numerical/level boundaries still stop pooling. Quantization hypotheses
and integer-endpoint preference are unchanged.

| Unavailable captures at 20s cadence | Presentation |
|---|---|
| 1 (20s) | Retain rate; existing no-new-gain grace period |
| 2 (40s) | Easing presentation rate, sample count/time retained |
| 5 (100s) | Continue easing using only remaining recent captured coverage |
| 10 (200s) | Still show useful dated evidence; no ETA or new gains |
| Five minutes without eligible evidence | Show **last observed Xm ago**, original historical rate and sample coverage; never current |
| Thirty minutes while capture remains running | Pause public rate; underlying historical evidence remains in Advanced |

For the synthetic 200-second constant-rate sample, 1/2/5/10 missing captures
show factors 1, 200/220, 200/280 and 100/280 respectively. Older whole intervals
expire as real time advances; these factors are presentation assumptions, not
observed zero-gain records. Historical fallback switches explicitly to the
unscaled last sampled rate. Finished/offline/stopped views retain dated history,
with no live ETA. Fresh independently eligible intervals promptly restore an
observation-based rate. None of these fallback rates qualifies for rankings.

Backend policy metadata drives the browser's aging and expiry during polling or
cached failures. Directory caching continues expiring old intervals without
requiring a new SQLite write. No separate freshness policy or statistics store
was added. A sampled-EXP window card is deferred; existing interval coverage and
dated pace communicate the available evidence without changing window semantics.

## Reproduction and verification

```powershell
.\.venv\Scripts\python -m pytest tests/test_gap_level_resilience.py tests/test_diagnostic_evidence.py tests/test_hud_resilience.py tests/test_pace_reacquisition.py tests/test_percentage_quarantine.py -q
.\.venv\Scripts\python -m pytest -q -rs
node --test tools/*.test.mjs

# New output name + unused localhost port; no Twitch request or capture.
node tools/product.browser.mjs http://127.0.0.1:18972 private/gap-level-resilience/browser-new --verify-resilience telfer1

# View persisted history read-only on a separate port; does not start capture.
.\.venv\Scripts\python -m exp_tracker.server --db private/multi-alpha/live-telfer-shiphtur.sqlite3 --diagnostic-dashboard --port 8766
Start-Process 'http://127.0.0.1:8766/stream/telfer1'
```

Private evidence is in `private/gap-level-resilience/`: frozen prefix, its SHA-256,
before/after causal results, replay scripts and isolated databases. The replay
clock and coordinator activity are explicitly simulated; saved source timestamps
are preserved. `browser-resilience-01` verifies five polled gap/recovery/historical/
restart/finish states. `browser-checkpoint13` contains the actual #13 desktop,
390px mobile, homepage and 500×160 OBS views. They show 402,319 EXP / 22.89%,
last-supported level 67, and the dated prior 10-reading rate, without an ETA.
Screenshots were inspected for readability and overflow.

Twenty-five 55-row player projections measured 13.62ms median / 15.60ms p95 on
this workstation, excluding acquisition/OCR and SQLite retrieval. This is not a
VPS capacity claim. New synthetic cases cover explicit exclusions, context expiry,
real level changes, streamed state, strict-window separation, 1/2/5/10/16 missing
attempts, historical expiry and recovery; existing rotation/restart/quarantine
regressions remain in place.

Final verification: **121 focused Python passes**, **1,447 full-suite passes in
161.68s, zero skips**, and **73 Node passes**. Both SQLite-backed Chrome runs
passed without console exceptions or external browser requests; five live DOM
update stages required no navigation. `git diff --check` passed. The first
sandboxed pytest invocation could not create temporary directories; the completed
runs used normal authorized temporary-directory/localhost access. The existing
label-tail test changes only its explicit grammar-version expectation to v4 and
asserts that the new symbol-hypothesis list stays empty for its unchanged input.

No new independent labels were obtained. Small wrong digits, correlated OCR
errors, unsupported table applicability and character identity remain unresolved.
The next useful manual trial should save crops and review weak competing levels
and `X1` source pixels, rather than accepting grammar/table agreement as proof.
