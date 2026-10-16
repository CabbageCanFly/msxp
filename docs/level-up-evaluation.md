# Held-out recording evaluation and proposed level-up handling

Evaluation only, 2026-10-16. **Automatic level-up handling is not implemented.**
Production OCR, thresholds, profiles, accounting, schema, statistics and overlay
are unchanged. The worktree was clean at the start. No new footage was collected.

## Recording, selection and ground truth

The private `samples/sample-stream.mp4` is 1,820.01 seconds long, 1920 × 1080,
60 fps, H.264. FFmpeg decoded local frames; this did not exercise Twitch capture.
Visual scans located all nine transitions from level 1 through level 10. The
frozen evaluation set has **117 unique timestamps**: 34 spread examples,
54 one-second boundary examples and 29 subsecond boundary examples. Overlapping
selections count once. It covers zero EXP, one through four EXP digits, thousands
commas, one/two percentage integer digits, and the 9→10 level digit-width change.
It is a purposive, temporally correlated sample, not a random accuracy estimate
or a simulated 10–30-second capture schedule.

Labels were visually transcribed from nearest-neighbour enlarged HUD crops
**before any OCR ran on the recording**. They are independent of OCR output but
have one visual reviewer (Codex), not a second human annotation pass. There are
116 visually readable HUDs and one entirely black/missing HUD. No values were
inferred for the missing frame. Contact sheets, full annotations and scripts
remain under ignored `private/levelup-evaluation/`.

A separate visual name-panel check is consistent across all ten levels and on
both sides of the black frame (`visual-identity-check.png`). That is manual
evaluation context, not an implemented character-identity detector.

Recording-specific field boxes were selected visually before evaluation:
level `(435,975,467,1005)`, EXP `(985,974,1120,992)` in the native frame. These
coordinates are evaluation calibration, not a new production layout assumption.
Existing `tools/evaluate_ocr.py:load_crops` reconstructs the disjoint fields at
their original resolution with exact normalized ROIs. Nothing rescales the
glyphs before recognition; enlargement is only for manual inspection.

Frozen inputs:

- Manifest: `private/levelup-evaluation/manifest.json`, SHA-256
  `5ad4f858f4bcd8e5b3846704f88bda091c93a78e9b8bf16a0e710fa697dc842c`.
- Existing v2 profile: `private/ocr-evaluation/glyph-profile-green-experimental.json`,
  SHA-256 `a3fc6d2d196e4c37137febb4607442c53642d592e0b3aad0701eb8defaf48d29`.
- Existing default pixel scale `1.0`, confidence floor `0.4` and all matcher
  tolerances unchanged. No glyph training or threshold search was performed.

## Baseline results

The following four columns are mutually exclusive. **Rejected complete** means
a full numeric candidate exists but confidence, bounds or the EXP trust guard
rejects it. **Incomplete** means OCR returns no complete triple; it does not
mean the HUD was necessarily unreadable to a person. Acceptance is measured
**after `guard_unverified_exp`**, not just raw `recognize()` status.

| Visually labeled level | Frames | Accepted correct | Accepted incorrect | Rejected complete | Incomplete |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 7 | 0 | 0 | 6 | 1 |
| 2 | 12 | 0 | 0 | 3 | 9 |
| 3 | 10 | 0 | 0 | 5 | 5 |
| 4 | 13 | 0 | 0 | 6 | 7 |
| 5 | 9 | 0 | 0 | 0 | 9 |
| 6 | 10 | 0 | 0 | 0 | 10 |
| 7 | 14 | 0 | 0 | 6 | 8 |
| 8 | 13 | 0 | 0 | 4 | 9 |
| 9 | 25 | 0 | 0 | 2 | 23 |
| 10 | 3 | 0 | 0 | 2 | 1 |
| Missing HUD | 1 | 0 | 0 | 0 | 1 |
| **Total** | **117** | **0** | **0** | **34** | **83** |

Thus all 117 attempts are nonaccepted; the 83 incomplete readings comprise
82 visually readable HUDs and the one missing HUD. There are no accepted
observations from which to estimate acceptance precision for this recording.

The 34 complete rejections comprise 27 low-confidence candidates, six invalid
percentages and one raw acceptance vetoed by the pixel trust guard. Of those
34 raw complete candidates, 19 match all three visual labels and 15 do not;
none may update trusted state. There are 49 EXP parse failures and 34 early level
parse failures. EXP-only matching was also probed independently on every crop,
so an early level failure does not hide whether the profile would match EXP.

### Calibration incompatibility versus recognition failures

**EXP profile compatibility:** all 116 readable EXP crops fail complete pixel
matching. The saved profile's example digit has a 5×7 lit-pixel bounding box;
the recording's manually identified same digit is 6×9 at the same threshold.
The private comparison image shows different raster geometry. This is evidence
of a native-scale/profile mismatch, not evidence that a properly calibrated
profile cannot recognize this HUD.

