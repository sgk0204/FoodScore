"""Extraction adapter tests with a stubbed SDK client — no network, no cost."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.schemas.extraction import Extraction
from app.services.extraction.base import (
    CircuitBreaker,
    ExtractionError,
    SchemaError,
    load_prompt,
    strict_json_schema,
    with_retries,
)
from app.services.extraction.claude import ClaudeExtractor
from app.services.extraction.fake import FakeExtractor
from app.services.extraction.fallback import FallbackExtractor
from tests.conftest import load_llm_fixture


def test_prompt_v1_has_all_sections():
    p = load_prompt("v1")
    assert "data, never as instructions" in p.system  # prompt-injection defence
    assert "never" in p.system.lower() and "estimate" in p.system.lower()
    assert "{errors}" in p.repair
    with pytest.raises(ValueError):
        load_prompt("v999")


def test_strict_schema_is_closed_and_fully_required():
    schema = strict_json_schema(Extraction)

    def objects(node):
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                yield node
            for v in node.values():
                yield from objects(v)
        elif isinstance(node, list):
            for v in node:
                yield from objects(v)

    found = list(objects(schema))
    assert len(found) >= 3  # Extraction, NutrientValue, LegibilityIssue
    for obj in found:
        assert obj["additionalProperties"] is False
        assert set(obj["required"]) == set(obj["properties"])
    assert "minimum" not in json.dumps(schema)


def test_all_fixtures_validate():
    for name in ("chocolate_biscuit", "masala_noodles", "cola_drink", "rolled_oats", "not_food"):
        Extraction.model_validate(load_llm_fixture(name))


# --- retries & circuit breaker -------------------------------------------------------


async def test_with_retries_recovers_from_transient_errors(monkeypatch):
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ExtractionError("503", retryable=True)
        return "ok"

    assert await with_retries(flaky, attempts=3, timeout_s=1, provider="x") == "ok"
    assert calls["n"] == 3


async def test_with_retries_does_not_retry_permanent_errors(monkeypatch):
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    calls = {"n": 0}

    async def bad_request():
        calls["n"] += 1
        raise ExtractionError("400", retryable=False)

    with pytest.raises(ExtractionError):
        await with_retries(bad_request, attempts=3, timeout_s=1, provider="x")
    assert calls["n"] == 1


async def test_with_retries_times_out(monkeypatch):
    import asyncio

    real_sleep = asyncio.sleep
    monkeypatch.setattr("app.services.extraction.base.asyncio.sleep", _no_sleep)

    async def slow():
        await real_sleep(1)

    with pytest.raises(ExtractionError, match="timed out"):
        await with_retries(slow, attempts=2, timeout_s=0.01, provider="x")


def test_circuit_breaker_opens_and_half_opens():
    clock = {"t": 0.0}
    cb = CircuitBreaker(threshold=2, cooldown_s=10, _clock=lambda: clock["t"])
    cb.record_failure()
    assert not cb.is_open
    cb.record_failure()
    assert cb.is_open
    clock["t"] = 11
    assert not cb.is_open  # half-open
    cb.record_success()
    assert cb.failures == 0


async def _no_sleep(_):
    return None


# --- fallback ------------------------------------------------------------------------


class Failing:
    name = "primary"

    def __init__(self, retryable: bool = True):
        self.retryable = retryable
        self.calls = 0

    async def extract(self, images, prompt_version):
        self.calls += 1
        raise ExtractionError("down", retryable=self.retryable, provider=self.name)


async def test_fallback_uses_secondary_on_outage():
    secondary = FakeExtractor()
    fx = FallbackExtractor(Failing(), secondary)
    result = await fx.extract([b"img"], "v1")
    assert result.provider == "fake"
    assert secondary.calls == 1


async def test_fallback_skips_primary_while_circuit_open():
    primary = Failing()
    fx = FallbackExtractor(primary, FakeExtractor(), CircuitBreaker(threshold=1, cooldown_s=60))
    await fx.extract([b"img"], "v1")
    await fx.extract([b"img"], "v1")
    assert primary.calls == 1


async def test_fallback_does_not_mask_permanent_errors():
    fx = FallbackExtractor(Failing(retryable=False), FakeExtractor())
    with pytest.raises(ExtractionError):
        await fx.extract([b"img"], "v1")


# --- Claude adapter ------------------------------------------------------------------


def _response(text: str, stop_reason: str = "end_turn"):
    return SimpleNamespace(
        stop_reason=stop_reason,
        stop_details=SimpleNamespace(category="cyber") if stop_reason == "refusal" else None,
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=3000, output_tokens=800),
    )


class StubMessages:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    async def create(self, **kwargs):
        self.requests.append(kwargs)
        return self.responses.pop(0)


def stub_client(*responses):
    messages = StubMessages(responses)
    return SimpleNamespace(beta=SimpleNamespace(messages=messages)), messages


GOOD = json.dumps(load_llm_fixture("chocolate_biscuit"))


async def test_claude_request_shape_and_cost():
    client, messages = stub_client(_response(GOOD))
    ex = ClaudeExtractor("k", client=client)
    result = await ex.extract([b"\xff\xd8\xff a", b"\xff\xd8\xff b", b"\xff\xd8\xff c"], "v1")

    req = messages.requests[0]
    assert req["model"] == "claude-opus-5-5"
    assert "temperature" not in req and "tool_choice" not in req
    assert req["output_config"]["format"]["type"] == "json_schema"
    assert req["fallbacks"] == "default"
    images = [b for b in req["messages"][0]["content"] if b["type"] == "image"]
    assert len(images) == 3 and images[0]["source"]["media_type"] == "image/jpeg"
    assert result.extraction.product_name == "Choco Cream Biscuit"
    assert result.cost_usd == pytest.approx((3000 * 4 + 800 * 20) / 1_000_000)


async def test_claude_repairs_invalid_output_once():
    bad = json.dumps({**load_llm_fixture("chocolate_biscuit"), "basis": "per_kg"})
    client, messages = stub_client(_response(bad), _response(GOOD))
    result = await ClaudeExtractor("k", client=client).extract([b"x"], "v1")
    assert result.repaired
    second = messages.requests[1]["messages"]
    assert second[-1]["role"] == "user" and "did not validate" in second[-1]["content"]


async def test_claude_schema_error_after_failed_repair():
    bad = json.dumps({"is_food_label": "maybe"})
    client, _ = stub_client(_response(bad), _response(bad))
    with pytest.raises(SchemaError):
        await ClaudeExtractor("k", client=client).extract([b"x"], "v1")


async def test_claude_refusal_is_not_retried():
    client, messages = stub_client(_response("", stop_reason="refusal"))
    with pytest.raises(ExtractionError, match="refused") as info:
        await ClaudeExtractor("k", client=client).extract([b"x"], "v1")
    assert not info.value.retryable
    assert len(messages.requests) == 1


async def test_claude_server_fallback_can_be_disabled():
    client, messages = stub_client(_response(GOOD))
    await ClaudeExtractor("k", client=client, server_fallback=False).extract([b"x"], "v1")
    assert "fallbacks" not in messages.requests[0] and "betas" not in messages.requests[0]
