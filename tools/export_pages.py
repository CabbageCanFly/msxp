"""Build the public-only static frontend for Cloudflare Pages.

    python tools/export_pages.py --api-origin https://api.example.org [--out dist/pages]
    MSXP_API_ORIGIN=https://api.example.org python tools/export_pages.py

Standard library only: Cloudflare's build image has Python but not this project's
dependencies. Only the files named in PAGES and STATIC are exported; everything else
under src/exp_tracker/web (admin, diagnostics, shadow viewer, demo) stays private.
The API origin comes from --api-origin, else MSXP_API_ORIGIN; there is no default, so a
build never silently points at a guessed backend.
See docs/cloudflare-pages-deployment.md.
"""

import argparse
import os
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / 'src' / 'exp_tracker' / 'web'
DEFAULT_OUT = ROOT / 'dist' / 'pages'
# Lets a rerun replace its own previous output, and nothing else.
MARKER = '.msxp-pages-export'
# Same exact-origin rule as exp_tracker.server.ORIGIN (a test keeps them identical): https, or http only for localhost.
LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
ORIGIN = re.compile(rf"https://{LABEL}(?:\.{LABEL})+(?::[0-9]{{1,5}})?|http://(?:localhost|127\.0\.0\.1)(?::[0-9]{{1,5}})?")

# Exported path -> source under web/. Anything not listed is never published.
PAGES = {'index.html': 'tracker.html', 'player.html': 'player.html', 'live-overlay.html': 'live-overlay.html'}
STATIC = ('product.js', 'product.css', 'leaderboard.css', 'live-overlay.css', 'steely.png', 'sleepywood.webp', 'sleepywood-forest.webp',
          'kerning.webp', 'kerning-sky.webp',
          'fonts/fredoka-latin.woff2', 'fonts/nunito-latin.woff2', 'fonts/OFL-Fredoka.txt', 'fonts/OFL-Nunito.txt',
          *sorted(f'mobs/{p.name}' for p in WEB.glob('mobs/*.*')))  # Wandering mob sprites; the folder holds only these.
# Developer links kept in the shared HTML; [data-site=public] hides them and they 404 on Pages.
DEVELOPER_LINKS = {'/dev/streams', '/demo/leaderboard'}
# Status 200 rewrites keep the browser URL, so product.js still reads the channel from location.pathname
# (with or without a trailing slash). Anything unmatched gets 404.html.
REDIRECTS = ('/streams / 200', '/streams/ / 200', '/stream/:channel /player 200', '/stream/:channel/ /player 200',
             '/live/overlay/:channel /live-overlay 200', '/live/overlay/:channel/ /live-overlay 200')
ROUTES = {'/', '/streams'}
CACHED = ('/static/fonts/*', '/static/steely.png', '/static/sleepywood.webp', '/static/sleepywood-forest.webp',
          '/static/kerning.webp', '/static/kerning-sky.webp', '/static/mobs/*')
NOT_FOUND = '''<!doctype html>
<html lang="en" data-site="public"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Not found · EXP Tracker</title><link rel="icon" href="/static/steely.png" type="image/png">
<link rel="stylesheet" href="/static/leaderboard.css"><link rel="stylesheet" href="/static/product.css"></head>
<body class="product"><main>
  <header class="masthead"><a class="brand" href="/"><img class="emblem" src="/static/steely.png" width="42" height="42" alt=""><div><strong>msxp.pages.dev</strong><span>EXP Tracker · MapleStory Classic</span></div></a></header>
  <section class="board"><header class="board-header"><h2>✦ Page not found</h2></header><div class="toolbar"><p>This page doesn't exist. <a href="/">Back to the player list</a></p></div></section>
</main></body></html>
'''


def api_origin(value):
    if not isinstance(value, str) or not ORIGIN.fullmatch(value):
        raise ValueError(f'API origin must be an exact https://host[:port] origin (http only for localhost), got {value!r}')
    return value


