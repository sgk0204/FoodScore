# CLAUDE.md

Guidance for Claude (and humans) working in this repository. Read this before changing code.

## What this is

FoodScore: a mobile-first web app that photographs a packaged-food label (front, nutrition
table, ingredients), extracts the data with a vision LLM, and scores the product 0–100 with a
deterministic engine. Monorepo: `frontend/` (Next.js 16, React 19, TS, Tailwind 3, TanStack
Query, Zod), `backend/` (Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.1 async, Alembic,
ARQ, Redis), `eval/` (extraction accuracy harness), `docs/` (architecture, ADRs, methodology,
API, edge-case traceability). The original spec is the project guide (sections referenced as
"guide §N" in code comments).

## Commands

Run backend commands from `backend/` with the venv (`backend/.venv`; on Windows
`.venv/Scripts/python`). Run frontend commands from `frontend/`.

```bash
# backend
pip install -e ".[dev]"
pytest                                   # unit + API tests, SQLite + fakeredis, ~20 s, no Docker
pytest tests/unit/test_scoring_engine.py # fastest feedback loop for scoring changes
pytest -m integration -o addopts=""      # Testcontainers Postgres + Redis (needs Docker running)
pytest --cov=app                         # CI gates: 80 % overall, 90 % on app/services/scoring
ruff check app tests scripts ../eval && ruff format app tests scripts ../eval
mypy app                                 # strict mode; must be clean
alembic upgrade head                     # needs DATABASE_URL in the environment
alembic check                            # fails if models and migrations drift
uvicorn --factory app.main:app_factory --reload --port 8000
arq app.workers.settings.WorkerSettings  # worker (when JOB_MODE=arq)
python scripts/export_openapi.py ../frontend/lib/api/openapi.json

# frontend
npm install
npm run dev                              # proxies /api/* to BACKEND_URL (default localhost:8000)
npm test                                 # Vitest
npm run test:e2e                         # Playwright; starts `next dev` itself; API is mocked
npm run lint && npm run typecheck && npm run format:check
npm run gen:api                          # lib/api/openapi.json → lib/api/schema.d.ts

# eval (from repo root, backend venv active)
python -m pytest eval
python -m eval.run --provider fake       # free; real providers cost money — ask first

# everything
cp .env.example .env && docker compose up --build
```

Minimal local backend without Docker: `DATABASE_URL=sqlite+aiosqlite:///./foodscore.db`,
`REDIS_URL=redis://localhost:6379/0` (Redis may be absent — the app fails open),
`JWT_SECRET=<32+ chars>`, `JOB_MODE=inline`, `LLM_PROVIDER=fake`, `COOKIE_SECURE=false`.

## Architecture map

```
POST /api/v1/scans  (app/api/v1/scans.py: create_scan)
  → rate limit + idempotency (Owner.key-scoped)        app/api/deps.py, services/cache.py
  → images.prepare: magic bytes → decode → EXIF transpose → resize → re-encode JPEG
  → images.find_duplicates (dHash)  → barcode.detect_barcode (zxing-cpp, GS1 check digit)
  → cache hit?  pipeline.apply_snapshot → 200            (no quota, no LLM)
  → quota → store images → Scan(QUEUED) → queue.enqueue_scan → 202
worker: pipeline.process_scan
  → BarcodeLock (SET NX) → re-check cache
  → extractor.extract (services/extraction/*)  → delete images
  → normalise.normalise (units → basis → sanity → confidence → needs_review)
  → NEEDS_REVIEW | apply_score (scoring.score) → DONE → cache snapshot
reaper (cron, every minute): PROCESSING > 2 min → FAILED; NEEDS_REVIEW > 24 h → EXPIRED
```

- `app/services/context.py` — `Services` container (settings, engine, sessionmaker, redis,
  store, extractor, additives, queue, cache, limiter, quotas). The API keeps it on
  `app.state.services`; the worker on `ctx["services"]`. `create_app(settings, services)`
  accepts injected services (tests do this).
