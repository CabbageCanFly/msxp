"""Plain-English health check of a running tracker database: missed readings and why, late captures, kept data.

Read-only (opens the database in SQLite read-only mode); safe while the tracker runs, locally or on the VPS.
Run it before and after a change and compare. Example:
    python tools/tracker_health.py --db private/multi-alpha/live-local.sqlite3 --minutes 60
"""
import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3


def missed(times, interval):
    """Slots missed between consecutive captures: a gap of k intervals (rounded) means k-1 missed."""
    return sum(max(0, round((b - a) / interval) - 1) for a, b in zip(times, times[1:]))


def behind(skipped):
    """Slots the scheduler skipped while behind schedule, from each lane's running counter; a restart resets it."""
    return sum(max(0, b - a) for a, b in zip(skipped, skipped[1:]))


def outcome(status, reasons):
    """What one capture got: a reading, or why not (offline, no frame from Twitch, no game HUD on screen)."""
    if status == 'capture_failed': return 'offline' if 'offline_or_unavailable' in reasons else 'no frame'
    if {'missing_hud', 'multiple_huds'} & set(reasons): return 'no HUD'
    return 'unclear' if status in ('unavailable', 'malformed_or_unavailable') else 'read'


def report(database, minutes, now=None):
    now = now or datetime.now(timezone.utc); start = now - timedelta(minutes=minutes)
    db = sqlite3.connect(f'file:{Path(database).resolve().as_posix()}?mode=ro', uri=True)
    rows = db.execute('''SELECT s.login, r.configuration_json, a.attempted_at, json_extract(a.payload_json,'$.status'),
        json_extract(a.payload_json,'$.reasons'), json_extract(a.payload_json,'$.skipped_deadlines') FROM diagnostic_attempts a
        JOIN diagnostic_runs r ON r.run_id=a.run_id JOIN streamers s ON s.id=r.streamer_id
        WHERE a.attempted_at>=? ORDER BY s.login, a.attempted_at''', (start.isoformat(),)).fetchall()
    channels = {}
    for login, config, at, status, reasons, skipped in rows:
        entry = channels.setdefault(login, dict(interval=json.loads(config).get('interval') or 20, times=[], skipped=[], got=Counter()))
        entry['times'].append(datetime.fromisoformat(at).timestamp())
        entry['skipped'].append(skipped or 0); entry['got'][outcome(status, json.loads(reasons or '[]'))] += 1
    lines = [f'Last {minutes} min, {len(channels)} streamers capturing:']
    for login, e in sorted(channels.items()):
        t, i, got = e['times'], e['interval'], e['got']
        late = max((b - a - i for a, b in zip(t, t[1:])), default=0)
        lines.append(f'  {login:<18} {len(t):4d} readings  missed {missed(t, i):3d} (behind {behind(e["skipped"]):3d})  '
                     f'worst delay {max(0, late):5.1f}s  | read {got["read"]:4d}  no HUD {got["no HUD"]:3d}  '
                     f'unclear {got["unclear"]:3d}  no frame {got["no frame"]:3d}  offline {got["offline"]:4d}  (every {i:g}s)')
    lines.append('  behind = tracker fell behind schedule (CPU/workers); rest of missed = paused while live outside '
                 'MapleStory, or a restart.\n  no HUD = frame without the game HUD (ad, covered screen, menu); '
                 'no frame = Twitch sent nothing in time.')
    total = db.execute('SELECT COUNT(*), MIN(attempted_at) FROM diagnostic_attempts').fetchone()
    oldest = (now - datetime.fromisoformat(total[1])).total_seconds() / 3600 if total[1] else 0
    lines.append(f'Kept data: {total[0]} readings, oldest {oldest:.1f} h old (about 24 h once retention has caught up), '
                 f'database {Path(database).stat().st_size / 1e6:.0f} MB')
    return '\n'.join(lines)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--minutes', type=int, default=60)
    args = parser.parse_args()
    print(report(args.db, args.minutes))
