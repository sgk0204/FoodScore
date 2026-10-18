from __future__ import annotations

import pytest

from app.services.scoring import parse_ingredients
from app.services.scoring.additives import normalise_code
from app.services.scoring.ingredients import classify_nova


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("INS 211", "INS 211"),
        ("ins211", "INS 211"),
        ("E211", "INS 211"),
        ("E-211", "INS 211"),
        ("211", "INS 211"),
        ("INS 322(i)", "INS 322"),
        ("E150d", "INS 150d"),
        ("INS 160A", "INS 160a"),
        ("sugar", None),
    ],
)
def test_normalise_code(text, code):
    assert normalise_code(text) == code


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Preservative (INS 211)", ["INS 211"]),
        ("sodium benzoate", ["INS 211"]),
        ("Emulsifier (322)", ["INS 322"]),
        ("Raising agents [503(ii), 500(ii)]", ["INS 503", "INS 500"]),
        ("Soy lecithin", ["INS 322"]),
        ("Contains added flavour (artificial flavouring substances)", ["X-ARTIFICIAL-FLAVOUR"]),
        ("Wheat flour 70%", []),
        ("Salt 1.2", []),
    ],
)
def test_codes_in_text(additives, text, expected):
    assert additives.codes_in_text(text) == expected


def test_alias_table_maps_all_spellings_to_one_code(additives):
    # edge case 21
    for spelling in ("sodium benzoate", "E211", "INS 211", "Preservative (211)"):
        assert additives.codes_in_text(spelling) == ["INS 211"]


def test_parse_ingredients_flattens_nested_lists():
    ings = parse_ingredients(
        ["Refined wheat flour (maida) (45%)", "Filling (sugar, palm oil, cocoa (5%))", "Salt"]
    )
    names = [(i.name, i.parent, i.position) for i in ings]
    assert names == [
        ("refined wheat flour", None, 0),
        ("maida", "refined wheat flour", 0),
        ("filling", None, 1),
        ("sugar", "filling", 1),
        ("palm oil", "filling", 1),
        ("cocoa", "filling", 1),
        ("salt", None, 2),
    ]


def test_parse_ingredients_accepts_one_raw_label_string():
    ings = parse_ingredients(["Sugar, wheat flour, edible vegetable oil (palm oil), salt."])
    assert [i.name for i in ings if i.parent is None] == [
        "sugar",
        "wheat flour",
        "edible vegetable oil",
        "salt",
    ]


def test_parse_ingredients_accepts_parent_arrow_format():
    ings = parse_ingredients(["Wheat flour", "Filling > sugar", "Filling > palm oil", "Salt"])
    assert [(i.name, i.parent, i.position) for i in ings] == [
        ("wheat flour", None, 0),
        ("filling", None, 1),
        ("sugar", "filling", 1),
        ("palm oil", "filling", 1),
        ("salt", None, 2),
    ]


@pytest.mark.parametrize(
    ("items", "additive_count", "concern", "nova"),
    [
        ([], 0, False, 3),
        (["Toor dal"], 0, False, 1),
        (["Rice", "Moong dal"], 0, False, 1),
        (["Groundnut oil"], 0, False, 2),
        (["Peanuts", "Salt"], 0, False, 3),
        (["Potato", "Oil", "Salt", "Flavour enhancer"], 0, False, 4),
        (["Water", "Sugar"], 0, True, 4),
        (["Milk", "Sugar"], 2, False, 4),
    ],
)
def test_classify_nova(items, additive_count, concern, nova):
    assert (
        classify_nova(parse_ingredients(items), additive_count=additive_count, has_concern=concern)
        == nova
    )


def test_additive_table_loaded_with_sources(additives):
    assert len(additives) > 50
    for ref in additives.by_code.values():
        assert ref.source_url.startswith("https://"), ref.code
