"""Exercise the opt-in service arguments against disposable, mocked coordinators."""
import importlib
import os
from pathlib import Path
import shlex
from types import SimpleNamespace

import pytest

from exp_tracker import streamer_roster as roster
from exp_tracker.store import Store
from exp_tracker.writer_lock import writer_lease
from tests.test_automatic_adoption import legacy, multi  # noqa: F401
from tests.test_db_streamer_roster import managed, legacy10  # noqa: F401

DEPLOY=Path(__file__).resolve().parents[1]/'deploy'


def commands():
    text=(DEPLOY/'msxp-tracker-roster.conf').read_text().replace('\\\n','')
    return [shlex.split(line.split('=',1)[1])[2:] for line in text.splitlines()
        if line.startswith(('ExecStartPre=','ExecStart=')) and line.split('=',1)[1]]


def arguments(command,path,*,twitch=''):
    env=dict(MSXP_DATABASE=str(path),MSXP_TWITCH_STATUS=twitch,
        MSXP_CAPTURE_LIMITS='--stop-after-seconds 600 --exit-after-capture')
    args=[]
    for token in command:
        if token.startswith('${'):args.append(env[token[2:-1]])
        elif token.startswith('$'):args.extend(shlex.split(env[token[1:]]))
        elif token=='/opt/msxp/app/private/rapidocr/.venv/bin/python':
            args.append(str(path.parent/'rapidocr/.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')))
        else:args.append(token)
    return args


@pytest.fixture
def preflight(managed,monkeypatch):
    module,_,_,path,_=managed
    pools=[]
    def pool(command,workers):
        pools.append(workers)
        return SimpleNamespace(check=lambda:dict(version='test',model_sha256='a'*64),close=lambda:None)
    monkeypatch.setattr(importlib.import_module('resident_tesseract'),'TesseractPool',pool)
    monkeypatch.setattr(module,'available_port',lambda port,**kwargs:None)
    def forbidden(*args,**kwargs):raise AssertionError('Preflight must not connect or capture')
    monkeypatch.setattr(module.shadow,'capture_attempt',forbidden)
    monkeypatch.setattr(module,'create_server',forbidden)
    return module,path,pools


def test_service_is_opt_in_bounded_and_retention_free():
    pre,start=commands()
    assert pre==start+['--check']
    for flag in ('--db-roster','--continuous','--public-only','--stagger-capture','--resident-neural','--resident-tesseract'):
        assert flag in start
    assert start[start.index('--port')+1]=='8765'
    assert start[start.index('--workers')+1]=='6'
    assert start[start.index('--cors-origin')+1]=='https://msxp.pages.dev'
    assert start[start.index('--ocr-python')+1]=='/opt/msxp/app/private/rapidocr/.venv/bin/python'
    assert '--retention-24h' not in start
    text=(DEPLOY/'msxp-tracker-roster.conf').read_text()
    assert '\nExecStart=\n' in text and '\nRestart=no\n' in text
    assert 'Environment="MSXP_CAPTURE_LIMITS=--stop-after-seconds 600 --exit-after-capture"' in text
    base=(DEPLOY/'msxp-tracker.service').read_text()
    assert 'KillSignal=SIGINT' in base and 'KillMode=mixed' in base
    assert '--config private/vps/config.json' in base and '--db-roster' not in base
    assert 'msxp-tracker-roster.conf' not in (DEPLOY/'install-ubuntu.sh').read_text()
    env=(DEPLOY/'msxp-roster.env.example').read_text()
    assert 'MSXP_CAPTURE_LIMITS=--stop-after-seconds 600 --exit-after-capture' in env
    # No coordinator unit can run retention inline, whatever an old env file still sets.
    for unit in ('msxp-tracker.service','msxp-tracker-roster.conf','msxp-tracker-capture-only.conf'):
        text=(DEPLOY/unit).read_text()
        assert '--retention-24h' not in text and 'MSXP_RETENTION' not in text


def test_retention_is_a_separate_opt_in_bounded_pass():
    service=(DEPLOY/'msxp-retention.service').read_text();timer=(DEPLOY/'msxp-retention.timer').read_text()
    start=shlex.split(next(l for l in service.splitlines() if l.startswith('ExecStart=')).split('=',1)[1])
    assert start[1:4]==['-m','exp_tracker.retention','--db'] and '--apply' in start
    assert start[start.index('--log-root')+1]=='${MSXP_LOG_ROOT}' and float(start[start.index('--max-seconds')+1])<=900
    assert 'Type=oneshot' in service and 'User=msxp' in service and 'ProtectSystem=strict' in service
    assert 'PYTHONPATH=/opt/msxp/app/src' in service  # Like msxp-api: `-m exp_tracker...` needs this checkout's src.
    assert 'OnUnitInactiveSec=1h' in timer  # Counted from the end of a pass: passes never overlap.
    assert 'msxp-retention' not in (DEPLOY/'install-ubuntu.sh').read_text()  # Enabling stays a deliberate step.


