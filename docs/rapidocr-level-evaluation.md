# Isolated RapidOCR level recognition

The existing PP-OCRv6 recognizer is promising **with one fixed background-suppression
preprocessing method**, but native RGB is unsafe as a level candidate source on
the reviewed level-51 layout. RGB at both enlargements reads **50 on all 11 crops
labeled 51**, at high scores. The predeclared grayscale alternative reads **51 on
all 11**, without S-to-5 substitution. No method was integrated or promoted to trust.

## Fixed plan and evidence

`private/rapidocr-levels/plan.json` existed before new OCR. Selection was fixed:

- All 24 frozen two-stream attempts: A at level 63 and B at level 51, including
  the two absent level crops. References are James/ChatGPT-assisted, not independent
  expert adjudication; neighboring frames and repeated levels are correlated.
- All 24 user-transcribed blinded-review frames, six from each original/Stream 2/
  Stream 3 windowed/Stream 3 large category. Labels were previously frozen before
  their original OCR evaluation. They are now familiar development examples, not
  new unseen-stream validation or newly blinded references.
- Two **separately reported Codex-provisional** original-recording cases at 599 and
  1061.75 seconds. They are not counted as independently human-verified examples.
- Two controlled negatives: the B1 crop with its left orange tile removed at the
  orange-bounding-box midpoint, and a uniform orange blank of the same dimensions.
  Both have no complete numeric reference; no synthetic numeral was invented.

Total: **52 scheduled entries, 50 source crops, 150 neural calls** across three
fixed variants. Original RGB crops were copied byte-for-byte into the new private
directory; controls are separately marked generated images. No full-frame capture,
localization, EXP recognition, arithmetic level inference or label correction ran.
Lower reference levels present are 2, 3, 4, 6, 7, 8 and 9; levels 1/5/10 are absent.

The unchanged `adaptive_hud.level_reading` guard was rerun on all 50 images. Its
results reproduce every cached original baseline. All neutral160/180/200 and
fallback raw attempts, scores and timings are retained. Its 0.40 confidence floor
and consensus remain unchanged.

## Recognition configurations

Existing **RapidOCR 3.10.0 / ONNX Runtime 1.31.0**, CPU provider, one intra/inter-op
thread, bundled `PP-OCRv6_rec_small.onnx` (21,234,383 bytes). The engine receives
`use_det=False, use_cls=False, use_rec=True`. Detector/classifier models remain
unloaded. Downloads are explicitly refused, including dictionary fallback. Model
hashes are checked before and after; no weights or dependencies changed.

1. **RGB2:** unchanged native RGB level crop, 2× bicubic.
2. **RGB4:** same crop, 4× bicubic.
3. **Neutral4:** `invert(min(R,G,B))`, then 4× bicubic, converted to RGB for the
   same recognizer. Orange has little blue while white strokes retain intensity;
   this tests background suppression with grayscale evidence preserved. No threshold,
   new crop alignment, tile split, mask profile, contrast sweep or alternate model.

The model's existing recognizer normalizes to height 48 (`rec_img_shape=[3,48,320]`).
External 2×/4× calls are therefore correlated resamplings, not independent evidence.
Every raw string/score is written before parsing. A diagnostic number requires a
whole ASCII numeral 1–200, outer whitespace only; prefixes, internal spaces, S/I/O
confusions, zero and leading-zero strings are not repaired. No neural score cutoff
was fitted or added. Numeric candidates remain **UNVERIFIED**, not accepted levels.
Default RapidOCR direct-line output includes low-score text; this is recorded openly.

## Results by source

Cells are **correct numeric / incorrect numeric / unavailable** against the stated
references, with every scheduled entry retained. Unavailable includes nonnumeric
text, no output or missing crops. These are diagnostic candidate comparisons, not
production acceptance rates.

