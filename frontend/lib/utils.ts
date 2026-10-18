import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/** Front-of-pack thumbnails live only in this tab's memory — never uploaded for display, never persisted. */
const thumbnails = new Map<string, string>();
export const thumbnailStore = {
  set: (scanId: string, url: string) => thumbnails.set(scanId, url),
  get: (scanId: string) => thumbnails.get(scanId),
};

export function newIdempotencyKey(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}
