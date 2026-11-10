# Personal EXP tracker in the browser (`/local`)

`msxp.pages.dev/local` tracks **your own** character without Twitch, Python or any install. You
share the MapleStory window with Chrome or Edge; the page reads the EXP bar every few seconds and
keeps the history in this browser. It is independent of the VPS, the API and the production
database: the page and its OCR runtime are static Pages files, and the page's Content Security
Policy allows network requests only to its own origin (`connect-src 'self'`), so readings cannot be
sent anywhere.

## Using it

1. Open `/local` and click **Start tracking**. Name, job and level are read from the game; a
   character is created or chosen automatically (you can rename it; history stays with it).
2. In the browser's sharing dialog choose **Window → MapleStory → Share**. The browser asks every
   time; the page cannot select a window itself. A window covered by other windows still captures.
3. The first scan finds the status bar (about a second), then scans every 20 seconds
   (5, 10, 20 or 30 s can be chosen). Changes are confirmed by a **burst**: an extra scan a second
   later (first reading, level-up, EXP loss, new job) or three (a different name).
4. **Stop**, Chrome's **Stop sharing**, closing the tab or a reload end the session. Saved readings
   stay; after a reload the page shows the saved progress and is not tracking until you start again.
   While tracking, a reload or close triggers the browser's own leave-page confirmation.

The page mirrors the live character page: the same stat cards and windows (5–60 min, *Current level
only*), the EXP bar chart (1/5/30-minute bars, 15 min–24 h), the Level % line with level-up markers
and the daily History line (30/90/365 days), drawn by `local/charts.js`, a port of the live chart
code fed from local readings (`product.js` is unchanged).

**Stream overlay**: the live overlay builder (layouts General, EXP bar, EXP rates, Last hour; title,
icon, job, name; colour presets, custom and random colours) previews `/local/overlay` in place.
**Open pop-out** opens it in a window of the same browser profile at the overlay's size; capture it
in OBS with **Window Capture** (the window "msxp overlay · On this device"). It takes the live
overlay's URL options plus `bg=dark|green|magenta`: Window Capture cannot see transparency, so crop
to the card or key out the green/magenta background. The overlay never captures the screen.
An OBS **Browser Source** cannot use it: OBS runs its own Chromium with separate storage, so it
cannot read this browser's IndexedDB or BroadcastChannel. That would need a local bridge (a small
local HTTP/WebSocket helper) and is a separate milestone.

## How a scan works

Receiving a capture stream is not the same as processing every frame. The page asks for at most
5 frames per second (`frameRate: {ideal: 5, max: 5}`; Chrome honoured it in the live test) and on
each scan takes the latest frame (`ImageCapture.grabFrame`, a `<video>` fallback elsewhere), crops
the HUD and discards the pixels. One scan runs at a time; a tick that finds the previous scan still
running is skipped, never queued.

| Step | Module | Notes |
| --- | --- | --- |
| Locate the status bar | `hud.js` `locate` | One sparse Tesseract pass over the bottom 22 % of the window finds the `EXP`, `HP`, `MP` and `LV.` labels (the Python `discover_regions` geometry). Boxes are saved normalized with the window size. Without `LV.`, the level box is a strip left of HP. |
| Copy the HUD rows | `app.js` `grab` | Once boxes are known, only the band of rows holding them is copied (1368×56 instead of 1368×800 in the test). Detection and the preview use full frames. |
| Fit the fields | `reader.js` `fieldBoxes` | Each scan finds the two olive-green brackets around the percentage in pixels, trims the `EXP.` label (it is taller than the digits) and finds the orange level tiles. Without both brackets the field is treated as hidden or covered. |
| Read EXP | `glyphs.js`, `reader.js` | Learned glyph templates first (exact pixels, ~2 ms). Otherwise Tesseract reads the number and the percentage separately (digit whitelists), nearest-neighbour at two magnifications, then a smoothed pass for scaled HUDs. Both variants of a pass must parse to the same value. |
| Read level | `reader.js` | Learned digit templates on the orange tiles; otherwise Tesseract (white digits via the minimum channel). |
| Name and job | `hud.js` `panelLines`, `glyphs.js` `lineKey` | The two text lines beside the badge, found in pixels. Each scan compares their exact bitmaps (about 0.1 ms); OCR runs only to label a new bitmap. |
| Validate and track | `exp.js` | Strict parsing, EXP-table arithmetic, confirmation rules below. |
| Store and publish | `store.js`, BroadcastChannel | IndexedDB transaction per scan; the overlay re-reads IndexedDB when notified. |

