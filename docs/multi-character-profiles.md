# Multi-character public profiles

A Twitch channel can own several characters (automatic switching keeps one ID and
history per character: Alpha → Beta → Alpha reuses Alpha). `/stream/CHANNEL` now lets
visitors browse every saved character. Selection on the page is **view-only**: the
database's selected character is changed only by automatic OCR (or an operator).

## Page

- With **two or more** saved characters, a one-row strip appears under the name: name,
  level, and either `● Tracking` (the character being captured now) or the age of its
  last reading. The character being *viewed* is highlighted (`aria-current`).
- Order: tracked character first, then most recently seen. The row scrolls
  horizontally (touch, trackpad, Tab, ←/→/Home/End) with an edge fade when more exist.
  From 7 characters an **All N** button opens a searchable list.
- Over the strip, an unmodified vertical mouse wheel scrolls the cards horizontally;
  at either edge it returns to normal page scrolling. Horizontal trackpad input stays
  native. Desktop mouse users can also drag (6 px threshold); releasing a drag never
  opens a character. Touch swipes, keyboard links and the separate menu remain native.
  The strip scrolls freely without snapping, keeping small wheel deltas and dragging responsive.
- **One** saved character: no strip, labels or space; the page is unchanged.
  The strip appears on the next poll when a second character is saved.
- Clicking a character sets `?character=ID` (shareable, back/forward work). Clicking the
  tracked character removes the parameter and follows live tracking again. A viewer
  who chose a character stays on it while tracking switches elsewhere; polling continues.
- An inactive character shows only its own saved reading, level, rates (labelled
  "last observed"), 24h total and charts, with status
  `Not currently tracked · last reading …`. Charts and rolling windows remain relative
  to now, so a character not played for hours shows empty short windows and its
  24-hour bars; beyond 24h only the saved level/reading remain (retention).
- The homepage defaults to **Streamers**, preserving the existing one-row-per-channel
  cards, sorting and statistics. **Characters** lists every saved genuine character,
  including unplayed records, with saved level, channel, selected-for-tracking status
  and dated last reading. Search by name/channel; sort by last seen, level or name.
  Historical pace is never used to rank these rows. The selected-for-tracking status
  does not assert the stream is live. OBS overlays continue to follow the tracked character.
- Homepage toggles use `?mode=characters` (omitted means Streamers), update without a
  page reload and support Back/Forward. Every character entry links to
  `/stream/CHANNEL?character=ID`; identical names on different channels remain separate.

### Placeholder

The configured pre-recognition label `PendingOCR` (`PLACEHOLDER_CHARACTER`) is shown
as `—` on every public surface and is never a roster entry or counted for the strip.
Only that exact label matches. Records, attribution and OCR safeguards are untouched.

## API

`GET /api/players/CHANNEL?character=ID` (with the existing `history`/`tracked`
revision parameters). Every character body now also carries:

- `roster`: `[{id, label, level, last_seen_at, current}]`, placeholder excluded.
  `level` is the tracked character's displayed level, otherwise its validated level
  floor (or retained display level). `last_seen_at` ignores identity-held frames.
- `view`: `{character_id, current}`.

`ID` must be a roster entry of that channel: malformed → 400 `invalid_character`;
placeholder, unknown or another channel's ID → 404 `unknown_character`. Omitted, blank
or the selected ID → the normal channel entry. An inactive view carries no coordinator
activity (`historical_session`) and Twitch status `not_applicable`.

`GET /api/players` is unchanged. `GET /api/players?mode=characters` returns
`{characters: [{channel, id, label, level, last_seen_at, current}], served_at, warming,
truncated, experimental, poll_seconds}`. This uses the publisher's existing compact
rosters, with no inactive card/window/chart calculation and no new view registrations.
Invalid or repeated modes return 400 `invalid_mode`.

## Implementation and limits

- `select_runs`, `replay`, `recent_snapshot`, `aggregate` and `Diagnostics.card` take an
  optional explicit `character` (default: selected, so existing callers are identical).
  An inactive character is read from its latest session via `Diagnostics.character_session`,
  which checks channel ownership. Nothing is ever selected, temporarily or otherwise.
- The background publisher builds views on demand, like channel entries: requests
  only present published bodies. At most `MAX_VIEWS = 8` distinct views exist across all
  channels. A ninth view replaces the least recently polled view, so visiting characters
  9–12 works immediately, without waiting for the 60 s idle expiry. Eviction also drops
  its failure and presentation caches. A view is dropped immediately when its character becomes
  selected or its saved data/corrections/renames/retention change, so it is never served
  stale. Checkpoint and ETA caches were enlarged for these views (80 / 33 entries).
- The first view request answers `warming_up` (≈ one refresher step), as cold channels do.
- Due tracked-channel publications take priority over historical view builds; each
  refresher step still builds at most one card. Simultaneous demand for more than eight
  inactive profiles can cause eviction/rebuild churn; this is a cache, not eight permanent slots.
- Roster queries use indexed session lookups, at most 64 characters per channel and
  the existing 25-channel publisher limit. Retained display fields are extracted in SQL;
  roster building does not unpack complete frozen checkpoints. Saved characters with
  no session have empty profiles, never the selected character's statistics.
- The autonomous discovery cap remains 16 per channel; no recognition or attribution
  policy, schema, deployment setting or global character linking was added.

## Synthetic demo (no Twitch, fictional streamer)

Writes only `private/character-demo/demo.sqlite3` (with a `synthetic` marker). Uses the
real automatic attribution path with generated frames: `PendingOCR` discovers Alpha
(Lv. 67), switches to Beta (Lv. 43), returns to Alpha, keeping Alpha's ID.

