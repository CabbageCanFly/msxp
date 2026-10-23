# Classic town website backgrounds

The public player list and character page choose original pre-Big Bang
Sleepywood artwork on odd local dates and Kerning City on even local dates,
from GMS v55. A navy CSS tint
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

- Town of the day: <http://127.0.0.1:8890/>
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

At the top of `src/exp_tracker/web/product.css`, **`--background-tint:15%`** adds a
uniform 15% navy veil over Sleepywood's previous gradients. Increase the percentage
to dim the scene further. Kerning overrides the same variable to **45%**, because
its sunset sky and brickwork are brighter. The underlying gradients now use
readable opacity percentages instead of hex alpha values.
Kerning's fixed background extends 3% past each viewport edge, providing a small
zoom that crops away the original render's uneven transparent bottom border.

Overrides apply to the current URL; add the parameter on a character URL too,
e.g. `/stream/synthetic_demo?background=kerning`. Without an override, the selection
follows the visitor's local day of the month: odd dates use Sleepywood and even
dates use Kerning. The choice is made on page load, stays consistent between pages
that day, and does not change while a page is open. Unknown override values use
the daily selection. Month boundaries follow date parity, so the 31st and the 1st
both show Sleepywood. Only the chosen town's images are loaded.

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
Both selected layers download in parallel and decode before the scene fades in
together over 550 ms. The data request runs independently; neither images nor
players wait for the other. If either image fails, the solid navy fallback stays.
A faint navy pill frames the logo/title link, with its outer left edge aligned to the panels;
padding moves the logo and text inward slightly.

The original whole-panel fade is restored: panels and the footer fade in after
the first response, with the existing two-second visibility fallback. There are
no placeholder rows or separate row/stat entrance animations.
Later polls and filters do not replay the entrance. The masthead and description
fade for 280 ms only on the first public page in a tab, remembered in session
storage; blocked storage leaves them visible. Page navigation does not repeat that
introduction. Reduced motion disables these fades. No image bytes or API latency
are reduced by these presentation changes; no additional image variants are loaded.

Walking mobs and their damage numbers disable touch highlighting, selection and
image dragging. Each accepted tap/click shows one floating damage number, including
nonlethal reactions; mobs already dying or falling ignore further input.
The character-page "Bar chart transfers below" tip is a keyboard-accessible
button: one activation draws a gold strike, two form an X, and three dismiss the
text and arrow with a brief shrinking/blurred fade. Reduced motion dismisses it
immediately. Dismissal lasts for this page visit; refreshing restores the tip.
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
The product JavaScript suite passed all 124 tests, including repeated mob clicks
across all four reactions. On 2026-10-23, Chrome touch emulation verified four taps
and a mouse click each create one damage number, numbers clean up, mob highlighting
and selection are disabled, and ordinary page text remains selectable.
The three-stage character tip was checked with actual mouse clicks, touch taps
and Enter/Space, including reduced motion, focus transfer and restoration on
refresh. Its strikes were visually inspected; test preview servers were stopped.
Both towns were checked at 1080p, 4K and mobile, on long scrolling lists and the
character page; only the selected images loaded and OBS remained transparent.
Tests also change source CSS and HTML while the same live server runs, and verify
that Ctrl+C closes both servers and removes the temporary demo database.

The loading follow-up was checked against main in Chrome with an intentionally
delayed API response containing 25 synthetic players and a held background layer:
data renders before the held image, and the scene reveals after both layers
decode. The revision restores the original whole-panel fade without placeholders.
Each selected image requests once.
Header navigation, the profile, mobile/reduced motion, a failed image fallback and
transparent OBS were checked. These are controlled delays, not deployment timings.
The final main-branch check passed 124 JavaScript tests and 2,952 Python tests
with private-sample tests excluded; one OS symlink test skipped. The full Python
run also found 67 failures from private OCR annotations/banks referencing absent
crop files, plus one private calibration skip. Those fixture dependencies remain
unresolved; the UI and export checks pass.
The rollback to the original panel fade passed all 124 JavaScript tests and 84
focused Python server/export tests (no skips). Chrome verified the restored fade,
absent placeholders, retained background fade and title pill; both test servers
stopped afterward. Date-parity tests cover both pages, valid/invalid overrides,
and the 1st, 2nd, 28th, 29th, 30th and 31st.

Untested: Safari/iOS browser chrome resizing, Firefox, actual 4K hardware/GPU
performance, real mobile-network loading and a real Cloudflare deployment. No publishing
or push is part of this change. Seasonal themes and other regions are deferred.
