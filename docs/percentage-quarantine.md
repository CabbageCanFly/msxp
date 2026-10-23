# Experimental percentage quarantine and EXP-loss confirmation

This read-time policy protects the real website and experimental OBS overlay.
It never changes raw SQLite payloads, trusted Store accounting, requirements,
schema, character assignment or historical source timestamps. “Accepted” below
means eligible for the **experimental public projection**, not verified OCR.

## Policy

The first same-context decrease is withheld. The public percentage, numerical EXP
and percentage-derived EXP stay at their previous event/timestamp. Pace, windows
and pace ranking become unavailable; the UI quietly says **Verifying EXP change**.

A lower baseline needs two consecutive eligible, strict, same-level captures,
both below the last accepted pre-drop percentage. The second can equal or exceed
the first lower percentage: 77.00 → 76.50 → 76.75 confirms at **76.75**. It cannot
still be falling. The captures must have distinct event IDs/timestamps and distinct
known source-frame hashes. Unknown/duplicate hashes, grammar repairs, known damaged
crop geometry, missing/ambiguous HUDs, stale captures or uncertain levels cannot
corroborate the baseline. Different hashes do **not** prove independent OCR errors.

Maximum confirmation span: **60 seconds**, explicit in the diagnostic engine
(`confirmation_seconds`, 1–60). Existing cadence/gap gates also apply: a missing
attempt or gap beyond min(120s, 1.5 × cadence) breaks confirmation. Tests cover
7/15/20/30-second captures and the 60/61-second boundary. No catch-up or interpolation.

Confirmation starts a fresh segment at the **second** lower observation. Neither
the negative boundary nor the first pending point contributes gains. Returning to
or above the pre-drop percentage instead classifies the pending candidate as a
**suspected OCR anomaly**, with a fresh baseline at recovery. Nothing is counted
across the excluded interval. This does not establish the cause of a real loss.

Expiry abandons the old confirmation opportunity; fresh eligible pairs can establish
a later baseline. A separate original verification deadline ensures repeated timed-out
candidates cannot make the old public value fresh again, even at slow cadences.
The old reading retains its original timestamp throughout. Session/character/source,
run/restart and established level changes break continuity; only the existing
validated clean-rotation exception can cross run UUIDs.

**Exceptional changes:** 10 percentage points is a deliberately conservative
diagnostic evidence threshold, not a game-mechanics rule or EXP gain/rate cap.
It separates the observed 0.02/0.54-point dips from the 50.47-point collapse, but
these examples do not calibrate its safety. Decreases at/above 10 points remain
unresolved rather than being confirmed by repeated neural text. Independent image
review or an explicit new baseline/session is needed for such a case. Large upward
changes also wait for corroboration, so an isolated upward spike cannot immediately
become the public reference. Two eligible higher captures can establish a new
higher baseline without a maximum gain cap; the suspicious interval is not counted.

Unknown-level percentages can still be displayed when otherwise usable, but a
drop from their latest public reference is withheld as **unresolved numerical
continuity**. They cannot confirm a same-level loss or contribute comparable pace.
This closes the display loophole for #17/#42 without guessing their level.

Each raw attempt has additive `percentage_review` metadata: causal status,
candidate/reference values and event IDs, eligibility reason, confirmation/verification
deadlines and any later resolution link. Earlier pending points are never promoted
retroactively. `percentage_progress` and player APIs use this same policy. Advanced
tables retain original OCR with explicit withheld/status/reason information; product
history marks excluded observations as missing rather than plotting them as accepted.

## Saved evidence

Native RGB crops were enlarged with nearest-neighbor scaling. The displaced fields
start around y1043 and end y1058/1059, cutting lower glyph strokes; good neighbors
start around y1049 and retain pixels through y1063/1064.

| Sequence | Evidence | Public behavior |
|---|---|---|
| #9–11: 74.76 / 74.22 / 74.81 | User reviewed #10 as approximately 74.77; native pixels agree provisionally. Crop displacement plus OCR substitution. | Hold 74.76 at #10; resume at #11's 74.81, new baseline. |
| #16–18: 74.94 / 74.92 / 75.00 | #17 is displaced; AI visual inspection suggests possibly 74.97, not human-verified. | Hold 74.94 at #17; display resumes at #18. Level continuity remains unavailable. |
| #41–43: 75.68 / 25.21 / 75.74 | #42 is displaced; AI visual inspection suggests about 75.71, not authenticated truth. | Hold 75.68 at #42; display resumes at #43. No inferred loss or boundary gain. |