```powershell
Set-Location 'H:\Desktop\codex\msclassic-character-name-ocr'
$python = 'H:\Desktop\codex\msclassic-twitch-exp-tracker\.venv\Scripts\python.exe'
$env:PYTHONPATH = (Resolve-Path src).Path
& $python tools/character_demo.py create --replace   # --replace only for a previous demo
& $python tools/character_demo.py serve --port 8890   # Ctrl+C stops; 8765 is refused
```

For the twelve-character scenario, **stop the demo server first**, then run:

```powershell
& $python tools/character_demo.py create --replace --characters 12
& $python tools/character_demo.py serve --port 8890
```

Use `--characters 1` instead to verify the selector is entirely absent. Omitting
`--characters` retains the original Alpha (67) → Beta (43) → Alpha demo. The twelve
characters have levels 43–54, ending on Mu. None are real streamers or OCR samples.
Never rebuild the demo while its server is running. These commands only replace a
previous marked synthetic database under `private/character-demo`; no capture starts.

Open `http://127.0.0.1:8890/stream/synthetic_demo`. In a second terminal (same three
setup lines), `& $python tools/character_demo.py switch` appends two fresh frames of the
next saved character (alternates Alpha/Beta in the default demo): the open page shows
a live automatic switch. Both generated frames have fresh independent evidence and
the real writer still holds the first frame and switches on the second. Timestamps are relative to
`create`; re-run `create --replace` for fresh recent windows.

The returning character resumes its own last publicly validated whole-EXP endpoint,
also requiring matching high-quality name evidence. Raw switch-out attempts can contain
an ownership-held frame of the *other* character: unwrapping that frame caused Beta's
57.24% → 23.24% demo regression. The generator now reuses the existing numeric/history
validators and rejects held, rejected, stale, duplicate and mismatched-name baselines.
No tracker guard was relaxed. Quick successive `switch` commands retain ordered times;
missing usable history or nearing a synthetic level-up fails with a rebuild instruction.

Open the homepage at `http://127.0.0.1:8890/`, toggle Characters, search, sort and open
a direct profile. `http://127.0.0.1:8890/?mode=characters` starts in that mode.

## Validation

- `tests/test_character_profiles.py`: A→B→A→B IDs/sessions; increasing own numeric
  endpoints in actual public responses and chart readings; held/rejected/stale/wrong-name
  baseline rejection; per-character totals and
  charts; explicit character equals selecting it in a disposable copy (oracle); current and
  inactive views; private-field absence; held revisions; homepage/overlay; read-only
  (full SQL dump unchanged, selection unchanged); invalid/placeholder/cross-channel IDs;
  live switch while viewing; placeholder `—`; exact-label matching; ordering; expired
  history after retention; LRU eviction, reuse without rebuild, idle drop; empty/unplayed
  characters; twelve-profile HTTP browsing; tracked publication priority; lightweight
  roster-only homepage; same-name characters scoped by channel.
- `tools/product.test.mjs` (68 total): no strip for one character; reveal on a second;
  view-only click, cleared numbers, late-response discard; direct, invalid and unknown
  URLs; 12-character list search; level-floor display; homepage modes/search/sorting,
  scoped links, Back/Forward and late-response isolation. Last-seen labels are filled
  before scrolling the viewed chip; otherwise growing chip widths hid it offscreen.
- Headless Chrome on the demo (desktop 1280 and mobile 390): roster, click, URL,
  inactive status, live switch while viewing, back navigation, homepage, overlay,
  12-character single row and search; no page exceptions or horizontal overflow.

Measured on this Windows desktop with generated frames (not VPS/live OCR): fourteen
real HTTP visits (all twelve profiles plus two revisits) completed in **1.08 s**, before
idle expiry. Cold-view readiness was about **63–92 ms**, including a 50 ms polling
delay; ready profile responses were about 6–11 ms and 162–193 KB. Twenty compact
homepage requests averaged **1.8 ms**, **1,831 bytes**, without history builds. Full
SQL dumps before/after browsing matched. Private screenshots/benchmark output remain
under `private/character-demo/review-*/browser/` and are not committed.

Focused commands (same `$python`/`PYTHONPATH` setup as above):

```powershell
New-Item -ItemType Directory -Force private/character-demo/tmp | Out-Null
$env:TEMP = (Resolve-Path private/character-demo/tmp).Path
$env:TMP = $env:TEMP
& $python -m pytest tests/test_character_profiles.py tests/test_publisher.py -q -ra -k 'not test_concurrent_viewers_share_one_projection_per_publication'
node --test tools/product.test.mjs
& $python -m pytest -q -ra -k 'not test_concurrent_viewers_share_one_projection_per_publication'
```

Broader regression: **2,591 passed, 122 skipped** (118 private fixtures, two OS link
restrictions and two sandbox socket restrictions). Frontend: **68 passed**, zero skips.
The existing concurrent socket test was excluded from that sandbox run.
The excluded concurrent socket test and the twelve-profile real HTTP test were also
run separately with localhost sockets permitted: **2 passed**. Restricted runs skip
the new HTTP test explicitly; the rest exercise actual HTTP parsing in memory. No
Twitch connections, production database access, capture processes or deployment were used.

Also fixed: a level-floor display level lacked the `evidence` field every other display
level has, so `levelTitle()` threw and the character page/overlay stopped rendering when
the floor was the only display level (introduced with persistent level floors).
