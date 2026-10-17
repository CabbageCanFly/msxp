"""Local read-only state API and OBS overlay: python -m exp_tracker.server --db PATH."""

import argparse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import sqlite3
import sys
import threading
from urllib.parse import unquote, urlsplit

from .store import STALE_AFTER_SECONDS, Store, utc
from .shadow_view import ShadowLog
from .diagnostics import Diagnostics


WEB = Path(__file__).with_name("web")
ASSETS = {
    "/static/overlay.css": ("overlay.css", "text/css"),
    "/static/overlay.js": ("overlay.js", "text/javascript"),
    "/static/leaderboard.css": ("leaderboard.css", "text/css"),
    "/static/leaderboard.js": ("leaderboard.js", "text/javascript"),
    "/static/leaderboard.svg": ("leaderboard.svg", "image/svg+xml"),
}
SHADOW_ASSETS = {
    "/static/shadow.css": ("shadow.css", "text/css"),
    "/static/shadow.js": ("shadow.js", "text/javascript"),
}
DIRECTORY_ASSETS = {'/static/streams.js': ('streams.js','text/javascript')}
CHANNEL = re.compile(r"[A-Za-z0-9_]{1,25}")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        if not getattr(self.server, 'quiet', False):
            super().log_message(format, *args)

    def reply(self, status, body, content_type="application/json"):
        payload = json.dumps(body, allow_nan=False).encode() if content_type == "application/json" else body
        self.send_response(status)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        if status == 405:
            self.send_header("Allow", "GET")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'self'")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        path = unquote(urlsplit(self.path).path)
        api = re.fullmatch(r"/api/streams/([^/]*)/state", path)
        overlay = re.fullmatch(r"/overlay/([^/]*)", path)
        dashboard = re.fullmatch(r"/dashboard/([^/]*)", path)
        diagnostic_api = re.fullmatch(r"/dev/api/streams/([^/]*)/diagnostics", path)
        if path in ('/streams','/dev/api/streams') or path in DIRECTORY_ASSETS:
            if not self.server.diagnostic_dashboard:
                self.reply(404, {'error':'not_found'})
            elif path == '/dev/api/streams':
                try:
                    with self.server.directory_lock, Store(self.server.database,read_only=True) as store:
                        self.reply(200,Diagnostics(store).directory(self.server.directory_cache,
                            active_runs=self.server.active_run_ids.copy()))
                except (ValueError,sqlite3.Error):
                    self.reply(503,{'error':'database_unavailable'})
            else:
                name,kind = DIRECTORY_ASSETS.get(path,('streams.html','text/html'))
                self.reply(200,(WEB/name).read_bytes(),kind)
        elif dashboard or diagnostic_api:
            channel = (dashboard or diagnostic_api)[1]
            if not self.server.diagnostic_dashboard:
                self.reply(404, {"error": "not_found"})
            elif not CHANNEL.fullmatch(channel):
                self.reply(400, {"error": "invalid_channel"})
            else:
                try:
                    with Store(self.server.database, read_only=True) as store:
                        channels = [row[0] for row in store.db.execute('SELECT login FROM streamers ORDER BY login LIMIT 25')]
                        store._channel(channel)
                        value = Diagnostics(store).snapshot(channel,active_runs=self.server.active_run_ids.copy()) if diagnostic_api else None
                    if dashboard:
                        self.reply(200, (WEB / 'shadow.html').read_bytes(), 'text/html')
                    else:
                        self.reply(200, value)
                except ValueError as error:
                    unknown = str(error) == 'unknown channel'
                    body = {'error': 'unknown_channel' if unknown else 'database_unavailable'}
                    if unknown:
                        body.update(message='This channel is not in the selected database. Check --db and the dashboard URL. Starting this server does not start capture.',
                                    configured_channels=channels)
                    self.reply(404 if unknown else 503, body)
                except sqlite3.Error:
                    self.reply(503, {'error': 'database_unavailable'})
        elif path in ("/dev/shadow", "/dev/api/shadow") or path in SHADOW_ASSETS:
            if self.server.shadow_log is None and not (path in SHADOW_ASSETS and self.server.diagnostic_dashboard):
                self.reply(404, {"error": "not_found"})
            elif path == "/dev/api/shadow":
                self.reply(200, self.server.shadow_log.snapshot())
            else:
                name, content_type = SHADOW_ASSETS.get(path, ("shadow.html", "text/html"))
                self.reply(200, (WEB / name).read_bytes(), content_type)
        elif api or overlay:
            channel = (api or overlay)[1]
            if not CHANNEL.fullmatch(channel):
                self.reply(400, {"error": "invalid_channel"})
                return
            if overlay:
                self.reply(200, (WEB / "overlay.html").read_bytes(), "text/html")
                return
            try:
                now = datetime.now(timezone.utc)
                with Store(self.server.database, read_only=True) as store:
                    state = store.state(channel, as_of=now)
                state["selected_character"] = next((c for c in state["characters"] if c["id"] == state["selected_character_id"]), None)
                state.update(served_at=utc(now), stale_after_seconds=STALE_AFTER_SECONDS)
                self.reply(200, state)
            except ValueError as error:
                unknown = str(error) == "unknown channel"
                self.reply(404 if unknown else 503, {"error": "unknown_channel" if unknown else "database_unavailable"})
            except sqlite3.Error:
                self.reply(503, {"error": "database_unavailable"})
        elif path == "/demo/leaderboard":
            self.reply(200, (WEB / "leaderboard.html").read_bytes(), "text/html")
        elif path in ASSETS:
            name, content_type = ASSETS[path]
            self.reply(200, (WEB / name).read_bytes(), content_type)
        else:
            self.reply(404, {"error": "not_found"})

    def reject_write(self):
        self.reply(405, {"error": "read_only"})

    do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = reject_write


