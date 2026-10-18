import { NUTRIENT_KEYS, type Nutrition } from "@/lib/api/schemas";
import { NUTRIENT_LABELS, formatValue, trafficLight, type Level } from "@/lib/nutrition";
import { cn } from "@/lib/utils";

const LEVEL_STYLE: Record<Level, string> = {
  low: "bg-green-100 text-green-900",
  medium: "bg-amber-100 text-amber-900",
  high: "bg-red-100 text-red-900",
};

export function NutritionTable({
  nutrition,
  isBeverage,
  fieldConfidence = {},
}: {
  nutrition: Nutrition;
  isBeverage: boolean;
  fieldConfidence?: Record<string, number>;
}) {
  return (
    <table className="w-full text-sm">
      <caption className="mb-2 text-left text-gray-500">
        Per {isBeverage ? "100 ml" : "100 g"}
        {nutrition.source === "user" && " · edited by you"}
      </caption>
      <tbody>
        {NUTRIENT_KEYS.map((key) => {
          const value = nutrition[key];
          const level = trafficLight(key, value, isBeverage);
          const unsure = nutrition.source === "llm" && (fieldConfidence[key] ?? 1) < 0.7;
          return (
            <tr key={key} className="border-b border-gray-100 last:border-0">
              <th scope="row" className="py-2 text-left font-normal text-gray-700">
                {NUTRIENT_LABELS[key].label}
                {unsure && <span className="ml-2 text-xs text-amber-700">(unsure)</span>}
              </th>
              <td className="py-2 text-right tabular-nums">
                {formatValue(value)} {value != null && NUTRIENT_LABELS[key].unit}
              </td>
              <td className="w-20 py-2 pl-2 text-right">
                {level && (
                  <span
                    className={cn(
                      "rounded px-2 py-0.5 text-xs font-medium capitalize",
                      LEVEL_STYLE[level],
                    )}
                  >
                    {level}
                  </span>
                )}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
