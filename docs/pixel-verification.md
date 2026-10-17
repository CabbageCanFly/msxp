# Label audit and native-pixel verification feasibility

Later [user-review reconciliation](ocr-label-audit.md) supersedes the definitive
“false corroboration” interpretation below: the 1141/1142 glyph labels remain
disputed, and 3359s has a conditional arithmetic annotation concern. Saved binary
rankings, original comparison counts and source annotations remain unchanged.

**Correct the provisional 1146 s label in a sidecar; do not use this binary pixel
probe as a numeric verifier.** It repeats two suspected neural errors and abstains
on the third. No candidate becomes trusted and no production behavior changes.

Five timestamp seeks from `samples/sample-stream3.mp4` produced RGB pixels identical
to the frozen frames at 1141, 1142, 1145, 1146 and 3359 s. Original fields were
inspected at 10× nearest-neighbor enlargement, and disputed cells at 18× alongside
clearly readable, separately transcribed same-recording references.

| Time | Original provisional EXP | Reviewed provisional EXP | Audit disposition |
|---|---:|---:|---|
| 1141 s | 73,981 | 73,981 | Confirmed by available visual evidence; two-loop/lower-left shape supports 8 |
| 1142 s | 73,981 | 73,981 | Confirmed by available visual evidence; supports 8 |
| 1145 s | 74,059 | 74,059 | Confirmed by available visual evidence; supports 5 |
| 1146 s | 74,069 | **74,059** | Original Codex label likely incorrect; supports 5 rather than 6 |
| 3359 s | 115,285 | 115,285 | Confirmed by available visual evidence; supports 8, with degraded raster |

These are **visual review judgments, not authenticated ground truth or Codex human
verification**. Every review/reference retains `human_verified: false`. The user's
review observations agree with this reinspection. Weak strokes and resampling
remain a source of uncertainty. The 1146 cell's binary distance is also 0 to a
separately labeled 5 and 12 to the nearest 6, consistent with the visual correction.

`private/pixel-verification/annotation-review.json` records the frozen source
manifest hash, all five dispositions and the sole override `temporal/28` → 74,059.
No original annotation, prior result, model, profile or report was overwritten.

Complete EXP/percentage candidates on the **44-frame temporal sample**, counted
as provisional matches / mismatches / unavailable:

| Padding | Frozen original comparison | Reviewed sidecar comparison |
|---|---:|---:|
| 0 px | 22 / 2 / 20 | **22 / 2 / 20** |
| 2 px | 31 / 4 / 9 | **32 / 3 / 9** |

The 2-px Stream 3 windowed subset changes from 6 / 3 / 2 to 7 / 2 / 2. Its complete
triples also gain one provisional match: total 30 / 3 / 11 instead of 29 / 4 / 11.
At zero padding 1146 s is malformed, so complete counts do not change. The raw
numeric prediction at 1146 s was not an OCR digit error. The apparent 1145→1146
EXP change disappears on review, leaving 26 rather than 27 distinct provisional
visual numerical states in the temporal sample. None of this changes the frozen
117-frame benchmark or the separate 45-frame cross-stream comparisons.

Ten evaluation fields were fixed before pixel scoring: 1141, 1142, 1145, 1146,
3359 s plus controls at 1140, 1143, 1144, 3349 and 3352 s. The controls include
correct raw numbers with unavailable localization or malformed punctuation;
they are not all complete neural candidates. Forty independently visually labeled
character boxes came from seven disjoint source frames: cross-stream indices
8, 12, 15, 4, 0, 43 and temporal index 38 (3354 s). Each of the two native
geometries has references for all ten digits. Reference labels are manual Codex
transcriptions, never neural predictions. They were frozen before pixel scoring.
The 3354 s reference is adjacent development material, used for missing large-font
classes; all references share this recording. This is not independent-stream testing.

`tools/pixel_numeric_probe.py` reuses `exp_digits.columns`, its bitmap conversion,
the existing green-excess mask and `level_digits.distance`. A fixed >180 luminance
mask isolates one text band. Two colored regions locate the numeric prefix for
diagnosis only: their shapes do **not** authenticate brackets. Every white column
run is retained, including commas and unknown fragments. Native-size all-digit
comparisons allow existing ±1-pixel shifts, distance ≤3 and class margin ≥2;
these inherited bounds were fixed before measurement, not validated for this
new geometry. No resizing, fragment joining, threshold sweep or neural-guided
segmentation/reference selection occurs. Neural strings are joined only after
pixel scoring for reporting. Manual cell maps assess segmentation afterwards.

