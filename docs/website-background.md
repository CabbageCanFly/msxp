# Classic town website backgrounds

The public player list and character page randomly choose original pre-Big Bang
Sleepywood or Kerning City artwork from GMS v55 on each page load. A navy CSS tint
matches the existing Classic Night palette. Sleepywood uses its dark forest;
Kerning uses its original sunset sky. These are tinted original scenes, not newly
drawn nighttime versions. No claim that every detail matches the earliest
release or the upcoming Classic client.

## Preview and tune

From the Sleepywood worktree on Windows, run:

```powershell
.\preview.cmd
```

The launcher uses this worktree's virtual environment, or the adjacent
`msclassic-twitch-exp-tracker/.venv` if necessary. It always loads this worktree's
source. It creates temporary fictional players and starts the preview in your
current terminal. No previously generated database or exported folder is needed.

- Random town: <http://127.0.0.1:8890/>
- Force Sleepywood: <http://127.0.0.1:8890/?background=sleepywood>
- Force Kerning City: <http://127.0.0.1:8890/?background=kerning>

Save CSS, HTML or JavaScript and refresh the browser. Live preview reads
allowlisted source files for every request and disables browser caching; no
re-export or restart is needed for these edits. There is no automatic browser
reload. Python changes still need a restart.

Press **Ctrl+C in that terminal** to stop both the preview and its API and remove
the temporary demo database. The launcher leaves no detached server. If port 8890
is occupied, stop your earlier preview or choose another with
`.\preview.cmd --port 8891`. It never kills an existing process.

With an active Python environment, the equivalent command on any platform is
`python tools/preview_pages.py --demo --live --port 8890`. To keep your own synthetic
data, use `--api-db PATH --live` instead of `--demo`.

At the top of `src/exp_tracker/web/product.css`, **`--background-tint:10%`** adds a
uniform 10% navy veil over Sleepywood's previous gradients. Increase the percentage
to dim the scene further. Kerning overrides the same variable to **40%**, because
its sunset sky and brickwork are brighter. The underlying gradients now use
readable opacity percentages instead of hex alpha values.
Kerning's fixed background extends 3% past each viewport edge, providing a small
zoom that crops away the original render's uneven transparent bottom border.

Overrides apply to the current URL; add the parameter on a character URL too,
e.g. `/stream/synthetic_demo?background=kerning`. Without an override, either town
has a 50% chance each load. The page does not rotate scenes while open. Unknown
values fall back to random selection. Only the chosen town's images are loaded.

## Candidates inspected

These are clean original map renders from maplestory.io, without NPCs, monsters,
portals, HUDs or players. They are decorative game assets, not tracking fixtures.

| Town | Map ID (GMS v55) | Native render | Fit |
|---|---|---|---|
| Sleepywood | 105040300 | 2,983 × 1,435 | Shipped: recognizable hotel, leaf-roof houses and naturally dark forest |
| Ellinia | 101000000 | 2,775 × 4,948 | Iconic, but very tall; a viewport crop loses most of the town |
| Kerning City | 103000000 | 5,260 × 1,817 | Shipped: wide rooftops and sunset sky with a stronger navy tint |

## Sources and transformation

All artwork remains © Nexon; the project's MIT licence does not relicense it.
As with the existing monster sprites, it is credited decoration for an independent,
non-commercial fan site. No separate artwork redistribution licence was obtained.

