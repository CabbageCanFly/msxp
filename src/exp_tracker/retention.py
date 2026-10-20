"""Transactional 24-hour evidence retention. CLI defaults to read-only reporting."""
from collections import deque
from datetime import datetime, timedelta, timezone
from fractions import Fraction
import argparse
import json
from pathlib import Path
import sqlite3

from .store import Store, utc


def pack(value):
    if isinstance(value, datetime):return {'$datetime':value.isoformat()}
    if isinstance(value, Fraction):return {'$fraction':[value.numerator,value.denominator]}
    if isinstance(value, deque):return {'$deque':[pack(list(value)),value.maxlen]}
    if isinstance(value, set):return {'$set':[pack(v) for v in sorted(value,key=str)]}
    if isinstance(value, tuple):return {'$tuple':[pack(v) for v in value]}
    if isinstance(value, dict):return {k:pack(v) for k,v in value.items()}
    if isinstance(value, list):return [pack(v) for v in value]
    return value


def unpack(value):
    if isinstance(value,list):return [unpack(v) for v in value]
    if not isinstance(value,dict):return value
    if '$datetime' in value:return datetime.fromisoformat(value['$datetime'])
    if '$fraction' in value:return Fraction(*value['$fraction'])
    if '$deque' in value:return deque(unpack(value['$deque'][0]),maxlen=value['$deque'][1])
    if '$set' in value:return set(unpack(value['$set']))
    if '$tuple' in value:return tuple(unpack(value['$tuple']))
    result={k:unpack(v) for k,v in value.items()}
    # Also compact copies in old endpoints/display/provenance, including inactive characters.
    if {'wrap_event_id','from_level','phase','samples'}<=result.keys():
        from .diagnostic_evidence import compact_transition
        return compact_transition(result)
    return result


def dumps(value):return json.dumps(pack(value),separators=(',',':'),allow_nan=False)
def loads(value):return unpack(json.loads(value))


def checkpoint(store, character):
    if store.schema_version<8 or character is None:return {}
    row=store.db.execute('SELECT checkpoint_json FROM retention_state WHERE character_id=?',(character,)).fetchone()
    return loads(row[0]) if row else {}


def expired(store, character, when):
    if store.schema_version<8:return False
    row=store.db.execute('SELECT cutoff FROM retention_state WHERE character_id=?',(character,)).fetchone()
    return bool(row and datetime.fromisoformat(when)<=datetime.fromisoformat(row[0]))


def guard(store, character, when):
    if expired(store,character,when):
        raise ValueError('reading history has expired under 24-hour retention; use a new current baseline')


def next_id(store, table, column):
    """Audit source identities must never be recycled after the highest row expires."""
    return store.db.execute(f'SELECT MAX(COALESCE((SELECT MAX(rowid) FROM {table}),0),{column})+1 FROM retention_meta WHERE id=1').fetchone()[0]


def plan(store, now, active_runs=None):
    cutoff=now-timedelta(hours=24,minutes=5)
    groups={}
    for row in store.db.execute('''SELECT r.rowid,r.*,MAX(a.attempted_at) AS attempted,
            MAX(COALESCE(a.received_at,a.attempted_at)) AS received,COUNT(a.id) AS attempts
            FROM diagnostic_runs r LEFT JOIN diagnostic_attempts a ON a.run_id=r.run_id
            GROUP BY r.rowid ORDER BY r.rowid'''):
        groups.setdefault(row['character_id'],[]).append(dict(row))
    prefixes={};remaining=200
    for cid,runs in groups.items():
        if not remaining:break
        floor=checkpoint(store,cid).get('through_run',0);chosen=[]
        for run in runs:
            if run['rowid']<=floor:continue
            stamp=max(run['attempted'] or run['created_at'],run['received'] or run['created_at'])
            protected=run['run_id'] in active_runs if active_runs is not None else run['summary_json'] is None
            if protected or run['attempts'] and datetime.fromisoformat(stamp)>=cutoff:break
            chosen.append(run)
            remaining-=1
            if not remaining:break
        if chosen:prefixes[cid]=chosen
    return prefixes


