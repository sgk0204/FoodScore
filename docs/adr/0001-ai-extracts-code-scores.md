# ADR-1: AI extracts, code scores

**Status:** Accepted · 2026-10-18

## Context
A vision LLM can read a label and could also be asked "how healthy is this out of 100?".
LLM output is non-deterministic, hard to audit, and can be steered by text printed on the
pack (prompt injection).

## Decision
The model only **transcribes** the label into a strict JSON schema
(`backend/app/schemas/extraction.py`). A pure-Python engine
(`backend/app/services/scoring/`) computes the score from the normalised values. The engine
has no I/O, no clock and no randomness.

## Consequences
- Same input → same score, always (tested: `test_score_is_reproducible`).
- Every point lost is explainable and traceable to a published threshold.
- Text on the pack cannot change a score — injected text can at most mis-transcribe a value,
  which the sanity checks and review step catch.
- Trade-off: the scoring rules (thresholds, additive tiers) are maintained by hand and must be
  versioned (`SCORING_VERSION`, stored on every scan).
