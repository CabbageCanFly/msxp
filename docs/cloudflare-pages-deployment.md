# Cloudflare Pages frontend

One repository, two deployment targets:

```
GitHub main ──► Cloudflare Pages build: python3 tools/export_pages.py ──► dist/pages ──► https://msxp.pages.dev
           └──► VPS (manual, docs/vps-deployment.md): Python tracker + SQLite + read-only API ──► <API origin>
```

The API hostname is not final, so nothing in the repository assumes it: every Pages build
must be told the origin (see [API origin](#api-origin)).

The static site is exported from the same files the Python server serves
(`src/exp_tracker/web/`); there is no second frontend copy. Browsers load HTML, CSS and
JavaScript, fonts and images from Pages; the VPS receives only the public read-only JSON
requests below. Merging to `main` redeploys only
the frontend: **backend changes still need the VPS rollout**, and a frontend that relies
on new API fields must wait for that backend to be live.

## What is exported

`tools/export_pages.py` (standard library only) writes an explicit allowlist to `dist/pages/`:

| Output | Source / purpose |
|---|---|
| `index.html`, `player.html`, `live-overlay.html` | `tracker.html`, `player.html`, `live-overlay.html` with `<html data-site="public" data-api="…">` |
| `static/product.js`, `product.css`, `leaderboard.css`, `live-overlay.css`, `steely.png` | Copied byte for byte |
| `static/fonts/*.woff2`, `static/fonts/OFL-*.txt` | Self-hosted fonts and their licences |
| `static/mobs/*.gif`, `*.webp` | Wandering mob sprites (see README credits), copied byte for byte |
| `static/jobs/*.png` | Job skill icons (see README credits), copied byte for byte |
| `static/classes/*.gif` | Class badges for the home job filter (see README credits), copied byte for byte |
| `static/sleepywood.webp`, `static/sleepywood-forest.webp` | Original town/forest background, lossless WebP (see [sources](website-background.md)) |
| `static/kerning.webp`, `static/kerning-sky.webp` | Original Kerning City town/sunset background, lossless WebP |
| `_redirects`, `_headers`, `404.html` | Generated: routes, security headers, not-found page |
| `.msxp-pages-export` | Marker that lets a rerun replace its own output |

Admin, shadow viewer, developer diagnostics, the demo leaderboard, the legacy `/overlay/`
page, Python, databases, samples and configuration are never copied. The script fails if
an allowlisted file is missing or a symlink, if any exported page or stylesheet refers to
anything other than an exported `/static/` file on its own origin (only `<a>` links may
point elsewhere), if no API origin is given, or if `--out` is a non-empty directory it did
not create.
`data-site="public"` is the attribute the Python server adds in `--public-only` mode; it
hides the developer links (`/dev/streams`, `/demo/leaderboard`, dashboard links), which
return the 404 page on Pages.

## Cloudflare Pages settings

| Setting | Value |
|---|---|
| Repository | the existing MS XP repository |
| Production branch | `main` |
| Framework preset | None |
| Root directory | repository root (leave empty) |
| Build command | `python3 tools/export_pages.py` |
| Build output directory | `dist/pages` |
| Environment variables | `MSXP_API_ORIGIN` = the public API origin, e.g. `https://api.example.org`, set for **both** Production and Preview |

The build needs only Python 3.9 or newer, with no `pip install`. Without
`MSXP_API_ORIGIN` the build fails with "set --api-origin or MSXP_API_ORIGIN", so a
deployment can never silently point at a guessed backend. Changing the API host later
means updating the variable and retrying the latest deployment; no code change is needed.

## API origin

The exported pages carry the API origin on `<html data-api="…">`, and `product.js` prefixes
its only two fetches with it:

- `GET /api/players` and `/api/players?mode=characters` (directory);
- `GET /api/players/{channel}`, with `?character=ID` and the held `?history=…&tracked=…` revisions (character page and overlay);
- `GET /api/players/{channel}/history` (24 h history, only when the character response omits it).

Responses, `503 warming_up` retries, stale and historical readings, and polling behave
exactly as on the Python server. Pages served by the Python server have no `data-api`,
so their requests stay same-origin. `--api-origin` takes precedence over
`MSXP_API_ORIGIN`; there is no default. The value must be an exact origin
(`https://host[:port]`, or `http://localhost` / `http://127.0.0.1` for local testing),
the same rule as the server's `--cors-origin`. Anything else, including paths, trailing
slashes, uppercase or wildcards, stops the build; `product.js` also refuses to start with
a malformed value. The origin is fixed at build time; no URL parameter can change it.
`_headers` sends `default-src 'self'; connect-src 'self' <API origin>`, so browsers load
every script, stylesheet, font, image and frame from the Pages origin and send network
requests only there and to the API.

The Caddy allowlist (`deploy/Caddyfile`) already covers the player GET routes, including
`/api/players/{channel}/daily-history`; no proxy change is needed for that endpoint.
The tracker must run with `--cors-origin https://msxp.pages.dev`
(see [VPS deployment](vps-deployment.md#api-contract-for-the-frontend)). Requests are
CORS-simple GETs, so no preflight is needed.

## Routes

`_redirects` uses Cloudflare's documented proxy form, `source destination 200` with a
`:channel` placeholder (one path segment). A 200 rewrite keeps the browser URL, so
`product.js` still reads the channel from `location.pathname`:

| URL | Serves |
|---|---|
| `/` | `index.html` (directory) |
| `/streams`, `/streams/` | `index.html` |
| `/stream/{channel}`, `/stream/{channel}/` (any `?character=` / `?mode=`) | `player.html` |
| `/live/overlay/{channel}`, `/live/overlay/{channel}/` (any `?layout=…&theme=…`) | `live-overlay.html` |
| anything else, e.g. `/dev/streams`, `/dashboard/…`, `/admin`, `/overlay/…`, `/stream/a/b` | `404.html` with status 404 |

A `404.html` at the root also stops Pages from treating unknown paths as a single-page
app that falls back to the directory.

Assets use absolute `/static/...` paths, so nested routes and refreshes load them correctly.
The overlay builder copies `https://msxp.pages.dev/live/overlay/{channel}?…` (the page's
own origin), and its live preview is a same-origin iframe, allowed by `frame-ancestors 'self'`.

## Build and preview locally (Windows PowerShell)

For CSS/HTML/JS iteration, run `.\msxp demo` from the checkout or worktree. This uses temporary
synthetic data and `--live` mode: save and refresh to see source edits, with no
export/restart needed. Ctrl+C in that terminal closes both servers and removes the
temporary database. See [town overrides and tint](website-background.md).
The commands below still check an exported snapshot with production-style caching.

Run with the project's virtual environment active (the local API needs its dependencies):

```powershell
$env:PYTHONPATH = 'src'
# Production-shaped build (any syntactically valid origin; nothing is contacted).
python tools/export_pages.py --api-origin https://api.example.org
Get-ChildItem -Recurse -File dist\pages | Select-Object -ExpandProperty FullName

# Full local preview against synthetic data: one command, no VPS involved.
python tools/character_demo.py create --replace --characters 12 --streamers 5
python tools/preview_pages.py --api-db private/character-demo/demo.sqlite3
# It prints the preview URL; open it, then /stream/synthetic_demo and /live/overlay/synthetic_demo?layout=rates
```

`--api-db` exports to `dist/pages-local` against a local public-only API on the given
synthetic database. The preview binds first, the API allows CORS from exactly that
preview origin, and **both listen on OS-assigned free ports on 127.0.0.1**. On Windows a
fixed port could otherwise be shared silently with something already listening, such as
an SSH tunnel to the VPS, and send requests there. `preview_pages.py` applies the
generated `_redirects`, `_headers` and `404.html` the way Pages does, and refuses an
explicit `--port` that is already in use. Stop it with Ctrl+C, which also stops the API.
Point `--api-db` only at the synthetic demo database, never at a production copy.

To check public-only contents: `python -m pytest tests/test_export_pages.py` lists the
exact expected files, rejects admin, diagnostic, Python, database and configuration
files, and checks every page reference.

## Preview deployments and CORS

Pages preview URLs (`https://<hash>.msxp.pages.dev`, `https://<branch>.msxp.pages.dev`)
are different origins, and the API allows only `https://msxp.pages.dev`. A preview
deployment therefore loads its pages but every API request fails CORS: the directory
stays on "Loading players…". Do not widen `--cors-origin` to wildcards. Instead:

- test locally as above, against synthetic data; or
- if a hosted preview is needed, add one exact branch alias temporarily
  (`--cors-origin https://staging.msxp.pages.dev`), redeploy the backend, and remove it afterwards.

## Rollback

Cloudflare dashboard → Workers & Pages → the project → Deployments → pick the last good
production deployment → **Rollback to this deployment**. This is instant and does not
touch the VPS. Then revert the offending commit on `main`, so the next build doesn't
redeploy it.

## Known limitations

- Not yet verified on a real Cloudflare deployment; tests and `preview_pages.py`
  approximate Pages. On the first deployment, check: `/stream/{channel}`,
  `/stream/{channel}/`, `/live/overlay/{channel}?layout=rates` and a refresh keep their URLs
  and render; `/dev/streams` and `/admin` return the 404 page; response headers include the
  `_headers` policy; DevTools Network shows only `/static/…` from Pages and `/api/players…`
  from the API origin.
- Pages also serves `/player` and `/live-overlay` directly (the rewrite targets). Without a
  channel in the path they show an empty page; they expose nothing private.
- If the API is down, Caddy's 502/504 has no CORS headers; pages keep their last data
  and say updates are delayed, as they do when the local server stops.
