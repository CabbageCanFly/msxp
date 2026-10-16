"""Evaluation plumbing uses synthetic inputs, never private video or glyph assets."""

import importlib
from pathlib import Path
from types import SimpleNamespace

from PIL import Image
import pytest

from exp_tracker.models import Region


@pytest.fixture
def evaluation(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / 'tools'))
    return importlib.import_module('evaluate_cross_stream')


def candidate(x):
    return dict(regions=dict(level=Region(x, .70, x+.03, .75),
                             exp=Region(x+.08, .70, x+.15, .75)))


@pytest.mark.parametrize('candidates,expected', [
    ([], 'missing'), ([candidate(.65), candidate(.1)], 'ambiguous'),
    ([candidate(.65)], 'main'), ([candidate(.1)], 'wrong_secondary'),
    ([candidate(.45)], 'wrong_other'), ([dict(regions={})], 'wrong_other'),
])
def test_main_target_is_explicit_not_first_or_largest(evaluation, candidates, expected):
    assert evaluation.target_category(candidates, (600, 400, 1000, 500),
                                      (0, 200, 400, 500), (1000, 600)) == expected


def test_unknown_labels_are_unscored_not_errors_or_inferred(evaluation):
    result = dict(exp=123, percentage=12.34, status='candidate')
    expected = dict(level=None, current_exp=123, percentage=None)
    metrics = evaluation.provisional_metrics(result, expected, dict(tesseract=40, pixel=None))
    assert metrics == dict(exp='matches_provisional', percentage='unscored',
                           complete_exp='unscored', complete_tesseract='unscored', complete_pixel='unscored')


def test_wrong_level_cannot_be_hidden_by_a_correct_pair(evaluation):
    metrics = evaluation.provisional_metrics(dict(exp=123, percentage=12.34, status='candidate'),
                dict(level=8, current_exp=123, percentage=12.34), dict(tesseract=3, pixel=None))
    assert metrics['complete_exp'] == 'matches_provisional'
    assert metrics['complete_tesseract'] == 'mismatch_provisional'
    assert metrics['complete_pixel'] == 'unavailable'


def test_partial_exp_is_not_a_complete_observation(evaluation):
    metrics = evaluation.provisional_metrics(dict(exp=123, percentage=None, status='unavailable'),
                dict(level=8, current_exp=123, percentage=12.34), dict(tesseract=8, pixel=8))
    assert metrics['exp'] == 'matches_provisional'
    assert metrics['complete_exp'] == metrics['complete_pixel'] == 'unavailable'


def test_sparse_timestamps_cover_video_without_exhaustive_decode(evaluation):
    times = evaluation.sample_times(3600.03, 45)
    assert len(times) == len(set(times)) == 45
    assert times[0] == 0 and times[-1] == 3599.03
    assert all(81 < b-a < 83 for a,b in zip(times, times[1:]))
    with pytest.raises(ValueError):
        evaluation.sample_times(3600, 1)


def test_prepare_never_overwrites_annotations(evaluation, tmp_path):
    (tmp_path/'manifest.json').write_text('preserve me')
    with pytest.raises(ValueError, match='overwrite'):
        evaluation.prepare(SimpleNamespace(directory=tmp_path))
    assert (tmp_path/'manifest.json').read_text() == 'preserve me'


def test_ffmpeg_metadata_fallback(evaluation, tmp_path, monkeypatch):
    video = tmp_path/'synthetic.mp4'
    video.write_bytes(b'only a stat fixture')
    stderr = b'Duration: 01:02:03.45, start: 0\nVideo: h264 (High), yuv420p(tv, progressive), 1920x1080 [SAR 1:1], 5000 kb/s, 60 fps'
    monkeypatch.setattr(evaluation.subprocess, 'run', lambda *a, **kw: SimpleNamespace(stderr=stderr))
    info = evaluation.probe(video)
    assert info['duration_seconds'] == 3723.45
    assert (info['width'], info['height'], info['fps']) == (1920, 1080, 60)


def test_contact_sheets_respect_per_frame_geometry(evaluation, tmp_path):
    image = Image.new('RGB', (100, 50), 'black')
    image.paste('red', (40, 0, 45, 5))
    image.paste('green', (50, 0, 55, 5))
    image.save(tmp_path/'frame.png')
    row = dict(id='synthetic/0', seconds=0, frame='frame.png', hud_box=(40, 0, 90, 20),
               field_boxes=dict(level=(40, 0, 45, 5), exp=(50, 0, 55, 5)))
    manifest = dict(examples=[row], hud_box=(0, 0, 40, 20),
                    field_boxes=dict(level=(0, 0, 5, 5), exp=(10, 0, 15, 5)))
    evaluation.save_sheets(tmp_path, manifest)
    with Image.open(tmp_path/'hud-01.png') as sheet:
        assert sheet.getpixel((351, 109)) == (0, 128, 0)
        assert sheet.getpixel((11, 109)) == (255, 0, 0)
