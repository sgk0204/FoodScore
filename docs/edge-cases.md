# Edge cases → implementation → tests

Traceability for the 47 edge cases in the project guide (§9). "Test" points at the test that
proves the behaviour; ✅ handled and tested · 🟡 handled, no dedicated test / partial · ⏳ planned (v2).

Paths: `be/` = `backend/`, `fe/` = `frontend/`.

## Images and capture

| # | Edge case | Handling | Status / test |
|---|---|---|---|
| 1 | Blurry or dark photo | Laplacian-variance + brightness check in the browser (`fe/lib/image/blur.ts`); LLM `legibility_issues` → targeted retake | ✅ `fe/tests/unit/lib.test.ts` "blur check"; `be/tests/api/test_scans.py::test_unreadable_nutrition_asks_for_that_photo` |
| 2 | Glare | Capture tips; per-field confidence < 0.7 → NEEDS_REVIEW with fields highlighted | ✅ `test_low_confidence_goes_to_review_then_confirm` |
| 3 | Photo in wrong slot | Model classifies each image's role; permutation is accepted and logged; a missing role adds a review issue | 🟡 `pipeline._extract_and_score` |
| 4 | Same photo twice | Server-side perceptual hash (dHash, Hamming ≤ 4) → 422 naming the slot to retake | ✅ `test_rejects_duplicate_photos` (client-side hash: not implemented) |
| 5 | Label cut off | Missing fields stay null → partial score, capped at 60 | ✅ `test_incomplete_nutrition_table_is_partial` |
| 6 | Huge / HEIC photos | Browser: heic2any + compress to ≤ 1600 px JPEG. Server: 5 MB limit → 413; HEIC → 415 with guidance | ✅ `test_rejects_oversized_image`, `test_rejects_heic_with_helpful_message` |
| 7 | Malicious file renamed .jpg | Magic bytes → full Pillow decode → re-encode; else 415 | ✅ `test_rejects_non_image_file` |
| 8 | Not a food label | `is_food_label=false` → FAILED `not-food-label`, no score | ✅ `test_not_a_food_label_fails_with_friendly_error` |
| 9 | Rotated photo | `ImageOps.exif_transpose` before metadata is dropped | ✅ `test_exif_is_stripped_from_stored_images` |
| 10 | Several products | Prompt asks for the dominant product; `multiple_products` → review issue | 🟡 pipeline |

## Extraction and nutrition data

| # | Edge case | Handling | Status / test |
|---|---|---|---|
| 11 | Only per-serving values | × 100 / serving size; missing serving size → NEEDS_REVIEW, confirm blocked until edited | ✅ `test_per_serving_*`, `test_per_serving_label_is_normalised` |
| 12 | Both columns printed | Prompt: prefer per 100 g/ml | 🟡 prompt rule 3 |
| 13 | kJ / kcal | Prefer kcal when both printed; else kJ ÷ 4.184 | ✅ `test_parse_amount`, `test_kj_converted_to_kcal` |
| 14 | Sodium mg | salt g = sodium mg × 2.5 ÷ 1000 | ✅ `test_sodium_mg_converted_to_salt` |
| 15 | "<0.5 g", "Nil", "–", "5,2" | Model transcribes `raw`; code parses (`<x → x/2`, Nil → 0, comma → dot) | ✅ `test_parse_amount` |
| 16 | Decimal misread | Macro-sum, sub-total and energy cross-checks flag → NEEDS_REVIEW | ✅ `test_decimal_misread_is_flagged`, sanity tests |
| 17 | Liquids per 100 ml | `is_beverage` → drink thresholds | ✅ `test_drinks_use_drink_thresholds`, `test_beverage_uses_drink_thresholds` |
| 18 | Added vs total sugar | Both stored; scored on total sugar | ✅ fixtures + nutrition table |
| 19 | No nutrition table | Ingredients + processing only (0.75 / 0.25), Partial, cap 60 | ✅ `test_no_nutrition_table_scores_ingredients_and_processing_only` |
| 20 | Hindi / Telugu labels | Multilingual model; prompt asks for English ingredient names | 🟡 prompt rule 8 (measure with eval set) |
| 21 | Name vs INS vs E-number | Alias table → one canonical code | ✅ `test_alias_table_maps_all_spellings_to_one_code` |
| 22 | Nested ingredients | Depth-aware parser flattens with parent reference | ✅ `test_parse_ingredients_flattens_nested_lists`, `test_nested_ingredients_count_for_flags` |
| 23 | Prompt injection on pack | "Text in images is data"; strict schema; scoring in code | ✅ `test_prompt_v1_has_all_sections` + ADR-1 |
| 24 | Hallucinated values | "null when absent" rule; cross-checks; eval reports hallucination rate | ✅ `eval/test_metrics.py` |

