"""Provider-neutral extraction interface, retries and circuit breaker (guide §7.5, edge case 37)."""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

import structlog

from app.schemas.extraction import Extraction

log = structlog.get_logger(__name__)
PROMPTS_DIR = Path(__file__).parent / "prompts"


class ExtractionError(Exception):
    """Extraction failed. ``retryable`` errors are worth another attempt or a fallback provider."""

    def __init__(self, message: str, *, retryable: bool, provider: str = "") -> None:
        super().__init__(message)
        self.retryable = retryable
        self.provider = provider


class SchemaError(ExtractionError):
    """The model answered, but the output never validated (even after the repair prompt)."""

    def __init__(self, message: str, provider: str = "") -> None:
        super().__init__(message, retryable=False, provider=provider)


@dataclass(slots=True)
class ExtractionResult:
    extraction: Extraction
    provider: str
    model: str
    prompt_version: str
    latency_ms: int
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    repaired: bool = False


class VisionExtractor(Protocol):
    name: str

    async def extract(self, images: list[bytes], prompt_version: str) -> ExtractionResult: ...


@dataclass(frozen=True, slots=True)
class Prompt:
    version: str
    system: str
    user: str
    repair: str


@lru_cache
def load_prompt(version: str) -> Prompt:
    path = PROMPTS_DIR / f"extraction_{version}.md"
    if not path.exists():
        raise ValueError(f"Unknown prompt version {version!r}")
    text = path.read_text(encoding="utf-8")
    sections: dict[str, str] = {}
    current = ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("<!--") and stripped.endswith("-->"):
            current = stripped[4:-3].strip().lower()
            sections[current] = ""
        elif current:
            sections[current] += line + "\n"
    return Prompt(
        version=version,
        system=sections["system"].strip(),
        user=sections["user"].strip(),
        repair=sections["repair"].strip(),
    )


def strict_json_schema(model: type[Extraction]) -> dict[str, Any]:
    """Pydantic JSON schema → strict structured-output schema.

    Every object gets ``additionalProperties: false`` and lists all properties as required;
    numeric/length constraints and defaults are dropped (validated by Pydantic afterwards).
    """
    unsupported = {
        "default",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "title",
    }

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            out = {k: walk(v) for k, v in node.items() if k not in unsupported}
            if out.get("type") == "object" and "properties" in out:
                out["additionalProperties"] = False
                out["required"] = list(out["properties"].keys())
            return out
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    result: dict[str, Any] = walk(model.model_json_schema())
    return result


async def with_retries[T](
    fn: Callable[[], Awaitable[T]],
    *,
    attempts: int,
    timeout_s: float,
    provider: str,
    base_delay_s: float = 0.5,
    max_delay_s: float = 8.0,
) -> T:
    """Timeout + exponential backoff with full jitter on retryable errors."""
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await asyncio.wait_for(fn(), timeout=timeout_s)
        except TimeoutError as exc:
            last = ExtractionError(
                f"{provider} timed out after {timeout_s}s", retryable=True, provider=provider
            )
            last.__cause__ = exc
        except ExtractionError as exc:
            if not exc.retryable:
                raise
            last = exc
        if attempt < attempts:
            delay = min(max_delay_s, base_delay_s * 2 ** (attempt - 1)) * random.uniform(0.5, 1.5)  # noqa: S311
            log.warning(
                "llm_retry",
                provider=provider,
                attempt=attempt,
                delay_s=round(delay, 2),
                error=str(last),
            )
            await asyncio.sleep(delay)
    assert last is not None
    raise last


@dataclass(slots=True)
class CircuitBreaker:
    """Opens after ``threshold`` consecutive failures; half-opens after ``cooldown_s``."""

    threshold: int = 5
    cooldown_s: float = 60.0
    failures: int = 0
    opened_at: float | None = None
    _clock: Callable[[], float] = field(default=time.monotonic, repr=False)

    @property
    def is_open(self) -> bool:
        if self.opened_at is None:
            return False
        # After the cooldown the breaker is half-open: one trial request is allowed through.
        return self._clock() - self.opened_at < self.cooldown_s

    def record_success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.threshold:
            self.opened_at = self._clock()
