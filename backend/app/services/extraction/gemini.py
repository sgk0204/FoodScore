"""Gemini vision extractor (google-genai SDK) with JSON-schema constrained output."""

from __future__ import annotations

import json
import time
from typing import Any

import structlog
from google import genai
from google.genai import errors as genai_errors
from google.genai import types
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

PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-pro": (1.25, 10.0),
}


class GeminiExtractor:
    name = "gemini"

    def __init__(
        self,
        api_key: str,
        *,
        model: str = "gemini-2.5-flash",
        timeout_s: float = 30.0,
        max_attempts: int = 3,
        client: genai.Client | None = None,
    ) -> None:
        self.model = model
        self.timeout_s = timeout_s
        self.max_attempts = max_attempts
        self._client = client or genai.Client(api_key=api_key)
        self._schema = strict_json_schema(Extraction)

    async def _call(self, system: str, contents: list[Any]) -> Any:
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=0,
            response_mime_type="application/json",
            response_json_schema=self._schema,
        )
        try:
            return await self._client.aio.models.generate_content(
                model=self.model, contents=contents, config=config
            )
        except genai_errors.APIError as exc:
            retryable = exc.code == 429 or exc.code >= 500
            raise ExtractionError(
                f"Gemini API error {exc.code}", retryable=retryable, provider=self.name
            ) from exc

    async def extract(self, images: list[bytes], prompt_version: str) -> ExtractionResult:
        prompt = load_prompt(prompt_version)
        contents: list[Any] = [
            types.Part.from_bytes(data=img, mime_type="image/jpeg") for img in images
        ]
        contents.append(prompt.user)
        started = time.perf_counter()
        in_tok = out_tok = 0

        async def attempt() -> Any:
            return await self._call(prompt.system, contents)

        repaired = False
        response = await with_retries(
            attempt, attempts=self.max_attempts, timeout_s=self.timeout_s, provider=self.name
        )
        usage = response.usage_metadata
        in_tok += (usage.prompt_token_count or 0) if usage else 0
        out_tok += (usage.candidates_token_count or 0) if usage else 0
        try:
            extraction = Extraction.model_validate(json.loads(response.text or ""))
        except (ValidationError, json.JSONDecodeError) as first_error:
            log.warning("llm_schema_repair", provider=self.name, error=str(first_error)[:500])
            contents.append(prompt.repair.format(errors=str(first_error)[:2000]))
            response = await with_retries(
                attempt, attempts=self.max_attempts, timeout_s=self.timeout_s, provider=self.name
            )
            try:
                extraction = Extraction.model_validate(json.loads(response.text or ""))
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
