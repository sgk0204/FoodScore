"use client";

import { Trash2 } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useDeleteScan, useHistory } from "@/lib/api/hooks";
import { bandInfo } from "@/lib/bands";
import { useAuth } from "@/lib/auth";

export default function HistoryPage() {
  const { user, ready } = useAuth();
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setDebounced(query.trim()), 300);
    return () => clearTimeout(t);
  }, [query]);
  const history = useHistory(debounced, Boolean(user));
  const remove = useDeleteScan();

  if (!ready) return null;
  if (!user) {
    return (
      <Alert title="Sign in to see your history">
        Guests can scan without an account, but history is only kept for signed-in users.{" "}
        <Link href="/login?next=/history" className="underline">
          Sign in
        </Link>
      </Alert>
    );
  }
  const items = history.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Your scans</h1>
      <label className="block">
        <span className="sr-only">Search by product or brand</span>
        <input
          type="search"
          placeholder="Search by product or brand"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="w-full rounded-lg border border-gray-300 px-3 py-2"
        />
      </label>
      {history.isLoading && <p className="text-gray-500">Loading…</p>}
      {!history.isLoading && items.length === 0 && (
        <p className="text-gray-600">
          No scans yet.{" "}
          <Link href="/scan" className="text-brand underline">
            Scan your first product
          </Link>
          .
        </p>
      )}
      <ul className="space-y-2">
        {items.map((s) => {
          const band = s.band ? bandInfo(s.band) : null;
          return (
            <li key={s.id}>
              <Card className="flex items-center gap-3 p-3 sm:p-4">
                <div
                  className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-lg text-lg font-bold ${
                    band?.className ?? "bg-gray-200 text-gray-600"
                  }`}
                  aria-label={s.score != null ? `Score ${s.score}, ${band?.label}` : s.status}
                >
                  {s.score ?? "–"}
                </div>
                <Link href={`/result/${s.id}`} className="min-w-0 flex-1">
                  <p className="truncate font-medium">{s.product.name ?? "Unnamed product"}</p>
                  <p className="truncate text-sm text-gray-600">
                    {[s.product.brand, new Date(s.created_at).toLocaleDateString()]
                      .filter(Boolean)
                      .join(" · ")}
                    {s.status !== "DONE" && ` · ${s.status.replace("_", " ").toLowerCase()}`}
                  </p>
                </Link>
                <Button
                  variant="ghost"
                  size="sm"
                  aria-label={`Delete scan of ${s.product.name ?? "product"}`}
                  onClick={() => {
                    if (confirm("Delete this scan permanently?")) remove.mutate(s.id);
                  }}
                >
                  <Trash2 aria-hidden className="h-4 w-4" />
                </Button>
              </Card>
            </li>
          );
        })}
      </ul>
      {history.hasNextPage && (
        <Button
          variant="secondary"
          onClick={() => void history.fetchNextPage()}
          disabled={history.isFetchingNextPage}
        >
          {history.isFetchingNextPage ? "Loading…" : "Load more"}
        </Button>
      )}
    </div>
  );
}
