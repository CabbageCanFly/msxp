# MapleStory Classic EXP tracker

Independent, free, MIT-licensed feasibility prototype. This contains local OCR,
acquisition, SQLite tracking and a localhost OBS overlay, not a hosted service.
No accounts, cloud resources or secrets are required for offline tests.

The local **[simulated leaderboard demo](docs/demo-leaderboard.md)** is available at
`http://127.0.0.1:8765/demo/leaderboard` through the existing read-only server.
It uses fictional data, functional metric/window sorting and no real Twitch or
tracking inputs. [Latest user-reported shadow findings](docs/test-shadow-diagnostic.md)
retain the unresolved level/percentage rounding uncertainty.

The [held-out level 1–10 recording evaluation and level-up proposal](docs/level-up-evaluation.md)
documents a profile/scale incompatibility and level OCR failures on a separate
recording. Automatic level-up handling remains design-only.

The isolated [adaptive HUD experiment](docs/adaptive-ocr.md) locates fields without
supplied regions and compares scale normalization with private native profiles.
It remains an offline prototype; production recognition and tracking are unchanged.

The separate [native level-digit experiment](docs/level-digits.md) trades coverage
for safer rejection: 57 correct levels, zero incorrect accepts and 60 unavailable
on 117 saved crops, versus Tesseract's 68 / 2 / 47. It averages 2.77 ms per field,
but still requires private geometry-specific calibration and stays outside production.

