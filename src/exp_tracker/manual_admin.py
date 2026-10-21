"""Local-only manual corrections: python -m exp_tracker.manual_admin --help."""
import argparse
from contextlib import contextmanager,closing
from datetime import datetime
import json
from pathlib import Path
import re
import sqlite3
import tempfile
import uuid

from .store import Store, utc


def percentage(value):
    if not re.fullmatch(r'[0-9]{1,2}(?:\.[0-9]{1,2})?',value):
        raise argparse.ArgumentTypeError('percentage must be 0.00..99.99 with at most two decimal places')
    whole,_,fraction=value.partition('.')
    return int(whole)*100+int(fraction.ljust(2,'0'))


def timestamp(value):
    try:
        if not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}[T ][0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})',value):
            raise ValueError
        if int(value[11:13])>23 or int(value[14:16])>59 or int(value[17:19])>59:raise ValueError
        if not value.endswith('Z') and (int(value[-5:-3])>23 or int(value[-2:])>59):raise ValueError
        stamp=datetime.fromisoformat(value)
        utc(stamp)
        return stamp
    except (ValueError,TypeError):
        raise argparse.ArgumentTypeError('effective-at must include YYYY-MM-DD, HH:MM:SS and timezone (Z or +/-HH:MM)') from None


@contextmanager
def writable_store(path, preview):
    if not preview:
        with Store(path) as store:yield store
        return
    # Validate the real operation on a private snapshot; even schema migration stays off the source.
    with Store(path,read_only=True) as source, tempfile.TemporaryDirectory(prefix='exp-admin-preview-') as directory:
        copied=Path(directory)/'preview.sqlite3'
        with closing(sqlite3.connect(copied)) as target:source.db.backup(target)
        with Store(copied) as store:yield store


