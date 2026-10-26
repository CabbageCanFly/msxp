"""Local preview of the Pages export: applies its _redirects rewrites, _headers and 404.html.

    python tools/preview_pages.py [--dir dist/pages] [--port N]
    python tools/preview_pages.py --api-db private/character-demo/demo.sqlite3   # export + local API
    python tools/preview_pages.py --demo --live --port 8890   # temporary fictional players; save source and refresh

An approximation of Cloudflare Pages for checking routes and assets on 127.0.0.1 only;
a real preview deployment remains the authority (docs/cloudflare-pages-deployment.md).
Ports default to OS-assigned free ones, so a preview can never share a port that is
already in use (on Windows, e.g. an SSH tunnel to the VPS).
"""

import argparse
from fnmatch import fnmatch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import mimetypes
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
import threading
from urllib.parse import unquote, urlsplit

import export_pages

# A shared virtual environment may be installed against a different worktree.
sys.path.insert(0, str(export_pages.ROOT / 'src'))

TYPES = {'.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
         '.woff2': 'font/woff2', '.png': 'image/png', '.webp': 'image/webp', '.txt': 'text/plain; charset=utf-8'}


def rewrites(root):
    """_redirects lines 'source destination 200' as (regex, destination); ':name' matches one path segment."""
    rules = []
    for line in (root / '_redirects').read_text(encoding='utf-8').splitlines():
        if not line.strip() or line.lstrip().startswith('#'):continue
        src, dest, status = line.split()
        if status != '200':raise ValueError(f'Preview only supports 200 rewrites: {line}')
        rules.append((re.compile('^' + re.sub(r':[a-z]+', '[^/]+', re.escape(src)) + '$'), dest))
    return rules


def header_rules(root):
    rules, current = [], None
    for line in (root / '_headers').read_text(encoding='utf-8').splitlines():
        if line and not line[0].isspace():current = (line.strip(), []);rules.append(current)
        elif line.strip():name, value = line.strip().split(':', 1);current[1].append((name, value.strip()))
    return rules


def resolve(root, path):
    """URL path -> file, Pages-style: '/' is index.html and '/name' may serve name.html."""
    for name in (('index.html',) if path == '/' else (path.lstrip('/'), path.lstrip('/') + '.html')):
        file = (root / name).resolve()
        if file.is_relative_to(root) and file.is_file():return file
    return None


def handler(root, source_origin=None):
    rules, headers = rewrites(root), header_rules(root)

    class Preview(BaseHTTPRequestHandler):
        def do_GET(self):
            path = unquote(urlsplit(self.path).path)
            target = next((dest for pattern, dest in rules if pattern.match(path)), path)
            file, status = resolve(root, target), 200
            if file is None:file, status = root / '404.html', 404
            name = file.relative_to(root).as_posix()
            if source_origin is not None and name in export_pages.PAGES:
                body = export_pages.page(export_pages.PAGES[name], source_origin)
            elif source_origin is not None and name.removeprefix('static/') in export_pages.STATIC and name.startswith('static/'):
                body = export_pages.source(name.removeprefix('static/'))
            else:
                body = file.read_bytes()
            self.send_response(status)
            self.send_header('Content-Type', TYPES.get(file.suffix, mimetypes.guess_type(file.name)[0] or 'application/octet-stream'))
            self.send_header('Content-Length', str(len(body)))
            for pattern, values in headers:
                if fnmatch(path, pattern):
                    for name, value in values:
                        if source_origin is None or name.lower() != 'cache-control':self.send_header(name, value)
            if source_origin is not None:self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

    return Preview


class PreviewServer(ThreadingHTTPServer):
    # On Windows SO_REUSEADDR lets a second server share a busy port (e.g. an SSH tunnel); fail instead.
    allow_reuse_address = False


def with_api(database, out, port=0, *, live=False):
    """Export against a local public-only API and preview it; both listen on 127.0.0.1 only.

    The preview binds first so the API can allow exactly its origin; the API then takes an
    OS-assigned port and the export is built for it. Returns (preview, api), not yet serving.
    """
    from exp_tracker.server import create_server  # The project's environment; only this mode needs it.
    preview = PreviewServer(('127.0.0.1', port), BaseHTTPRequestHandler)
    api = None
    try:
        api = create_server(database, port=0, public_only=True, background=True,
                            cors_origins=(f'http://127.0.0.1:{preview.server_port}',))
        export_pages.export(out, f'http://127.0.0.1:{api.server_port}')
    except BaseException:
        preview.server_close()
        if api:api.server_close()
        raise
    preview.RequestHandlerClass = handler(Path(out).resolve(), f'http://127.0.0.1:{api.server_port}' if live else None)
    return preview, api


def main(argv=None):
    cli = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    cli.add_argument('--port', type=int, default=0, help='Preview port; default: a free one chosen by the OS')
    cli.add_argument('--dir', type=Path, help='Export to preview (default dist/pages; dist/pages-local with --api-db)')
    database = cli.add_mutually_exclusive_group()
    database.add_argument('--api-db', type=Path, help='Also export for, and run, a local public-only API on this synthetic database')
    database.add_argument('--demo', action='store_true', help='Use temporary fictional characters; remove the demo database when stopped')
    cli.add_argument('--live', action='store_true', help='Read allowlisted HTML/CSS/JS/images from source on refresh, with no browser cache (requires --api-db or --demo)')
    args = cli.parse_args(argv)
    if args.live and not (args.api_db or args.demo):cli.error('--live requires --api-db or --demo')
    dist = Path(__file__).resolve().parents[1] / 'dist'
    preview = api = demo = None
    try:
        if args.demo:
            from datetime import datetime, timezone
            import character_demo
            demo = TemporaryDirectory(prefix='msxp-preview-')
            args.api_db = Path(demo.name) / 'demo.sqlite3'
            character_demo.create(now=datetime.now(timezone.utc), path=args.api_db, characters=12, streamers=5, history=True)
            print('Using temporary fictional characters; no capture is started.', flush=True)
        if args.api_db:
            preview, api = with_api(args.api_db, args.dir or dist / 'pages-local', args.port, live=args.live)
            if args.demo:
                from exp_tracker.store import Store
                with Store(args.api_db,read_only=True) as store:channels=[r[0] for r in store.db.execute('SELECT login FROM streamers')]
                character_demo.demo_twitch(api, channels, offline=character_demo.OFFLINE)
            threading.Thread(target=api.serve_forever, daemon=True).start()
            print(f'Local API: http://127.0.0.1:{api.server_port}/api/players (CORS: this preview only)', flush=True)
        else:
            preview = PreviewServer(('127.0.0.1', args.port), handler((args.dir or dist / 'pages').resolve()))
        url = f'http://127.0.0.1:{preview.server_port}/'
        print(f'Preview: {url}', flush=True)
        if args.live:
            print('Save source files and refresh the browser; no export or restart needed.', flush=True)
            for town in ('sleepywood', 'kerning'):print(f'{town.title()}: {url}?background={town}', flush=True)
        print('Press Ctrl+C in this terminal to stop the preview and its local API.', flush=True)
        preview.serve_forever()
    except KeyboardInterrupt:pass
    finally:
        if preview:preview.server_close()
        if api:api.shutdown();api.server_close()
        if demo:demo.cleanup()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