Re-detection runs after three failed or rejected scans in a row (at most once a minute) when the
boxes came from automatic detection. **Manual calibration**: *Show preview* displays the bottom of
the last frame with the boxes; *Draw EXP box* / *Draw level box* then drag a rectangle. A level box
must contain the orange badge. Boxes only apply to a window with the same aspect ratio; a resized
window is detected again. The preview exists only in memory.

### Why glyph templates

Tesseract is a poor fit for the HUD's 1-pixel bitmap font at native size. On one live crop of
`5,661` it returned `5.661`, `.661`, `.1` or `2.61` depending only on magnification and smoothing,
and bilinear upscaling flipped `27.09%` to `27.08%`. A window capture, however, draws the font
pixel-identically every time. So the page learns templates on the player's machine: when a
Tesseract reading has been **accepted by the tracker** (both variants agreed, the EXP table matched,
and a second scan confirmed it), each glyph bitmap is paired with the HUD's own spelling of that
value (`5,477` and `27.09%`) if and only if the glyph count equals the character count. A bitmap
ever paired with two characters is poisoned and never used. A field with any unknown glyph falls
back to Tesseract. No game font data ships with msxp; templates are stored only in this browser and
reset when the window size changes. In the live test 11 templates were learned within two minutes
and later scans read EXP from templates alone.

## Trust rules (port of `parsing.py`, `exp_consistency.py`, `validation.py`)

- **Strict parsing**: `number[dd.dd%]`, commas or periods as thousands separators, exactly two
  decimals. Brackets are accepted only because they were found in pixels; digits are never invented.
- **EXP table**: the community table (`data/community-exp-v2.json`, exported as
  `static/local/community-exp.json`) must agree with EXP and percentage under either rounding
  (nearest or truncation). Levels without a published requirement (100+) are `ocr_only`:
  accepted with an OCR level but without ETA or level-up gain.
- **Level**: the badge reading must agree with the table; if the badge is unreadable, the previous
  accepted level may continue only when the pair is consistent with it.
- **Confirmation**: the first reading of a session, a level change, an EXP loss (death), a jump of
  more than 20 percentage points and anything after a gap (more than `max(120 s, 4 × interval + 10 s)`)
  wait for a second agreeing reading. A one-off misread is dropped and the accepted state kept.
- **Gains**: only endpoint differences between consecutive accepted readings in the same session.
  A confirmed break starts a baseline whose difference is never counted. A confirmed +1 level-up
  inside the gap limit with a published requirement counts `to_next − previous EXP + new EXP`.
- **Identity, automatic and by pixels**: the name line's exact bitmap identifies the character. A
  different bitmap must repeat on three scans a second apart. Then the page switches to the
  character with that bitmap; or gives it to the character being tracked if that one has no name
  bitmap yet and the reading fits its history; or creates a character named by OCR (both native
  magnifications must agree; a glyph identical to a digit learned from the EXP bar is that digit,
  and any other OCR `0` is the letter O). No valid OCR name, no new character. Because identity is
  the bitmap, a misread name only mislabels a history, it never splits or mixes one; renaming keeps
  it. Choosing another character by hand while the game shows a known name switches back.
  Errors are accepted as on the live site rather than asking for confirmation.
- **Job**: a changed job line must repeat on two scans; OCR is matched to the 15 known jobs (at most
  two edits, and never between two equally close jobs, e.g. the two Wizards).
- **Fallback identity check**: without a readable name line (manual boxes, covered panel), a
  confirmed reading that drops a level, jumps more than one level, or loses more than 15 percentage
  points pauses with "this looks like a different character". A new session keeps the previous
  reading only as this reference, never as an interval start.

## Statistics and storage

EXP/hour uses whole accepted intervals inside the window and divides by observed time, with 80 %
coverage (as `statistics.py`); the session rate needs two observed minutes. Until the selected
window has that coverage, the card shows the session's rate labelled "So far · N observed"
(overlay: "EXP/h · so far") instead of a blank. The 5-minute chart
shows grey for buckets with too little observed time; missing time is never zero. ETA uses the
selected window's rate and the published requirement. The "so far" rate is shown only while a
session is running (the overlay: while the last reading is under two minutes old).

