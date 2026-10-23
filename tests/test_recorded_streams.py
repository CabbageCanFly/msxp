"""The live reader (shadow_capture.analyze: localization, Tesseract, RapidOCR) on labelled frames of real recordings.

Frames are decoded straight from the private recordings in samples/ (never in Git), so this needs no saved crops:
anything it checks can be recreated from the videos. Labels and expected outcomes are in data/recorded_frames.json.
It never accepts a wrong EXP pair, and frames read correctly on 2026-10-23 must still read correctly; a rejected
frame that now reads correctly is an improvement, not a failure. Every 5th frame runs by default (about 20 s on
8 workers); MSXP_ALL_FRAMES=1 runs all 206.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]
DATA = json.loads((Path(__file__).parent / 'data/recorded_frames.json').read_text(encoding='utf-8'))
OCR = ROOT / 'private/rapidocr/.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
pytestmark = [pytest.mark.samples, pytest.mark.ocr]


def frames():
    chosen = [f for i, f in enumerate(DATA['frames']) if os.environ.get('MSXP_ALL_FRAMES') or i % 5 == 0 or f['expect'] == 'misread']
    known = pytest.mark.xfail(strict=True, reason='Known misread: a 9 read as an 8 in a tiny HUD font; '
                              'the EXP table contradicts it (1,241 / 1,242 = 99.92%)')
    return [pytest.param(f, marks=[known] if f['expect'] == 'misread' else [], id=f"{Path(f['video']).stem}-{f['seconds']}s")
            for f in chosen]


@pytest.fixture(scope='module')
def live():
    if not OCR.is_file() or not shutil.which('ffmpeg'):
        pytest.skip('Private OCR environment or FFmpeg absent (msxp install)')
    sys.path.insert(0, str(ROOT / 'tools'))
    import shadow_capture
    table = json.loads((ROOT / 'src/exp_tracker/data/community-exp-v2.json').read_text(encoding='utf-8'))
    return shadow_capture, {int(level): value for level, value in table['to_next'].items()}


def frame_at(video, seconds):
    from exp_tracker.video import Frame
    png = subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-ss', str(seconds), '-i', str(video), '-frames:v', '1',
                          '-f', 'image2pipe', '-c:v', 'png', 'pipe:1'], check=True, capture_output=True, timeout=120).stdout
    return Frame(png=png, sequence=0, arrived_monotonic=time.monotonic(), received_at=datetime.now(timezone.utc).isoformat())


@pytest.mark.parametrize('item', frames())
def test_live_reader_never_accepts_a_wrong_pair_and_keeps_its_coverage(live, item):
    video = ROOT / item['video']
    if not video.is_file() or video.stat().st_size != DATA['videos'][item['video']]:
        pytest.skip('Private recording absent or a different file')
    shadow, requirements = live
    result = shadow.analyze(frame_at(video, item['seconds']), requirements,
                            lambda crop: shadow.neural_line(crop, OCR, 20), max_age=600)
    got, label = result.get('candidate'), [item['exp'], item['percentage']]
    assert got is None or got == label, f'accepted a wrong EXP pair {got}; label {label}'
    if item['expect'] == 'read':
        assert got == label, f"no longer read ({result['status']}: {result['reasons']}); label {label}"
