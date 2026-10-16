# EXP accounting across brief OCR interruptions

Same-character, same-session, same-level trusted endpoints may contribute their
nondecreasing net EXP difference even when intermediate OCR attempts failed.
The existing transition validator still checks the endpoints and the **120-second
inclusive** limit between their timestamps. Recent failed attempts do not extend
that limit. The calibrated-profile/pixel trust gate is unchanged; no maximum gain
or EXP/hour limit is applied.

## Soft interruption and hard break

| Attempt/boundary | Accounting behaviour |
| --- | --- |
| Profiled OCR `unreadable`, `missing_hud`, `low_confidence`, `invalid`, or `ambiguous` | Diagnostic only; preserve trusted reading/time and allow an eligible later endpoint |
| Unverified Tesseract fallback with a configured profile | Guard changes it to low confidence; diagnostic only, never an endpoint |
| Confirmed `offline`, explicit `paused`, capture/processing failure, unknown failure or missing profile | Hard break; next compatible trusted endpoint rebaselines without gain |
| Validated numeric decrease/reset, level change or contradictory percentage | Hard break; preserve evidence and trusted values; never infer another character |
| Character/session change | Separate baseline/history, no transfer of gain |
| More than 120 seconds between trusted endpoints | New baseline, no cross-gap gain |

OCR's `ambiguous` status means uncertain recognition. It is distinct from a
numeric `ambiguous` transition between trusted candidates, such as a level change
or decrease; those are hard breaks. Capture failure is not proof of offline, but
remains a hard break under this narrowly scoped OCR-only policy.

Soft failures still report `status: paused`. `continuity_broken` distinguishes
hard pauses from temporary OCR interruptions and stays set through subsequent
failures and restarts until a compatible trusted baseline is established.
Neither kind overwrites the last trusted reading or its timestamp. A level
change/decrease still needs explicit confirmation via session end/start where
necessary; this milestone adds no automatic reset confirmation.

## Interval evidence and totals

Every newly accepted delta stores `interval_start_observation_id`, identifying
its starting trusted reading, and `missing_observations`, counting ordered OCR
rejections since that endpoint. A positive count marks a bridged interval. Start
and end timestamps remain on their observation rows. No EXP is assigned to the
missing timestamps, and rejected readings never supply numeric gain values.
Zero-delta intervals can also be marked as bridged.

State exposes `pending_missing_observations` until the next endpoint or hard
break, and `bridged_session_exp` as the portion of the session total coming from
marked intervals. All diagnostic attempts remain in history, including discarded
or interrupted intervals. Out-of-order/inactive-session attempts and duplicate
replay do not change counters, continuity or trusted state.

`observed_session_exp` keeps its public name for backward compatibility. It now
means the sum of validated endpoint **net changes**, including eligible short
OCR interruptions. It does not promise continuous observation, gross earned EXP,
or the timing of gains inside an interval. Do not derive continuously covered
rates or interpolate a graph through missing observations. The later
[window-statistics policy](statistics.md) adds endpoint-based estimates with
explicit history/coverage rules; it does not change these counted gains.
An unobserved death/reset, level change or unreported character switch that leaves
plausible endpoints cannot be excluded by HUD readings alone; explicit selection
and operator review remain necessary.

Schema 2 adds interval metadata and durable interruption state atomically.
Opening a version 1 database migrates it without rewriting observations, gains,
event IDs, selected characters or sessions. Legacy non-tracking states become
hard breaks conservatively. Existing accepted rows lack interval-start metadata;
their stored totals remain authoritative. Replaying their event IDs returns the
original outcomes, not newly calculated gains. Use a fresh database for comparisons.

## Saved-trial verification

Actual OCR → shared guard → SQLite replay of `green-test-20261015-215403`:

| Measurement | Previous policy | New policy |
| --- | ---: | ---: |
| Trusted baselines | 3 | 1 |
| Accepted deltas | 11 | 13 |
| Rejected attempts | 3 | 3 |
| `observed_session_exp` | 4,529 | **6,121** |
| Explicitly bridged EXP | 0 | **1,592** |

Two intervals recover **738** and **854** EXP, each across one rejected OCR frame.
The 6,121 total equals the difference between the first and last trusted endpoints;
no other hard boundaries occur in this saved trial. The last frame still fails:
state is paused, with one pending missing observation and trusted **60 / 879,217 /
72.66%** preserved. Restarting after every frame and replaying duplicate events
retains the same totals, 17 attempts and one session. Historical timestamps are
preserved, so the saved state is stale today.

The complete CLI workflow in [integration verification](ocr-sqlite-verification.md#run-the-complete-saved-data-pipeline-locally)
also works with schema 2: substitute a **fresh** path such as
`artifacts/accounting-bridge.sqlite3` for every occurrence of the old database
path. That path was used for this milestone's actual CLI replay; choose another
unused path for a new comparison. Captures, profiles, replay output and databases
stay in ignored directories.

Focused tests cover isolated/multiple failures, inclusive short/long gaps, zero
and large gains, hard-break persistence, decreases/levels, character/session
switches, ordering, fallback trust, replay, transaction rollback, migration and
restart. The real local-video fixture now contains two identical keyframes so
a fractional seek cannot skip its only frame; capture implementation is unchanged.

Verification on Windows: **82 targeted tests passed**, then **3 real OCR/capture
integration tests passed**. Final full suite: **276 passed, zero skipped**. SQLite
integrity and foreign-key checks passed. A second complete CLI replay returned
17 duplicates with no extra rows or gain. The old schema 1 replay database remains
untouched at 4,529 EXP. Linux execution was not checked in this milestone.

```powershell
.\.venv\Scripts\python -m pytest -q tests/test_store.py tests/test_capture_store.py tests/test_replay_capture.py tests/test_tracking_cli.py tests/test_validation.py --basetemp=artifacts/pytest-accounting-targeted
.\.venv\Scripts\python -m pytest -q --basetemp=artifacts/pytest-accounting-full
```

No OCR tuning, new footage, frontend, API, deployment or commits are included.
