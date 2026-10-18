"""Parsing and unit conversion for printed nutrition values (edge cases 13–15).

Parser rules (documented on the methodology page and unit-tested):
- "Nil", "None", "-", "–", "Traces", "ND" → 0
- "<x" → x / 2   (a "less than" claim is scored as half the limit)
- decimal comma "5,2" → 5.2
- kJ → kcal ÷ 4.184; mg → g ÷ 1000; mcg → g ÷ 1 000 000
- sodium (g) × 2.5 → salt (g)
"""

from __future__ import annotations

import re

KJ_PER_KCAL = 4.184
SALT_PER_SODIUM = 2.5

_ZERO_WORDS = {"nil", "none", "-", "–", "—", "traces", "trace", "nd", "not detected", "0"}
_NUM_RE = re.compile(
    r"(?P<lt><\s*|less than\s*)?(?P<num>\d+(?:[.,]\d+)?)\s*(?P<unit>kcal|kj|mcg|µg|ug|mg|g|ml|cal)?",
    re.IGNORECASE,
)


def parse_amount(raw: str | None) -> tuple[float, str | None] | None:
    """Parse printed text into (value, unit). Returns None when nothing numeric is present.

    When both kcal and kJ are printed ("2008 kJ / 480 kcal"), kcal is preferred.
    """
    if raw is None:
        return None
    text = raw.strip().lower()
    if not text:
        return None
    if text.strip(" .") in _ZERO_WORDS or re.fullmatch(r"(nil|traces?|nd)\s*\w*", text):
        return 0.0, None

    matches = list(_NUM_RE.finditer(text))
    if not matches:
        return None
    chosen = next((m for m in matches if (m.group("unit") or "").lower() == "kcal"), matches[0])
    value = float(chosen.group("num").replace(",", "."))
    if chosen.group("lt"):
        value /= 2
    unit = (chosen.group("unit") or "").lower() or None
    unit = {"µg": "mcg", "ug": "mcg", "kj": "kJ", "cal": "kcal"}.get(unit or "", unit)
    return value, unit


def to_grams(value: float, unit: str | None) -> float:
    if unit == "mg":
        return value / 1000
    if unit == "mcg":
        return value / 1_000_000
    return value


def to_kcal(value: float, unit: str | None) -> float:
    if unit == "kJ":
        return value / KJ_PER_KCAL
    return value


def sodium_to_salt(sodium_g: float) -> float:
    return sodium_g * SALT_PER_SODIUM
