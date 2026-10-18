/**
 * Typed API client.
 *
 * Auth (guide §4.5): the access token lives in memory only — never localStorage. On a 401 the
 * client calls /auth/refresh once (the refresh token is an httpOnly cookie the JS cannot read)
 * and retries the request.
 */
import type { z } from "zod";

import { Problem, Scan, ScanPage, Methodology, Token, User } from "./schemas";
import type { NutrientKey } from "./schemas";

const BASE = "/api/v1";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly problem: Problem,
  ) {
    super(problem.detail ?? problem.title);
    this.name = "ApiError";
  }

  get slug(): string {
    return this.problem.type.split("/").pop() ?? "error";
  }
}

let accessToken: string | null = null;
let refreshing: Promise<boolean> | null = null;
const listeners = new Set<(token: string | null) => void>();

export function setAccessToken(token: string | null): void {
  accessToken = token;
  listeners.forEach((fn) => fn(token));
}

export function onAccessTokenChange(fn: (token: string | null) => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function hasAccessToken(): boolean {
  return accessToken !== null;
}

/** Single-flight refresh: concurrent 401s share one /auth/refresh call. */
export async function refreshAccessToken(): Promise<boolean> {
  refreshing ??= (async () => {
    try {
      const res = await fetch(`${BASE}/auth/refresh`, { method: "POST", credentials: "include" });
      if (!res.ok) {
        setAccessToken(null);
        return false;
      }
      setAccessToken(Token.parse(await res.json()).access_token);
      return true;
    } catch {
      return false;
    } finally {
      setTimeout(() => (refreshing = null), 0);
    }
  })();
  return refreshing;
}

async function toError(res: Response): Promise<ApiError> {
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    /* non-JSON error body */
  }
  const parsed = Problem.safeParse(body);
  return new ApiError(
    res.status,
    parsed.success
      ? parsed.data
      : { type: "about:blank", title: res.statusText || "Request failed", status: res.status },
  );
}

type RequestOptions = Omit<RequestInit, "body"> & { body?: unknown; retry?: boolean };

async function request(path: string, opts: RequestOptions = {}): Promise<Response> {
  const { body, retry = true, headers, ...rest } = opts;
  const h = new Headers(headers);
  if (accessToken) h.set("Authorization", `Bearer ${accessToken}`);
  let payload: BodyInit | undefined;
  if (body instanceof FormData) payload = body;
  else if (body !== undefined) {
    h.set("Content-Type", "application/json");
    payload = JSON.stringify(body);
  }
  const res = await fetch(`${BASE}${path}`, {
    ...rest,
    headers: h,
    body: payload,
    credentials: "include",
  });
  if (res.status === 401 && retry && accessToken && !path.startsWith("/auth/")) {
    if (await refreshAccessToken()) return request(path, { ...opts, retry: false });
  }
  if (!res.ok && res.status !== 304) throw await toError(res);
  return res;
}

async function json<T extends z.ZodTypeAny>(
  schema: T,
  path: string,
  opts?: RequestOptions,
): Promise<z.infer<T>> {
  const res = await request(path, opts);
  return schema.parse(await res.json());
}

export type NutritionPatch = Partial<Record<NutrientKey, number | null>> & {
  ingredients?: string[];
  is_beverage?: boolean;
};

export type UploadResult = { scan: Scan; cached: boolean };

export const api = {
  register: async (email: string, password: string) => {
    const t = await json(Token, "/auth/register", { method: "POST", body: { email, password } });
    setAccessToken(t.access_token);
  },
  login: async (email: string, password: string) => {
    const t = await json(Token, "/auth/login", { method: "POST", body: { email, password } });
    setAccessToken(t.access_token);
  },
  logout: async () => {
    try {
      await request("/auth/logout", { method: "POST" });
    } finally {
      setAccessToken(null);
    }
  },
  me: () => json(User, "/auth/me"),
  deleteAccount: async () => {
    await request("/me", { method: "DELETE" });
    setAccessToken(null);
  },
  getScan: (id: string) => json(Scan, `/scans/${id}`),
  listScans: (params: { q?: string; cursor?: string | null }) => {
    const qs = new URLSearchParams();
    if (params.q) qs.set("q", params.q);
    if (params.cursor) qs.set("cursor", params.cursor);
    return json(ScanPage, `/scans?${qs.toString()}`);
  },
  correctNutrition: (id: string, patch: NutritionPatch) =>
    json(Scan, `/scans/${id}/nutrition`, { method: "PATCH", body: patch }),
  confirmScan: (id: string) => json(Scan, `/scans/${id}/confirm`, { method: "POST" }),
  deleteScan: async (id: string) => {
    await request(`/scans/${id}`, { method: "DELETE" });
  },
  sendFeedback: (id: string, body: { type: string; field?: string; comment: string }) =>
    request(`/scans/${id}/feedback`, { method: "POST", body }),
  methodology: () => json(Methodology, "/methodology"),

  /**
   * Multipart upload with progress. Uses XHR because fetch has no upload-progress events.
   * The Idempotency-Key makes double-taps and retries safe (edge case 35).
   */
  uploadScan(
    files: { front: Blob; nutrition: Blob; ingredients: Blob },
    idempotencyKey: string,
    onProgress?: (fraction: number) => void,
  ): Promise<UploadResult> {
    const send = (): Promise<{ status: number; body: unknown }> =>
      new Promise((resolve, reject) => {
        const form = new FormData();
        form.append("front", files.front, "front.jpg");
        form.append("nutrition", files.nutrition, "nutrition.jpg");
        form.append("ingredients", files.ingredients, "ingredients.jpg");
        const xhr = new XMLHttpRequest();
        xhr.open("POST", `${BASE}/scans`);
        xhr.withCredentials = true;
        xhr.setRequestHeader("Idempotency-Key", idempotencyKey);
        if (accessToken) xhr.setRequestHeader("Authorization", `Bearer ${accessToken}`);
        xhr.upload.onprogress = (e) => e.lengthComputable && onProgress?.(e.loaded / e.total);
        xhr.onerror = () => reject(new Error("Network error — check your connection and retry."));
        xhr.onload = () => {
          let body: unknown = null;
          try {
            body = JSON.parse(xhr.responseText);
          } catch {
            /* ignore */
          }
          resolve({ status: xhr.status, body });
        };
        xhr.send(form);
      });

    return (async () => {
      let res = await send();
      if (res.status === 401 && accessToken && (await refreshAccessToken())) res = await send();
      if (res.status === 200 || res.status === 202) {
        return { scan: Scan.parse(res.body), cached: res.status === 200 };
      }
      const parsed = Problem.safeParse(res.body);
      throw new ApiError(
        res.status,
        parsed.success
          ? parsed.data
          : { type: "about:blank", title: "Upload failed", status: res.status },
      );
    })();
  },
};