def create_server(database, *, port=8765, shadow_log=None, diagnostic_dashboard=False):
    database = Path(database).resolve()
    with Store(database, read_only=True):
        pass  # Validate without creating, migrating or changing journal mode.
    diagnostics = ShadowLog(shadow_log) if shadow_log is not None else None
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.database = database
    server.shadow_log = diagnostics
    server.diagnostic_dashboard = diagnostic_dashboard
    server.active_run_ids = set()
    server.directory_cache = {}
    server.directory_lock = threading.Lock()
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True, help="Existing current-schema database; never initialized by HTTP")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--shadow-log", type=Path, help="Opt in to /dev/shadow for one private/artifacts JSONL; read-only")
    parser.add_argument('--diagnostic-dashboard', action='store_true', help='Opt in to /dashboard/CHANNEL backed by separate SQLite diagnostics')
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error("port must be 0..65535")
    try:
        with create_server(args.db, port=args.port, shadow_log=args.shadow_log,
                           diagnostic_dashboard=args.diagnostic_dashboard) as server:
            print(f'Database: {server.database}', flush=True)
            print('Read-only HTTP server; capture is NOT started by this command.', flush=True)
            print(f"Local read-only server: http://127.0.0.1:{server.server_port}/overlay/CHANNEL", flush=True)
            if server.shadow_log:
                print(f"UNVERIFIED shadow viewer: http://127.0.0.1:{server.server_port}/dev/shadow", flush=True)
            if server.diagnostic_dashboard:
                print(f"Streamer directory: http://127.0.0.1:{server.server_port}/streams",flush=True)
                with Store(server.database, read_only=True) as store:
                    channels = [row[0] for row in store.db.execute('SELECT login FROM streamers ORDER BY login LIMIT 25')]
                for channel in channels:
                    print(f"SQLite diagnostic dashboard: http://127.0.0.1:{server.server_port}/dashboard/{channel}", flush=True)
                if not channels:
                    print('No channels configured in this database.', flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
        return 0
    except (OSError, sqlite3.Error, ValueError) as error:
        print(f"Cannot start local server: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
