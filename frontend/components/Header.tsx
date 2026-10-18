"use client";

import { Leaf } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";

const LINKS = [
  { href: "/scan", label: "Scan" },
  { href: "/history", label: "History" },
  { href: "/methodology", label: "Scoring" },
];

export function Header() {
  const { user, ready, logout } = useAuth();
  const pathname = usePathname();
  return (
    <header className="border-b border-gray-200 bg-white">
      <nav className="mx-auto flex max-w-4xl items-center gap-2 px-4 py-3" aria-label="Main">
        <Link href="/" className="mr-auto flex items-center gap-2 font-bold text-brand">
          <Leaf aria-hidden className="h-5 w-5" /> FoodScore
        </Link>
        {LINKS.map((l) => (
          <Link
            key={l.href}
            href={l.href}
            aria-current={pathname.startsWith(l.href) ? "page" : undefined}
            className={cn(
              "whitespace-nowrap rounded-md px-2 py-1 text-sm text-gray-700 hover:bg-gray-100",
              pathname.startsWith(l.href) && "font-semibold text-brand",
            )}
          >
            {l.label}
          </Link>
        ))}
        {ready &&
          (user ? (
            <button
              onClick={() => void logout()}
              className="rounded-md px-2 py-1 text-sm text-gray-700 hover:bg-gray-100"
            >
              Sign out
            </button>
          ) : (
            <Link
              href="/login"
              className="rounded-md px-2 py-1 text-sm font-medium text-brand hover:bg-gray-100"
            >
              Sign in
            </Link>
          ))}
      </nav>
    </header>
  );
}
