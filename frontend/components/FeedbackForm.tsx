"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { api } from "@/lib/api/client";

/** "Report a problem" (feature F11): stored for review, never changes scores directly. */
export function FeedbackForm({ scanId }: { scanId: string }) {
  const [open, setOpen] = useState(false);
  const [type, setType] = useState("wrong_value");
  const [comment, setComment] = useState("");
  const [state, setState] = useState<"idle" | "sending" | "sent" | "error">("idle");

  if (state === "sent")
    return <p className="text-sm text-green-700">Thanks — we&apos;ll review it.</p>;
  if (!open) {
    return (
      <Button variant="ghost" size="sm" onClick={() => setOpen(true)}>
        Report a problem
      </Button>
    );
  }
  return (
    <form
      className="space-y-2"
      onSubmit={async (e) => {
        e.preventDefault();
        setState("sending");
        try {
          await api.sendFeedback(scanId, { type, comment });
          setState("sent");
        } catch {
          setState("error");
        }
      }}
    >
      <label className="block text-sm">
        What&apos;s wrong?
        <select
          value={type}
          onChange={(e) => setType(e.target.value)}
          className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2"
        >
          <option value="wrong_value">A value was read wrongly</option>
          <option value="unfair_score">The score seems unfair</option>
          <option value="wrong_product">Wrong product</option>
          <option value="other">Something else</option>
        </select>
      </label>
      <label className="block text-sm">
        Details (optional)
        <textarea
          value={comment}
          maxLength={2000}
          onChange={(e) => setComment(e.target.value)}
          className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2"
          rows={3}
        />
      </label>
      {state === "error" && (
        <p className="text-sm text-red-700">Couldn&apos;t send. Please retry.</p>
      )}
      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={state === "sending"}>
          Send
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
