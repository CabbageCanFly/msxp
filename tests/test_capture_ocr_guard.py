from exp_tracker.capture import _guard_unverified_exp
from exp_tracker.models import Reading, Recognition


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
