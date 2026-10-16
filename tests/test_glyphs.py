"""Synthetic seven-segment font: no screenshot pixels or game font assets."""

from dataclasses import replace
import json

from PIL import Image
import pytest

from exp_tracker.glyphs import GlyphProfile, SYMBOLS, mask, match_exp
from exp_tracker import recognition
from exp_tracker.models import Region


@pytest.fixture
def synthetic_profile():
    segments = {
        "a": [(x, 1) for x in range(1, 4)], "b": [(4, y) for y in (2, 3)],
        "c": [(4, y) for y in (5, 6)], "d": [(x, 7) for x in range(1, 4)],
        "e": [(0, y) for y in (5, 6)], "f": [(0, y) for y in (2, 3)],
        "g": [(x, 4) for x in range(1, 4)]}
    shapes = dict(zip("0123456789", ("abcdef", "bc", "abged", "abgcd", "fgbc",
                                         "afgcd", "afgecd", "abc", "abcdefg", "abfgcd")))
    widths = {c: 6 for c in SYMBOLS}
    punctuation = {"[": [(2, y) for y in range(9)] + [(3, 0), (3, 8)],
                   "]": [(3, y) for y in range(9)] + [(2, 0), (2, 8)],
                   ".": [(2, 7)], ",": [(2, 7), (1, 8)],
                   "%": [(0, 1), (1, 1), (4, 7), (3, 7), (3, 2), (2, 3), (1, 4), (0, 5)]}
    templates = {}
    for char in SYMBOLS:
        coordinates = [xy for s in shapes[char] for xy in segments[s]] if char.isdigit() else punctuation[char]
        templates[char] = (sum(1 << (y * 6 + x) for x, y in set(coordinates)),)
    return GlyphProfile(9, widths, templates)


def render(profile, text, offset=(3, 2)):
    width = sum(profile.widths[c] for c in text)
    image = Image.new("RGB", (width + 8, profile.height + 5), (30, 30, 30))
    x, top = offset
    for char in text:
        cell_width = profile.widths[char]
        value = profile.templates[char][0]
        for i in range(cell_width * profile.height):
            if value & (1 << i):
                image.putpixel((x + i % cell_width, top + i // cell_width),
                               (140, 190, 60) if char in "[]" else (240, 240, 240))
        x += cell_width
    return image


@pytest.mark.parametrize("text", ["1[0.12%]", "12,345[67.89%]", "987654[32.10%]",
                                  "9,876,543[98.76%]", "0[0.00%]"])
def test_complete_variable_length_line(synthetic_profile, text):
    result = match_exp(render(synthetic_profile, text), synthetic_profile)
    assert result["text"] == text
    assert result["score_kind"] == "glyph_pixel_agreement"


def test_integer_scaling_and_translation(synthetic_profile):
    text = "12,345[67.89%]"
    image = render(synthetic_profile, text, offset=(5, 4))
    image = image.resize((image.width * 2, image.height * 2), Image.Resampling.NEAREST)
    assert match_exp(image, synthetic_profile, scales=(2,))["text"] == text


@pytest.mark.parametrize("symbol", ["[", "]", ".", "%", ","])
def test_missing_punctuation_is_rejected(synthetic_profile, symbol):
    text = "12,345[67.89%]"
    image = render(synthetic_profile, text)
    x = 3 + sum(synthetic_profile.widths[c] for c in text[:text.index(symbol)])
    image.paste((30, 30, 30), (x, 2, x + synthetic_profile.widths[symbol], 11))
    assert not match_exp(image, synthetic_profile)["text"]


def test_uncertain_six_eight_is_rejected(synthetic_profile):
    image = render(synthetic_profile, "12,346[67.89%]")
    # Six and eight differ in two pixels; halfway is an exact distance tie.
    x = 3 + 5 * 6
    image.putpixel((x + 4, 2 + 2), (240, 240, 240))
    assert not match_exp(image, synthetic_profile)["text"]


def test_unreadable_digit_cannot_be_dropped_as_prefix(synthetic_profile):
    image = render(synthetic_profile, "12,345[67.89%]")
    image.paste((30, 30, 30), (3 + 3 * 6, 2, 3 + 4 * 6, 11))
    assert not match_exp(image, synthetic_profile)["text"]


def test_blank_and_oversize_are_bounded(synthetic_profile):
    assert not match_exp(Image.new("RGB", (100, 12)), synthetic_profile)["text"]
    result = match_exp(Image.new("RGB", (1920, 1080)), synthetic_profile)
    assert result["reason"] == "pixel_roi_too_large"


def test_invalid_or_incomplete_profiles(synthetic_profile, tmp_path):
    with pytest.raises(ValueError):
        replace(synthetic_profile, templates={})
    with pytest.raises(ValueError):
        replace(synthetic_profile, templates={**synthetic_profile.templates, "1": (0,)})
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(dict(version=99)))
    with pytest.raises(ValueError):
        GlyphProfile.load(path)
    with pytest.raises(ValueError):
        match_exp(Image.new("RGB", (10, 10)), synthetic_profile, scales=(float("nan"),))


