import gzip
import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
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
