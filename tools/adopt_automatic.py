"""Offline, preview-first adoption of an existing multi-alpha database. Never captures video."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys

from exp_tracker import automatic_adoption as adoption
from exp_tracker.store import Store


def main(argv=None):
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--db', type=Path, required=True)
    modes = cli.add_subparsers(dest='mode', required=True)
    modes.add_parser('inspect')
    snap = modes.add_parser('snapshot')
    snap.add_argument('--output', type=Path, required=True)
    p = modes.add_parser('preview')
    p.add_argument('--mappings', type=Path, required=True, help='Private JSON array: channel, character_id, character, name')
    p.add_argument('--reason', required=True, help='Explain how the historical character identity was verified')
    p.add_argument('--preview', type=Path, required=True)
    a = modes.add_parser('apply')
    a.add_argument('--preview', type=Path, required=True)
    a.add_argument('--confirm', required=True)
    a.add_argument('--backup', type=Path, required=True)
    args = cli.parse_args(argv)
    try:
        if args.mode == 'inspect':
            owner = adoption.ownership(args.db)
            with Store(args.db, read_only=True) as store, store._transaction():
                approved = adoption.states(store)
                rows = [dict(r, automatic_adoption=approved.get(r['channel'])) for r in store.db.execute('''
                    SELECT s.login AS channel,c.id AS character_id,c.label AS character,
                        (SELECT COUNT(*) FROM sessions t WHERE t.character_id=c.id) AS sessions
                    FROM streamers s LEFT JOIN characters c ON c.id=s.selected_character_id ORDER BY s.login''')]
                for row in rows:
                    floor = store.db.execute('SELECT level FROM character_level_guard WHERE character_id=?', (row['character_id'],)).fetchone() if store.schema_version>=10 else None
                    latest = store.db.execute('''SELECT a.attempted_at,json_extract(a.payload_json,'$.status') AS status FROM diagnostic_attempts a
                        JOIN diagnostic_runs r ON r.run_id=a.run_id WHERE r.character_id=? ORDER BY a.id DESC LIMIT 1''', (row['character_id'],)).fetchone()
                    row.update(validated_level=floor[0] if floor else None, latest_attempt=dict(latest) if latest else None)
                result = dict(database=str(args.db.resolve()), schema=store.schema_version, owner=owner, channels=rows)
        elif args.mode == 'snapshot':
            result = adoption.snapshot(args.db, args.output)
        elif args.mode == 'preview':
            plan = adoption.preview(args.db, json.loads(args.mappings.read_text(encoding='utf-8-sig')), args.reason)
            with args.preview.open('x', encoding='utf-8') as output:
                json.dump(plan, output, indent=2)
            result = dict(preview=plan, confirmation=adoption.confirmation(plan),
                          warning='Stop all writers before apply. Confirm historical identity; this does not infer or merge histories.')
        else:
            plan = json.loads(args.preview.read_text(encoding='utf-8-sig'))
            result = adoption.apply(args.db, plan, confirm=args.confirm, backup=args.backup)
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error) as error:
        print(f'Adoption refused: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