| Disputed cell | Distance to 8 | Distance to 9 | Best-class margin | Probe outcome |
|---|---:|---:|---:|---|
| 1141 s, visual 8 | 13 | 1 | 7 | Selects **9**, false corroboration of neural output |
| 1142 s, visual 8 | 15 | 2 | 7 | Selects **9**, false corroboration of neural output |
| 3359 s, visual 8 | 35 / 35 | 28 / 22 | 7 / 2 | Two fragments, both abstain; no joined-glyph result |

The first two cells are correctly isolated but their fixed masks favor the wrong
class. Nearest-neighbor RGB/mask/reference views show weak distinguishing strokes
removed by thresholding and different native horizontal rasterization: windowed
reference 8s occupy six columns, while the disputed cells span seven. This does
not prove which preprocessing change would fix them. In the large geometry an
empty interior column splits the disputed 8. A correctly read 9 in the 3349 s
control splits into the same fragment geometry, so fragmentation is not evidence
that the neural number is wrong. We did not merge it using expected digits.

Across **53 visually mapped numerical cells**: 34 matching hypotheses, two
mismatching hypotheses and 17 abstentions, including six fragmented cells.
On the seven numerically correct control fields (including 1145/1146), the
37 cells give **24 matches, zero contradictions and 13 abstentions**. Thus no
control is contradicted, but many cannot be corroborated. Every evaluation field
contains at least one unverified numeric cell; no complete EXP value is verified.
Comma fragments are retained separately and never appended as digits. These tiny,
selected, same-recording counts are diagnostic, not recognition accuracy estimates.

Segmentation plus ranking averages **4.16 ms per field** over ten fields, excluding
image/reference loading. The process peaks at **45.72 MiB sampled RSS**. The
whole measured loop, including full-frame PNG decoding, takes .343 s wall / .344 s
sampled CPU; its duration is too short for precise CPU attribution. No neural
model, new dependency, training or live footage was involved.

Private evidence under `private/pixel-verification/`: `audit-glyphs.png` compares
the five RGB cells, fixed masks and disjoint reference shapes; `evaluation-visual.png`
and `references-visual.png` preserve field-level source views. `comparison-01.png`
and `comparison-02.png` show all segmented patches, distances and margins.
`reference-glyphs.png`, `reference-annotations.json`, `results.json`, `source-audit.json`
and the correction sidecar retain detailed evidence. All remain Git-ignored.

```powershell
# Re-evaluate the fixed private inputs into a NEW directory; originals are preserved.
.\.venv\Scripts\python private/pixel-verification/evaluate.py private/pixel-verification/repeat
Start-Process .\private\pixel-verification\audit-glyphs.png
Start-Process .\private\pixel-verification\comparison-01.png
.\.venv\Scripts\python -m pytest tests/test_pixel_numeric_probe.py tests/test_exp_digits.py -q -rs --basetemp private/pixel-verification/pytest-targeted-repeat
.\.venv\Scripts\python -m pytest -q -rs --basetemp private/pixel-verification/pytest-full-repeat
```

Recommendation: **abandon this binary column matcher as a corroboration rule**.
Another algorithm can repeat the same error after information-losing preprocessing.
Before further implementation, obtain human review of the disputed RGB/reference
pairs. If continuing image-based verification, investigate a bounded grayscale or
soft-mask comparison that preserves weak strokes and explicitly handles pixel
alignment and split glyphs. More threshold relaxation, templates or temporal votes
are not justified by this result. No additional approach was tried in this task.

Validation: **40 focused tests passed; full suite 606 passed, zero skipped**
(84.36 s with local loopback access). Synthetic checks cover all-class competition,
bounded shifts, ambiguity, missing native classes, unknown ink, lost weak strokes,
retained fragments and missing anchors. A separate-directory repeat reproduces
the glyph scores and sidecar counts. No commits or pushes.
