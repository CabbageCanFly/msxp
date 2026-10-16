# Live OCR reliability milestone

Measured on Windows 11, Python 3.14.7, Pillow 12.3.0 and Tesseract
5.4.0.20240606, 2026-10-15. This milestone replays existing private captures;
it makes no new Twitch connections and does not change acquisition strategy.

## Accuracy

The optional calibrated EXP glyph matcher improves correct accepted complete
readings from **5/18 (27.8%) to 17/18 (94.4%)**, with **zero incorrect accepts**
in either run. The first held-out run accepted **9/9 correctly**. This justifies
a longer supervised trial, not a production accuracy claim.

| Unique examples | Baseline correct / wrong / rejected | Hybrid correct / wrong / rejected |
| --- | --- | --- |
| Development, 9 | 2 / 0 / 7 | 8 / 0 / 1 |
| Held out, 9 | 3 / 0 / 6 | 9 / 0 / 0 |
| Total, 18 | 5 / 0 / 13 | 17 / 0 / 1 |

All three repeated passes gave these counts. Repetitions measure timing, not
additional accuracy examples. Both original calibrated screenshots still accept
**60 / 71,441 / 5.90%** and **56 / 641,122 / 65.59%**, including with the optional
profile loaded. Default Tesseract behavior remains unchanged.

The rejected example is `periodic-10/0`, visually level 60, EXP 398,273, 32.92%.
Its degraded percent glyph exceeds the cell error limit; fallback also rejects it.
Other known failures are resolved, including 395,936 previously proposed as
398,936 and 399,353 previously proposed as 393,353.

## Reference and license

