from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from exp_tracker.shadow_view import MAX_BYTES, MAX_LINE, MAX_ROWS, ShadowLog

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def attempt(index=1, **changes):
    value = dict(type='attempt', index=index, status='diagnostic_pair', current=True,
                 source=dict(kind='twitch', channel='synthetic'), received_at=NOW.isoformat(),
                 attempted_at=NOW.isoformat(), candidate=[100, 25.0], neural=dict(text='100[25.00%]'),
                 visual_level=7, visual_attempts=[dict(text='7')], visual_status='available',
                 neural_status='single_line', reasons=[], level_evidence=dict(relation='conflict', hypotheses={
                     'nearest_half_up': dict(status='incompatible', levels=[]),
                     'truncate': dict(status='unique', levels=[7])}))
    return {**value, **changes}


@pytest.fixture
def log(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / 'private/trial.jsonl'
    path.parent.mkdir()
    return path


def write(log, *rows):
    log.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')


def test_absence_empty_and_completed_states(log):
    reader = ShadowLog(log)
    assert reader.snapshot(NOW)['log_status'] == 'missing'
    assert not log.exists()
    write(log)
    assert reader.snapshot(NOW)['observations'] == []
    write(log, dict(type='configuration', interval=15), attempt(), dict(type='summary', interrupted=False))
    result = reader.snapshot(NOW)
    assert result['run_status'] == 'completed' and result['source_status'] == 'diagnostic_pair'
    assert result['channel'] == 'synthetic' and not result['trusted']
    assert result['observations'][0]['candidate'] == dict(exp='100', percentage='25.00')
    assert result['observations'][0]['hypotheses']['nearest_half_up']['levels'] == []
    assert result['observations'][0]['hypotheses']['truncate']['levels'] == [7]


def test_partial_tail_even_valid_json_waits_for_newline(log):
    write(log, attempt())
    with log.open('a') as handle:
        handle.write(json.dumps(attempt(2)))
    result = ShadowLog(log).snapshot(NOW)
    assert result['incomplete_tail'] and len(result['observations']) == 1
    with log.open('a') as handle:
        handle.write('\n')
    assert len(ShadowLog(log).snapshot(NOW)['observations']) == 2


@pytest.mark.parametrize('bad', ['not JSON', '[]', '{', '[' * 1000 + '0' + ']' * 1000, 'x' * (MAX_LINE+1)],
                         ids=['syntax', 'array', 'unfinished', 'too_deep', 'too_long'])
def test_malformed_complete_lines_create_breaks_without_repair(log, bad):
    log.write_text(json.dumps(attempt()) + '\n' + bad + '\n' + json.dumps(attempt(3)) + '\n')
    result = ShadowLog(log).snapshot(NOW)
    assert result['malformed_lines'] == 1
    assert result['observations'][1]['status'] == 'malformed_log_line'
    assert result['observations'][1]['candidate'] is None


def test_unexpected_nested_shapes_do_not_crash_or_leak(log):
    write(log, attempt(status=[]), attempt(2, source=[], neural=[], level_evidence=[], reasons='secret'))
    result = ShadowLog(log).snapshot(NOW)
    assert result['malformed_lines'] == 1 and len(result['observations']) == 2
    assert 'secret' not in json.dumps(result)


@pytest.mark.parametrize('relative', ['outside.jsonl', 'samples/secret.jsonl', 'private/../outside.jsonl',
                                     'private/model.onnx', 'private/credentials.env'])
def test_paths_restricted_to_ignored_jsonl(log, relative):
    with pytest.raises(ValueError, match='Shadow log must'):
        ShadowLog(log.parents[1] / relative)


def test_restricted_path_is_rechecked_on_each_read(log):
    reader = ShadowLog(log)
    reader.path = log.parent.parent / 'outside.jsonl'
    result = reader.snapshot(NOW)
    assert result['log_status'] == 'unavailable' and 'outside.jsonl' not in json.dumps(result)


def test_directory_is_not_a_log(log):
    log.mkdir()
    assert ShadowLog(log).snapshot(NOW)['log_status'] == 'unavailable'


def test_log_fields_are_allowlisted_and_suspicious_raw_text_explicitly_redacted(log):
    write(log, attempt(neural={'text': 'https://host/play?token=secret', 'raw': {'secret': 'value'}},
                       resources={'password': 'secret'}, reasons=['secret'], frame_sha256='private',
                       source={'channel':'synthetic', 'kind':'twitch', 'signed_url':'secret'}, trusted=True))
    result = ShadowLog(log).snapshot(NOW)
    serialized = json.dumps(result)
    assert 'secret' not in serialized and 'password' not in serialized and 'signed_url' not in serialized
    row = result['observations'][0]
    assert row['raw_text'] is None and row['raw_text_redacted'] and not row['trusted']


def test_malformed_neural_text_is_not_reparsed_or_fixed(log):
    write(log, attempt(candidate=None, neural={'text': '100[25.00%1'}))
    row = ShadowLog(log).snapshot(NOW)['observations'][0]
    assert row['raw_text'] == '100[25.00%1' and row['candidate'] is None


@pytest.mark.parametrize('candidate', [[100, 25.001], [True, 25], [-1, 25], [100, float('nan')], ['100', 25]])
def test_invalid_saved_candidates_are_marked_not_repaired(log, candidate):
    write(log, attempt(candidate=candidate))
    row = ShadowLog(log).snapshot(NOW)['observations'][0]
    assert row['candidate'] is None and row['candidate_invalid']


def test_large_integer_and_genuine_zero_are_preserved_exactly(log):
    write(log, attempt(candidate=[2**63-1, 99.99]), attempt(2, candidate=[0, 0.0]))
    rows = ShadowLog(log).snapshot(NOW)['observations']
    assert rows[0]['candidate']['exp'] == str(2**63-1)
    assert rows[1]['candidate'] == dict(exp='0', percentage='0.00')


def test_source_failures_replace_status_not_history_and_age_advances(log):
    write(log, dict(type='configuration', interval=15), attempt(),
          attempt(2, status='capture_failed', candidate=None, current=False, received_at=None,
                  attempted_at=(NOW+timedelta(seconds=15)).isoformat(), reasons=['offline_or_unavailable']))
    reader = ShadowLog(log)
    result = reader.snapshot(NOW+timedelta(seconds=20))
    assert result['source_status'] == 'offline_or_unavailable' and not result['stale']
    assert result['observations'][0]['candidate']['exp'] == '100'
    assert result['observations'][1]['candidate'] is None
    assert reader.snapshot(NOW+timedelta(seconds=61))['stale']
    assert reader.snapshot(NOW-timedelta(seconds=1))['stale']


def test_mixed_channels_remain_separate(log):
    write(log, attempt(), attempt(2, source={'kind':'twitch', 'channel':'another'}))
    result = ShadowLog(log).snapshot(NOW)
    assert result['mixed_channels'] and result['channel'] is None
    assert [row['channel'] for row in result['observations']] == ['synthetic', 'another']


def test_history_bytes_lines_and_rows_bounded(log):
    write(log, dict(type='configuration', interval=30), *[attempt(i) for i in range(1, MAX_ROWS+20)])
    result = ShadowLog(log).snapshot(NOW)
    assert len(result['observations']) == MAX_ROWS and result['truncated']
    assert result['observations'][-1]['index'] == MAX_ROWS + 19
    with log.open('wb') as handle:
        handle.write(b'x' * (MAX_BYTES*2) + b'\n' + json.dumps(attempt()).encode() + b'\n')
    result = ShadowLog(log).snapshot(NOW)
    assert result['bytes_read'] <= MAX_BYTES+MAX_LINE+1
    assert result['truncated'] and len(result['observations']) == 1


def test_malformed_marker_limit_reports_omission_and_latest_status(log):
    log.write_text(json.dumps(attempt())+'\n'+'invalid\n'*(MAX_ROWS+1))
    result = ShadowLog(log).snapshot(NOW+timedelta(seconds=60))
    assert result['truncated'] and len(result['observations']) == MAX_ROWS
    assert result['source_status'] == 'malformed_log_line'


def test_failure_without_time_preserves_status_without_inventing_timestamp(log):
    write(log, attempt(status='capture_failed', candidate=None, attempted_at=None, received_at=None))
    result = ShadowLog(log).snapshot(NOW)
    assert result['source_status'] == 'capture_failed' and result['age_seconds'] is None
