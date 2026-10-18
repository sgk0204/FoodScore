"use client";

import { BandScale } from "@/components/BandScale";
import { Card, CardTitle } from "@/components/ui/card";
import { useMethodology } from "@/lib/api/hooks";
import type { Threshold } from "@/lib/api/schemas";

/** Public methodology (F10). Rendered from GET /methodology, i.e. from the engine's own constants. */
export default function MethodologyPage() {
  const { data: m, isLoading, error } = useMethodology();
  if (isLoading) return <p className="text-gray-500">Loading…</p>;
  if (error || !m) return <p className="text-red-700">Couldn&apos;t load the methodology.</p>;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">How we score</h1>
        <p className="mt-1 text-sm text-gray-500">Scoring version {m.scoring_version}</p>
      </div>

      <Card>
        <CardTitle>The formula</CardTitle>
        <p className="rounded-lg bg-gray-50 p-3 font-mono text-sm">{m.formula}</p>
        <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-gray-700">
          <li>
            <strong>Nutrients ({m.weights.nutrient! * 100}%)</strong> start at 100; sugar, saturated
            fat, salt, fat and energy subtract points; fibre and protein add some back.
          </li>
          <li>
            <strong>Ingredients ({m.weights.ingredient! * 100}%)</strong> start at 100; additives
            and some ingredients subtract points.
          </li>
          <li>
            <strong>Processing ({m.weights.processing! * 100}%)</strong> from the NOVA group:{" "}
            {Object.entries(m.nova_scores)
              .map(([g, s]) => `NOVA ${g} = ${s}`)
              .join(" · ")}
            .
          </li>
        </ul>
        <p className="mt-3 text-sm text-gray-700">{m.rounding}</p>
      </Card>

      <Card>
        <CardTitle>Nutrient thresholds</CardTitle>
        <p className="mb-3 text-sm text-gray-600">
          UK FSA traffic-light cut-offs. At or below <em>low</em> costs nothing; above <em>high</em>{" "}
          costs the maximum; linear in between.
        </p>
        <div className="grid gap-4 md:grid-cols-2">
          <ThresholdTable title="Foods (per 100 g)" rows={m.nutrient_thresholds.food_per_100g} />
          <ThresholdTable
            title="Drinks (per 100 ml)"
            rows={m.nutrient_thresholds.drink_per_100ml}
          />
        </div>
      </Card>

      <Card>
        <CardTitle>Caps and bands</CardTitle>
        <ul className="mb-3 list-disc space-y-1 pl-5 text-sm text-gray-700">
          {m.caps.map((c) => (
            <li key={c.rule}>
              Capped at <strong>{c.cap}</strong> when {c.when}.
            </li>
          ))}
        </ul>
        <BandScale />
      </Card>

      <Card>
        <CardTitle>Additive ratings</CardTitle>
        <p className="mb-3 text-sm text-gray-600">
          High-concern −{m.ingredient_penalties.high_concern_additive} · moderate −
          {m.ingredient_penalties.moderate_concern_additive} · low −
          {m.ingredient_penalties.low_concern_additive}. Unknown additives are not penalised and are
          queued for review.
        </p>
        <div className="max-h-96 overflow-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-white text-left text-gray-500">
              <tr>
                <th className="py-1">Code</th>
                <th className="py-1">Name</th>
                <th className="py-1">Tier</th>
                <th className="py-1">Source</th>
              </tr>
            </thead>
            <tbody>
              {m.additives.map((a) => (
                <tr key={a.code} className="border-t border-gray-100">
                  <td className="py-1 pr-2 tabular-nums">
                    {a.code.startsWith("X-") ? "—" : a.code}
                  </td>
                  <td className="py-1 pr-2">{a.name}</td>
                  <td className="py-1 pr-2 capitalize">{a.risk_tier}</td>
                  <td className="py-1">
                    <a
                      href={a.source_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-brand underline"
                    >
                      link
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card>
        <CardTitle>Sources</CardTitle>
        <ul className="list-disc space-y-1 pl-5 text-sm">
          {m.sources.map((s) => (
            <li key={s.url}>
              <a
                href={s.url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-brand underline"
              >
                {s.name}
              </a>
            </li>
          ))}
        </ul>
        <p className="mt-3 text-sm text-gray-600">{m.disclaimer}</p>
      </Card>
    </div>
  );
}

function ThresholdTable({ title, rows }: { title: string; rows: Threshold[] }) {
  return (
    <table className="w-full text-sm">
      <caption className="mb-1 text-left font-medium">{title}</caption>
      <thead className="text-left text-gray-500">
        <tr>
          <th className="py-1">Nutrient</th>
          <th className="py-1">Low ≤</th>
          <th className="py-1">High &gt;</th>
          <th className="py-1">Max</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.factor} className="border-t border-gray-100">
            <td className="py-1">{r.name}</td>
            <td className="py-1 tabular-nums">
              {r.low} {r.unit}
            </td>
            <td className="py-1 tabular-nums">
              {r.high} {r.unit}
            </td>
            <td className="py-1 tabular-nums">−{r.max_penalty}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
