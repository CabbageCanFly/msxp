"""Shared EXP trust gate; legacy callers without a profile stay diagnostic."""

from .parsing import parse_exp


def guard_unverified_exp(result, profile):
    """Never promote a Tesseract-only EXP guess when a glyph profile was supplied.

    Preserve the candidate and raw attempts for debugging, but only glyph-verified
    EXP may advance live tracking state. This does not impose an EXP gain-rate cap.
    """
    if profile is None or result.status != "accepted":
        return result
    pixel_matches = [parse_exp(a.get("text") or "")
                     for a in result.raw.get("exp", []) if a.get("variant") == "pixel"]
    verified = result.reading is not None and (
        result.reading.current_exp, result.reading.percentage) in pixel_matches
    if not verified:
        result.status = "low_confidence"
        result.confidence = 0.0
        result.reasons.append("unverified_tesseract_exp")
    return result
