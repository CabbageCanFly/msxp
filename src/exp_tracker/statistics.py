"""Read-only statistics from the current chain of already validated intervals."""

from datetime import datetime, timedelta


MIN_WINDOW_COVERAGE = .8
MIN_ETA_PROGRESS_BP = 10  # 0.10 percentage points: endpoint rounding error is at most ~10%.


def _window(chain, now, seconds, unavailable):
    result = dict(exp=None, reason=unavailable, window_seconds=seconds, covered_seconds=0,
                  start_at=None, end_at=None, missing_observations=0,
                  boundary_trimmed=False, percentage_gained_bp=None)
    if unavailable:
        return result
    cutoff = now - timedelta(seconds=seconds)
    if not chain or chain[-1]["start"] > cutoff:
        result["reason"] = "insufficient_history"
        return result
    inside = [row for row in chain if row["start"] >= cutoff]
    if not inside:
        result["reason"] = "insufficient_coverage"
        return result
    first, last = inside[-1], inside[0]
    covered = (last["end"] - first["start"]).total_seconds()
    result.update(covered_seconds=covered, start_at=first["start"].isoformat(), end_at=last["end"].isoformat(),
                  missing_observations=sum(row["missing_observations"] for row in inside),
                  boundary_trimmed=first["start"] != cutoff or last["end"] != now)
    if covered < seconds * MIN_WINDOW_COVERAGE:
        result["reason"] = "insufficient_coverage"
        return result
    result.update(exp=sum(row["gained_exp"] for row in inside), reason="ok",
                  percentage_gained_bp=last["percentage_bp"] - first["start_percentage_bp"])
    return result


def tracking_statistics(db, state, now):
    """Use complete intervals only; never interpolate boundary gains or fill gaps with zero."""
    session, last = state["session"], state["last_trusted"]
    unavailable = None
    if not session or not last or last["session_id"] != session["id"]:
        unavailable = "no_current_reading"
    elif state["continuity_broken"]:
        unavailable = "hard_break"
    elif state["stale"]:
        unavailable = "stale"
    elif datetime.fromisoformat(last["observed_at"]) > now:
        unavailable = "future_reading"
    chain = []
    if unavailable is None:
        rows = db.execute("""SELECT o.id,o.interval_start_observation_id,o.observed_at,
            o.gained_exp,o.missing_observations,o.percentage_bp,p.observed_at AS start_at,
            p.percentage_bp AS start_percentage_bp
            FROM observations o JOIN observations p ON p.id=o.interval_start_observation_id
            WHERE o.character_id=? AND o.session_id=? AND o.outcome='accepted'
              AND p.character_id=o.character_id AND p.session_id=o.session_id AND p.level=o.level
              AND p.outcome IN ('accepted','baseline') AND o.observed_at>? AND o.observed_at<=?
            ORDER BY o.observed_at DESC""", (state["selected_character_id"], session["id"],
                (now - timedelta(minutes=30)).isoformat(timespec="microseconds"),
                last["observed_at"]))
        expected = last["id"]
        for record in rows:
            if record["id"] != expected:
                break  # A baseline/hard break or legacy row has no interval link.
            row = dict(record)
            row.update(start=datetime.fromisoformat(row["start_at"]), end=datetime.fromisoformat(row["observed_at"]))
            chain.append(row)
            expected = row["interval_start_observation_id"]
    recent = _window(chain, now, 300, unavailable)
    pace = _window(chain, now, 1800, unavailable)
    pace["exp_per_hour"] = pace["exp"] * 3600 / pace["covered_seconds"] if pace["exp"] is not None else None
    eta = dict(seconds=None, reason=pace["reason"], percentage_gained_bp=pace["percentage_gained_bp"])
    if pace["exp"] is not None:
        if pace["percentage_gained_bp"] < MIN_ETA_PROGRESS_BP:
            eta["reason"] = "insufficient_percentage_progress"
        else:
            eta.update(seconds=(10000 - last["percentage_bp"]) * pace["covered_seconds"] / pace["percentage_gained_bp"],
                       reason="ok")
    return dict(last_5_min=recent, exp_per_hour_30m=pace, to_next_level=eta)
