# Personal EXP tracker in the browser (`/local`)

`msxp.pages.dev/local` tracks **your own** character without Twitch, Python or any install. You
share the MapleStory window from a desktop browser (tested: Chrome, Edge, Brave and Opera on Windows, Chrome and Safari on macOS; Firefox is not supported); the page reads the EXP bar every few seconds and
keeps the history in this browser. It is independent of the VPS, the API and the production
database: the page and its OCR runtime are static Pages files, and the page's Content Security
Policy allows network requests only to its own origin (`connect-src 'self'`), so readings cannot be
sent anywhere.

## Using it

1. Open `/local` and click **Start tracking**. Name, job and level are read from the game; a
   character is created or chosen automatically (you can rename it; history stays with it).
2. In the browser's sharing dialog choose **Window → MapleStory → Share**. The browser asks every
   time; the page cannot select a window itself. A window covered by other windows still captures.
3. The first scan finds the status bar (about a second), then scans every second by default
   (1, 5, 10, 20 or 30 s can be chosen; 1 s stores up to 86,400 readings, ~10 MB, a day). Changes are confirmed by a **burst**: an extra scan a second
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

The frame path checks for `ImageCapture.prototype.grabFrame`, not just `ImageCapture`:
Safari was reported (2026-11-13) to expose the constructor without that method, causing
"grabber.grabFrame is not a function" before OCR. It now uses the existing `<video>` fallback.
Synthetic tests cover that partial API, an absent API and the full API.

