# MapleStory Classic EXP tracker (legacy README)

> The full developer README as of 2026-10-23, kept for reference. The current, short guide is the
> [README](../README.md); every document is listed in the [docs index](README.md).

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

- Private screenshots in `samples/` are excluded from Git (see [samples/README.md](../samples/README.md)).
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

For website styling on Windows, run `.\msxp demo` from this checkout or worktree. It uses
temporary fictional players, serves saved CSS/HTML/JS edits on browser refresh,
and stops both local servers with Ctrl+C. See [background preview and tint controls](website-background.md).

Serve an existing database without starting capture ([product preview guide](product-preview.md)):

```powershell
.\.venv\Scripts\python -m exp_tracker.server --db private/product-preview/preview-01/tracker.sqlite3 --diagnostic-dashboard
Start-Process 'http://127.0.0.1:8765/'
```

| Path | What it shows |
| --- | --- |
| `/`, `/streams` | Progress leaderboard |
| `/stream/CHANNEL` | Character page |
| `/live/overlay/CHANNEL` | Experimental transparent **500 × 160** OBS overlay |
| `/overlay/CHANNEL` | Original trusted overlay ([overlay guide](overlay.md)) |
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

- [Multi-stream alpha](multi-alpha.md): explicit assignments, sequential by default.
  Opt-in `--workers 2..8` ([capture performance](capture-performance.md)),
  `--stagger-capture` and `--resident-tesseract` ([performance integration](performance-integration.md)).
  Start with the offline two-video example.
- [Single-stream local alpha](local-alpha.md): start with saved-log replay. For a
  permitted live trial:
  `python tools/local_alpha.py --channel CHANNEL --character "Main" --authorized --experimental-neural-level`
- Neural and grammar candidates are experimental and never count toward trusted EXP totals.
  With a profile, capture refuses to promote unverified Tesseract EXP fallbacks to trusted state.
  Trusted game tracking requires your own calibrated v2 profile; none is bundled.

### Administration

- [Manual admin](manual-exp-admin.md): a loopback-only dashboard for baselines, fixes,
  invalidation, undo and renames. Corrections never count as earned EXP, and time never
  defaults silently. It does not start or restart capture.
  `python -m exp_tracker.admin_server --db YOUR_DATABASE.sqlite3 --port 8766`
- Rosters: [private roster CLI](streamer-roster.md), [database-managed roster](database-streamer-roster.md)
  and [automatic adoption](existing-tracker-auto-adoption.md) for existing databases.
- Twitch status: put `TWITCH_CLIENT_ID` and `TWITCH_CLIENT_SECRET` in the ignored root `.env`
  and pass `--twitch-status`. App tokens are managed automatically ([guide](twitch-authentication.md)).
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
  must apply the [capture trust gate](ocr-consolidation.md). See [results](results.md).

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

**Start here:** [design](design.md), [acquisition](acquisition.md),
[results](results.md), [player experience principles](product-experience-principles.md),
[agent setup](agent-setup.md).

**Capture and OCR**
- [Live capture](live-capture.md): Streamlink/FFmpeg remote acquisition (passed an authorized live trial).
- [OCR consolidation](ocr-consolidation.md), [OCR reliability](ocr-reliability.md),
  [OCR → SQLite verification](ocr-sqlite-verification.md): trust rules, measurements, profile setup.
- [Shadow capture](shadow-capture.md), [shadow viewer](shadow-viewer.md),
  [blinded review](shadow-reliability-review.md): diagnostic only, never trusted state.
- Experiments outside production: [adaptive HUD](adaptive-ocr.md),
  [character-name OCR](character-name-ocr.md), [level digits](level-digits.md),
  [EXP digits](exp-digits.md), [grayscale hybrid](grayscale-ocr.md),
  [cross-stream evaluation](cross-stream-evaluation.md), [RapidOCR benchmark](rapidocr-benchmark.md),
  [level-up evaluation](level-up-evaluation.md), [shadow findings](test-shadow-diagnostic.md),
  [extended diagnostics](extended-diagnostics.md).

**Tracking and accounting**
- [Tracking engine](tracking.md), [gap accounting](accounting.md),
  [endpoint pace](endpoint-exp-pace.md), [rolling-window gaps](rolling-window-gaps.md).
- Validity: [EXP validity and level policy](exp-validity-level-policy.md),
  [percentage quarantine](percentage-quarantine.md), [MVP level evidence](mvp-level-evidence.md),
  [CharA level-up](prompt-levelup-and-window-gaps.md).
- History and ETA: [numerical windows](numerical-windows-eta.md),
  [cross-level history](cross-level-history.md), [tracked-EXP consistency](tracked-exp-consistency.md),
  [gap and level resilience](gap-level-resilience.md), [ETA and short gaps](eta-and-short-gap-followup.md).

**Player UI**
- [Statistics](statistics.md), [recent windows](recent-windows.md),
  [observed windows](observed-progress-windows.md), [live updates](live-player-updates.md),
  [live usability](live-usability.md), [responsive experience](responsive-player-experience.md),
  [pace pooling](responsive-pace-pooling.md), [companion statistics](gaming-companion-statistics.md),
  [rolling history](rolling-exp-history.md), [completed captures](historical-player-usability.md),
  [HUD resilience and Twitch status](hud-resilience-and-twitch-status.md),
  [multi-character profiles](multi-character-profiles.md), [demo leaderboard](demo-leaderboard.md).

**Operations and performance**
- [Continuous mode](continuous-alpha.md), [24-hour retention](24h-retention.md),
  [restart recovery](restart-recovery.md), [background publishing](background-publishing.md).
- [Homepage performance](homepage-performance.md), [incremental history](incremental-history.md),
  [card projection](card-projection.md), [EXP-derived level search](exp-inference-performance.md),
  [HUD localization performance](hud-localization-performance.md).
- [VPS readiness](vps-readiness.md), [VPS deployment](vps-deployment.md).

Other notes live in [docs/](). The earlier OBS test page is an unverified developer experiment.

## Credits

The Sleepywood and Kerning City website backgrounds (`src/exp_tracker/web/sleepywood*.webp`
and `kerning*.webp`) are
MapleStory artwork © Nexon, rendered from original GMS v55 game assets by
[maplestory.io](https://maplestory.io). The towns and original forest/sky backdrops are preserved
as lossless WebP; the navy tint is CSS. See [sources and background checks](website-background.md).

Monster sprites in `src/exp_tracker/web/mobs/` are MapleStory artwork © Nexon, rendered
from game data by [maplestory.io](https://maplestory.io)
(`https://maplestory.io/api/GMS/83/mob/{id}/render/{move|hit1|die1|stand}`), with empty margins
trimmed losslessly so the feet touch the bottom edge. The Slime is the animated WebP from
[meowdb.com](https://meowdb.com/msclassic/es/monsters/7), because maplestory.io's GIF dithers its soft edges. They decorate this non-commercial fan site, which is
not affiliated with Nexon. These decorative assets and the website background are intentional exceptions to "nothing game-derived in Git",
a rule that covers OCR screenshots, crops and templates.
