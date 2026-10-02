import type { NovaState } from "./types";

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
  { name: "System Agent", description: "System maloomat aur Windows actions", phase: 8 },
  { name: "Browser Agent", description: "Browser, search, websites", phase: 8 },
  { name: "File Agent", description: "Files aur folders", phase: 8 },
  { name: "Coding Agent", description: "VS Code, projects, errors", phase: 8 },
  { name: "Research Agent", description: "Web research aur reports", phase: 8 },
  { name: "Design Agent", description: "Design tools", phase: 8 },
  { name: "Communication Agent", description: "Messages (permission ke sath)", phase: 8 },
];

export function formatTime(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}