**Safari on macOS, measured 2026-11-13:** the video fallback captured the game at
1366×796, including the title bar. Its saved HUD pixels were softened; localization and
level 1 worked, but EXP OCR failed. `getCapabilities()` reported maximum dimensions of
1366×796. Applying ideal dimensions of 2732×1592 with `resizeMode: 'none'` still produced
1366×796; `getSupportedConstraints()` did not list `resizeMode`. The app copies these
video pixels at their supplied size, without resizing. Chrome on the same Mac was
reported to read successfully, and the earlier Chrome capture below supplied 2732×1592.
The same stream later read level 1 and `2 [13.33%]` successfully, with agreeing EXP OCR.
Name recognition still left the placeholder: offline replay of its name crop with the
vendored English data returned two identical correct smoothed reads, but the fallback
discarded names whose length equalled the glyph count. It now accepts two identical
valid whole-line reads regardless of glyph count; no new glyphs or fuzzy matching were
needed for this case. After the player refreshed to load the fix, the live Safari
session displayed the name automatically while EXP tracking continued (2026-11-13).
The tested Safari stream did not supply the sharper capture.
Pickup startup previously checked only `window.MediaStreamTrackProcessor`, incorrectly
rejecting Safari's worker-only implementation. The worker can now open a transferred
clone of the shared track; Chrome still passes its processor's frame stream. Startup
waits for the worker to confirm readiness, and failure releases the clone and restores
the 5 fps capture request. Synthetic tests cover both paths and startup failure.
Live Safari after refresh (2026-11-13): the pickup worker reported 15.0 fps while EXP
tracking continued. Item and meso counting accuracy on that capture has not yet been verified.
Later at `7 [46.67%]`, EXP OCR dropped the percentage decimal. The HUD pixels were
identical with pickups enabled (15 fps) and disabled (5 fps), and scans stayed one
second apart. The smooth numeric pass now uses threshold 125 to preserve softened
punctuation. With level evidence, candidates from both passes of the same frame are
checked together: the crisp pass can supply the number and the smooth pass the
percentage. Exactly one distinct pair must fit the EXP table; competing valid pairs
are rejected. Without level evidence, the two variants of one pass must still agree.
Offline replay with the vendored English data read level 1 and the exact pairs at
0, 2 and 7 EXP (including the pickup-on/off comparison); these are private fixtures.
Live Safari after refresh read `7 [46.67%]` and level 1, with pickups still at 15.0 fps
and scans every second. Further level-up and digit combinations remain to be checked.
At level 3, a later private crop showed `30 [52.63%]`; both smoothed line-mode reads
dropped the leading 5. A final smoothed word-mode pass recovers it, with the same
unique table-match requirement (or two agreeing variants without level evidence).
Offline replay reads all five saved HUD crops correctly, including that failure.
The word fallback has not yet been checked in the live Safari session.
These Safari passes (the threshold-125 smooth pass, the word-mode pass and the label-fragment retry) run only in
Safari since 2026-11-15: on private Twitch frames the unconditional threshold 125 made other browsers' smooth pass
misread (65.59% as `65.594.`, a number as nothing), which the word pass then recovered at 4–8 extra OCR calls per
failing scan. Other browsers are back to the earlier reads and call counts on those frames.
A later private level-23 crop showed `575 [1.68%]` but OCR read `57`, `5` or nothing.
The field retained a short upper fragment of the taller EXP label, and smoothing at
the usual 5×/6× magnifications joined the digit tops. When all existing passes fail,
the reader can exclude that leading fragment and retry at 3×/4×. The fragment must
touch the field's left edge, occupy only its upper half, follow a detected label and
precede another glyph; a full-height leading digit is kept. Existing successful reads
are unchanged. The same parsing, agreement and unique table-match rules apply.
Native replay reads all seven saved HUD crops correctly, including this failure;
grayscale-only preprocessing did not recover it and was not added. Live verification
of the fragment fallback is pending.
A later live Safari session (2026-11-15 UTC) read `919 [2.68%]` correctly but the
level preview contained only the final `3` of `23`. It resumed reading `23` without
user action; saved failing and recovered captures have identical badge pixels.
Failed automatic scans re-run HUD localization once a minute. The level search
previously began at the right edge of the sparse OCR `LV.` word, which can include
badge digits. In Safari it now begins at the word's left edge; orange pixels still
define the actual badge crop. Other browsers keep the original right-edge start.
Synthetic merged-label cases and native replay reproduce a
clipped `3` and recover the full `23`. The exact failing calibration was not saved,
so a merged label is a reproduced failure mechanism, not a confirmed OCR transcript
from that live scan. The new localization change still needs a page refresh for
live verification.
A subsequent Safari crop showed `931 [2.71%]` at level 23, but whole-field OCR
dropped the `7` from the percentage. The existing exact templates already matched
the `7`, `1` and decimal; only the `2` and percent sign were unknown. After the
other passes fail, Safari can retain those exact matches and OCR each unknown
glyph at two magnifications, requiring identical single-character reads. Conflicted
templates and fields with no known digit are rejected. The reconstructed percentage
still needs two agreeing number variants without level evidence, or one unique
table-consistent pair across observed candidates with level evidence. This fallback
does not run in other browsers or replace an earlier successful read. Native replay
passes all ten saved HUD crops; live verification after refresh is pending.
A later crop showed `955 [2.78%]`: the level and percentage read correctly, but
softened digit tops joined the EXP number into one component and OCR returned `98`
or `95`. After the other methods fail, Safari with level evidence retries the number
only, unsmoothed at threshold 150 and the normal two magnifications. The accumulated
number/percentage candidates must have exactly one table-consistent pair. A missing
level or an earlier successful reading bypasses this retry. Live Safari returned
`55` and `955` at the two magnifications, while native replay read `955` twice.
Requiring the two new numbers to agree blocked that live reading; the retry now
uses the regular reader's unique table-match rule and the tracker's existing
confirmation rules for baselines and suspicious changes; ordinary same-level gains
can be accepted immediately. Competing valid pairs remain rejected. The native
replay reads all eleven saved HUD crops, including the exact `955 [2.78%]` pair.
Live Safari after refresh (2026-11-15) accepted level 23 and `955 [2.78%]`, displayed
Tracking and updated its last-reading age to zero. This check used a manually fitted
EXP box made during diagnosis. Automatic localization had produced changing crop
heights and intermittent level OCR noise; that path and further digit combinations
still need live coverage. The Safari retry's acceptance rule is covered by a synthetic
case where one variant drops a digit and only the complete observed number fits,
plus rejection of two different table-consistent candidates.
A subsequent live value, `971 [2.83%]`, still failed whole-number OCR. Excluding the
short EXP-label fragment before segmentation made all three number digits match the
existing exact templates. Safari now tries that clean segmentation first; unknown
percentage glyphs can use the same two-agreeing-read fallback. An entirely known
pair needs no EXP OCR. A partial percentage remains an OCR result so accepted scans
can teach its new glyphs. The level read keeps the smoothed preprocessing used for
this softened capture; if it reads no badge, Safari can try the crisp pass, while
conflicting variants still reject the reading. Other browsers retain the original
glyph path. Native replay passes twelve HUD crops both with a fresh template bank
and with glyph learning between accepted frames. The live session later showed
`1,128 [3.29%]` and a fresh Tracking state using ordinary OCR; that observation does
not directly verify the new `971` glyph path. The player subsequently confirmed
that the refreshed Safari session read `971` correctly and continued tracking.
Other Safari versions and full-display sharing have not been checked.

**Safari native-font recovery, 2026-11-15:** seven later saves exposed the same
threshold problem across different numbers: one field-wide cutoff joins adjacent
strokes, while a firmer cutoff removes faint strokes. Generic OCR can also produce a
wrong number and percentage that happen to agree with the EXP table. The Safari path
now checks the existing seven-row EXP font using its character advances, without
requiring blank columns between digits. Each character must have a brightness cutoff
between 110 and 200 that reproduces every stroke and background pixel of its known
shape. All matching paths are considered; competing strings are rejected. Commas and
the percentage decimal must occupy their actual font cells, and strict parsing still
applies. This is restricted to Safari and the native seven-row font; other sizes keep
the existing readers. A fully matched number is retained if the percentage needs OCR.
Unknown or poisoned additional templates cannot supply a font match. On Safari native
frames, checked shipped shapes take precedence over learned entries: a live browser
had poisoned the canonical `6` as `?`, which prevented fresh-bank replay successes
from carrying over to that session. The live crop, exact regions and captured glyph
bank are now an additional private regression case. Other browsers retain their
previous template precedence.

