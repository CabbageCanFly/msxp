"""HUD-context discovery and small-field Tesseract OCR.

Explicit field ROIs are trusted user calibration; automatic discovery requires
HP, MP, EXP and LV in the geometry of the game status panel.
"""

from pathlib import Path
import os
import re
import shutil

from PIL import Image, ImageOps
import pytesseract
from pytesseract import Output

from .models import Reading, Recognition, Region, reading_errors
from .parsing import parse_exp, parse_level
from .glyphs import GlyphProfile, match_exp


def configure_tesseract() -> None:
    command = os.environ.get("TESSERACT_CMD") or shutil.which("tesseract")
    if not command:
        candidate = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Tesseract-OCR/tesseract.exe"
        if candidate.is_file():
            command = str(candidate)
    if not command:
        raise RuntimeError("Install Tesseract 5 with English data or set TESSERACT_CMD")
    pytesseract.pytesseract.tesseract_cmd = command


def _ocr(image: Image.Image, psm: int, whitelist: str = "") -> list[dict]:
    config = f"--psm {psm}"
    if whitelist:
        config += f" -c tessedit_char_whitelist={whitelist}"
    data = pytesseract.image_to_data(image, lang="eng", config=config,
                                     output_type=Output.DICT, timeout=10)
    return [dict(text=t.strip(), confidence=max(0, float(data["conf"][i]) / 100),
                 x=data["left"][i], y=data["top"][i],
                 width=data["width"][i], height=data["height"][i])
            for i, t in enumerate(data["text"]) if t.strip()]


def _label(token: dict) -> str:
    return re.sub(r"[^A-Z]", "", token["text"].upper())


def discover_regions(image: Image.Image, search: Region) -> list[dict[str, Region]]:
    """Locate HP/MP/EXP rows, then bind LV to that same status panel.

    Search can cover the whole frame. Multiple valid panels are ambiguous.
    The classic HUD's consistent HP->MP->EXP spacing is a layout assumption.
    """
    box = search.pixels(*image.size)
    crop = image.crop(box).convert("L")
    scale = 3
    crop = crop.resize((crop.width * scale, crop.height * scale), Image.Resampling.BICUBIC)
    tokens = _ocr(crop.point(lambda p: 0 if p > 160 else 255), 11)
    result = []
    for hp in (t for t in tokens if _label(t) == "HP"):
        for mp in (t for t in tokens if _label(t) == "MP" and t["x"] > hp["x"]):
            step = mp["x"] - hp["x"]
            row_height = max(hp["height"], mp["height"])
            if abs(mp["y"] - hp["y"]) > row_height or step < 3 * row_height:
                continue
            exps = [t for t in tokens if _label(t) == "EXP"
                    and .65 * step < t["x"] - mp["x"] < 1.5 * step
                    and abs(t["y"] - hp["y"]) < row_height]
            levels = [t for t in tokens if _label(t) == "LV"
                      and 1.1 * step < hp["x"] - t["x"] < 2.7 * step
                      and abs(t["y"] - hp["y"]) < 1.5 * row_height]
            for exp in exps:
                for lv in levels:
                    number = [t for t in tokens if t["x"] > lv["x"] + lv["width"]
                              and t["x"] < lv["x"] + 4 * lv["height"]
                              and abs(t["y"] - lv["y"]) < lv["height"]]
                    exp_text = [t for t in tokens
                                if exp["x"] + exp["width"] <= t["x"] < exp["x"] + 1.2 * step
                                and abs(t["y"] - hp["y"]) < row_height]
                    if not number or not exp_text:
                        continue

                    def region(group: list[dict], pad: float) -> Region:
                        left = min(t["x"] for t in group) / scale + box[0] - pad
                        top = min(t["y"] for t in group) / scale + box[1] - pad
                        right = max(t["x"] + t["width"] for t in group) / scale + box[0] + pad
                        bottom = max(t["y"] + t["height"] for t in group) / scale + box[1] + pad
                        return Region(max(0, left / image.width), max(0, top / image.height),
                                      min(1, right / image.width), min(1, bottom / image.height))

                    result.append({"level": region(number, 3), "exp": region(exp_text, 2)})
    return result


