"""Private, explicitly SIMULATED history for SQLite query/size checks, never OCR."""

import argparse
from contextlib import closing
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import statistics
import time
import uuid

from shadow_capture import private_path
from exp_tracker.store import Store,utc
from exp_tracker.diagnostics import Diagnostics
from exp_tracker.metrics import ResourceMonitor


def main(argv=None):
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--directory',type=Path,required=True)
    cli.add_argument('--channels',type=int,default=25)
    cli.add_argument('--attempts-per-channel',type=int,default=2400)
    args=cli.parse_args(argv)
    if not 2<=args.channels<=25 or not 1<=args.attempts_per_channel<=100000:
        cli.error('Use 2..25 channels and 1..100000 attempts per channel')
    folder=private_path(args.directory);folder.mkdir(parents=True,exist_ok=False)
    db=folder/'synthetic.sqlite3';start=datetime(2000,1,1,tzinfo=timezone.utc)
    started=time.perf_counter()
    with closing(ResourceMonitor(sample_interval=.05,scope='SIMULATED SQLite history generation and read projection')) as monitor,Store(db) as store:
        bindings=[]
        for i in range(args.channels):
            channel=f'simulated_{i:02d}';sid=store.add_channel(channel)
            cid=store.add_character(channel,f'SIMULATED character {i}');store.select_character(channel,cid)
            session=store.start_session(channel,at=start)
            bindings.append((sid,cid,session))
        has_session='session_id' in [r[1] for r in store.db.execute('PRAGMA table_info(diagnostic_attempts)')]
        with store._transaction():
            for base in range(0,args.attempts_per_channel,60):
                runs=[];n=min(60,args.attempts_per_channel-base)
                for sid,cid,session in bindings:
                    run=uuid.uuid4().hex;runs.append(run)
                    config=dict(type='configuration',trusted=False,interval=15,count=n,timing_mode='simulated',source_kind='file')
                    store.db.execute('INSERT INTO diagnostic_runs VALUES(?,?,?,?,?,?,?)',
                        (run,sid,cid,session,utc(start+timedelta(seconds=base*15)),json.dumps(config),json.dumps(dict(type='summary',trusted=False,attempts=n,interrupted=False))))
                for index in range(1,n+1):
                    when=utc(start+timedelta(seconds=(base+index)*15))
                    payload=json.dumps(dict(type='attempt',trusted=False,index=index,timing_mode='simulated',attempted_at=when,received_at=when,
                        current=True,status='diagnostic_percentage_only',source=dict(kind='file'),neural=dict(text='[33.05%]'),visual_level=64,visual_status='available',localization=dict(count=1)))
                    for run,(_,_,session) in zip(runs,bindings):
                        values=(run,index,when,when,when,payload)
                        columns='run_id,attempt_index,attempted_at,received_at,recorded_at,payload_json'
                        if has_session: columns+=',session_id';values+= (session,)
                        store.db.execute(f'INSERT INTO diagnostic_attempts({columns}) VALUES({",".join("?" for _ in values)})',values)
        build=time.perf_counter()-started
        session=bindings[0][2]
        timings=[]
        for _ in range(20):
            tick=time.perf_counter()
            rows=list(store.db.execute('''SELECT a.* FROM diagnostic_attempts a JOIN diagnostic_runs r ON r.run_id=a.run_id
                WHERE r.session_id=? ORDER BY a.id DESC LIMIT 121''',(session,)))
            timings.append((time.perf_counter()-tick)*1000)
        report=dict(simulated=True,channels=args.channels,attempts=args.channels*args.attempts_per_channel,
            schema=store.db.execute('PRAGMA user_version').fetchone()[0],build_seconds=build,
            legacy_recent_query_ms=dict(median=statistics.median(timings),p95=sorted(timings)[18]),
            legacy_plan=[tuple(r) for r in store.db.execute('EXPLAIN QUERY PLAN SELECT a.* FROM diagnostic_attempts a JOIN diagnostic_runs r ON r.run_id=a.run_id WHERE r.session_id=? ORDER BY a.id DESC LIMIT 121',(session,))])
        if has_session:
            report['indexed_plan']=[tuple(r) for r in store.db.execute('EXPLAIN QUERY PLAN SELECT * FROM diagnostic_attempts WHERE session_id=? ORDER BY id DESC LIMIT 121',(session,))]
            for label,query,params in [
                ('recent','SELECT * FROM diagnostic_attempts WHERE session_id=? ORDER BY id DESC LIMIT 121',(session,)),
                ('time_window','SELECT * FROM diagnostic_attempts WHERE session_id=? AND attempted_at>=? AND attempted_at<? ORDER BY id DESC LIMIT 121',
                    (session,utc(start+timedelta(seconds=300)),utc(start+timedelta(seconds=600))))]:
                measurements=[]
                for _ in range(20):
                    tick=time.perf_counter();list(store.db.execute(query,params));measurements.append((time.perf_counter()-tick)*1000)
                report[label+'_ms']=dict(median=statistics.median(measurements),p95=sorted(measurements)[18])
            diagnostic=Diagnostics(store);measurements=[]
            for _ in range(10):
                tick=time.perf_counter();snap=diagnostic.snapshot('simulated_00');measurements.append((time.perf_counter()-tick)*1000)
            assert not snap['percentage_progress']['current_pace']
            report['snapshot_ms']=dict(median=statistics.median(measurements),p95=max(measurements))
            report['snapshot_rows']=len(snap['observations'])
            cache={};tick=time.perf_counter();diagnostic.directory(cache)
            report['directory_cold_ms']=(time.perf_counter()-tick)*1000
            measurements=[]
            for _ in range(20):
                tick=time.perf_counter();diagnostic.directory(cache);measurements.append((time.perf_counter()-tick)*1000)
            report['directory_cached_ms']=dict(median=statistics.median(measurements),p95=sorted(measurements)[18])
        store.db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        report['resources']=monitor.snapshot()
    report['database_bytes']=db.stat().st_size
    (folder/'measurements.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
