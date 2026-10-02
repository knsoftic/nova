import type { AiStatus, HistoryOutcome, MemoryFact, NovaState, UserSettings, WorkflowStep } from "./types";

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
  { name: "Memory Agent", description: "Aap ki batai baatein, history aur workflows (sab isi PC par)", phase: null },
  { name: "Behavior Layer", description: "Andaz ka andaza (sirf andaza), jawab ka andaz, aadatein", phase: null },
  { name: "Admin", description: "Self-test, bugs aur approvals (LOGS.md)", phase: null },
];

/** The feature lifecycle from the spec (section 28), in order. "problem" sends a feature back to fixing. */
export const LIFECYCLE: { id: string; label: string }[] = [
  { id: "implemented", label: "Implemented" },
  { id: "automated_test", label: "Automated test" },
  { id: "verified", label: "Verified" },
  { id: "admin_tested", label: "Admin test" },
  { id: "approved", label: "Admin approved" },
];

/** How far along the lifecycle a stage is (problem = back at the start). */
export function lifecycleIndex(stage: string): number {
  if (stage === "problem") return 0;
  return Math.max(0, LIFECYCLE.findIndex((s) => s.id === stage));
}

export const CHECK_TONE: Record<string, string> = {
  pass: "text-emerald-300",
  info: "text-sky-300",
  warn: "text-amber-300",
  fail: "text-red-300",
};

export const BUG_WORDS: Record<string, string> = {
  open: "khula",
  fixed: "fix hua — retest baqi",
  closed: "band",
  reopened: "dobara khula",
};

/** "shayad jaldi mein" -> "Andaza: shayad jaldi mein" plus the reasons, for the badge under the avatar. */
export function estimateText(e: { label: string; reasons: string[] } | null): { text: string; title: string } | null {
  if (!e || !e.label) return null;
  return { text: `Andaza: ${e.label}`, title: `Sirf andaza, pakki baat nahi. Wajah: ${e.reasons.join(", ")}` };
}

export const OUTCOME_META: Record<HistoryOutcome, { label: string; tone: string }> = {
  done: { label: "ho gaya", tone: "text-emerald-300" },
  failed: { label: "nahi hua", tone: "text-red-300" },
  denied: { label: "ijazat nahi mili", tone: "text-orange-300" },
  answered: { label: "jawab", tone: "text-slate-400" },
  not_understood: { label: "samajh nahi aaya", tone: "text-slate-500" },
};

export const STEP_KIND: Record<WorkflowStep["kind"], { icon: string; label: string }> = {
  app: { icon: "▣", label: "app" },
  website: { icon: "◍", label: "website" },
  project: { icon: "</>", label: "project" },
  folder: { icon: "▤", label: "folder" },
  setting: { icon: "◐", label: "setting" },
};

export const SLOT_LABEL: Record<NonNullable<MemoryFact["slot"]>, string> = {
  name: "Naam",
  city: "Shehar",
  work: "Kaam",
  birthday: "Birthday",
};

export const RETENTION_OPTIONS: { value: UserSettings["history_days"]; label: string }[] = [
  { value: 30, label: "30 din" },
  { value: 90, label: "90 din (tajweez)" },
  { value: 365, label: "1 saal" },
  { value: 0, label: "Hamesha (jab tak aap na mitayein)" },
];

/** The command the "Chalao" button sends, so a workflow runs through the normal plan/permission/verify path. */
export function workflowCommand(name: string): string {
  return `${name} workflow chalao`;
}

/** "2026-10-02T14:05:00" -> "2 Oct" (dates of memories and history). */
export function shortDate(iso: string | null | undefined): string {
  const d = iso ? new Date(iso.length === 10 ? `${iso}T00:00:00` : iso) : null;
  if (!d || Number.isNaN(d.getTime())) return "";
  return `${d.getDate()} ${["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][d.getMonth()]}`;
}

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
