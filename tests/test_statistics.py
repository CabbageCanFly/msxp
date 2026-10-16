from datetime import datetime, timedelta, timezone
import json

import pytest

from exp_tracker.glyphs import GlyphProfile, SYMBOLS
from exp_tracker.models import Reading, Recognition
from exp_tracker.store import Store
from tools.demo_statistics import main as demo


END = datetime(2026, 1, 1, 1, tzinfo=timezone.utc)


def reading(exp, percentage, level=60):
    return Recognition("accepted", Reading(level, exp, percentage), .99,
                       raw={"exp": [dict(variant="pixel", text=f"{exp:,}[{percentage:.2f}%]", confidence=.99)]})


@pytest.fixture
def profile():
    return GlyphProfile(9, {c: 6 for c in SYMBOLS}, {c: (1 << i,) for i, c in enumerate(SYMBOLS)})


@pytest.fixture
def history(tmp_path, profile):
    path = tmp_path / "statistics.sqlite3"
    demo(path, as_of=END)
    with Store(path) as store:
        yield store, profile, path


def ingest(history, event, seconds, result, profile_required=True):
    store, profile, _ = history
    session = store.state("demo", as_of=END)["session"]
    return store.ingest("demo", event, END + timedelta(seconds=seconds), result,
                        profile=profile if profile_required else None, session_id=session["id"])


def test_populated_history_uses_persisted_intervals_and_survives_restart(history):
    store, _, path = history
    state = store.state("demo", as_of=END)
    statistics = state["statistics"]
    recent, pace, eta = statistics.values()
    assert recent["exp"] == 20000 and recent["covered_seconds"] == 300
    assert recent["missing_observations"] == 1 and not recent["boundary_trimmed"]
    assert pace["exp"] == 120000 and pace["covered_seconds"] == 1800
    assert pace["exp_per_hour"] == 240000
    assert eta["seconds"] == 11400 and eta["percentage_gained_bp"] == 1200
    assert state["observed_session_exp"] == 140000 and state["bridged_session_exp"] == 4000
    changes = store.db.total_changes
    with Store(path, read_only=True) as restarted:
        assert restarted.state("demo", as_of=END) == state
    assert store.db.total_changes == changes


def test_boundary_crossing_interval_is_never_prorated(history):
    store, _, _ = history
    result = store.state("demo", as_of=END + timedelta(microseconds=1))["statistics"]
    assert result["last_5_min"]["exp"] == 18000
    assert result["last_5_min"]["covered_seconds"] == 270
    assert result["last_5_min"]["boundary_trimmed"]
    assert result["exp_per_hour_30m"]["exp"] == 118000
    assert result["exp_per_hour_30m"]["exp_per_hour"] == 240000


@pytest.mark.parametrize("seconds,available", [(60, True), (60.000001, False)])
def test_minimum_coverage_boundary_does_not_fill_tail_with_zero(history, seconds, available):
    recent = history[0].state("demo", as_of=END + timedelta(seconds=seconds))["statistics"]["last_5_min"]
    assert (recent["exp"] is not None) == available
    assert recent["covered_seconds"] == (240 if available else 210)
    assert recent["reason"] == ("ok" if available else "insufficient_coverage")


def test_full_window_history_is_required_even_if_partial_rate_looks_plausible(history):
    store, _, _ = history
    store.end_session("demo", at=END)
    session = store.start_session("demo", at=END)
    for index in range(10):
        ingest(history, f"new-{index}", index * 30 + 1, reading(250000 + index * 2000, 25 + index * .2))
    statistics = store.state("demo", as_of=END + timedelta(seconds=271))["statistics"]
    assert statistics["last_5_min"]["reason"] == "insufficient_history"
    assert statistics["exp_per_hour_30m"]["exp_per_hour"] is None
    assert statistics["to_next_level"]["seconds"] is None
    assert store.state("demo")["session"]["id"] == session
    ingest(history, "new-10", 301, reading(270000, 27))
    statistics = store.state("demo", as_of=END + timedelta(seconds=301))["statistics"]
    assert statistics["last_5_min"]["exp"] == 20000
    assert statistics["exp_per_hour_30m"]["reason"] == "insufficient_history"
    assert statistics["to_next_level"]["seconds"] is None