Replay on the bundled browser OCR engine reads all **20** private HUD captures exactly,
as first and continuing scans, with fresh and learned template banks (80 checks).
The six new saves read EXP entirely from font shapes, including a case previously
misread as a different table-consistent pair. The replay now requires every saved HUD
case to succeed; it no longer permits the two earlier skipped captures. Synthetic
checks cover all two-digit combinations from 10 to 99, differing local thresholds,
invalid grouping and competing font matches. This is replay evidence; refreshed live
Safari behavior and other capture sizes remain to be verified.

A later debug archive contained six faded/black HUDs (correctly rejected before OCR)
and two bright crops of the same `7,492 [21.83%]` value. The percentage matched the
font exactly, while the number's softened `4` had no exact threshold match. The
fallback retained verified numbers but still re-read a verified percentage; OCR then
introduced both `21.82%` and `21.83%`, which can both fit truncation/rounding at that
EXP value. Safari now retains either verified field and OCRs only the unknown one.
Competing numeric candidates that both fit are still rejected. The saved live case,
with its exact regions and glyph bank, passes first and continuing scans with fresh
and learned banks, bringing the replay set to 21 HUD cases. After refresh, the player
confirmed that live tracking detected the correct EXP.

| Step | Module | Notes |
| --- | --- | --- |
| Locate the status bar | `hud.js` `locate` | One sparse Tesseract pass over the bottom 22 % of the window finds the `EXP`, `HP`, `MP` and `LV.` labels (the Python `discover_regions` geometry). Boxes are saved normalized with the window size. Without `LV.`, the level box is a strip left of HP. |
| Copy the HUD rows | `app.js` `grab` | Once boxes are known, only the band of rows holding them is copied (1368×56 instead of 1368×800 in the test). Detection and the preview use full frames. |
| Fit the fields | `reader.js` `fieldBoxes` | Each scan finds the two olive-green brackets around the percentage in pixels, trims the `EXP.` label (it is taller than the digits) and finds the orange level tiles. Without both brackets the field is treated as hidden or covered. |
| Read EXP | `glyphs.js`, `reader.js` | Learned glyph templates first (exact pixels, ~2 ms). Otherwise Tesseract reads the number and percentage separately at two magnifications, then a smoothed pass for scaled HUDs (Safari adds a word-mode fallback). Level evidence permits one unique table-consistent pair across observed candidates; without it, both variants of one pass must agree. |
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
back to Tesseract. The HUD digits ship with the page (`HUD_GLYPHS`), so the first scan reads at once;
learned templates are stored in this browser and add to them, one
set for every frame of game pixels (a native window, or a stretched one read unstretched) and one per
other window size, so a size used before reads at once. In the live test 11 templates were learned within two minutes
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
- **Percentage-only HUD** (`EXP. [78.63%]`, no number before `[`; common at higher levels): the same
  rules as the Twitch tracker (`shadow_types.parse_percentage_only`, `product.percentage_exp`). The field
  must be exactly `dd.dd%` within 0.00–100.00; the level comes from the badge alone (no EXP table can check
  it) and must have a published requirement; EXP is the estimate `percentage × requirement`, rounded half
  up, shown with "≈". The number box counts as empty when its bright ink covers less than 60 % of the digit
  band (the label's dot does not). Stricter than the numeric path, because a blurred 7 can read as 2 in both
  OCR variants: a change of more than 1 percentage point must repeat and then starts a baseline rather than
  counting; a level-up counts only when the percentage reset (a badge misread as the next level does not);
  only crisp-pass reads teach percentage glyphs, and a smooth-pass agreement that contradicts a valid crisp read is
  refused. Measured on 28 private two-feed stream frames (levels 71–72, compressed 1080p): 24 showed the field and
  all 24 were detected as percentage-only; 17 read, all correct except one whose badge also misread (level 4 for
  72, which the tracker treats as another character, never a gain); 7 were skipped. Before the contradiction rule
  the smooth pass read three leading 7s as 2. Cost: 4–6 OCR calls on a scan that needs OCR; a native-size window
  reads with the shipped glyphs. Numeric HUD frames read as before. Not yet seen on a live high-level client.
- **Gains**: only endpoint differences between consecutive accepted readings in the same session.
  A confirmed break starts a baseline whose difference is never counted. A confirmed +1 level-up
  inside the gap limit with a published requirement counts `to_next − previous EXP + new EXP`.
- **Identity, automatic and by pixels**: the name line's exact bitmap identifies the character. A
  different bitmap must repeat on three scans a second apart. Then the page switches to the
  character with that bitmap; or gives it to the character being tracked if that one has no name
  bitmap yet and the reading fits its history; or creates a character named by OCR (a glyph
  identical to a digit learned from the EXP bar is that digit,
  and any other OCR `0` is the letter O). Names are read at four magnifications with votes pooled
  per identical glyph (one misread letter is outvoted). When touching letters prevent alignment,
  two agreeing whole-line reads of the smoothed crop can label the bitmap; that also handles blurred
  glyphs whose count is unchanged. **Letters are learned like digits**, from
  verified text only: every job line that matches the job list, and every rename you type
  (authoritative); a name whose glyphs are all known is read without OCR. Only scans whose level
  matches the EXP table count toward a change, so logout fades and loading screens cannot.
  An unreadable but stable name becomes "Character N". A name read by OCR (never one you typed) is
  re-read once per session and corrected if the better reading differs. Because identity is
  the bitmap, a misread name only mislabels a history, it never splits or mixes one; renaming keeps
  it. Choosing another character by hand while the game shows a known name switches back.
  Errors are accepted as on the live site rather than asking for confirmation. Measured live: a
  new level-1 character was created and named automatically; its level-up 1→2 was confirmed by a
  one-second burst scan and its cross-level gain (15 − 13 + 8 = 10 EXP) counted exactly.
  Switching among three characters on the live client: a new character was created and named
  automatically, and returning to a known one switched on the third confirming scan (about 3 s
  after its HUD reappeared), by bitmap alone with no OCR; loading screens were skipped.
- **Job**: a changed job line must repeat on two scans; OCR is matched to the 15 known jobs (at most
  two edits, and never between two equally close jobs, e.g. the two Wizards).
  If the crisp reads fail, a smoothed threshold-125 pass still needs two identical reads.
  On a private Safari Swordsman crop (2026-11-13), four crisp spellings disagreed while
  the smoothed reads agreed correctly; replay also preserved Beginner on five earlier crops.
  A failed read keeps the last job and retries after 30 seconds rather than marking that
  bitmap as successfully labelled. Each capture rechecks the job, recovering older cached
  failures that left the default Beginner label. Live verification of this fix is pending.
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

IndexedDB `msxp-local` (version 3): `characters` (name, job, name/job bitmaps, last accepted
reading, tracker state, all-time gain), `sessions` (start/end, end reason, counts per scan outcome),
`readings` (accepted readings only: time, level, EXP, basis points, gain, kind; about 115 bytes
each), `days` (one row per character and local calendar day: last reading and EXP gained),
`pickups` (version 3: meso and item pickups, see below) and `settings` (interval, window,
calibration, glyph templates, overlay options, active character, Track pickups).

**Edit** opens a popup with the character's name and job and *Remove tracked data*: between two
times (default the last 15 minutes) it lists the EXP, mesos and items tracked, and removes the kinds
ticked (only kinds with data are offered; two clicks). Removed EXP keeps each reading's level and
EXP but drops its gain, so that time counts as not observed (rates are not lowered) and the day and
all-time totals fall by it; removed pickups are deleted. Days older than the 24 hours of detail keep
only a summary, so EXP there is removed by whole local days the range covers (the day's History point
and its gain).
Times are the browser's local time, labelled with its zone (e.g. "EST · America/Toronto"). The popup
also has *Clear all local history* (two clicks), like the page's data section.

**Live rate** (beside Pickups on wide screens, below it on narrow ones) draws EXP or mesos per hour as
a smooth line, one point per second, scrolling with the clock (`local/live-chart.js`, canvas, about 30
frames a second, paused while hidden or off screen). Each point is what was gained in the last 5, 10,
15, 30 or 60 minutes (the pills) over that span, or over the time since the first saved gain while shorter
(at least a minute), starting at the third gain. It uses the saved 24 hours, not only this session, so it
survives a refresh, and always runs to now: quiet time (not tracking, nothing picked up) counts as nothing
gained, so the line slopes down toward 0 until gains resume (unlike the EXP progress charts, where missing time is never zero). A
6-second moving average turns each step into a curve; hovering shows the nearest second. A dot with a
slow pulse marks the tip (now) and a faint light sweeps along the line every 3.2 s; rates under 1 an hour
count as 0 (the eased line only approaches 0), so an idle card shows 0 and no time to the next level. The Pickups
panel's *Mesos / hour* uses the same rule over the page's selected window.

The pop-out overlay has two local-only layouts. **Live** (360x290) mirrors the Live rate panel: the big
number is the line's tip (the drawn, eased value) over the panel's window ("Last 5/10/15/30/60 min",
read from the saved setting and followed when it changes), for EXP or mesos (*Live shows*), with the other
one, % of level and EXP below; the time to the next level uses the same EXP rate, so every number on the
card agrees with the line. The page's "/ hour now" note quotes the same eased value. **Items** (360x215)
shows up to 12 items picked up in the last 24 hours with their icons and counts. *Branding* shows or hides
a small msxp.pages.dev line on both. They refresh when the tracker tab saves a reading or a pickup
(BroadcastChannel) and draw the line themselves.

The round button in the character card's header switches the live pages' scenery (town background,
wandering mobs; `local/scenery.js` mirrors `product.js`) on or off; on by default, remembered.

**Retention like the live site**: detailed readings are kept for **24 hours + 5 minutes** (plus one
older boundary reading per character), pruned when tracking starts and hourly while it runs. Days
are kept indefinitely: about 200 bytes per character per day, so a year of one character is about
75 KB. Each accepted reading updates its day row in the same transaction, so pruning loses nothing
the History chart uses. Version 1 databases are migrated by folding existing readings into days.
Outside `?debug`, no frames are stored. Debug mode can retain failed HUD crops as described below. The other pixel data kept are the learned bitmaps: single HUD characters
(about 35 pixels each) and each character's name and job lines, which are needed to read without
OCR; *Clear all local history* deletes them.
Sessions left open by a crash are closed at their last reading on the next visit. Only one tab
of a browser profile can capture (Web Locks `msxp-local-capture`, released automatically when the
tab closes); a second `/local` tab says tracking is already running and leaves that session open. *Export JSON*
downloads tracking history (debug crops use their own archive); *Clear all local history* (two clicks) deletes the database.
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

Second live run (same day, after name/job detection, level templates, bursts and band copies;
5-second interval chosen by the player):

- A character named by hand ("CharA", no name bitmap) was given the on-screen name and job
  (Beginner → Swordsman) automatically: three one-second burst scans agreed on the name bitmap,
  then OCR labelled it.
- Steady scans copied 58 of 800 rows and read level and EXP from templates only: 14–26 ms wall time
  per scan, no OCR. The OCR engine ran 12 times in the session (66 ms): detection, the level until
  its digits were learned, and the name/job labels.

Offline replay of the 26 labelled Twitch frames (`samples/live-regression`, compressed and scaled,
not the target input): no reading was accepted with a wrong value. Most are rejected or not
located (overlays, third-party trackers, scaled layouts); manual calibration is the fallback there.

## Pickup messages (Track pickups)

On macOS, one Chrome window capture reported 2732×1592. Its pixels were doubled on both axes.
The extra height is consistent with window chrome. Keeping the 2× vertical scale in both the HUD
and pickup readers preserves the original text rows. On a 43-second, 251-frame pickup recording,
offline replay with the same sharper filter on both runs resolved 6 item messages instead of 2
and left 3 unread messages instead of 11. The recording had no inventory tally. Offline HUD
replay also read the name, job and level, including one badge with the game cursor at its lower edge.

**Track pickups** (off by default, remembered) reads the game's pickup messages while tracking and
keeps meso and item pickups in IndexedDB (`pickups` store, 24 hours like readings; included in the
JSON export and deleted with the character). EXP messages are read but never kept: EXP comes only
from the EXP bar. Items are kept only when the name matches the item list (`local/items/`, built by `tools/build_local_items.py`
from maplestory.io's copy of the Classic World client data: 1,978 non-cash Equip, Use and Etc items, one per name;
the client data has no drop tables; the NiaDB monster-drop build is kept as a backup source); unread messages are
dropped. The Pickups panel shows mesos per hour (see Live rate), mesos in the last 24 hours, and the items picked up with their icons. With `?debug`
a log lists every message as read. Not yet in the OBS overlay; the learned message font is saved
(setting `pickupFont`; the older `messageFont` held shapes misread before word alignment and is ignored), one
font for game pixels and one per other window size, so reading starts from it next time; *Clear all* resets it.
Every browser starts from a shipped font (`message-font-base.js`, 57 characters learned from recorded play).
Learning is local to this browser; a Safari-specific shipped starter font has not been calibrated.
Use an ordinary window to retain learning between visits: Safari Private Browsing uses
[ephemeral website storage](https://webkit.org/tracking-prevention/).

`local/pickups.js` follows the message stack in the bottom-right corner (pickup-worker.js, 15 fps).
Chrome creates `MediaStreamTrackProcessor` on the page and transfers its readable stream;
Safari transfers a cloned track and creates the processor inside the worker. Both use
the same frame cropping, message detection and OCR. Stopping terminates the worker,
releases the clone and restores the shared track's 5 fps request.
With `?debug`, the pickup status also shows the cumulative number of frames with detected
text and messages sent to OCR. The log appears after a tracked line leaves the screen
and its OCR finishes; an empty log alone does not distinguish detection from OCR failure.
**Save pickup area (debug)** downloads the next detector frame from the pickup worker
when running, or a fresh crop from the page capture otherwise. Worker snapshots include
`worker` and the source frame size in the filename; the status also shows that size.
This matters when a browser's processor and video element deliver different pixels.
The first live worker snapshot (Safari, 2026-11-13) exposed a capture error: the
9-argument `drawImage(VideoFrame, ...)` squeezed the entire 1366×796 window into the
342×350 destination instead of cropping the requested corner. The earlier page-video
snapshots cropped correctly, hiding this difference. The transferred-track worker now
draws the whole frame at its supplied size, then crops with `getImageData`; a second
live snapshot confirmed the correct corner. The Safari recorder crops its video element
directly for the same reason. Chrome's streamed-frame crop is unchanged. Pickup totals
with this correction still need a live comparison against visible messages.
**Automatic EXP failure collection (`?debug`):** starting tracking also collects failed
HUD reads and table-rejected readings in this site's IndexedDB. Each lossless PNG is
stored separately, with the actual scan regions, glyph bank, previous level, reader
identifier and raw OCR result. Identical EXP/level-region pixels, regions and failure reasons reuse
one entry with a repeat count. Successful scans do not create images. Normal tracking
without `?debug` does not collect them.

**Save EXP issues** downloads one `msxp-exp-TIMESTAMP.tar` containing `frames.bin` and
`index.json`; stopping tracking also attempts one download if new cases were collected.
A blocked or cancelled download does not remove the originals. Reloads retain the
saved cases in a normal browser session; private browsing or clearing site data can
remove them. **Clear saved EXP issues** removes only these diagnostics, so save the
archive first. Nothing is uploaded, and they are excluded from the history JSON export.

Collection holds only the current crop's bytes in JavaScript, rather than previous
PNGs. The on-disk limit is about **50 MB including scan metadata, or 5,000 unique
cases**. At the limit, the button says **full** and collection pauses until cleared;
tracking continues. Exporting constructs one archive from stored Blob records and
can temporarily use additional browser memory. The six recent 1366×796 examples crop
to about 21 KB each (575×33), versus 415–450 KB for their full HUD strips, before scan
metadata. This does not reduce the OCR engine's own memory use. Storage quota errors
also pause collection; earlier samples remain available. Live Safari collected five cases and exported one 181 KB archive successfully; those
cases also exposed changing HP/MP pixels between the regions, which are now excluded
from duplicate fingerprints. Real browser IndexedDB tests verified Blob persistence
across reload, duplicates, cap rejection and isolated clearing in a disposable Chrome
profile. Safari storage-quota behavior still needs live verification.

**Record pickups (debug)** uses the page processor where available, or snapshots of the
shared video in Safari. With a directory picker it keeps the existing `frames.bin` and
`index.json` folder format. Without one, it records at most 30 seconds or about 32 MB in
memory, then downloads `msxp-pickups-TIMESTAMP.tar` containing `frames.bin` and `index.json`.
Safari dropped the frame download when these were triggered separately, so they now
travel together. Extract the archive into a private folder for the replay tools. Synthetic tests
check the binary offsets, metadata, frame cleanup and both output paths.
The text is light grey with a dark drop shadow one pixel right and down, so a text pixel is a light
pixel whose down-right neighbour is much darker; over white clouds the fill itself is invisible and
only that rule keeps the letters solid (any darker neighbour drew them hollow there). Each new
message enters at the bottom slot and pushes every line up 14 px, three or four can arrive in one
frame, and the whole stack fades out together. Each frame picks the shift that best explains the
lines; lines on screen when tracking starts are followed but not counted. A message is reported once
its line leaves the screen, with up to four masks of it (a mask unlike its first is another line
and is dropped).

Safari's unscaled worker-track capture uses a softer mask (brightness floor 110,
stroke/shadow difference 60, instead of 150/100). The earlier 70/30 calibration
included too much scenery in the letters. Only the transferred-track path at 1× uses
this calibration; streamed and unstretched larger captures keep the existing mask.
An unread message also gets a word-mode OCR attempt; a parsed reading is kept.

Six private Safari recordings, 2026-11-13: 542 frames, about 62 seconds, including
controlled item drops and meso amounts. Controlled Etc/equipment clips supplied mask
calibration examples; rock, moving-background and single-feather clips supplied replay
checks. The following compares the previous 70/30 reader against the final production
reader, using native Tesseract with the vendored English data and the actual detector,
stack tracker and message reader. Both fresh fonts and a font learned by the previous
reader passed exact item/count and amount checks.

| Clip | Correct item pickups, before → after | Mesos read, before → after | Visible mesos |
| --- | --- | --- | --- |
| Rock, burst pickups | 0 → 8 | 0 → 107 | 119; final +12 begins at the recording edge and is missed |
| Moving background | 3 → 3 | 75 → 89 | 89 |
| Single Stiff Feather | 0 → 1 | 0 → 0 | 0 |
| Controlled Etc items | 7 → 10 | 21 → 21 | 21 |
| Equipment and 10/100/888 amounts | 7 → 7 | 110 → 998 | 998 |
| Already fading tail | 0 → 0 | 0 → 0 | Inherited on-screen message correctly excluded |

All 29 item pickups resolved correctly, including both Stiff Feathers; all 17 counted
meso amounts matched the visible digits. No incorrect counted item or amount appeared
in this small calibration/replay set. This is not a general accuracy guarantee or a
live Safari measurement. The more selective mask loses some very faint still-frame
reads: five parsed lines on the four older snapshots fell to one; whole recordings
can read a notification earlier while it is bright. Live verification is pending.

On the same Safari path, meso OCR keeps the final 100 game pixels with `(+amount)`
delimiters rather than trusting the glyph-derived digit box: blur made the plus look
like an opening parenthesis and cropped +13 to 3. At least one delimiter is still
required. Known digits from partial font reads are retained even when the fixed words
cannot be classified; previously `(+888)` was discarded when `gained` had unknown
letters, allowing an OCR 808 to win. Item-count OCR and other capture paths are unchanged.
Experimental Safari font banks and alternate stroke thickening did not improve these
checks and were not shipped. Existing local learning remains available.
Reading (pickup-session.js) first tries the message font learned during the session
(message-font.js): every confirmed reading teaches it each glyph of its lines, and a line it reads
completely needs no OCR. Otherwise every mask is read whole by OCR (strokes thickened to 2x2 first),
and the amount, "xN" count, tab and name are taken from those reads, from the font's partial reads
(known digits) and, when they disagree, from OCR of just those parts, voting across the masks. Item
names are matched to the item list allowing OCR slips; an unread tab is the named item's own.
Fuzzy item names must be at least two edits ahead of the runner-up, including within the
usual typo allowance: the live OCR text `Sift Feather` previously chose Soft Feather
(one edit) over Stiff Feather (two edits). It now stays unresolved and cannot teach that
wrong item name. Exact names still match. This rejects uncertainty rather than correcting
the letters from an assumed drop; the original feather pixels were not recorded.
Each line is also added up over every frame it is on screen (a pixel is text when it is text in 45% of them, so scenery
drops out), and item names are compared shape by shape with every item name before OCR is asked
(`matchName`). Measured 2026-11-12 on the three recordings with the shipped font: unread lines 14 to 10 and
2 to 1, three garbled names resolved ("Biift Feather" to Stiff Feather), no wrong items; on 63 saved item
lines the shape match agreed with all 42 earlier matches and found 20 more. Meso
amounts are approximate by design: an unconfirmed amount is rounded down to the digits the reads
agree on ("23" and "28" count as 20).

Measured offline on two private recordings, against hand-counted arrival windows and the inventory's
meso total:

| Recording | Arrivals in windows | Counted | Mesos read | Unread |
|---|---|---|---|---|
| 118 s, clouds, grass, dark rock; slow looting | 56 | 50 | 22 messages, +356 of +497 | 2 of 65 |
| 127 s, scrolling camera, bursts of 3-4 per frame | 62 | 51 | 15 messages, +195 of +255 | 15 of 51 |

- Live, 5.5 minutes of looting (144 messages, 14.8 fps, ~3.5 ms per frame, never behind): the EXP
  messages added up to +1,160 while the EXP bar gained +981. Four lines had been read as +100 each
  ("(+13)" with ")" read as a digit, rounded down); without them +760. Amounts with no bracket
  around them are now refused and rounding follows the digit count most reads agree on.
- The live test before these changes reported 367 messages in 2.5 minutes: while the camera
  scrolled, the old masks changed by 30-45 pixels a frame and every line looked new.
- Not solved: faint single lines over bright cloud are sometimes missed (counts run ~10% low); a
  full stack of identical lines ("+13" six times) looks the same after one more; letters whose
  strokes touch merge into one glyph, so the font learns few lines; "x1" often reads as "A".
- Four more recordings, 2026-11-12: 1920x1080 with the sharp filter (4.1 min); 1368x800 bright clouds
  (4.6 min); two in Perion with fog drifting over the corner (5.7 and 4.3 min). The last has a meso total
  from the inventory (+965). Two mask fixes, measured on all of them:
  - The pixel inside a letter next to the stroke's own shadow (the top of an "8") is no longer text, and a
    stroke continued down-right must be about as bright as the stroke (within 20): dim fog beside a ")"
    was text, so "(+10)" read as +100.
  - An unknown glyph that splits into two known characters ("0)" touching) reads as both.
  | Recording | Before | After |
  |---|---|---|
  | 118 s, slow looting (truth +497, 56 arrivals) | +357, 50 counted, 2 unread | +438, 54 counted, 1 unread, every item right |
  | Fog, 4.3 min (truth +965) | +720, 9 unread | +960, 4 unread |
  | Fog, 5.7 min (no total) | 18 unread, 10 of 31 amounts rounded | 12 unread, 6 of 40 rounded |
  | 1080p sharp filter (no total) | 39 meso lines, 2 unread | 44 meso lines, 2 unread |
  Glyphs the shipped font cannot name fell from 13% to 6.5% (slow looting) and from 30% to 19-20% (fog).
  The mask costs ~0.9 ms a frame instead of ~0.7 (worker, 15 fps). A "+12" read as +173 in the first fog
  recording no longer happens. Still missed: a whole stack replaced between two frames (the recorder dropped
  to ~7 fps there) counts only the lines that look new; meso lines that differ only in their last digit
  can trade samples, and the amount is then rounded. Raising the mismatch cost, or comparing only the
  amount's columns, tripled the count (fog moves a line's right edge from frame to frame).
  The recorder (`?debug`, "Record pickups") saves up to ~10 frames a second: ~7 at 1368x800, ~2.6 at 1080p.
