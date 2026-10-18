"""Gemini vision extractor (google-genai SDK) with JSON-schema constrained output.

Request shape:
- One user turn holding the three images + the instruction; the system prompt goes in
  ``system_instruction``. ``response_json_schema`` constrains the answer to the Extraction
  schema (with ``$ref``s inlined — Gemini supports only a subset of JSON Schema).
- Temperature 0 only on 2.x models (Gemini 3 should keep its default). SDK-level retries are not used; retries/backoff live in ``base.py``.
- Blocked or truncated answers are classified by ``finish_reason`` / ``prompt_feedback``
  instead of being mistaken for schema errors.
- The schema-repair round is a proper multi-turn exchange: the model sees its own previous
  answer followed by the validation errors.
"""

from __future__ import annotations

import json
import time
from typing import Any, Literal

import httpx
import structlog
from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import ValidationError

from app.schemas.extraction import Extraction
from app.services.extraction.base import (
    ErrorKind,
    ExtractionError,
    ExtractionResult,
    SchemaError,
    inline_refs,
    load_prompt,
    strict_json_schema,
    with_retries,
)

log = structlog.get_logger(__name__)

# USD per million tokens (input, output). Thinking tokens are billed as output.
PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    "gemini-3.8-flash": (0.75, 3.75),  # rises to (1.50, 7.50) on 2027-01-01
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-2.5-pro": (1.25, 10.0),
}

ThinkingLevel = Literal["minimal", "low", "medium", "high"]

_RETRYABLE_FINISH = {"MAX_TOKENS"}  # transient: worth another attempt


class GeminiExtractor:
    name = "gemini"

    def __init__(
        self,
        api_key: str,
        *,
        model: str = "gemini-3.8-flash",
        timeout_s: float = 60.0,
        max_attempts: int = 3,
        thinking_level: ThinkingLevel | None = "low",
        client: Any | None = None,
    ) -> None:
        self.model = model
        # Transcribing a label needs little reasoning, so use the lowest thinking level the model
        # allows: faster and cheaper. Gemini 3 models cannot switch thinking off, and the lowest
        # level differs per model (gemini-3.8-flash: "low"; flash-lite: "minimal"). None keeps the
        # model's default.
        self.thinking_level = thinking_level
        # Gemini 3+: Google strongly recommends the default temperature (1.0); lower values can
        # cause looping (truncated JSON). Older 2.x models are most consistent at 0.
        self.temperature: float | None = 0 if model.startswith(("gemini-2.", "gemini-1.")) else None
        self.timeout_s = timeout_s
        self.max_attempts = max_attempts
        self._client = client or genai.Client(api_key=api_key)
        self._schema = inline_refs(strict_json_schema(Extraction))

    async def _call(self, system: str, contents: list[types.ContentUnion]) -> Any:
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=self.temperature,
            max_output_tokens=16000,
            response_mime_type="application/json",
            response_json_schema=self._schema,
            thinking_config=(
                types.ThinkingConfig(thinking_level=self.thinking_level.upper())
                if self.thinking_level is not None
                else None
            ),
        )
        try:
            return await self._client.aio.models.generate_content(
                model=self.model, contents=contents, config=config
            )
        except genai_errors.APIError as exc:
            code = int(getattr(exc, "code", 0) or 0)
            status = str(getattr(exc, "status", "") or code)
            if code == 429:
                kind: ErrorKind = "rate_limit"
            elif code >= 500 or code == 408:
                kind = "unavailable"
            else:  # 400 bad request/schema, 401/403 key, 404 unknown model
                kind = "config"
            raise ExtractionError(
                f"Gemini API error {code} {status}: {getattr(exc, 'message', '')}"[:400],
                retryable=kind in ("rate_limit", "unavailable"),
                provider=self.name,
                kind=kind,
                code=f"gemini:{status}",
            ) from exc
        except httpx.TransportError as exc:  # connection reset, DNS, read timeout…
            raise ExtractionError(
                f"Gemini network error: {type(exc).__name__}",
                retryable=True,
                provider=self.name,
                code="gemini:network",
            ) from exc

    def _text(self, response: Any) -> str:
        """Return the JSON text, or raise a correctly classified ExtractionError."""
        feedback = getattr(response, "prompt_feedback", None)
        if feedback is not None and getattr(feedback, "block_reason", None):
            raise ExtractionError(
                f"Gemini blocked the request ({feedback.block_reason})",
                retryable=False,
                provider=self.name,
                kind="blocked",
                code=f"gemini:blocked:{feedback.block_reason}",
            )
        candidates = getattr(response, "candidates", None) or []
        reason = getattr(candidates[0], "finish_reason", None) if candidates else None
        reason_name = getattr(reason, "name", None) or (str(reason) if reason else None)
        text = getattr(response, "text", None)
        if text:
            return str(text)
        if reason_name in _RETRYABLE_FINISH:
            raise ExtractionError(
                "Gemini output truncated",
                retryable=True,
                provider=self.name,
                code="gemini:MAX_TOKENS",
            )
        if reason_name and reason_name not in ("STOP", "FINISH_REASON_UNSPECIFIED"):
            raise ExtractionError(
                f"Gemini returned no answer (finish_reason={reason_name})",
                retryable=False,
                provider=self.name,
                kind="blocked",
                code=f"gemini:{reason_name}",
            )
        raise ExtractionError(
            "Gemini returned an empty answer",
            retryable=True,
            provider=self.name,
            code="gemini:empty",
        )

    @staticmethod
    def _usage(response: Any) -> tuple[int, int]:
        usage = getattr(response, "usage_metadata", None)
        if usage is None:
            return 0, 0
        out = (usage.candidates_token_count or 0) + (getattr(usage, "thoughts_token_count", 0) or 0)
        return usage.prompt_token_count or 0, out

    async def extract(self, images: list[bytes], prompt_version: str) -> ExtractionResult:
        prompt = load_prompt(prompt_version)
        parts = [types.Part.from_bytes(data=img, mime_type="image/jpeg") for img in images]
        parts.append(types.Part.from_text(text=prompt.user))
        contents: list[types.ContentUnion] = [types.Content(role="user", parts=parts)]
        started = time.perf_counter()

        async def attempt() -> Any:
            return await self._call(prompt.system, contents)

        response = await with_retries(
            attempt, attempts=self.max_attempts, timeout_s=self.timeout_s, provider=self.name
        )
        in_tok, out_tok = self._usage(response)
        text = self._text(response)
        repaired = False
        try:
            extraction = Extraction.model_validate(json.loads(text))
        except (ValidationError, json.JSONDecodeError) as first_error:
            log.warning("llm_schema_repair", provider=self.name, error=str(first_error)[:500])
            contents.append(types.Content(role="model", parts=[types.Part.from_text(text=text)]))
            contents.append(
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_text(
                            text=prompt.repair.format(errors=str(first_error)[:2000])
                        )
                    ],
                )
            )
            response = await with_retries(
                attempt, attempts=self.max_attempts, timeout_s=self.timeout_s, provider=self.name
            )
            more_in, more_out = self._usage(response)
            in_tok, out_tok = in_tok + more_in, out_tok + more_out
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
