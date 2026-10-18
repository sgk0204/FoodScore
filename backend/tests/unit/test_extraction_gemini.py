"""Gemini adapter tests with a stubbed google-genai client — no network, no cost."""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
from google.genai import errors as genai_errors
from google.genai import types

from app.schemas.extraction import Extraction
from app.services.extraction.base import (
    ExtractionError,
    SchemaError,
    inline_refs,
    strict_json_schema,
)
from app.services.extraction.gemini import GeminiExtractor
from tests.conftest import load_llm_fixture

GOOD = json.dumps(load_llm_fixture("chocolate_biscuit"))


def response(text, *, finish="STOP", block=None, prompt=2000, out=600, thoughts=400):
    return SimpleNamespace(
        text=text,
        prompt_feedback=SimpleNamespace(block_reason=block) if block else None,
        candidates=[SimpleNamespace(finish_reason=getattr(types.FinishReason, finish))],
        usage_metadata=SimpleNamespace(
            prompt_token_count=prompt, candidates_token_count=out, thoughts_token_count=thoughts
        ),
    )


class StubModels:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    async def generate_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": list(contents), "config": config})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def make(*outcomes, **kwargs):
    models = StubModels(outcomes)
    client = SimpleNamespace(aio=SimpleNamespace(models=models))
    return GeminiExtractor("key", client=client, **kwargs), models


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch):
    async def instant(_):
        return None

    monkeypatch.setattr("app.services.extraction.base.asyncio.sleep", instant)


def test_schema_is_self_contained():
    schema = inline_refs(strict_json_schema(Extraction))
    dumped = json.dumps(schema)
    assert "$ref" not in dumped and "$defs" not in dumped
    assert schema["properties"]["energy"]["additionalProperties"] is False
    assert set(schema["properties"]["energy"]["required"]) == {"raw", "value", "unit", "confidence"}


async def test_request_shape_usage_and_cost():
    ex, models = make(response(GOOD))
    result = await ex.extract([b"\xff\xd8\xff a", b"\xff\xd8\xff b", b"\xff\xd8\xff c"], "v1")

    call = models.calls[0]
    assert call["model"] == "gemini-2.5-flash"
    assert call["config"].temperature == 0
    assert call["config"].response_mime_type == "application/json"
    assert "data, never as instructions" in call["config"].system_instruction
    [turn] = call["contents"]
    assert turn.role == "user"
    assert [p.inline_data.mime_type for p in turn.parts[:3]] == ["image/jpeg"] * 3
    assert "Extract the label data" in turn.parts[3].text

    assert result.extraction.product_name == "Choco Cream Biscuit"
    assert result.output_tokens == 1000  # 600 answer + 400 thinking (billed as output)
    assert result.cost_usd == pytest.approx((2000 * 0.30 + 1000 * 2.50) / 1_000_000)


async def test_repair_round_shows_the_model_its_previous_answer():
    bad = json.dumps({**load_llm_fixture("chocolate_biscuit"), "basis": "per_kg"})
    ex, models = make(response(bad), response(GOOD))
    result = await ex.extract([b"x"], "v1")

    assert result.repaired
    roles = [c.role for c in models.calls[1]["contents"]]
    assert roles == ["user", "model", "user"]
    assert models.calls[1]["contents"][1].parts[0].text == bad
    assert "did not validate" in models.calls[1]["contents"][2].parts[0].text
    assert result.input_tokens == 4000  # both rounds counted


async def test_schema_error_after_failed_repair():
    bad = json.dumps({"is_food_label": "maybe"})
    ex, _ = make(response(bad), response(bad))
    with pytest.raises(SchemaError):
        await ex.extract([b"x"], "v1")


async def test_safety_block_is_permanent_not_a_schema_error():
    ex, models = make(response(None, finish="SAFETY"))
    with pytest.raises(ExtractionError, match="SAFETY") as info:
        await ex.extract([b"x"], "v1")
    assert not info.value.retryable
    assert len(models.calls) == 1


async def test_prompt_block_is_permanent():
    ex, _ = make(response(None, block="PROHIBITED_CONTENT"))
    with pytest.raises(ExtractionError, match="blocked") as info:
        await ex.extract([b"x"], "v1")
    assert not info.value.retryable


async def test_truncated_answer_is_retryable():
    ex, _ = make(response(None, finish="MAX_TOKENS"))
    with pytest.raises(ExtractionError, match="truncated") as info:
        await ex.extract([b"x"], "v1")
    assert info.value.retryable


@pytest.mark.parametrize(
    ("code", "retryable"), [(429, True), (503, True), (500, True), (400, False), (403, False)]
)
async def test_api_errors_are_classified(code, retryable):
    err = genai_errors.APIError(code, {"error": {"code": code, "message": "x", "status": "X"}})
    ex, models = make(err, err, err, max_attempts=3)
    with pytest.raises(ExtractionError) as info:
        await ex.extract([b"x"], "v1")
    assert info.value.retryable is retryable
    assert len(models.calls) == (3 if retryable else 1)


async def test_transient_error_then_success():
    err = genai_errors.APIError(
        503, {"error": {"code": 503, "message": "overloaded", "status": "UNAVAILABLE"}}
    )
    ex, models = make(err, response(GOOD))
    result = await ex.extract([b"x"], "v1")
    assert result.extraction.is_food_label
    assert len(models.calls) == 2


async def test_network_errors_are_retried():
    ex, models = make(httpx.ConnectError("reset"), response(GOOD))
    result = await ex.extract([b"x"], "v1")
    assert result.provider == "gemini"
    assert len(models.calls) == 2