- Glyphs the mask lost are read from the line's brightness (each line keeps it beside its mask): a learned
  shape predicts its strokes light and their drop shadows dark, which stay dark over white fog. Only for
  glyphs the mask read cannot name. Fully font-read lines: 42 to 72 (fog, 4.3 min) and 54 to 85 (fog,
  5.7 min); 9 reads changed across six recordings, each from unsure to a value checked on the frames
  (fog 4.3 min: +960 to +965 of +965). Font reads also stop counting at the acceptance limit and remember
  exact glyph shapes per font (emptied when it learns): page time per message ~52-65 ms to ~3.5-6 ms, the
  same text on all 1,498 samples; OCR time per recording about halved. Pickup reading has its own OCR
  worker (~50 MB, measured in Node), so EXP scans never wait for it. Not verified live yet.
- Counting bursts (2026-11-12): while following the stack, the worker reads the end of each unclear line with
  the shipped font. Two lines whose numbers read in full and differ ("+35", "+38") are different messages; equal
  meso/EXP amounts, or item lines whose names read alike, count as one. Only the number is compared: whole-line
  text ("gained" read as "qained" between frames) added messages that were never there. Calm frames (cheaper
  than one new message by pixels) read nothing. Never over a known total on six recordings:
  | Recording (true mesos) | Before | After |
  |---|---|---|
  | Slow looting (+497) | +438 | +438, items unchanged |
  | Perion fog, 4.3 min (+965) | +965 (duplicates hiding misses) | +955; three lines of a 16-line burst found |
  | Perion fog, 7.5 min (+1,466; shells +12) | +1,269, shells 14 | +1,193, shells 12 |
  | Burst, 13.5 s (+244) | +88 | +129 |
  Still over in one place: a fog burst at 257 s of the 7.5-minute run counts six "+11" where three arrived (before:
  the same six and two "~10" more), as nearly every number there reads incomplete. Cost: the tracker
  takes ~0.3 ms more a frame in clear maps and ~0.8-1.0 ms in fog (worker, 15 fps). A stack swapped whole
  between frames is still undercounted when the reads are incomplete (fog).
