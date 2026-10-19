"""Local-only manual corrections: python -m exp_tracker.manual_admin --help."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import sqlite3
import uuid

from .store import Store, utc


def percentage(value):
    if not re.fullmatch(r'[0-9]{1,2}(?:\.[0-9]{1,2})?',value):
        raise argparse.ArgumentTypeError('percentage must be 0.00..99.99 with at most two decimal places')
    whole,_,fraction=value.partition('.')
    return int(whole)*100+int(fraction.ljust(2,'0'))


def timestamp(value):
    try:
        stamp=datetime.fromisoformat(value)
        utc(stamp)
        return stamp
    except (ValueError,TypeError):
        raise argparse.ArgumentTypeError('effective-at must be an ISO timestamp with a timezone') from None


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',required=True,type=Path)
    parser.add_argument('--channel',required=True)
    commands=parser.add_subparsers(dest='command',required=True)
    commands.add_parser('inspect',help='Show selection and current public display')
    commands.add_parser('history',help='Show the append-only correction log for this channel')
    for name in ('set','clear'):
        command=commands.add_parser(name)
        command.add_argument('--character',required=True,help='Exact selected character label')
        command.add_argument('--event-id',default=None,help='Stable retry ID; otherwise a UUID is generated')
        command.add_argument('--effective-at',type=timestamp)
        command.add_argument('--reason')
        if name=='set':
            command.add_argument('--level',type=int)
            command.add_argument('--exp',type=int)
            command.add_argument('--percentage',type=percentage)
    args=parser.parse_args(argv)
    try:
        if not args.db.is_file():raise ValueError('database must already exist; initialize the explicit selection first')
        if args.command=='set':
            if all(v is None for v in (args.level,args.exp,args.percentage)):
                raise ValueError('supply --level, --exp and/or --percentage')
            if args.level is not None and not 1<=args.level<=200 or args.exp is not None and not 0<=args.exp<2**63:
                raise ValueError('level must be 1..200; EXP must be a nonnegative SQLite integer')
        with Store(args.db,read_only=args.command in ('inspect','history')) as store:
            state=store.state(args.channel)
            if args.command=='history':result=store.manual_history(args.channel)
            elif args.command=='inspect':
                from .diagnostics import Diagnostics
                from .product import player
                value=player(Diagnostics(store).snapshot(args.channel))
                result=dict(channel=state['channel'],characters=state['characters'],selected_character_id=state['selected_character_id'],
                    session=state['session'],reading=value['reading'],display_level=value['display_level'],
                    manual_correction=value.get('manual_correction'),schema_version=store.schema_version)
            else:
                character=next((c for c in state['characters'] if c['label']==args.character),None)
                if not character:raise ValueError('unknown character label')
                result=store.correct_manual(args.channel,args.event_id or uuid.uuid4().hex,character['id'],
                    level=getattr(args,'level',None),current_exp=getattr(args,'exp',None),
                    percentage_bp=getattr(args,'percentage',None),effective_at=args.effective_at,reason=args.reason,
                    clear=args.command=='clear')
        print(json.dumps(result,indent=2,allow_nan=False))
        return 0
    except (ValueError,sqlite3.Error,OSError) as error:
        parser.exit(2,f'error: {error}\n')


if __name__=='__main__':
    raise SystemExit(main())
