"""Private fixtures never leave RAM/disk on this machine; no network access."""

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter
import pytest

from exp_tracker.models import Reading, Region
from exp_tracker.recognition import recognize

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {1: Reading(60, 71441, 5.90), 2: Reading(56, 641122, 65.59)}
pytestmark = [pytest.mark.samples, pytest.mark.ocr]


def sample(number):
    path = ROOT / f"samples/maplestory-classic-stream{number}.png"
    if not path.exists():
        pytest.skip("Private sample is intentionally excluded from public checkout")
    with Image.open(path) as image:
        return image.convert("RGB")


def configuration(number):
    data = json.loads((ROOT / f"configs/stream{number}.json").read_text())
    return {key: Region(*coords) for key, coords in data.items()}


@pytest.mark.parametrize("number", [1, 2])
def test_calibrated_sample(number):
    result = recognize(sample(number), regions=configuration(number))
    assert result.reading == EXPECTED[number]
    assert result.status == "accepted"


@pytest.mark.parametrize("number", [1, 2])
def test_original_samples_with_live_font_profile(number):
    from exp_tracker.glyphs import GlyphProfile
    path = ROOT / "private/ocr-evaluation/glyph-profile.json"
    if not path.exists():
        pytest.skip("Private live-font calibration is intentionally excluded from Git")
    result = recognize(sample(number), regions=configuration(number), glyph_profile=GlyphProfile.load(path))
    assert result.status == "accepted"
    assert result.reading == EXPECTED[number]


@pytest.mark.parametrize("number", [1, 2])
def test_automatic_game_hud_not_tracker_overlay(number):
    result = recognize(sample(number))
    assert result.reading == EXPECTED[number]
    assert result.status in {"accepted", "low_confidence"}
    assert result.regions["exp"].x0 > .5


def test_hidden_hud_does_not_fall_back_to_third_party_overlay():
    image = sample(1)
    ImageDraw.Draw(image).rectangle((image.width * .29, image.height * .965,
                                    image.width * .71, image.height), fill="black")
    assert recognize(image).status == "missing_hud"


def test_obscured_exp_is_unreadable():
    image = sample(2)
    rois = configuration(2)
    ImageDraw.Draw(image).rectangle(rois["exp"].pixels(*image.size), fill="black")
    result = recognize(image, regions=rois)
    assert result.status == "unreadable"
    assert result.reading is None


@pytest.mark.parametrize("size", [(1280, 720), (2560, 1440)])
@pytest.mark.parametrize("number", [1, 2])
def test_resize_must_not_accept_incorrect_values(number, size):
    image = sample(number).resize(size, Image.Resampling.LANCZOS)
    result = recognize(image, regions=configuration(number))
    # Losing tiny glyphs is allowed; accepting incorrect digits is not.
    if result.status == "accepted":
        assert result.reading == EXPECTED[number]


def test_moved_hud_with_normalized_calibration():
    image = sample(1)
    # Move the source into a larger canvas without resampling its glyphs.
    canvas = Image.new("RGB", (image.width + 400, image.height + 400), "black")
    canvas.paste(image, (200, 0))
    moved = {key: Region((roi.x0 * image.width + 200) / canvas.width,
                         roi.y0 * image.height / canvas.height,
                         (roi.x1 * image.width + 200) / canvas.width,
                         roi.y1 * image.height / canvas.height)
             for key, roi in configuration(1).items()}
    result = recognize(canvas, regions=moved)
    assert result.status == "accepted"
    assert result.reading == EXPECTED[1]


def test_blurred_hud_is_not_accepted():
    result = recognize(sample(1).filter(ImageFilter.GaussianBlur(5)), regions=configuration(1))
    assert result.status != "accepted"


def test_blank_image_has_no_hud():
    assert recognize(Image.new("RGB", (640, 360), "black")).status == "missing_hud"
