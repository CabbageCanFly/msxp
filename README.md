# MapleStory Classic EXP tracker

Independent, free, MIT-licensed feasibility prototype: local OCR, Streamlink/FFmpeg
acquisition, SQLite tracking, a read-only player website and a localhost OBS overlay.
It is not a hosted service. Offline tests need no accounts, cloud resources or secrets.

## Setup

Python 3.11+ and Tesseract 5 with English language data are required on the
development machine or OCR server. Streamers never install Python or Tesseract.

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

Live capture needs the optional dependencies: `pip install -e '.[capture]'`.
For source-only execution after installing dependencies, set `$env:PYTHONPATH = 'src'`.

### Tests

- Private screenshots in `samples/` are excluded from Git (see [samples/README.md](samples/README.md)).
  Sample tests skip when they are absent. A missing OCR engine is a failure when samples are present.
- Optional video tests skip without FFmpeg or the capture dependencies. No test downloads data.
- `--basetemp` keeps temporary files under ignored `artifacts/`; pytest clears it on the next run.
- A public checkout needs no private profile, annotations or screenshots. The core subset
  also needs no Tesseract executable:

```powershell
.\.venv\Scripts\python -m pytest -q -m "not ocr and not samples" --basetemp=artifacts/pytest-public
.\.venv\Scripts\python tools/evaluate_samples.py
# Optional, with Node.js 20+ (no npm packages needed):
node --test tools/obs-client.test.mjs
```

Not verified: fresh dependency downloads and the Linux steps above (the original
setup was checked on Windows with an existing local build backend).

## Run it

### Website and overlay

Serve an existing database without starting capture ([product preview guide](docs/product-preview.md)):

```powershell
.\.venv\Scripts\python -m exp_tracker.server --db private/product-preview/preview-01/tracker.sqlite3 --diagnostic-dashboard
Start-Process 'http://127.0.0.1:8765/'
```

| Path | What it shows |
| --- | --- |
| `/`, `/streams` | Progress leaderboard |
| `/stream/CHANNEL` | Character page |
| `/live/overlay/CHANNEL` | Experimental transparent **500 × 160** OBS overlay |
| `/overlay/CHANNEL` | Original trusted overlay ([overlay guide](docs/overlay.md)) |
| `/dev/streams`, `/dashboard/CHANNEL` | Advanced diagnostics |
| `/demo/leaderboard` | Simulated leaderboard with fictional data |

The read-only server supports schemas 3–10; writer initialization migrates to 10.
HTTP never creates or migrates databases or writes tracking state.

### Synthetic demos

```powershell
.\.venv\Scripts\python tools/demo_tracking.py artifacts/sqlite-demo.sqlite3
.\.venv\Scripts\python -m exp_tracker.tracking --db artifacts/sqlite-demo.sqlite3 --channel demo state
.\.venv\Scripts\python tools/demo_statistics.py artifacts/statistics-preview.sqlite3
.\.venv\Scripts\python -m exp_tracker.server --db artifacts/sqlite-demo.sqlite3
Start-Process 'http://127.0.0.1:8765/overlay/demo'
```

### Capture

- [Multi-stream alpha](docs/multi-alpha.md): explicit assignments, sequential by default.
  Opt-in `--workers 2..8` ([capture performance](docs/capture-performance.md)),
  `--stagger-capture` and `--resident-tesseract` ([performance integration](docs/performance-integration.md)).
  Start with the offline two-video example.
- [Single-stream local alpha](docs/local-alpha.md): start with saved-log replay. For a
  permitted live trial:
  `python tools/local_alpha.py --channel CHANNEL --character "Main" --authorized --experimental-neural-level`
- Neural and grammar candidates are experimental and never count toward trusted EXP totals.
  With a profile, capture refuses to promote unverified Tesseract EXP fallbacks to trusted state.
  Trusted game tracking requires your own calibrated v2 profile; none is bundled.

### Administration

- [Manual admin](docs/manual-exp-admin.md): a loopback-only dashboard for baselines, fixes,
  invalidation, undo and renames. Corrections never count as earned EXP, and time never
  defaults silently. It does not start or restart capture.
  `python -m exp_tracker.admin_server --db YOUR_DATABASE.sqlite3 --port 8766`
- Rosters: [private roster CLI](docs/streamer-roster.md), [database-managed roster](docs/database-streamer-roster.md)
  and [automatic adoption](docs/existing-tracker-auto-adoption.md) for existing databases.
- Twitch status: put `TWITCH_CLIENT_ID` and `TWITCH_CLIENT_SECRET` in the ignored root `.env`
  and pass `--twitch-status`. App tokens are managed automatically ([guide](docs/twitch-authentication.md)).
  Twitch credentials stay on the developer/server machine, never in the website or an overlay URL.

### Inspect a screenshot

```powershell
.\.venv\Scripts\ms-exp.exe inspect samples/maplestory-classic-stream1.png --config configs/stream1.json --debug-dir artifacts/stream1
# Automatic discovery currently returns correct but low-confidence candidates (exit 2):
.\.venv\Scripts\python -m exp_tracker inspect samples/maplestory-classic-stream1.png
```

- The output is JSON: parsed values, raw OCR, confidence, ROI and reasons. Exit codes: 0 accepted,
  2 uncertain/missing/invalid, 1 setup/input error.
- `--debug-dir` is opt-in and writes only field crops. `--search x0,y0,x1,y1` restricts
  discovery (fractions of the frame; default: lower 30%). Config ROIs use the same normalized
  coordinates. Recalibrate when the layout changes.
- This needs the in-game HP/MP/EXP HUD. It is a limited baseline, not universal HUD recognition.
  Scores are Tesseract engine scores, not probabilities (default threshold 0.40). Live tracking
  must apply the [capture trust gate](docs/ocr-consolidation.md). See [results](docs/results.md).

