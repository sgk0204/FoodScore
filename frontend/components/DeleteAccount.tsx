"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/auth";

export function DeleteAccount() {
  const { user, deleteAccount } = useAuth();
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  if (!user) return <p className="text-sm text-gray-600">Sign in to delete your account.</p>;
  return (
    <Button
      variant="danger"
      disabled={busy}
      onClick={async () => {
        if (!confirm("Permanently delete your account and all scans? This cannot be undone."))
          return;
        setBusy(true);
        try {
          await deleteAccount();
          router.push("/");
        } finally {
          setBusy(false);
        }
      }}
    >
      Delete my account and data
    </Button>
  );
}
