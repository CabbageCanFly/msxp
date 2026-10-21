"""SYNTHETIC multi-character demo: a fictional streamer, a disposable SQLite and no network.

    python tools/character_demo.py create [--replace] [--characters 1|2|12]
    python tools/character_demo.py serve [--port 8890]  # public-only local website
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
    return dict(type='attempt', trusted=False, index=index, current=True, status='diagnostic_pair',
        attempted_at=stamp, received_at=stamp, frame_sha256=digest, local_age_seconds=0,
        source=dict(kind='file', channel=None), visual_level=level, visual_status='available',
        neural_status='single_line', candidate=[exp, pct], neural=dict(text=text), localization=dict(count=1),
        character_name=dict(reading_hold_recommended=name != selected, hold_reasons=['name_mismatch'] if name != selected else [],
            identity_conflict=None, evidence=dict(status='candidate', name=name, score=.99, received_at=stamp,
                pixel_sha256=digest, box=[1, 2, 50, 20], provenance=dict(layout_count=1, search='full_frame'),
                raw=dict(raw=dict(txts=[name], scores=[.99])))))


def append(store, readings):
    """Feed (name, level, bp, at) readings through automatic attribution; returns switch receipts."""
    policy, switches = AutonomousCharacters(store), []
    for name, level, bp, at in readings:
        run = store.db.execute('SELECT run_id FROM diagnostic_runs ORDER BY rowid DESC LIMIT 1').fetchone()[0]
        selected = store.db.execute('SELECT c.label FROM streamers s JOIN characters c ON c.id=s.selected_character_id WHERE s.login=?',
                                    (CHANNEL,)).fetchone()[0]
        index = store.db.execute('SELECT COUNT(*) FROM diagnostic_attempts WHERE run_id=?', (run,)).fetchone()[0] + 1
        following = hashlib.sha256(f'{run}:{index}'.encode()).hexdigest()[:32]
        receipt = policy.append(run, attempt(index, name, level, bp, at, selected), following, configuration(following))
        if receipt['switched']:switches.append(receipt)
    return switches


def create(*, now, path=DATABASE, characters=2):
    """The scenario ends one interval before now, so recent windows show the return to Alpha."""
    if characters not in (1, 2, 12):raise ValueError('Choose 1, 2 or 12 synthetic characters')
    scenario = SCENARIO if characters == 2 else [(name, 43 + i, 2000 + 200 * i, 12, 8) for i, name in enumerate(NAMES[:characters])]
    total = sum(row[4] for row in scenario)
    at = now - timedelta(seconds=INTERVAL * total)
    readings = []
    for name, level, bp, step, count in scenario:
        for i in range(count):
            readings.append((name, level, bp + step * i, at)); at += timedelta(seconds=INTERVAL)
    with Store(path) as store:
        store.add_channel(CHANNEL)
        placeholder = store.add_character(CHANNEL, PLACEHOLDER_CHARACTER)
        store.select_character(CHANNEL, placeholder, at=readings[0][3] - timedelta(seconds=1))
        store.start_session(CHANNEL, at=readings[0][3] - timedelta(seconds=1))
        Diagnostics(store).begin('synthetic-start', CHANNEL, configuration('synthetic-start'))
        return append(store, readings)


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


def main(argv=None):
    cli = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = cli.add_subparsers(dest='command', required=True)
    create_cli = commands.add_parser('create')
    create_cli.add_argument('--replace', action='store_true', help='Replace a previous SYNTHETIC demo database')
    create_cli.add_argument('--characters', type=int, choices=(1, 2, 12), default=2, help='Synthetic roster size (default: 2)')
    commands.add_parser('serve').add_argument('--port', type=int, default=8890)
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
            for receipt in create(now=datetime.now(timezone.utc), characters=args.characters):
                print(f"SYNTHETIC: automatically selected {receipt['name']} / character {receipt['character_id']}")
            print(f'SYNTHETIC demo database: {DATABASE}')
        elif args.command == 'switch':
            if not MARKER.is_file():raise ValueError('Create the synthetic demo first')
            for receipt in switch(now=datetime.now(timezone.utc)):
                print(f"SYNTHETIC: automatically selected {receipt['name']} / character {receipt['character_id']}")
        else:
            if not MARKER.is_file():raise ValueError('Create the synthetic demo first')
            if args.port == 8765 or not 0 <= args.port <= 65535:raise ValueError('Choose a free port other than the main tracker 8765')
            from exp_tracker.server import create_server
            with create_server(DATABASE, port=args.port, public_only=True, background=True) as server:
                print(f'SYNTHETIC demo (fictional streamer, no Twitch): http://127.0.0.1:{server.server_port}/stream/{CHANNEL}', flush=True)
                print(f'Homepage: http://127.0.0.1:{server.server_port}/   Overlay: http://127.0.0.1:{server.server_port}/live/overlay/{CHANNEL}', flush=True)
                try:server.serve_forever()
                except KeyboardInterrupt:pass
        return 0
    except (OSError, ValueError) as error:
        print(f'Character demo stopped: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