def prune(store, *, now=None, dry_run=True, active_runs=None):
    """Only the owning coordinator supplies active_runs, after acquiring its writer lease."""
    from .diagnostics import Diagnostics
    from .product import player,reading,responsive_pace
    from .rolling_history import usable_endpoint
    now=datetime.fromisoformat(utc(now))
    with store._transaction():
        prefixes=plan(store,now,active_runs)
        cutoff=now-timedelta(hours=24,minutes=5)
        report=dict(dry_run=dry_run,cutoff=utc(cutoff),runs=sum(map(len,prefixes.values())),
            attempts=sum(r['attempts'] for runs in prefixes.values() for r in runs),
            observation_candidates=store.db.execute('SELECT COUNT(*) FROM observations WHERE observed_at<?',(utc(cutoff),)).fetchone()[0])
        report['batch_limit_reached']=report['runs']==200
        if dry_run:return report
        if store.schema_version<9:raise ValueError('writer migration to schema 9 required')
        store.db.execute('''UPDATE retention_meta SET revision=revision+1,
            attempt_id=MAX(attempt_id,COALESCE((SELECT MAX(id) FROM diagnostic_attempts),0)),
            observation_id=MAX(observation_id,COALESCE((SELECT MAX(id) FROM observations),0)),
            run_id=MAX(run_id,COALESCE((SELECT MAX(rowid) FROM diagnostic_runs),0)) WHERE id=1''')
        for cid,runs in prefixes.items():
            character=store.db.execute('SELECT c.*,s.login,s.selected_character_id FROM characters c JOIN streamers s ON s.id=c.streamer_id WHERE c.id=?',(cid,)).fetchone()
            # Private transaction: other connections always see the original selection.
            store.db.execute('UPDATE streamers SET selected_character_id=? WHERE id=?',(cid,character['streamer_id']))
            try:
                diagnostic=Diagnostics(store);diagnostic._retention_prefix={r['run_id'] for r in runs};diagnostic._retention_states={}
                diagnostic.rolling_history(character['login'],now=now)
                from .rolling_history import recent_snapshot
                recent=recent_snapshot(diagnostic,character['login'],now=now,_historical=True)
                states=diagnostic._retention_states
                if set(states)!={'tracked','recent'} or recent.get('recent_history_status')!='ready':
                    raise ValueError('cannot checkpoint incomplete retention replay')
                previous=checkpoint(store,cid)
                prefix_pace=responsive_pace(recent,None,now=now)
                from .diagnostic_progress import progress
                from .diagnostic_evidence import Projected
                recent['observations']=Projected(diagnostic._retention_display_rows if hasattr(diagnostic,'_retention_display_rows') else [])
                recent['percentage_progress']=progress(recent['observations'],now=now)
                shown=player(recent,now=now)
                display={k:shown[k] for k in ('reading','display_level','level_context','latest_attempt_at','latest_attempt_status','responsive_pace')}
                display['responsive_pace']=prefix_pace
                full=next((reading(r) for r in reversed(recent['observations']) if reading(r) and reading(r)['exp'] is not None),None)
                display['full_exp']=dict(exp=full['exp'],percentage=full['percentage'],evidence=full['evidence'],event_id=full['event_id'],
                    timestamp=full['timestamp']) if full else previous.get('display',{}).get('full_exp')
                for key in ('reading','display_level','responsive_pace'):
                    if display[key] is None:display[key]=previous.get('display',{}).get(key)
                if display['responsive_pace']:
                    display['responsive_pace']={k:v for k,v in display['responsive_pace'].items()
                        if k not in ('intervals','conditional_recoveries','excluded','latest_endpoint')}
                etas=recent['historical_etas']
                etas={str(m):etas.get(str(m)) for m in (5,10,15,30,60)}
                etas={m:v or previous.get('etas',{}).get(m) for m,v in etas.items()}
                tracked=states['tracked']
                tracked['rows']=[p for p in tracked['rows'] if usable_endpoint(p)][-1:]
                states['recent']['rows']=[];states['recent']['decisions']=[]
                # Event IDs are immutable and prefix runs cannot be appended/replayed.
                for value in (tracked,states['recent']):
                    value['percentage_state'].get('seen',set()).clear()
                diagnostic_state=tracked['interval_state'].get('diagnostic',{})
                diagnostic_state.get('seen_events',set()).clear()
                # These IDs describe intervals wholly before every future rolling window.
                tracked['interval_state']['holes']=[]
                if diagnostic_state:diagnostic_state['holes']=[]
                paces=dict(previous.get('paces',{}),**states['recent'].get('retained_paces',{}))
                value=dict(states,through_run=runs[-1]['rowid'],display=display,etas=etas,paces=paces)
                store.db.execute('INSERT OR REPLACE INTO retention_state VALUES(?,?,?)',(cid,utc(cutoff),dumps(value)))
                for run in runs:
                    store.db.execute('DELETE FROM diagnostic_attempts WHERE run_id=?',(run['run_id'],))
                # Keep one predecessor for rotation validation, plus the latest run per session.
                store.db.execute('''DELETE FROM diagnostic_runs WHERE character_id=? AND rowid<?
                    AND rowid NOT IN (SELECT MAX(rowid) FROM diagnostic_runs GROUP BY session_id)''',(cid,runs[-1]['rowid']))
            finally:
                store.db.execute('UPDATE streamers SET selected_character_id=? WHERE id=?',(character['selected_character_id'],character['streamer_id']))
        _trusted(store,cutoff)
        if store.db.execute('PRAGMA foreign_key_check').fetchone():raise ValueError('retention foreign key check failed')
    return report


