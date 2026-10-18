"use client";

import { Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import { CaptureStep, STEPS, type Role } from "@/components/CaptureStep";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { ApiError, api } from "@/lib/api/client";
import { keys } from "@/lib/api/hooks";
import type { PreparedImage } from "@/lib/image/prepare";
import { newIdempotencyKey, thumbnailStore } from "@/lib/utils";
import { useQueryClient } from "@tanstack/react-query";

type Photos = Record<Role, PreparedImage | null>;

export default function ScanPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const [photos, setPhotos] = useState<Photos>({ front: null, nutrition: null, ingredients: null });
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<ApiError | Error | null>(null);
  // One key per photo set: a double-tap or a network retry re-sends the same key (edge case 35).
  const idemKey = useRef(newIdempotencyKey());

  const ready = STEPS.every((s) => photos[s.role]);
  const retake = error instanceof ApiError ? (error.problem.retake ?? []) : [];

  function setPhoto(role: Role, img: PreparedImage | null) {
    setPhotos((p) => ({ ...p, [role]: img }));
    idemKey.current = newIdempotencyKey(); // new photos → new request
    setError(null);
  }

  async function submit() {
    if (!ready || progress !== null) return;
    setError(null);
    setProgress(0);
    try {
      const { scan } = await api.uploadScan(
        {
          front: photos.front!.blob,
          nutrition: photos.nutrition!.blob,
          ingredients: photos.ingredients!.blob,
        },
        idemKey.current,
        setProgress,
      );
      thumbnailStore.set(scan.id, photos.front!.previewUrl);
      qc.setQueryData(keys.scan(scan.id), scan);
      router.push(`/result/${scan.id}`);
    } catch (e) {
      setError(e instanceof Error ? e : new Error("Upload failed"));
      setProgress(null);
    }
  }

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Scan a product</h1>
      <p className="text-gray-600">Three clear photos give the best result.</p>

      {STEPS.map((step, i) => (
        <CaptureStep
          key={step.role}
          index={i}
          {...step}
          value={photos[step.role]}
          onChange={(img) => setPhoto(step.role, img)}
          serverError={retake.includes(step.role) ? (error as ApiError).message : null}
        />
      ))}

      {error && !retake.length && (
        <Alert
          tone="error"
          title={error instanceof ApiError ? error.problem.title : "Something went wrong"}
        >
          {error.message}
        </Alert>
      )}

      <Button
        size="lg"
        className="w-full"
        disabled={!ready || progress !== null}
        onClick={() => void submit()}
      >
        {progress !== null ? (
          <>
            <Loader2 aria-hidden className="h-5 w-5 animate-spin" />
            {progress < 1 ? `Uploading ${Math.round(progress * 100)}%` : "Reading the label…"}
          </>
        ) : (
          "Get my score"
        )}
      </Button>
    </div>
  );
}
