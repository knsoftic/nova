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
  phase: string | null; // phase that delivers it; null = active now
}

export const AGENTS: AgentInfo[] = [
  { name: "Orchestrator", description: "Command samajhna aur route karna", phase: null },
  { name: "System Agent", description: "System maloomat, apps, windows, screen, volume/brightness/Wi-Fi", phase: null },
  { name: "Browser Agent", description: "Websites kholna, parhna, click/type aur downloads (ijazat se)", phase: null },
  { name: "Research Agent", description: "Web search (Brave/Wikipedia), jawab aur reports", phase: null },
  { name: "File Agent", description: "Files dhoondna, banana, move/copy, Recycle Bin, organize, undo", phase: null },
  { name: "Coding Agent", description: "VS Code, projects, tests, errors dhoondna aur theek karna", phase: null },
  { name: "Design Agent", description: "Tasveer resize/convert/watermark, posts aur banners", phase: null },
  { name: "Communication Agent", description: "WhatsApp aur email (har dafa ijazat se)", phase: null },
];

/** "923001234567" -> "+92 300 1234567" (other countries: "+<digits>"). */
export function showPhone(digits: string | null): string {
  if (!digits) return "";
  if (digits.startsWith("92") && digits.length === 12) return `+92 ${digits.slice(2, 5)} ${digits.slice(5)}`;
  return `+${digits}`;
}

/** Splits a reply into prose and ``` code blocks (file contents, command output). */
export function messageBlocks(text: string): { code: boolean; text: string }[] {
  const blocks: { code: boolean; text: string }[] = [];
  const parts = text.split(/```[a-z]*\n?/i);
  parts.forEach((part, i) => {
    const code = i % 2 === 1; // odd parts sit between an opening and a closing fence
    const value = code ? part.replace(/\n$/, "") : part;
    if (value.trim()) blocks.push({ code, text: code ? value : value.replace(/^\n+|\n+$/g, "") });
  });
  return blocks;
}

/** Splits text into plain parts and https links, so web sources can be opened from a reply. */
export function linkParts(text: string): { text: string; href?: string }[] {
  const parts: { text: string; href?: string }[] = [];
  let last = 0;
  for (const m of text.matchAll(/https:\/\/[^\s<>"'`]+/g)) {
    const url = m[0].replace(/[.,;:!?]+$/, ""); // trailing punctuation belongs to the sentence
    const start = m.index ?? 0;
    if (start > last) parts.push({ text: text.slice(last, start) });
    parts.push({ text: url, href: url });
    last = start + url.length;
  }
  if (last < text.length) parts.push({ text: text.slice(last) });
  return parts;
}

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
