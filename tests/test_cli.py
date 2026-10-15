import json

from exp_tracker.cli import main


def test_missing_image_is_structured_error(capsys):
    assert main(["inspect", "does-not-exist.png"]) == 1
    assert json.loads(capsys.readouterr().err)["status"] == "error"


def test_non_object_config_is_structured_error(tmp_path, capsys):
    config = tmp_path / "bad.json"
    config.write_text("[]", encoding="utf-8")
    assert main(["inspect", "unused.png", "--config", str(config)]) == 1
    assert "JSON object" in json.loads(capsys.readouterr().err)["error"]


def test_invalid_search_is_structured_error(capsys):
    assert main(["inspect", "unused.png", "--search", "0,0,2,1"]) == 1
    assert json.loads(capsys.readouterr().err)["status"] == "error"