- Shipped font, 2026-11-13: every checked variant kept, up to one more per character picked from ~32,000
  labelled glyphs (six recordings and a player's learned font; complete shapes only, digits checked by eye),
  then tested on three recordings it was not picked from. Glyphs there: 90.5% right / 1.78% wrong / 7.7% unknown
  before, 95.6% / 0.35% / 4.1% after. Lines the font reads alone (same counting): 108 to 134 of 209 (Perion fog,
  7.5 min); OCR falls back less. A first pick that dropped the shipped "g" with its full hook read "gained" as
  "qained" and lost line reads: the checked shapes are now always kept. With the better font a disagreeing number
  at full weight (100) counted 36 mesos too many on the 4.3-minute recording, so it now weighs 50. Totals: +438
  (of +497), +953 (of +965), +1,133 (of +1,466; the fog burst at 257 s now counts its three "+11" exactly),
  +129 (of +244). One phantom "+11" remains in the 5.7-minute fog recording (76 s, a fog shape taken for a line in
  an empty slot); weighing such lines less removed it but lost up to 9% of real messages, so it stays.

## Not yet verified

- **Hidden or minimized tab.** Automation kept the tab visible, so throttling was not measured.
  Chrome documents that intensive timer throttling (one wake-up per minute after 5 hidden minutes)
  is not applied while a page has a live `MediaStreamTrack`, which screen sharing provides. The page
  shows the measured scan spacing ("every 20.0 s") so a slowdown is visible; statistics use real
  timestamps, so a slower cadence lowers coverage, not accuracy. A minimized game window may stop
  producing frames; scans then report "No picture from the game window".
- Chrome's own **Stop sharing** button (handled by the track's `ended` event) and the leave-page
  dialog were checked only indirectly (a synthetic `beforeunload` is cancelled while tracking).
