/** Ingredient chips; ones that triggered a scoring rule are highlighted (and announced). */
export function IngredientList({
  ingredients,
  flagged,
}: {
  ingredients: string[];
  flagged: string[];
}) {
  if (!ingredients.length) {
    return <p className="text-sm text-gray-500">No ingredient list was found.</p>;
  }
  const flaggedLower = flagged.map((f) => f.toLowerCase());
  const isFlagged = (item: string) => {
    const lower = item.toLowerCase();
    return flaggedLower.some((f) => lower.includes(f) || f.includes(lower));
  };
  return (
    <ul className="flex flex-wrap gap-2" aria-label="Ingredients">
      {ingredients.map((item, i) => {
        const hit = isFlagged(item);
        return (
          <li
            key={`${item}-${i}`}
            className={
              hit
                ? "rounded-full bg-red-100 px-3 py-1 text-sm text-red-900"
                : "rounded-full bg-gray-100 px-3 py-1 text-sm text-gray-800"
            }
          >
            {item}
            {hit && <span className="sr-only"> (flagged)</span>}
          </li>
        );
      })}
    </ul>
  );
}
