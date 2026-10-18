"""Private browser-test server: immutable saved replay + explicitly synthetic window control.

No OCR, network capture, HTTP writes or source retiming. stdin accepts only 'advance'.
"""
import argparse
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import sys
import threading

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from exp_tracker.store import Store
from exp_tracker.diagnostics import Diagnostics
from exp_tracker.server import create_server


def window_trial(database,port):
    """Actual rotation logs, causal prefix clock; never retimes or recaptures sources."""
    root=Path('private/multi-alpha/runs/20261018T005419Z-6d0af805')
    logs={}
    for channel in ('telfer1','shiphtur'):
        paths=list((root/channel).rglob('capture.jsonl'))
        logs[channel]=sorted(([json.loads(s) for s in p.read_text().splitlines()] for p in paths),
            key=lambda records:next(r['attempted_at'] for r in records if r['type']=='attempt'))[:2]
    import exp_tracker.server as server_module
    import exp_tracker.diagnostics as diagnostic_module
    class ReviewClock(datetime):
        at=None
        @classmethod
        def now(cls,tz=None):return cls.at
    server_module.datetime=diagnostic_module.datetime=ReviewClock
    with Store(database) as store:
        d=Diagnostics(store)
        def stage(stop):
            stamps=[]
            for channel,runs in logs.items():
                if stop==42:
                    store.add_channel(channel);cid=store.add_character(channel,'Saved review')
                    store.select_character(channel,cid);store.start_session(channel)
                    d.begin(runs[0][0]['run_id'],channel,runs[0][0])
                for number,records in enumerate(runs):
                    if number and stop<=60:continue
                    if number and stop==61:d.begin(records[0]['run_id'],channel,records[0])
                    for r in records[1:]:
                        ordinal=number*60+r.get('index',60)
                        lower=0 if stop==42 else 42 if stop==61 else 61
                        if r['type']=='attempt' and lower<ordinal<=stop:d.append(records[0]['run_id'],r)
                        if r['type']=='summary' and number==0 and stop==61:d.append(records[0]['run_id'],r)
                        if r['type']=='attempt' and ordinal<=stop and r.get('received_at'):stamps.append(datetime.fromisoformat(r['received_at']))
            ReviewClock.at=max(stamps)
            assert not store.db.execute('select 1 from observations').fetchone()
        stage(42)
        with create_server(database,port=port,diagnostic_dashboard=True) as http:
            http.quiet=True;thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
            print(json.dumps(dict(ready=True,port=http.server_port)),flush=True)
            try:
                for expected,stop in (('advance',61),('finish',70)):
                    command=next(sys.stdin,None)
                    if command is None:break
                    if command.strip()!=expected:raise ValueError('Ordered replay only')
                    stage(stop);print(json.dumps(dict(stage=expected,as_of=ReviewClock.at.isoformat())),flush=True)
                for command in sys.stdin:
                    if command.strip()!='stale':raise ValueError('Replay complete')
                    ReviewClock.at+=timedelta(seconds=90)
                    print(json.dumps(dict(stage='stale',as_of=ReviewClock.at.isoformat())),flush=True)
            finally:http.shutdown();thread.join(2)


def rolling_trial(database,port):
    """Actual existing character/session payloads, two causal replay stages."""
    with Store('private/local-alpha/live/telfer1.sqlite3',read_only=True) as source:
        streamer=source._channel('telfer1')
        character=source.db.execute('select * from characters where id=?',(streamer['selected_character_id'],)).fetchone()
        runs=[dict(r) for r in source.db.execute('select * from diagnostic_runs where character_id=? order by rowid',(character['id'],))]
        assert len({r['session_id'] for r in runs})==1
        records={r['run_id']:[json.loads(a[0]) for a in source.db.execute('select payload_json from diagnostic_attempts where run_id=? order by attempt_index',(r['run_id'],))] for r in runs}
    second='d747b5b42eef47bd843ce2fa4bf82748'
    assert runs[-1]['run_id']==second and len(records[second])==10
    import exp_tracker.server as server_module
    import exp_tracker.diagnostics as diagnostic_module
    class ReviewClock(datetime):
        at=None
        @classmethod
        def now(cls,tz=None):return cls.at
    server_module.datetime=diagnostic_module.datetime=ReviewClock
    with Store(database) as store:
        store.add_channel('telfer1');cid=store.add_character('telfer1',character['label'])
        store.select_character('telfer1',cid);store.start_session('telfer1')
        d=Diagnostics(store)
        def load(run):
            rid=run['run_id'];d.begin(rid,'telfer1',json.loads(run['configuration_json']))
            for record in records[rid]:d.append(rid,record)
            if run['summary_json']:d.append(rid,json.loads(run['summary_json']))
            ReviewClock.at=max(datetime.fromisoformat(r.get('received_at') or r['attempted_at']) for r in records[rid])+timedelta(seconds=4)
        for run in runs[:-1]:load(run)
        with create_server(database,port=port,diagnostic_dashboard=True) as http:
            http.quiet=True;thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
            print(json.dumps(dict(ready=True,port=http.server_port)),flush=True)
            try:
                for command in sys.stdin:
                    if command.strip()=='advance':load(runs[-1])
                    elif command.strip()=='expire':ReviewClock.at+=timedelta(days=2)
                    else:raise ValueError('Ordered replay commands only')
                    assert not store.db.execute('select 1 from observations').fetchone()
                    print(json.dumps(dict(stage=command.strip(),as_of=ReviewClock.at.isoformat())),flush=True)
            finally:http.shutdown();thread.join(2)


