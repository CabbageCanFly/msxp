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
from urllib.parse import parse_qs, unquote, urlsplit

from .store import STALE_AFTER_SECONDS, Store, utc
from .shadow_view import ShadowLog
from .diagnostics import Diagnostics, operation
from .product import reading,PACE_TREND_SECONDS
from .publisher import Publisher
from .pace_intervals import collect
from .twitch_probe import StreamAvailability
from .twitch_auth import AppTokens


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
PRODUCT_ASSETS = {'/static/product.css':('product.css','text/css'),'/static/product.js':('product.js','text/javascript')}
CHANNEL = re.compile(r"[A-Za-z0-9_]{1,25}")


class TrackerHTTPServer(ThreadingHTTPServer):
    # The socketserver default of 5 refused connections at 100 viewers while a build held the GIL.
    request_queue_size = 128

    def server_close(self):
        super().server_close()
        publisher=getattr(self,'publisher',None)
        if publisher:publisher.close()
        availability=getattr(self,'twitch_availability',None)
        if availability:availability.auth.close()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        if not getattr(self.server, 'quiet', False):
            super().log_message(format, *args)

    def reply(self, status, body, content_type="application/json", headers=()):
        # Bytes are a body the publisher already serialized for every viewer.
        payload = json.dumps(body, allow_nan=False).encode() if content_type == "application/json" and not isinstance(body, bytes) else body
        self.send_response(status)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        for name, value in headers:
            self.send_header(name, value)
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
        history_api = re.fullmatch(r'/dev/api/streams/([^/]*)/(sessions|runs)',path)
        product_api=re.fullmatch(r'/api/players/([^/]*)',path)
        product_history=re.fullmatch(r'/api/players/([^/]*)/history',path)
        product_page=re.fullmatch(r'/(stream|live/overlay)/([^/]*)',path)
        if path in ('/','/streams','/api/players') or product_api or product_history or product_page or path in PRODUCT_ASSETS:
            if not self.server.diagnostic_dashboard:
                self.reply(404,{'error':'not_found'});return
            try:
                if path in PRODUCT_ASSETS:
                    name,kind=PRODUCT_ASSETS[path];self.reply(200,(WEB/name).read_bytes(),kind)
                elif path in ('/','/streams'):
                    self.reply(200,(WEB/'tracker.html').read_bytes(),'text/html')
                elif path=='/api/players':
                    # Requests only present published state; inline servers settle it first.
                    publisher=self.server.publisher
                    if not publisher.background:publisher.settle()
                    self.reply(200,publisher.homepage())
                else:
                    channel=(product_api[1] if product_api else product_history[1] if product_history else product_page[2]).lower()
                    if not CHANNEL.fullmatch(channel):self.reply(400,{'error':'invalid_channel'});return
                    if product_page:
                        with Store(self.server.database,read_only=True) as store:store._channel(channel)
                        self.reply(200,(WEB/('live-overlay.html' if product_page[1]=='live/overlay' else 'player.html')).read_bytes(),'text/html')
                        return
                    publisher=self.server.publisher
                    if not publisher.background:publisher.settle()
                    body=publisher.character(channel) if product_api else publisher.history(channel)
                    if body is None:
                        with Store(self.server.database,read_only=True) as store:store._channel(channel)  # Unknown: 404.
                        with publisher.lock:
                            limited=publisher.truncated and channel not in {h['login'] for h in publisher.heads}
                        if limited:
                            self.reply(503,{'error':'publication_limit','limit':25});return
                        publisher.want(channel)
                        self.reply(503,{'error':'warming_up','retry_after_seconds':2},headers=[('Retry-After','2')])
                    else:
                        self.reply(200,body)
            except ValueError as error:
                self.reply(404 if str(error)=='unknown channel' else 503,{'error':'unknown_channel' if str(error)=='unknown channel' else 'database_unavailable'})
            except sqlite3.Error:
                self.reply(503,{'error':'database_unavailable'})
        elif path in ('/dev/streams','/dev/api/streams') or path in DIRECTORY_ASSETS:
            if not self.server.diagnostic_dashboard:
                self.reply(404, {'error':'not_found'})
            elif path == '/dev/api/streams':
                try:
                    with self.server.directory_lock, Store(self.server.database,read_only=True) as store:
                        self.reply(200,Diagnostics(store).directory(self.server.directory_cache,
                            active_runs=self.server.active_run_ids.copy(),coordinator_status=self.server.coordinator_status.copy()))
                except (ValueError,sqlite3.Error):
                    self.reply(503,{'error':'database_unavailable'})
            else:
                name,kind = DIRECTORY_ASSETS.get(path,('streams.html','text/html'))
                self.reply(200,(WEB/name).read_bytes(),kind)
        elif dashboard or diagnostic_api or history_api:
            channel = (dashboard or diagnostic_api or history_api)[1].lower()
            if not self.server.diagnostic_dashboard:
                self.reply(404, {"error": "not_found"})
            elif not CHANNEL.fullmatch(channel):
                self.reply(400, {"error": "invalid_channel"})
            else:
                try:
                    with Store(self.server.database, read_only=True) as store:
                        channels = [row[0] for row in store.db.execute('SELECT login FROM streamers ORDER BY login LIMIT 25')]
                        store._channel(channel)
                        query=parse_qs(urlsplit(self.path).query,keep_blank_values=True,max_num_fields=8)
                        allowed={'session','run','before','start','end'} if diagnostic_api or dashboard else {'session','before'} if history_api else set()
                        query={k:v for k,v in query.items() if k in allowed}
                        if any(len(v)!=1 or not v[0] for v in query.values()):
                            raise ValueError('Invalid history query')
                        for name in ('session','before'):
                            if name in query and (not re.fullmatch(r'[1-9][0-9]{0,17}',query[name][0])): raise ValueError('Invalid history cursor')
                        session=int(query['session'][0]) if 'session' in query else None
                        before=int(query['before'][0]) if 'before' in query else None
                        diagnostic=Diagnostics(store)
                        if diagnostic_api:
                            value=diagnostic.snapshot(channel,active_runs=self.server.active_run_ids.copy(),session_id=session,
                                before=before,run_id=query.get('run',[None])[0],start=query.get('start',[None])[0],end=query.get('end',[None])[0])
                            value['operation']=dict(state='historical_session') if value['historical'] else operation(value,self.server.coordinator_status.get(channel),datetime.now(timezone.utc))
                            recoveries=collect(value,now=datetime.now(timezone.utc),read=reading,max_interval_seconds=PACE_TREND_SECONDS)['recoveries']
                            for row in value['observations']:
                                row['conditional_percent']=next((r for r in recoveries if r['event_id']==row['event_id']),None)
                        elif history_api:
                            value=diagnostic.sessions(channel,before=before) if history_api[2]=='sessions' else diagnostic.runs(channel,session,before=before)
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
                    query_error=not unknown and ('history' in str(error).lower() or any(word in str(error).lower() for word in ('session','cursor','timestamp','window','run')))
                    if query_error: body={'error':'invalid_history_query'}
                    self.reply(404 if unknown else 400 if query_error else 503, body)
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


