"""Private SYNTHETIC homepage/character API latency at 1-25 channels; never Twitch or OCR.

One full-day 20-second channel is written through the normal Diagnostics append and
rotation path, then cloned per channel with SQL. An in-process read-only server is
timed over HTTP in cold, warm and newly-appended (cache-invalidated) states.
"""
import argparse
from contextlib import closing
from datetime import datetime,timedelta,timezone
from fractions import Fraction
import json
from pathlib import Path
import shutil
import statistics
import threading
import time
from urllib.request import urlopen

from shadow_capture import private_path
from exp_tracker.diagnostics import Diagnostics
from exp_tracker.exp_requirements import requirement
from exp_tracker.server import create_server
from exp_tracker.store import Store

STEP=20


def payload(channel,index,n,start,at=None):
    stamp=(at or start+timedelta(seconds=n*STEP)).isoformat();bp=1000+n%8000;pct=f'{bp//100}.{bp%100:02}'
    exp=bp*requirement(64)['to_next']//10000
    return dict(type='attempt',index=index,trusted=False,current=True,attempted_at=stamp,received_at=stamp,
        localization=dict(count=1),frame_sha256=f'{n:064x}',visual_level=64,visual_status='available',
        neural_level=dict(status='numeric_candidate',text='64',level=64,score=.99),
        source=dict(kind='twitch',channel=channel),neural=dict(text=f'{exp:,}[{pct}%]'),candidate=[exp,float(pct)],status='diagnostic_pair')


def config(run,previous=None):
    return dict(type='configuration',trusted=False,interval=STEP,count=60,run_id=run,source_kind='twitch',
        coordinator='multi_alpha_v1',coordinator_instance='a'*32,source_identity='b'*64,requirements_sha256='c'*64,
        timing_mode='real',start_reason='scheduled_rotation' if previous else 'process_start',previous_run_id=previous)


def template(db,attempts,start):
    """Real append/rotation code path for one channel; returns the open run and next attempt number."""
    with Store(db) as store:
        store.add_channel('bench_00');cid=store.add_character('bench_00','SYNTHETIC');store.select_character('bench_00',cid)
        store.start_session('bench_00',at=start)
        d=Diagnostics(store);run=None
        for n in range(attempts):
            if n%60==0:
                following=f'c00-r{n//60:04d}'
                if run:d.rotate(run,following,'bench_00',dict(type='summary',trusted=False,attempts=60,interrupted=False,
                    completion_reason='scheduled_rotation',next_run_id=following),config(following,run))
                else:d.begin(following,'bench_00',config(following))
                run=following
            d.append(run,payload('bench_00',n%60+1,n,start))
    return run,attempts


def clone(db,channels,start):
    with Store(db) as store:
      for i in range(1,channels):
        name=f'bench_{i:02d}';prefix=f'c{i:02d}-'
        store.add_channel(name);cid=store.add_character(name,'SYNTHETIC');store.select_character(name,cid)
        store.start_session(name,at=start)
        sid=store._channel(name)['id'];session=store._open_session(sid)['id']
        with store._transaction():
            store.db.execute('''INSERT INTO diagnostic_runs SELECT REPLACE(run_id,'c00-',?),?,?,?,created_at,
                REPLACE(configuration_json,'c00-',?),REPLACE(summary_json,'c00-',?) FROM diagnostic_runs WHERE run_id LIKE 'c00-%' ''',
                (prefix,sid,cid,session,prefix,prefix))
            store.db.execute('''INSERT INTO diagnostic_attempts(run_id,attempt_index,attempted_at,received_at,recorded_at,payload_json,session_id)
                SELECT REPLACE(run_id,'c00-',?),attempt_index,attempted_at,received_at,recorded_at,REPLACE(payload_json,'bench_00',?),?
                FROM diagnostic_attempts WHERE run_id LIKE 'c00-%' ORDER BY id''',(prefix,name,session))


class TimedLock:
    def __init__(self):self.lock=threading.Lock();self.wait=0.0;self.held=0.0;self.since=0.0
    def __enter__(self):
        tick=time.perf_counter();self.lock.acquire();self.since=time.perf_counter();self.wait+=self.since-tick
    def __exit__(self,*_):self.held+=time.perf_counter()-self.since;self.lock.release()


SPENT={}
def timed(name,function):
    def wrapper(*args,**kwargs):
        tick=time.perf_counter()
        try:return function(*args,**kwargs)
        finally:SPENT[name]=SPENT.get(name,0.0)+time.perf_counter()-tick
    return wrapper


for name in ('directory','rolling_history','recent_snapshot'):setattr(Diagnostics,name,timed(name,getattr(Diagnostics,name)))


def get(server,path):
    tick=time.perf_counter()
    with urlopen(f'http://127.0.0.1:{server.server_port}{path}',timeout=600) as response:body=json.load(response)
    return (time.perf_counter()-tick)*1000,body


