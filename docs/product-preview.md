# Real-data EXP Tracker prototype

The default page **with `--diagnostic-dashboard` enabled** is now the player-facing
EXP Tracker. It reuses the original leaderboard's navy, warm brown, orange and
lime presentation and the compact overlay's own SVG/CSS. No new framework,
dependency, database schema, capture path or OCR rule was added.

| URL | Purpose |
|---|---|
| `/` or `/streams` | Actual configured characters, progress bars and functional sorting |
| `/stream/CHANNEL` | Character, recent estimates, bounded percentage history and overlay link/copy |
| `/live/overlay/CHANNEL` | Experimental OBS Browser Source, **500 × 160**, transparent surroundings |
| `/dev/streams`, `/dashboard/CHANNEL` | Existing advanced directory and historical diagnostics |
| `/overlay/CHANNEL` | Original trusted overlay, unchanged semantics |
| `/demo/leaderboard` | Separate, explicitly simulated design demo |

The OBS builder offers **General**, **EXP bar**, **EXP rates** and **Last hour**.
General replaces the progress bar and current EXP numbers with a miniature EXP
history chart. Its preview and copied URL follow the EXP history panel's interval
(1/5/30 minutes) and time window. The 30-minute interval enables 12h/24h windows
and disables 15/30/60-minute windows; 1- and 5-minute intervals reverse those
choices. The 24h view remains the default. The 12h view uses the newest 24 of the
existing 48 aggregate buckets, including their missing/zero states, with no API
change. Short and long window selections are remembered independently while the
page stays open. The General overlay caption, preview, bars and chart total follow
the selection (`interval=1800&range=720` for 12h, `range=1440` for 24h).
Standalone URLs without chart settings default to 1-minute
bars over the last hour. After changing settings, copy the updated URL into OBS;
an existing OBS source keeps the settings in its URL.
Profile, linked overlay and homepage mini-chart bars omit gains whose observation endpoints are more than 60 minutes apart;
exactly 60 minutes remains eligible. This removes unlocated gains on returning
after a long tracking gap while retaining short intervals in the same bucket.
The API's chart-only `chart_value` is separate from bucket `value`: saved readings
and 24-hour EXP totals retain those long-gap gains.
EXP bar preserves the previous General layout at
`?layout=bar`. Both use a 500 × 160 Browser Source; rates use 500 × 110 and the
standalone last-hour chart uses 500 × 180. Missing history stays blank/dashed.
The builder's **Character** selector defaults to **Automatic (most recent character)**.
Choosing a character's name puts that saved character's ID in the overlay URL and
reloads the preview for that character across all four layouts. An inactive
character shows its saved readings with a last-tracked date. An unavailable lock
stays locked and clears the display rather than switching to another character.
Header text switches to black for light header colours. Roster status text is
neutral: **Current** requires a confirmed EXP reading within five minutes;
otherwise the pill shows the saved EXP reading's age. Published roster entries
include `last_exp_at` from cached summaries; a newer HUD sighting does not refresh it.
While a character's summary warms, its EXP timestamp may be unavailable.
The Streamers Level view and every Characters sort show a five-minute EXP/hour
estimate on the right, or a dash if unavailable or over five minutes old.
Character list rates reuse the cached five-minute pace; HTTP requests do not build
history or fetch individual profiles. All Characters sorts also show a saved
five-minute next-level ETA for up to five minutes after it was estimated, using
the same static-duration label as Streamers; missing or expired estimates stay hidden.
Character rows are numbered in every sort,
with gold/silver/bronze rank badges only when sorted by Level.
The homepage header search filters both Streamers and Characters by character
name or channel, keeping the search text when switching views. Both views have
**SORT BY** pills below the header. Characters offers **Name / Level / Last seen**
and defaults to Level. Streamers retains **EXP / hour / Level / 24h EXP**; its
5/10/15/30-minute controls are hidden in Characters because they do not apply.

## Try the saved data

Run from the repository root with the existing environments. This workstation's
preview database was copied safely from actual two-video capture results. It
contains `offline_window` and `offline_low`, explicitly identified as video
sources, with separate characters/sessions. It is private, not shipped in Git.

```powershell
.\.venv\Scripts\python -m exp_tracker.server --db private/product-preview/preview-01/tracker.sqlite3 --diagnostic-dashboard
Start-Process 'http://127.0.0.1:8765/'
Start-Process 'http://127.0.0.1:8765/stream/offline_window'
Start-Process 'http://127.0.0.1:8765/live/overlay/offline_window'
```

Saved readings age naturally; starting HTTP does **not** start capture. For a new
disposable copy, use the existing backup command with a **new** destination:

```powershell
.\.venv\Scripts\python tools/backup_database.py private/continuous-alpha/actual-01/shared.sqlite3 private/product-preview/my-preview/tracker.sqlite3
.\.venv\Scripts\python -m exp_tracker.server --db private/product-preview/my-preview/tracker.sqlite3 --diagnostic-dashboard
```

