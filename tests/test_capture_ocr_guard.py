from exp_tracker.capture import _guard_unverified_exp
from exp_tracker.models import Reading, Recognition
import json
import pytest


def recognition(pixel_text, fallback_text=None):
    attempts = [dict(variant='pixel', text=pixel_text, confidence=0.99 if pixel_text else 0)]
    if fallback_text is not None:
        attempts.append(dict(variant='unrestricted-line', text=fallback_text, confidence=.5))
    return Recognition('accepted', Reading(60, 775303, 64.07), .5, raw={'exp': attempts})


def test_glyph_verified_reading_stays_accepted():
    rec = recognition('775,303[64.07%]')
    assert _guard_unverified_exp(rec, object()).status == 'accepted'


def test_unverified_tesseract_guess_is_not_promoted():
    rec = Recognition('accepted', Reading(60, 778303, 64.07), .5,
                      raw={'exp':[{'variant':'pixel','text':'','confidence':0},
                                  {'variant':'unrestricted-line','text':'778.303(64.07%)', 'confidence':.5}]})
    _guard_unverified_exp(rec, object())
    assert rec.status == 'low_confidence'
    assert rec.reading.current_exp == 778303  # candidate retained for diagnostics
    assert 'unverified_tesseract_exp' in rec.reasons
    assert rec.confidence == 0


def test_absent_profile_preserves_tesseract_fallback():
    rec = recognition('', '775,303[64.07%]')
    assert _guard_unverified_exp(rec, None).status == 'accepted'


def test_pixel_text_must_agree_with_selected_value():
    rec = Recognition('accepted', Reading(60, 778303, 64.07), .99,
                      raw={'exp':[{'variant':'pixel','text':'775,303[64.07%]','confidence':.99}]})
    assert _guard_unverified_exp(rec, object()).status == 'low_confidence'


def test_large_verified_jump_is_not_rate_limited():
    rec = Recognition('accepted', Reading(60, 999999, 82.64), .99,
                      raw={'exp':[{'variant':'pixel','text':'999,999[82.64%]','confidence':.99}]})
    assert _guard_unverified_exp(rec, object()).status == 'accepted'


@pytest.mark.parametrize('pixel_text', [None, 'garbage', '775,303[64.08%]'])
def test_missing_malformed_or_disagreeing_pixel_evidence_is_rejected(pixel_text):
    rec = recognition(pixel_text, '775,303[64.07%]')
    assert _guard_unverified_exp(rec, object()).status == 'low_confidence'


def test_capture_failures_preserve_trusted_state_without_gain_cap(tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace
    from PIL import Image
    from exp_tracker import capture
    from exp_tracker.video import CaptureError
    metrics = pytest.importorskip('exp_tracker.metrics')

    def verified(exp, percent, level=60):
        return Recognition('accepted', Reading(level, exp, percent), .99,
                           raw={'exp': [dict(variant='pixel', text=f'{exp:,}[{percent:.2f}%]', confidence=.99)]})

    events = iter([
        verified(100, 10),
        recognition('', '775,303[64.07%]'),
        Recognition('missing_hud'), Recognition('unreadable'),
        Recognition('low_confidence', Reading(60, 500, 50), .1),
        Recognition('ambiguous'), Recognition('invalid'),
        CaptureError('offline_or_unavailable'), RuntimeError('ocr_failed'),
        verified(0, 0, level=61), verified(99, 9.99),
        verified(999999, 82.64), verified(1000000, 82.65),
    ])
    pending = None

    class Session:
        source_bytes = 0
        def __init__(self, *_args, **_kwargs):
            pass
        def frame(self, **_kwargs):
            nonlocal pending
            pending = next(events)
            if isinstance(pending, CaptureError):
                raise pending
            return SimpleNamespace(sequence=1, png=b'owned-synthetic-frame', received_at='test',
                                   arrived_monotonic=capture.time.monotonic(),
                                   image=lambda: Image.new('RGB', (100, 20)))
        def close(self):
            pass

    def recognize(*_args, **_kwargs):
        if isinstance(pending, Exception):
            raise pending
        return pending

    transitions = []
    validate = capture.validate_transition
    def validate_and_record(previous, current, **options):
        assert 'max_exp_per_second' not in options
        transitions.append((previous, current))
        return validate(previous, current, **options)

    path = tmp_path / 'source.mp4'
    path.write_bytes(b'fixture')
    monkeypatch.setattr(capture.shutil, 'which', lambda _name: 'mock-ffmpeg')
    monkeypatch.setattr(capture.GlyphProfile, 'load', lambda _path: object())
    monkeypatch.setattr(capture, 'VideoSession', Session)
    monkeypatch.setattr(capture, 'recognize', recognize)
    monkeypatch.setattr(capture, 'validate_transition', validate_and_record)
    monkeypatch.setattr(capture.time, 'sleep', lambda _seconds: None)
    monkeypatch.setattr(metrics, 'ResourceMonitor', lambda: SimpleNamespace(snapshot=lambda: {}, close=lambda: None))

    assert capture.main(['--file', str(path), '--glyph-profile', 'provided-profile.json', '--count', '13']) == 0
    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [r['status'] for r in records[:-1]] == [
        'accepted', 'low_confidence', 'missing_hud', 'unreadable', 'low_confidence',
        'ambiguous', 'invalid', 'capture_failed', 'processing_failed',
        'accepted', 'accepted', 'accepted', 'accepted']
    assert all(r.get('transition') is None for r in records[1:9])
    assert records[9]['transition']['status'] == records[10]['transition']['status'] == 'ambiguous'
    assert records[11]['transition']['gained_exp'] == 999899
    assert records[12]['transition']['gained_exp'] == 1
    assert records[-1]['readings_accepted'] == 3
    baseline = transitions[0][1]
    assert transitions[0][0] is None
    assert all(previous is baseline for previous, _ in transitions[1:4])
    assert transitions[4][0] is transitions[3][1]
