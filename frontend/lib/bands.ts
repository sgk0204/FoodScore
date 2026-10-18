import type { Band } from "./api/schemas";

export const BANDS: {
  band: Band;
  label: string;
  min: number;
  max: number;
  className: string;
  hex: string;
}[] = [
  {
    band: "VERY_BAD",
    label: "Very Bad",
    min: 0,
    max: 20,
    className: "bg-band-very-bad text-white",
    hex: "#c62828",
  },
  {
    band: "BAD",
    label: "Bad",
    min: 21,
    max: 40,
    className: "bg-band-bad text-white",
    hex: "#ef6c00",
  },
  {
    band: "GOOD",
    label: "Good",
    min: 41,
    max: 60,
    className: "bg-band-good text-gray-900",
    hex: "#f2b300",
  },
  {
    band: "VERY_GOOD",
    label: "Very Good",
    min: 61,
    max: 80,
    className: "bg-band-very-good text-gray-900",
    hex: "#7cb342",
  },
  {
    band: "EXCELLENT",
    label: "Excellent",
    min: 81,
    max: 100,
    className: "bg-band-excellent text-white",
    hex: "#2e7d32",
  },
];

export function bandInfo(band: Band) {
  return BANDS.find((b) => b.band === band) ?? BANDS[0]!;
}

/** Display-only mirror of the backend's banding. The backend is the source of truth. */
export function bandFor(score: number): Band {
  return (BANDS.find((b) => score <= b.max) ?? BANDS[BANDS.length - 1]!).band;
}