[mapleland-exp-tracker-web](https://github.com/myungwoo/mapleland-exp-tracker-web)
captures a user-selected screen/window in the browser, not a remote Twitch stream.
Its [EXP recognizer](https://github.com/myungwoo/mapleland-exp-tracker-web/blob/main/lib/pixelRecognizer.ts)
builds a brightness/color mask, removes UI components, estimates scale/baseline,
segments columns and compares glyphs with score/margin checks. Its
[font definitions](https://github.com/myungwoo/mapleland-exp-tracker-web/blob/main/lib/pixelFont.ts)
use small bitmap cells with special punctuation advances. Level uses a separate
font. These sources were actually inspected; their clean-pixel guarantees do not
transfer to compressed video.

The project is [MIT licensed](https://github.com/myungwoo/mapleland-exp-tracker-web/blob/main/LICENSE),
copyright 2025 Myungwoo Chun. Acknowledge it as the reference for glyph matching,
color preservation and rejecting unknown digits. No upstream code, font tables
or images were copied. If incorporated later, retain the applicable copyright
and MIT notice. Our templates derive from permitted private crops and stay
private; distribution rights have not been assessed. Public tests use an
independently constructed seven-segment font.

## Implementation and bounds

`glyphs.py` loads a small profile covering digits and `, [ . % ]`. Training
extracts manually annotated cells from development crops, not complete readings
or screen coordinates. The first three development crops cover the full alphabet.

Connected-component/empty-column experiments found compression bridges adjacent
digits. Instead, the matcher enumerates valid text layouts and compares cells
with calibrated advances. EXP has 1–12 digits; percent has one/two integer digits.
Values are not prescribed.
It searches translations within a bounded calibrated ROI. Colored brackets use
maximum RGB brightness; white digits and other punctuation use grayscale. No
OpenCV, NumPy, ML framework or new runtime dependency was added.

A complete match requires observed brackets, decimal point, percent symbol and
two decimal places. Each cell permits at most three changed pixels, and a digit
needs a two-pixel distance margin over the next class. Unknown slots cannot be
dropped; bright prefix/suffix text cannot be ignored. Conflicting complete matches
veto acceptance. Scores are geometric agreement, not calibrated probabilities or
a guarantee against compression changing one glyph into another. Tesseract's
existing confidence threshold was not lowered.

`recognize(..., glyph_profile=profile)` uses matching EXP when it passes, otherwise
falls back to the existing EXP Tesseract attempts. Ambiguous pixel results are
rejected rather than rescued. Level retains its three Tesseract passes: the live
dataset is all level 60 and cannot establish a full level font. Omitting the
profile preserves the old path. Both screenshot/capture CLIs take `--glyph-profile`.

Native scale is the default; `--pixel-scale 2` permits explicit integer scaling.
Multiple flags try multiple scales and reject conflicting text. Synthetic
translation/integer-scale regressions pass; different real UI scales, fractional
resizing and 720p reliability remain unverified. Automatic HUD discovery is
unchanged. Pixels clipped outside a ROI cannot be recovered: a wholly clipped
leading character can be indistinguishable from a shorter number. Recalibrate
rather than infer digits.

## Private evaluation protocol

`private/ocr-evaluation/manifest.json` contains manually inspected level/EXP/percent
for the 18 wider-crop live captures. Color crops and enlargements were reviewed,
including every level crop. Two initial development labels were corrected by
larger visual inspection before freezing the matcher.

The split was fixed before matcher development: nine periodic captures for
development, nine persistent captures held out. `training.json` lists three
development examples, glyph advances and cell origins. `glyph-profile.json`
records training IDs and an annotation hash. `freeze.json` records profile,
manifest and matcher hashes before the first held-out run, saved separately in
`artifacts/ocr-heldout-first.json`. Only loader validation changed afterward;
matching rules/profile were not tuned on held-out results.

This is a **same-session holdout**, not an independent stream evaluation. Some
crops had been inspected in the earlier capture milestone. Temporal correlation,
one font/level and the tiny dataset limit generalization and false-accept
estimates. Keep the profile opt-in. Additional repeats do not address this.

Reproduce after `pip install -e '.[dev,capture]'` and installing Tesseract:

```powershell
# Private annotations/profile exist on this workstation, not in public Git.
.\.venv\Scripts\python tools/train_glyph_profile.py private/ocr-evaluation/training.json private/ocr-evaluation/glyph-profile.json
.\.venv\Scripts\python tools/evaluate_ocr.py private/ocr-evaluation/manifest.json --engine baseline --repeat 3 --output artifacts/ocr-baseline.json
.\.venv\Scripts\python tools/evaluate_ocr.py private/ocr-evaluation/manifest.json --engine hybrid --profile private/ocr-evaluation/glyph-profile.json --repeat 3 --output artifacts/ocr-hybrid.json
.\.venv\Scripts\python tools/evaluate_ocr.py private/ocr-evaluation/manifest.json --engine pixel-exp --profile private/ocr-evaluation/glyph-profile.json --repeat 20 --output artifacts/ocr-pixel-exp.json
.\.venv\Scripts\python -m pytest -q --basetemp=artifacts/pytest-tmp
```

Run benchmarks sequentially. On Linux use `.venv/bin/python` (not tested here).
Trainer/evaluator module docstrings specify their JSON formats. Training rejects
held-out flags and incomplete alphabets. Public contributors need their own
permitted crops/calibration to reproduce the live improvement; private fixture
tests explicitly skip when absent. Profiles, labels, contact sheets and detailed
benchmark outputs stay under ignored `private/` or `artifacts/`.

Final validation: **167 Python tests passed, zero skipped**, including **53 tests
marked `samples`**. New tests cover pixel matching, missing punctuation, ambiguous
digits, unreadable slots, translations, integer resampling, held-out training
rejection, profile round trips and private live regressions. Existing capture,
parsing, transition and original screenshot tests pass. Both CLI entry points,
`pip check`, compilation and `git diff --check` also passed. A real local generated
video capture with the profile loaded returned the correct synthetic reading
(37 / 123,456 / 12.34%) through Tesseract fallback. This checks integration, not
new Twitch acquisition. Git ignore checks exclude all private artifacts; nothing
was pushed or published. Local commit creation remains unavailable because this
session has read-only access to protected `.git` metadata.

## Recognition cost, separate from capture

Three passes over 18 full readings (54 attempts), and 20 EXP-only passes (360).
Images were prepared before timing. The OCR timer excludes Streamlink, FFmpeg,
disk loading, network, interpreter startup and full-frame decode. Memory is
sampled aggregate working set, including Python, small prepared crops and
Tesseract. `OMP_THREAD_LIMIT=1` bounds Tesseract.

| Path | Mean wall / attempt | P95 wall | Sampled CPU / attempt | Peak tree RSS |
| --- | ---: | ---: | ---: | ---: |
| Tesseract complete reading | 613 ms | 681 ms | 594 ms | 63.8 MiB |
| Hybrid complete reading | 336 ms | 583 ms | 324 ms | 63.5 MiB |
| Pixel EXP only, excludes level | 1.85 ms | 2.42 ms | 1.87 ms | 31.3 MiB |

Full recognition is about **45% faster**. Hybrid P95 includes the rejected crop's
fallback. CPU is sampled every 10 ms; short-lived work/peaks can be missed and
monitor overhead is included. `python_cpu_seconds` excludes Tesseract and is not
total OCR CPU. Capture's older 250 ms monitor is not directly comparable. These
are developer-machine results, not Linux VPS measurements or total pipeline costs.

Using 0.324 CPU-seconds/reading, recognition-only planning estimates are:

| Interval | One channel, one-core average | Five channels, one-core average |
| --- | ---: | ---: |
| 30 seconds | 1.1% | 5.4% |
| 15 seconds | 2.2% | 10.8% |
| 10 seconds | 3.2% | 16.2% |

Acquisition is unchanged. Its earlier complete tree peaked near 200 MiB; five
copies still leave no comfortable margin in 1 GB. A future worker should stagger
jobs and bound concurrency. At roughly 3.8 MB relayed per periodic attempt,
15-second sampling implies ~2 Mbps/channel, 10 seconds ~3 Mbps/channel, before
overhead/prefetch. Multiply by five for five channels. These extrapolations are
not newly measured pipeline totals.

## Responsiveness and next trial

Recognition leaves ample headroom for 10–15-second sampling on this machine.
The earlier short live trial captured all scheduled 10/15-second frames; the new
combination has **not** run live. Faster OCR does not reduce connection/network
cost, establish broadcast age or ensure a changed reading. A webpage can refresh
every five seconds while showing the same old observation. Display last newly
accepted observation time separately. The reference app's capture cadence is unknown.

Next: a supervised 15–30-minute authorized trial, starting at 15 seconds. Include
stable play, HUD obstruction and a scene switch. Audit accepted readings and
measure coverage, delivery age, full CPU/RAM/bandwidth and reconnects. Keep the
native rendition/profile and save only opt-in field crops:

```powershell
# Only while the already authorized channel is live and testing is permitted.
.\.venv\Scripts\python -m exp_tracker.capture --channel telfer1 --mode periodic --interval 15 --count 61 --config configs/telfer1-live.json --glyph-profile private/ocr-evaluation/glyph-profile.json --debug-dir artifacts/live-hybrid-15 > artifacts/live-hybrid-15.jsonl
```

This is about 15 minutes. No trial was started during this offline milestone.
Platform permission remains unresolved: streamer consent/playback success do
not establish public-service authorization. See [platform boundary](live-capture.md#platform-boundary).
No OBS changes are needed.

For an independent evaluation, collect 30–50 consented level/EXP crop pairs from
another session, with different backgrounds, EXP lengths, UI scales and missing
HUD periods. Reserve an untouched session before tuning. To replace level
Tesseract, supply level crops covering digits 0–9. No additional labels or
installations block this milestone. Linux and long-running stability remain untested.
