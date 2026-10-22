"""Synthetic credentials only; Streamlink checks here never open a stream."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

from exp_tracker import streamlink_playback as playback, twitch_auth
from exp_tracker.video import Source


@pytest.fixture(autouse=True)
def private_credentials(tmp_path, monkeypatch):
    monkeypatch.setattr(twitch_auth, 'DEFAULT_ENV_FILE', tmp_path / '.env')
    monkeypatch.delenv('TWITCH_PLAYBACK_TOKEN', raising=False)


def test_dotenv_token_and_environment_precedence(monkeypatch):
    twitch_auth.DEFAULT_ENV_FILE.write_text('TWITCH_CLIENT_SECRET="unrelated bad value"\nTWITCH_PLAYBACK_TOKEN=fileToken123\n')
    assert playback.playback_token() == 'fileToken123'
    assert Source('twitch', 'example').streamlink_command()[2] == 'exp_tracker.streamlink_playback'
    assert 'TWITCH_PLAYBACK_TOKEN' not in os.environ
    monkeypatch.setenv('TWITCH_PLAYBACK_TOKEN', 'environmentToken456')
    assert playback.playback_token() == 'environmentToken456'
    monkeypatch.setenv('TWITCH_PLAYBACK_TOKEN', '')
    twitch_auth.DEFAULT_ENV_FILE.write_bytes(b'\xff')
    assert playback.playback_token() == ''
    assert Source('twitch', 'example').streamlink_command()[2] == 'streamlink'


@pytest.mark.parametrize('token', ['OAuth secret123', 'secret\nheader', 'abc=def', 'a'*4097])
def test_invalid_token_fails_before_capture_without_exposing_it(token, monkeypatch):
    monkeypatch.setenv('TWITCH_PLAYBACK_TOKEN', token)
    with pytest.raises(ValueError) as error:
        Source('twitch', 'example').streamlink_command()
    assert token not in str(error.value)
    assert Source('hls', 'https://example.test/live').streamlink_command()[2] == 'streamlink'


@pytest.mark.parametrize('exit_error', [False, True])
def test_private_config_is_removed_even_when_streamlink_exits(monkeypatch, exit_error):
    cli = pytest.importorskip('streamlink_cli.main')
    parser_module = pytest.importorskip('streamlink_cli.argparser')
    monkeypatch.setenv('TWITCH_PLAYBACK_TOKEN', 'syntheticToken123')
    original = ['streamlink', '--no-config', '--loglevel', 'error']
    monkeypatch.setattr(sys, 'argv', original)
    paths = []
    def run():
        path = Path(sys.argv[1][1:]);paths.append(path)
        assert path.read_text() == 'twitch-api-header=Authorization=OAuth syntheticToken123\n'
        if os.name != 'nt':
            assert path.stat().st_mode & 0o777 == 0o600
            assert path.parent.stat().st_mode & 0o777 == 0o700
        assert 'syntheticToken123' not in ' '.join(sys.argv)
        parser = parser_module.ArgumentParser(fromfile_prefix_chars='@')
        parser.add_argument('--twitch-api-header')
        args, _ = parser.parse_known_args(sys.argv[1:])
        assert args.twitch_api_header == 'Authorization=OAuth syntheticToken123'
        if exit_error:raise SystemExit(7)
        return 0
    monkeypatch.setattr(cli, 'main', run)
    if exit_error:
        with pytest.raises(SystemExit, match='7'):playback.main()
    else:
        assert playback.main() == 0
    assert sys.argv is original and paths
    assert not paths[0].parent.exists()


def test_real_streamlink_accepts_authenticated_command_offline(monkeypatch):
    pytest.importorskip('streamlink_cli.main')
    monkeypatch.setenv('TWITCH_PLAYBACK_TOKEN', 'syntheticToken123')
    command = Source('twitch', 'example').streamlink_command()
    assert 'syntheticToken123' not in ' '.join(command)
    assert '--no-config' in command and '--no-plugin-cache' in command and '--no-plugin-sideloading' in command
    result = subprocess.run([*command[:-2], '--can-handle-url-no-redirect', command[-2]],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert 'syntheticToken123' not in result.stdout + result.stderr


def test_anonymous_launcher_creates_no_temporary_config(monkeypatch):
    cli = pytest.importorskip('streamlink_cli.main')
    monkeypatch.setenv('TWITCH_PLAYBACK_TOKEN', '')
    monkeypatch.setattr(cli, 'main', lambda: 0)
    monkeypatch.setattr(playback, 'TemporaryDirectory', lambda **kwargs: pytest.fail('anonymous playback needs no config'))
    assert playback.main() == 0