## Local data

All of this is ignored by Git:

- `private/multi-alpha/`: the local tracker's database and capture logs. Tests never read
  its `runs/`. Real-log replays use a frozen copy.
- `private/rapidocr/`: the OCR environment. `private/manual-backups/`: backups.
- Test fixtures: `private/test-fixtures/runs/` (a frozen ~43 MB copy of the capture logs, of which
  replays use each channel's oldest 25), `private/ocr-evaluation/`, `adaptive-ocr/`,
  `exp-digits/`, `level-digits/`, `numeric-classifier/`, `levelup-evaluation/`,
  `samples/maplestory-classic-stream1.png` and `-stream2.png`, and in `artifacts/`:
  `accounting-bridge.sqlite3`, `green-test-20261015-215403/` and its `.jsonl`,
  `live-benchmark/` and `live-validation-20261015-203121/` (some manifests use relative paths).

Everything else under `private/`, `samples/` and `artifacts/` is experiment output and safe to archive.

## Documentation

**Start here:** [design](docs/design.md), [acquisition](docs/acquisition.md),
[results](docs/results.md), [player experience principles](docs/product-experience-principles.md),
[agent setup](docs/agent-setup.md).

**Capture and OCR**
- [Live capture](docs/live-capture.md): Streamlink/FFmpeg remote acquisition (passed an authorized live trial).
- [OCR consolidation](docs/ocr-consolidation.md), [OCR reliability](docs/ocr-reliability.md),
  [OCR → SQLite verification](docs/ocr-sqlite-verification.md): trust rules, measurements, profile setup.
- [Shadow capture](docs/shadow-capture.md), [shadow viewer](docs/shadow-viewer.md),
  [blinded review](docs/shadow-reliability-review.md): diagnostic only, never trusted state.
- Experiments outside production: [adaptive HUD](docs/adaptive-ocr.md),
  [character-name OCR](docs/character-name-ocr.md), [level digits](docs/level-digits.md),
  [EXP digits](docs/exp-digits.md), [grayscale hybrid](docs/grayscale-ocr.md),
  [cross-stream evaluation](docs/cross-stream-evaluation.md), [RapidOCR benchmark](docs/rapidocr-benchmark.md),
  [level-up evaluation](docs/level-up-evaluation.md), [shadow findings](docs/test-shadow-diagnostic.md),
  [extended diagnostics](docs/extended-diagnostics.md).

**Tracking and accounting**
- [Tracking engine](docs/tracking.md), [gap accounting](docs/accounting.md),
  [endpoint pace](docs/endpoint-exp-pace.md), [rolling-window gaps](docs/rolling-window-gaps.md).
- Validity: [EXP validity and level policy](docs/exp-validity-level-policy.md),
  [percentage quarantine](docs/percentage-quarantine.md), [MVP level evidence](docs/mvp-level-evidence.md),
  [Telfer level-up](docs/telfer-levelup-and-window-gaps.md).
- History and ETA: [numerical windows](docs/numerical-windows-eta.md),
  [cross-level history](docs/cross-level-history.md), [tracked-EXP consistency](docs/tracked-exp-consistency.md),
  [gap and level resilience](docs/gap-level-resilience.md), [ETA and short gaps](docs/eta-and-short-gap-followup.md).

**Player UI**
- [Statistics](docs/statistics.md), [recent windows](docs/recent-windows.md),
  [observed windows](docs/observed-progress-windows.md), [live updates](docs/live-player-updates.md),
  [live usability](docs/live-usability.md), [responsive experience](docs/responsive-player-experience.md),
  [pace pooling](docs/responsive-pace-pooling.md), [companion statistics](docs/gaming-companion-statistics.md),
  [rolling history](docs/rolling-exp-history.md), [completed captures](docs/historical-player-usability.md),
  [HUD resilience and Twitch status](docs/hud-resilience-and-twitch-status.md),
  [multi-character profiles](docs/multi-character-profiles.md), [demo leaderboard](docs/demo-leaderboard.md).

**Operations and performance**
- [Continuous mode](docs/continuous-alpha.md), [24-hour retention](docs/24h-retention.md),
  [restart recovery](docs/restart-recovery.md), [background publishing](docs/background-publishing.md).
- [Homepage performance](docs/homepage-performance.md), [incremental history](docs/incremental-history.md),
  [card projection](docs/card-projection.md), [EXP-derived level search](docs/exp-inference-performance.md),
  [HUD localization performance](docs/hud-localization-performance.md).
- [VPS readiness](docs/vps-readiness.md), [VPS deployment](docs/vps-deployment.md).

Other notes live in [docs/](docs/). The earlier OBS test page is an unverified developer experiment.

## Credits

The Sleepywood website background (`src/exp_tracker/web/sleepywood*.webp`) is
MapleStory artwork © Nexon, rendered from original GMS v55 game assets by
[maplestory.io](https://maplestory.io). The town and forest backdrop are preserved
as lossless WebP; the navy tint is CSS. See [sources and background checks](docs/website-background.md).

Monster sprites in `src/exp_tracker/web/mobs/` are MapleStory artwork © Nexon, rendered
from game data by [maplestory.io](https://maplestory.io)
(`https://maplestory.io/api/GMS/83/mob/{id}/render/{move|hit1|die1|stand}`), with empty margins
trimmed losslessly so the feet touch the bottom edge. The Slime is the animated WebP from
[meowdb.com](https://meowdb.com/msclassic/es/monsters/7), because maplestory.io's GIF dithers its soft edges. They decorate this non-commercial fan site, which is
not affiliated with Nexon. These decorative assets and the website background are intentional exceptions to "nothing game-derived in Git",
a rule that covers OCR screenshots, crops and templates.