In a second terminal, this existing bounded runner acquires three actual local
video frames, recognizes them and commits separate diagnostic attempts. The open
pages update automatically; their responses are not replaced with fixtures.

```powershell
.\.venv\Scripts\python tools/shadow_capture.py --db private/product-preview/my-preview/tracker.sqlite3 --tracking-channel offline_window --file samples/sample-stream3.mp4 --start 1186 --interval 16 --count 3 --experimental-neural-level --output private/product-preview/my-preview/update-01.jsonl
```

Use a new output filename for each invocation. Existing assignments/sessions must
already exist; the runner does not infer a character from the HUD. The standalone
server has no coordinator runtime ownership, so it conservatively shows capture
paused even while this independently started writer delivers fresh observations.
For accurate capturing/waiting activity labels, use the normal
[multi-stream coordinator](multi-alpha.md), which owns both worker and server:

```powershell
.\.venv\Scripts\python tools/multi_alpha.py --config private/multi-alpha/config.json --check
.\.venv\Scripts\python tools/multi_alpha.py --config private/multi-alpha/config.json --continuous
Start-Process 'http://127.0.0.1:8765/'
```

Do not start another server on its port. For a later permitted Twitch trial,
explicitly configure the channel/character, `authorized:true`, neural-level
diagnostics and a bounded attempt count for each source, then use the same
coordinator without `--continuous`. No Twitch connection was made for this milestone.
The original saved Streamer_A database is also viewable without modifying it:

```powershell
.\.venv\Scripts\python -m exp_tracker.server --db private/local-alpha/live/streamer_a.sqlite3 --diagnostic-dashboard --port 8766
Start-Process 'http://127.0.0.1:8766/stream/streamer_a'
```

## Observations and estimates

`/api/players` uses the existing cached, bounded SQLite directory projection.
`/api/players/CHANNEL` reuses the selected session's snapshot and returns at most
640 compact history points (enough for 30 minutes at the offline 3-second floor).
Advanced diagnostics keep their 120-attempt pages. Both are read-only, opt-in, localhost-only and retain
the server's CSP/security behavior. Raw model text, private paths and playback
URLs are absent. Advanced APIs retain raw evidence and detailed bounds.

The latest usable reading follows existing precedence: strict full pair, strict
percentage-only, then unique grammar interpretation. Absolute EXP comes **from
that same attempt**, or stays unavailable; an old integer is never combined with
a newer percentage. Recovered values use an ≈ marker/dashed border. The model can
still make plausible numeric errors even in strictly parsed output. Two level
readers are retained separately. The [bounded provisional level policy](exp-validity-level-policy.md)
can confirm recent neural evidence despite Tesseract disagreement; `*` marks
provisional evidence. Conditional EXP contradictions withhold the integer while
preserving its percentage. No table inference silently replaces a visual level.

When that integer is unavailable/withheld, `reading.estimated_exp` may separately
provide a presentation estimate from the displayed percentage and the existing
supported visual-level context. The UI shows a compact `≈1.07M` with both formatting
hypotheses' integer ranges in its tooltip. `reading.exp` and all raw candidates
remain unchanged; missing/disputed levels/requirements leave this estimate blank.
See [live update validation](live-player-updates.md). Player pages poll every two
seconds including background tabs (browser throttling may delay timers), with an
immediate request on returning and no overlapping requests.

- **Homepage and character-page comparisons** use the selected 5/10/15/30-minute
  window ending at the latest capture. Only endpoints inside that window count;
  no boundary gains are interpolated. At least 90% uninterrupted coverage and a
  first endpoint within one recorded capture interval of the boundary are needed.
  Actual elapsed time is shown; shorter/interrupted histories leave metrics blank.
  See [recent windows](recent-windows.md) for the policy and saved-data checks.
- **OBS overlay recent progress** retains the existing current uninterrupted
  segment's displayed change and actual duration; it is not a fixed-window total.
- **Pace** reuses the existing engine: at least three readings over 30 seconds,
  explicit same-level evidence, source/character/session continuity and all
  freshness/missing-attempt/rotation safeguards. Zero displayed change can give
  zero displayed pace, not proof of zero earned EXP.
- **Estimated EXP/hour** = displayed pp/hour × provisional requirement / 100.
  Missing/disputed requirements leave this blank. Exact rational calculations
  preserve nearest-half-up and truncation bounds separately; no rule is selected.
  The UI shows a compact approximate value, with bounds/provenance in its tooltip.
- **To next level** = displayed remaining percentage / positive eligible pace.
  Both hypotheses must have strictly positive lower pace bounds. Their remaining
  percentage intervals and rate bounds give separate outer ETA bounds. This is
  an assumption of continued same-level pace, rounded up to five minutes in the
  UI, not a countdown or a guarantee. No EXP table is needed for this conversion.
