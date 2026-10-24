import gzip
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import restore_test_data as recovery
from restore_test_data import restore


def fixture(tmp_path, *, compressed=False, target='private/test-fixtures/runs/a.jsonl'):
    data = tmp_path / 'data';data.mkdir()
    content = b'{"sequence":1}\n'
    path = 'a.jsonl.gz' if compressed else 'a.jsonl'
    (data / path).write_bytes(gzip.compress(content) if compressed else content)
    manifest = dict(files=[dict(path=path, target=target, size=len(content), sha256=hashlib.sha256(content).hexdigest(), gzip=compressed)])
    (data / 'manifest.json').write_text(json.dumps(manifest))
    return data, manifest, content


@pytest.mark.parametrize('compressed', [False, True])
def test_restoration_verifies_original_bytes_and_is_repeatable(tmp_path, compressed):
    data, _, content = fixture(tmp_path, compressed=compressed)
    target = tmp_path / 'project'
    assert restore(data, target) == dict(verified=1, restored=1, installed=1)
    assert (target / 'private/test-fixtures/runs/a.jsonl').read_bytes() == content
    assert restore(data, target, check=True) == dict(verified=1, restored=0, installed=1)
    assert restore(data, target)['restored'] == 0


def test_corrupt_sources_and_conflicting_destinations_do_not_get_overwritten(tmp_path):
    data, manifest, _ = fixture(tmp_path)
    target = tmp_path / 'project';target.mkdir()
    path = target / manifest['files'][0]['target'];path.parent.mkdir(parents=True);path.write_bytes(b'my local changes')
    with pytest.raises(ValueError, match='overwrite different file'):restore(data, target)
    assert path.read_bytes() == b'my local changes'
    (data / 'a.jsonl').write_bytes(b'bad')
    with pytest.raises(ValueError, match='checksum mismatch'):restore(data, target)
    assert path.read_bytes() == b'my local changes'


@pytest.mark.parametrize('field,value', [('path', '../outside'), ('target', 'private/../../outside'),
    ('target', 'private/escape\\file'), ('target', 'private/C:/outside'), ('target', 'src/app.py'), ('target', '')])
def test_manifest_paths_cannot_escape_or_replace_source_code(tmp_path, field, value):
    data, manifest, _ = fixture(tmp_path)
    manifest['files'][0][field] = value
    (data / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError):restore(data, tmp_path / 'project')
    assert not (tmp_path / 'project').exists()


def test_check_does_not_create_missing_files_and_gzip_size_is_bounded(tmp_path):
    data, manifest, _ = fixture(tmp_path, compressed=True)
    target = tmp_path / 'project'
    with pytest.raises(ValueError, match='missing'):restore(data, target, check=True)
    assert not target.exists()
    manifest['files'][0]['size'] = 1
    (data / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='exceeds its recorded size'):restore(data, target)
    assert not target.exists()


@pytest.fixture
def data_git_repo(tmp_path):
    if not shutil.which('git'):pytest.skip('Git is needed for private fixture downloads')
    source = tmp_path / 'source';source.mkdir()
    def git(*args):
        return subprocess.run(['git', '-C', str(source), *args], check=True, capture_output=True).stdout
    git('init', '-q')
    git('config', 'user.name', 'Fixture test');git('config', 'user.email', 'fixture@example.invalid')
    git('config', 'core.autocrlf', 'input')
    git('config', 'uploadpack.allowFilter', 'true');git('config', 'uploadpack.allowAnySHA1InWant', 'true')
    content = b'{"sequence":1}\n'
    (source / 'frame[1].jsonl.gz').write_bytes(gzip.compress(content))
    plain = b'{\r\n "n":1\n}\r\n';(source / 'plain.json').write_bytes(plain)
    (source / '.gitattributes').write_text('* -text\n')
    (source / 'research.bin').write_bytes(bytes(range(256)) * 4096)
    manifest = dict(files=[dict(path='frame[1].jsonl.gz', target='private/test-fixtures/run.jsonl',
        size=len(content), sha256=hashlib.sha256(content).hexdigest(), gzip=True),
        dict(path='plain.json', target='private/test-fixtures/plain.json', size=len(plain), sha256=hashlib.sha256(plain).hexdigest()),
        dict(path='research.bin', target=None, size=1048576, sha256='not-used-for-download')])
    (source / 'manifest.json').write_text(json.dumps(manifest))
    git('add', '.');git('-c', 'commit.gpgsign=false', 'commit', '-qm', 'Synthetic fixtures')
    return source, git, manifest, content


def test_download_fetches_only_required_blobs_and_leaves_no_clone(tmp_path, monkeypatch, data_git_repo):
    source, git, _, content = data_git_repo
    required = git('rev-parse', 'HEAD:frame[1].jsonl.gz').strip()
    plain = git('rev-parse', 'HEAD:plain.json').strip()
    research = git('rev-parse', 'HEAD:research.bin').strip()
    scratch = tmp_path / 'scratch';scratch.mkdir();monkeypatch.setattr(tempfile, 'tempdir', str(scratch))
    actual, fetches = subprocess.run, []
    def spy(command, **kwargs):
        if 'fetch' in command:fetches.append(kwargs['input'])
        return actual(command, **kwargs)
    monkeypatch.setattr(recovery.subprocess, 'run', spy)
    target = tmp_path / 'project'
    assert recovery.download(target, repository=source.as_uri()) == dict(verified=2, restored=2, installed=2)
    assert fetches == [b'\n'.join(sorted([required, plain])) + b'\n'] and research not in fetches[0]
    path = target / 'private/test-fixtures/run.jsonl'
    assert path.read_bytes() == content and not (target / 'research.bin').exists()
    assert (target / 'private/test-fixtures/plain.json').read_bytes() == b'{\r\n "n":1\n}\r\n'
    assert not list(scratch.iterdir())
    assert recovery.download(target, repository=source.as_uri(), check=True)['restored'] == 0
    assert len(fetches) == 1
    with pytest.raises(ValueError, match='missing'):
        recovery.download(tmp_path / 'absent', repository=source.as_uri(), check=True)
    assert len(fetches) == 1 and not (tmp_path / 'absent').exists()
    path.write_bytes(b'local changes')
    with pytest.raises(ValueError, match='overwrite different'):
        recovery.download(target, repository=source.as_uri())
    assert path.read_bytes() == b'local changes' and len(fetches) == 1
    assert not list(scratch.iterdir())


def test_incomplete_remote_manifest_cannot_silently_skip_a_fixture(tmp_path, data_git_repo):
    source, git, manifest, _ = data_git_repo
    manifest['files'].append(dict(path='absent.bin', target='samples/missing.png', size=1, sha256='0' * 64))
    (source / 'manifest.json').write_text(json.dumps(manifest))
    git('add', '.');git('-c', 'commit.gpgsign=false', 'commit', '-qm', 'Missing fixture')
    with pytest.raises(ValueError, match='missing from remote snapshot'):
        recovery.download(tmp_path / 'project', repository=source.as_uri())
    assert not (tmp_path / 'project').exists()
