"""SYNTHETIC multi-character demo: a fictional streamer, a disposable SQLite and no network.

    python tools/character_demo.py create [--replace] [--characters 1|2|12] [--streamers 1-5] [--no-day]
    python tools/character_demo.py serve [--port 8890] [--live] [--offline [CHANNEL ...]] [--slow SECONDS]  # public-only local website
    python tools/character_demo.py switch               # two-frame switch to the next saved character

Readings go through the real automatic attribution path (two-frame name confirmation,
level floors, sessions per switch); only the OCR frames are generated. Never point this
at a tracking database: it only ever writes private/character-demo/demo.sqlite3.
"""

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
import threading
import time

from exp_tracker.character_automation import PLACEHOLDER_CHARACTER, AutonomousCharacters, name_evidence
from exp_tracker.diagnostics import Diagnostics
from exp_tracker.exp_requirements import requirement
from exp_tracker.pace_intervals import collect_observed, usable_endpoint
from exp_tracker.product import reading
from exp_tracker.rolling_history import recent_snapshot
from exp_tracker.store import Store

ROOT = Path(__file__).resolve().parents[1] / 'private' / 'character-demo'
DATABASE = ROOT / 'demo.sqlite3'
MARKER = ROOT / 'demo.sqlite3.synthetic.json'
CHANNEL = 'synthetic_demo'  # Fictional; never a Twitch login this demo connects to.
INTERVAL = 30
# (name, level, first basis points, basis points per reading, readings)
SCENARIO = [('Alpha', 67, 2000, 12, 24), ('Beta', 43, 5000, 25, 30), ('Alpha', 67, 2276, 12, 56)]
NAMES = ('Alpha', 'Beta', 'Gamma', 'Delta', 'Epsilon', 'Zeta', 'Eta', 'Theta', 'Iota', 'Kappa', 'Lambda', 'Mu')
# Extra fictional streams for homepage sorting: (channel, character, level, first bp, bp per reading, readings, minutes it ended before now).
# Ember and Frost share a level so level ties break on EXP %; Quiet ended hours ago, so it has a 24h total but no live pace.
STREAMS = [('synthetic_ember', 'Ember', 61, 7200, 30, 40, 0), ('synthetic_frost', 'Frost', 61, 4800, 9, 40, 0),
           ('synthetic_sprout', 'Sprout', 32, 1500, 70, 30, 0), ('synthetic_quiet', 'Quiet', 70, 3000, 6, 40, 180)]
# The job each generated status panel shows; the real two-read confirmation records it.
# Every job appears once; Quiet (an ended stream) repeats Cleric because there are 16 characters and 15 jobs.
JOBS = {'Alpha': 'Cleric', 'Beta': 'Hunter', 'Gamma': 'Bandit', 'Delta': 'Page', 'Epsilon': 'Wizard (Fire,Poison)', 'Zeta': 'Crossbowman',
        'Eta': 'Spearman', 'Theta': 'Assassin', 'Iota': 'Fighter', 'Kappa': 'Magician', 'Lambda': 'Swordsman', 'Mu': 'Wizard (Ice,Lightning)',
        'Ember': 'Archer', 'Frost': 'Rogue', 'Sprout': 'Beginner', 'Quiet': 'Cleric'}
LIVE_SECONDS = INTERVAL  # Same spacing as the generated history, so live paces match it.
OFFLINE = ('synthetic_frost', 'synthetic_quiet')  # `serve --offline` without names: one recent and one ended stream.
# Earlier sessions that fill the 24 h charts: (hours ago, readings) per half-hour slot, 30 s apart.
# Each stream's slots fit below its first bp above, so its EXP only rises and no level-up is synthesized.
DAY = {CHANNEL: ((21, 10), (20.5, 16), (20, 22), (19.5, 14), (8, 12), (7.5, 20), (7, 8)),
       'synthetic_ember': ((19.5, 10), (19, 16), (18.5, 22), (18, 14), (17.5, 8), (3.5, 18), (3, 12), (2.5, 20)),
       'synthetic_frost': ((23, 12), (22.5, 20), (22, 16), (21.5, 24), (21, 10), (20.5, 18), (10, 14), (9.5, 22), (9, 12)),
       'synthetic_sprout': ((6, 8), (5.5, 6), (2, 6)),
       'synthetic_quiet': ((16, 10), (15.5, 16), (15, 22), (14.5, 14), (14, 8), (13.5, 18), (13, 12), (12.5, 20), (12, 16), (11.5, 10), (11, 14))}


