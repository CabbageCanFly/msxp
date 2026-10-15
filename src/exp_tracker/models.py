"""Plain data contracts shared by OCR, CLI and future persistence code."""

from dataclasses import dataclass, field
import math


@dataclass(frozen=True)
class Region:
    """Normalized rectangle in its input image; coordinates are in [0, 1]."""

    x0: float
    y0: float
    x1: float
    y1: float

    def __post_init__(self):
        if not (0 <= self.x0 < self.x1 <= 1 and 0 <= self.y0 < self.y1 <= 1):
            raise ValueError("ROI must satisfy 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1")

    def pixels(self, width: int, height: int) -> tuple[int, int, int, int]:
        return (int(self.x0 * width), int(self.y0 * height),
                math.ceil(self.x1 * width), math.ceil(self.y1 * height))


@dataclass(frozen=True)
class Reading:
    level: int
    current_exp: int
    percentage: float


def reading_errors(reading: Reading) -> list[str]:
    errors = []
    if type(reading.level) is not int or not 1 <= reading.level <= 200:
        errors.append("level_out_of_range")
    if type(reading.current_exp) is not int or not 0 <= reading.current_exp <= 2**63 - 1:
        errors.append("exp_out_of_range")
    if (type(reading.percentage) not in (int, float)
            or not math.isfinite(reading.percentage) or not 0 <= reading.percentage < 100):
        errors.append("percentage_out_of_range")
    if reading.current_exp == 0 and reading.percentage != 0:
        errors.append("zero_exp_with_nonzero_percentage")
    return errors


@dataclass
class Recognition:
    status: str
    reading: Reading | None = None
    confidence: float = 0.0
    reasons: list[str] = field(default_factory=list)
    raw: dict[str, list[dict]] = field(default_factory=dict)
    regions: dict[str, Region] = field(default_factory=dict)

