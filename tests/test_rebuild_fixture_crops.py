"""Fixture crops are recreatable from their recording: build, verify pixel-identical, detect tampering."""
import json
from pathlib import Path
import shutil
import subprocess
import sys

from PIL import Image
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import rebuild_fixture_crops as rebuild


@pytest.fixture
def manifest(tmp_path):
    if not shutil.which('ffmpeg'):pytest.skip('Optional FFmpeg integration')
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i', 'testsrc=size=320x180:rate=10:duration=3',
                    '-pix_fmt', 'yuv420p', str(tmp_path / 'synthetic.mp4')], check=True, timeout=60)
    path = tmp_path / 'labels' / 'manifest.json';path.parent.mkdir()
    path.write_text(json.dumps(dict(video='../synthetic.mp4', crop_root='crops', boxes=dict(exp=[10, 10, 90, 30], level=[0, 0, 20, 20]),
        examples=[dict(id='run/0', seconds=0), dict(id='run/1500', seconds=1.5, field_boxes=dict(exp=[100, 50, 200, 80]))])))
    return path


def test_crops_are_built_from_the_recording_then_verified_pixel_for_pixel(manifest):
    assert rebuild.rebuild(manifest, say=lambda line: None)['created'] == 3
    crops = manifest.parent / 'crops/run-crops'
    with Image.open(crops / '1500/exp-crop.png') as crop:assert crop.size == (100, 30)  # The example's own boxes win.
    assert not (crops / '1500/level-crop.png').exists()
    assert rebuild.rebuild(manifest, say=lambda line: None)['created'] == 0  # Never overwrites.
    assert rebuild.rebuild(manifest, check=True, say=lambda line: None) == dict(created=0, identical=3, different=0, missing=0)
    with Image.open(crops / '0000/exp-crop.png') as crop:crop.rotate(180).save(crops / '0000/exp-crop.png')
    seen = []
    assert rebuild.rebuild(manifest, check=True, say=seen.append)['different'] == 1 and 'different: run/0 exp' in seen
    assert rebuild.main([str(manifest), '--check']) == 1


def test_lossless_frames_rebuild_identical_crops_without_the_recording(manifest, monkeypatch):
    data = json.loads(manifest.read_text())
    video = manifest.parent / data['video']
    assert rebuild.rebuild(manifest, say=lambda _: None)['created'] == 3
    frames = video.parent / 'frames';frames.mkdir()
    for example in data['examples']:
        # An integer timestamp also matches a manifest written with a trailing .0.
        seconds = example['seconds']
        rebuild.frame_at(video, seconds).save(frames / f'{video.stem}-{seconds:g}s.webp', lossless=True)
    data['examples'][0]['seconds'] = 0.0
    manifest.write_text(json.dumps(data))
    video.unlink()
    monkeypatch.setattr(rebuild.subprocess, 'run', lambda *a, **k: pytest.fail('Recording fallback attempted'))
    assert rebuild.rebuild(manifest, check=True, say=lambda _: None) == dict(created=0, identical=3, different=0, missing=0)
    crop = manifest.parent / 'crops/run-crops/0000/exp-crop.png'
    crop.unlink()
    assert rebuild.rebuild(manifest, say=lambda _: None)['created'] == 1
    assert rebuild.rebuild(manifest, check=True, say=lambda _: None)['identical'] == 3
    (frames / f'{video.stem}-0s.webp').unlink()
    with pytest.raises(ValueError, match='source frame or recording not found'):
        rebuild.rebuild(manifest, check=True, say=lambda _: None)