- [Sleepywood map metadata](https://maplestory.io/api/GMS/55/map/105040300)
- [Sleepywood town render](https://maplestory.io/api/GMS/55/map/105040300/render/0?showLife=false&showPortals=false)
- [Original map background definitions](https://maplestory.io/api/wz/GMS/55/Map/Map/Map1/105040300.img/back): the town uses `darkWood` backgrounds.
- [Original forest backdrop, darkWood/back/0](https://maplestory.io/api/wz/img/GMS/55/Map/Back/darkWood.img/back/0), native 842 × 340.
- [Ellinia render](https://maplestory.io/api/GMS/55/map/101000000/render/0?showLife=false&showPortals=false)
- [Kerning City render](https://maplestory.io/api/GMS/55/map/103000000/render/0?showLife=false&showPortals=false)
- [Kerning City backdrop reference](https://maplestory.io/api/wz/GMS/55/Map/Map/Map1/103000000.img/back/0/bS): `sunsetCity`.
- [Kerning sunset sky](https://maplestory.io/api/wz/img/GMS/55/Map/Back/sunsetCity.img/back/0), native 900 × 799.

The renderer omits the scrolling backdrop. CSS places each transparent town
render over its original forest or sky tile. This is a static composition of those source
layers, not a reconstruction of the game's camera or parallax. Pillow converted
each PNG directly to lossless WebP (`lossless=True, method=6, exact=True`), preserving its size
and decoded pixels. No generated artwork, repainting or AI upscaling is involved.

`sleepywood.webp` is 891,786 bytes; `sleepywood-forest.webp` is 97,010 bytes:
988,796 bytes combined (about 966 KiB), cached for one day on both serving paths.
Images are self-hosted; visiting the website makes no request to the image provider.
Kerning's map is 1,977,206 bytes and its sky is 304,324 bytes (about 2.18 MiB combined).
The unselected town's images are not downloaded. Live preview uses `no-store`;
normal exports and the Python website keep their one-day image cache.

## Page behavior

A fixed, viewport-sized pseudo-element in `product.css` keeps the scene behind
normal scrolling content. `cover` preserves image proportions and crops the edges
as needed, rather than stretching the town to the document's height or repeating
it down a long leaderboard. The navy gradients protect text contrast; data panels
retain their opaque surfaces. The older abstract cloud decoration is hidden.

This gives pages of any length the same scene without a scroll handler or animation.
The existing wandering monsters supply movement. Mobile shows a narrower crop.
Walking mobs and their damage numbers disable touch highlighting, selection and
image dragging. Each accepted tap/click shows one floating damage number, including
nonlethal reactions; mobs already dying or falling ignore further input.
The town scales up on 4K screens: this is original pixel art, not native 4K detail.
The small forest tile is also enlarged and intentionally subdued by the tint.
If an image fails, the navy body remains the fallback. The OBS overlay uses its own
stylesheet and retains transparent surroundings.

## Verification (2026-10-22)

Measured locally in headless Chrome using the Pages export, a local read-only API
and an isolated synthetic database:

- Homepage at 1,920 × 1,080, 3,840 × 2,160 and 390 × 844; character page at desktop/mobile sizes.
- A long homepage built by cloning synthetic rows, scrolled more than 1,000 pixels:
  the scene remains viewport-sized and fixed, with no horizontal overflow.
- Both background assets load from the site's own origin, with no browser errors
  or third-party requests; OBS body stays transparent with no scene pseudo-element.
- Original PNGs and WebPs decode to identical RGBA pixels.

Local screenshots and browser measurements are under ignored
`artifacts/map-background/`; no screenshots or databases are committed.
The server/export tests cover asset availability, MIME, caching and copied bytes.
The original background milestone passed 2,985 Python tests with one OS symlink
skip on the main workstation. This follow-up in the separate worktree passed
2,869 Python tests, with 119 private-fixture skips and one OS symlink skip;
the worktree does not copy the original directory's ignored private fixtures.
The product JavaScript suite passed all 121 tests, including repeated mob clicks
across all four reactions. On 2026-10-23, Chrome touch emulation verified four taps
and a mouse click each create one damage number, numbers clean up, mob highlighting
and selection are disabled, and ordinary page text remains selectable.
Both towns were checked at 1080p, 4K and mobile, on long scrolling lists and the
character page; only the selected images loaded and OBS remained transparent.
Tests also change source CSS and HTML while the same live server runs, and verify
that Ctrl+C closes both servers and removes the temporary demo database.

Untested: Safari/iOS browser chrome resizing, Firefox, actual 4K hardware/GPU
performance, slow-network loading and a real Cloudflare deployment. No publishing
or push is part of this change. Seasonal themes and other regions are deferred.
