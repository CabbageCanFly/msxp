"""Private SYNTHETIC homepage/character API latency at 1-25 channels; never Twitch or OCR.

One full-day 20-second channel is written through the normal Diagnostics append and
rotation path, then cloned per channel with SQL. An in-process read-only server is
timed over HTTP in cold, warm and newly-appended (cache-invalidated) states, then
under a bounded concurrent viewer load, with the background publisher. ``--full-replay``
disables causal checkpoints.
"""
import argparse
from contextlib import closing
from datetime import datetime,timedelta,timezone
from fractions import Fraction
import json
import multiprocessing
import os
from pathlib import Path
import shutil
import statistics
import threading
import time
from urllib.request import urlopen

import psutil

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


PROCESS=psutil.Process(os.getpid())
def cpu():
    times=PROCESS.cpu_times();return times.user+times.system


def get(server,path,timeout=600):
    tick=time.perf_counter()
    with urlopen(f'http://127.0.0.1:{server.server_port}{path}',timeout=timeout) as response:body=json.load(response)
    return (time.perf_counter()-tick)*1000,body


def nested(packet):
    values=[packet['windows'][m]['gain'] for m in ('5','10','15','30','60')]+[packet['tracked_exp']]
    values=[Fraction(v['numerator'],v['denominator']) for v in values if v is not None]
    assert values==sorted(values),'nested tracked EXP invariant'
    return len(values)


def measure(db,channels,open_runs,next_n,start,repeat,full_replay=False,viewers=0,seconds=0):
    """Background publisher: requests only read published state; the refresher computes it."""
    used=cpu();tick=time.monotonic()
    server=create_server(db,port=0,diagnostic_dashboard=True,background=True);server.quiet=True
    if full_replay:server.checkpoints=None
    baseline=threading.active_count()
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    result=dict(channels=channels);n=dict.fromkeys((f'bench_{i:02d}' for i in range(channels)),next_n)
    publisher=server.publisher
    def append(names):
        # A new capture for each named channel: the latest revision changes, as in live operation.
        stamps={}
        with Store(db) as store:
            d=Diagnostics(store)
            for name in names:
                i=int(name[-2:]);stamps[name]=datetime.now(timezone.utc)
                d.append(open_runs.replace('c00-',f'c{i:02d}-'),payload(name,n[name]%60+1,n[name],start,stamps[name]))
                n[name]+=1
        return stamps
    def published(stamps):
        """Seconds until every appended capture is visible through the HTTP API."""
        tick=time.monotonic()
        while time.monotonic()-tick<600:
            players={p['channel']:p for p in get(server,'/api/players')[1]['players']}
            if all(players.get(c,{}).get('latest_attempt_at')==s.isoformat() for c,s in stamps.items()):return round(time.monotonic()-tick,2)
            time.sleep(.05)
        raise AssertionError('Publication did not arrive')
    def stats():
        value=dict(publisher.stats);return dict(builds=value['builds'],build_seconds=value['build_seconds'],presentations=value['presentations'],present_seconds=value['present_seconds'])
    names=[f'bench_{i:02d}' for i in range(channels)]
    try:
        ms,body=get(server,'/api/players')
        result['cold_first_response_ms']=round(ms,1);result['cold_first_warming']=len(body.get('warming',[]))
        while len(get(server,'/api/players')[1]['players'])<channels:time.sleep(.1)
        result['cold_full_availability_seconds']=round(time.monotonic()-tick,1);result['cold_cpu_seconds']=round(cpu()-used,1)
        warm=[get(server,'/api/players')[0] for _ in range(repeat)]
        result['home_warm_ms']=dict(median=round(statistics.median(warm),1),max=round(max(warm),1))
        warm=[get(server,'/api/players/bench_00')[0] for _ in range(repeat)]
        result['character_warm_ms']=dict(median=round(statistics.median(warm),1),max=round(max(warm),1))
        before=stats()
        result['one_capture_visible_seconds']=[published(append(names[:1])) for _ in range(3)]
        result['all_captures_visible_seconds']=published(append(names))
        after=stats()
        result['refresh_build_ms_mean']=round((after['build_seconds']-before['build_seconds'])/max(1,after['builds']-before['builds'])*1000)
        result['present_ms_mean']=round((after['present_seconds']-before['present_seconds'])/max(1,after['presentations']-before['presentations'])*1000,1)
        result['nested_values']=min(nested(get(server,f'/api/players/{name}/history')[1]) for name in names)
        if viewers:
            before=stats();publisher.stats['max_build_seconds']=0;result['viewers']=load(server,names,append,viewers,seconds);after=stats()
            result['viewers'].update(refresher_builds=after['builds']-before['builds'],max_build_ms=round(publisher.stats['max_build_seconds']*1000),refresher_busy_fraction=round((after['build_seconds']-before['build_seconds'])/result['viewers']['seconds'],2),
                presentations=after['presentations']-before['presentations'],present_busy_fraction=round((after['present_seconds']-before['present_seconds'])/result['viewers']['seconds'],3))
        result['rss_mib']=round(PROCESS.memory_info().rss/2**20)
    finally:
        server.shutdown();thread.join(5);server.server_close()
        # Handler threads are daemons: requests a client abandoned keep running. Let
        # them finish so they cannot steal CPU from the next measurement.
        tick=time.monotonic()
        while threading.active_count()>baseline and time.monotonic()-tick<1800:time.sleep(.2)
        result['abandoned_work_drain_seconds']=round(time.monotonic()-tick,1)
    return result


