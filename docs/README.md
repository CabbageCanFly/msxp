# Documentation index

Start with the [README](../README.md) and `msxp help` for everyday use.
The README's [Next improvements](../README.md#next-improvements) is the single short TODO list.

## Running a tracker

- [Database-managed streamers](database-streamer-roster.md) · [Admin and corrections](manual-exp-admin.md)
- [Twitch status keys](twitch-authentication.md) · [Twitch Turbo playback](twitch-turbo.md)
- [Multi-character profiles and History](multi-character-profiles.md) · [OBS overlay and read-only API](overlay.md)
- [Demo previews](demo-leaderboard.md) · [Real-data preview](product-preview.md)
- [Validated-level repair](level-floor-repair.md)

## Servers and deployment

- [VPS roster runbook](vps-roster-rollout.md) · [Separate API/capture services and restart recovery](restart-recovery.md)
- [Cloudflare Pages website](cloudflare-pages-deployment.md)
- [Retention and daily history](24h-retention.md) · [Timeout overrides](24h-retention.md#updating-the-historical-feature-and-resuming-a-paused-vps-timer)
- [Background publishing](background-publishing.md) · [Unattended capture reliability](unattended-capture-reliability.md)

## Capture and OCR

- [Layout-first HUD recognition](layout-first-hud.md) · [Merged HP/MP labels in 720p HUDs](720p-hud-label-recovery.md)
- [Capture performance](capture-performance.md) · [Staggered capture and resident Tesseract](performance-integration.md)
- [Character-name OCR](character-name-ocr.md)

## Tracking and EXP math

- [Tracking engine](tracking.md) · [Accounting across gaps](accounting.md)
- [Level evidence](mvp-level-evidence.md) · [EXP/hour from endpoints](endpoint-exp-pace.md) · [Rolling windows across gaps](rolling-window-gaps.md)

## Website and player experience

- [Player experience principles](product-experience-principles.md) · [Background preview and asset sources](website-background.md)
- Performance: [homepage](homepage-performance.md), [incremental history](incremental-history.md),
  [card projection](card-projection.md), [character summaries](per-character-summary-cache.md)

## Development

- [Private fixtures, recovery and disposable output](private-test-data.md) · [Parallel test audit](parallel-tests.md)
- Run `msxp test`; private sample tests skip when their inputs are absent. Use normal pytest temporary storage.

<details>
<summary>Research, experiments and past milestones</summary>

These notes preserve earlier measurements, commands and limits. Use the guides above for
current operation and the README TODO list for planned work.

### Early plans and setup

- [Service proposal](design.md) · [Acquisition investigation](acquisition.md) · [Original feasibility results](results.md)
- [Historical agent sandbox notes](agent-setup.md) · [Legacy developer README](legacy-readme.md)
- [Original Ubuntu installation](vps-deployment.md) · [100-viewer readiness](vps-readiness.md)
- Earlier capture guides: [multi-stream alpha](multi-alpha.md), [single-stream alpha](local-alpha.md),
  [continuous mode](continuous-alpha.md), [JSON roster](streamer-roster.md),
  [adopting an existing tracker](existing-tracker-auto-adoption.md), [isolated character trial](local-live-character-trial.md)

### Capture and OCR research

- [Live capture trial](live-capture.md) · [OCR consolidation](ocr-consolidation.md) ·
  [OCR reliability](ocr-reliability.md) · [OCR to SQLite verification](ocr-sqlite-verification.md)
- [HUD localization performance](hud-localization-performance.md) · [Cached HUD regions](cached-hud-evaluation.md) ·
  [15-second cadence](production-cadence-evaluation.md) · [Retention/capture interference](retention-capture-interference.md)
- [Throughput architecture](throughput-architecture-research.md) · [Staggered-capture experiment](staggered-capture-experiment.md) ·
  [Resident-Tesseract evaluation](resident-tesseract-evaluation.md) · [Character-name review](character-name-ocr-review.md)
- [RapidOCR benchmark](rapidocr-benchmark.md) · [RapidOCR levels](rapidocr-level-evaluation.md)
- Shadow diagnostics: [capture](shadow-capture.md), [viewer](shadow-viewer.md), [blinded review](shadow-reliability-review.md),
  [neural level](shadow-neural-level.md), [first trial](test-shadow-diagnostic.md)

### OCR experiments and evaluations

- Recognition experiments: [adaptive HUD](adaptive-ocr.md), [level digits](level-digits.md),
  [EXP digits](exp-digits.md), [grayscale EXP](grayscale-ocr.md), [grayscale verification](grayscale-numeric-verification.md),
  [temporal RapidOCR](temporal-ocr.md), [native-pixel verification](pixel-verification.md)
- Evaluations: [cross-stream](cross-stream-evaluation.md), [blinded 24-frame](blinded-ocr-evaluation.md),
  [level-up](level-up-evaluation.md), [final level-up validation](final-levelup-validation.md),
  [EXP-derived levels](exp-derived-level-evaluation.md), [EXP consistency](exp-consistency.md),
  [label audit](ocr-label-audit.md), [timeline coverage](timeline-audit.md)
- Investigations: [obscured HUD](obscured-hud-investigation.md), [percentage-only and level 51](percentage-only-level51.md),
  [leading 1 in percentages](leading-percentage-recovery.md), [extended diagnostics](extended-diagnostics.md),
  [grammar diagnostics](grammar-progress-diagnostics.md), [grammar recovery](live-grammar-recovery.md)

### Tracking and history milestones

- Validity: [EXP validity and level policy](exp-validity-level-policy.md), [percentage quarantine](percentage-quarantine.md),
  [prompt level-ups](prompt-levelup-and-window-gaps.md), [stationary EXP after level-up](stationary-level-up.md),
  [numeric gaps and percentage recovery](numeric-gap-and-percentage-recovery.md)
- History and ETA: [numerical windows and ETA](numerical-windows-eta.md), [cross-level history](cross-level-history.md),
  [tracked-EXP consistency](tracked-exp-consistency.md), [historical EXP consistency](historical-exp-consistency.md),
  [pace through gaps](gap-level-resilience.md), [ETA and short gaps](eta-and-short-gap-followup.md),
  [EXP-derived level search](exp-inference-performance.md)

### Website milestones

- [Window statistics](statistics.md) · [Recent windows](recent-windows.md) · [Observed windows](observed-progress-windows.md) ·
  [Live updates](live-player-updates.md) · [Last-known levels](live-usability.md) ·
  [Responsive estimates](responsive-player-experience.md) · [Pace pooling](responsive-pace-pooling.md)
- [Companion statistics](gaming-companion-statistics.md) · [Rolling EXP history](rolling-exp-history.md) ·
  [Completed captures](historical-player-usability.md) · [Unreadable HUDs and Twitch status](hud-resilience-and-twitch-status.md)
- [Background-publishing review](background-publishing-review.md)

</details>
