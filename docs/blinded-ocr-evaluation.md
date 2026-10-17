# Frozen 24-frame human-review evaluation

**23/24 complete EXP/percentage pairs match the frozen user readings; 18/24
complete triples match. No completed incorrect pair, triple or level was observed.**
Five level abstentions are the largest measured availability loss. One malformed
closing bracket prevents another pair. All candidates remain experimental and
untrusted; this small same-recording test does not establish numerical safety.

## References frozen before inference

The exact input is
`samples/blinded-review/review-human-manual-transcribe-converted.txt`. Its first
and second passes each have four six-row sheets: H01–H06, H07–H12, H13–H18,
H19–H24. All eight supplied PNG sheets are byte-identical to their corresponding
prepared sheets in `private/blinded-review/`. The IDs/order, 24 answers per pass,
numeric grammar, ranges and agreement of repeated level/EXP values were checked
before any Tesseract or RapidOCR call. There was no unclear mapping or value to repair.

`private/blinded-ocr-evaluation/user-review.json` retains the two original answer
lines and line numbers per ID, exact two-decimal percentage strings, level/EXP,
source-frame hashes, original text hash, original blank-manifest hash and UTC
freeze time. Its SHA-256, also saved in `user-review.sha256`, is:

```text
d4737541d8dad3073a5229aaf840ef096c6b20450d49176116b7d9191a243972
```

