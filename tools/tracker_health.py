"""Plain-English health check of a running tracker database: missed readings, late captures, kept data.

Read-only (opens the database in SQLite read-only mode); safe while the tracker runs, locally or on the VPS.
Run it before and after a change and compare. Example:
    python tools/tracker_health.py --db private/multi-alpha/live-telfer-shiphtur.sqlite3 --minutes 60
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3


def missed(times, interval):
    """Slots missed between consecutive captures: a gap of k intervals (rounded) means k-1 missed."""
    return sum(max(0, round((b - a) / interval) - 1) for a, b in zip(times, times[1:]))


def report(database, minutes, now=None):
    now = now or datetime.now(timezone.utc); start = now - timedelta(minutes=minutes)
    db = sqlite3.connect(f'file:{Path(database).resolve().as_posix()}?mode=ro', uri=True)
    rows = db.execute('''SELECT s.login, r.configuration_json, a.attempted_at FROM diagnostic_attempts a
        JOIN diagnostic_runs r ON r.run_id=a.run_id JOIN streamers s ON s.id=r.streamer_id
        WHERE a.attempted_at>=? ORDER BY s.login, a.attempted_at''', (start.isoformat(),)).fetchall()
    channels = {}
    for login, config, at in rows:
        entry = channels.setdefault(login, dict(interval=json.loads(config).get('interval') or 20, times=[]))
        entry['times'].append(datetime.fromisoformat(at).timestamp())
    lines = [f'Last {minutes} min, {len(channels)} streamers capturing:']
    for login, e in sorted(channels.items()):
        t, i = e['times'], e['interval']
        late = max((b - a - i for a, b in zip(t, t[1:])), default=0)
        lines.append(f'  {login:<18} {len(t):4d} readings  missed {missed(t, i):3d}  worst delay {max(0, late):5.1f}s  (every {i:g}s)')
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