IndexedDB `msxp-local` (version 2): `characters` (name, job, name/job bitmaps, last accepted
reading, tracker state, all-time gain), `sessions` (start/end, end reason, counts per scan outcome),
`readings` (accepted readings only: time, level, EXP, basis points, gain, kind; about 115 bytes
each), `days` (one row per character and local calendar day: last reading and EXP gained) and
`settings` (interval, window, calibration, glyph templates, overlay options, active character).

**Retention like the live site**: detailed readings are kept for **24 hours + 5 minutes** (plus one
older boundary reading per character), pruned when tracking starts and hourly while it runs. Days
are kept indefinitely: about 200 bytes per character per day, so a year of one character is about
75 KB. Each accepted reading updates its day row in the same transaction, so pruning loses nothing
the History chart uses. Version 1 databases are migrated by folding existing readings into days.
No frames are stored. The only pixel data kept are the learned bitmaps: single HUD characters
(about 35 pixels each) and each character's name and job lines, which are needed to read without
OCR; *Clear all local history* deletes them.
Sessions left open by a crash are closed at their last reading on the next visit. Only one tab
of a browser profile can capture (Web Locks `msxp-local-capture`, released automatically when the
tab closes); a second `/local` tab says tracking is already running and leaves that session open. *Export JSON*
downloads everything; *Clear all local history* (two clicks) deletes the database.
`navigator.storage.persist()` is requested once tracking starts; normal use does not depend on it.

## Measured (2026-11-10, Windows 11, Chrome, MapleStory Classic window 1368×800)

Live capture, character level 20, scans every 20 s with the game in the foreground:

- Chrome's picker listed the MapleStory window and captured it while Chrome covered it;
  `getSettings()` reported 1368×800 at 5 fps.
- Automatic localization: about 1.0–1.2 s, once per session.
- Scan wall time (grab, crop, read, validate, store): 24–31 ms with learned templates; 65–120 ms on
  the Tesseract path (about 6 ms per small OCR call, 88 calls averaged).
- Cadence: consecutive scans 20.00 s apart (±0.01 s) over the test.
- Main-thread JS heap: 13 MB. Process CPU was not isolated; at 30 ms per 20 s the page's own work
  is about 0.15 % of one core, plus Chrome's capture pipeline.
- Accuracy: after the fixes, every accepted reading matched the HUD (visually checked samples
  `5,477 [27.09%]`, `6,439 [31.85%]`, `7,041 [34.83%]`, level 20); 13 readings, 980 EXP tracked,
  equal to the difference between first and last accepted EXP. Earlier misreads (clipped leading
  digits, `27.08%`) were all rejected by variant agreement or the EXP table, never stored.
- Overlay: a BroadcastChannel update reached `/local/overlay` within the same scan; card and
  bar/green layouts rendered from IndexedDB.

Offline replay of the 26 labelled Twitch frames (`samples/live-regression`, compressed and scaled,
not the target input): no reading was accepted with a wrong value. Most are rejected or not
located (overlays, third-party trackers, scaled layouts); manual calibration is the fallback there.

## Not yet verified

- **Hidden or minimized tab.** Automation kept the tab visible, so throttling was not measured.
  Chrome documents that intensive timer throttling (one wake-up per minute after 5 hidden minutes)
  is not applied while a page has a live `MediaStreamTrack`, which screen sharing provides. The page
  shows the measured scan spacing ("every 20.0 s") so a slowdown is visible; statistics use real
  timestamps, so a slower cadence lowers coverage, not accuracy. A minimized game window may stop
  producing frames; scans then report "No picture from the game window".
- Chrome's own **Stop sharing** button (handled by the track's `ended` event) and the leave-page
  dialog were checked only indirectly (a synthetic `beforeunload` is cancelled while tracking).
- Other resolutions, a stretched/fullscreen game, Edge, level-ups and character switches on a
  live client. The smoothed fallback exists for scaled HUDs but is tested only on Twitch frames.
- The `_headers` detach syntax (`! Content-Security-Policy`) on real Cloudflare Pages; the local
  preview implements it the same way.
- Name/job detection, level templates, bursts and band copies were verified offline on a saved
  native frame (template scan 1.2 ms on the band, identity OCR 34 ms); the live switch between two
  characters and a job advancement are not yet tested.
