"""Synthetic name/ownership boundaries; no private footage or neural dependency."""

import importlib.util
import json
from pathlib import Path
import sys

from PIL import Image
import pytest

TOOLS = Path(__file__).parents[1] / 'tools'
sys.path.insert(0, str(TOOLS))
SPEC = importlib.util.spec_from_file_location('character_name_ocr', TOOLS / 'character_name_ocr.py')
names = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(names)


def attempt(text, score=.95):
    return dict(engine='synthetic', text=text, score=score)


def frame(text='PlayerOne', digest='one', ownership='status_panel_candidate', layouts=1):
    return dict(pixel_sha256=digest, layout_count=layouts,
                candidates=[names.candidate(dict(box=[0, 0, 80, 15], ownership=ownership), [attempt(text)])])


@pytest.mark.parametrize('text', ['A', 'Some Name', 'Player!', 'Player |', '123456', 'a' * 13, '玩家', None])
def test_rejects_uncertain_or_unsupported_name_strings(text):
    assert names.name_text(text) is None


def test_preserves_case_digits_and_conflicts_without_spelling_repair():
    assert names.name_text('  Player1  ') == 'Player1'
    item = names.candidate(dict(box=[0, 0, 80, 15], ownership='unverified_region'),
                           [attempt('Player1'), attempt('PIayer1')])
    assert item['status'] == 'ambiguous'
    assert item['names'] == ['PIayer1', 'Player1']
    assert names.candidate({}, [attempt('Player1', .49)])['names'] == []


def test_distinct_pixels_required_and_nearby_stable_names_have_no_owner():
    assert names.summarize([frame(), frame()])['status'] == 'unknown'
    assert names.summarize([frame(ownership='unverified_region'),
                            frame(digest='two', ownership='unverified_region')])['proposed_name'] is None
    result = names.summarize([frame(), frame(digest='two')])
    assert result['status'] == 'review_required'
    assert result['proposed_name'] == 'PlayerOne'
    assert result['trusted'] is False


def test_multiple_huds_and_switches_abstain_even_when_one_name_wins():
    assert names.summarize([frame(layouts=2), frame(digest='two')])['status'] == 'ambiguous'
    assert names.summarize([frame(), frame(digest='two'), frame('Other', 'three')])['status'] == 'ambiguous'
    conflicting = frame(digest='three')
    conflicting['candidates'][0]['names'].append('Other')
    assert names.summarize([frame(), frame(digest='two'), conflicting])['proposed_name'] is None


def test_missing_latest_owner_evidence_does_not_propose_a_stale_name():
    missing = dict(pixel_sha256='black', layout_count=0, candidates=[])
    result = names.summarize([frame(), frame(digest='two'), missing])
    assert result['status'] == 'unknown'
    assert result['proposed_name'] is None
    assert result['distinct_frame_support'] == {'PlayerOne': 2}


def test_geometry_relative_to_hud_and_all_candidates_retained(monkeypatch):
    layouts = [dict(anchors=dict(hp=dict(x=300, y=100)), anchor_step=100),
               dict(anchors=dict(hp=dict(x=600, y=200)), anchor_step=50)]
    monkeypatch.setattr(names, 'locate', lambda image: layouts)
    regions, count = names.name_regions(Image.new('RGB', (800, 400)))
    assert count == 2
    assert regions[0]['box'] == [172, 110, 294, 126]
    assert len(regions) == 2
    layouts[1]['anchors']['hp']['y'] = 399
    assert names.name_regions(Image.new('RGB', (800, 400)))[1] == 2


@pytest.mark.parametrize('height,band',[(14,1),(25,2),(40,3)])
def test_name_cleanup_removes_job_remnants_without_resizing_or_touching_name_pixels(height,band):
    image=Image.new('RGB',(120,height),(40,50,60))
    image.putpixel((50,0),(230,230,230))
    image.putpixel((20,band),(210,210,210))
    image.putpixel((40,height-1),(200,200,200))
    cleaned=names.clean_name_crop(image)
    assert cleaned.size==image.size
    assert all(cleaned.getpixel((50,y))==(40,50,60) for y in range(band))
    assert cleaned.crop((0,band,120,height)).tobytes()==image.crop((0,band,120,height)).tobytes()
    assert image.getpixel((50,0))==(230,230,230)


