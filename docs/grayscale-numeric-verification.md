# Grayscale numeric-verification feasibility

**Decision 2: evidence is inconclusive. Stop before building a grayscale verifier.**
Useful grayscale differences survive thresholding, but the existing references do
not establish reliable 8/9 separation across the disputed native raster positions.
This is insufficient calibration evidence, not proof that the original pixels
contain no distinguishing information or that grayscale matching cannot work.

Read-only inspection reused the frozen ten evaluation fields and forty reference
annotations from the previous [pixel experiment](pixel-verification.md). Phase 1
examined all eight labeled 8/9 reference patches and the three disputed cells at
1141, 1142 and 3359 s. Full-field context, native RGB/L pixels, 15× nearest-neighbor
views, fixed >180 masks, and two-pixel context around unchanged old cell boundaries
are retained privately. No new glyphs were calibrated. Reference/evaluation frames
remain disjoint; all material is from the same recording. Labels remain provisional
Codex transcriptions and user review observations, not authenticated ground truth.

The reference-label check supports **plausibility, not independent confirmation**:
the 654.369 s full field supports the existing `63,896` transcription; the two
adjacent glyphs have different lower-left/mid-right intensity patterns despite
looking similar when enlarged. For a cleaner comparison at the same six-column
position, reference 8 at 654.369 s versus reference 9 at 981.554 s has raw grayscale
MAE **9.17/255**, maximum difference **120**, with the four largest differences
120, 112, 75 and 61. At local row 6, the first column is 200 for that 8 versus
88 for the 9. The other two same-position 8 references give 203 and 200.
Thus some localized class evidence exists; most of the cell remains similar.
At row 5, values 157 versus 96 are both erased by >180 thresholding. This directly
demonstrates lost information, without proving it determines the disputed digits.

A single numerical **reference audit** was fixed before measurements: subtract
each cell's 10th-percentile grayscale background, clamp below zero, divide by
255 minus background, pad with zero and minimize native MAE over ±1 integer shifts.
No resizing, blur, threshold sweep, augmentations, trained parameters or acceptance
cutoffs were used. These distances describe references, not calibrated confidence.
The common canvas for each pair is max(widths)+4 by max(heights)+4.

| Reference comparison | Background-normalized native MAE |
|---|---:|
| Three windowed 8s, same position, different frames | 0.00595–0.00739 |
| Same-position windowed 8s versus 9 at 981.554 s | 0.02098–0.02224 |
| Two windowed 9s, different positions/widths | **0.07117** |
| Adjacent windowed 8/9 at 654.369 s, best one-pixel alignment | 0.07970 |
| Large 8 versus first 9, both at 3517.234 s | 0.04710 |
| Two large 9s in that same frame | **0.06039** |

The 981.554 s labeled 9 is closer to **every labeled 8** than to the other 9.
Large same-class variation also exceeds one opposing-class distance. Integer
alignment and background normalization therefore do not establish consistent
separation in this bank. Distances alone cannot prove a reference label wrong.
Position, rasterization, compression and annotation uncertainty remain confounded;
there is no clean uncompressed reference to separate these causes.

Reference coverage explains why proceeding would be premature:

- All three windowed 8s occupy the same prefix position, six columns wide. There
  is no seven-column 8 reference at the position of the 1141/1142 s disputed cells.
  Windowed 9 has one six-column and one seven-column source example.
- The large 8 and both large 9s all come from **one frame**. The disputed large
  cell is eight columns wide, whereas its sole labeled 8 reference spans nine.
  Multiple glyphs in one image do not provide independent source holdouts.
- Old threshold-derived tight boxes omit nonzero antialiasing context. Immediately
  outside windowed reference 8 boxes, intensities reach 169–175 on the left and
  152–155 on the right. Outside the disputed large cell, maxima are 157 left,
  167 right and 151 below. These exceed typical within-cell background estimates
  of about 63–73. Some faint context is excluded, but not every outside pixel can
  be attributed to this glyph. Wider boxes also approach neighboring digits.
  Blindly expanding them would introduce another contamination risk.

| Disputed cell | What survives | Feasibility disposition |
|---|---|---|
| 1141 s | Faint grayscale structure; automatic binary column segment intact | Abstain: missing comparable-position 8 references; identity unresolved |
| 1142 s | Same limitation; distinct source pixels, similar structure | Abstain; repeated appearance does not authenticate 8 or 9 |
| 3359 s | Grayscale strokes across the binary-empty column and around the old box | Abstain: automatic binary segmentation is fragmented; manual full-cell view is diagnostic only |

For example, row-6 first-column intensity is 106/104 in the 1141/1142 cells,
versus 102 in the seven-column reference labeled 9. There is no seven-column
reference labeled 8 against which to assess that cue. This cannot independently
confirm the provisional 8 labels, declare them wrong, or prove RapidOCR correct.
The existing review sidecar, including the 1146 s correction to 74,059, remains
unchanged. No new label correction or revised accuracy count is claimed.

**Phase 2 was not justified and was not run.** No evaluation glyph was classified;
there are no new numeric accepts, corroborations, control contradictions or
availability statistics. The other seven frozen fields remain unscored by a new
method. Calling them correct or unavailable would fabricate an evaluation result.
No production verifier, experimental classifier or public code/tests were added.

The next requirement is human review of the reference full fields and disputed
cells, plus at least two separately reviewed source frames per class at each
relevant native position/width, especially seven-column windowed 8 and eight-column
large 8. Keep enough original context to establish halo boundaries without the
neighbor entering the cell. Do not substitute synthetic variants for independent
sources. Only then would a small fixed grayscale comparison with source holdouts
and unknown examples be justified. More threshold tuning on these disputes is not.

Private artifacts under `private/grayscale-numeric-verification/`:
`full-context.png`, `phase1-review-01.png` through `03.png`, `phase1.json` (native
intensity grids, neighboring pixels and every reference-pair distance),
`context-audit.json` (raw difference grid), and `decision.json` (per-dispute
abstentions and reference-source limitations). The repeat additionally saves native
RGB cells. These are review diagnostics, not a new training bank or model.

```powershell
# Fixed source/reference diagnostics into a NEW directory; no OCR inference.
.\.venv\Scripts\python private/grayscale-numeric-verification/phase1_inspect.py private/grayscale-numeric-verification/repeat2
.\.venv\Scripts\python private/grayscale-numeric-verification/context_audit.py private/grayscale-numeric-verification/repeat2
.\.venv\Scripts\python private/grayscale-numeric-verification/decision.py private/grayscale-numeric-verification/repeat2
Start-Process .\private\grayscale-numeric-verification\full-context.png
Start-Process .\private\grayscale-numeric-verification\phase1-review-03.png
.\.venv\Scripts\python -m pytest tests/test_pixel_numeric_probe.py tests/test_grayscale_digits.py -q -rs --basetemp private/grayscale-numeric-verification/pytest-targeted-repeat
.\.venv\Scripts\python -m pytest -q -rs --basetemp private/grayscale-numeric-verification/pytest-full-repeat
```

The scripts refuse to replace diagnostic JSON evidence. Source images and frozen
annotations are read-only; no neural inference, model training, new dependencies,
production changes, commits or pushes. An isolated-directory repeat reproduces the
reference distances and decision byte-for-byte. This report is the only public
addition; private diagnostic scripts include identity/nonnegative-distance checks.

Validation: **30 focused tests passed; existing full suite 606 passed, zero skipped**
(80.90 s with local loopback access). All **419** snapshotted prior evidence files,
including the 1146 s review sidecar, remain byte-identical. `git diff --check` and
report whitespace checks pass; production, tools and tests have no changes.