| Source | Count | Unchanged Tesseract guard | RGB2 | RGB4 | Neutral4 |
|---|---:|---|---|---|---|
| Reviewed A, level 63 | 12 | 8 / 0 / 4 | 8 / 0 / 4 | 8 / 0 / 4 | **9 / 0 / 3** |
| Reviewed B, level 51 | 12 | 0 / 0 / 12 | **0 / 11 / 1** | **0 / 11 / 1** | **11 / 0 / 1** |
| Human review: original recording | 6 | 4 / 0 / 2 | 3 / 0 / 3 | 3 / 0 / 3 | **5 / 0 / 1** |
| Human review: Stream 2 | 6 | 3 / 0 / 3 | 3 / 0 / 3 | 3 / 0 / 3 | **6 / 0 / 0** |
| Human review: Stream 3 windowed, level 40 | 6 | 6 / 0 / 0 | 6 / 0 / 0 | 6 / 0 / 0 | 6 / 0 / 0 |
| Human review: Stream 3 large, level 40 | 6 | 6 / 0 / 0 | 6 / 0 / 0 | 6 / 0 / 0 | 6 / 0 / 0 |
| Known cases, **Codex-provisional only** | 2 | 0 / 2 / 0 | 0 / 0 / 2 | 0 / 0 / 2 | **1 / 0 / 1** |

On available A crops, RGB has **three nonnumeric** outputs; Neutral4 has **two**.
On B, every available RGB crop gives numeric `50`, not `S1` or an abstention.
Both scales agree on all eleven wrong values. **Scale agreement fails to detect
the systematic error.** No per-frame variant is selected or combined using labels.
Neutral4 has no incorrect in-range number observed on the selected reference crops,
but this small familiar-data comparison does not establish a safe acceptance rule.

### Concrete successes, failures and scores

- B1/R014: RGB2 `50` **.99231**, RGB4 `50` **.99228**; Neutral4 `51` **.97088**.
  All B RGB wrong scores span **.95450–.99238**; correct Neutral4 51 scores span
  **.95466–.99162**. A confidence cutoff cannot separate these distributions.
- A/R010 and R020 become numeric `63` under Neutral4, while Tesseract abstains.
  However A/R024, accepted as 63 by Tesseract, becomes nonnumeric **`B3` (.76230)**.
  This is one lost baseline success, not a numeric substitution. It remains an
  abstention; no B-to-6 correction is attempted. Net A coverage gains one.
- H10 (9), H15 (8), H21 (9), H24 (6) recover under Neutral4 without numeric edits.
  H03 (9) remains nonnumeric **`回` (.40955)**. H21's correct `9` scores only
  **.27109**, reinforcing that output confidence is not a correctness guarantee.
- At 599s, reference 8 is **Codex-provisional**: current Tesseract accepts 3,
  RGB gives `回`, Neutral4 gives `8` **.48416**. At 1061.75s, provisional reference
  9 versus Tesseract 8 remains nonnumeric under all neural variants (`日` .52745
  for Neutral4). Neither value was inferred from EXP or neighboring timestamps.

### Controlled negatives

On the partial single-tile control, **all three neural variants output `0`**
(scores .82629/.82523/.46625). It is an incorrect raw numeric output for a complete
level field and is explicitly rejected as out of range; it is not counted as a
valid numeric level. The unchanged Tesseract guard returns **1** on this partial
field, showing that its consensus does not itself authenticate crop completeness.
The blank control yields empty text with score 0 under all neural variants and
Tesseract abstains. Thus this pair of limited controls introduces zero in-range
neural numeric candidates, but offers very little coverage of clipping/obstruction.
No real level-50 reference was available to test 50/51 discrimination symmetrically.

## Cost and worker reuse

Windows workstation only; image loading, preprocessing and inference are separately
recorded. Timings below exclude video capture/localization and model initialization.
Each neural variant has 50 measured calls; Tesseract has 50 full-guard calls.

| Method | Mean | Median | p95 |
|---|---:|---:|---:|
| RGB2 | 37.72ms | 46.14ms | 47.94ms |
| RGB4 | 38.32ms | 46.30ms | 48.47ms |
| Neutral4 | 38.21ms | 46.40ms | 48.46ms |
| Unchanged Tesseract guard | 439.91ms | 478.27ms | 510.60ms |

