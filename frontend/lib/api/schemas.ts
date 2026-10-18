/**
 * Runtime validation of API responses (guide §2: "Zod validates API responses at runtime").
 * Static types come from the backend's OpenAPI schema (`npm run gen:api` → schema.d.ts);
 * these Zod schemas guard against drift at runtime and are what the UI actually consumes.
 */
import { z } from "zod";

export const ScanStatus = z.enum([
  "QUEUED",
  "PROCESSING",
  "NEEDS_REVIEW",
  "DONE",
  "FAILED",
  "EXPIRED",
]);
export type ScanStatus = z.infer<typeof ScanStatus>;

export const Band = z.enum(["VERY_BAD", "BAD", "GOOD", "VERY_GOOD", "EXCELLENT"]);
export type Band = z.infer<typeof Band>;

export const Factor = z.object({
  factor: z.string(),
  label: z.string(),
  points: z.number(),
  reason: z.string(),
  code: z.string().nullable().optional(),
});
export type Factor = z.infer<typeof Factor>;

export const NUTRIENT_KEYS = [
  "energy_kcal",
  "sugars_g",
  "added_sugars_g",
  "carbs_g",
  "fat_g",
  "sat_fat_g",
  "trans_fat_g",
  "salt_g",
  "fibre_g",
  "protein_g",
] as const;
export type NutrientKey = (typeof NUTRIENT_KEYS)[number];

const nutrientShape = Object.fromEntries(
  NUTRIENT_KEYS.map((k) => [k, z.number().nullable().optional()]),
) as Record<NutrientKey, z.ZodOptional<z.ZodNullable<z.ZodNumber>>>;

export const Nutrition = z.object({
  basis: z.string(),
  source: z.enum(["llm", "user"]),
  ...nutrientShape,
});
export type Nutrition = z.infer<typeof Nutrition>;

export const Problem = z
  .object({
    type: z.string(),
    title: z.string(),
    status: z.number(),
    detail: z.string().optional(),
    retake: z.array(z.string()).optional(),
    request_id: z.string().nullable().optional(),
  })
  .passthrough();
export type Problem = z.infer<typeof Problem>;

export const Product = z.object({
  name: z.string().nullable().optional(),
  brand: z.string().nullable().optional(),
  barcode: z.string().nullable().optional(),
  category: z.string().nullable().optional(),
});

export const Scan = z.object({
  id: z.string().uuid(),
  status: ScanStatus,
  score: z.number().int().min(0).max(100).nullable(),
  band: Band.nullable(),
  verdict: z.string().nullable(),
  confidence: z.number().nullable(),
  is_partial: z.boolean(),
  is_beverage: z.boolean(),
  user_corrected: z.boolean(),
  from_cache: z.boolean(),
  nova: z.number().nullable(),
  product: Product,
  penalties: z.array(Factor),
  positives: z.array(Factor),
  caps_applied: z.array(z.object({ rule: z.string(), cap: z.number(), reason: z.string() })),
  nutrition: Nutrition.nullable(),
  ingredients: z.array(z.string()),
  flagged_ingredients: z.array(z.string()),
  unrated_additives: z.array(z.string()),
  review_issues: z.array(z.object({ field: z.string(), code: z.string(), message: z.string() })),
  field_confidence: z.record(z.number()),
  error: Problem.nullable(),
  created_at: z.string(),
  completed_at: z.string().nullable(),
  disclaimer: z.string(),
});
export type Scan = z.infer<typeof Scan>;

export const ScanSummary = z.object({
  id: z.string().uuid(),
  status: ScanStatus,
  score: z.number().nullable(),
  band: Band.nullable(),
  product: Product,
  is_partial: z.boolean(),
  user_corrected: z.boolean(),
  created_at: z.string(),
});
export type ScanSummary = z.infer<typeof ScanSummary>;

export const ScanPage = z.object({
  items: z.array(ScanSummary),
  next_cursor: z.string().nullable(),
});
export type ScanPage = z.infer<typeof ScanPage>;

export const Token = z.object({
  access_token: z.string(),
  token_type: z.literal("bearer"),
  expires_in: z.number(),
});

export const User = z.object({
  id: z.string(),
  email: z.string(),
  created_at: z.string(),
  is_admin: z.boolean(),
});
export type User = z.infer<typeof User>;

const Threshold = z.object({
  factor: z.string(),
  name: z.string(),
  unit: z.string(),
  low: z.number(),
  high: z.number(),
  max_penalty: z.number(),
});
export type Threshold = z.infer<typeof Threshold>;

export const Methodology = z.object({
  scoring_version: z.string(),
  formula: z.string(),
  weights: z.record(z.number()),
  nutrient_thresholds: z.object({
    food_per_100g: z.array(Threshold),
    drink_per_100ml: z.array(Threshold),
  }),
  bonuses: z.array(
    z.object({
      factor: z.string(),
      tiers: z.array(z.object({ min_g: z.number(), points: z.number() })),
    }),
  ),
  nova_scores: z.record(z.number()),
  ingredient_penalties: z.record(z.number()),
  caps: z.array(z.object({ rule: z.string(), cap: z.number(), when: z.string() })),
  bands: z.array(z.object({ max: z.number(), band: Band, label: z.string() })),
  rounding: z.string(),
  parsing_rules: z.record(z.string()),
  sources: z.array(z.object({ name: z.string(), url: z.string() })),
  additives: z.array(
    z.object({
      code: z.string(),
      name: z.string(),
      risk_tier: z.enum(["low", "moderate", "high"]),
      source_url: z.string(),
      notes: z.string(),
    }),
  ),
  disclaimer: z.string(),
});
export type Methodology = z.infer<typeof Methodology>;

export const TERMINAL: ReadonlySet<ScanStatus> = new Set(["DONE", "FAILED", "EXPIRED"]);