The full **55-attempt** replay newly excludes those **three syntactically usable
readings**. Thirteen other attempts were already malformed/unavailable. Thus 39
attempts provide public updates, three numerical candidates are withheld, and all
55 raw attempts remain inspectable. No real loss is claimed as confirmed in this run.

Same-level eligible segment lengths change from `3,3,3,1,1,4` to `3,2,3,1,1,4`.
Neither policy produces an eligible five-minute window. The shorter segment excludes
the false rebound; coverage has **not** improved artificially. Most later percentages
still lack qualifying level context, so display recovery is not pace recovery.
CharB: **41/41** public readings retained, same 40-point eligible segment after
the level-confirmation baseline, zero new quarantine or geometry changes.

## Narrow crop correction

A shared pure geometry helper recognizes a tall, upward-contaminated HP token only
when bare MP/EXP labels agree vertically, LV has its expected relative position,
and EXP height is compatible with the existing HUD scale. It chooses EXP's supported
vertical origin without moving horizontal bounds, widening tolerances, changing OCR,
or choosing between competing HUDs. The known clipped-bottom pattern is also flagged
at read time, so it cannot corroborate a loss.

Nine saved geometries change: **10,12,17,27,31,37,42,46,53**. For #10 the padded box
changes `(1023,1043)–(1122,1058)` → `(1023,1049)–(1122,1063)`; #17/#42 receive the
same vertical correction while keeping their original X bounds. Some horizontal
misalignment remains. All 116 available temporal/cross-stream control anchor sets
(39+36+41) are unchanged. This is saved-anchor replay, not a new locator benchmark.
Original full frames are absent: lost pixels cannot be recropped from the saved
fields. **No new real OCR recovery or accuracy improvement is claimed.**

## Validation and use

Synthetic tests cover small/large true or false changes, identical/different lower
values, gradual recovery, malformed/correlated frames, expiry, direction reversals,
uncertain levels, character/session/source changes, missing/stale/future attempts,
SQLite/API consistency, restart and no trusted/raw mutation. Browser checks use
actual SQLite writes and HTTP responses: eligible pace disappears during quarantine,
the old overlay value stays put, the second lower capture changes the baseline,
and subsequent movement is measured only from that new baseline. No navigation.
The labeled synthetic browser controls are functionality tests, not real loss labels.
Final checks: **1,225 Python tests passed, zero skipped; 55 Node tests passed;
actual Chrome/SQLite checks and `git diff --check` passed**. Test-owned processes
shut down cleanly.

Private evidence: `private/percentage-quarantine/{sequences.png,visual-review.json,
audit-final.json,saved-review-final.sqlite3,browser-complete/}`. All 193 recorded
source input hashes remain unchanged. The review database contains all 96 saved
attempts across both streams and zero trusted observations. Public tests use synthetic
data. No new Twitch connection, model training, threshold search or OCR inference.

```powershell
.\.venv\Scripts\python -m exp_tracker.server --db private/percentage-quarantine/saved-review-final.sqlite3 --diagnostic-dashboard
# In another terminal:
Start-Process 'http://127.0.0.1:8765/stream/streamer_a'
Start-Process 'http://127.0.0.1:8765/dashboard/streamer_a'
# Self-contained SQLite/browser regression: use NEW output directory and free port.
node tools/product.browser.mjs http://127.0.0.1:8787 private/percentage-quarantine/browser-new --verify-quarantine streamer_a
.\.venv\Scripts\python -m pytest tests/test_percentage_quarantine.py tests/test_adaptive_hud.py -q
node --test tools/*.test.mjs
.\.venv\Scripts\python -m pytest -q
```

Changed files: new `src/exp_tracker/{diagnostic_percentage,diagnostic_geometry}.py`;
existing `diagnostic_progress.py`, `diagnostics.py`, `product.py`, `shadow_view.py`;
`web/{product,shadow}.js`; `tools/adaptive_hud.py`, `product_updates_fixture.py`,
`product.browser.mjs`, `product.test.mjs`; new `tests/test_percentage_quarantine.py`;
updated `test_adaptive_hud.py` and `test_diagnostic_progress.py`; this note and README.

Limits: two strict clean frames may still share an unknown systematic numeric error;
small upward errors remain possible. The 10-point threshold is uncalibrated and may
hold real large losses. Read-time state is reproducible from the bounded selected
history, not a durable authenticated verdict; losses outside that context are unknown.
Next check is a separately authorized, crop-preserving trial with human review of
pending/confirmed events, particularly genuine loss and repeated damaged fields.