The frozen EXP crop also includes an adjacent label fragment and a lower HUD
line. A separate, post-baseline crop-only diagnostic removed those margins
without resampling or changing any settings: still zero complete pixel matches
on all 117 crops. This diagnostic does not replace the frozen baseline and
does not isolate font scaling from every compression/font-rendering effect.

**Level recognition:** among the 116 readable frames, 74 have only the correct
level among variants scoring at least 0.4, six have only low-confidence parses,
33 have no level parse, and three have confidently wrong level variants. In
particular, two consecutive level-9 frames are read as level 5 at score 0.75.
Level recognition uses Tesseract, not the EXP glyph profile. These are real
level-recognition failures at the frozen ROI; calibrating EXP alone cannot fix
them. Tesseract scores and agreement between preprocessing variants are not
independent proof of correctness.

**EXP/percentage/brackets:** Tesseract fallback examples lose or confuse brackets,
merge EXP with percentage digits, produce out-of-range percentages or substitute
digits. Twenty-eight frames contain an exact EXP/percentage parse in at least
one fallback attempt, but that is diagnostic evidence, not pixel verification.
This evaluation cannot attribute every incomplete pixel match to an individual
bracket/digit because the existing profile is incompatible as a whole. No
obstruction is visible in the 116 labeled readable crops; the black HUD is a
separate missing-image case, not a font failure.

### Local examples and reproducibility

All paths below are private and ignored, including the diagnostic scripts:

- `private/levelup-evaluation/boundary-subsecond-1.png` through `-9.png`:
  visually checked frames immediately adjacent to each transition.
- `private/levelup-evaluation/profile-compatibility.png` and
  `geometry-diagnostic.json`: previous working raster versus this recording.
- `evaluation-crops/recording-crops/0000/`: correct raw numeric candidate at
  0 seconds, rejected on confidence and without pixel evidence.
- `evaluation-crops/recording-crops/236500/`: first new-level boundary example
  where every level preprocessing variant returns no parse.
- `evaluation-crops/recording-crops/454000/`: black/missing HUD; no numeric label.
- `evaluation-crops/recording-crops/1061750/`: wrong level variant immediately
  after a level-up. `1064000/` and `1065000/` show the repeated wrong level.
- `evaluation-crops/recording-crops/1800000/`: correct raw acceptance, then
  `unverified_tesseract_exp`; correct digits alone do not establish trust.
- `results.json`: every raw attempt, guarded result, independent EXP probe and
  elapsed time. `summary.json` uses the four output categories above; the older
  `category` field inside raw results instead separates readable-label rejections
  from the one unlabeled/missing HUD. Do not confuse the two definitions.

Run from the repository root, with the existing local profile and extracted
private fixtures in place:

```powershell
.\.venv\Scripts\python private/levelup-evaluation/evaluate.py
.\.venv\Scripts\python private/levelup-evaluation/summarize.py
```

These scripts are local research artifacts, not dependencies of a public checkout.
The initial labeling/extraction scripts are also saved privately; the freeze step
refuses to overwrite its manifest. Do not regenerate labels after inspecting OCR.
Mean measured full-recognizer time was **0.479 s/frame** on this Windows machine;
this excludes decoding, separate diagnostic probes and SQLite. It is not a VPS
CPU/memory benchmark or an acquisition-latency measurement.

## Current tracking behaviour, verified

Actual guarded recording results were ingested into a **new private diagnostic
database**, with an explicitly selected evaluation character and one session.
Restart after each of 117 attempts plus replay of all 117 stable event IDs leaves
117 rejected rows, zero trusted readings, zero gain and one session. Integrity
and foreign-key checks pass. Existing history was not modified. The recording's
timestamps are offsets from a fixed evaluation origin, not claimed wall-clock
Twitch timestamps.

A positive control using the existing saved `green-test-20261015-215403` crops
and the same unchanged profile still yields **14/17 guarded accepts**, three
unreadable. This is the previous compatible session, not new held-out evidence.

Pure `validate_transition` probes using the manually labeled endpoints return
`level_change_requires_confirmation` for all nine changes and all nine subsequent
new-level readings against the unchanged old baseline. These manual-reference
probes were **not** fabricated into pixel evidence or stored as OCR observations.
The current Store consequently needs explicit session end/start to replace an
old-level baseline after a real level change. A restart does not clear that guard.

## Recommended policy — design only

Use an opt-in **pending level-up → confirmation → new-level baseline** path in
the existing validator/Store. Do not make a second numeric validator.

1. Require a selected character, its unchanged active session, a compatible
   calibrated EXP profile and a previously trusted reading. Only a candidate
   exactly **one level higher** is eligible. Decreases and jumps of two or more
   remain review cases. Do not require near-100% old EXP, near-zero new EXP or a
   decrease in either numeric EXP or percentage: observed transitions include
   substantial new-level progression, and both values can increase across a
   legitimate level boundary.
2. Keep the first candidate diagnostic/pending; preserve the old trusted value
   and timestamp. Its EXP/percentage must already pass the existing pixel guard
   and bounds. For a cautious first implementation, require at least two current
   level preprocessing variants to agree confidently, without a contradictory
   confident variant. This corroboration is weaker than a calibrated independent
   level recognizer; validate it on compatible held-out footage before enabling
   automation. Current evidence is insufficient to enable it safely by default.