def test_bridged_interval_straddling_cutoff_is_excluded_whole(history):
    for index in range(1, 6):
        ingest(history, f"future-{index}", index * 30, reading(240000 + index * 2000, 24 + index * .2))
    recent = history[0].state("demo", as_of=END + timedelta(seconds=150))["statistics"]["last_5_min"]
    # The 4,000 bridge covers -180..-120; cutoff is -150. No invented half-bridge.
    assert recent["exp"] == 18000 and recent["covered_seconds"] == 270
    assert recent["missing_observations"] == 0 and recent["boundary_trimmed"]


@pytest.mark.parametrize("result", [Recognition("offline"), Recognition("paused"), Recognition("capture_failed"),
                                  reading(239000, 23.9), reading(0, 0, 61)])
def test_hard_breaks_disable_windows_without_losing_session_gain(history, result):
    store, _, _ = history
    before = store.state("demo", as_of=END)
    ingest(history, "break", 1, result)
    ingest(history, "later-unreadable", 2, Recognition("unreadable"))
    after = store.state("demo", as_of=END + timedelta(seconds=2))
    assert after["last_trusted"] == before["last_trusted"]
    assert after["observed_session_exp"] == 140000
    assert after["statistics"]["last_5_min"]["reason"] == "hard_break"
    assert after["statistics"]["exp_per_hour_30m"]["exp_per_hour"] is None
    assert after["statistics"]["to_next_level"]["seconds"] is None


def test_post_offline_baseline_does_not_cherry_pick_older_intervals(history):
    ingest(history, "offline", 1, Recognition("offline"))
    assert ingest(history, "new-baseline", 2, reading(242000, 24.2))["outcome"] == "baseline"
    ingest(history, "new-gain", 32, reading(244000, 24.4))
    state = history[0].state("demo", as_of=END + timedelta(seconds=32))
    assert state["statistics"]["last_5_min"]["reason"] == "insufficient_history"
    assert state["observed_session_exp"] == 142000


def test_unverified_fallback_never_supplies_statistics_but_trusted_bridge_can(history):
    fallback = reading(999999, 99.99)
    fallback.raw["exp"][0]["variant"] = "unrestricted-line"
    assert ingest(history, "fallback", 15, fallback)["reason"] == "unverified_tesseract_exp"
    result = ingest(history, "trusted", 30, reading(242000, 24.2))
    assert result["gained_exp"] == 2000 and result["missing_observations"] == 1
    recent = history[0].state("demo", as_of=END + timedelta(seconds=30))["statistics"]["last_5_min"]
    assert recent["exp"] == 20000 and recent["missing_observations"] == 2
    assert ingest(history, "trusted", 30, reading(242000, 24.2))["duplicate"]
    assert history[0].state("demo", as_of=END + timedelta(seconds=30))["statistics"]["last_5_min"] == recent


def test_missing_profile_cannot_contribute_a_new_statistics_endpoint(history):
    result = ingest(history, "unprofiled", 1, reading(999999, 99.99), profile_required=False)
    assert result["reason"] == "glyph_profile_required"
    assert history[0].state("demo", as_of=END + timedelta(seconds=1))["statistics"]["last_5_min"]["exp"] is None


def test_large_accepted_gain_has_no_rate_cap(history):
    result = ingest(history, "large", 30, reading(2000000000, 99.99))
    assert result["outcome"] == "accepted" and result["gained_exp"] == 1999760000
    recent = history[0].state("demo", as_of=END + timedelta(seconds=30))["statistics"]["last_5_min"]
    assert recent["exp"] == 1999778000


@pytest.mark.parametrize("age", [121, 1801])
def test_stale_windows_and_eta_are_null_not_zero_or_frozen_pace(history, age):
    state = history[0].state("demo", as_of=END + timedelta(seconds=age))
    assert state["statistics"]["last_5_min"]["reason"] == "stale"
    assert state["statistics"]["exp_per_hour_30m"]["exp_per_hour"] is None
    assert state["statistics"]["to_next_level"]["seconds"] is None
    assert state["last_trusted"]["current_exp"] == 240000 and state["observed_session_exp"] == 140000


