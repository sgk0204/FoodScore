"use client";

import { Camera, ImageUp, Loader2 } from "lucide-react";
import { useId, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { ImagePrepError, prepareImage, type PreparedImage } from "@/lib/image/prepare";
import { cn } from "@/lib/utils";

export type Role = "front" | "nutrition" | "ingredients";

export const STEPS: { role: Role; title: string; tip: string }[] = [
  {
    role: "front",
    title: "Front of the pack",
    tip: "Show the product name and the barcode if it's on the front.",
  },
  {
    role: "nutrition",
    title: "Nutrition facts table",
    tip: "Fill the frame with the table. Tilt the pack to avoid glare; no flash.",
  },
  {
    role: "ingredients",
    title: "Ingredients list",
    tip: "Get the whole list in focus, including any small print.",
  },
];

/** One guided photo slot: camera/upload, preview, quality warning and retake (feature F1). */
export function CaptureStep({
  index,
  role,
  title,
  tip,
  value,
  onChange,
  serverError,
}: {
  index: number;
  role: Role;
  title: string;
  tip: string;
  value: PreparedImage | null;
  onChange: (img: PreparedImage | null) => void;
  serverError?: string | null;
}) {
  const inputId = useId();
  // Two inputs: `capture` forces the camera on phones, so the gallery needs its own input.
  const cameraRef = useRef<HTMLInputElement>(null);
  const galleryRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handle(file: File | undefined) {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      onChange(await prepareImage(file));
    } catch (e) {
      setError(
        e instanceof ImagePrepError ? e.message : "Couldn't read that photo. Please try another.",
      );
      onChange(null);
    } finally {
      setBusy(false);
      for (const ref of [cameraRef, galleryRef]) if (ref.current) ref.current.value = "";
    }
  }

  const warning =
    value && !value.quality.ok
      ? value.quality.reason === "dark"
        ? "This photo looks dark. Move to better light and retake if the text is hard to read."
        : "This photo looks blurry. Hold steady and retake if the text isn't sharp."
      : null;

  return (
    <section
      aria-labelledby={`${inputId}-title`}
      className={cn(
        "rounded-xl border-2 border-dashed p-4",
        value ? "border-brand bg-brand-light/50" : "border-gray-300 bg-white",
        (error || serverError) && "border-red-400",
      )}
      data-testid={`capture-${role}`}
    >
      <div className="flex items-start gap-3">
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-brand text-sm font-bold text-white">
          {index + 1}
        </span>
        <div className="min-w-0 flex-1">
          <h3 id={`${inputId}-title`} className="font-semibold text-gray-900">
            {title}
          </h3>
          <p className="text-sm text-gray-600">{tip}</p>
        </div>
      </div>

      {value && (
        <div className="mt-3">
          {/* eslint-disable-next-line @next/next/no-img-element -- local blob preview */}
          <img
            src={value.previewUrl}
            alt={`${title} preview`}
            className="h-24 w-24 rounded-lg object-cover"
          />
        </div>
      )}

      <div className="mt-3 grid grid-cols-2 gap-2">
        <Button
          type="button"
          variant={value ? "secondary" : "primary"}
          onClick={() => cameraRef.current?.click()}
          disabled={busy}
          aria-describedby={`${inputId}-title`}
        >
          {busy ? (
            <Loader2 aria-hidden className="h-4 w-4 animate-spin" />
          ) : (
            <Camera aria-hidden className="h-4 w-4" />
          )}
          {busy ? "Preparing…" : value ? "Retake" : "Take photo"}
        </Button>
        <Button
          type="button"
          variant="secondary"
          onClick={() => galleryRef.current?.click()}
          disabled={busy}
          aria-describedby={`${inputId}-title`}
        >
          <ImageUp aria-hidden className="h-4 w-4" />
          {value ? "Choose another" : "Upload photo"}
        </Button>
      </div>

      <input
        ref={cameraRef}
        type="file"
        accept="image/*,.heic,.heif"
        capture="environment"
        className="sr-only"
        tabIndex={-1}
        aria-label={`Take ${title} photo with camera`}
        data-testid={`camera-${role}`}
        onChange={(e) => void handle(e.target.files?.[0])}
      />
      <input
        ref={galleryRef}
        id={inputId}
        type="file"
        accept="image/*,.heic,.heif"
        className="sr-only"
        tabIndex={-1}
        aria-label={`Upload ${title} photo`}
        data-testid={`input-${role}`}
        onChange={(e) => void handle(e.target.files?.[0])}
      />

      {(error || serverError) && (
        <p role="alert" className="mt-2 text-sm text-red-700">
          {error ?? serverError}
        </p>
      )}
      {warning && !error && <p className="mt-2 text-sm text-amber-800">{warning}</p>}
    </section>
  );
}