def configuration(run):
    return dict(type='configuration', trusted=False, run_id=run, interval=INTERVAL, automatic_characters=True,
                source_kind='file', timing_mode='real', character_names=True, synthetic_demo=True)


def attempt(index, name, level, bp, at, selected):
    """One generated full-frame reading, shaped like a capture attempt with name evidence."""
    need = requirement(level)['to_next']
    exp = need * bp // 10000
    pct = exp * 10000 // need / 100  # Truncated display, as the HUD shows it.
    stamp = at.isoformat()
    digest = hashlib.sha256(f'synthetic:{stamp}:{name}:{bp}'.encode()).hexdigest()
    text = f'{exp}[{pct:.2f}%]'
    job = JOBS.get(name)
    return dict(type='attempt', trusted=False, index=index, current=True, status='diagnostic_pair',
        attempted_at=stamp, received_at=stamp, frame_sha256=digest, local_age_seconds=0,
        source=dict(kind='file', channel=None), visual_level=level, visual_status='available',
        neural_status='single_line', candidate=[exp, pct], neural=dict(text=text), localization=dict(count=1),
        character_name=dict(reading_hold_recommended=name != selected, hold_reasons=['name_mismatch'] if name != selected else [],
            identity_conflict=None, evidence=dict(status='candidate', name=name, score=.99, received_at=stamp,
                pixel_sha256=digest, box=[1, 2, 50, 20], provenance=dict(layout_count=1, search='full_frame'),
                raw=dict(raw=dict(txts=[name], scores=[.99])),
                **({'job': dict(status='candidate', job=job, text=job, score=.99, box=[1, 0, 50, 2])} if job else {}))))


def latest_run(store, channel):
    return store.db.execute('SELECT r.run_id FROM diagnostic_runs r JOIN streamers s ON s.id=r.streamer_id WHERE s.login=? '
                            'ORDER BY r.rowid DESC LIMIT 1', (channel,)).fetchone()[0]


def append(store, readings, channel=CHANNEL):
    """Feed (name, level, bp, at) readings through automatic attribution; returns switch receipts."""
    policy, switches = AutonomousCharacters(store), []
    for name, level, bp, at in readings:
        run = latest_run(store, channel)
        selected = store.db.execute('SELECT c.label FROM streamers s JOIN characters c ON c.id=s.selected_character_id WHERE s.login=?',
                                    (channel,)).fetchone()[0]
        index = store.db.execute('SELECT COUNT(*) FROM diagnostic_attempts WHERE run_id=?', (run,)).fetchone()[0] + 1
        if index > 60:  # A full run rotates to a fresh one, as the coordinator's scheduled rotation does.
            following = hashlib.sha256(f'{run}:rotation'.encode()).hexdigest()[:32]
            Diagnostics(store).rotate(run, following, channel, dict(type='summary', trusted=False, attempts=index - 1, interrupted=False,
                completion_reason='scheduled_rotation', next_run_id=following), configuration(following))
            run, index = following, 1
        following = hashlib.sha256(f'{run}:{index}'.encode()).hexdigest()[:32]
        receipt = policy.append(run, attempt(index, name, level, bp, at, selected), following, configuration(following))
        if receipt['switched']:switches.append(receipt)
    return switches


