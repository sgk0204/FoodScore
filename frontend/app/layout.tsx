import type { Metadata, Viewport } from "next";
import Link from "next/link";

import { Header } from "@/components/Header";
import { Providers } from "@/components/Providers";

import "./globals.css";

export const metadata: Metadata = {
  title: { default: "FoodScore — scan a food label, get a score", template: "%s · FoodScore" },
  description:
    "Photograph a packaged food label and get an explainable health score out of 100, with the reasons behind it.",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1, themeColor: "#1f5f3b" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="flex min-h-screen flex-col">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:rounded focus:bg-white focus:px-3 focus:py-2"
        >
          Skip to content
        </a>
        <Providers>
          <Header />
          <main id="main" className="mx-auto w-full max-w-4xl flex-1 px-4 py-6">
            {children}
          </main>
          <footer className="border-t border-gray-200 bg-white">
            <div className="mx-auto flex max-w-4xl flex-wrap gap-4 px-4 py-4 text-xs text-gray-500">
              <span>For general information only. Not medical or dietary advice.</span>
              <Link href="/methodology" className="underline">
                Methodology
              </Link>
              <Link href="/privacy" className="underline">
                Privacy
              </Link>
            </div>
          </footer>
        </Providers>
      </body>
    </html>
  );
}
