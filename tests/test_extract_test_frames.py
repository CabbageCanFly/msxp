"""The golden frame set is lossless: frames saved from a recording verify pixel-identical, and tampering is caught."""
import json
from pathlib import Path
import shutil
import subprocess
import sys

from PIL import Image
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import extract_test_frames as extract


def test_frames_are_saved_once_then_verified_against_the_recording(tmp_path, monkeypatch, capsys):
    if not shutil.which('ffmpeg'):pytest.skip('Optional FFmpeg integration')
    (tmp_path / 'samples').mkdir()
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i', 'testsrc=size=320x180:rate=10:duration=3',
                    '-pix_fmt', 'yuv420p', str(tmp_path / 'samples/clip.mp4')], check=True, timeout=60)
    labels = tmp_path / 'frames.json'
    labels.write_text(json.dumps(dict(frames=[dict(video='samples/clip.mp4', seconds=0.5), dict(video='samples/clip.mp4', seconds=2),
                                              dict(video='samples/absent.mp4', seconds=1)])))
    monkeypatch.setattr(extract, 'ROOT', tmp_path);monkeypatch.setattr(extract, 'FRAMES', labels)
    monkeypatch.setattr(extract, 'OUT', tmp_path / 'samples/frames')
    assert extract.main([]) == 0 and "'written': 2" in capsys.readouterr().out
    assert sorted(p.name for p in (tmp_path / 'samples/frames').iterdir()) == ['clip-0.5s.webp', 'clip-2s.webp']
    assert extract.main([]) == 0 and "'kept': 2" in capsys.readouterr().out  # Never rewrites.
    assert extract.main(['--check']) == 0 and "'identical': 2" in capsys.readouterr().out
    path = tmp_path / 'samples/frames/clip-2s.webp'
    with Image.open(path) as image:image.convert('RGB').rotate(90).save(path, 'WEBP', lossless=True)
    assert extract.main(['--check']) == 1 and "'DIFFERENT': 1" in capsys.readouterr().out