def _read_field(crop: Image.Image, field: str, debug: Path | None) -> list[dict]:
    gray = crop.convert("L").resize((crop.width * 5, crop.height * 5), Image.Resampling.BICUBIC)
    variants = (("threshold160", gray.point(lambda p: 0 if p > 160 else 255), 7),
                ("threshold180", gray.point(lambda p: 0 if p > 180 else 255), 7),
                ("threshold200", gray.point(lambda p: 0 if p > 200 else 255), 7)) if field == "level" else (
                    ("inverted", ImageOps.invert(gray), 13),
                    ("threshold140", gray.point(lambda p: 0 if p > 140 else 255), 13),
                    # The numeric whitelist can collapse word confidence to zero.
                    # An unrestricted line pass still must satisfy the strict parser.
                    ("unrestricted-line", ImageOps.invert(gray), 7))
    attempts = []
    for name, processed, psm in variants:
        processed = ImageOps.expand(processed, 10, fill=255)
        if debug:
            processed.save(debug / f"{field}-{name}.png")
        whitelist = "" if name == "unrestricted-line" else "0123456789" if field == "level" else "0123456789.,[]()%"
        tokens = _ocr(processed, psm, whitelist)
        attempts.append(dict(variant=name, text="".join(t["text"] for t in tokens),
                             confidence=min((t["confidence"] for t in tokens), default=0)))
    return attempts


def recognize(image: Image.Image, *, regions: dict[str, Region] | None = None,
              search: Region = Region(0, .7, 1, 1), min_confidence: float = .4,
              debug_dir: Path | None = None, glyph_profile: GlyphProfile | None = None,
              pixel_scales: tuple[float, ...] = (1.0,)) -> Recognition:
    """Return a visual reading, not proof of identity or a tracking observation.

    Tesseract confidence is an uncalibrated engine score. Conflicting plausible
    variants are rejected. Missing and obscured HUDs cannot reliably be distinguished.
    """
    if not 0 <= min_confidence <= 1:
        raise ValueError("min_confidence must be between 0 and 1")
    configure_tesseract()
    if regions is None:
        candidates = discover_regions(image, search)
        if not candidates:
            return Recognition("missing_hud", reasons=["no_complete_hud_context; may be obscured or unreadable"])
        if len(candidates) != 1:
            return Recognition("ambiguous", reasons=["multiple_hud_candidates; configure_explicit_rois"])
        regions = candidates[0]
    if set(regions) != {"level", "exp"}:
        raise ValueError("Configure both level and exp ROIs")
    if debug_dir:
        debug_dir.mkdir(parents=True, exist_ok=True)
    raw = {}
    parsed = {}
    for field, region in regions.items():
        crop = image.crop(region.pixels(*image.size))
        if debug_dir:
            crop.save(debug_dir / f"{field}-crop.png")
        attempt = match_exp(crop, glyph_profile, scales=pixel_scales) if field == "exp" and glyph_profile else None
        if attempt and attempt.get("veto"):
            raw[field] = [attempt]
            return Recognition("ambiguous", reasons=[attempt["reason"]], raw=raw, regions=regions)
        if attempt and parse_exp(attempt["text"]) is not None:
            raw[field] = [attempt]
        else:
            raw[field] = ([attempt] if attempt else []) + _read_field(crop, field, debug_dir)
        parser = parse_level if field == "level" else parse_exp
        options = [(parser(a["text"]), a["confidence"]) for a in raw[field]]
        options = [(value, conf) for value, conf in options if value is not None]
        if not options:
            return Recognition("unreadable", reasons=[f"cannot_parse_{field}"], raw=raw, regions=regions)
        plausible = {value for value, conf in options if conf >= min_confidence}
        if len(plausible) > 1:
            return Recognition("ambiguous", reasons=[f"conflicting_{field}_variants"], raw=raw, regions=regions)
        parsed[field] = max(options, key=lambda v: v[1])
    level, lc = parsed["level"]
    (exp, percent), ec = parsed["exp"]
    reading = Reading(level, exp, percent)
    confidence = min(lc, ec)
    errors = reading_errors(reading)
    status = "invalid" if errors else "low_confidence" if confidence < min_confidence else "accepted"
    return Recognition(status, reading, confidence,
                       errors or (["ocr_score_below_threshold"] if status == "low_confidence" else []),
                       raw, regions)
