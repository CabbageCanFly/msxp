from io import BytesIO

from PIL import Image
import pytest

from exp_tracker.twitch_probe import inspect_thumbnail, main, thumbnail_url


def test_only_official_https_thumbnail_host():
    template = "https://static-cdn.jtvnw.net/previews/live-{width}x{height}.jpg"
    assert thumbnail_url(template, 1920, 1080).endswith("1920x1080.jpg")
    for url in ("http://static-cdn.jtvnw.net/a", "https://example.com/a", "https://127.0.0.1/a"):
        with pytest.raises(ValueError):
            thumbnail_url(url, 1920, 1080)


def test_thumbnail_metrics_without_retaining_image():
    payload = BytesIO()
    Image.new("RGB", (64, 32), "black").save(payload, format="PNG")
    result = inspect_thumbnail(payload.getvalue())
    assert result["image_size"] == [64, 32]
    assert len(result["sha256"]) == 64
    assert "recognition" not in result


def test_missing_credentials_do_not_make_network_requests(monkeypatch, capsys):
    monkeypatch.delenv("TWITCH_CLIENT_ID", raising=False)
    monkeypatch.delenv("TWITCH_ACCESS_TOKEN", raising=False)
    assert main(["somechannel"]) == 1
    assert "TWITCH_CLIENT_ID" in capsys.readouterr().err
