# Blinded multi-stream shadow review

`tools/shadow_review.py` is an isolated **prepare → freeze → evaluate** workflow.
It never runs OCR, chooses a rounding rule or ingests tracking data. Review material,
references and reports must stay under ignored `private/` or `artifacts/` directories.
Only Pillow and existing pure parsing helpers are used; no new dependencies/models.

## 1. The maintainer captures two new permitted streams

Choose two NEW consenting livestreams and new filenames. Streamer permission is
required; the platform restrictions in [shadow-capture.md](shadow-capture.md) still
apply. Do not open raw logs, shadow viewer, earlier predictions or arithmetic before
review. Ideally have someone who has not seen those outputs do the transcription.

```powershell
.\.venv\Scripts\python tools/shadow_capture.py --channel CHANNEL_A --authorized --interval 15 --count 12 --save-crops --output private/reliability/captures/stream-a.jsonl
.\.venv\Scripts\python tools/shadow_capture.py --channel CHANNEL_B --authorized --interval 15 --count 12 --save-crops --output private/reliability/captures/stream-b.jsonl
```

Replace the channel placeholders only after obtaining permission for both trials.
Each takes roughly three minutes, depending on acquisition/processing. The existing
runner/configuration remains unchanged: RapidOCR direct line, CPU, 2×/+2 pixels,
strict complete-pair parser and separate visual/arithmetic evidence. No streamer
installation/OBS configuration. Do not retry or replace individual failed attempts.

Prepare accepts **completed runs**, including capture/OCR/localization failures.
Interrupted/unfinished logs, missing scheduled records, duplicate indices, malformed
JSONL or a non-newline tail stop preparation; they are never silently trimmed.
Keep such evidence; use another distinctly named complete run rather than repairing
the log. This small first workflow does not score partially completed trials.

## 2. Prepare anonymous review sheets

```powershell
.\.venv\Scripts\python tools/shadow_review.py prepare --run private/reliability/captures/stream-a.jsonl private/reliability/captures/stream-a --run private/reliability/captures/stream-b.jsonl private/reliability/captures/stream-b --output private/reliability/review-01 --seed 17
```

The two crop directories are the runner's existing automatic layout. **Every attempt
is retained**; absent crops get visible placeholders. Sorting by SHA-256 of the fixed
seed/stream ordinal/attempt index assigns anonymous R001… IDs, independently of
predictions and confidence. Twenty-four attempts produce four six-row sheets.
Reusing the same ordered runs/seed reproduces order and sheet pixels; changing the
repository's absolute location does not change the order. Output directories must
be new. Inputs, pixels and software are fingerprinted before any reference scoring.

Give the reviewer **only `private/reliability/review-01/review/`**:

- `sheet-01.png`… show native RGB fields and nearest-neighbor enlargements, no OCR
  predictions, inferred levels, arithmetic, channel, timestamps or chronological IDs.
- `pixels/` contains anonymous native crops, with image metadata stripped and RGB
  pixels preserved. Wide/tall fields can be opened here without clipping.
- `answers-template.csv`, `provenance-template.json`, `README.txt` are blank forms.

Keep `manifest.json`, its mapping, original capture logs and prior reports away from
the initial reviewer. The screenshot's actual percentage is visible for transcription;
this is prediction-blind review, **not** a masked-percentage two-pass protocol. Do not
use the EXP table or neighboring values to resolve ambiguous digits.

## 3. Submit explicit human references and freeze

Copy the forms, preserving the originals:

```powershell
Copy-Item private/reliability/review-01/review/answers-template.csv private/reliability/review-01/completed.csv
Copy-Item private/reliability/review-01/review/provenance-template.json private/reliability/review-01/provenance.json
```

In `completed.csv`, retain all IDs/order/columns and fill EXP, percentage and level:

```csv
id,exp,percentage,level,note
R001,1234,12.34,40,example syntax only; not a supplied reference
R002,ambiguous,unknown,40,uncertain last EXP digit
```

The examples are format instructions, not labels for any sheet. Use a text editor;
plain integer EXP avoids CSV comma quoting. Percentage needs two decimals **without
the `%` sign**. `unknown` and `ambiguous` are distinct, accepted values for each field.
Empty means unfinished and prevents freezing. A field without a saved crop cannot
be labeled known in this crop-only review. Never use zero for unreadable EXP.

Complete provenance: reviewer, method (`human_transcription`,
`human_chatgpt_assisted`, or `independent_human_review`), and explicit JSON booleans
for saved-prediction exposure, arithmetic/neighbor assistance, prior-material exposure
and independent review. An independent-review claim requires a named second reviewer.
Record ChatGPT assistance/exposure honestly; self-reported independence is not
authenticated. Disagreements should remain ambiguous pending separate adjudication.
No labels are filled from OCR, AI image interpretation or the EXP table by this tool.