- `InlineQueue` runs jobs as asyncio tasks in-process (tests, `JOB_MODE=inline`); `ArqQueue`
  enqueues to Redis with `_job_id=scan:{id}` (idempotent).

## Invariants — do not break these

1. **The scoring engine is pure.** `app/services/scoring/` must not import the DB, Redis,
   HTTP, settings, the clock or randomness. The additive table is passed in. Same input → same
   output (`test_score_is_reproducible`).
2. **The LLM never scores.** It only fills `app/schemas/extraction.py::Extraction`. Never add a
   "score" or "healthiness" field to the extraction schema or prompt.
3. **The worked example is a regression anchor.** `test_worked_example_*` (biscuit → 28.75 /
   65 / 20 → 38.75 → **39 BAD**, plus the exact ranked reasons) must keep passing. If you
   intentionally change scoring rules, bump `SCORING_VERSION` in `thresholds.py`, update the
   test *and* `docs/methodology.md`, and say so in the PR.
4. **Every scan query is owner-scoped.** Use `Owner.scope(stmt)` or `get_owned_scan(...)`.
   Return 404 (never 403) for scans that exist but belong to someone else.
5. **User edits never reach the shared cache.** Only high-confidence, unedited `DONE` results
   are written to `product:{barcode}`. NEEDS_REVIEW results are never cached either.
6. **Images are temporary.** The worker deletes them right after extraction on every path
   (success, failure, not-food). Never log image bytes, tokens or passwords.
7. **Errors are RFC 9457.** Raise `app.core.errors.AppError(status, slug, title, detail,
   **extra)`; use `retake=[role, ...]` when the user should re-photograph something.
8. **Config is validated at start-up.** New settings go in `app/core/config.py` *and*
   `.env.example` (`test_env_example_is_a_valid_configuration` loads it).
9. **Migrations match models.** Any model change needs an Alembic revision in
   `app/db/migrations/versions/`; verify with `alembic upgrade head && alembic check`.
10. **API contract changes regenerate the frontend copy**: run `export_openapi.py` and
    `npm run gen:api`, and update the Zod schemas in `frontend/lib/api/schemas.ts`. CI diffs both.

## Conventions

- **Python:** `from __future__ import annotations`, full type hints (mypy strict), Ruff
  (line length 100 via the formatter), async everywhere on I/O paths, `structlog` loggers via
  `structlog.get_logger(__name__)` with snake_case event names (`log.info("scan_queued", ...)`).
  Docstrings explain *why*, and reference the guide section/edge case they implement.
- **Tests:** pytest-asyncio auto mode. API tests use `tests/api/conftest.py` fixtures
  (`client`, `services`, `extractor`, `settings`) plus `register()` and `drain()` (waits for
  inline jobs). Test photos come from `tests/images.py` (`photo_set(seed, barcode=...)`).
  Switch the replayed model response with `extractor.fixture = "<name>"`. Name tests after the
  behaviour and edge case they prove; add a row to `docs/edge-cases.md` for new edge cases.
- **LLM fixtures:** `backend/tests/fixtures/llm_responses/*.json` are full `Extraction`
  objects. They double as demo data for `LLM_PROVIDER=fake` (`FAKE_FIXTURE=auto` picks one per
  photo set). Keep them schema-valid (`test_all_fixtures_validate`).
- **Prompts are versioned files:** `app/services/extraction/prompts/extraction_vN.md` with
  `<!-- SYSTEM -->`, `<!-- USER -->`, `<!-- REPAIR -->` sections. Don't edit a released
  version in place — add `vN+1`, switch `PROMPT_VERSION`, and run the eval before and after.
- **Additives:** edit `backend/data/additives_ref.csv` (code, name, `|`-separated aliases,
  `low|moderate|high`, source URL, notes). Every row needs an `https://` source. Pseudo-codes
  for non-INS items use the `X-` prefix (e.g. `X-ARTIFICIAL-FLAVOUR`).
