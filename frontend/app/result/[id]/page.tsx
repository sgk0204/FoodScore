"use client";

import { Loader2, Pencil } from "lucide-react";
import Link from "next/link";
import { use, useState } from "react";

import { BandScale } from "@/components/BandScale";
import { FeedbackForm } from "@/components/FeedbackForm";
import { IngredientList } from "@/components/IngredientList";
import { NutritionTable } from "@/components/NutritionTable";
import { PenaltyList } from "@/components/PenaltyList";
import { ReviewForm } from "@/components/ReviewForm";
import { ScoreDial } from "@/components/ScoreDial";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardTitle } from "@/components/ui/card";
import { useScan } from "@/lib/api/hooks";
import type { Scan } from "@/lib/api/schemas";
import { thumbnailStore } from "@/lib/utils";

const RETAKE_LABEL: Record<string, string> = {
  front: "front of the pack",
  nutrition: "nutrition table",
  ingredients: "ingredients list",
};

export default function ResultPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data: scan, error, isLoading } = useScan(id);

  if (isLoading) return <Waiting status="QUEUED" />;
  if (error || !scan) {
    return (
      <Alert tone="error" title="Couldn't load this scan">
        It may have been deleted, or it belongs to another account.{" "}
        <Link href="/scan" className="underline">
          Start a new scan
        </Link>
      </Alert>
    );
  }
  if (scan.status === "QUEUED" || scan.status === "PROCESSING")
    return <Waiting status={scan.status} />;
  if (scan.status === "FAILED" || scan.status === "EXPIRED") return <Failed scan={scan} />;
  if (scan.status === "NEEDS_REVIEW") {
    return (
      <div className="space-y-4">
        <ProductHeader scan={scan} />
        <Card>
          <CardTitle>Check the values we read</CardTitle>
          <ReviewForm scan={scan} />
        </Card>
      </div>
    );
  }
  return <Result scan={scan} />;
}

function Waiting({ status }: { status: string }) {
  return (
    <div
      className="flex flex-col items-center gap-3 py-16 text-center"
      role="status"
      aria-live="polite"
    >
      <Loader2 aria-hidden className="h-10 w-10 animate-spin text-brand" />
      <p className="text-lg font-medium">
        {status === "QUEUED" ? "In the queue…" : "Reading the label…"}
      </p>
      <p className="text-sm text-gray-600">
        This usually takes 5–15 seconds. You can leave — it will appear in your history.
      </p>
    </div>
  );
}

function Failed({ scan }: { scan: Scan }) {
  const retake = (scan.error?.retake as string[] | undefined) ?? [];
  return (
    <div className="space-y-4">
      <Alert
        tone="error"
        title={
          scan.error?.title ?? (scan.status === "EXPIRED" ? "This review expired" : "Scan failed")
        }
      >
        <p>{scan.error?.detail ?? "Please try again."}</p>
        {retake.length > 0 && (
          <p className="mt-1">
            Please retake the <strong>{retake.map((r) => RETAKE_LABEL[r] ?? r).join(", ")}</strong>{" "}
            photo.
          </p>
        )}
      </Alert>
      <Link
        href="/scan"
        className="inline-flex h-10 items-center rounded-lg bg-brand px-4 font-medium text-white"
      >
        Scan again
      </Link>
    </div>
  );
}

function ProductHeader({ scan }: { scan: Scan }) {
  const thumb = thumbnailStore.get(scan.id);
  return (
    <div className="flex items-center gap-4">
      {thumb && (
        // eslint-disable-next-line @next/next/no-img-element -- in-memory blob preview, never uploaded for display
        <img src={thumb} alt="" className="h-16 w-16 rounded-lg object-cover" />
      )}
      <div className="min-w-0">
        {/* Extracted text is rendered as text only: React escapes it (edge case 47). */}
        <h1 className="truncate text-2xl font-bold">{scan.product.name ?? "Unnamed product"}</h1>
        {scan.product.brand && <p className="text-gray-600">{scan.product.brand}</p>}
      </div>
    </div>
  );
}

function Result({ scan }: { scan: Scan }) {
  const [editing, setEditing] = useState(false);
  const confidencePct = scan.confidence != null ? Math.round(scan.confidence * 100) : null;
  return (
    <div className="space-y-4">
      <ProductHeader scan={scan} />

      <Card className="flex flex-col items-center gap-4 sm:flex-row sm:items-center">
        {scan.score != null && scan.band && (
          <ScoreDial score={scan.score} band={scan.band} partial={scan.is_partial} />
        )}
        <div className="flex-1 space-y-2 text-center sm:text-left">
          <p className="text-lg font-medium">{scan.verdict}</p>
          <p className="text-sm text-gray-600">
            {scan.from_cache && "Instant result from a previous scan of this product. "}
            {scan.user_corrected && "Includes your corrections. "}
            {confidencePct != null &&
              !scan.user_corrected &&
              `Read with ${confidencePct}% confidence.`}
          </p>
          {scan.is_partial && (
            <Alert tone="warning" title="Partial score">
              Some nutrition values were missing, so the score is capped at 60.
            </Alert>
          )}
          <Button variant="secondary" size="sm" onClick={() => setEditing((e) => !e)}>
            <Pencil aria-hidden className="h-4 w-4" /> {editing ? "Close editor" : "Edit values"}
          </Button>
        </div>
      </Card>

      {editing && (
        <Card>
          <CardTitle>Edit values</CardTitle>
          <ReviewForm scan={scan} onDone={() => setEditing(false)} />
        </Card>
      )}

      <BandScale highlight={scan.band} />

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardTitle>What lowered the score</CardTitle>
          <PenaltyList items={scan.penalties} kind="penalty" />
          {scan.caps_applied.map((c) => (
            <p key={c.rule} className="mt-3 text-sm text-red-800">
              Capped at {c.cap}: {c.reason}
            </p>
          ))}
        </Card>
        <Card>
          <CardTitle>What helped</CardTitle>
          <PenaltyList items={scan.positives} kind="positive" />
        </Card>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardTitle>Nutrition</CardTitle>
          {scan.nutrition ? (
            <NutritionTable
              nutrition={scan.nutrition}
              isBeverage={scan.is_beverage}
              fieldConfidence={scan.field_confidence}
            />
          ) : (
            <p className="text-sm text-gray-500">No nutrition table was found.</p>
          )}
        </Card>
        <Card>
          <CardTitle>Ingredients</CardTitle>
          <IngredientList ingredients={scan.ingredients} flagged={scan.flagged_ingredients} />
          {scan.unrated_additives.length > 0 && (
            <p className="mt-3 text-xs text-gray-500">
              Not yet rated: {scan.unrated_additives.join(", ")}
            </p>
          )}
        </Card>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <FeedbackForm scanId={scan.id} />
        <Link href="/scan" className="text-sm font-medium text-brand underline">
          Scan another product
        </Link>
      </div>
      <p className="text-xs text-gray-500">{scan.disclaimer}</p>
    </div>
  );
}
