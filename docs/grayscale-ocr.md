# Bounded grayscale EXP experiment

The hybrid reaches **64/117 correct complete EXP + percentage pairs**, versus
54 with grammar assistance and 50 with strict pixels. There are **zero incorrect
numeric, percentage or complete outputs** in these replays. No strict/grammar
success was lost. This is useful progress, not 80–90% coverage or independent
stream validation. Production recognition, tracking and profiles are unchanged.

## Diagnosis and chosen experiment

All 47 previously identified percentage failures were inspected in private
enlargements with native character boundaries marked. **43 have correct character
segmentation but rejected glyphs; four have merged numerical digits** (236.5,
236.75, 237 and 599 s). All 47 have a visible, separate decimal point; none is
blank or wholly occluded. Overlapping diagnostics find excessive binary distance
in 45 cases and insufficient class margins in 16. Among correctly segmented
rejections, the problematic reference characters include 31 nines and 21 eights.

This establishes the failing stage, not that every compressed glyph is uniquely
decidable. Raster/contrast variation is visible, but these crops alone cannot
separate encoder damage from rendering phase or prove that lost 8/9 strokes can
be recovered. No reference-quality uncompressed text was available. The private
`reviewed-failures.json` records each case and `failure-sheet-{0,1,2}.png` shows
the review. Expected benchmark characters are diagnostic only, never training.

`tools/grayscale_digits.py` implements one nearest-example grayscale classifier:
native padded 4-bit intensity grids, bounded integer shifts, contrast ±10% and
blur radius .35. It uses Pillow and the standard library, with no new dependencies.
It trains from the existing **66 recording and 30 CharA verified digit boxes**.
The model is approximately 68 KB and remains private because it contains glyphs.

Acceptance requires two labeled source images corroborating the class, an absolute
distance bound, and a class margin. Augmentations never count as extra sources.
Limits are calibrated once on development source holdouts and verified punctuation
negatives: native error ≤0.1276, CharA ≤0.0574, margin ≥0.06. These are normalized
feature distances, not probabilities. Source images are grouped by SHA-256;
numeric/percentage annotations of the same image cannot leak across a holdout.
The grouping correction was made after code review and all comparisons repeated.

The existing grammar/pixel reader runs first. Complete successes are retained;
otherwise the classifier can recognize or veto individual numerical characters
inside the existing segmentation search. Confident disagreements veto a candidate.
Unknown shapes, inadequate ink, merged geometry and weak margins remain rejected.
Decimals, field grammar and bracket verification stay with the existing reader.
No missing digit, gain-rate rule or cross-frame numeric inference is introduced.

## Frozen comparisons

Each cell is **correct / incorrect / unavailable**. All 117 inputs count, including
one missing HUD. Partial EXP alone is never counted as a complete observation.

| Fixed recording crops | Strict pixels | Grammar | Grayscale hybrid |
| --- | --- | --- | --- |
| Numeric EXP | 90 / 0 / 27 | 90 / 0 / 27 | **96 / 0 / 21** |
| Percentage | 60 / 0 / 57 | 64 / 0 / 53 | **68 / 0 / 49** |
| Complete EXP + percentage | 50 / 0 / 67 | 54 / 0 / 63 | **64 / 0 / 53** |
| Complete with unchanged Tesseract level helper | 35 / 0 / 82 | 39 / 0 / 78 | **46 / 0 / 71** |
| Complete with unchanged pixel level reader | 31 / 0 / 86 | 32 / 0 / 85 | **37 / 0 / 80** |

With previous **automatic HUD regions**, hybrid EXP is **84 / 0 / 33**, percentage
**63 / 0 / 54**, and pairs **59 / 0 / 58** (strict 46 pairs, grammar 50). Complete
readings with Tesseract/pixel levels are **41 / 0 / 76** and **33 / 0 / 84**.
The original **17-frame CharA trial stays 15 / 0 / 2** for EXP, percentage, pairs
and complete Tesseract-level readings. Its geometry is unsupported by the existing
recording-only pixel level profile, so that combination stays unavailable.

New complete recoveries: 239, 384.25, 384.5, 420, 452, 453, 453.5, 780, 1065 and
1380 s. For example, **57 / 15.32%** at 384.25 s and **280 / 33.33%** at 780 s
now pass. No previously correct partial fields or complete pairs were lost.
Native four-digit recording EXP remains **0/10 complete**, while six-digit CharA
values work; digit count is confounded with rendering variation, not a format cap.

