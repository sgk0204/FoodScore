"use client";

import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { ApiError, type NutritionPatch } from "@/lib/api/client";
import { useConfirmScan, useCorrectNutrition } from "@/lib/api/hooks";
import { NUTRIENT_KEYS, type NutrientKey, type Scan } from "@/lib/api/schemas";
import { NUTRIENT_LABELS } from "@/lib/nutrition";
import { cn } from "@/lib/utils";

/**
 * Editable table of extracted values (feature F4). Low-confidence fields are highlighted.
 * Saving re-scores this scan only — the shared product cache is never changed by user edits.
 */
export function ReviewForm({ scan, onDone }: { scan: Scan; onDone?: () => void }) {
  const initial = Object.fromEntries(
    NUTRIENT_KEYS.map((k) => [k, scan.nutrition?.[k] == null ? "" : String(scan.nutrition[k])]),
  ) as Record<NutrientKey, string>;
  const [values, setValues] = useState(initial);
  const [ingredients, setIngredients] = useState(scan.ingredients.join("\n"));
  const [isBeverage, setIsBeverage] = useState(scan.is_beverage);
  const correct = useCorrectNutrition(scan.id);
  const confirm = useConfirmScan(scan.id);
  const lowFields = new Set(
    Object.entries(scan.field_confidence)
      .filter(([, c]) => c < 0.7)
      .map(([f]) => f),
  );
  const flagged = new Set(scan.review_issues.map((i) => i.field));
  const error = (correct.error ?? confirm.error) as ApiError | Error | null;
  const inReview = scan.status === "NEEDS_REVIEW";

  function buildPatch(): NutritionPatch {
    const patch: NutritionPatch = {};
    for (const key of NUTRIENT_KEYS) {
      const raw = values[key].trim().replace(",", ".");
      const parsed = raw === "" ? null : Number(raw);
      if (parsed !== null && Number.isNaN(parsed)) continue;
      if (parsed !== (scan.nutrition?.[key] ?? null)) patch[key] = parsed;
    }
    const list = ingredients
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean);
    if (list.join("\n") !== scan.ingredients.join("\n")) patch.ingredients = list;
    if (isBeverage !== scan.is_beverage) patch.is_beverage = isBeverage;
    return patch;
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    await correct.mutateAsync(buildPatch());
    onDone?.();
  }

  return (
    <form onSubmit={(e) => void save(e)} className="space-y-4" aria-label="Edit extracted values">
      {inReview && (
        <Alert tone="warning" title="Please check these values">
          <ul className="mt-1 list-disc pl-5">
            {scan.review_issues.map((i, idx) => (
              <li key={idx}>{i.message}</li>
            ))}
          </ul>
        </Alert>
      )}
      <fieldset>
        <legend className="mb-2 text-sm text-gray-600">
          Values per {isBeverage ? "100 ml" : "100 g"}. Leave blank if not printed.
        </legend>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {NUTRIENT_KEYS.map((key) => {
            const warn = lowFields.has(key) || flagged.has(key);
            return (
              <label key={key} className="block">
                <span
                  className={cn("text-sm", warn ? "font-semibold text-amber-800" : "text-gray-700")}
                >
                  {NUTRIENT_LABELS[key].label} ({NUTRIENT_LABELS[key].unit})
                  {warn && " — please check"}
                </span>
                <input
                  inputMode="decimal"
                  name={key}
                  value={values[key]}
                  onChange={(e) => setValues((v) => ({ ...v, [key]: e.target.value }))}
                  className={cn(
                    "mt-1 w-full rounded-lg border px-3 py-2 tabular-nums",
                    warn ? "border-amber-500 bg-amber-50" : "border-gray-300",
                  )}
                />
              </label>
            );
          })}
        </div>
      </fieldset>
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={isBeverage}
          onChange={(e) => setIsBeverage(e.target.checked)}
        />
        This is a drink (use per 100 ml thresholds)
      </label>
      <label className="block">
        <span className="text-sm text-gray-700">Ingredients (one per line, in label order)</span>
        <textarea
          rows={6}
          value={ingredients}
          onChange={(e) => setIngredients(e.target.value)}
          className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
        />
      </label>
      {error && (
        <Alert tone="error" title="Couldn't save">
          {error.message}
        </Alert>
      )}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={correct.isPending}>
          {correct.isPending ? "Saving…" : "Save and re-score"}
        </Button>
        {inReview && (
          <Button
            type="button"
            variant="secondary"
            disabled={confirm.isPending}
            onClick={() => void confirm.mutateAsync().then(() => onDone?.())}
          >
            Values look right
          </Button>
        )}
      </div>
    </form>
  );
}
