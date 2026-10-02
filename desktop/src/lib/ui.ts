import type { AiStatus, NovaState } from "./types";

export const STATE_META: Record<NovaState, { label: string; color: string }> = {
  IDLE: { label: "Tayyar hoon", color: "#38bdf8" },
  LISTENING: { label: "Sun raha hoon", color: "#34d399" },
  THINKING: { label: "Soch raha hoon", color: "#a78bfa" },
  PLANNING: { label: "Plan bana raha hoon", color: "#818cf8" },
  WORKING: { label: "Kaam kar raha hoon", color: "#fbbf24" },
  WAITING_FOR_PERMISSION: { label: "Permission ka intezar", color: "#fb923c" },
  VERIFYING: { label: "Verify kar raha hoon", color: "#60a5fa" },
  COMPLETED: { label: "Kaam mukammal", color: "#10b981" },
  ERROR: { label: "Masla aa gaya", color: "#f87171" },
};

export interface AgentInfo {
  name: string;
  description: string;
  phase: number | null; // phase that delivers it; null = active now
}

export const AGENTS: AgentInfo[] = [
  { name: "Orchestrator", description: "Command samajhna aur route karna", phase: null },
  { name: "System Agent", description: "System maloomat (read-only). Windows actions Phase 8 mein", phase: null },
  { name: "Browser Agent", description: "Browser, search, websites", phase: 8 },
  { name: "File Agent", description: "Files aur folders", phase: 8 },
  { name: "Coding Agent", description: "VS Code, projects, errors", phase: 8 },
  { name: "Research Agent", description: "Web research aur reports", phase: 8 },
  { name: "Design Agent", description: "Design tools", phase: 8 },
  { name: "Communication Agent", description: "Messages (permission ke sath)", phase: 8 },
];

/** Short label for who is understanding commands right now. */
export function aiLabel(status: AiStatus | null): { text: string; ok: boolean } {
  if (!status) return { text: "AI: ...", ok: true };
  if (status.mode === "rules") return { text: "AI: sirf rules", ok: true };
  if (status.model_ready) return { text: `AI: ${status.model} (${status.mode})`, ok: true };
  return { text: "AI: rules (model offline)", ok: false };
}

/** "ollama:qwen3:4b" -> "qwen3:4b", "rule_based" -> "rules". */
export function providerLabel(provider: string | undefined): string | null {
  if (!provider) return null;
  if (provider === "rule_based") return "rules";
  return provider.replace(/^ollama:/, "");
}

export function formatBytes(n: number | null | undefined): string {
  if (!n) return "?";
  const gb = n / 1024 ** 3;
  if (gb >= 1) return gb < 10 ? `${gb.toFixed(1)} GB` : `${Math.round(gb)} GB`;
  return `${Math.round(n / 1024 ** 2)} MB`;
}

export function formatDuration(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

export function formatTime(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}