- **Frontend:** client components for anything interactive; all API calls go through
  `lib/api/client.ts` (`api.*`) and are parsed with Zod. Access token lives in memory only
  (never localStorage). Render extracted text as plain JSX text — never
  `dangerouslySetInnerHTML` (ESLint `react/no-danger` is an error). Colour is never the only
  signal: band labels are always shown as text. Prettier (with the Tailwind plugin) formats.
- **Commits:** conventional commits (`feat:`, `fix:`, `docs:`, `test:`, `chore:`).

## Gemini adapter (default in production)

`app/services/extraction/gemini.py` (google-genai SDK, async `client.aio.models.generate_content`):
one `Content(role="user")` with three JPEG parts + the instruction; `system_instruction`;
`temperature=0`; `response_json_schema=inline_refs(strict_json_schema(Extraction))` (no
`$defs` — Gemini supports a JSON Schema subset). Empty answers are classified by
`prompt_feedback.block_reason` / `finish_reason` (SAFETY etc. → permanent, MAX_TOKENS →
retryable), never treated as schema errors. Thinking tokens are billed as output and counted.
`scripts/check_provider.py` makes one real call with a synthetic label — use it after changing
the model, prompt or schema. Unit tests: `tests/unit/test_extraction_gemini.py`.

## Claude API usage (extraction adapter)

`app/services/extraction/claude.py` uses the official `anthropic` SDK (1.x), async client,
`client.beta.messages.create` with:
- `output_config={"effort": ..., "format": {"type": "json_schema", "schema": strict_schema}}`
  — the schema comes from `strict_json_schema(Extraction)` (all properties required,
  `additionalProperties: false`, numeric/length constraints stripped; Pydantic re-validates).
- `betas=["server-side-fallback-2026-07-01"], fallbacks="default"` (refusal fallbacks;
  disable with `CLAUDE_SERVER_FALLBACK=false`).
- Default model `claude-opus-5-5`. **Do not add `temperature` or a forced `tool_choice`** — the
  current models reject both with a 400. Check `stop_reason` (`refusal`, `max_tokens`) before
  reading content. SDK retries are off (`max_retries=0`); retries/backoff live in `base.py`.
- Prices in `PRICES_PER_MTOK` feed cost-per-scan metrics; update them if pricing changes.

## Gotchas (learned the hard way)

- **Coverage under-reports async SQLAlchemy code** unless `concurrency = ["greenlet",
  "thread"]` is set (it is, in `pyproject.toml`). Don't remove it.
- **Tailwind must scan `lib/`** — band colour classes live in `frontend/lib/bands.ts`. If they
  get purged the score pill and band scale render blank; CI greps the built CSS for
  `bg-band-bad` to catch this.
- **Dependency-set cookies vanish if a route returns its own `Response`.** `get_owner` sets
  the guest cookie on the injected `Response`; routes must return models and set
  `response.status_code` / headers on that injected object (see `_respond` in `scans.py`).
- **List settings need `NoDecode`** (`cors_origins`), otherwise pydantic-settings tries to
  JSON-decode comma-separated env values. `env_ignore_empty=True` lets `.env` keep blank keys.
- **SQLite needs `PRAGMA foreign_keys=ON`** for `ON DELETE CASCADE` (the test harness sets it).
  Production is Postgres; don't rely on SQLite-only behaviour.
- **SQLAlchemy 2.1 typing:** `Select[Scan]`, not `Select[tuple[Scan]]`.
- **zxing-cpp:** pass barcode formats as a tuple; the `|` operator is deprecated.
- **Pillow:** `Image.getdata()` is deprecated — use `tobytes()`.
- **`browser-image-compression` must run with `useWebWorker: false`** — its worker loads code
  from a CDN, which the CSP blocks.
- **Next.js dev compiles routes on first visit**, so E2E navigations use a 30 s timeout.
- **Refresh-token rotation is strict:** two tabs refreshing at once can trigger reuse
  detection and sign the user out. That's deliberate (theft detection) — don't "fix" it by
  removing family revocation.
