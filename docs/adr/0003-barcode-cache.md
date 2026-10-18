# ADR-3: Barcode-keyed result cache

**Status:** Accepted · 2026-10-18

## Context
LLM calls are the dominant cost and latency. Many users scan the same popular products.

## Decision
The API decodes an EAN/UPC barcode from the uploaded photos (zxing-cpp, GS1 check digit
verified). After a successful high-confidence scan, the worker stores a snapshot
(normalised nutrition, ingredients, result) in Redis under `product:{barcode}` for 30 days.
A later scan of the same barcode is served from the snapshot: no LLM call, no quota used,
p95 well under 300 ms. A Redis `SET NX` lock makes concurrent first scans share one LLM call.

## Consequences
- Only the first scan of a product costs money.
- The engine is re-run on cached snapshots, so scoring-rule changes apply immediately.
- **Never cached:** low-confidence (`NEEDS_REVIEW`) results and user-edited values — one
  user's correction must not change what everyone else sees.
- Trade-off: a recipe change under the same barcode can serve stale data until someone
  rescans; each new high-confidence scan overwrites the snapshot and `products.latest_scan_id`.
