"""Separate loopback operator dashboard: python -m exp_tracker.admin_server --db PATH."""
import argparse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time
from urllib.parse import parse_qs, urlsplit
import uuid

from .manual_admin import inspect, percentage, timestamp, writable_store
from .manual import corrected_reading
from .store import Store, utc

WEB = Path(__file__).with_name('web')
PREVIEW_SECONDS = 900
ROSTER_NOTICE = ('Rename preserves the character ID. Before the next coordinator startup, '
                 'update the matching private roster character label and run its preflight. '
                 'This dashboard does not edit configuration or restart capture.')


def integer(value, name):
    # Decimal strings keep SQLite's full integer precision across the browser boundary.
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,19}', value):
        raise ValueError(f'{name} must be a decimal integer')
    return int(value)


def character(store, channel, identity):
    cid = integer(identity, 'character ID')
    result = next((c for c in store.state(channel)['characters'] if c['id'] == cid), None)
    if result is None:
        raise ValueError('character does not belong to channel')
    return result


def operation(data):
    """Validate transport fields; Store remains the authority for correction rules."""
    if not isinstance(data, dict):
        raise ValueError('expected a JSON object')
    action = data.get('action')
    if action not in ('set', 'correct', 'amend', 'undo', 'clear', 'rename'):
        raise ValueError('unknown administration action')
    allowed = {'action', 'channel', 'character_id', 'reason'}
    if action == 'rename':
        allowed |= {'new_name'}
    elif action == 'undo':
        allowed |= {'correction_id'}
    else:
        allowed |= {'session_id', 'effective_at', 'use_now'}
        if action != 'clear':
            allowed |= {'level', 'exp', 'percentage'}
        if action in ('correct', 'amend'):
            allowed |= {'target_kind', 'target_event_id'}
        if action == 'amend':
            allowed |= {'correction_id', 'kind'}
    if data.keys() - allowed:
        raise ValueError('unexpected fields: ' + ', '.join(sorted(data.keys() - allowed)))
    if any(not isinstance(v, str) for k, v in data.items() if k != 'use_now'):
        raise ValueError('form fields must be strings; use_now must be a boolean')
    if not re.fullmatch(r'[A-Za-z0-9_]{1,25}', data.get('channel', '')):
        raise ValueError('select an existing Twitch channel')
    integer(data.get('character_id'), 'character ID')
    result = dict(data, event_id=uuid.uuid4().hex)
    if action not in ('rename', 'undo'):
        now = data.get('use_now', False)
        if type(now) is not bool or now and 'effective_at' in data:
            raise ValueError('choose an explicit timestamp or Use current timestamp, exclusively')
        if not now and 'effective_at' not in data:
            raise ValueError('enter an explicit timestamp or select Use current timestamp')
        # An explicit current-time choice freezes the exact previewed time for saving.
        result['effective_at'] = utc(datetime.now(timezone.utc) if now else timestamp(data['effective_at']))
    return result


def apply(store, data):
    channel = data['channel']; action = data['action']
    selected = character(store, channel, data['character_id'])
    reason = data.get('reason') or None
    if action == 'rename':
        return store.rename_character(channel, selected['id'], data.get('new_name'), reason=reason)
    if action == 'undo':
        cid = integer(data.get('correction_id'), 'correction ID')
        previous = next((e for e in store.manual_history(channel) if e['id'] == cid), None)
        if previous is None or previous['character_id'] != selected['id']:
            raise ValueError('correction does not belong to the selected channel/character')
        return store.retract_manual(channel, data['event_id'], cid, reason=reason)
    kind = 'point' if action == 'correct' else 'baseline'
    replaces = None
    if action == 'amend':
        replaces = integer(data.get('correction_id'), 'correction ID')
        previous = store._manual_revision(channel, replaces)
        kind = data.get('kind', previous['kind'])
    session = data.get('session_id', 'auto')
    if kind == 'point' and (not data.get('target_event_id') or data.get('target_kind') not in ('diagnostic', 'observation')):
        raise ValueError('a historical correction needs its original reading identity and type')
    return store.correct_manual(channel, data['event_id'], selected['id'],
        level=integer(data['level'], 'level') if 'level' in data else None,
        current_exp=integer(data['exp'], 'EXP') if 'exp' in data else None,
        percentage_bp=percentage(data['percentage']) if 'percentage' in data else None,
        effective_at=timestamp(data['effective_at']), reason=reason, clear=action == 'clear',
        session_id=integer(session, 'session ID') if session not in ('auto', 'none') else None,
        no_session=session == 'none', kind=kind, replaces_id=replaces,
        target_kind=data.get('target_kind'), target_event_id=data.get('target_event_id'))


