"""Strict HUD text parsing. Never substitute likely digits or sample answers."""

import re


def parse_level(text: str) -> int | None:
    text = re.sub(r"\s+", "", text.upper())
    match = re.fullmatch(r"(?:LV[.:]?)?(\d{1,3})", text)
    return int(match[1]) if match else None


def parse_exp(text: str) -> tuple[int, float] | None:
    text = re.sub(r"\s+", "", text.upper())
    # Commas may be absent; malformed grouping or a missing decimal point is rejected.
    match = re.fullmatch(
        r"(?:EXP[.:]?)?([0-9]+|[0-9]{1,3}(?:,[0-9]{3})+|[0-9]{1,3}(?:\.[0-9]{3})+)"
        r"[\[(](\d{1,3}\.\d{2})%[\])]", text
    )
    if not match:
        return None
    return int(match[1].replace(",", "").replace(".", "")), float(match[2])

