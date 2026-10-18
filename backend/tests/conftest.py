from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.scoring import DEFAULT_ADDITIVES_PATH, AdditiveTable, load_additive_table

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def additives() -> AdditiveTable:
    return load_additive_table(DEFAULT_ADDITIVES_PATH)


def load_llm_fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / "llm_responses" / f"{name}.json").read_text(encoding="utf-8"))
