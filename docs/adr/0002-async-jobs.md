# ADR-2: Asynchronous jobs (202 + polling)

**Status:** Accepted · 2026-10-18

## Context
A vision-LLM call takes 5–15 s and sometimes fails or times out. Holding an HTTP request open
that long risks gateway timeouts and ties up API workers.

## Decision
`POST /api/v1/scans` validates the upload, stores the images, creates a `QUEUED` scan,
enqueues an ARQ job and returns **202** with the scan id. A separate worker process runs the
pipeline. The client polls `GET /scans/{id}` (ETag → cheap 304s) or listens on the SSE endpoint.
Cache hits skip the queue and return **200** immediately.

## Consequences
- API latency stays low and independent of the AI provider.
- Jobs can be retried; API and workers scale independently.
- Trade-off: more moving parts — a queue, a worker, a status state machine
  (`QUEUED → PROCESSING → DONE | NEEDS_REVIEW | FAILED`, `NEEDS_REVIEW → DONE | EXPIRED`) and a
  reaper (`app/workers/reaper.py`) so a crashed worker never leaves a scan stuck.
- `JOB_MODE=inline` runs the same pipeline in-process for tests and single-process dev.
