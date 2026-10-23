# Sleepywood website background

The public player list and character page use original pre-Big Bang Sleepywood
artwork from GMS v55, with a navy CSS tint matching the existing Classic Night
palette. This is a dark forest scene, not a newly drawn nighttime version of the
town. The version is explicit: no claim that every detail matches the earliest
release or the upcoming Classic client.

## Candidates inspected

These are clean original map renders from maplestory.io, without NPCs, monsters,
portals, HUDs or players. They are decorative game assets, not tracking fixtures.

| Town | Map ID (GMS v55) | Native render | Fit |
|---|---|---|---|
| Sleepywood | 105040300 | 2,983 × 1,435 | Selected: recognizable hotel, leaf-roof houses and naturally dark forest |
| Ellinia | 101000000 | 2,775 × 4,948 | Iconic, but very tall; a viewport crop loses most of the town |
| Kerning City | 103000000 | 5,260 × 1,817 | Strong wide alternative; warmer brickwork needs more tint to fit the navy UI |

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

The renderer omits the scrolling forest backdrop. CSS places the transparent town
render over its original forest tile. This is a static composition of those source
layers, not a reconstruction of the game's camera or parallax. Pillow converted
each PNG directly to lossless WebP (`lossless=True, method=6, exact=True`), preserving its size
and decoded pixels. No generated artwork, repainting or AI upscaling is involved.

`sleepywood.webp` is 891,786 bytes; `sleepywood-forest.webp` is 97,010 bytes:
988,796 bytes combined (about 966 KiB), cached for one day on both serving paths.
Images are self-hosted; visiting the website makes no request to the image provider.

## Page behavior

A fixed, viewport-sized pseudo-element in `product.css` keeps the scene behind
normal scrolling content. `cover` preserves image proportions and crops the edges
as needed, rather than stretching the town to the document's height or repeating
it down a long leaderboard. The navy gradients protect text contrast; data panels
retain their opaque surfaces. The older abstract cloud decoration is hidden.

This gives pages of any length the same scene without a scroll handler or animation.
The existing wandering monsters supply movement. Mobile shows a narrower crop.
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
The full Python suite passed: 2,985 passes, one OS symlink-permission skip;
no sample skips. The affected server/export subset passed all 81 tests.

Untested: Safari/iOS browser chrome resizing, Firefox, actual 4K hardware/GPU
performance, slow-network loading and a real Cloudflare deployment. No publishing
or push is part of this change. Seasonal themes and other regions are deferred.