def source(name):
    path = WEB / name
    # Allowlisted names only; a symlink could publish something outside web/.
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(WEB.resolve()):
        raise ValueError(f'Missing or unsafe source file: {path}')
    return path.read_bytes()


def page(name, origin):
    body = source(name)
    tag = b'<html lang="en">'
    if body.count(tag) != 1:raise ValueError(f'{name}: expected exactly one {tag.decode()}')
    # The same public-site attribute the Python server adds in public-only mode, plus the API origin.
    return body.replace(tag, f'<html lang="en" data-site="public" data-api="{origin}">'.encode(), 1)


def headers(origin):
    policy = f"default-src 'self'; connect-src 'self' {origin}; object-src 'none'; base-uri 'none'; frame-ancestors 'self'; form-action 'none'"
    lines = ['/*', f'  Content-Security-Policy: {policy}', '  X-Content-Type-Options: nosniff',
             '  Referrer-Policy: strict-origin-when-cross-origin']
    for path in CACHED:lines += [path, '  Cache-Control: public, max-age=86400']
    return '\n'.join(lines) + '\n'


def references(out):
    """Everything a page loads is an exported /static/ file on the site's own origin; only <a> links may go elsewhere."""
    problems = []
    for html in sorted(out.glob('*.html')):
        for tag, attributes in re.findall(r'<([a-z]+)\b([^>]*)>', html.read_text(encoding='utf-8')):
            for ref in re.findall(r'\b(?:href|src)="([^"]*)"', attributes):
                if tag == 'a':
                    if ref == '#' or ref.startswith('https://') or ref in ROUTES or ref in DEVELOPER_LINKS:continue
                elif ref.startswith('/static/') and (out / ref[1:]).is_file():continue
                problems.append(f'{html.name}: <{tag}> {ref}')
    for css in sorted(out.glob('static/*.css')):
        text = css.read_text(encoding='utf-8')
        if '@import' in text:problems.append(f'{css.name}: @import')
        for ref in re.findall(r'url\(([^)]*)\)', text):
            file = (css.parent / ref.strip('\'"')).resolve()
            if ':' in ref or not file.is_relative_to(out.resolve() / 'static') or not file.is_file():problems.append(f'{css.name}: {ref}')
    if problems:raise ValueError('Unresolved or external references: ' + ', '.join(problems))


def export(out, origin):
    origin = api_origin(origin)
    out = Path(out).resolve()
    if out.exists():
        if not out.is_dir() or any(out.iterdir()) and not (out / MARKER).is_file():
            raise ValueError(f'Refusing to replace {out}: not empty and not a previous export')
        shutil.rmtree(out)
    files = {name: page(src, origin) for name, src in PAGES.items()}
    files.update({f'static/{name}': source(name) for name in STATIC})
    files.update({'404.html': NOT_FOUND.encode(), '_redirects': ('\n'.join(REDIRECTS) + '\n').encode(),
                  '_headers': headers(origin).encode(), MARKER: b'Generated by tools/export_pages.py; safe to delete.\n'})
    for name, body in sorted(files.items()):
        (out / name).parent.mkdir(parents=True, exist_ok=True)
        (out / name).write_bytes(body)
    references(out)
    return sorted(files)


def main(argv=None):
    cli = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    cli.add_argument('--api-origin', default=os.environ.get('MSXP_API_ORIGIN'), help='Public API origin; or set MSXP_API_ORIGIN')
    cli.add_argument('--out', type=Path, default=DEFAULT_OUT)
    args = cli.parse_args(argv)
    if not args.api_origin:
        print('Pages export failed: set --api-origin or MSXP_API_ORIGIN to the public API origin, e.g. https://api.example.org', file=sys.stderr)
        return 1
    try:
        files = export(args.out, args.api_origin)
    except (OSError, ValueError) as error:
        print(f'Pages export failed: {error}', file=sys.stderr)
        return 1
    print(f'Exported {len(files)} files to {args.out.resolve()} (API {args.api_origin})')
    for name in files:print(f'  {name}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