def details(store, channel, cid, session=None):
    selected = character(store, channel, cid)
    result = inspect(store, channel, selected, session)
    result['character'] = selected
    for row in result['readings']:
        if row['kind'] == 'observation' and row['presentation'] is None:
            original = row['original']; bp = original['percentage_bp']
            row['presentation'] = dict(level=dict(value=original['level']),
                exp=str(original['current_exp']) if original['current_exp'] is not None else None,
                percentage=f'{bp//100}.{bp%100:02}' if bp is not None else None,
                evidence='trusted_sqlite_ocr' if original['outcome'] in ('accepted','baseline') else 'rejected_sqlite_ocr',
                timestamp=row['timestamp'])
    result['corrections'] = store.manual_history(channel, character_id=selected['id'])
    result['renames'] = [dict(r) for r in store.db.execute(
        'SELECT * FROM character_renames WHERE character_id=? ORDER BY id DESC', (selected['id'],))] if store.schema_version >= 6 else []
    return result


class AdminServer(ThreadingHTTPServer):
    def __init__(self, database, port):
        self.database = Path(database).resolve()
        if not self.database.is_file():
            raise ValueError('database must already exist')
        with Store(self.database, read_only=True):
            pass
        self.token = secrets.token_urlsafe(32)
        self.previews = {}
        self.lock = threading.Lock()
        # No configurable host: the public server and operator interface are separate.
        super().__init__(('127.0.0.1', port), Handler)
        self.origin = f'http://127.0.0.1:{self.server_port}'

    def preview(self, raw):
        data = operation(raw)
        with writable_store(self.database, True) as store:
            selected = character(store, data['channel'], data['character_id'])
            event = apply(store, data)
            result = dict(action=data['action'], channel=data['channel'], character=selected, event=event,
                          timestamp_choice='inherited from correction' if data['action'] == 'undo' else
                          'current time at preview' if data.get('use_now') else 'explicit time',
                          reading=corrected_reading(event) if event.get('action') == 'set' else None,
                          notice=ROSTER_NOTICE if data['action'] == 'rename' else
                          'Operator adjustment, not earned EXP. Existing OCR, history and precedence rules apply.')
        with self.lock:
            self.previews = {k:v for k,v in self.previews.items() if v['expires'] > time.monotonic()}
            if len(self.previews) >= 64:
                self.previews.pop(next(iter(self.previews)))
            identity = secrets.token_urlsafe(24)
            self.previews[identity] = dict(data=data, expires=time.monotonic()+PREVIEW_SECONDS,
                                           character_label=selected['label'], result=None)
        return dict(preview_id=identity, expires_in_seconds=PREVIEW_SECONDS, **result)

    def save(self, identity):
        with self.lock:
            item = self.previews.get(identity)
            if item is None or item['expires'] <= time.monotonic():
                raise ValueError('preview expired or is unknown; preview again before saving')
            if item['result'] is not None:
                return item['result']
            data = item['data']
            with writable_store(self.database, False) as store:
                if character(store, data['channel'], data['character_id'])['label'] != item['character_label']:
                    raise ValueError('character name changed since preview; refresh and preview again')
                event = apply(store, data)
            item['result'] = dict(action=data['action'], event=event, saved=True,
                                  notice=ROSTER_NOTICE if data['action'] == 'rename' else 'Saved with manual_admin provenance.')
            return item['result']


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def reply(self, status, body, content_type='application/json'):
        def wire(value):
            if isinstance(value, dict):
                return {k:str(v) if k == 'current_exp' and type(v) is int else wire(v) for k,v in value.items()}
            if isinstance(value, list):return [wire(v) for v in value]
            return value
        payload = json.dumps(wire(body), allow_nan=False).encode() if content_type == 'application/json' else body
        self.send_response(status)
        for name, value in [('Content-Type', content_type+'; charset=utf-8'), ('Content-Length', str(len(payload))),
                ('Cache-Control', 'no-store'), ('X-Content-Type-Options', 'nosniff'), ('Referrer-Policy', 'no-referrer'),
                ('Content-Security-Policy', "default-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")]:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(payload)

    def protected(self, api=False, write=False):
        host = self.server.origin.removeprefix('http://')
        if self.client_address[0] != '127.0.0.1' or self.headers.get_all('Host') != [host]:
            self.reply(403, dict(error='use the exact loopback URL printed at startup')); return False
        origins = self.headers.get_all('Origin')
        if (origins is not None and origins != [self.server.origin] or write and origins != [self.server.origin]
                or self.headers.get('Sec-Fetch-Site') == 'cross-site'):
            self.reply(403, dict(error='same-origin operator request required')); return False
        tokens = self.headers.get_all('X-Admin-Token', [])
        if api and (len(tokens) != 1 or not secrets.compare_digest(tokens[0].encode(), self.server.token.encode())):
            self.reply(403, dict(error='operator request token missing or invalid; reload the dashboard')); return False
        return True

    def do_GET(self):
        url = urlsplit(self.path)
        if not self.protected(api=url.path.startswith('/api/')):
            return
        try:
            if url.path == '/' and not url.query:
                body = (WEB/'admin.html').read_bytes().replace(b'__ADMIN_TOKEN__', self.server.token.encode())
                self.reply(200, body, 'text/html')
            elif url.path in ('/admin.js', '/admin.css') and not url.query:
                self.reply(200, (WEB/url.path[1:]).read_bytes(), 'text/javascript' if url.path.endswith('.js') else 'text/css')
            elif url.path == '/api/channels' and not url.query:
                with Store(self.server.database, read_only=True) as store:
                    channels = [dict(r) for r in store.db.execute('SELECT login,selected_character_id FROM streamers ORDER BY login')]
                self.reply(200, dict(channels=channels, database=str(self.server.database)))
            elif url.path == '/api/inspect':
                query = parse_qs(url.query, keep_blank_values=True, max_num_fields=3)
                if query.keys()-{'channel', 'character_id', 'session_id'} or any(len(v) != 1 for v in query.values()) or 'channel' not in query:
                    raise ValueError('invalid inspection query')
                channel = query['channel'][0]
                with Store(self.server.database, read_only=True) as store:
                    cid = query.get('character_id', [str(store.state(channel)['selected_character_id'])])[0]
                    if cid == 'None':
                        self.reply(200, dict(characters=store.state(channel)['characters'], character=None)); return
                    session = integer(query['session_id'][0], 'session ID') if 'session_id' in query else None
                    self.reply(200, details(store, channel, cid, session))
            else:
                self.reply(404, dict(error='not found'))
        except (ValueError, argparse.ArgumentTypeError) as error:
            self.reply(400, dict(error=str(error)))
        except (sqlite3.Error, OSError) as error:
            self.reply(503, dict(error=f'database or file unavailable: {error}'))

    def do_POST(self):
        if not self.protected(api=True, write=True):
            return
        try:
            if self.path not in ('/api/preview', '/api/save'):
                self.reply(404, dict(error='not found')); return
            lengths = self.headers.get_all('Content-Length', [])
            if self.headers.get('Transfer-Encoding') or len(lengths) != 1 or not re.fullmatch(r'[0-9]{1,5}', lengths[0]):
                raise ValueError('a single bounded Content-Length is required')
            if int(lengths[0]) > 16384 or self.headers.get_content_type() != 'application/json':
                raise ValueError('request must be application/json, at most 16 KiB')
            def unique(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:raise ValueError('duplicate JSON field: '+key)
                    result[key] = value
                return result
            data = json.loads(self.rfile.read(int(lengths[0])), object_pairs_hook=unique)
            if self.path == '/api/preview':
                result = self.server.preview(data)
            else:
                if not isinstance(data, dict) or set(data) != {'preview_id'} or not isinstance(data['preview_id'], str):
                    raise ValueError('saving requires only a preview_id; preview changes first')
                result = self.server.save(data['preview_id'])
            self.reply(200, result)
        except (ValueError, argparse.ArgumentTypeError, UnicodeError) as error:
            self.reply(409 if self.path == '/api/save' else 400, dict(error=str(error)))
        except (sqlite3.Error, OSError) as error:
            self.reply(503, dict(error=f'database unavailable; inspect before retrying: {error}'))

    def do_OPTIONS(self):
        self.reply(405, dict(error='cross-origin requests are not supported'))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True, type=Path)
    parser.add_argument('--port', type=int, default=8766)
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error('port must be 0..65535')
    try:
        with AdminServer(args.db, args.port) as server:
            print(f'Local operator dashboard: {server.origin}/\nDatabase: {server.database}', flush=True)
            server.serve_forever()
    except KeyboardInterrupt:
        pass
    except (ValueError, OSError, sqlite3.Error) as error:
        parser.exit(2, f'error: {error}\n')


if __name__ == '__main__':
    raise SystemExit(main())
