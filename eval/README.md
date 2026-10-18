# Extraction evaluation

Measures how well a provider + prompt reads real labels, through the **real** pipeline
(extraction → schema validation → normalisation → scoring).

```bash
# from the repo root, with the backend venv active
python -m eval.run --provider fake                 # free smoke run (CI)
python -m eval.run --provider claude --prompt v1   # real run — costs money
python -m eval.run --provider gemini --only noodles --no-write
```

Reports per-field exact-match accuracy, within-5 % accuracy, hallucination rate (value returned
where the label prints none), ingredient-list F1, score MAE, band accuracy, failure and
NEEDS_REVIEW rates, average/p95 latency and cost per scan. Each run appends to `results.md`.
`--min-exact 0.9` makes the command fail below 90 % exact accuracy (used by the nightly job).

## Adding a case

1. Photograph a packet: front, nutrition table, ingredients. Include some deliberately bad
   photos (glare, blur, cut-off, per-serving-only labels, Hindi/Telugu labels).
2. Put the photos in `dataset/images/` (git-ignored — they can contain personal data).
3. Create `dataset/<id>.json`:

```json
{
  "id": "chips_salted_brandx",
  "category": "chips",
  "images": {
    "front": "images/chips_salted_brandx_front.jpg",
    "nutrition": "images/chips_salted_brandx_nutrition.jpg",
    "ingredients": "images/chips_salted_brandx_ingredients.jpg"
  },
  "expected": {
    "is_food_label": true,
    "basis": "per_100g",
    "nutrition": { "energy_kcal": 536, "sugars_g": 0.9, "added_sugars_g": null, "carbs_g": 53,
                   "fat_g": 33, "sat_fat_g": 15, "trans_fat_g": 0.1, "salt_g": 1.55,
                   "fibre_g": null, "protein_g": 6.4 },
    "ingredients": ["Potato", "Edible vegetable oil (palmolein)", "Salt"],
    "score": 31,
    "band": "BAD"
  }
}
```

Ground-truth nutrition is **normalised per 100 g/ml** (convert per-serving labels yourself) and
`null` means "not printed on the label". `score`/`band` are optional.
`fake_fixture` (optional) names the recorded response the `fake` provider replays.

The three bundled cases are synthetic and mirror the recorded fixtures; they prove the harness
works. Target: 40–50 real packets across biscuits, chips, drinks, dairy, noodles and sauces.
