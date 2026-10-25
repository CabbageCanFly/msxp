"""Startup research stays offline, bounded and separate from capture."""
import importlib
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


@pytest.fixture
def startup(monkeypatch):
    monkeypatch.syspath_prepend(str(Path('tools').resolve()))
    return importlib.import_module('benchmark_streamlink_startup')


@pytest.mark.parametrize('count',['0','21'])
def test_probe_count_is_bounded_before_creating_processes(startup,count):
    with pytest.raises(SystemExit) as error:startup.main(['--count',count])
    assert error.value.code==2


def test_unsupported_platform_is_an_explicit_error(startup,monkeypatch,capsys):
    monkeypatch.setattr(startup.sys,'platform','win32')
    with pytest.raises(SystemExit) as error:startup.main([])
    assert error.value.code==2 and 'requires Linux' in capsys.readouterr().err


def test_probe_restores_stdout_and_argv_after_cli_exit(startup,monkeypatch):
    sent=[];closed=[];original_stdout=sys.stdout;original_argv=sys.argv
    def cli():
        assert sys.argv==['streamlink',*startup.PROBE]
        assert '--can-handle-url-no-redirect' in sys.argv
        assert '--no-config' in sys.argv and '--no-plugin-cache' in sys.argv
        assert '--no-plugin-sideloading' in sys.argv
        del sys.stdout
        raise SystemExit(0)
    monkeypatch.setitem(sys.modules,'streamlink_cli.main',SimpleNamespace(main=cli))
    startup.probe(SimpleNamespace(send=sent.append,close=lambda:closed.append(True)))
    assert sent[0]['code']==0 and sent[0]['cpu_seconds']>=0 and closed==[True]
    assert sys.stdout is original_stdout and sys.argv is original_argv


def test_probe_timeout_kills_a_hung_child_and_closes_pipes(startup):
    actions=[]
    class Pipe:
        def close(self):actions.append('close_pipe')
        def poll(self,timeout):return False
    class Process:
        pid=123
        alive=True
        def start(self):actions.append('start')
        def is_alive(self):return self.alive
        def terminate(self):actions.append('terminate')
        def join(self,timeout):actions.append('join')
        def kill(self):actions.append('kill');self.alive=False
        def close(self):actions.append('close_process')
    context=SimpleNamespace(Pipe=lambda **_: (Pipe(),Pipe()),Process=lambda **_:Process())
    with pytest.raises(RuntimeError,match='timed out'):startup.warm_attempt(context,timeout=.01)
    assert 'terminate' in actions and 'kill' in actions and actions[-1]=='close_process'
    assert actions.count('close_pipe')==3
