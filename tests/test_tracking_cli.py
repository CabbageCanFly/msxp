import json

from exp_tracker.tracking import main
from tools.demo_tracking import main as demo


def test_local_admin_workflow(tmp_path, capsys):
    path = tmp_path / "tracker.sqlite3"
    args = ["--db", str(path), "--channel", "demo"]
    assert main([*args, "state"]) == 1
    assert json.loads(capsys.readouterr().err)["status"] == "error"
    assert not path.exists()
    for command in (["init"], ["character", "Mage"], ["select", "1"], ["start"], ["state"]):
        assert main([*args, *command]) == 0
        state = json.loads(capsys.readouterr().out)
    assert state["selected_character_id"] == 1 and state["session"]["id"] == 1
    assert state["last_trusted"] is None and state["status"] == "waiting"
    assert main([*args, "start"]) == 0
    assert json.loads(capsys.readouterr().out)["session"]["id"] == 1
    assert main([*args, "end"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "stopped"


def test_owned_synthetic_demo_and_restart(tmp_path, capsys):
    path = tmp_path / "demo.sqlite3"
    demo(path)
    state = json.loads(capsys.readouterr().out)
    assert state["last_trusted"]["current_exp"] == 1500
    assert state["observed_session_exp"] == 500
    assert main(["--db", str(path), "--channel", "demo", "state"]) == 0
    assert json.loads(capsys.readouterr().out)["last_trusted"] == state["last_trusted"]
