"""Optional private live-crop regressions; absent fixtures are explicit skips."""

import json
from pathlib import Path
import sys

import pytest

from exp_tracker.glyphs import GlyphProfile, match_exp
from exp_tracker.models import Reading
from exp_tracker.parsing import parse_exp
from exp_tracker.recognition import recognize

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from evaluate_ocr import load_crops

MANIFEST = ROOT / "private/ocr-evaluation/manifest.json"
PROFILE = ROOT / "private/ocr-evaluation/glyph-profile.json"
pytestmark = pytest.mark.samples


@pytest.fixture(scope="module")
def dataset():
    if not MANIFEST.exists() or not PROFILE.exists():
        pytest.skip("Private live crops/labels/profile are intentionally excluded from Git")
    return json.loads(MANIFEST.read_text(encoding="utf-8")), GlyphProfile.load(PROFILE)


@pytest.mark.parametrize("index", range(18))
def test_live_pixel_exp_never_accepts_wrong_reading(dataset, index):
    data, profile = dataset
    item = data["examples"][index]
    _, _, crop = load_crops(MANIFEST, item, data)
    result = match_exp(crop, profile)
    if item["id"] == "periodic-10/0":
        # Degraded percent symbol: retain the deliberate rejection.
        assert not result["text"]
    else:
        assert parse_exp(result["text"]) == (item["current_exp"], item["percentage"])


@pytest.mark.ocr
@pytest.mark.parametrize("index", range(18))
def test_live_hybrid_coverage_and_correctness(dataset, index):
    data, profile = dataset
    item = data["examples"][index]
    image, regions, _ = load_crops(MANIFEST, item, data)
    result = recognize(image, regions=regions, glyph_profile=profile)
    if item["id"] == "periodic-10/0":
        assert result.status != "accepted"
    else:
        assert result.status == "accepted"
        assert result.reading == Reading(item["level"], item["current_exp"], item["percentage"])


@pytest.mark.parametrize("scale", [1, 2])
def test_real_glyphs_with_padding_and_integer_resampling(dataset, scale):
    from PIL import Image
    data, profile = dataset
    item = data["examples"][0]  # Development only; this is a synthetic variation.
    _, _, crop = load_crops(MANIFEST, item, data)
    padded = Image.new("RGB", (crop.width + 12, crop.height + 6))
    padded.paste(crop, (5, 3))
    if scale != 1:
        padded = padded.resize((padded.width * scale, padded.height * scale), Image.Resampling.NEAREST)
    result = match_exp(padded, profile, scales=(scale,))
    assert parse_exp(result["text"]) == (item["current_exp"], item["percentage"])
