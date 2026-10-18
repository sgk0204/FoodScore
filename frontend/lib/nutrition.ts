import type { NutrientKey } from "./api/schemas";

export const NUTRIENT_LABELS: Record<NutrientKey, { label: string; unit: string }> = {
  energy_kcal: { label: "Energy", unit: "kcal" },
  sugars_g: { label: "Total sugars", unit: "g" },
  added_sugars_g: { label: "Added sugars", unit: "g" },
  carbs_g: { label: "Carbohydrates", unit: "g" },
  fat_g: { label: "Total fat", unit: "g" },
  sat_fat_g: { label: "Saturated fat", unit: "g" },
  trans_fat_g: { label: "Trans fat", unit: "g" },
  salt_g: { label: "Salt", unit: "g" },
  fibre_g: { label: "Fibre", unit: "g" },
  protein_g: { label: "Protein", unit: "g" },
};

export type Level = "low" | "medium" | "high";

// UK FSA traffic-light cut-offs (same numbers the scoring engine uses).
const FOOD: Partial<Record<NutrientKey, [number, number]>> = {
  sugars_g: [5, 22.5],
  sat_fat_g: [1.5, 5],
  salt_g: [0.3, 1.5],
  fat_g: [3, 17.5],
};
const DRINK: Partial<Record<NutrientKey, [number, number]>> = {
  sugars_g: [2.5, 11.25],
  sat_fat_g: [0.75, 2.5],
  salt_g: [0.3, 0.75],
  fat_g: [1.5, 8.75],
};

export function trafficLight(
  key: NutrientKey,
  value: number | null | undefined,
  isBeverage: boolean,
): Level | null {
  if (value == null) return null;
  const t = (isBeverage ? DRINK : FOOD)[key];
  if (!t) return null;
  if (value <= t[0]) return "low";
  if (value > t[1]) return "high";
  return "medium";
}

export function formatValue(value: number | null | undefined): string {
  if (value == null) return "—";
  return Number.isInteger(value) ? String(value) : value.toFixed(value < 1 ? 2 : 1);
}
