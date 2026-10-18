"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ApiError } from "@/lib/api/client";
import { useAuth } from "@/lib/auth";

export function AuthForm({ mode }: { mode: "login" | "register" }) {
  const auth = useAuth();
  const router = useRouter();
  const params = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const next = params.get("next");
  const safeNext = next && next.startsWith("/") && !next.startsWith("//") ? next : "/scan";

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await (mode === "login" ? auth.login(email, password) : auth.register(email, password));
      router.push(safeNext);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="mx-auto max-w-sm">
      <h1 className="mb-4 text-2xl font-bold">
        {mode === "login" ? "Sign in" : "Create an account"}
      </h1>
      <form onSubmit={(e) => void submit(e)} className="space-y-3">
        <label className="block text-sm">
          Email
          <input
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2"
          />
        </label>
        <label className="block text-sm">
          Password
          <input
            type="password"
            required
            minLength={mode === "register" ? 10 : 1}
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2"
          />
          {mode === "register" && (
            <span className="text-xs text-gray-500">
              At least 10 characters with a letter and a digit.
            </span>
          )}
        </label>
        {error && <Alert tone="error">{error}</Alert>}
        <Button type="submit" className="w-full" disabled={busy}>
          {busy ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}
        </Button>
      </form>
      <p className="mt-4 text-sm text-gray-600">
        {mode === "login" ? (
          <>
            New here?{" "}
            <Link href="/register" className="text-brand underline">
              Create an account
            </Link>
          </>
        ) : (
          <>
            Already have an account?{" "}
            <Link href="/login" className="text-brand underline">
              Sign in
            </Link>
          </>
        )}
      </p>
    </Card>
  );
}
