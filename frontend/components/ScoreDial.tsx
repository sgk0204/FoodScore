import type { Band } from "@/lib/api/schemas";
import { bandInfo } from "@/lib/bands";

/** Score out of 100 with the band shown as text too — colour is never the only signal (WCAG). */
export function ScoreDial({
  score,
  band,
  partial,
}: {
  score: number;
  band: Band;
  partial?: boolean;
}) {
  const info = bandInfo(band);
  const r = 52;
  const circumference = 2 * Math.PI * r;
  const offset = circumference * (1 - score / 100);
  return (
    <figure
      className="flex flex-col items-center"
      aria-label={`Score ${score} out of 100, ${info.label}`}
    >
      <svg viewBox="0 0 120 120" className="h-40 w-40" aria-hidden>
        <circle cx="60" cy="60" r={r} fill="none" stroke="#e5e7eb" strokeWidth="12" />
        <circle
          cx="60"
          cy="60"
          r={r}
          fill="none"
          stroke={info.hex}
          strokeWidth="12"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          transform="rotate(-90 60 60)"
        />
        <text x="60" y="60" textAnchor="middle" fontSize="32" fontWeight="700" fill="#111827">
          {score}
        </text>
        <text x="60" y="80" textAnchor="middle" fontSize="11" fill="#6b7280">
          / 100
        </text>
      </svg>
      <figcaption className={`mt-2 rounded-full px-4 py-1 text-sm font-semibold ${info.className}`}>
        {info.label}
        {partial ? " · Partial" : ""}
      </figcaption>
    </figure>
  );
}
