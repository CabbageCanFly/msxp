# User-review reconciliation of OCR evidence

**The prior 8→9 error claims were stronger than the reference evidence supports.**
The 21 supplied field transcriptions remove the cadence comparison's sole mismatch,
but the disputed glyph is not independently adjudicated. Raw OCR, frozen labels,
profiles and earlier review sidecars remain unchanged. No inference was rerun.

## Provenance and private evidence

`private/ocr-label-audit/user-review.json` records all **21 explicit user
transcriptions**, including level, EXP, percentage, source image/hash and original
values. Provenance is **user and ChatGPT visual screenshot review**. It records
`user_transcribed=true`, `user_and_chatgpt_visually_reviewed=true`, and
`independently_adjudicated=false`; ordinary human review is not conflated with a
blinded independent decision about an ambiguous glyph. The sidecar does not assign
the ambiguous existing `human_verified` flag or confer recognition trust.

Only 1141s differs from the frozen cadence labels. All other supplied values agree.
`disputed-glyphs.png` shows original full-field RGB at 5× nearest-neighbor scale,
full-frame context, enlarged disputed cells and wider neighboring-pixel context.
It also shows existing, separately visually labeled 8/9 references at **654.369,
981.554 and 3517.234s**, their native widths and full numbers. Those reference
labels were transcribed from images rather than model predictions; they remain
Codex-provisional, not independently human-adjudicated. Six/seven-column windowed
and eight/nine-column large-HUD geometries must not be treated as interchangeable.
No reference was added to a classifier or selected using a new prediction.

`dispute-review.json` retains the per-case dispositions below. The prior 1146s
sidecar correction **74,069→74,059** is preserved, not rewritten.

## Disputed identities and conditional arithmetic

Reused [the existing exact-integer diagnostic](exp-consistency.md), requirement
**294,216 at level 40**, and its two separately named hypotheses. No formula or
tolerance was selected from these labels. Client formatting semantics and recording
build compatibility remain provisional; arithmetic can challenge a transcription
without authenticating the neural value.

| Frame | Frozen EXP / raw neural EXP | Evidence and disposition |
|---|---|---|
| 1141s | 73,981 / 73,991 | User now reads 73,991, agreeing with RapidOCR and saved binary selection 9. Native pixels and differently rasterized reference glyphs do not uniquely settle the identity. **Unresolved visual ambiguity**, not a demonstrated OCR substitution. |
| 1142s | 73,981 / 73,991 | Reinspected separately: similar appearance, distinct RGB pixels, same reference limitations. No new user transcription was supplied for this timestamp. **Unresolved**; do not propagate 1141's review or use repeated neural output as truth. |
| 3359s | 115,285 / 115,295 | Visible percentage is provisionally 39.19. Nearest rounding gives **39.18 for 115,285**, **39.19 for 115,295**; truncation gives 39.18 for both. **Likely annotation error conditional on the proposed display rule**, with visual identity still unadjudicated. No label override. |

For 1141/1142, both alternatives nearest-round to **25.15%**. Its compatible
integer range is **73,981–74,010 (30 values)**, so arithmetic cannot distinguish
them. Truncation predicts 25.14% for both. At 3359, nearest-rounded 39.19% admits
**115,289–115,317 (29 values)**: even rejecting 115,285 does not uniquely prove
115,295. No missing digit is inferred or candidate repaired.

The former pixel report's “confirmed by available visual evidence” judgments are
historical AI assessments, **not independent authentication**. No supported OCR
error is established by these three disputed cases alone. This does not establish
that they are all correct, or that errors elsewhere are absent.

## Cadence subset: original versus user-sidecar comparison

All rows below are **agreement / disagreement / unavailable**, using the same
saved strict complete-pair parser and unchanged Tesseract level outputs.

| Seven reviewed frames per window | Frozen pairs | User-sidecar pairs | Frozen triples | User-sidecar triples |
|---|---|---|---|---|
| Stream 2 | 6 / 0 / 1 | 6 / 0 / 1 | 5 / 0 / 2 | 5 / 0 / 2 |
| Stream 3 windowed | 5 / 1 / 1 | **6 / 0 / 1** | 5 / 1 / 1 | **6 / 0 / 1** |
| Stream 3 late | 6 / 0 / 1 | 6 / 0 / 1 | 6 / 0 / 1 | 6 / 0 / 1 |
| **21-frame subset** | **17 / 1 / 3** | **18 / 0 / 3** | **16 / 1 / 4** | **17 / 0 / 4** |

One of the revised agreements remains explicitly disputed: 1141s. Equivalently,
the pair bookkeeping is **17 ordinary agreements, one disputed agreement, three
unavailable**. It is not “18 independently verified correct readings.” The other
42 cadence frames remain numerically unreviewed. Overall **55/63 pairs, 49/63
triples**, target locations, interruptions, costs and production eligibility do
not change. At 3404s the user's complete source transcription does not rescue the
saved malformed `%1` output.

## Temporal sample: limited reconciliation, not new labels

The 1141s temporal and cadence source RGB frames are byte-identical, so the exact
timestamp's user review can be reported against both saved evaluations. No review
is extended to adjacent frames or inferred from identical recognized values.
Applying only the existing 1146 correction and the explicit new 1141 transcription:

| All 44 temporal frames | Frozen pairs | Prior 1146 sidecar | Plus user review at 1141 only |
|---|---|---|---|
| 0-pixel padding | 22 / 2 / 20 | 22 / 2 / 20 | **23 / 1 / 20** |
| 2-pixel padding | 31 / 4 / 9 | 32 / 3 / 9 | **33 / 2 / 9** |
| 0-pixel triples | 20 / 2 / 22 | 20 / 2 / 22 | **21 / 1 / 22** |
| 2-pixel triples | 29 / 4 / 11 | 30 / 3 / 11 | **31 / 2 / 11** |

Remaining two-pixel mismatches are **1142 and 3359s reference conflicts**, not two
established neural errors. At zero padding 3359 and 1146 remain malformed, so
1142 is the sole remaining complete mismatch. Do not count hypothetical corrections
at either unresolved timestamp as measured additional successes. The frozen
117-frame benchmark, 45-frame cross-stream comparisons and cached-ROI study were
not rescored or altered.

## What the binary checker actually showed

Saved binary class rankings at 1141/1142 select **9**, with distances to 8/9
**13/1 and 15/2**, respectively. RapidOCR also reads 9. The algorithms therefore
agree with each other; their conflict is with the old provisional **8 label**.
The 1141 user transcription now agrees with both. Calling this independently
repeated *wrong* recognition, or definite *false* corroboration, is unsupported
without resolving that label. At 3359 binary segmentation **fragments and abstains**;
it did not independently choose a wrong 9 there.

The [grayscale feasibility result](grayscale-numeric-verification.md) still shows
missing comparable-width references, cropped faint context and within-class raster
variation. Those limitations and the binary probe's incomplete field coverage
remain real. They justify withholding trust, not declaring a particular rejected
reference label correct. No saved ranking, mask, distance or model output changes.

## Counterexamples that remain valid

These are not overturned by uncertainty in the three disputed glyphs:

- **Real source, Stream 2 2987.260s, +4px:** neighboring HUD contamination changes
  `345[92.74%]` to complete **`2345[92.74%]`**. This is distinct from the cadence
  frame at exactly 2987s, where localization is unavailable. The actual saved
  output and source context remain preserved.
- **Controlled damaged-digit negative:** source intent 74,059 becomes complete
  **`74,050[25.17%]` at +2/+4px**, with intact-looking punctuation. Both numbers
  fit nearest-rounded 25.17% at level 40. This is a synthetic source mutation,
  not a newly verified real-stream error rate.
- **Controlled clipped-leading-digit negative:** complete **`4,059[25.17%]`**
  appears at 0/+4px. At +2px it stays malformed; variants do not choose winners.
- **Original recording, 1769.75s:** saved raw **`1,241199.82%]`** versus visually
  transcribed 99.92% retains the percentage substitution and malformed opener.
  It is a raw numerical-error example, not an additional accepted complete pair.

The [RapidOCR/context report](rapidocr-benchmark.md) and original negative artifacts
remain the evidence sources. Correcting suspected annotation errors does not make
punctuation, confidence, arithmetic or temporal repetition a numeric verifier.

## Recommendation, reproduction and checks

**Next: a small blinded human adjudication of numerical references and negative
controls before developing another verifier.** Hide predictions and prior disputed
labels, include full source context and matched native geometries, permit “unclear,”
and keep source holdouts. Use the genuine contamination and controlled corruption
cases as fixed negative controls. The current evidence does not justify training
or tuning specifically to force these three glyphs to 8, nor does it justify
trusting RapidOCR. The cadence localization/level abstentions remain measurable
coverage problems once the numerical reference basis is sound.

```powershell
# No OCR inference. Choose a NEW output directory; old reviews/results are refused.
.\.venv\Scripts\python private/ocr-label-audit/audit.py private/ocr-label-audit/repeat2
Start-Process .\private\ocr-label-audit\disputed-glyphs.png
# user-review.json and comparison-counts.json contain all values and counts.
.\.venv\Scripts\python -m pytest tests/test_exp_consistency.py tests/test_cadence_evaluation.py tests/test_temporal_ocr.py tests/test_pixel_numeric_probe.py -q -rs --basetemp private/ocr-label-audit/pytest-targeted-repeat
.\.venv\Scripts\python -m pytest -q -rs --basetemp private/ocr-label-audit/pytest-full-repeat
```

The private audit script asserts unique/exact review IDs, expected original/revised
counts, exact arithmetic, identical shared source pixels and unchanged input hashes.
A separate-directory repeat reproduces the review sidecar and counts byte-for-byte.
All **987 snapshotted prior artifacts** remain unchanged, including frozen labels,
the 1146/N08 sidecars, neural outputs, reference manifests and model weights.
Private imagery, review records and scripts remain ignored. Public changes are
this report and short supersession links in the three historical reports;
no recognizer, production code, dependency, threshold, profile or trust change.

Validation: **58 focused tests passed; full suite 634 passed, zero skipped**
(81.07s, including localhost HTTP tests). The private audit's count/arithmetic
assertions and repeat checks pass. `git diff --check` passes. No commits or pushes.
