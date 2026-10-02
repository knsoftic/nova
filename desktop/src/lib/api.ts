import type { ActivityRecord, AiStatus, LiveStats, SystemProfile, UserSettings } from "./types";

export const API_BASE = import.meta.env.VITE_NOVA_API_URL ?? "http://127.0.0.1:8765";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail: unknown,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init);
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new ApiError(`${init?.method ?? "GET"} ${path} failed: ${res.status}`, res.status, detail);
  }
  return (await res.json()) as T;
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  profile: () => request<{ scanning: boolean; profile: SystemProfile | null }>("/api/system/profile"),
  scan: () => request<{ scanned_at: string; apps: number; errors: string[] }>("/api/system/scan", { method: "POST" }),
  live: () => request<LiveStats>("/api/system/live"),
  settings: () => request<UserSettings>("/api/settings"),
  updateSettings: (patch: Partial<UserSettings>) => request<UserSettings>("/api/settings", json("PUT", patch)),
  activity: (limit = 200) => request<ActivityRecord[]>(`/api/activity?limit=${limit}`),
  aiStatus: (refresh = false) => request<AiStatus>(`/api/ai/status${refresh ? "?refresh=true" : ""}`),
};

/** Turns a FastAPI 422 body into {field: message} for form display. */
export function fieldErrors(err: unknown): Record<string, string> {
  if (!(err instanceof ApiError) || err.status !== 422) return {};
  const detail = (err.detail as { detail?: { loc?: unknown[]; msg?: string }[] } | null)?.detail ?? [];
  const out: Record<string, string> = {};
  for (const d of detail) {
    const field = String(d.loc?.[d.loc.length - 1] ?? "form");
    out[field] = (d.msg ?? "Ghalat value").replace(/^Value error, /, "");
  }
  return out;
}
