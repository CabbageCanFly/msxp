"""Calibrated, bounded pixel-glyph matching for a single EXP text line.

Profiles contain font cells, not readings or screen coordinates. No game font
assets ship with this module. A profile must be calibrated on permitted crops.
Level recognition remains a separate concern because it uses another font.
"""

from dataclasses import dataclass
import json
from pathlib import Path

from PIL import Image, ImageChops

from .parsing import parse_exp


SYMBOLS = "0123456789,[.]%"


def mask(image: Image.Image, threshold: int, *, color: bool = False,
         green_excess: bool = False) -> int:
    if green_excess:
        rgb = image.convert("RGB").tobytes()
        return sum(1 << (i // 3) for i in range(0, len(rgb), 3)
                   if 2 * rgb[i + 1] - rgb[i] - rgb[i + 2] >= 2 * threshold)
    if color:
        r, g, b = image.convert("RGB").split()
        image = ImageChops.lighter(ImageChops.lighter(r, g), b)
    else:
        image = image.convert("L")
    return sum(1 << i for i, value in enumerate(image.tobytes()) if value > threshold)


@dataclass(frozen=True)
class GlyphProfile:
    height: int
    widths: dict[str, int]
    templates: dict[str, tuple[int, ...]]
    digit_threshold: int = 175
    punctuation_threshold: int = 100
    bracket_mode: str = "max_channel"

    def __post_init__(self):
        if self.bracket_mode not in ("max_channel", "green_excess"):
            raise ValueError("unsupported bracket mask")
        if not 3 <= self.height <= 32 or set(self.widths) != set(SYMBOLS):
            raise ValueError("invalid glyph profile geometry or alphabet")
        if set(self.templates) != set(SYMBOLS):
            raise ValueError("profile must cover every digit and punctuation symbol")
        if not all(1 <= w <= 32 for w in self.widths.values()):
            raise ValueError("invalid glyph cell width")
        if len({self.widths[c] for c in "0123456789"}) != 1:
            raise ValueError("this recognizer requires monospaced digits")
        for char, values in self.templates.items():
            limit = 1 << (self.widths[char] * self.height)
            if not 1 <= len(values) <= 32 or any(not 0 < v < limit for v in values):
                raise ValueError("invalid or empty glyph template")
        if not all(0 <= t <= 255 for t in (self.digit_threshold, self.punctuation_threshold)):
            raise ValueError("invalid mask threshold")

    @classmethod
    def load(cls, path: Path) -> "GlyphProfile":
        if path.stat().st_size > 1024 * 1024:
            raise ValueError("glyph profile exceeds 1 MiB limit")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            version = data.get("version")
            if version not in (1, 2):
                raise ValueError("unsupported glyph profile version")
            mode = "max_channel" if version == 1 else data.get("bracket_mode")
            if version == 2 and mode != "green_excess":
                raise ValueError("unsupported version 2 bracket mode")
            return cls(data["height"], data["widths"],
                       {c: tuple(v) for c, v in data["templates"].items()},
                       data["digit_threshold"], data["punctuation_threshold"], mode)
        except (AttributeError, KeyError, TypeError) as error:
            raise ValueError("invalid glyph profile structure") from error


def _layouts():
    # Grammar, not expected values: 1..12 EXP digits, optional thousands groups,
    # one/two percentage digits and exactly two decimal places. Punctuation
    # must be seen; never reconstruct a missing bracket or decimal separator.
    for count in range(1, 13):
        formats = {"D" * count}
        if count > 3:
            groups = ["D" * (count % 3 or 3)] + ["DDD"] * ((count - 1) // 3)
            formats.add(",".join(groups))
        for number in sorted(formats):
            for percent_digits in (1, 2):
                yield number + "[" + "D" * percent_digits + ".DD%]"


def match_exp(crop: Image.Image, profile: GlyphProfile, *, scales=(1.0,)) -> dict:
    """Return an OCR attempt with diagnostic scores; ambiguity is a veto.

    At most three changed pixels per digit and a two-pixel margin to the next
    digit class are allowed. These are geometric scores, not probabilities.
    Integer resampling can be requested explicitly; compressed fractional
    scales need their own calibration. Work is bounded to a tightly cropped HUD.
    """
    if crop.width > 512 or crop.height > 96:
        return dict(variant="pixel", text="", confidence=0, reason="pixel_roi_too_large")
    if not scales or len(scales) > 4 or any(not .5 <= s <= 4 for s in scales):
        raise ValueError("pixel scales must contain 1..4 values between .5 and 4")
    matches = {}
    digit_width = profile.widths["0"]
    for scale in scales:
        image = crop.resize((round(crop.width / scale), round(crop.height / scale)),
                            Image.Resampling.NEAREST) if scale != 1 else crop
        if image.width > 512 or image.height > 96:
            continue
        cache = {}
        bands = {}
        gray = image.convert("L")
        for y in range(image.height - profile.height + 1):
            columns = [0] * image.width
            for i, value in enumerate(gray.crop((0, y, image.width, y + profile.height)).tobytes()):
                columns[i % image.width] += value > profile.digit_threshold
            prefix = [0]
            for count in columns:
                prefix.append(prefix[-1] + count)
            bands[y] = prefix

        def cell(x, y, symbol):
            key = x, y, "D" if symbol == "D" else symbol
            if key not in cache:
                digit = symbol == "D"
                width = digit_width if digit else profile.widths[symbol]
                patch = image.crop((x, y, x + width, y + profile.height))
                colored = symbol in "[]"
                value = mask(patch, profile.punctuation_threshold if colored else profile.digit_threshold,
                             color=colored,
                             green_excess=colored and profile.bracket_mode == "green_excess")
                candidates = "0123456789" if digit else symbol
                ranked = sorted((min((value ^ template).bit_count()
                                     for template in profile.templates[c]), c) for c in candidates)
                distance, char = ranked[0]
                margin = ranked[1][0] - distance if digit else 99
                # A missing punctuation mask cannot be explained by a blank cell.
                # Green bracket pixels vary slightly under video compression.
                limit = 4 if colored and profile.bracket_mode == "green_excess" else 3
                cache[key] = (char, distance) if value and distance <= limit and margin >= 2 else None
            return cache[key]

        for layout in _layouts():
            widths = [digit_width if c == "D" else profile.widths[c] for c in layout]
            total_width = sum(widths)
            if total_width > image.width:
                continue
            # A generous ROI is allowed but no unbounded full-frame scan.
            offsets = []
            position = 0
            for symbol, width in zip(layout, widths):
                offsets.append((position, symbol))
                position += width
            # Check punctuation before digits: most wrong alignments fail cheaply.
            order = sorted(range(len(offsets)), key=lambda i: offsets[i][1] == "D")
            for y in range(image.height - profile.height + 1):
                for x in range(image.width - total_width + 1):
                    # Reject suffix matches and clipped/misbound lines. Text
                    # elsewhere on this same baseline cannot be silently dropped.
                    prefix = bands[y]
                    if prefix[x] > 2 or prefix[-1] - prefix[x + total_width] > 2:
                        continue
                    chars, distance = [""] * len(layout), 0
                    for i in order:
                        offset, symbol = offsets[i]
                        found = cell(x + offset, y, symbol)
                        if found is None:
                            break
                        chars[i] = found[0]
                        distance += found[1]
                    else:
                        text = "".join(chars)
                        if parse_exp(text) is not None:
                            score = 1 - distance / (total_width * profile.height)
                            matches[text] = max(score, matches.get(text, 0))
    if len(matches) > 1:
        return dict(variant="pixel", text="", confidence=0, veto=True,
                    reason="conflicting_pixel_readings", candidates=sorted(matches))
    if not matches:
        return dict(variant="pixel", text="", confidence=0, reason="no_complete_pixel_match")
    text, score = next(iter(matches.items()))
    return dict(variant="pixel", text=text, confidence=score, score_kind="glyph_pixel_agreement")
