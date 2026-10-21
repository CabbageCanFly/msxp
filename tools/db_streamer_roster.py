"""Explicit one-time JSON -> database roster bootstrap; no captures or service management."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys

import multi_alpha
from exp_tracker import streamer_roster as roster
from exp_tracker.store import Store


def main(argv=None):
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--db',type=Path,required=True)
    sub=cli.add_subparsers(dest='mode',required=True)
    sub.add_parser('inspect')
    p=sub.add_parser('preview');p.add_argument('--config',type=Path,required=True)
    p.add_argument('--automatic-channel',action='append',default=[]);p.add_argument('--reason',required=True)
    p.add_argument('--preview',type=Path,required=True)
    p=sub.add_parser('apply');p.add_argument('--preview',type=Path,required=True)
    p.add_argument('--confirm',required=True);p.add_argument('--backup',type=Path,required=True)
    args=cli.parse_args(argv)
    try:
        if args.mode=='inspect':
            with Store(args.db,read_only=True) as store:result=dict(channels=roster.status(store))
        elif args.mode=='preview':
            value=json.loads(args.config.read_text(encoding='utf-8-sig'))
            roots=[p.parent for p in args.config.resolve().parents if p.name in ('private','artifacts')]
            if not roots:raise ValueError('bootstrap config must be in its checkout private/ or artifacts/')
            _,_,rows=multi_alpha.validate_config(value,existing_root=roots[0])
            plan=roster.bootstrap_preview(args.db,rows,args.automatic_channel,args.reason)
            with args.preview.open('x',encoding='utf-8') as out:json.dump(plan,out,indent=2)
            result=dict(preview=plan,confirmation='bootstrap-roster:'+plan['fingerprint'][:16])
        else:
            plan=json.loads(args.preview.read_text(encoding='utf-8-sig'))
            result=roster.bootstrap_apply(args.db,plan,confirm=args.confirm,backup=args.backup)
        print(json.dumps(result,indent=2));return 0
    except (OSError,ValueError,TypeError,KeyError,sqlite3.Error) as error:
        print(f'Database roster refused: {error}',file=sys.stderr);return 1


if __name__=='__main__':raise SystemExit(main())