- On Windows, a stray `package-lock.json` in a parent directory confuses Next's workspace root;
  `outputFileTracingRoot` is pinned in `next.config.ts` for that reason.
- **Next 16 has breaking changes vs older Next.js** — check the docs bundled at
  `frontend/node_modules/next/dist/docs/` before using an unfamiliar API. `agentRules: false` in
  `next.config.ts` stops `next dev` writing its own `AGENTS.md` (this file is the agent guide).
- **`prettier-plugin-tailwindcss` ≥ 0.8 assumes Tailwind 4** unless told otherwise;
  `.prettierrc.json` sets `"tailwindConfig": "./tailwind.config.ts"` so it uses the v3 path.
  Remove that line if the project moves to Tailwind 4.
- **Test tooling moves as a set:** Vitest 5 + `@vitejs/plugin-react` 6 need Vite 8 (pinned in
  devDependencies). Upgrade them together.
- **Async tests that check "concurrent" behaviour must force the overlap** (e.g. hold the fake
  extractor on an `asyncio.Event`) — on a fast runner the first background job can finish
  before the second request arrives.
- **Next 16 builds with Turbopack:** built CSS lands in `.next/static/chunks/`, not
  `static/css/` — the CI purge guard greps all of `.next/static`. `next lint` no longer exists;
  linting is plain `eslint .` with eslint-config-next's native flat configs.
- **ESLint stays on 9** until `eslint-plugin-react`, `jsx-a11y` and `import` (pulled in by
  eslint-config-next) support ESLint 10.
- CI runs `npm audit --audit-level=high`. If you add npm `overrides`, regenerate
  `package-lock.json` (delete it and `node_modules`) or the old nested copy stays.
- **Managed Postgres URLs** (`postgres://…?sslmode=require&channel_binding=require`) are
  rewritten by `normalise_database_url` in `app/core/config.py` (also used by Alembic's
  `env.py`). Keep both call sites if you touch it.
- **Inline mode has no ARQ cron**, so `create_app`'s lifespan starts `reaper.run_forever` when
  `JOB_MODE=inline`. The reaper also fails scans stuck in `QUEUED` > 10 min (lost jobs).
- **The backend image listens on `$PORT`** (Render sets it); local/compose default is 8000.

## Deployment

`render.yaml` (Render Blueprint: API + Postgres + Key Value, deploys `main` after CI passes) and
Vercel for `frontend/` (root dir `frontend`, env `BACKEND_URL`). Walkthrough and troubleshooting:
`docs/deployment.md`. `deploy.yml` is an optional Actions-driven flow, off unless the repo
variable `DEPLOY_VIA_ACTIONS=true`; `eval.yml` runs only with `EVAL_ENABLED=true`. The repo is
**public**: never commit `.env`, keys or real label photos (`eval/dataset/images/` is git-ignored).

## Where to look

| Need | File |
|---|---|
| Scoring rules / numbers | `backend/app/services/scoring/thresholds.py` |
| Additive data | `backend/data/additives_ref.csv` |
| Label parsing, unit and basis conversion | `backend/app/services/normalise/` |
| Worker pipeline | `backend/app/services/pipeline.py` |
| Endpoints | `backend/app/api/v1/` |
| Response shapes | `backend/app/schemas/api.py` ↔ `frontend/lib/api/schemas.ts` |
| Result screen | `frontend/app/result/[id]/page.tsx` |
| Edge case → test map | `docs/edge-cases.md` |
| Why things are the way they are | `docs/adr/` |

## Dependency updates

There is no Dependabot (removed on purpose). Update dependencies manually in a PR: keep coupled
packages together (Next + eslint-config-next; Vitest + `@vitejs/plugin-react` + Vite), run
`npm audit --audit-level=high` and `pip-audit`, and let CI verify. GitHub Actions should stay on
Node 24 releases.