def nested(packet):
    values=[packet['windows'][m]['gain'] for m in ('5','10','15','30','60')]+[packet['tracked_exp']]
    values=[Fraction(v['numerator'],v['denominator']) for v in values if v is not None]
    assert values==sorted(values),'nested tracked EXP invariant'
    return len(values)


def measure(db,channels,open_runs,next_n,start,repeat):
    server=create_server(db,port=0,diagnostic_dashboard=True);server.quiet=True
    server.history_lock=TimedLock();server.directory_lock=TimedLock()
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    result=dict(channels=channels);n=dict.fromkeys((f'bench_{i:02d}' for i in range(channels)),next_n)
    def scenario(label,action):
        SPENT.clear();server.history_lock.wait=server.history_lock.held=server.directory_lock.wait=0.0
        ms,body=action()
        result[label]=dict(ms=round(ms,1),**{k:round(v*1000,1) for k,v in SPENT.items()},
            history_lock_wait_ms=round(server.history_lock.wait*1000,1),history_lock_held_ms=round(server.history_lock.held*1000,1),
            directory_lock_wait_ms=round(server.directory_lock.wait*1000,1))
        return body
    def append(names):
        # A new capture for each named channel: the latest revision changes, as in live operation.
        with Store(db) as store:
            d=Diagnostics(store)
            for name in names:
                i=int(name[-2:]);d.append(open_runs.replace('c00-',f'c{i:02d}-'),payload(name,n[name]%60+1,n[name],start,datetime.now(timezone.utc)))
                n[name]+=1
    names=[f'bench_{i:02d}' for i in range(channels)]
    try:
        body=scenario('home_cold',lambda:get(server,'/api/players'))
        assert len(body['players'])==channels
        warm=[get(server,'/api/players')[0] for _ in range(repeat)]
        result['home_warm_ms']=dict(median=round(statistics.median(warm),1),max=round(max(warm),1))
        append(names[:1]);scenario('home_one_new_capture',lambda:get(server,'/api/players'))
        append(names);body=scenario('home_all_new_captures',lambda:get(server,'/api/players'))
        # Every channel changed, so every packet is recomputed at this response's clock.
        served=datetime.fromisoformat(body['served_at'].replace('Z','+00:00'))
        assert all(datetime.fromisoformat(p['tracked_as_of'])==served for p in body['players'])
        result['nested_values']=min(nested(get(server,f'/api/players/{name}/history')[1]) for name in names)
        warm=[get(server,'/api/players/bench_00')[0] for _ in range(repeat)]
        result['character_warm_ms']=dict(median=round(statistics.median(warm),1),max=round(max(warm),1))
        append(names[:1]);scenario('character_new_capture',lambda:get(server,'/api/players/bench_00'))
        if channels>1:
            # Unrelated reader while the homepage replays every changed channel.
            append(names);other=names[-1];get(server,f'/api/players/{other}')  # other's own cache is fresh
            append([n_ for n_ in names if n_!=other]);done={}
            homepage=threading.Thread(target=lambda:done.update(home=get(server,'/api/players')[0]));homepage.start()
            time.sleep(.05);done['other']=get(server,f'/api/players/{other}')[0];homepage.join()
            result['concurrent_homepage_ms']=round(done['home'],1);result['concurrent_unchanged_character_ms']=round(done['other'],1)
    finally:server.shutdown();thread.join(5);server.server_close()
    return result


def main(argv=None):
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--directory',type=Path,required=True)
    cli.add_argument('--attempts',type=int,default=4321,help='Per channel; 4,321 at 20s is 24 hours')
    cli.add_argument('--channels',type=int,nargs='+',default=[1,5,10,25])
    cli.add_argument('--repeat',type=int,default=5)
    args=cli.parse_args(argv)
    if not 61<=args.attempts<=4400 or not all(1<=c<=25 for c in args.channels):cli.error('Use 61..4400 attempts and 1..25 channels')
    folder=private_path(args.directory);folder.mkdir(parents=True,exist_ok=False)
    start=datetime.now(timezone.utc)-timedelta(seconds=args.attempts*STEP+60)
    base=folder/'template.sqlite3';tick=time.perf_counter();open_run,next_n=template(base,args.attempts,start)
    report=dict(synthetic=True,not_capture_throughput=True,attempts_per_channel=args.attempts,cadence_seconds=STEP,
        template_build_seconds=round(time.perf_counter()-tick,1),results=[])
    for channels in args.channels:
        db=folder/f'channels-{channels:02d}.sqlite3';shutil.copy(base,db);clone(db,channels,start)
        result=measure(db,channels,open_run,next_n,start,args.repeat)
        report['results'].append(result);print(json.dumps(result),flush=True)
    (folder/'homepage-benchmark.json').write_text(json.dumps(report,indent=2),encoding='utf-8')


if __name__=='__main__':main()
