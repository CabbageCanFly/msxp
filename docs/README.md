# Documentation index

You do not need any of this to run MSXP: the [README](../README.md) and `msxp help` cover everyday
use. These are the deeper notes behind it: guides, design decisions and measured experiments,
grouped so you can find one without opening a hundred files.

## Start here

- [Verified results and known limits](results.md): what works, how well, and what does not.
- [Design](design.md): how the pieces fit together.
- [Acquisition](acquisition.md): how frames are read from Twitch.
- [Player experience principles](product-experience-principles.md): what the website shows, and why.
- [Agent setup](agent-setup.md): optional setup for AI coding sessions.
- [Legacy README](legacy-readme.md): the previous, detailed developer README.

## Running a tracker

- [Database-managed streamers](database-streamer-roster.md) and the [admin page](manual-exp-admin.md):
  adding streamers, corrections, invalidation and renames.
- [Twitch status keys](twitch-authentication.md) · [Twitch Turbo playback](twitch-turbo.md)
- [OBS overlay and read-only API](overlay.md) · [Multi-character profiles](multi-character-profiles.md)
- [Demo leaderboard](demo-leaderboard.md) · [Real-data preview](product-preview.md)
- Older ways to run capture: [multi-stream alpha](multi-alpha.md), [single-stream alpha](local-alpha.md),
  [continuous mode](continuous-alpha.md), [JSON roster](streamer-roster.md),
  [adopting an existing tracker](existing-tracker-auto-adoption.md),
  [isolated character trial](local-live-character-trial.md)
- Repairs: [validated-level repair](level-floor-repair.md)

## Servers and deployment

- [Ubuntu server](vps-deployment.md) · [Server roster rollout](vps-roster-rollout.md) ·
  [100-viewer readiness](vps-readiness.md) · [Cloudflare Pages website](cloudflare-pages-deployment.md)
- [Restart recovery](restart-recovery.md) · [Background publishing](background-publishing.md)
  ([review](background-publishing-review.md)) · [Unattended capture reliability](unattended-capture-reliability.md)
- [24-hour retention](24h-retention.md) · [Retention without missed captures](retention-capture-interference.md)
- [Website backgrounds and their sources](website-background.md)

## Capture and OCR

- [Merged HP/MP labels in 720p HUDs](720p-hud-label-recovery.md)
- [Live capture](live-capture.md) · [OCR consolidation](ocr-consolidation.md) ·
  [OCR reliability](ocr-reliability.md) · [OCR to SQLite verification](ocr-sqlite-verification.md)
- [Capture throughput](capture-performance.md) · [HUD localization performance](hud-localization-performance.md) ·
  [Staggered capture and resident Tesseract](performance-integration.md) ·
  [Cached HUD regions](cached-hud-evaluation.md) · [15-second cadence](production-cadence-evaluation.md)
- [Character-name OCR](character-name-ocr.md) ([review](character-name-ocr-review.md)) ·
  [RapidOCR benchmark](rapidocr-benchmark.md) · [RapidOCR levels](rapidocr-level-evaluation.md)
- Shadow (diagnostic-only) capture: [capture](shadow-capture.md), [viewer](shadow-viewer.md),
  [blinded review](shadow-reliability-review.md), [neural level](shadow-neural-level.md),
  [first trial](test-shadow-diagnostic.md)

## OCR experiments and evaluations

- Recognition experiments: [adaptive HUD](adaptive-ocr.md), [level digits](level-digits.md),
  [EXP digits](exp-digits.md), [grayscale EXP](grayscale-ocr.md),
  [grayscale verification](grayscale-numeric-verification.md), [temporal RapidOCR](temporal-ocr.md),
  [native-pixel verification](pixel-verification.md)
- Evaluations: [cross-stream](cross-stream-evaluation.md), [blinded 24-frame](blinded-ocr-evaluation.md),
  [level-up](level-up-evaluation.md), [final level-up validation](final-levelup-validation.md),
  [EXP-derived levels](exp-derived-level-evaluation.md), [EXP consistency](exp-consistency.md),
  [label audit](ocr-label-audit.md), [timeline coverage](timeline-audit.md)
- Investigations: [obscured HUD](obscured-hud-investigation.md),
  [percentage-only and level 51](percentage-only-level51.md),
  [leading 1 in percentages](leading-percentage-recovery.md), [extended diagnostics](extended-diagnostics.md),
  [grammar diagnostics](grammar-progress-diagnostics.md), [grammar recovery](live-grammar-recovery.md)

## Tracking and EXP math

- [Durable tracking](tracking.md) · [Accounting across gaps](accounting.md) ·
  [EXP/hour from endpoints](endpoint-exp-pace.md) · [Rolling windows across gaps](rolling-window-gaps.md)
- Validity: [EXP validity and level policy](exp-validity-level-policy.md),
  [percentage quarantine](percentage-quarantine.md), [level evidence](mvp-level-evidence.md),
  [prompt level-ups](prompt-levelup-and-window-gaps.md), [stationary EXP after level-up](stationary-level-up.md),
  [numeric gaps and percentage recovery](numeric-gap-and-percentage-recovery.md)
- Deferred follow-up: [obscured LV labels and localization timeouts](stationary-level-up.md#todo-deferred-obscured-lv-labels-and-localization-timeouts)
- History and ETA: [numerical windows and ETA](numerical-windows-eta.md),
  [cross-level history](cross-level-history.md), [tracked-EXP consistency](tracked-exp-consistency.md),
  [historical EXP consistency](historical-exp-consistency.md), [pace through gaps](gap-level-resilience.md),
  [ETA and short gaps](eta-and-short-gap-followup.md), [EXP-derived level search](exp-inference-performance.md)

## Website and player experience

- [Window statistics](statistics.md) · [Recent windows](recent-windows.md) ·
  [Observed windows](observed-progress-windows.md) · [Live updates](live-player-updates.md) ·
  [Last-known levels](live-usability.md) · [Responsive estimates](responsive-player-experience.md) ·
  [Pace pooling](responsive-pace-pooling.md)
- [Companion statistics](gaming-companion-statistics.md) · [Rolling EXP history](rolling-exp-history.md) ·
  [Completed captures](historical-player-usability.md) · [Unreadable HUDs and Twitch status](hud-resilience-and-twitch-status.md)
- Performance: [homepage](homepage-performance.md), [incremental history](incremental-history.md),
  [card projection](card-projection.md), [character summaries](per-character-summary-cache.md)

## Development

- [Test data: public, private and recreatable](private-test-data.md) · [Parallel test audit](parallel-tests.md) · Run everything with `msxp test` (private sample tests skip
  when their files are absent).
