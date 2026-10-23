# Green bracket OCR consolidation

Follow-up: the [SQLite engine](tracking.md) now consumes this same trust gate and
the existing transition validator. Matching thresholds/profile behavior are
unchanged; capture without database mode retains its prior compatibility.

This supersedes the capture trust guidance in the earlier
[OCR reliability experiment](ocr-reliability.md). The existing green-excess
matcher and safety patch were present in commits `169bc35` and `f5a8d0f` when
this work started; the working tree was clean. Their matching/state behavior
is preserved. No new livestream connection or threshold tuning was performed.

## Preserved behavior and trust boundary

Version 2 profiles use `bracket_mode: "green_excess"`. A bracket pixel passes
when `2*G - R - B >= 2*threshold`, suppressing bright gray background artifacts.
With the current profile's threshold 11, the existing adaptive bracket checks
are **7, 11, 15**, with at most four changed bracket pixels. Digits stay at their
single calibrated threshold (175 here), at most three changed pixels and a
two-pixel margin over the next digit. Other punctuation is unchanged. Unknown
digits, missing punctuation and conflicting complete matches remain rejections.

The existing capture guard runs **before** transition validation. With a glyph
profile supplied, an accepted OCR candidate must have matching parsed pixel
evidence for both EXP and percentage. A Tesseract-only fallback is downgraded to
`low_confidence`, score zero, reason `unverified_tesseract_exp`. Its candidate
remains available for diagnostics but cannot replace the trusted observation.

Unreadable/missing/ambiguous/invalid results, capture errors and processing errors
leave trusted state unchanged. An OCR-accepted candidate whose transition is
ambiguous or rejected also leaves state unchanged. Only transition `baseline`
or `accepted` advances it. Thus `record.status == "accepted"` alone is insufficient
for ingestion. Last trusted reading and timestamp survive failures; this is not
a claim that elapsed failure time represents covered tracking time.

No EXP gain-rate limit is active. The validator's existing optional rate argument
is unchanged; capture does not supply it. Regression tests allow a large verified
gain and check that earlier failures did not become the baseline. Level changes,
resets and character ambiguity retain their existing handling.

**Legacy boundary:** `recognize()` and capture without a profile can still accept
Tesseract candidates for backward compatibility. These are not glyph-verified.
The future SQLite engine must require a calibrated profile and consume the
post-guard result plus its transition, rather than trust raw OCR status or the
presence of a populated reading.

## Reproducible calibration and a new installation

No font assets, private screenshots, calibration images or experimental profiles
ship in Git. Install the normal README dependencies and Tesseract, then:

1. Collect permitted **RGB** EXP crops at the intended native capture scale.
   Retain color; grayscale crops cannot calibrate green-excess brackets.
2. Manually label development cells, including all digits and `, [ . % ]`.
   Reserve another session for evaluation. Never use OCR guesses as labels.
3. Put crops and annotation JSON under `private/`. Cell height includes vertical
   padding; widths include trailing advances. `origin` is the top-left of the
   first annotated cell within the crop. `text` can cover a complete line or a
   selected glyph/substring, so bracket examples need not add numeric variants.
4. Run the trainer and evaluate the generated model before trusting live output.

Illustrative annotation (replace text/geometry with your actual manual labels;
the numbers below are not a fixture or a model):

```json
{
  "version": 2,
  "bracket_mode": "green_excess",
  "height": 9,
  "digit_threshold": 175,
  "punctuation_threshold": 11,
  "samples": [{
    "id": "owned-development-1",
    "split": "development",
    "image": "exp-crop.png",
    "text": "123,456,789[0.12%]",
    "origin": [1, 1],
    "widths": {
      "0": 6, "1": 6, "2": 6, "3": 6, "4": 6,
      "5": 6, "6": 6, "7": 6, "8": 6, "9": 6,
      ",": 5, "[": 6, ".": 4, "%": 8, "]": 5
    }
  }]
}
```

Paths resolve relative to the annotation file. Training refuses held-out samples,
incomplete alphabets and incompatible version/mask combinations. Existing
annotations without a version still generate version 1/max-channel profiles.
Version 2 must explicitly select green-excess; numeric masks stay unchanged.

```powershell
.\.venv\Scripts\python tools/train_glyph_profile.py private/calibration/training.json private/calibration/glyph-profile.json
# Offline screenshot inspection; capture's trust guard is a separate step.
.\.venv\Scripts\python -m exp_tracker inspect private/calibration/frame.png --config configs/streamer-live.json --glyph-profile private/calibration/glyph-profile.json
```

Choose/calibrate ROIs for the actual layout; the channel-specific example config
is not universal. A differently scaled font needs its own calibration.

On this workstation, `private/ocr-evaluation/training-green.json` reconstructs
the working experimental model from annotated source crops: numeric/white
punctuation cells from the original three development examples and bracket
cells from `live-validation-20261015-203121`, samples 0–2. All glyph masks and
settings match `glyph-profile-green-experimental.json`; template ordering and
provenance differ. Repeated generation of the new file is byte-identical:

```powershell
.\.venv\Scripts\python tools/train_glyph_profile.py private/ocr-evaluation/training-green.json private/ocr-evaluation/glyph-profile-green-generated.json
```

The existing experimental profile was not overwritten. Its SHA-256 remains
`a3fc6d2d196e4c37137febb4607442c53642d592e0b3aad0701eb8defaf48d29`.
Training materials, generated profiles and captures remain ignored and untracked.
No redistribution clearance is assumed.

## Regression evidence and SQLite readiness

Final suite: **209 passed, zero skipped**, including **71 private sample tests**.
`pip check` and `git diff --check` passed. Reproduce with:

```powershell
.\.venv\Scripts\python -m pytest -q --basetemp=artifacts/pytest-consolidation
```

The pre-change suite passed **172 tests, zero skips**. Added coverage checks both
profile versions, deterministic generation, each adaptive bracket threshold,
strict/ambiguous digits, missing and severely degraded brackets, fallback evidence
mismatch, and preservation of trusted state through failures and ambiguous resets.

Offline replay of `green-test-20261015-215403` preserves **14 accepted / 17 frames**
at the recorded seven-second interval. Accepted values match the saved trial;
visual consistency was reported by the user, not newly established by replay.
Frames 3 and 16 remain EXP failures; frame 6 remains a level failure. Frame 6 has
no saved EXP crop because recognition stopped at level. This is a regression set,
not an untouched accuracy evaluation or a new live trial.

Ready to implement the local SQLite engine using this explicit trust boundary.
Next scope: transactional observations/state, explicit character selection,
separate histories, pause/gap segments and restart recovery. Keep uncertain
attempts auditable while preserving the last trusted observation. No database
implementation was started here. Wider font/scale validation and Linux resource
testing remain separate work; 14/17 is not evidence of production-wide accuracy.
