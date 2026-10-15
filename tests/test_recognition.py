from PIL import Image
import pytest

from exp_tracker.models import Region
from exp_tracker import recognition


REGIONS = {"level": Region(0, 0, .2, .2), "exp": Region(.2, 0, 1, .2)}


@pytest.mark.parametrize("level,exp,status", [
    ([("42", .9)], [("12,345[23.45%]", .9)], "accepted"),
    ([("42", .1)], [("12,345[23.45%]", .9)], "low_confidence"),
    ([("42", .9), ("43", .9)], [("12,345[23.45%]", .9)], "ambiguous"),
    ([("42", .9)], [("12,345[23.45%]", .9), ("12,845[23.45%]", .8)], "ambiguous"),
    ([("42", .9)], [("12,345[2345%]", .9)], "unreadable"),
    ([("201", .9)], [("12,345[23.45%]", .9)], "invalid"),
    ([("42", .9)], [("12,345[100.00%]", .9)], "invalid"),
])
def test_confidence_and_conflicting_ocr(monkeypatch, level, exp, status):
    monkeypatch.setattr(recognition, "configure_tesseract", lambda: None)
    def field(_image, name, _debug):
        return [dict(text=t, confidence=c) for t, c in (level if name == "level" else exp)]
    monkeypatch.setattr(recognition, "_read_field", field)
    result = recognition.recognize(Image.new("RGB", (100, 100)), regions=REGIONS)
    assert result.status == status


def test_multiple_hud_panels_need_explicit_selection(monkeypatch):
    monkeypatch.setattr(recognition, "configure_tesseract", lambda: None)
    monkeypatch.setattr(recognition, "discover_regions", lambda *_: [REGIONS, REGIONS])
    assert recognition.recognize(Image.new("RGB", (100, 100))).status == "ambiguous"
