# Architecture

FoodScore uses a classic **API + background worker** pattern. The browser only talks to the
Next.js origin; `/api/*` is proxied to FastAPI, so AI keys never reach the client and the
refresh-token cookie stays first-party.

```mermaid
flowchart TB
  subgraph Client
    U[Browser / mobile web] -->|HTTPS| FE[Next.js frontend<br/>capture · compress · poll]
  end
  subgraph Backend
    API[FastAPI API<br/>auth · rate limit · image checks<br/>barcode lookup · enqueue]
    W[ARQ worker<br/>LLM extraction → validate →<br/>normalise → score]
    R[Reaper cron<br/>every minute]
  end
  subgraph Data
    PG[(PostgreSQL)]
    RD[(Redis<br/>cache · queue · limits · locks)]
    S3[(Object storage<br/>images, deleted after use)]
    LLM[[Vision LLM<br/>Claude / Gemini via adapter]]
  end
  FE -->|/api/v1 REST + JSON| API
  API --> PG & RD & S3
  API -->|enqueue| RD
  RD -->|job| W
  W --> PG & S3
  W -->|images + prompt + schema| LLM
  R --> PG
```

## Request flow — new product

```mermaid
sequenceDiagram
  participant B as Browser
  participant A as FastAPI
  participant R as Redis
  participant W as Worker
  participant L as LLM API
  participant P as Postgres
  B->>A: POST /scans (3 images, Idempotency-Key)
  A->>R: rate-limit INCR · quota INCR
  A->>A: magic bytes · decode · re-encode · dHash · barcode
  A->>R: GET product:{barcode} (miss)
  A->>P: INSERT scan QUEUED
  A->>R: enqueue process_scan_job
  A-->>B: 202 {id, status: QUEUED}
  R->>W: job
  W->>R: SET NX lock:barcode
  W->>L: images + prompt + JSON schema
  L-->>W: Extraction JSON
  W->>W: validate · normalise · sanity checks · score
  W->>P: UPDATE scan DONE · nutrition · penalties
  W->>R: SET product:{barcode}
  B->>A: GET /scans/{id} (If-None-Match)
  A-->>B: 200 {score, band, penalties}
```

A repeat scan of a cached barcode returns **200** from the API directly (no queue, no LLM).

## Scan state machine

```mermaid
stateDiagram-v2
  [*] --> QUEUED
  QUEUED --> PROCESSING: worker picks job
  PROCESSING --> DONE: confident extraction
  PROCESSING --> NEEDS_REVIEW: low confidence / sanity issue
  PROCESSING --> FAILED: unreadable · not food · provider down · reaper (> 2 min)
  NEEDS_REVIEW --> DONE: user confirms or edits
  NEEDS_REVIEW --> EXPIRED: not reviewed in 24 h
  DONE --> DONE: user correction re-scores
```

## Components

| Component | Code | Responsibility |
|---|---|---|
| Frontend | `frontend/app`, `frontend/components` | Guided capture, client-side image prep, upload with progress, polling, result/review/history |
| API | `backend/app/api/v1` | Auth, rate limits, quotas, image security, barcode, idempotency, job creation, results |
| Pipeline | `backend/app/services/pipeline.py` | Worker job: extract → validate → normalise → score → persist → cache → delete images |
| Extraction | `backend/app/services/extraction` | Provider adapters, prompt loading, retries, circuit breaker, fallback |
| Normalisation | `backend/app/services/normalise` | Label-text parsing, unit/basis conversion, sanity checks, review decision |
| Scoring engine | `backend/app/services/scoring` | Pure functions: thresholds, additives, ingredient rules, NOVA, caps, bands |
| Workers | `backend/app/workers` | ARQ settings, job entry point, reaper cron |
| Data | `backend/app/db` | SQLAlchemy 2 models, Alembic migrations, additive seed |

## Data model

```mermaid
erDiagram
  users ||--o{ scans : owns
  users ||--o{ refresh_tokens : has
  products ||--o{ scans : "scanned as"
  scans ||--o{ nutrition_facts : "llm / user rows"
  scans ||--o{ score_penalties : explains
  scans ||--o{ feedback : receives
  additives_ref }o..o{ score_penalties : "looked up"
```

Indexes: `products(barcode)` unique, `products(fingerprint)` unique, `scans(user_id, created_at)`
for history, `scans(idempotency_key)` unique, GIN trigram on `products(name)` (Postgres).
`ON DELETE CASCADE` from `users` makes account deletion remove all personal data.

## Failure policy

| Dependency down | Behaviour |
|---|---|
| LLM provider | Retries with backoff → fallback provider → scan FAILED with a 503-style problem, quota kept |
| Redis — cache | Skipped (fail open) |
| Redis — rate limits | In-process counters |
| Redis — queue | `POST /scans` returns 503 + `Retry-After`, images deleted, quota refunded |
| Worker | Job retried by ARQ; reaper marks stuck scans FAILED after 2 min |
| Postgres | `/ready` returns 503 so the platform stops routing traffic |

## Observability

- **Logs:** structlog JSON with `request_id` (propagated via `X-Request-ID`), hashed user id,
  `scan_id`, duration. Passwords, tokens and image bytes are redacted.
- **Metrics** (`/metrics`, Prometheus): scans by status, cache hits/misses, LLM latency
  histogram, LLM cost, extraction failures, user corrections per field.
- **Errors:** Sentry when `SENTRY_DSN` is set (`send_default_pii=False`).
- **Suggested alerts:** failure rate > 10 % over 15 min; `llm_budget_alarm` log events;
  queue depth > 50.

See `docs/adr/` for the reasoning behind each design decision.
