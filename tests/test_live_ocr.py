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


@pytest.mark.ocr
@pytest.mark.parametrize("index", range(17))
def test_saved_green_trial_preserves_recorded_outcomes(index):
    from PIL import Image
    from exp_tracker.capture import _guard_unverified_exp
    from exp_tracker.models import Region
    trial = "green-test-20261015-215403"
    records_path = ROOT / f"artifacts/{trial}.jsonl"
    profile_path = ROOT / "private/ocr-evaluation/glyph-profile-green-experimental.json"
    if not records_path.exists() or not profile_path.exists():
        pytest.skip("Private green trial/profile are intentionally excluded from Git")
    payload = records_path.read_bytes()
    encoding = "utf-16" if payload.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
    records = [json.loads(line) for line in payload.decode(encoding).splitlines()]
    record = next(r for r in records if r.get("type") == "observation" and r["index"] == index)
    regions = {field: Region(**roi) for field, roi in record["recognition"]["regions"].items()}
    image = Image.new("RGB", tuple(record["frame_size"]))
    # An early level failure saves only the level crop; EXP was never processed.
    for field in record["recognition"]["raw"]:
        roi = regions[field]
        with Image.open(ROOT / f"artifacts/{trial}/{index:04d}/{field}-crop.png") as crop:
            image.paste(crop, roi.pixels(*image.size)[:2])
    profile = GlyphProfile.load(profile_path)
    result = _guard_unverified_exp(recognize(image, regions=regions, glyph_profile=profile), profile)
    # The user visually reviewed these accepted trial values; this is replay,
    # not a newly labeled or independent accuracy dataset.
    assert result.status == record["status"]
    if result.status == "accepted":
        assert result.reading == Reading(**record["recognition"]["reading"])


def test_green_calibration_reproduces_experimental_glyphs(tmp_path):
    from tools.train_glyph_profile import train
    annotation = ROOT / "private/ocr-evaluation/training-green.json"
    experiment = ROOT / "private/ocr-evaluation/glyph-profile-green-experimental.json"
    if not annotation.exists() or not experiment.exists():
        pytest.skip("Private green training material/profile are intentionally excluded from Git")
    generated = train(annotation, tmp_path / "generated.json")
    expected = GlyphProfile.load(experiment)
    assert (generated.height, generated.widths, generated.digit_threshold,
            generated.punctuation_threshold, generated.bracket_mode) == (
        expected.height, expected.widths, expected.digit_threshold,
        expected.punctuation_threshold, expected.bracket_mode)
    assert {c: set(v) for c, v in generated.templates.items()} == {
        c: set(v) for c, v in expected.templates.items()}
