# Verified results and known limits

This page records the original screenshot prototype. Later remote capture results
are in [live-capture.md](live-capture.md); its recognition follow-up is in
[ocr-reliability.md](ocr-reliability.md). Acquisition boundaries and next steps
below are historical, not the current implementation status.

Measured locally on Windows, 2026-10-15, after resuming the interrupted prototype.
Python 3.14.7, Pillow 12.3.0, pytesseract 0.3.13, pytest 9.1.1 and Tesseract
5.4.0.20240606 with English data. Results may vary with engine/model versions.

## Original screenshots

| Image / mode | Extracted level | Current EXP | Percent | Status | Minimum field score |
| --- | ---: | ---: | ---: | --- | ---: |
| stream1, automatic | 60 | 71,441 | 5.90 | low_confidence | 0.27 |
| stream1, calibrated | 60 | 71,441 | 5.90 | accepted | 0.52 |
| stream2, automatic | 56 | 641,122 | 65.59 | low_confidence | 0.03 |
| stream2, calibrated | 56 | 641,122 | 65.59 | accepted | 0.45 |

Both images are 1920x1080. Values above came from the actual in-game HUD.
Automatic discovery uses nearby HP/MP/EXP/LV labels and relative layout; the
third-party overlay in stream1 is not used. Hiding the game HUD while leaving
that overlay visible returns `missing_hud`. Configs supply normalized crop
coordinates only. Expected answers occur in tests/documentation, not production
recognition logic.

EXP OCR renders the tiny thousands separator as a dot (`71.441`, `641.122`). The
parser accepts commas or dots only in valid three-digit grouping before a
bracketed percentage with two decimal places. It does not replace missing digits
or guess values from known answers. Field preprocessing enlarges glyphs,
inverts light text and tries a few thresholds. Scores are the minimum Tesseract
word score per attempt, then the best parseable attempt per field; the final
score is the lesser field score. Conflicting above-threshold values are flagged.
The 0.40 acceptance threshold is exploratory and uncalibrated.

Measured recognition time (excluding interpreter startup) was approximately
0.44–0.59 seconds for calibrated crops and 0.94–1.44 seconds for automatic search.
These are Windows developer-machine measurements, not 1 vCPU VPS benchmarks.
Changing crop edges by a few pixels changes scores materially. This is the
main remaining OCR weakness; automatic results should not advance tracking.

## Failure and variation checks

Reproduce with `python tools/evaluate_samples.py` after installation:

| Variation using the same normalized config | Observed behavior |
| --- | --- |
| stream1 resized to 1280x720 with Lanczos | unreadable EXP, no complete reading |
| stream2 resized to 1280x720 with Lanczos | incorrect level candidate **6**, correct EXP/percent, score 0; rejected as low_confidence |
| stream1 resized to 2560x1440 | correct candidate, score 0; low_confidence |
| stream2 resized to 2560x1440 | correct candidate, score 0.21; low_confidence |
| stream1 moved into a larger canvas with adjusted normalized ROIs, no resampling | accepted, correct reading |
| Actual game HUD hidden, third-party overlay retained | missing_hud |
| stream2 EXP crop blacked out | unreadable, no complete reading |
| Strong Gaussian blur | not accepted |
| Blank synthetic image | missing_hud |

Normalized calibration supports layout changes and resizing geometrically; it
does not guarantee OCR survives resampling. Missing, obscured and illegible HUDs
cannot be reliably distinguished from pixels alone. A low-confidence populated
reading is diagnostic output, never an observation to commit. Percent/EXP
consistency against a verified game EXP table remains future work. Character
identity is not recognized.

## Automated checks and commands

```powershell
.\.venv\Scripts\python -m pytest -q --basetemp=artifacts/pytest-tmp
node --test tools/obs-client.test.mjs
node --check tools/obs-probe.mjs
.\.venv\Scripts\ms-exp.exe inspect samples/maplestory-classic-stream1.png --config configs/stream1.json
.\.venv\Scripts\python -m exp_tracker inspect samples/maplestory-classic-stream2.png --config configs/stream2.json
```

At completion: **86 Python tests passed, zero skipped**, including all 13 tests
marked `samples`; **3 JavaScript mock/protocol tests passed**. Node is optional
for Python OCR. Synthetic tests cover malformed/missing digits, numeric bounds,
non-finite percentages, ROI validation, confidence conflicts, structured CLI
errors, resets, possible level-ups, explicit character switches, out-of-order
timestamps, gaps and rate bounds. The SQL design sketch executes in memory and
rejects cross-character/session ownership errors. It is not a persistence service.

An editable package was built/installed offline using an already available local
setuptools backend. Both the `ms-exp.exe` entry point and `python -m exp_tracker`
work. A build metadata compatibility issue was fixed by using the license table
form supported by the declared setuptools minimum. Fresh internet installation
could not be tested: command networking is restricted. The developer installed
Pillow, pytesseract, pytest and Tesseract manually. A restricted system temp path
also blocked pytest's initial temporary fixture; using the documented workspace
`--basetemp` fixed it. No failed/skipped OCR test is counted as a pass.

`.gitignore` was checked against `.venv`, supplied screenshots, debug artifacts,
private/data/capture directories, secrets and SQLite/database journals. The only
public file under `samples/` is its README. Git has no commits: creating the index
lock is denied by this session's protected `.git` permissions. Nothing was pushed.

## Acquisition verification boundary

| Item | Verified here | Still unverified |
| --- | --- | --- |
| Twitch official thumbnails | Current official API docs; probe argument/host validation and in-memory metrics using synthetic image; missing-token behavior | Any actual live API/CDN capture, refresh cadence, requested image quality, live OCR |
| Remote video extraction | Documentation and technical/policy assessment only | Authorized Twitch playback method, FFmpeg example execution, all resource/latency claims |
| OBS WebSocket | Official API docs; mock authentication, request correlation/errors and crop math; JS syntax | Running OBS, browser/CEF access, source screenshot freshness, hosted HTTPS/loopback, hidden-scene behavior |
| VPS | Capacity estimates and a proposed bounded worker design | Actual CPU, peak resident memory, network traffic, long-running stability |

No remote screenshot acquisition is claimed to work. Follow
[acquisition.md](acquisition.md) for executable probes and manual trials.

Current follow-up work is listed only in the README's [Next improvements](../README.md#next-improvements).
