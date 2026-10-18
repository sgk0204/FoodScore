"""Prometheus metrics (guide §13 "Metrics to track")."""

from __future__ import annotations

from prometheus_client import Counter, Histogram

SCANS = Counter("foodscore_scans_total", "Scans by final status", ["status"])
CACHE_HITS = Counter("foodscore_cache_hits_total", "Barcode cache hits")
CACHE_MISSES = Counter("foodscore_cache_misses_total", "Barcode cache misses")
LLM_LATENCY = Histogram(
    "foodscore_llm_latency_seconds",
    "Vision LLM extraction latency",
    ["provider"],
    buckets=(1, 2, 4, 6, 8, 10, 15, 20, 30, 45, 60),
)
LLM_COST = Counter("foodscore_llm_cost_usd_total", "Estimated LLM spend in USD", ["provider"])
LLM_FAILURES = Counter("foodscore_llm_failures_total", "Extraction failures", ["provider", "kind"])
USER_CORRECTIONS = Counter(
    "foodscore_user_corrections_total", "User-corrected nutrition fields", ["field"]
)