- Other resolutions: a 1920x1080 window measured 2026-11-11 draws the game's 1366x768 screen
  stretched about 1.4x, so text is blurred: EXP digits 11 px tall instead of 7, and OCR read 7 as 2 on
  some passes. The HUD is now read unstretched, like the pickup corner below: the scan's rows are
  turned back into the game's own pixels, so the digits learned on a native window read at 1080p too.
  Measured live 2026-11-11 (1080p, 768p, 1080p): 212 of 212 scans read from learned digits, each switch
  2 s. Before, stretched digits looked different at every position (53 learned shapes) and the first
  minutes skipped scans. The EXP table picks, among a pass's OCR readings, the one that fits the level
  (badge or last accepted), requiring one distinct matching pair across the passes of that frame.
  The game's 1080p filter setting stretches sharply instead (each screen pixel the
  area-weighted mix of the game pixels it covers; measured 2026-11-12): the HUD is then undone with that model,
  chosen by whichever one makes the exact digits match (20,679 [84.74%] read exactly; bilinear lost the
  percentage). Pickup reading keeps the bilinear model; it read the filtered screen fine. A name bitmap is kept per screen
  size, adopted when the EXP carries on from the character's last reading. Pickups at a stretched
  size: the game's bilinear stretch is undone in the message corner (least squares per row and column,
  factored once; ~12 ms a frame, only when the window is >3% wider than 1366), so the detector sees the
  game's own pixels. Measured on a 2-minute 1920x1080 recording: 64 messages, 22 meso amounts read (1
  rounded), EXP messages ~317 against +364 on the EXP bar. Assumes the window shows only the game (no
  title bar). Edge, Brave and Opera: work (reported by the player, 2026-11-13); Firefox: not supported;
  Safari: window capture and later EXP OCR worked on its softened 1366×796 stream (see above).
  800x600 (2026-11-13, one screenshot): the game draws its interface at
  the same pixel size, so windows not wider than the game's screen now use the shipped HUD glyphs and pickup
  font (the HUD read Lv. 22, 19,671, 67.88% with them, nothing without; the HUD box was found automatically).
  The pickup area is at least 300 px wide (the right quarter, 200 px, dropped 5 of 6 lines including both meso
  lines). Firefox is not supported; the page says so and suggests another browser. Not verified: level-ups and character switches on a live client. The smoothed fallback exists for scaled HUDs but is tested only on Twitch frames.
- The `_headers` detach syntax (`! Content-Security-Policy`) on real Cloudflare Pages; the local
  preview implements it the same way.
- A job advancement on the live client (job detection was verified on Beginner and Swordsman).
