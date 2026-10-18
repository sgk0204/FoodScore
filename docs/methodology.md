# Scoring methodology (v1.0.0)

The live, authoritative version is served by `GET /api/v1/methodology` and rendered at
`/methodology`; it is generated from the engine's constants
(`backend/app/services/scoring/thresholds.py`) so it cannot drift from the code.

> Weights and additive tiers are documented **product decisions** based on public frameworks
> (Nutri-Score, UK FSA traffic lights, NOVA, EFSA/FSSAI/IARC opinions), not scientific facts.
> For general information only — not medical or dietary advice.

## Formula

```
Final = round_half_up(0.6 × NutrientScore + 0.3 × IngredientScore + 0.1 × ProcessingScore)
        → hard caps → clamp 0–100 → band
```

| Layer | Starts at | Adjustments |
|---|---|---|
| NutrientScore | 100 | − nutrient penalties, + fibre/protein bonuses, clamped 0–100 |
| IngredientScore | 100 | − additive and ingredient penalties, clamped 0–100 |
| ProcessingScore | NOVA | 1 → 100 · 2 → 80 · 3 → 60 · 4 → 20 |

With no nutrition table at all: `0.75 × Ingredient + 0.25 × Processing`, labelled **Partial**.

## Nutrient penalties

Linear interpolation: value ≤ low → 0; value > high → max; in between, proportional.

| Nutrient | Food low ≤ | Food high > | Drink low ≤ | Drink high > | Max |
|---|---|---|---|---|---|
| Total sugars | 5 g | 22.5 g | 2.5 g | 11.25 g | 30 |
| Saturated fat | 1.5 g | 5 g | 0.75 g | 2.5 g | 25 |
| Salt (sodium × 2.5) | 0.3 g | 1.5 g | 0.3 g | 0.75 g | 25 |
| Total fat | 3 g | 17.5 g | 1.5 g | 8.75 g | 10 |
| Energy | 400 kcal | 600 kcal | 20 kcal | 80 kcal | 10 |

Bonuses: fibre ≥ 3 g +5, ≥ 6 g +10 · protein ≥ 5 g +4, ≥ 10 g +8.

## Ingredient penalties

| Rule | Points |
|---|---|
| High-concern additive (e.g. INS 171 titanium dioxide, sodium nitrite) | −30 each |
| Moderate-concern additive (azo colours, aspartame, artificial flavour, …) | −15 each |
| Low-concern additive (lecithin, citric acid, raising agents, …) | −5 each |
| Partially hydrogenated oil / vanaspati | −30 |
| Palm oil / palmolein | −10 (once) |
| Added sugar among the first three ingredients | −10 |
| Refined flour (maida) as the first ingredient | −5 |
| Unknown additive | 0 — shown as "unrated" and logged for review |

The table lives in `backend/data/additives_ref.csv` with a source URL per row. **Before
publishing scores, verify every row against primary sources** (EFSA re-evaluations, FSSAI
permitted-additive lists, IARC monographs).

## NOVA classification (heuristic)

Code infers the processing group from the ingredient list (the model does not decide it):

- **4** — any ultra-processing marker (flavourings, emulsifiers, colours, sweeteners,
  hydrogenated fats, maltodextrin, glucose syrup, protein isolates, …), any moderate/high-concern
  additive, or two or more additives
- **3** — several ingredients including salt, sugar, oil, vinegar or similar
- **2** — a single processed culinary ingredient (oil, ghee, sugar, salt, honey)
- **1** — a single whole food or only whole foods
- unknown ingredient list → 3 (neutral)

## Hard caps

| Condition | Cap |
|---|---|
| Trans fat > 0.2 g/100 g, or any partially hydrogenated oil | 40 |
| Any high-concern additive | 50 |
| Nutrition table missing or incomplete (Partial) | 60 |

## Bands

| Very Bad | Bad | Good | Very Good | Excellent |
|---|---|---|---|---|
| 0–20 | 21–40 | 41–60 | 61–80 | 81–100 |

Round half up first, then band: 60.5 → 61 → Very Good.

## Label parsing rules

`"<x"` → x/2 · `Nil`, `None`, `Traces`, `-`, `–` → 0 · decimal comma `5,2` → 5.2 ·
kJ ÷ 4.184 → kcal · sodium mg × 2.5 ÷ 1000 → salt g · per-serving × 100 / serving size.

## Worked example — chocolate cream biscuit (unit-tested)

Per 100 g: energy 480 kcal, sugars 30 g, fat 22 g, saturated fat 10 g, salt 0.6 g, fibre 2 g,
protein 6 g. Ingredients include palm oil, INS 322, INS 503 and artificial flavour. NOVA 4.

| Step | Calculation | Result |
|---|---|---|
| Sugar 30 g | > 22.5 → full | −30 |
| Saturated fat 10 g | > 5 → full | −25 |
| Total fat 22 g | > 17.5 → full | −10 |
| Salt 0.6 g | (0.6 − 0.3)/(1.5 − 0.3) × 25 | −6.25 |
| Energy 480 kcal | (480 − 400)/(600 − 400) × 10 | −4 |
| Protein 6 g | ≥ 5 g | +4 |
| **NutrientScore** | | **28.75** |
| **IngredientScore** | 100 − 10 − 15 − 5 − 5 | **65** |
| **ProcessingScore** | NOVA 4 | **20** |
| **Final** | 0.6 × 28.75 + 0.3 × 65 + 0.1 × 20 = 38.75 | **39 → Bad** |

Reasons are ranked by **weighted** points (what each factor actually moved the final score):
sugar −18 · saturated fat −15 · ultra-processed −8 · total fat −6 · artificial flavour −4.5 ·
salt −3.75 · low-concern additives −3 · palm oil −3 · energy −2.4; positive: protein +2.4.

`backend/tests/unit/test_scoring_engine.py::test_worked_example_*` asserts every number above.
