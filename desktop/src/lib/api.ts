import type {
  ActivityRecord,
  AiStatus,
  Contact,
  FileRoot,
  HabitPatterns,
  HistoryPeriod,
  HistoryRecord,
  LiveStats,
  MemoryFact,
  PermissionRequest,
  PermissionRule,
  ShortTermMemory,
  SystemProfile,
  UserSettings,
  VoiceStatus,
  WebStatus,
  Workflow,
} from "./types";

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
  pendingPermissions: () => request<PermissionRequest[]>("/api/permissions/pending"),
  decidePermission: (id: string, approved: boolean, remember: boolean) =>
    request<{ ok: boolean }>(`/api/permissions/${encodeURIComponent(id)}/decision`, json("POST", { approved, remember })),
  permissionRules: () => request<PermissionRule[]>("/api/permissions/rules"),
  deletePermissionRule: (id: number) => request<{ ok: boolean }>(`/api/permissions/rules/${id}`, { method: "DELETE" }),
  voiceStatus: () => request<VoiceStatus>("/api/voice/status"),
  speak: (text: string) => request<{ speech_id: string }>("/api/voice/speak", json("POST", { text })),
  speechUrl: (id: string) => `${API_BASE}/api/voice/speech/${encodeURIComponent(id)}`,
  aiStatus: (refresh = false) => request<AiStatus>(`/api/ai/status${refresh ? "?refresh=true" : ""}`),
  webStatus: () => request<WebStatus>("/api/web/status"),
  fileRoots: () => request<FileRoot[]>("/api/files/roots"),
  contacts: () => request<Contact[]>("/api/contacts"),
  addContact: (contact: { name: string; phone?: string; email?: string }) =>
    request<Contact>("/api/contacts", json("POST", contact)),
  deleteContact: (id: number) => request<{ ok: boolean }>(`/api/contacts/${id}`, { method: "DELETE" }),
  memoryFacts: () => request<MemoryFact[]>("/api/memory/facts"),
  addMemoryFact: (text: string) => request<MemoryFact>("/api/memory/facts", json("POST", { text })),
  deleteMemoryFact: (id: number) => request<{ ok: boolean }>(`/api/memory/facts/${id}`, { method: "DELETE" }),
  deleteAllMemoryFacts: () => request<{ ok: boolean; removed: number }>("/api/memory/facts", { method: "DELETE" }),
  workflows: () => request<Workflow[]>("/api/workflows"),
  saveWorkflow: (name: string, steps: string) =>
    request<{ workflow: Workflow; problems: string[]; summary: string }>("/api/workflows", json("PUT", { name, steps })),
  deleteWorkflow: (id: number) => request<{ ok: boolean }>(`/api/workflows/${id}`, { method: "DELETE" }),
  history: (q = "", period: HistoryPeriod = "", limit = 50) =>
    request<HistoryRecord[]>(`/api/history?q=${encodeURIComponent(q)}&period=${period}&limit=${limit}`),
  deleteHistoryEntry: (taskId: string) =>
    request<{ ok: boolean }>(`/api/history/${encodeURIComponent(taskId)}`, { method: "DELETE" }),
  deleteAllHistory: () => request<{ ok: boolean; removed: number }>("/api/history", { method: "DELETE" }),
  habits: () => request<HabitPatterns>("/api/behavior/patterns"),
  forgetHabits: () => request<{ ok: boolean; removed: number }>("/api/behavior/patterns", { method: "DELETE" }),
  declineRoutine: (key: string) => request<{ ok: boolean }>("/api/behavior/routines/decline", json("POST", { key })),
  shortTerm: () => request<ShortTermMemory>("/api/memory/short-term"),
  clearShortTerm: () => request<{ ok: boolean }>("/api/memory/short-term", { method: "DELETE" }),
  /** Write-only: the backend encrypts the value and only ever returns a masked hint. */
  setSecret: (name: string, value: string) =>
    request<{ ok: boolean; masked: string }>(`/api/secrets/${encodeURIComponent(name)}`, json("PUT", { value })),
  deleteSecret: (name: string) => request<{ ok: boolean }>(`/api/secrets/${encodeURIComponent(name)}`, { method: "DELETE" }),
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
