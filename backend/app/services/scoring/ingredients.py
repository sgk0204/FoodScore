"""Ingredient-list parsing, rule matching and NOVA classification.

All rules are plain substring/regex checks over lower-cased ingredient names so they are
easy to read, test and explain.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from app.services.scoring.models import Ingredient

PHO_TERMS = (
    "partially hydrogenated",
    "partially-hydrogenated",
    "hydrogenated vegetable oil",
    "hydrogenated vegetable fat",
    "hydrogenated fat",
    "hydrogenated oil",
    "vanaspati",
    "bakery shortening",
)
PALM_TERMS = ("palm oil", "palmolein", "palm olein", "palm kernel", "palm fat", "palm stearin")
ADDED_SUGAR_TERMS = (
    "sugar",
    "glucose syrup",
    "liquid glucose",
    "invert syrup",
    "invert sugar",
    "corn syrup",
    "high fructose",
    "fructose",
    "dextrose",
    "sucrose",
    "maltose",
    "jaggery",
    "honey",
    "golden syrup",
    "molasses",
)
# "sugar" also appears in "no added sugar" / "sugar alcohol" — exclude those phrasings.
_SUGAR_EXCLUDE = ("no added sugar", "sugar free", "sugar-free", "sugar alcohol")
REFINED_FLOUR_TERMS = ("maida", "refined wheat flour", "refined flour", "all purpose flour")

# Markers of ultra-processing (NOVA group 4): industrial ingredients and cosmetic additives.
UPF_MARKERS = (
    "flavour",
    "flavor",
    "flavouring",
    "emulsifier",
    "sweetener",
    "colour",
    "color",
    "hydrogenated",
    "maltodextrin",
    "invert",
    "glucose syrup",
    "corn syrup",
    "high fructose",
    "protein isolate",
    "hydrolysed",
    "hydrolyzed",
    "modified starch",
    "flavour enhancer",
    "humectant",
    "thickener",
    "stabiliser",
    "stabilizer",
    "glazing agent",
    "interesterified",
)
CULINARY_INGREDIENTS = (
    "oil",
    "ghee",
    "butter",
    "sugar",
    "salt",
    "honey",
    "jaggery",
    "vinegar",
    "starch",
)
PROCESSED_MARKERS = ("salt", "sugar", "oil", "vinegar", "ghee", "butter", "syrup", "brine")

_SPLIT_DEPTH_RE = re.compile(r"[,;]")
_PERCENT_RE = re.compile(r"^\s*\d+(?:[.,]\d+)?\s*%\s*$")
_WS_RE = re.compile(r"\s+")


def _clean(text: str) -> str:
    text = text.strip().strip(".").strip()
    text = re.sub(r"\(\s*\d+(?:[.,]\d+)?\s*%\s*\)", "", text)  # "(12%)"
    text = re.sub(r"\d+(?:[.,]\d+)?\s*%", "", text)
    return _WS_RE.sub(" ", text).strip()


def _split_top_level(text: str) -> list[str]:
    """Split on commas/semicolons that are not inside (), [] or {}."""
    parts: list[str] = []
    depth = 0
    buf: list[str] = []
    for ch in text:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth = max(0, depth - 1)
        if depth == 0 and _SPLIT_DEPTH_RE.match(ch):
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return [p for p in (s.strip() for s in parts) if p]


def _split_parent_children(item: str) -> tuple[str, list[str]]:
    """'Filling (sugar, palm oil)' -> ('Filling', ['sugar', 'palm oil']).

    Handles several bracket groups, e.g. 'Wheat flour (maida) (45%)'.
    """
    head: list[str] = []
    children: list[str] = []
    depth = 0
    group: list[str] = []
    for ch in item:
        if ch in "([{":
            if depth > 0:
                group.append(ch)
            depth += 1
        elif ch in ")]}" and depth > 0:
            depth -= 1
            if depth == 0:
                children.extend(_split_top_level("".join(group)))
                group = []
            else:
                group.append(ch)
        elif depth > 0:
            group.append(ch)
        else:
            head.append(ch)
    if group:  # unbalanced bracket: keep the text as a child rather than dropping it
        children.extend(_split_top_level("".join(group)))
    return "".join(head).strip(), children


def parse_ingredients(items: Iterable[str]) -> list[Ingredient]:
    """Turn extracted ingredient strings into a flat, ordered list with parent links.

    Accepts either one string per ingredient (as the LLM returns) or a single raw label
    string. Sub-ingredients may be written as "Parent > child" or "Parent (child, child)".
    Nested sub-ingredients count for flags (edge case 22).
    """
    raw_items: list[str] = []
    for item in items:
        if item and item.strip():
            raw_items.extend(_split_top_level(item) if "," in item and ">" not in item else [item])

    result: list[Ingredient] = []
    position = -1
    last_parent: str | None = None
    for item in raw_items:
        if ">" in item:
            parent_raw, child_raw = (s.strip() for s in item.split(">", 1))
            parent_name = _clean(parent_raw).lower()
            if parent_name != last_parent:
                position += 1
                result.append(Ingredient(name=parent_name, raw=parent_raw, position=position))
                last_parent = parent_name
            child = _clean(child_raw)
            if child:
                result.append(
                    Ingredient(
                        name=child.lower(), raw=child_raw, parent=parent_name, position=position
                    )
                )
            continue

        last_parent = None
        position += 1
        head, children = _split_parent_children(item)
        head_clean = _clean(head)
        # Keep the full raw text on the parent so codes like "Emulsifier (322)" stay visible.
        result.append(
            Ingredient(name=(head_clean or _clean(item)).lower(), raw=item, position=position)
        )
        for child in children:
            if _PERCENT_RE.match(child):
                continue
            sub_head, grandchildren = _split_parent_children(child)
            for text in (sub_head, *grandchildren):
                cleaned = _clean(text)
                if cleaned and not _PERCENT_RE.match(cleaned):
                    result.append(
                        Ingredient(
                            name=cleaned.lower(),
                            raw=text.strip(),
                            parent=head_clean.lower() or None,
                            position=position,
                        )
                    )
    return result


def _contains(name: str, terms: Iterable[str]) -> bool:
    return any(term in name for term in terms)


def is_pho(ing: Ingredient) -> bool:
    return _contains(ing.name, PHO_TERMS)


def is_palm(ing: Ingredient) -> bool:
    return _contains(ing.name, PALM_TERMS)


def is_added_sugar(ing: Ingredient) -> bool:
    if _contains(ing.name, _SUGAR_EXCLUDE):
        return False
    return _contains(ing.name, ADDED_SUGAR_TERMS)


def is_refined_flour(ing: Ingredient) -> bool:
    return _contains(ing.name, REFINED_FLOUR_TERMS)


def classify_nova(ingredients: list[Ingredient], *, additive_count: int, has_concern: bool) -> int:
    """Heuristic NOVA group from the ingredient list (documented on the methodology page).

    4 — any ultra-processing marker, a moderate/high-concern additive, or 2+ additives
    3 — several ingredients including salt, sugar, oil or similar
    2 — a single processed culinary ingredient (oil, ghee, sugar, salt...)
    1 — single whole food, or only whole foods (rice, dal, plain nuts)
    Unknown ingredient list defaults to 3 (neutral).
    """
    if not ingredients:
        return 3
    names = [i.name for i in ingredients]
    if has_concern or additive_count >= 2 or any(_contains(n, UPF_MARKERS) for n in names):
        return 4
    top_level = [i for i in ingredients if i.parent is None]
    if len(top_level) == 1:
        only = top_level[0].name
        return 2 if _contains(only, CULINARY_INGREDIENTS) else 1
    if additive_count >= 1 or any(_contains(n, PROCESSED_MARKERS) for n in names):
        return 3
    return 1
