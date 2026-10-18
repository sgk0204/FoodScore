"""Primary → secondary provider on timeout / 5xx / 429 / open circuit (ADR-4, edge case 37)."""

from __future__ import annotations

import structlog

from app.core.config import Settings
from app.services.extraction.base import (
    CircuitBreaker,
    ExtractionError,
    ExtractionResult,
    VisionExtractor,
)

log = structlog.get_logger(__name__)


class FallbackExtractor:
    def __init__(
        self,
        primary: VisionExtractor,
        secondary: VisionExtractor,
        breaker: CircuitBreaker | None = None,
    ) -> None:
        self.primary = primary
        self.secondary = secondary
        self.breaker = breaker or CircuitBreaker()
        self.name = f"{primary.name}+{secondary.name}"

    async def extract(self, images: list[bytes], prompt_version: str) -> ExtractionResult:
        if not self.breaker.is_open:
            try:
                result = await self.primary.extract(images, prompt_version)
            except ExtractionError as exc:
                if not exc.retryable:
                    raise  # bad input / refusal / schema: another provider will not help
                self.breaker.record_failure()
                log.warning("llm_fallback", primary=self.primary.name, error=str(exc))
            else:
                self.breaker.record_success()
                return result
        else:
            log.warning("llm_circuit_open", primary=self.primary.name)
        return await self.secondary.extract(images, prompt_version)


def _build_one(name: str, settings: Settings) -> VisionExtractor:
    if name == "claude":
        from app.services.extraction.claude import ClaudeExtractor

        assert settings.anthropic_api_key is not None
        return ClaudeExtractor(
            settings.anthropic_api_key.get_secret_value(),
            model=settings.claude_model,
            effort=settings.claude_effort,
            timeout_s=settings.llm_timeout_s,
            max_attempts=settings.llm_max_attempts,
            server_fallback=settings.claude_server_fallback,
        )
    if name == "gemini":
        from app.services.extraction.gemini import GeminiExtractor

        assert settings.gemini_api_key is not None
        return GeminiExtractor(
            settings.gemini_api_key.get_secret_value(),
            model=settings.gemini_model,
            timeout_s=settings.llm_timeout_s,
            max_attempts=settings.llm_max_attempts,
            thinking_budget=settings.gemini_thinking_budget,
        )
    from app.services.extraction.fake import FakeExtractor

    return FakeExtractor(settings.fake_fixture)


def build_extractor(settings: Settings) -> VisionExtractor:
    primary = _build_one(settings.llm_provider, settings)
    if settings.llm_fallback_provider and settings.llm_fallback_provider != settings.llm_provider:
        return FallbackExtractor(primary, _build_one(settings.llm_fallback_provider, settings))
    return primary
