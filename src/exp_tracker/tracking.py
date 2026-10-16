"""Local tracking administration: python -m exp_tracker.tracking --db PATH COMMAND."""

import argparse
import json
from pathlib import Path
import sqlite3
import sys

from .store import Store


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--channel", required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init")
    character = commands.add_parser("character")
    character.add_argument("label")
    select = commands.add_parser("select")
    select.add_argument("character_id", type=int)
    for name in ("start", "end", "state"):
        commands.add_parser(name)
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            args.db.parent.mkdir(parents=True, exist_ok=True)
        elif not args.db.exists():
            raise ValueError("initialize the database first")
        with Store(args.db) as store:
            if args.command == "init":
                output = {"channel_id": store.add_channel(args.channel)}
            elif args.command == "character":
                output = {"character_id": store.add_character(args.channel, args.label)}
            else:
                if args.command == "select":
                    store.select_character(args.channel, args.character_id)
                elif args.command == "start":
                    store.start_session(args.channel)
                elif args.command == "end":
                    store.end_session(args.channel)
                output = store.state(args.channel)
            print(json.dumps(output, indent=2))
        return 0
    except (OSError, sqlite3.Error, ValueError) as error:
        print(json.dumps({"status": "error", "reason": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
