"""Claude vision extractor using structured outputs (JSON schema).

Notes on the request shape:
- ``output_config.format`` constrains the answer to the Extraction schema, so the first text
  block is always valid JSON. Pydantic still validates it (defence in depth).
- Current Claude models reject ``temperature`` and forced ``tool_choice``; consistency comes
  from the schema, the strict transcription prompt, validation, and the barcode cache.
- Server-side refusal fallbacks are on by default (``fallbacks="default"``).
- SDK retries are disabled: retries/backoff/circuit-breaking live in our adapter layer.
"""

from __future__ import annotations

import base64
import json
import time
from typing import Any

import anthropic
import structlog
from pydantic import ValidationError

from app.schemas.extraction import Extraction
from app.services.extraction.base import (
    ExtractionError,
    ExtractionResult,
    SchemaError,
    load_prompt,
    strict_json_schema,
    with_retries,
)

log = structlog.get_logger(__name__)

# USD per million tokens (input, output). Used for cost-per-scan metrics and the eval report.
PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
}
SERVER_FALLBACK_BETA = "server-side-fallback-2026-07-01"


class ClaudeExtractor:
    name = "claude"

    def __init__(
        self,
        api_key: str,
        *,
        model: str = "claude-opus-5-5",
        effort: str = "medium",
        timeout_s: float = 30.0,
        max_attempts: int = 3,
        server_fallback: bool = True,
        client: anthropic.AsyncAnthropic | None = None,
    ) -> None:
        self.model = model
        self.effort = effort
        self.timeout_s = timeout_s
        self.max_attempts = max_attempts
        self.server_fallback = server_fallback
        self._client = client or anthropic.AsyncAnthropic(
            api_key=api_key, timeout=timeout_s, max_retries=0
        )
        self._schema = strict_json_schema(Extraction)

    async def _call(self, system: str, messages: list[dict[str, Any]]) -> Any:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 16000,
            "system": system,
            "messages": messages,
            "output_config": {
                "effort": self.effort,
                "format": {"type": "json_schema", "schema": self._schema},
            },
        }
        if self.server_fallback:
            kwargs["betas"] = [SERVER_FALLBACK_BETA]
            kwargs["fallbacks"] = "default"
        try:
            return await self._client.beta.messages.create(**kwargs)
        except anthropic.RateLimitError as exc:
            raise ExtractionError(
                "Claude rate limited",
                retryable=True,
                provider=self.name,
                kind="rate_limit",
                code="claude:rate_limited",
            ) from exc
        except anthropic.APITimeoutError as exc:
            raise ExtractionError(
                "Claude request timed out",
                retryable=True,
                provider=self.name,
                code="claude:timeout",
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise ExtractionError(
                "Claude connection error", retryable=True, provider=self.name, code="claude:network"
            ) from exc
        except anthropic.APIStatusError as exc:
            retryable = exc.status_code >= 500 or exc.status_code in (408, 409)
            raise ExtractionError(
                f"Claude API error {exc.status_code}",
                retryable=retryable,
                provider=self.name,
                kind="unavailable" if retryable else "config",
                code=f"claude:{exc.status_code}",
            ) from exc

    def _text(self, response: Any) -> str:
        if response.stop_reason == "refusal":
            category = (
                getattr(response.stop_details, "category", None) if response.stop_details else None
            )
            raise ExtractionError(
                f"Claude refused (category={category})",
                retryable=False,
                provider=self.name,
                kind="blocked",
                code="claude:refusal",
            )
        if response.stop_reason == "max_tokens":
            raise ExtractionError("Claude output truncated", retryable=True, provider=self.name)
        for block in response.content:
            if block.type == "text":
                return str(block.text)
        raise ExtractionError("Claude returned no text block", retryable=True, provider=self.name)

    async def extract(self, images: list[bytes], prompt_version: str) -> ExtractionResult:
        prompt = load_prompt(prompt_version)
        content: list[dict[str, Any]] = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": base64.standard_b64encode(img).decode("ascii"),
                },
            }
            for img in images
        ]
        content.append({"type": "text", "text": prompt.user})
        messages: list[dict[str, Any]] = [{"role": "user", "content": content}]

        started = time.perf_counter()
        in_tok = out_tok = 0

        async def attempt() -> Any:
            return await self._call(prompt.system, messages)

        response = await with_retries(
            attempt, attempts=self.max_attempts, timeout_s=self.timeout_s, provider=self.name
        )
        in_tok += response.usage.input_tokens
        out_tok += response.usage.output_tokens
        text = self._text(response)
        repaired = False
        try:
            extraction = Extraction.model_validate(json.loads(text))
        except (ValidationError, json.JSONDecodeError) as first_error:
            # One repair round-trip with the validation errors (guide §7.4, "Schema" row).
            log.warning("llm_schema_repair", provider=self.name, error=str(first_error)[:500])
            messages = [
                *messages,
                {"role": "assistant", "content": text},
                {"role": "user", "content": prompt.repair.format(errors=str(first_error)[:2000])},
            ]
            response = await with_retries(
                attempt, attempts=self.max_attempts, timeout_s=self.timeout_s, provider=self.name
            )
            in_tok += response.usage.input_tokens
            out_tok += response.usage.output_tokens
            try:
                extraction = Extraction.model_validate(json.loads(self._text(response)))
            except (ValidationError, json.JSONDecodeError) as exc:
                raise SchemaError(
                    f"Output failed validation after repair: {exc}", self.name
                ) from exc
            repaired = True

        price_in, price_out = PRICES_PER_MTOK.get(self.model, (0.0, 0.0))
        return ExtractionResult(
            extraction=extraction,
            provider=self.name,
            model=self.model,
            prompt_version=prompt_version,
            latency_ms=int((time.perf_counter() - started) * 1000),
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_usd=round((in_tok * price_in + out_tok * price_out) / 1_000_000, 6),
            repaired=repaired,
        )