- Failed latest captures interrupt estimates. Stale/simulated results cannot
  supply rates/ETA. Ages advance locally even when polling fails. No missing
  observation becomes zero. Clean dashes replace unavailable metrics.

Ranking compares only eligible configured characters for the selected metric,
with unavailable values after eligible ones and equal values sharing ranks.
On the homepage, the EXP/hour selection also sets the maximum age of a saved
pace: 5, 10, 15 or 30 minutes. Older estimates have no rank and sort last.
Homepage row ETAs also retain saved durations up to the selected window's age
limit. Estimate age is in the hover text, without a second age label beside the
duration. They do not count down or fill missing ETAs.
Level sorting explicitly uses **last observed** levels, which may be old. Recent
progress on the website compares eligible selected windows with actual coverage.
The overlay retains shorter segment estimates. No unsupported window,
daily total, session earnings or authoritative rank is invented.

All of these are experimental presentation, never `Store.ingest`, trusted state,
session gains, trusted statistics or trusted OBS data. Source/broadcast age and
in-frame character identity remain unverified. The card says capturing only when
the actual coordinator runtime establishes activity, never Twitch "Live".

## Verification and private evidence

The Chrome harness uses the actual localhost server and SQLite, not intercepted
responses. It checks initial real readings, mobile overflow, transparent fixed
overlay dimensions, navigation count, polling updates and same-origin requests.

```powershell
.\.venv\Scripts\python -m pytest tests/test_product.py tests/test_server.py tests/test_diagnostics.py -q
node --test tools/overlay.test.mjs tools/shadow.test.mjs tools/streams.test.mjs tools/leaderboard.test.mjs tools/product.test.mjs
# With the server above running; choose a NEW private output directory:
node tools/product.browser.mjs http://127.0.0.1:8765 private/product-preview/browser-new private/product-preview/my-preview/tracker.sqlite3 offline_window
.\.venv\Scripts\python -m pytest -q
```

Actual integration evidence: `private/product-preview/browser-e2e-03/` contains
desktop/mobile homepage, stale/fresh overlay and character screenshots, raw
capture JSONL, before/after API values and polling verification. Images were
visually inspected. The overlay remained 500 × 160 with transparent surroundings;
the actual card is 490 × 150 with five-pixel margins.

Three fresh FFmpeg/RapidOCR/Tesseract attempts yielded strict pairs
`74,861[25.44%]`, `75,199[25.56%]`, `75,630[25.71%]`; both level readers said 40.
The homepage and overlay observed changes without a reload. At 16-second requested
intervals, receipt gaps were 16.020s and 15.995s; attempts took 6.23–6.43s.
The segment's +0.27 pp over 32.015s produced ~30.36 pp/h, ~89.3K provisional EXP/h
and a coarse ~2h30m ETA. This verifies functionality, not new OCR accuracy or VPS
performance. These are familiar saved-source pixels, not a blind holdout.

The serial runner reported 38.46s wall, 12.875s sampled process-tree CPU and
193.51 MiB sampled peak process-tree RSS. This excludes Chrome and the independent
HTTP server. The earlier three-attempt run also succeeded, but its browser check
failed because the homepage tab was hidden and intentionally paused polling.
The corrected harness keeps it visible; the failed evidence remains preserved.

Read-only inspection of the untouched Streamer_A capture returned its last recovered
`498,337[33.27%]`, level evidence 64/64, stale with no current estimates. The
two-video source DB and historical logs were not rewritten; only its new copy
received six fresh attempts from the two bounded checks. Trusted observations
remain empty in that copy.

Validation: **87 focused Python tests**, **1,136 full-suite Python tests**
(128.50s), **45 Node tests**, all passing with **zero skips**. The final actual
Chrome check captured four current static/stale views in
`private/product-preview/browser-final-02/`; the unchanged advanced directory
also passed repeated polling and four browser cases in `advanced-browser-01/`.
The fresh capture/estimate screenshots remain in `browser-e2e-03/`.

## Changed files

- `src/exp_tracker/product.py`: small pure presentation/estimate adapter.
- `diagnostics.py`, `server.py`: cached adapter integration and read-only routes.
- `web/tracker.html`, `player.html`, `live-overlay.html`, `product.css`,
  `product.js`: product views reusing existing leaderboard/overlay assets.
- `web/streams.html`, `tools/shadow.browser.mjs`: preserve the advanced directory
  under `/dev/streams`.
- `tests/test_product.py`, `tools/product.test.mjs`, `tools/product.browser.mjs`:
  regression and actual local-video/browser checks.
- `README.md`, `docs/multi-alpha.md`, this guide: startup and route documentation.

No schema/accounting/capture/grammar/model changes, commits, pushes or deployment.
Remaining practical check: James tests the new Browser Source in OBS and then
runs a bounded, explicitly permitted one- or two-stream coordinator trial.