def start(store, channel, run, first):
    store.add_channel(channel)
    placeholder = store.add_character(channel, PLACEHOLDER_CHARACTER)
    store.select_character(channel, placeholder, at=first - timedelta(seconds=1))
    store.start_session(channel, at=first - timedelta(seconds=1))
    Diagnostics(store).begin(run, channel, configuration(run))


def day(channel, name, level, bp, step, now):
    """Earlier readings ending just below bp, for a channel's DAY sessions."""
    slots = DAY.get(channel, ())
    bp -= step * sum(count for _, count in slots)
    if bp < 0:raise ValueError(f'{channel}: its earlier sessions need more EXP than its first reading has')
    readings = []
    for hours, count in slots:
        for i in range(count):
            readings.append((name, level, bp, now - timedelta(hours=hours) + timedelta(seconds=INTERVAL * i))); bp += step
    return readings


def create(*, now, path=DATABASE, characters=2, streamers=1, history=False):
    """The scenario ends one interval before now, so recent windows show the return to Alpha.
    history adds earlier sessions across the last 24 hours (DAY) before each stream's recent readings."""
    if characters not in (1, 2, 12):raise ValueError('Choose 1, 2 or 12 synthetic characters')
    if not 1 <= streamers <= len(STREAMS) + 1:raise ValueError(f'Choose 1 to {len(STREAMS) + 1} synthetic streamers')
    scenario = SCENARIO if characters == 2 else [(name, 43 + i, 2000 + 200 * i, 12, 8) for i, name in enumerate(NAMES[:characters])]
    total = sum(row[4] for row in scenario)
    at = now - timedelta(seconds=INTERVAL * total)
    readings = []
    for name, level, bp, step, count in scenario:
        for i in range(count):
            readings.append((name, level, bp + step * i, at)); at += timedelta(seconds=INTERVAL)
    streams = [(CHANNEL, (day(CHANNEL, *scenario[0][:4], now) if history else []) + readings)]
    for channel, name, level, bp, step, count, ago in STREAMS[:streamers - 1]:
        first = now - timedelta(minutes=ago, seconds=INTERVAL * count)
        streams.append((channel, (day(channel, name, level, bp, step, now) if history else [])
                        + [(name, level, bp + step * i, first + timedelta(seconds=INTERVAL * i)) for i in range(count)]))
    with Store(path) as store:
        switches = []
        for channel, rows in streams:
            if [r[3] for r in rows] != sorted(r[3] for r in rows):raise ValueError(f'{channel}: earlier sessions overlap its recent readings')
            start(store, channel, 'synthetic-start' if channel == CHANNEL else f'synthetic-start-{channel}', rows[0][3])
            switches += append(store, rows, channel)
        return switches