@pytest.mark.parametrize('manual',[False,True])
def test_only_automatic_status_name_regions_receive_job_remnant_cleanup(monkeypatch,manual):
    image=Image.new('RGB',(100,50),(40,50,60));image.putpixel((50,0),(230,230,230));seen=[]
    monkeypatch.setattr(names,'name_regions',lambda _:(
        [dict(box=[0,0,80,25],ownership='status_panel_candidate')],1))
    def read(crop,box):seen.append(crop.getpixel((50,0)));return attempt('PlayerOne')
    monkeypatch.setattr(names,'tesseract',read)
    names.inspect_frame(image,'synthetic',region=[0,0,80,25] if manual else None,owner_field=manual)
    assert seen==[(230,230,230) if manual else (40,50,60)]


@pytest.mark.parametrize('height', [126, 125])
def test_automatic_name_region_tolerates_one_pixel_bottom_overflow(height):
    layout = dict(anchors=dict(hp=dict(x=300, y=100)), anchor_step=100)
    region = names.name_region(layout, (800, height))
    assert region['box'] == [172, 110, 294, height]
    image = Image.new('RGB', (800, height))
    image.putpixel((200, height - 1), (255, 255, 255))
    crop = image.crop(region['box'])
    assert crop.getpixel((28, crop.height - 1)) == (255, 255, 255)


@pytest.mark.parametrize('size,hp', [
    ((800, 124), dict(x=300, y=100)),  # Two pixels below the frame.
    ((800, 111), dict(x=300, y=100)),  # Substantial truncation.
    ((800, 400), dict(x=127, y=100)),  # One pixel past the left edge.
    ((293, 400), dict(x=300, y=100)),  # One pixel past the right edge.
    ((800, 400), dict(x=300, y=-11)),  # One pixel past the top edge.
])
def test_automatic_name_region_rejects_larger_or_other_edge_overflow(size, hp):
    with pytest.raises(ValueError):
        names.name_region(dict(anchors=dict(hp=hp), anchor_step=100), size)


@pytest.mark.parametrize('box', [[-1, 0, 10, 10], [10, 0, 10, 10], [0, 0, 101, 10],
                                 [0, 0, 10, 51], [0, 1, 2], [0, 0, 1.5, 2]])
def test_invalid_regions_rejected(box):
    with pytest.raises(ValueError):
        names.checked_box(box, (100, 50))


def test_ocr_error_is_preserved_and_does_not_create_a_name(monkeypatch):
    def fail(*args):
        raise RuntimeError('unavailable')
    monkeypatch.setattr(names, 'tesseract', fail)
    result = names.inspect_frame(Image.new('RGB', (100, 50)), 'synthetic', region=[0, 0, 80, 15])
    item = result['candidates'][0]
    assert item['names'] == []
    assert item['attempts'][0]['error'] == 'RuntimeError'
    assert item['ownership'] == 'unverified_region'


def test_cli_image_review_and_duplicate_pixels_do_not_confirm_owner(tmp_path, monkeypatch):
    path = tmp_path / 'generated.png'
    Image.new('RGB', (100, 50), 'black').save(path)
    monkeypatch.setattr(names, 'configure_tesseract', lambda: None)
    monkeypatch.setattr(names, 'tesseract', lambda *args: attempt('PlayerOne'))
    output = tmp_path / 'review.json'
    assert names.main([str(path), str(path), '--region', '0,0,80,15', '--owner-field',
                       '--output', str(output)]) == 0
    report = json.loads(output.read_text())
    assert report['summary']['status'] == 'unknown'
    assert output.with_suffix('.csv').is_file()
    assert output.with_suffix('.png').is_file()


def test_local_video_path_uses_existing_extractor(tmp_path, monkeypatch):
    video = tmp_path / 'local.mp4'
    video.touch()
    calls = []
    def extract(path, seconds):
        calls.append((path, seconds))
        return Image.new('RGB', (100, 50), (round(seconds), 0, 0))
    monkeypatch.setattr(names, 'frame_at', extract)
    monkeypatch.setattr(names, 'configure_tesseract', lambda: None)
    monkeypatch.setattr(names, 'tesseract', lambda *args: attempt('PlayerOne'))
    output = tmp_path / 'video.json'
    names.main(['--video', str(video), '--times', '10,0', '--region', '0,0,80,15',
                '--owner-field', '--output', str(output)])
    assert calls == [(video.resolve(), 0), (video.resolve(), 10)]
    assert json.loads(output.read_text())['summary']['proposed_name'] == 'PlayerOne'


@pytest.mark.parametrize('args', [[], ['--video', 'https://example.com/file.mp4', '--times', '0'],
                                 ['--video', 'local.mp4', '--times', 'nan'],
                                 ['--owner-field', 'missing.png'],
                                 ['missing.png', '--times', '0']])
def test_invalid_cli_inputs_fail_without_acquiring_network(args):
    with pytest.raises(SystemExit) as error:
        names.main(args)
    assert error.value.code == 1