```powershell
.\.venv\Scripts\python tools/shadow_review.py freeze --prepared private/reliability/review-01 --answers private/reliability/review-01/completed.csv --provenance private/reliability/review-01/provenance.json
```

This validates every field and all input receipts, then creates `references.json`
and `references.sha256` **before evaluation**. It preserves raw submission text,
file hashes, uncertainty, provenance and UTC freeze time; refuses overwrites.
Manifest, source logs, crop files, prepared review material and scoring software
must remain unchanged. These hashes detect accidental changes; they are not signed
authentication. The OCR outputs necessarily existed at capture time: freezing
precedes comparison, not original inference, and cannot prove the reviewer was blind.

## 4. Evaluate saved predictions, afterward

```powershell
.\.venv\Scripts\python tools/shadow_review.py evaluate --prepared private/reliability/review-01 --output private/reliability/review-01/evaluation.json
```

The command verifies seals/receipts before interpreting predictions. It reuses the
unchanged strict parser; no punctuation rescue, missing-digit inference, frame
filtering, model rerun or expected-answer selection. Original raw text/scores and
saved candidates stay in the private report. A saved-candidate/parser discrepancy
is reported, never silently corrected. Complete triples use the saved **visual level**;
arithmetic is separate and never supplies a missing visual level.

Each S01/S02 stream is reported separately, mapped to its source log in the manifest:

- Recorded capture availability, locator missing/ambiguous/not-run/unique status,
  missing crops, capture-local freshness and fresh complete-pair availability.
- Exact parsed EXP, displayed percentage, visual level, strict pair and visual-level
  triple **agreement / disagreement / unavailable / unknown_truth**. These four
  counts sum to **every selected attempt** for each metric. `known_truth` and
  `output_available` are separate coverage counts. Unknown references are never
  counted as correct or as proven OCR errors; abstention counts are independent.
- Complete wrong-candidate IDs, raw malformed outputs, component disagreements and
  both saved arithmetic sets. A known-component contradiction flags a wrong complete
  candidate even if another reference field is unknown; the full metric remains
  `unknown_truth`, making the partial evidence explicit.
- Nearest-half-up and truncation outcomes separately: unavailable pair/evidence,
  incompatible, ambiguous, unique agreement/disagreement, or unknown truth. Set
  membership does not authenticate EXP digits or select client display semantics.
- Exact duplicate full-frame hashes and duplicate EXP RGB pixels, preserving every
  repeat in the denominator. Equal HUD crops can mean unchanged gameplay rather than
  a frozen capture. Different pixels/nearby captures are still correlated; absence of
  duplicates does not make 12 adjacent frames independent trials. Timeline timestamps
  are retained in capture order; sparse short runs do not prove continuous reliability.

**Main-character identity and competing-HUD correctness remain unverified** on all
crop-only examples, even with unique reported localization and exact numerical
agreement. No main-HUD correctness rate or streamer authentication is claimed.
Reports always distinguish reviewer claims from independently authenticated evidence.
Zero observed errors on a tiny familiar layout does not establish numerical safety.

## Current mechanics check, not a new benchmark

No fresh multi-stream captures or human labels were supplied/run in this task.
The existing **test-shadow** trial was prepared with `--practice` into
`private/reliability/practice-test-shadow/`. Its two sheets were generated; one
was visually checked for anonymous, readable native/enlarged pixels. All twelve
practice references explicitly say **unknown**, with `practice_mechanics` provenance,
no human-transcription claim, and `practice_only:true`. Freeze/evaluate completed;
all twelve pair references remain unscored (`unknown_truth`). No accuracy result,
new blind holdout or independent validation was fabricated. Original inputs remain
unchanged. Actual new-stream evaluation waits for the maintainer's captures and submissions.

```powershell
.\.venv\Scripts\python -m pytest tests/test_shadow_review.py -q -rs --basetemp artifacts/pytest-shadow-review-focused-repeat
.\.venv\Scripts\python -m pytest -q -rs --basetemp artifacts/pytest-shadow-review-full-repeat
```

The public tool/tests contain no game imagery or annotations. All generated private
material stays ignored. Production recognition, shadow capture, website, overlay,
SQLite trust, requirements table and rounding policy are unchanged. No commits/pushes.

Validation: **25 focused tests passed; full suite 788 passed, zero skipped**
(80.86s). Compilation, `git diff --check` and ignored-artifact checks passed.
Practice receipts still match all 54 prepared inputs; no new accuracy figures.
