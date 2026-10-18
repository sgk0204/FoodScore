# ADR-4: Provider adapter for the vision LLM

**Status:** Accepted · 2026-10-18

## Context
Locking into one AI vendor risks outages, price changes and makes accuracy/cost comparisons
hard.

## Decision
All extraction goes through the `VisionExtractor` protocol
(`app/services/extraction/base.py`) with one implementation per provider:

| Adapter | Notes |
|---|---|
| `ClaudeExtractor` | Anthropic SDK, structured outputs (`output_config.format` JSON schema), server-side refusal fallbacks, default model `claude-opus-5-5` |
| `GeminiExtractor` | google-genai SDK, `response_json_schema`, temperature 0 |
| `FakeExtractor` | Replays recorded responses from `backend/tests/fixtures/llm_responses/` |
| `FallbackExtractor` | Primary → secondary on timeout / 429 / 5xx, with a circuit breaker |

Shared behaviour lives in the base: 30 s timeout, exponential backoff with jitter (3 tries),
one schema-repair round-trip, and cost/latency accounting.

## Consequences
- Switching provider is a config change (`LLM_PROVIDER`, `LLM_FALLBACK_PROVIDER`).
- The eval harness compares providers on the same dataset with the same pipeline.
- Permanent errors (refusal, bad request, schema failure after repair) are *not* retried on
  the fallback provider — another model would not fix bad input.
- Note: current Claude models reject `temperature` and forced `tool_choice`, so the guide's
  "temperature 0" is replaced by schema-constrained output + strict prompt + validation.