def viewer_process(port,names,first,count,viewers,start_at,seconds,queue):
    """Viewers first..first+count-1 in their own process, so client CPU never shares the server's GIL."""
    samples={'home':[],'character':[],'history':[]};timeouts=dict.fromkeys(samples,0);errors=dict.fromkeys(samples,0);reasons={};lock=threading.Lock()
    stop=start_at+seconds
    def fetch(kind,path):
        tick=time.perf_counter()
        try:
            with urlopen(f'http://127.0.0.1:{port}{path}',timeout=5) as response:data=response.read()
        except OSError as error:  # HTTPError (e.g. 503 warming) is an error; a socket timeout is a timeout.
            with lock:
                if isinstance(getattr(error,'reason',error),TimeoutError):timeouts[kind]+=1
                else:
                    errors[kind]+=1;reason=f'HTTP {error.code}' if hasattr(error,'code') else type(getattr(error,'reason',error)).__name__;reasons[reason]=reasons.get(reason,0)+1
            return None
        ms=(time.perf_counter()-tick)*1000
        with lock:
            if ms>5000:timeouts[kind]+=1  # The browser aborts the whole request at 5 s.
            else:samples[kind].append(ms)
        return json.loads(data)
    def viewer(i):
        kind='home' if i%2==0 else 'character';channel=names[i//2%len(names)]
        path='/api/players' if kind=='home' else f'/api/players/{channel}'
        time.sleep(max(0,start_at-time.time())+i*2/viewers);polls=0
        while time.time()<stop:
            body=fetch(kind,path)
            if body:
                for p in body['players'] if kind=='home' else [body['player']]:
                    values=[w['gain'] for w in p['recent_windows'].values() if w.get('gain')]
                    values=[Fraction(v['numerator'],v['denominator']) for v in values]
                    assert values==sorted(values),'nested public totals'
            if kind=='character' and polls%15==0:fetch('history',f'/api/players/{channel}/history')  # The page refreshes history every 30 s.
            polls+=1;time.sleep(2)
    threads=[threading.Thread(target=viewer,args=(i,)) for i in range(first,first+count)]
    for t in threads:t.start()
    for t in threads:t.join()
    queue.put((samples,timeouts,errors,reasons))


def load(server,names,append,viewers,seconds):
    """Browser-like clients in separate processes: 5 s timeout, next poll 2 s after each response.
    One capture per channel per 20 s is appended in this process; a monitor samples publication lag, entry age and RSS."""
    publisher=server.publisher;pending={};lags=[];ages=[];rss=[PROCESS.memory_info().rss];done=threading.Event()
    def monitor():
        while not done.is_set():
            rss[0]=max(rss[0],PROCESS.memory_info().rss);now=datetime.now(timezone.utc)
            with publisher.lock:entries=dict(publisher.entries)
            if entries:ages.append(max((now-datetime.fromisoformat(e['built_at'])).total_seconds() for e in entries.values()))
            for (name,stamp),at in list(pending.items()):
                latest=entries.get(name,{}).get('card',{}).get('player',{}).get('latest_attempt_at')
                if latest and datetime.fromisoformat(latest)>=stamp:lags.append(time.monotonic()-at);del pending[(name,stamp)]
            done.wait(.1)
    def writer():
        while time.time()<stop:
            for name in names:
                if time.time()>=stop:return
                for stamp in append([name]).values():pending[(name,stamp)]=time.monotonic()
                time.sleep(STEP/len(names))
    per=25;queue=multiprocessing.Queue()
    start_at=time.time()+5;stop=start_at+seconds  # Client processes need a few seconds to spawn on Windows.
    clients=[multiprocessing.Process(target=viewer_process,args=(server.server_port,names,first,min(per,viewers-first),viewers,start_at,seconds,queue))
        for first in range(0,viewers,per)]
    for c in clients:c.start()
    time.sleep(max(0,start_at-time.time()))
    threads=[threading.Thread(target=writer),threading.Thread(target=monitor)]
    used=cpu();tick=time.monotonic()
    for t in threads:t.start()
    results=[queue.get() for _ in clients]
    for c in clients:c.join()
    wall=time.monotonic()-tick;cpu_rate=round((cpu()-used)/wall,2);done.set()
    for t in threads:t.join()
    lags.sort();ages.sort()
    result=dict(viewers=viewers,client_processes=len(clients),seconds=round(wall,1),server_cpu_seconds_per_second=cpu_rate,peak_rss_mib=round(rss[0]/2**20),
        capture_to_publication_s=dict(count=len(lags),unpublished=len(pending),p50=round(lags[len(lags)//2],2),p95=round(lags[int(.95*(len(lags)-1))],2),max=round(lags[-1],2)) if lags else dict(unpublished=len(pending)),
        error_reasons={k:sum(r[3].get(k,0) for r in results) for r in results for k in r[3]},
        oldest_entry_age_s=dict(p50=round(ages[len(ages)//2],1),p95=round(ages[int(.95*(len(ages)-1))],1),max=round(ages[-1],1)) if ages else None)
    for kind in ('home','character','history'):
        values=sorted(v for samples,*_ in results for v in samples[kind])
        result[kind]=dict(requests=len(values),timeouts=sum(r[1][kind] for r in results),errors=sum(r[2][kind] for r in results),
            **(dict(p50_ms=round(statistics.median(values)),p95_ms=round(values[int(.95*(len(values)-1))]),
            p99_ms=round(values[int(.99*(len(values)-1))]),max_ms=round(values[-1])) if values else {}))
    return result


def main(argv=None):
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--directory',type=Path,required=True)
    cli.add_argument('--attempts',type=int,default=4321,help='Per channel; 4,321 at 20s is 24 hours')
    cli.add_argument('--channels',type=int,nargs='+',default=[1,5,10,25])
    cli.add_argument('--repeat',type=int,default=5)
    cli.add_argument('--full-replay',action='store_true',help='Disable causal checkpoints (before/after baseline)')
    cli.add_argument('--viewers',type=int,default=0,help='Concurrent browser-like clients after the scenarios')
    cli.add_argument('--seconds',type=int,default=30)
    args=cli.parse_args(argv)
    if not 61<=args.attempts<=4400 or not all(1<=c<=25 for c in args.channels) or not 0<=args.viewers<=200 or not 5<=args.seconds<=300:
        cli.error('Use 61..4400 attempts, 1..25 channels, 0..200 viewers and 5..300 seconds')
    folder=private_path(args.directory);folder.mkdir(parents=True,exist_ok=False)
    start=datetime.now(timezone.utc)-timedelta(seconds=args.attempts*STEP+60)
    base=folder/'template.sqlite3';tick=time.perf_counter();open_run,next_n=template(base,args.attempts,start)
    report=dict(synthetic=True,not_capture_throughput=True,attempts_per_channel=args.attempts,cadence_seconds=STEP,full_replay=args.full_replay,
        template_build_seconds=round(time.perf_counter()-tick,1),results=[])
    for channels in args.channels:
        db=folder/f'channels-{channels:02d}.sqlite3';shutil.copy(base,db);clone(db,channels,start)
        result=measure(db,channels,open_run,next_n,start,args.repeat,args.full_replay,args.viewers,args.seconds)
        report['results'].append(result);print(json.dumps(result),flush=True)
    (folder/'homepage-benchmark.json').write_text(json.dumps(report,indent=2),encoding='utf-8')


if __name__=='__main__':main()