def tick(store, *, now, offline=()):
    """One live frame per recently active demo stream; returns {channel: run_id} for the stand-in coordinator."""
    steps = {channel: step for channel, _, _, _, step, _, ago in STREAMS if not ago}
    live = {}
    for (channel,) in store.db.execute('SELECT login FROM streamers ORDER BY login').fetchall():
        if channel != CHANNEL and channel not in steps or channel in offline:continue  # Ended and offline streams stay ended.
        name = store.db.execute('SELECT c.label FROM streamers s JOIN characters c ON c.id=s.selected_character_id WHERE s.login=?',
                                (channel,)).fetchone()[0]
        run = latest_run(store, channel)
        rows = store.db.execute('SELECT a.payload_json FROM diagnostic_attempts a JOIN diagnostic_runs r ON r.run_id=a.run_id '
                                'JOIN streamers s ON s.id=r.streamer_id WHERE s.login=? ORDER BY a.attempted_at DESC LIMIT 20', (channel,)).fetchall()
        last = next((p for p in map(lambda row: json.loads(row[0]), rows) if (name_evidence(p) or {}).get('name') == name), None)
        if last is None:continue
        level, need = last['visual_level'], requirement(last['visual_level'])['to_next']
        bp = -(-last['candidate'][0] * 10000 // need) + steps.get(channel, 12)
        if bp >= 9990:continue  # Stop short of a level-up rather than synthesize one.
        append(store, [(name, level, bp, now)], channel)
        live[channel] = latest_run(store, channel)
    return live


def switch(*, now, path=DATABASE):
    """Two fresh frames of the other character: the server sees a live automatic switch."""
    with Store(path) as store:
        selected = store.db.execute('SELECT c.label FROM streamers s JOIN characters c ON c.id=s.selected_character_id WHERE s.login=?',
                                    (CHANNEL,)).fetchone()[0]
        roster = [r for r in Diagnostics(store).roster(CHANNEL) if r['label'] != PLACEHOLDER_CHARACTER]
        if len(roster) < 2:raise ValueError('Switching requires at least two synthetic characters')
        target = roster[(next(i for i, r in enumerate(roster) if r['label'] == selected) + 1) % len(roster)]
        name, step = target['label'], 25 if target['label'] == 'Beta' else 12
        # Replay the public validators; raw switch-out attempts may belong to the NEXT character.
        snap = recent_snapshot(Diagnostics(store), CHANNEL, now=now, character=target['id'], _historical=True)
        points = collect_observed(snap, now=now, read=reading, max_interval_seconds=120)['points']
        baseline = None
        for point in reversed(points):
            if not usable_endpoint(point) or point['exp'] is None:continue
            run, index = point['event_id'].rsplit(':', 1)
            row = store.db.execute('SELECT payload_json FROM diagnostic_attempts WHERE run_id=? AND attempt_index=?', (run, int(index))).fetchone()
            evidence = name_evidence(json.loads(row[0])) if row else None
            if evidence and evidence['name'] == name:
                baseline = point;break
        if baseline is None:raise ValueError(f'No confirmed numeric endpoint for {name}; rebuild the synthetic demo')
        level, bp = baseline['level']['value'], baseline['bp'] + step
        if bp + step >= 10000:raise ValueError('Synthetic character is near a level-up; rebuild the demo')
        latest = datetime.fromisoformat(store.db.execute('SELECT MAX(attempted_at) FROM diagnostic_attempts').fetchone()[0])
        first = max(now - timedelta(seconds=INTERVAL), latest + timedelta(microseconds=1))
        if first >= now:raise ValueError('Switch timestamps must be newer than the previous demo capture')
        return append(store, [(name, level, bp, first), (name, level, bp + step, now)])


def offline_twitch(server, channels):
    """Stand-in Twitch check: these demo streams report offline. Nothing is requested from Twitch."""
    check = server.twitch_availability.snapshot
    def snapshot(logins, *, now=None):
        now = now or datetime.now(timezone.utc)
        return {**check(logins, now=now), **{c: dict(status='offline', reason=None, checked_at=now.isoformat(), source='synthetic_demo',
            valid_until=(now + timedelta(seconds=60)).isoformat(), last_known_status=None) for c in channels}}
    server.twitch_availability.snapshot = snapshot


def live_loop(server, offline=()):
    """Stands in for the capture coordinator so demo streams read as live; real capture is never started."""
    while True:
        now = datetime.now(timezone.utc)
        with Store(DATABASE) as store:live = tick(store, now=now, offline=offline)
        for channel, run in live.items():
            server.active_run_ids.add(run)
            server.coordinator_status[channel] = dict(state='waiting', updated_at=now.isoformat(), run_id=run,
                                                      next_due_at=(now + timedelta(seconds=LIVE_SECONDS)).isoformat())
        time.sleep(LIVE_SECONDS)


def main(argv=None):
    cli = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = cli.add_subparsers(dest='command', required=True)
    create_cli = commands.add_parser('create')
    create_cli.add_argument('--replace', action='store_true', help='Replace a previous SYNTHETIC demo database')
    create_cli.add_argument('--characters', type=int, choices=(1, 2, 12), default=2, help='Synthetic roster size (default: 2)')
    create_cli.add_argument('--streamers', type=int, default=1, help=f'Fictional streamers on the homepage, 1-{len(STREAMS) + 1} (default: 1)')
    create_cli.add_argument('--no-day', dest='history', action='store_false', help='Only the recent readings, without earlier sessions across the last 24 hours')
    serve_cli = commands.add_parser('serve')
    serve_cli.add_argument('--port', type=int, default=8890)
    serve_cli.add_argument('--live', action='store_true', help=f'Keep demo streams updating every {LIVE_SECONDS}s (writes only the demo database)')
    serve_cli.add_argument('--offline', nargs='*', metavar='CHANNEL', help=f'Show these demo streams as offline on Twitch, with no live updates (default: {" ".join(OFFLINE)})')
    serve_cli.add_argument('--slow', type=float, default=0, metavar='SECONDS', help='Add this delay to every page build, like a busy server (0-60, e.g. 8)')
    commands.add_parser('switch')
    args = cli.parse_args(argv)
    try:
        if args.command == 'create':
            if DATABASE.exists() or MARKER.exists():
                if not args.replace:raise ValueError(f'{DATABASE} exists; pass --replace to rebuild the synthetic demo')
                if not MARKER.is_file() or json.loads(MARKER.read_text(encoding='utf-8')).get('synthetic') is not True:
                    raise ValueError('Refusing to replace a database without the synthetic demo marker')
                for suffix in ('', '-wal', '-shm'):
                    DATABASE.with_name(DATABASE.name + suffix).unlink(missing_ok=True)
            ROOT.mkdir(parents=True, exist_ok=True)
            MARKER.write_text(json.dumps(dict(synthetic=True, channel=CHANNEL)), encoding='utf-8')
            for receipt in create(now=datetime.now(timezone.utc), characters=args.characters, streamers=args.streamers, history=args.history):
                print(f"SYNTHETIC: automatically selected {receipt['name']} / character {receipt['character_id']}")
            print(f'SYNTHETIC demo database: {DATABASE}')
        elif args.command == 'switch':
            if not MARKER.is_file():raise ValueError('Create the synthetic demo first')
            for receipt in switch(now=datetime.now(timezone.utc)):
                print(f"SYNTHETIC: automatically selected {receipt['name']} / character {receipt['character_id']}")
        else:
            if not MARKER.is_file():raise ValueError('Create the synthetic demo first')
            if args.port == 8765 or not 0 <= args.port <= 65535:raise ValueError('Choose a free port other than the main tracker 8765')
            if not 0 <= args.slow <= 60:raise ValueError('--slow takes 0 to 60 seconds')
            if args.slow:
                card = Diagnostics.card
                Diagnostics.card = lambda self, *a, **k: time.sleep(args.slow) or card(self, *a, **k)
                print(f'Every page build takes {args.slow:g}s longer (a simulated busy server)', flush=True)
            offline = set()
            if args.offline is not None:
                with Store(DATABASE, read_only=True) as store:known = {row[0] for row in store.db.execute('SELECT login FROM streamers')}
                offline = set(args.offline) if args.offline else known & set(OFFLINE)
                if offline - known:raise ValueError(f'Unknown demo streams: {", ".join(sorted(offline - known))}')
            from exp_tracker.server import create_server
            with create_server(DATABASE, port=args.port, public_only=True, background=True) as server:
                if offline:offline_twitch(server, offline);print(f'Offline on Twitch: {", ".join(sorted(offline))}', flush=True)
                print(f'SYNTHETIC demo (fictional streamer, no Twitch): http://127.0.0.1:{server.server_port}/stream/{CHANNEL}', flush=True)
                print(f'Homepage: http://127.0.0.1:{server.server_port}/   Overlay: http://127.0.0.1:{server.server_port}/live/overlay/{CHANNEL}', flush=True)
                if args.live:threading.Thread(target=live_loop, args=(server, offline), daemon=True).start()
                try:server.serve_forever()
                except KeyboardInterrupt:pass
        return 0
    except (OSError, ValueError) as error:
        print(f'Character demo stopped: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