def historical_trial(database,port):
    root=Path('private/multi-alpha/runs/20261018T043432Z-c0b93f52')
    records={c:[[json.loads(s) for s in p.read_text().splitlines()] for p in sorted((root/c).rglob('capture.jsonl'),key=lambda p:len(p.parts))] for c in ('telfer1','shiphtur')}
    import exp_tracker.server as server_module
    import exp_tracker.diagnostics as diagnostic_module
    class ReviewClock(datetime):
        at=None
        @classmethod
        def now(cls,tz=None):return cls.at
    server_module.datetime=diagnostic_module.datetime=ReviewClock
    with Store(database) as store:
        d=Diagnostics(store)
        for channel,logs in records.items():
            store.add_channel(channel);cid=store.add_character(channel,'Saved review')
            store.select_character(channel,cid);store.start_session(channel)
            assert len(logs)==2
            for n,log in enumerate(logs):
                d.begin(log[0]['run_id'],channel,log[0])
                for row in log[1:]:
                    if n==0 or row['type']=='attempt' and row['index']<=28:d.append(log[0]['run_id'],row)
        ReviewClock.at=max(datetime.fromisoformat(row['received_at']) for logs in records.values() for row in logs[1] if row['type']=='attempt' and row['index']==28)+timedelta(seconds=4)
        with create_server(database,port=port,diagnostic_dashboard=True) as http:
            http.quiet=True;thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
            print(json.dumps(dict(ready=True)),flush=True)
            try:
                for command in sys.stdin:
                    action=command.strip()
                    if action=='finish':
                        for logs in records.values():
                            for row in logs[1][1:]:
                                if row['type']=='summary' or row['index']>28:d.append(logs[1][0]['run_id'],row)
                        ReviewClock.at=max(datetime.fromisoformat(row['received_at']) for logs in records.values() for row in logs[1] if row['type']=='attempt')+timedelta(seconds=4)
                    elif action=='age':ReviewClock.at+=timedelta(minutes=78)
                    else:raise ValueError('finish then age only')
                    assert not store.db.execute('select 1 from observations').fetchone()
                    print(json.dumps(dict(stage=action,as_of=ReviewClock.at.isoformat())),flush=True)
            finally:http.shutdown();thread.join(2)


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--directory',type=Path,required=True)
    cli.add_argument('--port',type=int,required=True)
    cli.add_argument('--usability',action='store_true',help='Saved two-stream trial, explicitly as-of replay clock')
    cli.add_argument('--level-up',action='store_true',help='Saved level-up trial; as-of replay, no source retiming')
    cli.add_argument('--windows',action='store_true',help='Saved fixed-window/60-attempt rotation review')
    cli.add_argument('--rolling',action='store_true',help='Actual new Telfer1 runs and existing character history, as-of replay')
    cli.add_argument('--historical',action='store_true',help='Actual completed 90-attempt two-stream trial, as-of clock')
    args=cli.parse_args()
    directory=args.directory.resolve()
    if not any(directory.is_relative_to(Path(p).resolve()) for p in ('private','artifacts')):
        raise ValueError('Private test directory required')
    database=directory/'updates.sqlite3'
    if database.exists():raise ValueError('Never overwrite an existing database')
    if args.historical:
        historical_trial(database,args.port)
        return
    if args.rolling:
        rolling_trial(database,args.port)
        return
    if args.windows:
        window_trial(database,args.port)
        return
    logs={channel:Path('private/local-alpha/runs')/run/'capture.jsonl' for channel,run in (
        ('telfer1','telfer1-20261017T214539Z-620539d6'),('shiphtur','shiphtur-20261017T214659Z-eba94e1c'))}
    saved={c:[json.loads(s) for s in p.read_text().splitlines()] for c,p in logs.items()}
    saved_trial=args.usability or args.level_up
    initial=13 if args.level_up else 7
    if saved_trial:
        root=Path('private/multi-alpha/runs')/('20261018T001050Z-b970792e' if args.level_up else '20261017T232522Z-d1ee1838')
        saved={c:[json.loads(s) for s in (root/c/'capture.jsonl').read_text().splitlines()] for c in logs}
        # As-of inspection only: original timestamps/payloads remain untouched.
        import exp_tracker.server as server_module
        import exp_tracker.diagnostics as diagnostic_module
        class ReviewClock(datetime):
            at=None
            @classmethod
            def now(cls,tz=None):return cls.at
        def as_of(index):
            ReviewClock.at=max(datetime.fromisoformat(r['received_at']) for records in saved.values()
                for r in records if r['type']=='attempt' and r['index']<=index and r.get('received_at'))
        as_of(initial)
        server_module.datetime=diagnostic_module.datetime=ReviewClock
    now=datetime.now(timezone.utc)
    with Store(database) as store:
        d=Diagnostics(store)
        for channel in (logs if saved_trial else (*logs,'synthetic_window')):
            store.add_channel(channel);cid=store.add_character(channel,'Synthetic window test' if channel=='synthetic_window' else 'Saved review')
            store.select_character(channel,cid);store.start_session(channel)
        for channel,records in saved.items():
            d.begin(records[0]['run_id'],channel,records[0])
            for record in records[1:]:
                if record['type']=='attempt' and record['index']<=(initial if saved_trial else 3 if channel=='telfer1' else 40):d.append(records[0]['run_id'],record)
        if not saved_trial:d.begin('synthetic-window','synthetic_window',dict(type='configuration',trusted=False,interval=15,source_kind='file'))
        def synthetic(index):
            # Test-generated historical timestamps, not a capture throughput/accuracy claim.
            stamp=(now-timedelta(seconds=5+15*(21-index))).isoformat()
            pct=f'{(6750+index)//100}.{(6750+index)%100:02}'
            return dict(type='attempt',trusted=False,index=index,current=True,attempted_at=stamp,received_at=stamp,frame_sha256=f'{index:064x}',
                source=dict(kind='file',channel=None),status='diagnostic_percentage_only',localization=dict(count=1),
                neural=dict(text=f'[{pct}%]'),visual_level=65,visual_status='available',
                neural_level=dict(status='numeric_candidate',text='65',level=65,score=.99,preprocessing='neutral4'))
        if not saved_trial:
            for i in range(1,20):d.append('synthetic-window',synthetic(i))
        with create_server(database,port=args.port,diagnostic_dashboard=True) as http:
            http.quiet=True
            thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
            print(json.dumps(dict(ready=True,port=http.server_port)),flush=True)
            advanced=False;change_index=22;last_saved=initial
            try:
                for command in sys.stdin:
                    action=command.strip()
                    if saved_trial:
                        expected={13:('levelup',14),14:('advance',15),15:('finish',42)} if args.level_up else {7:('advance',10),10:('finish',25)}
                        if last_saved not in expected or action!=expected[last_saved][0]:raise ValueError('Ordered saved replay commands only')
                        lower,upper=last_saved,expected[last_saved][1]
                        for channel,records in saved.items():
                            for record in records[1:]:
                                if record['type']=='attempt' and lower<record['index']<=upper:d.append(records[0]['run_id'],record)
                                if action=='finish' and record['type']=='summary':d.append(records[0]['run_id'],record)
                        as_of(upper);advanced=True;last_saved=upper
                        assert not store.db.execute('SELECT 1 FROM observations').fetchone()
                        print(json.dumps(dict(stage=action,as_of=ReviewClock.at.isoformat())),flush=True)
                        continue
                    if advanced and action in ('decrease','confirm','recover'):
                        expected,pct={22:('decrease','67.50'),23:('confirm','67.55'),24:('recover','67.60')}[change_index]
                        if action!=expected:raise ValueError('Quarantine test commands must be ordered')
                        record=synthetic(change_index);stamp=datetime.now(timezone.utc).isoformat()
                        record.update(attempted_at=stamp,received_at=stamp,neural=dict(text=f'[{pct}%]'))
                        d.append('synthetic-window',record);change_index+=1
                        print(json.dumps(dict(stage=action)),flush=True);continue
                    if command.strip()!='advance' or advanced:raise ValueError('One bounded advance only')
                    for channel,records in saved.items():
                        for record in records[1:]:
                            if record['type']=='attempt' and record['index']>(3 if channel=='telfer1' else 40):d.append(records[0]['run_id'],record)
                        d.append(records[0]['run_id'],records[-1])
                    for i in (20,21):d.append('synthetic-window',synthetic(i))
                    assert not store.db.execute('SELECT 1 FROM observations').fetchone()
                    advanced=True;print(json.dumps(dict(advanced=True)),flush=True)
            finally:
                http.shutdown();thread.join(timeout=2)


if __name__=='__main__':main()