def _trusted(store,cutoff):
    from .trusted_replay import replay
    for session,through in store.db.execute('SELECT session_id,MAX(id) FROM observations WHERE session_id IS NOT NULL AND observed_at<? GROUP BY session_id',(utc(cutoff),)).fetchall():
        # Only a chronological prefix can be folded into an anchor.
        earlier=store.db.execute('SELECT MIN(id) FROM observations WHERE session_id=? AND observed_at>=?',(session,utc(cutoff))).fetchone()[0]
        if earlier is not None:through=min(through,earlier-1)
        old=store.db.execute('SELECT * FROM trusted_checkpoints WHERE session_id=?',(session,)).fetchone()
        if old and through<=old['through_id']:continue
        value=replay(store,session,_force=True,_until_id=through)
        if value['unavailable']:raise ValueError('cannot checkpoint incomplete trusted replay')
        from .daily_snapshots import trusted as archive_daily
        archive_daily(store,session,through,old['through_id'] if old else 0,value['rows'])
        keep={r[0] for r in store.db.execute('SELECT last_trusted_observation_id FROM tracking_state WHERE last_trusted_observation_id IS NOT NULL')}
        keep.update(r[0] for r in store.db.execute('SELECT interval_start_observation_id FROM observations WHERE id>? AND interval_start_observation_id IS NOT NULL',(through,)))
        if value['last']:keep.add(value['last']['id'])
        candidates=[r[0] for r in store.db.execute('SELECT id FROM observations WHERE session_id=? AND id<=?',(session,through)) if r[0] not in keep]
        gain=old['original_gain'] if old else 0;bridged=old['original_bridged'] if old else 0
        for identity in candidates:
            row=store.db.execute('SELECT gained_exp,missing_observations FROM observations WHERE id=?',(identity,)).fetchone()
            gain+=row['gained_exp'] or 0
            if row['missing_observations']:bridged+=row['gained_exp'] or 0
        bridged+=store.db.execute('SELECT COALESCE(SUM(gained_exp),0) FROM observations WHERE session_id=? AND id<=? AND missing_observations>0'+
            (' AND id NOT IN ('+','.join('?'*len(candidates))+')' if candidates else ''),(session,through,*candidates)).fetchone()[0]
        # Expired anchors retain scalar evidence, not an entire foreign-key-linked chain.
        store.db.execute('UPDATE observations SET interval_start_observation_id=NULL,missing_observations=0 WHERE session_id=? AND id<=?',(session,through))
        for identity in candidates:store.db.execute('DELETE FROM observations WHERE id=?',(identity,))
        value['rows']=[]
        store.db.execute('INSERT OR REPLACE INTO trusted_checkpoints VALUES(?,?,?,?,?)',(session,through,dumps(value),gain,bridged))
        cid=store.db.execute('SELECT character_id FROM sessions WHERE id=?',(session,)).fetchone()[0]
        frozen=checkpoint(store,cid)
        store.db.execute('INSERT OR REPLACE INTO retention_state VALUES(?,?,?)',(cid,utc(cutoff),dumps(frozen)))
    store.db.execute('DELETE FROM observations WHERE session_id IS NULL AND observed_at<?',(utc(cutoff),))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',type=Path,required=True)
    parser.add_argument('--apply',action='store_true',help='Prune this explicitly selected database; default reports only')
    args=parser.parse_args(argv)
    if not args.db.is_file():parser.error('database must already exist')
    try:
        with Store(args.db,read_only=not args.apply) as store:
            print(json.dumps(prune(store,dry_run=not args.apply),indent=2))
        return 0
    except (ValueError,OSError,sqlite3.Error) as error:
        parser.exit(1,f'Retention failed: {error}\n')


if __name__=='__main__':raise SystemExit(main())
