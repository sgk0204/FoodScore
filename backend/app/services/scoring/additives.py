"""Additive reference table and code/alias normalisation.

Labels write the same additive many ways: "INS 211", "E211", "211", "sodium benzoate",
"Preservative (211)". Everything is normalised to one canonical code ("INS 211") before
lookup (edge case 21). The table itself is loaded from ``data/additives_ref.csv`` by
:func:`load_additive_table`; the engine only ever receives the in-memory table.
"""

from __future__ import annotations

import csv
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

RiskTier = Literal["low", "moderate", "high"]

_CODE_RE = re.compile(
    r"\b(?:ins|e)\s*-?\s*(\d{3,4})\s*([a-z])?\b(?:\s*\(\s*[ivx]+\s*\))?",
    re.IGNORECASE,
)
# A bare number inside an additive class name, e.g. "Emulsifier (322)" or "raising agents
# [503(ii), 500(ii)]". Only trusted when the surrounding text names an additive class.
_BARE_CODE_RE = re.compile(r"(?<![\d.,])(\d{3,4})([a-z])?(?:\s*\(\s*[ivx]+\s*\))?(?![\d.%])", re.I)

ADDITIVE_CLASS_WORDS = (
    "emulsifier",
    "stabiliser",
    "stabilizer",
    "raising agent",
    "leavening",
    "preservative",
    "colour",
    "color",
    "acidity regulator",
    "acidulant",
    "antioxidant",
    "thickener",
    "thickening agent",
    "flavour enhancer",
    "flavor enhancer",
    "sweetener",
    "humectant",
    "anticaking",
    "anti-caking",
    "gelling agent",
    "firming agent",
    "glazing agent",
    "improver",
    "dough conditioner",
    "bleaching agent",
)


def normalise_code(text: str) -> str | None:
    """Return the canonical "INS nnn[x]" form of an additive code, or None."""
    m = _CODE_RE.search(text)
    if not m:
        m = re.fullmatch(r"\s*(\d{3,4})\s*([a-z])?\s*(?:\(\s*[ivx]+\s*\))?\s*", text, re.I)
    if not m:
        return None
    number, suffix = m.group(1), (m.group(2) or "").lower()
    return f"INS {number}{suffix}"


def _norm_name(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", text.lower())).strip()


@dataclass(frozen=True, slots=True)
class AdditiveRef:
    code: str
    name: str
    risk_tier: RiskTier
    source_url: str
    aliases: tuple[str, ...] = ()
    notes: str = ""


@dataclass(slots=True)
class AdditiveTable:
    """Lookup by canonical code or by any alias (name)."""

    by_code: dict[str, AdditiveRef] = field(default_factory=dict)
    _alias_index: list[tuple[str, str]] = field(default_factory=list)  # (alias, code)

    @classmethod
    def from_rows(cls, rows: Iterable[AdditiveRef]) -> AdditiveTable:
        table = cls()
        for row in rows:
            table.by_code[row.code] = row
            for alias in (row.name, *row.aliases):
                key = _norm_name(alias)
                if key:
                    table._alias_index.append((key, row.code))
        # Longest alias first so "sodium benzoate" wins over "benzoate".
        table._alias_index.sort(key=lambda pair: -len(pair[0]))
        return table

    def get(self, code: str) -> AdditiveRef | None:
        return self.by_code.get(code)

    def codes_in_text(self, text: str, *, parent: str | None = None) -> list[str]:
        """Find every additive referenced in one ingredient string.

        Matches explicit INS/E codes, bare numbers when the text (or its parent) names an
        additive class, and known names/aliases from the table.
        """
        found: list[str] = []
        for m in _CODE_RE.finditer(text):
            found.append(f"INS {m.group(1)}{(m.group(2) or '').lower()}")

        context = f"{parent or ''} {text}".lower()
        if any(word in context for word in ADDITIVE_CLASS_WORDS):
            stripped = _CODE_RE.sub(" ", text)
            for m in _BARE_CODE_RE.finditer(stripped):
                found.append(f"INS {m.group(1)}{(m.group(2) or '').lower()}")

        normalised = f" {_norm_name(text)} "
        for alias, code in self._alias_index:
            if f" {alias} " in normalised:
                found.append(code)
                normalised = normalised.replace(f" {alias} ", " ")

        return list(dict.fromkeys(found))  # dedupe, keep order

    def __len__(self) -> int:
        return len(self.by_code)


def load_additive_table(path: Path) -> AdditiveTable:
    """Load ``additives_ref.csv`` (columns: code,name,aliases,risk_tier,source_url,notes)."""
    rows: list[AdditiveRef] = []
    with path.open(newline="", encoding="utf-8") as fh:
        for rec in csv.DictReader(fh):
            tier = rec["risk_tier"].strip().lower()
            if tier not in ("low", "moderate", "high"):
                raise ValueError(f"Invalid risk_tier {tier!r} for {rec['code']}")
            code = rec["code"].strip()
            canonical = normalise_code(code) or code.upper()
            aliases = tuple(a.strip() for a in rec.get("aliases", "").split("|") if a.strip())
            rows.append(
                AdditiveRef(
                    code=canonical,
                    name=rec["name"].strip(),
                    risk_tier=tier,  # type: ignore[arg-type]
                    source_url=rec["source_url"].strip(),
                    aliases=aliases,
                    notes=rec.get("notes", "").strip(),
                )
            )
    return AdditiveTable.from_rows(rows)


DEFAULT_ADDITIVES_PATH = Path(__file__).resolve().parents[3] / "data" / "additives_ref.csv"