Only four of the original 47 percentage failures recover. **39 segmented-glyph
failures and all four merged-digit cases remain**. At 141 s, true 8 is the nearest
gray class, but margin .015 and second-source error .152 fail the fixed limits.
At 1740 s, true 9 has margin .0015 and support error .140: guessing would sacrifice
safety. At 599 s, merged zeros remain unreadable; the known incorrect level is not
promoted into a complete reading. See private `results-examples.png` and the JSON
records for the actual character scores and stage evidence.

This is **same-recording, evaluation-informed design**, with disjoint development
timestamps, not a blind cross-stream test. The diagnosis informed the chosen
approach; frozen labels did not train it and no benchmark results tuned its
thresholds. CharA also shares calibration geometry with older development frames.

## Cost and reproduction

Windows, Python 3.14.7, Pillow 12.3; timings exclude setup, file loading, capture,
localization and level OCR. RSS includes interpreter, prepared crops and diagnostics.

| Hybrid EXP processing | Mean / p95 | Total sampled CPU | Peak RSS |
| --- | --- | --- | --- |
| Recording fixed crops, 117 | **268 / 774 ms** | 30.062 s | 36.74 MiB |
| Automatic regions, 117 | **175 / 552 ms** | 19.422 s | 38.07 MiB |
| CharA, 17 | **21 / 44 ms** | 0.344 s | 34.10 MiB |

The grammar-only recording baseline averaged 51 ms. The classifier is slower;
only incomplete first-pass frames invoke it. These are workstation measurements,
not Linux VPS or live throughput claims.

```powershell
.\.venv\Scripts\python tools/grayscale_digits.py private/exp-digits/bank.json private/numeric-classifier/model-repeat.json
.\.venv\Scripts\python tools/evaluate_exp_digits.py private/levelup-evaluation/manifest.json --engine grayscale --bank private/exp-digits/bank.json --model private/numeric-classifier/model.json --levels private/exp-digits/levels-fixed.json --output private/numeric-classifier/repeat-recording.json
.\.venv\Scripts\python tools/evaluate_exp_digits.py private/exp-digits/streamer_a-manifest.json --engine grayscale --bank private/exp-digits/bank.json --model private/numeric-classifier/model.json --levels private/exp-digits/levels-streamer_a.json --output private/numeric-classifier/repeat-streamer_a.json
# Compare with --engine valleys or grammar; use separate output files.
# Automatic regions: levels-adaptive.json plus --adaptive-results private/adaptive-ocr/benchmark-final.json.
.\.venv\Scripts\python -m pytest -q --basetemp=artifacts/pytest-gray-final -rs
```

Private evidence is under `private/numeric-classifier/`, including reviewed failure
cases, `model.json`, source-holdout calibration results, freeze/input hashes,
fixed/automatic/CharA results and the retained pre-grouping-correction run.
Calibration reproduces byte-for-byte. New installations need their own permitted
verified bank; no game-derived model or screenshot is distributed.

Validation: **490 full-suite tests passed, zero skipped**. Twenty new tests cover
native classification, uncertain 6/8 shapes, unknowns, source corroboration,
duplicate annotations of one image, deterministic training, model/bank binding,
conflicting readers and real private recoveries/rejections. No dependencies,
production source, original profiles or frozen labels changed. Nothing was committed
or pushed.

## What would move coverage toward 80–90%?

Recognition still dominates segmentation: changing only the four merged cases
cannot close the gap. The current data has only **three source frames each for
native 8 and 9**. Every native 8/9 source-holdout example abstains. CharA 4/5/6/8
each have only one source image. These development holdouts set rejection limits;
they are not independent validation results.

Keep this verifier, but prioritize data before another model search: approximately
20–30 verified examples per digit and supported raster geometry, spread over at
least ten source frames and multiple sessions, emphasizing 8/9 and thin strokes.
Preserve real grayscale context/halos and source-frame IDs. Include 50–100 verified
unknown/partial/merged/punctuation negatives per geometry. Reserve 100–200 complete
fields from a separate session for untouched evaluation. Mark genuinely ambiguous
crops unknown even when another frame reveals the true character.

That would justify testing a small discriminative grayscale/gradient classifier
that weights distinguishing strokes, rather than accumulating templates or
relaxing margins. Clean segmentation and sufficient capture detail remain necessary.
If compression destroys the distinction, better source detail or another fully
verified frame is needed; grammar cannot recover missing numbers. No evidence
here supports promising 80–90%. Full level+EXP+percentage coverage additionally
requires better level recognition: unchanged level helpers themselves cap correct
fixed-crop readings at 68/117 or 57/117 even with perfect EXP recognition.
