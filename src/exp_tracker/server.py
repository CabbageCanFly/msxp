"""Local read-only state API and OBS overlay: python -m exp_tracker.server --db PATH."""

import argparse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import sqlite3
import sys
from urllib.parse import unquote, urlsplit

from .store import STALE_AFTER_SECONDS, Store, utc
from .shadow_view import ShadowLog


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
CHANNEL = re.compile(r"[A-Za-z0-9_]{1,25}")


class Handler(BaseHTTPRequestHandler):
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
        if path in ("/dev/shadow", "/dev/api/shadow") or path in SHADOW_ASSETS:
            if self.server.shadow_log is None:
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


def create_server(database, *, port=8765, shadow_log=None):
    database = Path(database).resolve()
    with Store(database, read_only=True):
        pass  # Validate without creating, migrating or changing journal mode.
    diagnostics = ShadowLog(shadow_log) if shadow_log is not None else None
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.database = database
    server.shadow_log = diagnostics
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True, help="Existing current-schema database; never initialized by HTTP")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--shadow-log", type=Path, help="Opt in to /dev/shadow for one private/artifacts JSONL; read-only")
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error("port must be 0..65535")
    try:
        with create_server(args.db, port=args.port, shadow_log=args.shadow_log) as server:
            print(f"Local read-only server: http://127.0.0.1:{server.server_port}/overlay/CHANNEL", flush=True)
            if server.shadow_log:
                print(f"UNVERIFIED shadow viewer: http://127.0.0.1:{server.server_port}/dev/shadow", flush=True)
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
