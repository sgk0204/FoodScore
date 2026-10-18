import { BANDS } from "@/lib/bands";
import { cn } from "@/lib/utils";

export function BandScale({ highlight }: { highlight?: string | null }) {
  return (
    <div
      aria-label="Rating bands"
      className="grid grid-cols-5 overflow-hidden rounded-lg text-center text-xs sm:text-sm"
    >
      {BANDS.map((b) => (
        <div
          key={b.band}
          className={cn(
            "px-1 py-2",
            b.className,
            highlight && highlight !== b.band && "opacity-40",
            highlight === b.band && "ring-2 ring-inset ring-black/40",
          )}
        >
          <div className="font-semibold">{b.label}</div>
          <div>
            {b.min}–{b.max}
          </div>
        </div>
      ))}
    </div>
  );
}
