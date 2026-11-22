"""Stuck-stream alerts, run by `msxp alert` (every 5 minutes on a server, from msxp-alert.timer).

A stream is stuck when it has been captured for the whole window, its HUD was on screen in at least half of
those captures, and none gave a usable reading. Each stuck episode posts one Discord message and one more
when readings resume. Read-only on the database; the webhook URL is never printed.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .msxp import ROOT, path, settings
from .store import Store

USABLE = ('diagnostic_pair', 'diagnostic_percentage_only')
EDGE = timedelta(minutes=5)  # Recent captures and a pre-window capture establish coverage to this precision.
REPEAT = timedelta(hours=6)  # A stream that flaps between stuck and fine is reported at most this often.
STATE = 'private/alert-state.json'


def windows(settings):
    """Default window plus explicit, case-insensitive per-channel increases."""
    minutes = float(settings['MSXP_ALERT_MINUTES'])
    if not math.isfinite(minutes) or not 1 <= minutes <= 1440:
        raise ValueError('MSXP_ALERT_MINUTES must be 1..1440')
    default, overrides = timedelta(minutes=minutes), {}
    value = settings.get('MSXP_ALERT_STREAM_MINUTES', '').strip()
    for entry in value.split(',') if value else []:
        login, separator, raw = entry.strip().partition('=')
        if not separator or not re.fullmatch(r'[A-Za-z0-9_]{1,25}', login):
            raise ValueError('MSXP_ALERT_STREAM_MINUTES expects LOGIN=MINUTES, separated by commas')
        count = float(raw)
        if not math.isfinite(count) or not minutes <= count <= 1440 or login.lower() in overrides:
            raise ValueError('Streamer alert minutes must be unique and between the default and 1440')
        overrides[login.lower()] = timedelta(minutes=count)
    return default, overrides


def attempts(store, since, *, cutoffs=None):
    """Open-session attempts plus five minutes of coverage context, through the session/time index."""
    cutoff, params = '?', [(since - EDGE).isoformat()]
    if cutoffs:
        cutoff = 'CASE lower(st.login) ' + 'WHEN ? THEN ? ' * len(cutoffs) + 'ELSE ? END'
        params = [value for login, at in cutoffs.items() for value in (login, (at - EDGE).isoformat())] + params
    return [(r[0], datetime.fromisoformat(r[1]), json.loads(r[2])) for r in store.db.execute(
        f'''SELECT st.login, a.attempted_at, a.payload_json FROM sessions s JOIN streamers st ON st.id=s.streamer_id
           JOIN diagnostic_attempts a ON a.session_id=s.id AND a.attempted_at>={cutoff}
           WHERE s.ended_at IS NULL ORDER BY a.attempted_at''', params)]


def summary(rows, now, window, overrides=None):
    """{login: dict(stuck, usable_at, last_at, reason, level)} from one window of attempts."""
    found = {}
    for login, at, payload in rows:
        duration = (overrides or {}).get(login.lower(), window)
        if not now - duration - EDGE <= at <= now:continue
        s = found.setdefault(login, dict(first=at, last_at=at, usable_at=None, hud=0, count=0, reasons={}, levels={}, window=duration))
        if at < now - duration:continue  # Coverage only; older readings cannot reset the waiting period.
        held = payload.get('level_hold') or payload.get('identity_hold') or {}
        evidence = held.get('evidence') or payload
        s['last_at'], s['count'] = at, s['count'] + 1
        s['hud'] += (evidence.get('localization') or {}).get('count') == 1
        if payload.get('status') in USABLE:s['usable_at'] = at
        reason = held.get('reason') or payload.get('status') or 'unknown'
        s['reasons'][reason] = s['reasons'].get(reason, 0) + 1
        level = (evidence.get('neural_level') or {}).get('level')
        if level is not None:s['levels'][level] = s['levels'].get(level, 0) + 1
    for s in found.values():
        s['stuck'] = bool(s['count'] and now - s['last_at'] <= EDGE and s['first'] <= now - s['window']
                      and s['usable_at'] is None and 2 * s['hud'] >= s['count'])
        s['reason'] = max(s['reasons'], key=s['reasons'].get) if s['reasons'] else 'no_recent_captures'
        s['level'] = max(s['levels'], key=s['levels'].get) if s['levels'] else None
    return found


def recovered_readings(store, found, now):
    """Before alerting, consult the same judged reading used by the website."""
    from .diagnostics import Diagnostics
    diagnostics = Diagnostics(store)
    for login, result in found.items():
        if not result['stuck']:continue
        with store._transaction():
            heads = diagnostics.heads(login)
            reading = diagnostics.card({}, heads[0], now=now)[1]['player'].get('reading') if heads else None
        if not reading or not reading.get('fresh_at_capture') or reading.get('simulated'):continue
        at = datetime.fromisoformat(reading['timestamp'])
        if now - result['window'] <= at <= now:
            result.update(stuck=False, usable_at=at)


def step(state, found, now, window, link=''):
    """(messages, new state). State per login: alerted_at, and open while the alert awaits recovery."""
    state, messages = {k: dict(v) for k, v in state.items()}, []
    for login, s in sorted(found.items()):
        known = state.get(login)
        if not s['stuck'] or known and (known['open'] or now - datetime.fromisoformat(known['alerted_at']) < REPEAT):continue
        level = f", HUD shows Lv. {s['level']}" if s['level'] is not None else ''
        page = f' {link.rstrip("/")}/stream/{login}' if link else ''
        messages.append(f"⚠️ **{login}** looks stuck: HUD detected in at least half the captures but no usable reading for "
                        f"{int(s.get('window', window).total_seconds() // 60)} min (mostly {s['reason']}{level}).{page}")
        state[login] = dict(alerted_at=now.isoformat(), open=True)
    for login, known in sorted(state.items()):
        s = found.get(login)
        if not known['open'] or s and s['stuck']:continue
        if s and s['usable_at'] and s['usable_at'] > datetime.fromisoformat(known['alerted_at']):
            messages.append(f'✅ **{login}** is reading again.');known['open'] = False
        elif not s or now - s['last_at'] > 2 * EDGE:known['open'] = False  # Ended while stuck: the next stream alerts again.
    return messages, state


def send(webhook, text):
    """Posts to a Discord webhook. Errors name the HTTP status only: the URL itself is the secret."""
    body = json.dumps(dict(content=text[:2000], allowed_mentions=dict(parse=[]))).encode()
    request = Request(webhook, body, {'Content-Type': 'application/json', 'User-Agent': 'msxp-alert (1.0)'})
    try:
        with urlopen(request, timeout=15):return True
    except HTTPError as error:print(f'alert: webhook answered HTTP {error.code}', flush=True)
    except (URLError, OSError) as error:print(f'alert: webhook unreachable ({type(error).__name__})', flush=True)
    return False


def load(file):
    try:return json.loads(Path(file).read_text(encoding='utf-8'))
    except (OSError, ValueError):return {}


def check(db, s, *, dry_run=False, state_file=None):
    window, overrides = windows(s)
    file, now = Path(state_file or ROOT / STATE), datetime.now(timezone.utc)
    with Store(db, read_only=True) as store:
        rows = attempts(store, now - window, cutoffs={login:now-duration for login,duration in overrides.items()})
        found = summary(rows, now, window, overrides)
        recovered_readings(store, found, now)
    messages, state = step(load(file).get('streams', {}), found, now, window, s['MSXP_FRONTEND_ORIGIN'])
    stuck = sorted(login for login, v in found.items() if v['stuck'])
    print(f'alert: {len(found)} capturing, stuck: {", ".join(stuck) or "none"}', flush=True)
    for text in messages:print(f'alert: {"would send" if dry_run else "send"}: {text}', flush=True)
    # One post per run, so a failure leaves the state unchanged and the next run retries all of it.
    if messages and not dry_run and s['MSXP_ALERT_WEBHOOK'] and not send(s['MSXP_ALERT_WEBHOOK'], '\n'.join(messages)):return 1
    if messages and not s['MSXP_ALERT_WEBHOOK']:print('alert: no MSXP_ALERT_WEBHOOK set, so nothing was sent', flush=True)
    if not dry_run:
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(json.dumps(dict(checked_at=now.isoformat(), streams=state), indent=1), encoding='utf-8')
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog='msxp alert', description=__doc__.split('\n')[0])
    parser.add_argument('--db', help='tracker database (required except with --test)')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--test', action='store_true', help='send a test message and exit')
    mode.add_argument('--dry-run', action='store_true', help='show what would be sent; send and save nothing')
    mode.add_argument('--watch', action='store_true', help='check every 5 minutes until stopped (for a PC)')
    args, s = parser.parse_args(argv), settings()
    if args.test:
        if not s['MSXP_ALERT_WEBHOOK']:print('No MSXP_ALERT_WEBHOOK set (in .env, or /etc/msxp/alert.env on a server).');return 1
        ok = send(s['MSXP_ALERT_WEBHOOK'], '🔔 msxp alert test: alerts reach this channel.')
        print('Test message sent.' if ok else 'Test message failed; see above.');return 0 if ok else 1
    if not args.db:parser.error('--db is required')
    db = path(args.db)
    while True:
        try:code = check(db, s, dry_run=args.dry_run)
        except ValueError as error:parser.error(str(error))
        if not args.watch:return code
        time.sleep(300)
        s = settings()


if __name__ == '__main__':
    sys.exit(main())
