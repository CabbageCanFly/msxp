import json
from pathlib import Path

from PIL import Image, ImageDraw
import pytest

from exp_tracker import badge_digits

ROOT = Path(__file__).resolve().parents[1]


def badge(tiles=2, size=17, margin=4):
    image = Image.new('RGB', (tiles * (size + 1) + 2 * margin, size + 2 * margin), (25, 25, 28))
    draw = ImageDraw.Draw(image)
    for i in range(tiles):
        x = margin + i * (size + 1)
        draw.rectangle((x, margin, x + size - 2, margin + size - 1), fill=(240, 130, 30))
        draw.rectangle((x + size // 4, margin + size // 4, x + size - 2 - size // 4, margin + size - 1 - size // 4),
                       outline=(250, 250, 250), width=2)
    return image


def model(favourite, probability=.99):
    """A stand-in model that scores every tile as `favourite` with the given probability."""
    import math
    bias = [0.] * 10
    bias[favourite] = math.log(probability * 9 / (1 - probability))
    return dict(version=1, grid=12, ink=.45, scale=12, weights=[[0.] * 10 for _ in range(144)] + [bias])


@pytest.fixture
def fake(monkeypatch):
    def use(favourite, probability=.99):
        monkeypatch.setattr(badge_digits, 'model', lambda: model(favourite, probability))
    return use


@pytest.mark.parametrize('tiles,level', [(1, 7), (2, 77)])
def test_each_orange_tile_is_one_digit(fake, tiles, level):
    fake(7)
    got, details = badge_digits.read_badge(badge(tiles))
    assert got == level and details['confidence'] >= badge_digits.GATE


def test_levels_above_200_are_no_level(fake):
    fake(7)
    assert badge_digits.read_badge(badge(3)) == (None, dict(reason='range', text='777'))


def test_an_unsure_tile_reads_nothing(fake):
    fake(7, .8)
    assert badge_digits.read_badge(badge(2)) == (None, dict(reason='unsure', confidence=pytest.approx(.8)))


def test_leading_zero_is_no_level(fake):
    fake(0)
    assert badge_digits.read_badge(badge(2))[1]['reason'] == 'range'


@pytest.mark.parametrize('image,reason', [
    (badge(2).crop((6, 0, 46, 25)), 'clipped'),  # The first tile runs off the crop.
    (badge(2, size=8, margin=2), 'too_small'),
    (Image.new('RGB', (30, 20), (25, 25, 28)), 'no_tiles'),
])
def test_unreadable_badges_are_refused(fake, image, reason):
    fake(7)
    assert badge_digits.read_badge(image) == (None, dict(reason=reason))


def test_a_strip_that_is_no_tile_count_is_refused(fake):
    fake(7)
    image = Image.new('RGB', (60, 25), (25, 25, 28))
    ImageDraw.Draw(image).rectangle((4, 4, 4 + 21, 4 + 16), fill=(240, 130, 30))  # 1.3 tiles wide.
    assert badge_digits.read_badge(image) == (None, dict(reason='tile_count'))


def test_shipped_model_is_valid():
    data = badge_digits.model()
    assert data['version'] == 1 and len(data['weights']) == data['grid'] ** 2 + 1


@pytest.mark.parametrize('folder', ['badge-digits', 'badge-digits-holdout'])  # Training set; never-trained VODs.
def test_shipped_model_reads_checked_badges_without_wrong_levels(folder):
    folder = ROOT / 'private' / folder
    if not (folder / 'labels.json').exists():
        pytest.skip('private badge crops are not restored')
    labels = json.loads((folder / 'labels.json').read_text())['labels']
    wrong, read, readable = [], 0, 0
    for name, level in labels.items():
        got, _ = badge_digits.read_badge(Image.open(folder / 'crops' / name))
        readable += level != 'x'
        if got is not None and level != 'x':
            read += 1
            if str(got) != level: wrong.append((name, level, got))
    assert not wrong
    assert read >= .9 * readable