def test_color_mask_preserves_green_bracket():
    image = Image.new("RGB", (1, 1), (100, 180, 20))
    assert mask(image, 160, color=True) == 1
    assert mask(image, 160) == 0


def test_hybrid_uses_pixel_exp_and_keeps_level_engine(synthetic_profile, monkeypatch):
    image = render(synthetic_profile, "12,345[67.89%]")
    calls = []
    monkeypatch.setattr(recognition, "configure_tesseract", lambda: None)
    def read(_crop, field, _debug):
        calls.append(field)
        return [dict(text="42", confidence=.9)]
    monkeypatch.setattr(recognition, "_read_field", read)
    result = recognition.recognize(image, regions={"exp": Region(0, 0, 1, 1),
                                                  "level": Region(0, 0, .1, 1)},
                                   glyph_profile=synthetic_profile)
    assert result.status == "accepted"
    assert result.reading.current_exp == 12345
    assert calls == ["level"]


def test_hybrid_fallback_and_pixel_ambiguity_veto(synthetic_profile, monkeypatch):
    monkeypatch.setattr(recognition, "configure_tesseract", lambda: None)
    monkeypatch.setattr(recognition, "_read_field", lambda _c, field, _d:
                        [dict(text="42" if field == "level" else "12,345[67.89%]", confidence=.9)])
    regions = {"level": Region(0, 0, .1, 1), "exp": Region(.1, 0, 1, 1)}
    result = recognition.recognize(Image.new("RGB", (100, 12)), regions=regions,
                                   glyph_profile=synthetic_profile)
    assert result.status == "accepted"
    assert result.raw["exp"][0]["reason"] == "no_complete_pixel_match"
    monkeypatch.setattr(recognition, "match_exp", lambda *_a, **_kw:
                        dict(text="", confidence=0, veto=True, reason="conflicting_pixel_readings"))
    result = recognition.recognize(Image.new("RGB", (100, 12)), regions=regions,
                                   glyph_profile=synthetic_profile)
    assert result.status == "ambiguous"
    assert result.reading is None


def test_training_roundtrip_and_heldout_guard(synthetic_profile, tmp_path):
    from tools.train_glyph_profile import train
    text = "0123456789[12.34%],"
    render(synthetic_profile, text).save(tmp_path / "owned.png")
    annotation = tmp_path / "training.json"
    data = dict(height=9, digit_threshold=175, punctuation_threshold=100,
                samples=[dict(image="owned.png", id="synthetic-training", split="development",
                              text=text, origin=[3, 2], widths=synthetic_profile.widths)])
    annotation.write_text(json.dumps(data), encoding="utf-8")
    output = tmp_path / "profile.json"
    train(annotation, output)
    assert GlyphProfile.load(output) == synthetic_profile
    assert json.loads(output.read_text())["provenance"]["training_ids"] == ["synthetic-training"]
    data["samples"][0]["split"] = "heldout"
    annotation.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="Only development"):
        train(annotation, output)


def test_incomplete_training_alphabet_is_rejected(synthetic_profile, tmp_path):
    from tools.train_glyph_profile import train
    text = "1[0.00%]"
    render(synthetic_profile, text).save(tmp_path / "owned.png")
    annotation = tmp_path / "training.json"
    annotation.write_text(json.dumps(dict(height=9, digit_threshold=175, punctuation_threshold=100,
        samples=[dict(image="owned.png", id="incomplete", split="development", text=text,
                      origin=[3, 2], widths=synthetic_profile.widths)])))
    with pytest.raises(ValueError, match="empty glyph"):
        train(annotation, tmp_path / "profile.json")
