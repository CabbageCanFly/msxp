"""Real CLI byte parity, fresh process state, timeouts and coordinator wiring."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading

import pytest

from exp_tracker import preloaded_streamlink as preload
from exp_tracker.video import CaptureError, Source, VideoSession


@pytest.fixture
def launcher(monkeypatch):
    monkeypatch.setenv('TWITCH_PLAYBACK_TOKEN','')
    if sys.platform!='linux':pytest.skip('Linux forkserver native tests run separately on Linux')
    value=preload.PreloadedStreamlink()
    yield value
    value.close()


def output(process):
    with ThreadPoolExecutor(max_workers=2) as readers:
        data=readers.submit(process.stdout.read);errors=readers.submit(process.stderr.read)
        try:
            code=process.wait(timeout=15)
        finally:process.stop()
        result=code,data.result(timeout=3),errors.result(timeout=3)
    process.stdout.close();process.stderr.close()
    assert process.poll()==code and process.wait(timeout=0)==code
    return result


@contextmanager
def hls(payloads, *, stalled=False):
    release=threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            if stalled:
                release.wait(20)
                return
            name=self.path.rsplit('/',1)[-1].split('.')[0]
            if self.path.endswith('.m3u8'):
                body=('#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:3\n'
                    f'#EXTINF:3.0,\n{name}.ts\n#EXT-X-ENDLIST\n').encode()
            else:body=payloads[name]
            self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers()
            try:self.wfile.write(body)
            except (BrokenPipeError,ConnectionResetError):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:yield f'http://127.0.0.1:{server.server_port}'
    finally:release.set();server.shutdown();server.server_close();thread.join(timeout=2)


def test_raw_hls_bytes_and_concurrent_children_match_the_ordinary_cli(launcher):
    payloads={name:(name.encode()+b'\0\xff\n')*16384 for name in ('alpha','beta','gamma')}
    with hls(payloads) as base:
        commands={name:Source('hls',f'{base}/{name}.m3u8').streamlink_command() for name in payloads}
        for name,command in commands.items():
            cold=subprocess.run(command,capture_output=True,timeout=15)
            assert cold.returncode==0 and cold.stdout==payloads[name]
        processes={name:launcher(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE) for name,command in commands.items()}
        assert len({p.pid for p in processes.values()})==3
        with ThreadPoolExecutor(max_workers=3) as readers:
            results=dict(zip(processes,readers.map(output,processes.values())))
        for name,(code,data,errors) in results.items():
            assert code==0,errors.decode(errors='replace')
            assert data==payloads[name] and errors==b''


def test_authenticated_cli_uses_each_attempts_environment_without_leaking_it(launcher,monkeypatch):
    probe=[sys.executable,'-m','exp_tracker.streamlink_playback','--no-config','--no-plugin-cache',
        '--no-plugin-sideloading','--webbrowser','false','--loglevel','error',
        '--can-handle-url-no-redirect','https://www.twitch.tv/streamer_a']
    pids=[]
    for token,expected in [('firstSyntheticToken',0),('bad\nprivateToken',1),('secondSyntheticToken',0)]:
        monkeypatch.setenv('TWITCH_PLAYBACK_TOKEN',token)
        process=launcher(probe,stdout=subprocess.PIPE,stderr=subprocess.PIPE);pids.append(process.pid)
        code,data,errors=output(process)
        assert code==expected and not data and token.encode() not in errors
        if code:assert b'ValueError' in errors
    assert len(set(pids))==3


def test_timeout_cleanup_reaps_playback_and_decoder_and_closed_launcher_cannot_restart(launcher):
    ffmpeg=os.environ.get('FFMPEG_CMD') or shutil.which('ffmpeg')
    if not ffmpeg:pytest.skip('FFmpeg unavailable for capture cleanup test')
    with hls({},stalled=True) as base:
        session=VideoSession(Source('hls',f'{base}/hung.m3u8'),ffmpeg=ffmpeg,producer_factory=launcher)
        try:
            with pytest.raises(CaptureError):session.frame(timeout=.2)
        finally:session.close()
        assert session.producer.poll() is not None and session.decoder.poll() is not None
        assert all(not thread.is_alive() for thread in session.threads)
        session.close();launcher.close()
        with pytest.raises(OSError,match='closed'):
            launcher(Source('hls',base).streamlink_command(),stdout=subprocess.PIPE,stderr=subprocess.PIPE)


def test_real_decoder_receives_the_same_pixels_with_preloaded_streamlink(launcher):
    ffmpeg=os.environ.get('FFMPEG_CMD') or shutil.which('ffmpeg')
    if not ffmpeg:pytest.skip('FFmpeg unavailable for real HLS decoding')
    payload=subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-f','lavfi','-i',
        'color=c=red:s=160x90:r=1','-frames:v','3','-c:v','mpeg2video','-g','1',
        '-f','mpegts','pipe:1'],capture_output=True,timeout=15,check=True).stdout
    with hls({'red':payload}) as base:
        frames=[]
        for factory in (None,launcher):
            session=VideoSession(Source('hls',f'{base}/red.m3u8'),ffmpeg=ffmpeg,producer_factory=factory)
            try:
                try:frames.append(session.frame(timeout=15,max_age=5))
                except CaptureError:
                    pytest.fail(str({name:bytes(log).decode(errors='replace') for name,log in session.logs.items()}))
            finally:session.close()
        assert frames[0].png==frames[1].png and frames[1].image().size==(160,90)
        assert all(f.received_at and f.sequence>0 for f in frames)


def test_launcher_rejects_arbitrary_commands_and_incompatible_pipes(launcher):
    with pytest.raises(ValueError):launcher([sys.executable,'-c','raise SystemExit(0)'],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    with pytest.raises(ValueError):launcher([sys.executable,'-m','streamlink'],stdout=None,stderr=subprocess.PIPE)


def test_non_linux_preload_is_refused(monkeypatch):
    monkeypatch.setattr(preload.sys,'platform','win32')
    with pytest.raises(ValueError,match='requires Linux'):preload.PreloadedStreamlink()


@pytest.mark.skipif(sys.platform!='linux',reason='Forkserver crash/recovery is tested on Linux')
def test_dead_forkserver_cannot_leave_a_playback_child_running(tmp_path):
    script=tmp_path/'failure.py'
    script.write_text('''import sys,subprocess,psutil
from exp_tracker.preloaded_streamlink import PreloadedStreamlink
if __name__=='__main__':
    launcher=PreloadedStreamlink()
    process=launcher([sys.executable,'-m','streamlink','--no-config','--no-plugin-cache',
        '--no-plugin-sideloading','--webbrowser','false','--loglevel','error','--http-timeout','15',
        '--stdout',sys.argv[1],'best'],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    child=psutil.Process(process.pid)
    child.parent().kill()
    launcher.close()
    assert not child.is_running() or child.status()==psutil.STATUS_ZOMBIE
    assert process.poll() is not None
    process.stdout.close();process.stderr.close()
    fresh=PreloadedStreamlink()
    try:fresh.check()
    finally:fresh.close()
''')
    with hls({},stalled=True) as base:
        env=dict(os.environ,PYTHONPATH=str(Path(preload.__file__).resolve().parents[1]),TWITCH_PLAYBACK_TOKEN='')
        result=subprocess.run([sys.executable,str(script),'hls://'+base+'/hung.m3u8'],
            capture_output=True,timeout=25,env=env)
        assert result.returncode==0,result.stderr.decode(errors='replace')


from tests.test_multi_alpha import multi,main as run_main,record  # noqa: E402,F401


@pytest.mark.parametrize('check',[False,True])
def test_coordinator_wires_one_launcher_and_always_closes_it(multi,monkeypatch,check):
    module,path,_,_,_=multi;made=[];seen=[]
    class Launcher:
        closed=False
        def __init__(self):made.append(self)
        def check(self):pass
        def close(self):self.closed=True
    monkeypatch.setattr(preload,'PreloadedStreamlink',Launcher)
    def capture(*args,**kwargs):seen.append(kwargs);return record(args[3])
    monkeypatch.setattr(module.shadow,'capture_attempt',capture)
    assert run_main(multi,'--preload-streamlink',*(['--check'] if check else []))==0
    assert len(made)==1 and made[0].closed
    assert len(seen)==(0 if check else 4) and all(item['streamlink'] is made[0] for item in seen)
    if check:assert not (path.parent/'shared.sqlite3').exists()


def test_preload_failure_stops_before_database_or_capture(multi,monkeypatch):
    module,path,_,_,_=multi;closed=[]
    class Launcher:
        def check(self):raise ValueError('Preloaded Streamlink CLI preflight failed')
        def close(self):closed.append(True)
    monkeypatch.setattr(preload,'PreloadedStreamlink',Launcher)
    monkeypatch.setattr(module.shadow,'capture_attempt',lambda *a,**kw:pytest.fail('capture started'))
    assert run_main(multi,'--preload-streamlink')==1
    assert closed==[True] and not (path.parent/'shared.sqlite3').exists()


@pytest.mark.parametrize('platform,source,setting,flags,expected',[
    ('linux','twitch',None,[],True),
    ('linux','file',None,[],False),
    ('win32','twitch',None,[],False),
    ('darwin','twitch',None,[],False),
    ('linux','twitch','auto',[],True),
    ('linux','twitch','0',[],False),
    ('linux','twitch',None,['--no-preload-streamlink'],False),
    ('linux','twitch','1',['--no-preload-streamlink'],False),
    ('linux','twitch','0',['--preload-streamlink'],True),
])
def test_platform_and_source_defaults_allow_environment_and_cli_overrides(
        multi,monkeypatch,platform,source,setting,flags,expected):
    module,path,config,_,_=multi;made=[]
    monkeypatch.setattr(module.sys,'platform',platform)
    monkeypatch.delenv('MSXP_PRELOAD_STREAMLINK',raising=False)
    if setting is not None:monkeypatch.setenv('MSXP_PRELOAD_STREAMLINK',setting)
    if source=='twitch':
        for row in config['streams']:
            row.update(source='twitch',authorized=True)
            row.pop('file')
        path.write_text(json.dumps(config))
    class Launcher:
        def __init__(self):made.append('start')
        def check(self):made.append('check')
        def close(self):made.append('close')
    monkeypatch.setattr(preload,'PreloadedStreamlink',Launcher)
    assert run_main(multi,'--check',*flags)==0
    assert made==(['start','check','close'] if expected else [])
    assert not (path.parent/'shared.sqlite3').exists()


def test_invalid_preload_environment_is_rejected(multi,monkeypatch):
    monkeypatch.setenv('MSXP_PRELOAD_STREAMLINK','typo')
    with pytest.raises(SystemExit):run_main(multi,'--check')


def test_empty_database_roster_preloads_for_future_streamers_without_writing(multi,monkeypatch):
    from exp_tracker import streamer_roster
    from exp_tracker.store import Store
    module,path,_,_,_=multi
    database=path.parent/'empty.sqlite3';streamer_roster.create(database)
    with Store(database,read_only=True) as store:before=streamer_roster.database_digest(store)
    monkeypatch.setattr(module.sys,'platform','linux')
    monkeypatch.delenv('MSXP_PRELOAD_STREAMLINK',raising=False)
    made=[]
    class Launcher:
        def check(self):made.append('check')
        def close(self):made.append('close')
    monkeypatch.setattr(preload,'PreloadedStreamlink',Launcher)
    assert module.main(['--db-roster',str(database),'--port','0','--continuous','--check'])==0
    assert made==['check','close']
    with Store(database,read_only=True) as store:assert streamer_roster.database_digest(store)==before


@pytest.mark.parametrize('stage',['construction','check'])
def test_automatic_preload_falls_back_but_explicit_enablement_fails(multi,monkeypatch,capsys,stage):
    module,path,config,_,_=multi
    monkeypatch.setattr(module.sys,'platform','linux')
    monkeypatch.delenv('MSXP_PRELOAD_STREAMLINK',raising=False)
    for row in config['streams']:
        row.update(source='twitch',authorized=True);row.pop('file')
    path.write_text(json.dumps(config));closed=[]
    class Launcher:
        def __init__(self):
            if stage=='construction':raise OSError('unsupported process setup')
        def check(self):raise ValueError('preflight failed')
        def close(self):closed.append(True)
    monkeypatch.setattr(preload,'PreloadedStreamlink',Launcher)
    assert run_main(multi,'--check')==0
    assert 'using ordinary CLI startup' in capsys.readouterr().err
    assert closed==([True] if stage=='check' else [])
    assert run_main(multi,'--preload-streamlink','--check')==1
    assert closed==([True,True] if stage=='check' else [])
    assert not (path.parent/'shared.sqlite3').exists()


def test_automatic_preload_does_not_launch_during_historical_replay(multi,monkeypatch):
    module,path,config,_,_=multi
    for row in config['streams']:
        row.update(source='twitch',authorized=True);row.pop('file')
    path.write_text(json.dumps(config))
    assert run_main(multi,'--no-preload-streamlink')==0
    flags=[]
    for row in config['streams']:
        log=next((path.parent/'multi-alpha/runs').glob(f"*/{row['channel']}/capture.jsonl"))
        flags.extend(['--replay',f"{row['channel']}={log}"])
    monkeypatch.setattr(module.sys,'platform','linux')
    monkeypatch.delenv('MSXP_PRELOAD_STREAMLINK',raising=False)
    monkeypatch.setattr(preload,'PreloadedStreamlink',lambda:pytest.fail('replay launched playback'))
    monkeypatch.setattr(module.shadow,'capture_attempt',lambda *a,**kw:pytest.fail('replay captured'))
    assert run_main(multi,*flags)==0
