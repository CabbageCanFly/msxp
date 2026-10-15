# MapleStory Classic EXP tracker

Independent, free, MIT-licensed feasibility prototype. This milestone contains
local screenshot OCR and acquisition experiments, not a hosted tracking service.
No accounts, cloud resources or secrets are required for offline tests.

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
.venv/bin/python -m pytest --basetemp=artifacts/pytest-tmp
```

Private screenshots in `samples/` are excluded from Git; see
[samples/README.md](samples/README.md). Sample tests skip when absent; a missing
OCR engine is a test failure when samples are present. No test downloads data.

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
slight crop changes affect OCR substantially. Only `status: accepted` may advance
tracking; even a populated low-confidence reading may contain incorrect digits.

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
tests. A public contributor can run `python -m pytest -m "not samples"` without
private screenshots or an OCR engine. `--basetemp` keeps temporary test files under
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

See [docs/acquisition.md](docs/acquisition.md) for commands and manual test steps.
The OBS browser harness never sends screenshots or credentials to a server.
Twitch credentials belong in environment variables on a developer/server machine,
never in the public website or an overlay URL.

No acquisition route has been live-tested. The OBS test page is a local developer
experiment, not a finished public overlay. Start its localhost server as described
in the acquisition document; no installation on a streamer's PC has been validated.

Git is initialized, but this session's permissions prevent staging/commits inside
`.git`. No commits or pushes were made. The intended local milestone commit after
review is `feat: add local HUD OCR and acquisition feasibility probes`.
See [agent-setup.md](docs/agent-setup.md) for future session permissions and manual
commit commands when managed permissions cannot be changed.
