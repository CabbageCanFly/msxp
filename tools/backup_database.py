"""Consistent SQLite backup, including committed WAL data; never overwrite a file."""

import argparse
from contextlib import closing
from pathlib import Path
import sqlite3
import sys


def backup(source,destination):
    source=Path(source).resolve();destination=Path(destination).resolve()
    if not source.is_file(): raise ValueError('Source database does not exist')
    if not any(destination.is_relative_to(Path.cwd().resolve()/name) for name in ('private','artifacts')):
        raise ValueError('Backups must stay in ignored private/ or artifacts/')
    with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as incoming:
        destination.parent.mkdir(parents=True,exist_ok=True)
        with destination.open('xb'): pass
        with closing(sqlite3.connect(destination)) as outgoing:
            incoming.backup(outgoing)
            if outgoing.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or outgoing.execute('PRAGMA foreign_key_check').fetchone():
                raise ValueError('Backup verification failed; retained output is not a verified recovery copy')
    return destination


def main(argv=None):
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('source',type=Path);cli.add_argument('destination',type=Path)
    args=cli.parse_args(argv)
    try:
        print(f'Verified backup: {backup(args.source,args.destination)}');return 0
    except (OSError,ValueError,sqlite3.Error) as error:
        print(f'Backup failed: {error}',file=sys.stderr);return 1


if __name__=='__main__':raise SystemExit(main())