def create_server(database, *, port=8765, shadow_log=None, diagnostic_dashboard=False,twitch_status=False,background=False):
    """background=True runs the publisher thread; otherwise requests settle it inline."""
    database = Path(database).resolve()
    with Store(database, read_only=True):
        pass  # Validate without creating, migrating or changing journal mode.
    diagnostics = ShadowLog(shadow_log) if shadow_log is not None else None
    server = TrackerHTTPServer(("127.0.0.1", port), Handler)
    server.database = database
    server.shadow_log = diagnostics
    server.diagnostic_dashboard = diagnostic_dashboard
    server.active_run_ids = set()
    server.coordinator_status = {}
    server.directory_cache = {}
    server.directory_lock = threading.Lock()
    server.eta_cache={}
    server.checkpoints={}  # Exact resumable causal replay state; see rolling_history.replay().
    server.twitch_availability=StreamAvailability(enabled=twitch_status,auth=AppTokens(maintain=twitch_status))
    # Module-level datetime, so replay fixtures that pin this module's clock pin the publisher.
    server.publisher=Publisher(server,clock=lambda:datetime.now(timezone.utc),background=background)
    if diagnostic_dashboard:server.publisher.start()
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True, help="Existing current-schema database; never initialized by HTTP")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--shadow-log", type=Path, help="Opt in to /dev/shadow for one private/artifacts JSONL; read-only")
    parser.add_argument('--diagnostic-dashboard', action='store_true', help='Enable the experimental homepage, live overlay and advanced SQLite diagnostics')
    parser.add_argument('--twitch-status',action='store_true',help='Opt in to cached Helix live status using server environment credentials')
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error("port must be 0..65535")
    try:
        with create_server(args.db, port=args.port, shadow_log=args.shadow_log,
                           diagnostic_dashboard=args.diagnostic_dashboard,twitch_status=args.twitch_status,background=True) as server:
            print(f'Database: {server.database}', flush=True)
            print('Read-only HTTP server; capture is NOT started by this command.', flush=True)
            print(f"Local read-only server: http://127.0.0.1:{server.server_port}/overlay/CHANNEL", flush=True)
            if server.shadow_log:
                print(f"UNVERIFIED shadow viewer: http://127.0.0.1:{server.server_port}/dev/shadow", flush=True)
            if server.diagnostic_dashboard:
                print(f"EXP Tracker homepage: http://127.0.0.1:{server.server_port}/",flush=True)
                with Store(server.database, read_only=True) as store:
                    channels = [row[0] for row in store.db.execute('SELECT login FROM streamers ORDER BY login LIMIT 25')]
                for channel in channels:
                    print(f"Character: http://127.0.0.1:{server.server_port}/stream/{channel}",flush=True)
                    print(f"Experimental OBS overlay (500x160): http://127.0.0.1:{server.server_port}/live/overlay/{channel}",flush=True)
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