Provenance is **explicit user transcription with subsequent ChatGPT visual review**,
as supplied by the user, **not independent blinded expert adjudication**. The text
separates the passes; actual completion order, timing and prior percentage exposure
were not independently verified. The reused benchmark's default `human_verified:
false` field is not used in scoring; the annotation sidecar explicitly records
`user_transcribed:true` and `independently_adjudicated:false`.

The blank review manifest, original text and all reference answers remain unchanged.
A derived evaluation manifest adapts IDs to `blinded/Hxx` for the existing tools;
it never becomes the annotation authority. No model result, EXP arithmetic or
post-inference image judgment changes a frozen answer.

## Unchanged evaluation path

All 24 previously frozen source frames are retained, including failures. No video
extraction, frame replacement, new calibration or new model was needed.

- Fresh `adaptive_hud.locate` on each full RGB frame, then unchanged experimental
  `level_reading` from its unique level region.
- Every returned candidate passed the existing **both-field-center** main-HUD
  diagnostic against the review bounds. No wrong-target candidate entered numeric
  scoring. Manual bounds score localization only; they are not locator fallbacks.
- Existing RapidOCR **3.10.0 / ONNX Runtime 1.31.0**, bundled PP-OCRv6 small line
  model, CPU provider and one inference thread. Original source-frame automatic
  EXP region, fixed **+2 native pixels** on each side, then **2× bicubic** enlargement.
- Raw text and scores written to JSONL before the existing diagnostic parsing.
  Complete pairs require unchanged `complete_pair` / `parse_exp` syntax. No suffix
  rescue, numeric reconstruction, per-frame variant selection, glyph fallback,
  temporal voting, cached localization or arithmetic-based selection.

All regions were found, so no optional manual-region recognition control was run.
The failure sheet shows the original manual review pixels for context only.

## Results: all scheduled frames count

Each cell is **correct / incorrect / unavailable against the frozen user answers**.
Counts describe this reference comparison, not independently adjudicated truth.

| Category | Main HUD | Parsed EXP | Parsed percentage | Level | Strict complete pair | Strict complete triple |
|---|---|---|---|---|---|---|
| Original, 6 frames | 6 / 0 / 0 | 6 / 0 / 0 | 6 / 0 / 0 | 4 / 0 / 2 | 6 / 0 / 0 | 4 / 0 / 2 |
| Stream 2, 6 | 6 / 0 / 0 | 6 / 0 / 0 | 6 / 0 / 0 | 3 / 0 / 3 | 6 / 0 / 0 | 3 / 0 / 3 |
| Stream 3 windowed, 6 | 6 / 0 / 0 | 6 / 0 / 0 | 6 / 0 / 0 | 6 / 0 / 0 | 6 / 0 / 0 | 6 / 0 / 0 |
| Stream 3 large, 6 | 6 / 0 / 0 | 6 / 0 / 0 | 5 / 0 / 1 | 6 / 0 / 0 | 5 / 0 / 1 | 5 / 0 / 1 |
| **All 24** | **24 / 0 / 0** | **24 / 0 / 0** | **23 / 0 / 1** | **19 / 0 / 5** | **23 / 0 / 1** | **18 / 0 / 6** |

Localization breakdown: **24 main, zero missing, zero ambiguous, zero secondary
HUD selections, zero other wrong targets**. This is an evaluator geometric check
plus source-image inspection, not proof of robust global HUD disambiguation or
selected-character identity. All six Stream 2 main HUDs were selected here.

**Raw numeric-token scoring, separately:** EXP and percentage tokens match **6/6
in each category, 24/24 total**, with zero token mismatches or unavailable tokens.
H07 contains the correct percentage token but malformed suffix; the existing
structured percentage parser returns unavailable, explaining its table entry.
Token agreement never rescues the complete-pair result. Zero complete incorrect
pairs/triples does not turn missing readings into correct ones.

H18 raw `100.938[34.31%]` uses a dot thousands separator instead of the user's
comma. The existing strict parser already allows this notation and yields the
same integer 100,938. It is a semantic numerical match, not an exact literal-text
match or a new correction. There are **22 literal canonical text matches**, one
valid separator variant and one malformed string.

## Every observed failure / partial result

`private/blinded-ocr-evaluation/failures.png` shows all six affected fields with
full-frame context, current automatic EXP crop, original manual review pixels,
automatic level crop, raw result, score and frozen reference. Source inspection
identified no need to dispute a user value; no reference was revised.

| ID / time | Frozen level | Failure and saved level evidence | Raw neural string | Score |
|---|---:|---|---|---:|
| H03 / original 1327s | 9 | Level unavailable: only one sufficiently confident output, **5 at .52** | `533[42.91%]` | .99051 |
| H07 / Stream 3 large 3458s | 40 | Closing `]` predicted as `1`; no complete pair | `117,571[39.96%1` | .94489 |
| H10 / Stream 2 5525s | 9 | Level unavailable: all attempts empty | `305[24.56%]` | .98522 |
| H15 / Stream 2 3625s | 8 | Level unavailable: **8 at .95 vs 3 at .63** | `175[20.83%]` | .99080 |
| H21 / original 1609s | 9 | Level unavailable: 5 at .52; alternate 9 has zero confidence | `936[75.36%]` | .93925 |
| H24 / Stream 2 2675s | 6 | Level unavailable: **5 at .75 vs 6 at .96** | `173[46.51%]` | .95817 |

The level tiles remain visible in their automatic regions. The reader rejects
unsupported or contradictory raster interpretations rather than accepting the
listed wrong internal hypotheses. There are **no accepted incorrect levels**.
We did not rerun those crops with new thresholds or manual-region level OCR, so
the relative contribution of crop context versus Tesseract preprocessing remains
unmeasured. These are level-recognition/consensus failures, not missing HUDs.

At H07 the source and automatic crop visibly retain the closing bracket. This
supports a punctuation recognition failure, with no detected numeric substitution,
missing digit or obvious field clipping. No independent delimiter verifier was
used. The correct partial tokens `117,571` / `39.96` remain diagnostic only.

All 24 raw strings/scores, expected references, levels, target categories, parsed
tokens and field/pair/triple results are in `per-frame.csv` and
`comparison-summary.json`. Correct complete-pair raw scores span **.93925–.99633**;
incorrect complete candidates: **none observed**, so there is no incorrect-candidate
score distribution to estimate. H07's malformed score **.94489** falls within the
correct-candidate range. No confidence cutoff or numerical guarantee follows.

## Limits, comparison and next priority

These are new timestamps from the **same three recordings and familiar raster
geometries** used in development. There are only six frames per category, fixed
temporal exclusions and no deliberate difficulty balance. The densely sampled
large-HUD region is not an independent stream holdout. Sparse timestamps do not
measure continuous reliability or level-transition readiness. The human references
are stronger evidence than prior Codex-only labels, but their review procedure is
not independently authenticated.

The [label audit](ocr-label-audit.md) already limits the disputed 1141/1142/3359
8/9 claims; those frames are excluded here and were not reconsidered. This run
does not establish that RapidOCR never substitutes digits. Preserved
[context-experiment counterexamples](rapidocr-benchmark.md) still include:

- Real +4px neighboring-label contamination, `345` → complete `2345[92.74%]`.
- Controlled fragmented digit at +2px, `74,059` → complete `74,050[25.17%]`.
- Controlled clipping, complete `4,059[25.17%]` at 0/+4px.
- The original raw 99.92→99.82 percentage substitution with malformed opener.

None was regenerated, altered, added to these 24 denominators, or used to select
a result. Production calibrated pixel evidence and guarded ingestion remain
required; **zero production-trusted observations** result from this experiment.

**Next engineering priority: improve isolated scale-aware level recognition,
while retaining conservative rejection and frozen negative controls.** Five of
six incomplete triples lose only the level. Both visible correct and wrong raw
level hypotheses can be confident; loosening consensus is not justified. Keep
the EXP pipeline experimental and test any future level change on frozen source
holdouts, including known incorrect-level cases. No implementation starts here.

## Cost, reproduction and preservation

Windows workstation measurements, not VPS or remote-capture performance:

- Fresh localization mean/median/p95 **1.405 / .960 / 3.494s** per frame.
- Level reading mean/median/p95 **434 / 506 / 579ms**.
- Combined localization/level stage: **45.40s wall**, **42.02s sampled process-tree
  CPU**, **187.02 MiB** peak sampled tree RSS. PNG I/O is included in stage wall.
- RapidOCR inference mean/median/p95 **22.27 / 22.36 / 25.06ms** over 24 crops;
  process peak RSS **159.96 MiB**, measured loop CPU **1.25s**, including crop loading.
  Import **.749s**, constructor **.008s**, cold first call **.105s** are separate.

The private `freeze.py` refuses to replace an annotation sidecar and imports no OCR
engine. `analyze.py` refuses an existing summary and checks saved variants, source
IDs/timestamps, frozen values and input receipts. To reproduce into a NEW directory:

```powershell
.\.venv\Scripts\python private/blinded-ocr-evaluation/freeze.py private/blinded-ocr-evaluation/repeat
.\.venv\Scripts\python tools/evaluate_cadence.py localize --manifest private/blinded-ocr-evaluation/repeat/manifest.json --output private/blinded-ocr-evaluation/repeat/localization.json
.\private\rapidocr\.venv\Scripts\python tools/benchmark_rapidocr.py private/blinded-ocr-evaluation/repeat/manifest.json --plan private/blinded-ocr-evaluation/repeat/plan.json --all --automatic-results private/blinded-ocr-evaluation/repeat/localization.json --padding 2 --output private/blinded-ocr-evaluation/repeat/rapidocr-pad2.json
.\.venv\Scripts\python private/blinded-ocr-evaluation/analyze.py private/blinded-ocr-evaluation/repeat
Start-Process .\private\blinded-ocr-evaluation\failures.png
.\.venv\Scripts\python -m pytest tests/test_blinded_answers.py tests/test_cadence_evaluation.py tests/test_rapidocr_benchmark.py -q -rs --basetemp private/blinded-ocr-evaluation/pytest-targeted-repeat
.\.venv\Scripts\python -m pytest -q -rs --basetemp private/blinded-ocr-evaluation/pytest-full-repeat
```

If a future rerun returns a wrong target, preserve it as a localization failure
and exclude that region from intended-character recognition; do not use reference
numbers to choose another candidate. This initial run has no such cases.

Input receipts cover **1,151 files**: earlier benchmarks, model weights, review
materials, original user text, source frames and frozen new reference artifacts.
All remain byte-identical. Private results and screenshots remain ignored. Public
additions are this report, the small strict answer-format parser and its synthetic
tests; existing recognition and production modules are unchanged. No commits/pushes.

Validation: **67 focused synthetic tests passed; full suite 647 passed, zero skipped**
(79.97s, including local HTTP tests). The parser rejects missing/reordered answers,
malformed numeric grammar, out-of-range values and disagreements between passes.
`git diff --check`, frozen hashes and eight-sheet copy checks pass. No environmental
test limitation remains for this run.