@pytest.mark.parametrize('twitch',['','--twitch-status'])
def test_service_preflight_preserves_database_and_marker(preflight,twitch):
    module,path,pools=preflight
    marker=path.with_suffix(path.suffix+'.multi-alpha.json');before=marker.read_bytes()
    with Store(path,read_only=True) as store:digest=roster.database_digest(store)
    assert module.main(arguments(commands()[0],path,twitch=twitch))==0
    assert pools==[1]  # Native worker identity only; never capture or neural inference.
    assert marker.read_bytes()==before
    with Store(path,read_only=True) as store:assert roster.database_digest(store)==digest


@pytest.mark.parametrize('guard',['missing_database','missing_marker','unbootstrapped','busy_writer','busy_port'])
def test_service_preflight_refuses_unsafe_start(preflight,monkeypatch,guard):
    module,path,_=preflight;marker=path.with_suffix(path.suffix+'.multi-alpha.json')
    if guard=='missing_database':path.unlink()
    elif guard=='missing_marker':marker.unlink()
    elif guard=='unbootstrapped':
        with Store(path) as store:store.db.execute('DELETE FROM streamer_roster_bootstrap')
    elif guard=='busy_port':
        def busy(*args,**kwargs):raise ValueError('port already in use')
        monkeypatch.setattr(module,'available_port',busy)
    argv=arguments(commands()[0],path)
    if guard=='busy_writer':
        with writer_lease(marker):assert module.main(argv)==1
    else:assert module.main(argv)==1
    if guard=='missing_database':assert not path.exists()


def test_service_preflight_never_migrates_schema10(legacy10):
    module,_,_,path,_=legacy10
    assert module.main(arguments(commands()[0],path))==1
    with Store(path,read_only=True) as store:
        assert store.schema_version==10
        assert not store.db.execute("SELECT 1 FROM sqlite_master WHERE name='streamer_capture'").fetchone()


def test_capture_only_preflight_ignores_api_port_but_checks_exclusive_writer(preflight,tmp_path,monkeypatch):
    module,path,_=preflight
    def occupied(*args,**kwargs):raise AssertionError('Capture-only must not probe the API port')
    monkeypatch.setattr(module,'available_port',occupied)
    runtime=path.parent/'capture-runtime.json'
    argv=['--db-roster',str(path),'--continuous','--capture-only','--runtime-state',str(runtime),'--check']
    assert module.main(argv)==0
    assert not runtime.exists()
    with writer_lease(path.with_suffix(path.suffix+'.multi-alpha.json')):
        assert module.main(argv)==1


@pytest.mark.parametrize('extra',([],['--public-only'],['--twitch-status'],['--cors-origin','https://msxp.pages.dev']))
def test_capture_only_rejects_missing_heartbeat_and_http_options(preflight,extra):
    module,path,_=preflight
    argv=['--db-roster',str(path),'--continuous','--capture-only','--check']
    if extra:argv+=['--runtime-state',str(path.parent/'runtime.json'),*extra]
    assert module.main(argv)==1


def test_capture_only_coexists_with_api_without_starting_a_second_publisher(managed,monkeypatch):
    from exp_tracker.server import create_server
    module,_,_,path,_=managed;runtime=path.parent/'runtime.json'
    def forbidden(*args,**kwargs):raise AssertionError('Capture-only must not create HTTP or probe its port')
    monkeypatch.setattr(module,'create_server',forbidden)
    monkeypatch.setattr(module,'available_port',forbidden)
    actual=module.shadow.capture_attempt;checks=[]
    def capture(*args,**kwargs):
        with pytest.raises(ValueError,match='Another coordinator'):
            with writer_lease(path.with_suffix(path.suffix+'.multi-alpha.json')):pass
        checks.append(True)
        return actual(*args,**kwargs)
    monkeypatch.setattr(module.shadow,'capture_attempt',capture)
    with create_server(path,port=0,public_only=True,runtime_state=runtime) as api:
        listener=api.socket.fileno()
        assert module.main(['--db-roster',str(path),'--continuous','--capture-only',
            '--runtime-state',str(runtime),'--max-attempts','1'])==0
        assert checks and api.socket.fileno()==listener
        api.publisher.settle()
        assert api.publisher.entries and not api.active_run_ids and not api.coordinator_status


def test_split_services_are_opt_in_and_restart_independently():
    api=(DEPLOY/'msxp-api.service').read_text();capture=(DEPLOY/'msxp-tracker-capture-only.conf').read_text()
    assert '-m exp_tracker.server' in api and '--port 8765' in api
    assert '--publication-cache' in api and '--runtime-state' in api and '--public-only' in api
    assert '--cors-origin https://msxp.pages.dev' in api
    assert 'PartOf=' not in api and 'Requires=msxp-tracker' not in api
    assert 'multi_alpha.py' not in api and '--retention-24h' not in api
    for line in capture.replace('\\\n','').splitlines():
        if line.startswith(('ExecStart=','ExecStartPre=')) and line.split('=',1)[1]:
            assert '--capture-only' in line and '--runtime-state' in line
            assert '--public-only' not in line and '--twitch-status' not in line
    installer=(DEPLOY/'install-ubuntu.sh').read_text()
    assert 'msxp-api.service' not in installer and 'msxp-tracker-capture-only.conf' not in installer