@pytest.mark.parametrize("switch_character", [True, False])
def test_character_and_level_changes_start_separate_window_history(history, switch_character):
    store, _, _ = history
    if switch_character:
        other = store.add_character("demo", "Other hero")
        store.select_character("demo", other, at=END + timedelta(seconds=1))
    else:
        store.end_session("demo", at=END + timedelta(seconds=1))
    store.start_session("demo", at=END + timedelta(seconds=2))
    ingest(history, "other", 3, reading(0, 0, 61))
    state = store.state("demo", as_of=END + timedelta(seconds=3))
    assert state["last_trusted"]["level"] == 61 and state["observed_session_exp"] == 0
    assert state["statistics"]["last_5_min"]["exp"] is None
    assert state["statistics"]["to_next_level"]["seconds"] is None


@pytest.mark.parametrize("percent_gain,eta_available", [(0, False), (.09, False), (.10, True)])
def test_eta_needs_percentage_progress_above_rounding_noise(tmp_path, profile, percent_gain, eta_available):
    path = tmp_path / "slow.sqlite3"
    with Store(path) as store:
        store.add_channel("demo")
        character = store.add_character("demo", "Slow synthetic hero")
        start = END - timedelta(minutes=30)
        store.select_character("demo", character, at=start)
        session = store.start_session("demo", at=start)
        for index in range(61):
            percentage = (1000 + round(index / 60 * round(percent_gain * 100))) / 100
            store.ingest("demo", f"slow-{index}", start + timedelta(seconds=index * 30),
                         reading(100000 + index, percentage), profile=profile, session_id=session)
        eta = store.state("demo", as_of=END)["statistics"]["to_next_level"]
        assert (eta["seconds"] is not None) == eta_available


def test_long_gap_rebaselines_and_excludes_previous_history(history):
    result = ingest(history, "gap", 121, reading(500000, 50))
    assert result["outcome"] == "baseline" and result["gained_exp"] is None
    state = history[0].state("demo", as_of=END + timedelta(seconds=121))
    assert state["statistics"]["last_5_min"]["reason"] == "insufficient_history"
    assert state["observed_session_exp"] == 140000


def test_verified_unchanged_endpoints_can_report_zero_pace(tmp_path, profile):
    with Store(tmp_path / "unchanged.sqlite3") as store:
        store.add_channel("demo")
        character = store.add_character("demo", "Idle synthetic hero")
        start = END - timedelta(minutes=30)
        store.select_character("demo", character, at=start)
        session = store.start_session("demo", at=start)
        for index in range(61):
            store.ingest("demo", f"idle-{index}", start + timedelta(seconds=index * 30),
                         reading(100000, 10), profile=profile, session_id=session)
        statistics = store.state("demo", as_of=END)["statistics"]
        assert statistics["last_5_min"]["exp"] == 0
        assert statistics["exp_per_hour_30m"]["exp_per_hour"] == 0
        assert statistics["to_next_level"]["seconds"] is None


def test_legacy_interval_metadata_is_not_invented(history):
    store, _, _ = history
    store.db.execute("UPDATE observations SET interval_start_observation_id=NULL WHERE event_id='synthetic-history-70'")
    statistics = store.state("demo", as_of=END)["statistics"]
    assert statistics["last_5_min"]["reason"] == "insufficient_history"
    assert statistics["exp_per_hour_30m"]["exp_per_hour"] is None


def test_late_attempts_do_not_change_statistics_and_future_readings_are_not_used(history):
    before = history[0].state("demo", as_of=END)["statistics"]
    assert ingest(history, "late-offline", -5, Recognition("offline"))["reason"] == "out_of_order"
    assert history[0].state("demo", as_of=END)["statistics"] == before
    assert history[0].state("demo", as_of=END - timedelta(seconds=1))["statistics"]["last_5_min"]["reason"] == "future_reading"


def test_demo_is_reproducible_and_refuses_existing_history(tmp_path, capsys):
    path = tmp_path / "demo.sqlite3"
    state = demo(path, as_of=END)
    assert json.loads(capsys.readouterr().out)["statistics"] == state["statistics"]
    with pytest.raises(ValueError, match="new database"):
        demo(path, as_of=END)
    with pytest.raises(ValueError, match="timezone"):
        demo(tmp_path / "naive.sqlite3", as_of=END.replace(tzinfo=None))