3. Require a second distinct, newer qualifying capture at the same proposed
   level, at least **five seconds** later, with the same stronger level evidence.
   This is a proposed anti-repeat confirmation delay, not a measured safe cutoff.
   Apply the existing same-level validator between the two candidates, including
   nondecreasing EXP/percentage and no rate cap. Unchanged values are legitimate.
   Two adjacent video frames or a duplicate event are not two confirmations.
   A new event ID alone also cannot prove source freshness; use decoded-source
   progression when available and disclose the limitation of receipt timestamps.
4. Both candidates and the final confirmation must remain within **120 seconds
   of the old trusted reading**. Soft unreadable/unverified attempts may intervene
   but neither confirm nor extend the deadline. Any offline/capture hard failure,
   explicit pause, source/profile/config change, character/session change, larger
   level jump or candidate decrease cancels automatic confirmation. A conflicting
   candidate requires review; do not silently replace pending evidence until
   something happens to fit. A return to the old level cancels the proposal;
   only an otherwise-valid compatible reading can rebaseline, and decreases still
   need review. Do not bridge over the suspected boundary.
5. On confirmation, atomically promote **the confirming reading** as a baseline
   at the new level, preserving character and session. Do not retroactively turn
   the first candidate into trusted history. No gain or interval link crosses
   the boundary; future same-level readings resume ordinary accounting and
   eligible short-OCR-gap bridging. A hard gap requires review/reconfirmation,
   not permission to clear a level mismatch just because enough time elapsed.
6. Retain the known session total. Mark a durable boundary with **unknown
   cross-level EXP**, referencing the old endpoint, pending candidate and
   confirmation. Do not add the new current EXP, subtract endpoints at different
   levels, estimate the old-level tail or claim the uncounted amount is zero.
   The first-candidate-to-confirmation progress is also uncounted by this simple
   policy. Session EXP remains known validated net gains, not a complete earned
   total; expose an additive incompleteness marker in a later implementation.
7. End the statistics chain at the boundary. Existing policy naturally needs
   five minutes of new-level history for recent gains and thirty minutes for
   pace/ETA; keep them unavailable during warmup. Do not reuse old-level percentage
   pace. Fast early levels may never show ETA under this policy; no statistics
   change is proposed in this task.

No individual level segment in this recording lasts thirty minutes, so current
pace/ETA would remain unavailable even with perfect OCR. That is an intentional
history requirement, not a defect to fix in this milestone.

Explicit selection remains an operator assertion of identity. A silent switch to
another character one level higher can produce identical evidence; EXP/level
alone cannot distinguish it. Keep manual switching mandatory and explain this
limitation when opting in. Repeated preprocessing/capture errors can also remain
correlated. A calibrated level verifier or another trustworthy identity signal
would provide stronger protection; neither is implemented here.

Persist pending evidence rather than keeping it only in worker memory. A narrow
follow-up can add a pending-observation reference and append-only boundary evidence
with a small versioned migration. Recheck selected character/session, old trusted
pointer, candidate order/deadline and profile context inside `BEGIN IMMEDIATE`.
Stable event IDs must be checked before confirmation counting. Duplicate replay
and old events cannot advance, cancel or resurrect a proposal. On restart restore
the pending reference and re-evaluate expiry against the actual new event time;
never start a new session or weaken trust to make recovery work.

## Narrow next task and checks

1. First establish a compatible EXP calibration and reliable level evidence on
   separate development material, then re-evaluate the frozen set without
   relabeling it. An independent second recording is preferable to neighboring
   frames from this same session. Keep this set out of glyph training. Human
   review of the contact sheets/labels would strengthen the current ground truth.
2. Implement only the opt-in single-level pending/confirmation path above using
   the existing guard and validator, minimal durable pending/boundary metadata,
   and confirming-frame baselines. Leave the default conservative path available.
3. Add deterministic tests for single/multiple level-ups, quest-like overshoot,
   increasing EXP and percentage across the boundary, repeated wrong digits,
   insufficient level corroboration, old-level returns, candidate decreases,
   rejected/intervening frames, five-second delay, inclusive 120-second deadline,
   hard gaps/offline, profile/source changes, character/session switches, huge
   valid gains, event ordering/duplicates, rollback and restart during pending
   and after confirmation. Verify unknown boundary gain and new statistics warmup.
4. Replay compatible real OCR through the actual guard/Store with restarts;
   confirm preserved selection/session and no cross-level gain. Keep manually
   labeled validator tests distinct from real OCR integration results.

This task's existing full suite: **333 passed, zero skipped**, including private
sample tests. Local evaluation scripts also assert frozen counts, profile hash,
trust safety, replay idempotence, session recovery and database integrity.
No automatic-level code or new production tests were added. Linux execution and
a compatible calibrated run on this recording remain unverified.

```powershell
.\.venv\Scripts\python -m pytest -q --basetemp=artifacts/pytest-levelup-evaluation -rs
```