The [per-character EXP experiment](docs/exp-digits.md) improves complete EXP +
percentage readings from 41 to 50 on 117 saved recording crops, and from 14 to 15
on the 17-frame Telfer trial, with zero incorrect values observed. It remains isolated;
partial field recognition is diagnostic and does not update trusted tracking state.
Its optional [grammar-assisted suffix mode](docs/exp-digits.md#grammar-assisted-suffix-follow-up)
recovers four more recording readings (54/117), with no additional incorrect outputs
or improvement on Telfer. Numerical glyphs and segmentation remain the main failures.
The [grayscale digit hybrid](docs/grayscale-ocr.md) raises recording pairs to 64/117
(59 with automatic regions), with zero incorrect outputs observed and no Telfer
regression. It remains experimental; limited 8/9 development data is a major blocker.

The [untuned cross-stream evaluation](docs/cross-stream-evaluation.md) samples
45 frames from each of two new broadcasts. Provisional visual labels expose
automatic-crop alignment failures on one layout and numerical segmentation/raster
transfer failures on the other. Human label review is still required.

The isolated [RapidOCR CPU benchmark](docs/rapidocr-benchmark.md) tests pretrained
whole-line recognition in a separate environment. It recovers useful cross-stream
numeric readings, while bracket errors and raw numerical substitutions still
prevent trusting model output directly. No production integration is included.

The [local read-only API and transparent OBS overlay](docs/overlay.md) use the
existing SQLite state. Start with an existing demo database:

```powershell
.\.venv\Scripts\python -m exp_tracker.server --db artifacts/sqlite-demo.sqlite3
# In another terminal; use this URL in an OBS Browser Source too:
Start-Process 'http://127.0.0.1:8765/overlay/demo'
```

The database must already use schema 2. The linked guide covers creating a demo,
explicitly migrating old databases, saved real OCR state and timed synthetic
updates. HTTP never creates/migrates databases or writes tracking state.
Use a **500 × 160** OBS Browser Source for the compact, transparent overlay.
It now includes [five-minute gains, thirty-minute pace and percentage ETA](docs/statistics.md),
with explicit coverage rules. Seed a fresh database using
`python tools/demo_statistics.py artifacts/statistics-preview.sqlite3` to see
all four statistics without private data or a new capture.

The [minimal SQLite tracking engine](docs/tracking.md) now persists guarded
observations, explicit character/session selection and trusted state across
worker restarts. It uses Python's built-in SQLite; no service or ORM is required.
Short OCR interruptions now preserve eligible trusted endpoint gains, with
[missing-observation metadata and hard-break safeguards](docs/accounting.md).
Run its local synthetic demo with a new ignored database path:

```powershell
.\.venv\Scripts\python tools/demo_tracking.py artifacts/sqlite-demo.sqlite3
.\.venv\Scripts\python -m exp_tracker.tracking --db artifacts/sqlite-demo.sqlite3 --channel demo state
```

Current consolidation: [green bracket OCR and capture trust rules](docs/ocr-consolidation.md).
The saved seven-second trial replays 14/17 accepted readings. Version 2 profiles
can now be trained reproducibly; version 1 remains supported. With a profile,
capture refuses to promote unverified Tesseract EXP fallbacks to trusted state.
Private calibration/profile files are intentionally absent from public Git.

The prototype includes remote Streamlink/FFmpeg frame acquisition with zero
streamer installation or OBS configuration. See [live-capture.md](docs/live-capture.md)
for current implementation, reproduction commands, measured results and platform
limitations. Install its optional dependencies with `pip install -e '.[capture]'`.

The earlier [OCR reliability results](docs/ocr-reliability.md) improved saved live
readings from **5/18 to 17/18 correct accepts**, including **9/9 on the same-session
held-out set**, with zero observed incorrect accepts. Complete OCR averages
336 ms versus 613 ms. The optional glyph profile is private calibration data;
Tesseract remains available for diagnostics. Those measurements excluded live/VPS trials.

```powershell
.\.venv\Scripts\python tools/evaluate_ocr.py private/ocr-evaluation/manifest.json --engine hybrid --profile private/ocr-evaluation/glyph-profile.json --output artifacts/ocr-hybrid.json
# Opt into calibrated EXP matching during a permitted capture trial by adding:
# --glyph-profile private/ocr-evaluation/glyph-profile.json
```

The evaluation command needs the optional capture dependencies and private local
fixtures. Matching itself only adds Pillow code. The linked results cover training,
tests, benchmarks, limitations and the proposed longer live trial.

Development and acquisition findings are in [docs/acquisition.md](docs/acquisition.md),
the proposed service design in [docs/design.md](docs/design.md), and actual local
verification in [docs/results.md](docs/results.md).

## Development setup

Python 3.11+ and Tesseract 5 with English language data are required on the
development machine or eventual OCR server. Streamers would not install Python
or Tesseract.

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
New-Item -ItemType Directory -Force artifacts | Out-Null
winget install --id UB-Mannheim.TesseractOCR -e
# If the executable is not on PATH:
$env:TESSERACT_CMD = 'C:\Program Files\Tesseract-OCR\tesseract.exe'
.\.venv\Scripts\python -m pytest --basetemp=artifacts/pytest-tmp
```

On Debian/Ubuntu:

```sh
sudo apt-get install python3-venv tesseract-ocr tesseract-ocr-eng
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
mkdir -p artifacts
.venv/bin/python -m pytest --basetemp=artifacts/pytest-tmp
```

Private screenshots in `samples/` are excluded from Git; see
[samples/README.md](samples/README.md). Sample tests skip when absent; a missing
OCR engine is a test failure when samples are present. No test downloads data.

A public checkout needs no private profile, annotations or screenshots for its
public tests. After installing Python dependencies, the core subset also needs
no Tesseract executable:

```powershell
.\.venv\Scripts\python -m pytest -q -m "not ocr and not samples" --basetemp=artifacts/pytest-public
```

[End-to-end verification and profile setup](docs/ocr-sqlite-verification.md)
documents saved-crop OCR → guarded SQLite, public-checkout checks and the current
gap-accounting tradeoff. Trusted game tracking requires your own calibrated v2
profile; no game-font profile is bundled. Synthetic font fixtures are generated
by the public tests and are not game calibrations.

## Inspect a screenshot

```powershell
.\.venv\Scripts\ms-exp.exe inspect samples/maplestory-classic-stream1.png --config configs/stream1.json --debug-dir artifacts/stream1
.\.venv\Scripts\ms-exp.exe inspect samples/maplestory-classic-stream2.png --config configs/stream2.json
# Automatic discovery currently returns correct but low-confidence candidates (exit 2):
.\.venv\Scripts\python -m exp_tracker inspect samples/maplestory-classic-stream1.png
```

Use the virtual environment's `ms-exp` executable or `python -m exp_tracker`.
Results are JSON, including parsed values, raw OCR, confidence, ROI and reasons.
Exit codes: 0 accepted reading, 2 uncertain/missing/invalid reading, 1 setup/input error.
Debug output is opt-in and contains only field crops and processed versions.
`--search x0,y0,x1,y1` restricts automatic discovery using fractions of the frame.
Explicit JSON field ROIs use the same normalized coordinates, so resizing the
whole screenshot preserves the configuration. Recalibrate when the layout changes.

Automatic recognition requires the in-game HP/MP/EXP HUD context; it does not use
standalone tracker overlays. This is a limited baseline, not universal HUD recognition.
Default discovery searches the lower 30% of the frame; use `--search 0,0,1,1`
for a HUD elsewhere, or calibrate explicit ROIs. The supplied configs contain only
sample-specific normalized regions, never expected readings. Small glyphs and
slight crop changes affect OCR substantially. Live tracking must apply the
[capture trust gate](docs/ocr-consolidation.md); an accepted diagnostic candidate
alone is insufficient. Populated low-confidence readings may contain wrong digits.

Verified original 1920x1080 samples:

| Sample | Level | EXP | Percent | Calibrated status / score | Automatic status / score |
| --- | ---: | ---: | ---: | --- | --- |
| stream1 | 60 | 71,441 | 5.90% | accepted / 0.52 | low_confidence / 0.27 |
| stream2 | 56 | 641,122 | 65.59% | accepted / 0.45 | low_confidence / 0.03 |

Scores are Tesseract engine scores, not calibrated probabilities. The default
acceptance threshold is 0.40 for this exploratory baseline; two examples do not
establish a safe production threshold. See [results.md](docs/results.md) for
resizing failures and measurement details.

```powershell
.\.venv\Scripts\python tools/evaluate_samples.py
# Optional, with Node.js 20+ already installed; no npm packages needed:
node --test tools/obs-client.test.mjs
```

The Python suite includes private-image integration tests and synthetic validation
tests. A public contributor can run `python -m pytest -m "not ocr"` without
private screenshots or an OCR engine. Optional video tests skip if FFmpeg or
capture dependencies are absent. `--basetemp` keeps temporary test files under
ignored artifacts, and is useful in restricted agent environments. Pytest clears
that designated temporary directory on the next run.

If a restricted environment cannot download packages, install dependencies from
your own terminal first. For source-only execution after dependency installation:

```powershell
$env:PYTHONPATH = 'src'
.\.venv\Scripts\python -m exp_tracker inspect samples/maplestory-classic-stream2.png --config configs/stream2.json
```

Fresh dependency downloads and Linux setup were not verified inside this managed
Windows session. Editable package installation using an existing local build
backend, both CLI entry points, and all offline tests were verified.

## Acquisition experiments

For the isolated capture → adaptive HUD → RapidOCR/visual/arithmetic-level
diagnostic runner, see [shadow-capture.md](docs/shadow-capture.md). Its JSONL stays
private and never updates trusted tracking state.

See [docs/acquisition.md](docs/acquisition.md) for commands and manual test steps.
The OBS browser harness never sends screenshots or credentials to a server.
Twitch credentials belong in environment variables on a developer/server machine,
never in the public website or an overlay URL.

Streamlink/FFmpeg remote acquisition has now passed an authorized live trial;
see [live-capture.md](docs/live-capture.md). The earlier OBS test page remains an
unverified developer experiment and is outside the current milestone.

The repository contains the initial prototype commit. This session's permissions
may still prevent staging/commits inside `.git`; no remote pushes are authorized.
See [agent-setup.md](docs/agent-setup.md) for future session permissions and manual
commit commands when managed permissions cannot be changed.
