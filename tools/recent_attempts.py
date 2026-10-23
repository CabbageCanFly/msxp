"""Last captures of one streamer: the character each was saved under, the name and levels read, and any hold.

Read-only (opens the database in SQLite read-only mode); safe while the tracker runs, locally or on the VPS. Example:
    python tools/recent_attempts.py --db private/msxp/tracker.sqlite3 --channel streamer_a --limit 35
"""
import argparse
import json
from pathlib import Path
import sqlite3


def lines(database, channel, limit=15):
    db = sqlite3.connect(f'file:{Path(database).resolve().as_posix()}?mode=ro', uri=True)
    rows = db.execute('''SELECT a.attempted_at, c.label, a.payload_json FROM diagnostic_attempts a
        JOIN diagnostic_runs r ON r.run_id=a.run_id JOIN streamers s ON s.id=r.streamer_id
        JOIN characters c ON c.id=r.character_id WHERE s.login=? ORDER BY a.id DESC LIMIT ?''', (channel, limit)).fetchall()
    db.close()
    result = []
    for at, saved, payload in rows:
        row = json.loads(payload); level = row.get('level_hold') or {}; identity = row.get('identity_hold') or {}
        # A held attempt keeps what it read one level down, under its hold.
        seen = level.get('evidence') or identity.get('evidence') or row
        name = ((seen.get('character_name') or {}).get('evidence') or {}).get('name')
        result.append(f"{at[:19]} saved as: {saved} read: {name} {row.get('status')} "
                      f"hold: {level.get('reason') or ('identity' if identity else None)} "
                      f"floor: {(row.get('level_policy') or level).get('validated_level')} "
                      f"tesseract: {seen.get('visual_level')} neural: {(seen.get('neural_level') or {}).get('level')}")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--channel', required=True, help='Twitch login')
    parser.add_argument('--limit', type=int, default=15, help='Newest captures to show (default 15)')
    args = parser.parse_args(argv)
    print('\n'.join(lines(args.db, args.channel, args.limit)) or f'No captures for {args.channel}')


if __name__ == '__main__':
    main()
