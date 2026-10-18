# ADR-6: Monorepo with frontend/ and backend/

**Status:** Accepted · 2026-10-18

## Context
A solo project with one frontend, one API/worker codebase, an eval harness and docs.

## Decision
One repository: `frontend/` (Next.js), `backend/` (FastAPI + worker), `eval/`, `docs/`,
`.github/workflows/`. The backend's OpenAPI schema is exported into
`frontend/lib/api/openapi.json` and TypeScript types are generated from it.

## Consequences
- One place for docs, CI and versioning; API contract changes and their frontend updates land
  in the same PR, and CI fails if the committed schema drifts.
- Trade-off: CI needs path filters (`dorny/paths-filter`) so a frontend-only change does not
  run the backend suite and vice versa.
