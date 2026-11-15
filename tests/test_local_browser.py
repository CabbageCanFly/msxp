"""Browser tracker checks: synthetic Node tests and optional lossless Safari captures."""
import gzip
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

from PIL import Image
import pytest

from exp_tracker.msxp import tesseract

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'samples/safari'
MANIFEST = FIXTURES / 'manifest.json'


@pytest.fixture(scope='module')
def node():
    executable = shutil.which('node')
    if not executable:pytest.skip('Node.js is needed for browser tracker tests')
    version = subprocess.check_output([executable, '--version'], text=True).strip()
    if int(version.lstrip('v').split('.')[0]) < 18:pytest.skip('Browser tracker tests need Node.js 18 or newer')
    return executable


def test_browser_tracker_synthetic_regressions(node):
    result = subprocess.run([node, '--test', 'tools/local-tracker.test.mjs'], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr


def cases(kind):
    if not MANIFEST.is_file():
        return [pytest.param(None, id='private-safari-captures', marks=pytest.mark.skip(reason='Run msxp test-data to restore Safari captures'))]
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
    assert manifest['version'] == 1
    return [pytest.param(c, id=c['id']) for c in manifest[kind]] if kind == 'pickups' else [pytest.param(manifest[kind], id='twelve-hud-captures')]


@pytest.fixture(scope='module')
def ocr(tmp_path_factory):
    executable = tesseract()
    if not executable:pytest.skip('Tesseract is needed for Safari OCR replay (msxp install)')
    directory = tmp_path_factory.mktemp('safari-tessdata')
    with gzip.open(ROOT / 'src/exp_tracker/web/local/vendor/eng.traineddata.gz', 'rb') as incoming:
        with (directory / 'eng.traineddata').open('wb') as outgoing:shutil.copyfileobj(incoming, outgoing)
    return {'tesseract': executable, 'tessdata': str(directory)}


def rgba(source, destination):
    with Image.open(source) as image:
        size = image.size
        with destination.open('ab') as output:output.write(image.convert('RGBA').tobytes())
    return size


def replay(node, tmp_path, spec, ocr):
    path = tmp_path / 'replay.json'
    path.write_text(json.dumps({**spec, **ocr}), encoding='utf-8')
    result = subprocess.run([node, str(ROOT / 'tools/replay_local_safari.mjs'), str(path)], cwd=ROOT,
                            env={**os.environ, 'OMP_THREAD_LIMIT': '1'}, capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.samples
@pytest.mark.ocr
@pytest.mark.parametrize('captures', cases('hud'))
def test_safari_hud_replay(node, ocr, tmp_path, captures):
    decoded = []
    for c in captures:
        path = tmp_path / (c['id'] + '.rgba')
        assert rgba(FIXTURES / c['path'], path) == (c['width'], c['height'])
        decoded.append({**c, 'rgba': str(path)})
    replay(node, tmp_path, {'kind': 'hud', 'cases': decoded}, ocr)


@pytest.mark.samples
@pytest.mark.ocr
@pytest.mark.parametrize('clip', cases('pickups'))
def test_safari_pickup_replay(node, ocr, tmp_path, clip):
    with tarfile.open(FIXTURES / clip['path']) as archive:
        index = json.load(archive.extractfile('index.json'))
        pngs = archive.extractfile('frames.bin').read()
    assert len(index['frames']) == clip['frames']
    width, height = index['region']['w'], index['region']['h']
    path = tmp_path / 'frames.rgba'
    for frame in index['frames']:
        start, size = frame['offset'], frame['size']
        assert 0 <= start < start + size <= len(pngs)
        assert rgba(BytesIO(pngs[start:start + size]), path) == (width, height)
    replay(node, tmp_path, {'kind': 'pickups', **clip, 'index': index, 'rgba': str(path), 'width': width, 'height': height}, ocr)