Neural loop: **5.84s wall / 5.50s process CPU** for all 150 calls plus crop I/O,
preprocessing and raw-log writes. Import **1.475s**, lazy constructor **.008s**,
cold first recognition **.215s**, second synthetic warmup **.020s**. Process RSS
before neural import **30.44 MiB**, after **121.24 MiB**, Windows peak working set
**130.95 MiB**. These are process measurements, not OS-enforced budgets.
Tesseract stage: **22.25s wall**, **21.08s sampled process-tree CPU**, sampled peak
**63.95 MiB**, 10ms sampling; short-lived process peaks can be missed.

The *same* recognizer object handled EXP-like synthetic warmup text and every level
crop, with no detector/classifier or second model process. This supports the
feasibility of a future bounded two-field request to the existing worker. The current
shadow wrapper still accepts one EXP crop and is unchanged. A warm extra level call
appears inexpensive relative to a 15-second capture cadence; starting another
process would repeat roughly 1.7s import/initialization cost and duplicate memory.
No 1-vCPU VPS, Linux, live capture, concurrency or shared-worker integration was
measured. Aggregate capture/decoding/EXP memory and CPU still need their own budget.

## Files, reproduction and validation

New public files only:

- `tools/benchmark_rapidocr_levels.py`: fixed comparison, raw JSONL, receipt checks,
  strict numeric diagnostics, correlated RGB agreement and resource/timing report.
- `tests/test_rapidocr_levels.py`: synthetic numeric/unknown/ambiguous outputs,
  exact preprocessing, no substitutions, recognition-only calls, download refusal
  and source-code/crop receipt checks.
- This report. The prior milestone's five untracked additions are preserved.

Private `private/rapidocr-levels/` contains the predeclared plan, preparation scripts,
source copies and manifest under **`prepared-02/`**, `run-01/raw.jsonl`,
`run-01/report.json`, `analysis.json`, and three **`review-*.png`** sheets showing
native source RGB enlarged by nearest-neighbor beside all three raw outputs/scores.
Frozen user references, original source crops, previous baseline reports and all
model weights remain unchanged. All 193 fingerprinted preparation inputs verify.

One initial harness launch failed **before model import/inference** because its
checksum verifier incorrectly required source-code receipts to live under private/.
The read-only verifier was corrected and tested; original `prepared/` was retained,
and `prepared-02/` froze the corrected harness. This was not a recognition/configuration
change or post-result tuning. No other recognition configuration was tried.

```powershell
# Existing prepared evidence + existing isolated environment; choose a NEW output.
.\private\rapidocr\.venv\Scripts\python tools/benchmark_rapidocr_levels.py private/rapidocr-levels/prepared-02/manifest.json --output private/rapidocr-levels/repeat-01
.\.venv\Scripts\python -m pytest tests/test_rapidocr_levels.py -q -rs
.\.venv\Scripts\python -m pytest -q -rs
```

Synthetic tests require no private data or neural package. The neural command
requires the already installed private environment/models and frozen preparation;
it refuses replacements/downloads. No new frameworks, models, training, arithmetic
rule choice, production integration, commits, pushes or deployment occurred.

## Decision

**Continue only with independent validation of the single fixed Neutral4 variant.**
It materially improves the tested level-51 and lower-level candidates without an
observed wrong in-range number in this selection. Raw RGB should not be used as a
fallback or corroborator for 51; its correlated high-confidence 50 errors are concrete.
Do not integrate or combine methods yet. Obtain newly blinded, source-matched
examples of true **50 and 51**, varied raster positions/scales, unreadable/partial
tiles and hard 9/8/6/5 confusions, retaining unknown labels and unedited raw outputs.
The familiar 11-frame level-51 episode is not eleven independent validations.
No OCR-derived level authenticates character identity or authorizes automatic level-ups.

Validation: **23 focused synthetic tests passed; 892 full-suite tests passed, zero
skipped** (78.76s). `git diff --check`, receipt revalidation and private-artifact
ignore checks pass. The three review sheets were visually inspected; detailed raw
results remain authoritative for strings/scores. The complete report is also written
to the requested local `.git/codex-output/latest.md`. No manual action is required
to reproduce the existing comparison; independent future review remains necessary
before changing level acceptance or sharing the worker with the shadow pipeline.
