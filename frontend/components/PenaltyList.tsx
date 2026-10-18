import { ArrowDown, ArrowUp } from "lucide-react";

import type { Factor } from "@/lib/api/schemas";

export function PenaltyList({ items, kind }: { items: Factor[]; kind: "penalty" | "positive" }) {
  const shown = kind === "positive" ? items : items.filter((p) => p.points > 0);
  if (!shown.length) {
    return (
      <p className="text-sm text-gray-500">
        {kind === "penalty" ? "Nothing significant." : "No positive factors found."}
      </p>
    );
  }
  return (
    <ol className="space-y-2">
      {shown.map((p) => (
        <li
          key={p.factor}
          className="flex items-start justify-between gap-3 rounded-lg bg-gray-50 p-3"
        >
          <div className="min-w-0">
            <p className="font-medium text-gray-900">
              {p.label}
              {p.code && !p.code.startsWith("X-") && (
                <span className="ml-2 text-xs text-gray-500">{p.code}</span>
              )}
            </p>
            <p className="text-sm text-gray-600">{p.reason}</p>
          </div>
          {p.points > 0 && (
            <span
              className={`flex shrink-0 items-center gap-0.5 text-sm font-semibold tabular-nums ${
                kind === "penalty" ? "text-red-700" : "text-green-700"
              }`}
            >
              {kind === "penalty" ? (
                <ArrowDown aria-hidden className="h-4 w-4" />
              ) : (
                <ArrowUp aria-hidden className="h-4 w-4" />
              )}
              <span className="sr-only">{kind === "penalty" ? "minus" : "plus"}</span>
              {p.points.toFixed(1)}
            </span>
          )}
        </li>
      ))}
    </ol>
  );
}