def inspect(store, channel, character=None, session_id=None):
    from .diagnostics import Diagnostics
    from .product import player,reading
    from .manual import active,corrected_reading
    state=store.state(channel);d=Diagnostics(store)
    cid=character['id'] if character else state['selected_character_id']
    sessions=[dict(r) for r in store.db.execute('SELECT * FROM sessions WHERE streamer_id=? ORDER BY id DESC',
                                               (store._channel(channel)['id'],))]
    choices=[s for s in sessions if s['character_id']==cid]
    if session_id is not None and not any(s['id']==session_id for s in choices):raise ValueError('session does not belong to character/channel')
    if session_id is None and cid!=state['selected_character_id']:
        session_id=choices[0]['id'] if len(choices)==1 else None
    snap=d.snapshot(channel,session_id=session_id) if cid==state['selected_character_id'] or session_id is not None else None
    value=player(snap) if snap else {}
    records=[dict(identity=r['event_id'],kind='diagnostic',session_id=r['session_id'],
        timestamp=r.get('received_at') or r['attempted_at'],original_level=r['visual_level'],
        original_candidate=r['candidate'],presentation=reading(r)) for r in snap['observations']] if snap else []
    points=active(store.manual_history(channel,character_id=cid))
    for row in store.db.execute('SELECT * FROM observations WHERE character_id=?'+(' AND session_id=?' if session_id else '')+
                               ' ORDER BY id DESC LIMIT 60',(cid,session_id) if session_id else (cid,)):
        event=next((e for e in points if e['kind']=='point' and e['target_kind']=='observation' and e['target_event_id']==str(row['id'])),None)
        records.append(dict(identity=row['id'],kind='observation',session_id=row['session_id'],timestamp=row['observed_at'],
            original=dict(level=row['level'],current_exp=row['current_exp'],percentage_bp=row['percentage_bp'],
                          outcome=row['outcome'],reason=row['reason']),
            presentation=corrected_reading(event,event_id='observation:'+str(row['id'])) if event else None))
    return dict(channel=state['channel'],characters=state['characters'],selected_character_id=state['selected_character_id'],
        session=snap['session'] if snap else None,sessions=choices,reading=value.get('reading'),display_level=value.get('display_level'),
        manual_correction=value.get('manual_correction'),readings=records,schema_version=store.schema_version)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',required=True,type=Path)
    parser.add_argument('--channel',required=True)
    commands=parser.add_subparsers(dest='command',required=True)
    for name in ('inspect','history'):
        command=commands.add_parser(name)
        command.add_argument('--character',help='Exact existing character name; defaults to the selected character for inspect')
        command.add_argument('--session',type=int)
        if name=='history':command.add_argument('--correction-id',type=int)
    for name in ('set','correct','amend','clear'):
        command=commands.add_parser(name)
        command.add_argument('--character',required=True,help='Exact existing character name belonging to this channel')
        scope=command.add_mutually_exclusive_group()
        scope.add_argument('--session',type=int,help='Existing session; otherwise resolved uniquely from character and effective time')
        scope.add_argument('--no-session',action='store_true',help='Explicit unbound baseline, including between capture sessions')
        command.add_argument('--event-id',default=None,help='Stable retry ID; otherwise a UUID is generated')
        when=command.add_mutually_exclusive_group(required=True)
        when.add_argument('--effective-at',type=timestamp)
        when.add_argument('--now',action='store_true',help='Deliberately use the current UTC timestamp')
        command.add_argument('--reason',required=name=='amend')
        command.add_argument('--dry-run',action='store_true',help='Validate against a disposable SQLite snapshot')
        if name!='clear':
            command.add_argument('--level',type=int,required=True)
            command.add_argument('--exp',type=int)
            command.add_argument('--percentage',type=percentage)
        if name in ('correct','amend'):
            target=command.add_mutually_exclusive_group()
            target.add_argument('--reading',help='Diagnostic event identity RUN_ID:ATTEMPT_INDEX')
            target.add_argument('--observation-id',type=int,help='Trusted SQLite observation ID; original OCR stays intact')
        if name=='amend':
            command.add_argument('--correction-id',type=int,required=True)
            command.add_argument('--kind',choices=('baseline','point'),help='Defaults to the previous revision kind')
    undo=commands.add_parser('undo',help='Retract an active correction revision and its lineage')
    undo.add_argument('--correction-id',type=int,required=True);undo.add_argument('--reason',required=True)
    undo.add_argument('--event-id');undo.add_argument('--dry-run',action='store_true')
    rename=commands.add_parser('rename',help='Rename in place; coordinate the roster label before the next startup')
    rename.add_argument('--character-id',type=int,required=True);rename.add_argument('--new-name',required=True)
    rename.add_argument('--reason');rename.add_argument('--dry-run',action='store_true')
    from . import floor_repair
    floor_repair.arguments(commands.add_parser('repair-floor', help='Exceptional offline floor repair: preview, then explicitly apply'))
    args=parser.parse_args(argv)
    try:
        if not args.db.is_file():raise ValueError('database must already exist; initialize the explicit selection first')
        if args.command=='repair-floor':
            print(json.dumps(floor_repair.run(args),indent=2,allow_nan=False))
            return 0
        if args.command in ('set','correct','amend'):
            if args.exp is None and args.percentage is None:raise ValueError('supply --exp and/or --percentage as well as --level')
            if args.level is not None and not 1<=args.level<=200 or args.exp is not None and not 0<=args.exp<2**63:
                raise ValueError('level must be 1..200; EXP must be a nonnegative SQLite integer')
        read_only=args.command in ('inspect','history')
        context=Store(args.db,read_only=True) if read_only else writable_store(args.db,args.dry_run)
        with context as store:
            state=store.state(args.channel)
            character=next((c for c in state['characters'] if c['label']==args.character),None) if getattr(args,'character',None) else None
            if getattr(args,'character',None) and character is None:raise ValueError('unknown character name for this channel')
            if args.command=='history':
                events=store.manual_history(args.channel,character_id=character['id'] if character else None)
                if args.session is not None:events=[e for e in events if e['session_id']==args.session]
                if args.correction_id is not None:
                    events=[e for e in events if e['id']==args.correction_id or e['replaces_id']==args.correction_id]
                    if not events:raise ValueError('unknown correction in channel/character/session scope')
                renames=[dict(r) for r in store.db.execute('SELECT * FROM character_renames WHERE streamer_id=? ORDER BY id',
                    (store._channel(args.channel)['id'],))] if store.schema_version>=6 else []
                result=dict(corrections=events,renames=renames)
            elif args.command=='inspect':result=inspect(store,args.channel,character,args.session)
            elif args.command=='rename':
                result=store.rename_character(args.channel,args.character_id,args.new_name,reason=args.reason)
                result['roster_action']='Update the matching roster character label before the next coordinator startup; no running coordinator was changed.'
            elif args.command=='undo':
                result=store.retract_manual(args.channel,args.event_id or uuid.uuid4().hex,args.correction_id,reason=args.reason)
            else:
                kind='point' if args.command=='correct' else 'baseline'
                if args.command=='amend':
                    previous=next((e for e in store.manual_history(args.channel) if e['id']==args.correction_id),None)
                    if previous is None:raise ValueError('correction does not belong to channel')
                    kind=args.kind or previous['kind']
                target_kind='diagnostic' if getattr(args,'reading',None) is not None else 'observation' if getattr(args,'observation_id',None) is not None else None
                target_id=getattr(args,'reading',None) or getattr(args,'observation_id',None)
                result=store.correct_manual(args.channel,args.event_id or uuid.uuid4().hex,character['id'],
                    level=getattr(args,'level',None),current_exp=getattr(args,'exp',None),
                    percentage_bp=getattr(args,'percentage',None),effective_at=args.effective_at,now=args.now,reason=args.reason,
                    clear=args.command=='clear',session_id=args.session,no_session=args.no_session,kind=kind,target_kind=target_kind,target_event_id=target_id,
                    replaces_id=getattr(args,'correction_id',None))
            if not read_only:result['preview']=args.dry_run
        print(json.dumps(result,indent=2,allow_nan=False))
        return 0
    except (ValueError,sqlite3.Error,OSError) as error:
        parser.exit(2,f'error: {error}\n')


if __name__=='__main__':
    raise SystemExit(main())
