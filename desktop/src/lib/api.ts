import type { LiveStats, SystemProfile } from "./types";

export const API_BASE = import.meta.env.VITE_NOVA_API_URL ?? "http://127.0.0.1:8765";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init);
  if (!res.ok) throw new Error(`${init?.method ?? "GET"} ${path} failed: ${res.status}`);
  return (await res.json()) as T;
}

export const api = {
  profile: () => request<{ scanning: boolean; profile: SystemProfile | null }>("/api/system/profile"),
  scan: () => request<{ scanned_at: string; apps: number; errors: string[] }>("/api/system/scan", { method: "POST" }),
  live: () => request<LiveStats>("/api/system/live"),
};