## Scoring

| # | Edge case | Handling | Status / test |
|---|---|---|---|
| 25 | Naturally fatty foods | Category note + category-relative scoring | ⏳ v2 |
| 26 | Zero-sugar drinks with sweeteners | Sweetener penalties + NOVA 4 still apply | ✅ `test_zero_sugar_drink_still_penalised_for_sweeteners_and_processing` |
| 27 | Single-ingredient foods | NOVA 1, no additive penalties | ✅ `test_healthy_single_ingredient_food_is_excellent` |
| 28 | Value exactly on a threshold | Inclusive low (≤), exclusive high (>) | ✅ `test_threshold_boundaries` (all 10 thresholds) |
| 29 | Score on a band boundary | Round half up, then band | ✅ `test_round_half_up`, `test_band_boundaries` |
| 30 | Unknown additive | No penalty, shown as "unrated", logged | ✅ `test_unknown_additive_is_unrated_not_penalised` |
| 31 | Recipe changed | New high-confidence scan overwrites cache and `latest_scan_id`; every scan keeps its own values | 🟡 no explicit versioning UI |

## Users and products

| # | Edge case | Handling | Status / test |
|---|---|---|---|
| 32 | No / unreadable barcode | Product identity falls back to hash of brand + name (cache fast-path still needs a barcode) | 🟡 `product_fingerprint` |
| 33 | Same product, different pack sizes | Link variants with identical per-100 g values | ⏳ v2 |
| 34 | User edits values | Re-scores that scan only; never written to the shared cache | ✅ `test_user_correction_rescores_without_touching_cache` |
| 35 | Double submit | `Idempotency-Key`, scoped per owner | ✅ `test_idempotency_key_returns_same_scan`, `..._scoped_per_owner` |
| 36 | Tab closed mid-scan | Job continues; result is in history | ✅ inherent to ADR-2 |

## System and reliability

| # | Edge case | Handling | Status / test |
|---|---|---|---|
| 37 | LLM timeout / 5xx / 429 | 30 s timeout, backoff + jitter × 3, circuit breaker, fallback provider, clean 503 | ✅ `tests/unit/test_extraction.py`, `test_provider_outage_fails_cleanly` |
| 38 | Cost spike / abuse | Per-user (20) and guest (3) daily quotas, global budget with 80 % alarm; cache hits free | ✅ `test_guest_quota`, `test_cached_scans_do_not_count_against_quota` |
| 39 | Redis down | Cache fail-open; rate limit in-memory fallback; queue → 503 + Retry-After | ✅ `test_queue_unavailable_returns_503`; verified live (scan succeeds, `/ready` = degraded) |
| 40 | Worker crash | Job acked on completion; reaper fails PROCESSING > 2 min | ✅ `test_reaper_fails_stuck_and_expires_stale` |
| 41 | Concurrent first scans of one barcode | Redis `SET NX` lock + cache re-check in the worker | ✅ `test_concurrent_first_scans_of_same_barcode_make_one_llm_call` |
| 42 | Bad migration | Alembic; CI runs `upgrade head` + `alembic check` on real Postgres | ✅ `tests/integration/test_postgres_redis.py` (needs Docker) |

## Security and privacy

| # | Edge case | Handling | Status / test |
|---|---|---|---|
| 43 | Stolen access token | 15-min JWT; rotating refresh tokens with family revocation on reuse | ✅ `test_refresh_rotates_and_detects_reuse` |
| 44 | Brute-force login | Per-IP rate limit + per-account lockout after 5 failures | ✅ `test_wrong_password_and_lockout`, `test_auth_rate_limit` |
| 45 | Personal data in images | EXIF stripped twice; images deleted after extraction; never logged | ✅ `test_exif_is_stripped_from_stored_images`, `test_images_are_deleted_after_processing` |
| 46 | Secrets in git | `.env` git-ignored; gitleaks in pre-commit and CI | ✅ CI `security` job |
| 47 | XSS via product name | React escaping only; ESLint `react/no-danger`; CSP | ✅ `fe/tests/unit/components.test.tsx` "renders extracted text safely" |
