# API reference (v1)

Interactive docs: `http://localhost:8000/docs` (disabled in production). The machine-readable
contract is `frontend/lib/api/openapi.json` (regenerate with
`python backend/scripts/export_openapi.py frontend/lib/api/openapi.json`).

Base path `/api/v1`. Auth is `Authorization: Bearer <access_token>`; endpoints marked *guest*
also work without a token (a guest cookie identifies the caller).

| Method | Path | Auth | Purpose | Notes |
|---|---|---|---|---|
| POST | `/auth/register` | — | Create account | Password ≥ 10 chars with a letter and a digit; rate limited |
| POST | `/auth/login` | — | Access + refresh tokens | Lockout after 5 failures for 15 min |
| POST | `/auth/refresh` | cookie | Rotate tokens | Reuse of a rotated token revokes the whole family |
| POST | `/auth/logout` | cookie | Revoke refresh token | |
| GET | `/auth/me` | user | Current user | |
| POST | `/scans` | guest | Upload 3 images, start scan | multipart `front`, `nutrition`, `ingredients`; `Idempotency-Key`; **200** cached / **202** queued |
| GET | `/scans/{id}` | guest | Status and result | Owner only; `ETag` / `If-None-Match` → 304 |
| GET | `/scans/{id}/events` | guest | Live status (SSE) | Alternative to polling |
| PATCH | `/scans/{id}/nutrition` | guest | Correct values → re-score | Per 100 g/ml; marks `user_corrected`; cache untouched |
| POST | `/scans/{id}/confirm` | guest | Accept NEEDS_REVIEW values | → DONE |
| GET | `/scans?q=&cursor=&limit=` | user | History | Newest first, cursor pagination (20), search by name/brand |
| DELETE | `/scans/{id}` | guest | Delete scan | Hard delete |
| POST | `/scans/{id}/feedback` | guest | Report a problem | |
| GET | `/products/{barcode}` | — | Cached product result | Public, `Cache-Control: public, max-age=300` |
| GET | `/methodology` | — | Scoring rules and sources | Generated from engine constants |
| DELETE | `/me` | user | Delete account and all data | DPDP Act |
| GET | `/health` · `/ready` · `/metrics` | — | Liveness · readiness (DB + Redis) · Prometheus | outside `/api/v1` |

## Result

```json
{
  "id": "5f1c…", "status": "DONE", "score": 39, "band": "BAD",
  "verdict": "Eat rarely — mainly high sugar and high saturated fat",
  "confidence": 0.95, "is_partial": false, "from_cache": false, "nova": 4,
  "product": { "name": "Choco Cream Biscuit", "brand": "Acme Foods", "barcode": "8901234567890" },
  "penalties": [{ "factor": "sugar", "label": "High sugar", "points": 18.0,
                  "reason": "Sugar 30 g/100 g is high (> 22.5 g)" }],
  "positives": [{ "factor": "protein", "label": "Good source of protein", "points": 2.4,
                  "reason": "Protein 6 g/100 g (≥ 5 g)" }],
  "nutrition": { "basis": "per_100g", "source": "llm", "energy_kcal": 480, "sugars_g": 30 },
  "review_issues": [], "field_confidence": { "sugars_g": 0.95 },
  "disclaimer": "For general information only. Not medical or dietary advice."
}
```

## Errors — RFC 9457 Problem Details

Every error is `application/problem+json`:

```json
{
  "type": "https://foodscore.app/errors/duplicate-image",
  "title": "Two photos are the same",
  "status": 422,
  "detail": "Please retake the nutrition photo — it matches another photo.",
  "retake": ["nutrition"],
  "request_id": "req_8c2…"
}
```

| Slug | Status | When |
|---|---|---|
| `validation-error` | 422 | Request body/form failed validation (`errors` lists fields) |
| `unsupported-image` | 415 | Not JPEG/PNG/WebP, corrupt, or HEIC |
| `image-too-large` | 413 | Over 5 MB after client compression |
| `duplicate-image` | 422 | Two photos are (nearly) identical |
| `quota-exceeded` | 429 | Daily new-scan quota used (cached products still free) |
| `rate-limited` | 429 | Too many requests (`Retry-After`) |
| `budget-exhausted` | 503 | Global daily AI budget reached |
| `queue-unavailable` | 503 | Job queue down (`Retry-After: 30`) |
| `invalid-credentials` / `account-locked` | 401 / 429 | Login |
| `not-found` | 404 | Missing **or not yours** (same response, prevents id probing) |

Failed scans carry the same shape in `scan.error`, e.g. `unreadable-label` with
`"retake": ["nutrition"]`, `not-food-label`, `provider-unavailable`, `timeout`.
