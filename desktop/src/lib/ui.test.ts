import { describe, expect, it } from "vitest";
import { matchesActivity } from "./activityFilter";
import { computeLevel, smoothLevel } from "./audio";
import { emptyHistory, navigateHistory, pushHistory } from "./commandHistory";
import type { AiStatus, EventType, NovaEvent } from "./types";
import { aiLabel, formatBytes, formatDuration, linkParts, messageBlocks, providerLabel } from "./ui";

const ev = (type: EventType, agent: string | null = "Orchestrator"): NovaEvent => ({
  type,
  agent,
  timestamp: "2026-10-02T00:00:00Z",
  task_id: null,
  message: null,
  data: {},
});

describe("command history", () => {
  it("walks back and forward and restores the draft", () => {
    let h = pushHistory(pushHistory(emptyHistory, "chrome open karo"), "ram check karo");
    let r = navigateHistory(h, "up", "half typed");
    expect(r.value).toBe("ram check karo");
    r = navigateHistory(r.history, "up", r.value);
    expect(r.value).toBe("chrome open karo");
    r = navigateHistory(r.history, "up", r.value); // stays at oldest
    expect(r.value).toBe("chrome open karo");
    r = navigateHistory(r.history, "down", r.value);
    expect(r.value).toBe("ram check karo");
    r = navigateHistory(r.history, "down", r.value);
    expect(r.value).toBe("half typed");
    h = r.history;
    expect(h.index).toBeNull();
  });

  it("skips blanks and consecutive duplicates and caps length", () => {
    let h = pushHistory(emptyHistory, "  ");
    expect(h.items).toEqual([]);
    h = pushHistory(pushHistory(h, "a"), "a");
    expect(h.items).toEqual(["a"]);
    for (let i = 0; i < 10; i++) h = pushHistory(h, `c${i}`, 5);
    expect(h.items).toEqual(["c5", "c6", "c7", "c8", "c9"]);
  });

  it("does nothing with an empty history", () => {
    expect(navigateHistory(emptyHistory, "up", "x").value).toBe("x");
    expect(navigateHistory(emptyHistory, "down", "x").value).toBe("x");
  });
});

describe("activity filter", () => {
  it("filters by category", () => {
    expect(matchesActivity(ev("TASK_STARTED"), "tasks")).toBe(true);
    expect(matchesActivity(ev("TASK_STARTED"), "system")).toBe(false);
    expect(matchesActivity(ev("DISCOVERY_COMPLETED", "System Agent"), "system")).toBe(true);
    expect(matchesActivity(ev("TASK_FAILED"), "errors")).toBe(true);
    expect(matchesActivity(ev("ACTION_EXECUTED", "System Agent"), "agents")).toBe(true);
    expect(matchesActivity(ev("NOVA_RESPONSE"), "all")).toBe(true);
  });

  it("filters by agent", () => {
    expect(matchesActivity(ev("ACTION_EXECUTED", "System Agent"), "all", "System Agent")).toBe(true);
    expect(matchesActivity(ev("TASK_STARTED", "Orchestrator"), "all", "System Agent")).toBe(false);
  });
});

describe("audio level", () => {
  it("is 0 for silence and grows with amplitude, capped at 1", () => {
    expect(computeLevel(new Float32Array(512))).toBe(0);
    const quiet = computeLevel(Array.from({ length: 512 }, (_, i) => 0.02 * Math.sin(i / 5)));
    const loud = computeLevel(Array.from({ length: 512 }, (_, i) => 0.3 * Math.sin(i / 5)));
    expect(quiet).toBeGreaterThan(0);
    expect(loud).toBeGreaterThan(quiet);
    expect(computeLevel(new Float32Array(512).fill(1))).toBe(1);
    expect(computeLevel([])).toBe(0);
  });

  it("rises fast and falls slowly", () => {
    expect(smoothLevel(0, 1)).toBeCloseTo(0.6);
    expect(smoothLevel(1, 0)).toBeCloseTo(0.85);
  });
});

describe("AI labels", () => {
  const status = (over: Partial<AiStatus>): AiStatus => ({
    mode: "hybrid",
    model: "qwen3:4b",
    model_ready: true,
    llm_in_use: true,
    ollama: { reachable: true, version: "0.35.0", models: ["qwen3:4b"], error: null },
    last_provider: null,
    last_latency_ms: null,
    ...over,
  });

  it("describes the active brain honestly", () => {
    expect(aiLabel(null).text).toBe("AI: ...");
    expect(aiLabel(status({}))).toEqual({ text: "AI: qwen3:4b (hybrid)", ok: true });
    expect(aiLabel(status({ mode: "rules" })).text).toBe("AI: sirf rules");
    expect(aiLabel(status({ model_ready: false }))).toEqual({ text: "AI: rules (model offline)", ok: false });
  });

  it("shortens provider names", () => {
    expect(providerLabel("ollama:qwen3:4b")).toBe("qwen3:4b");
    expect(providerLabel("rule_based")).toBe("rules");
    expect(providerLabel(undefined)).toBeNull();
  });
});

describe("formatting", () => {
  it("formats bytes and durations", () => {
    expect(formatBytes(16 * 1024 ** 3)).toBe("16 GB");
    expect(formatBytes(1.5 * 1024 ** 3)).toBe("1.5 GB");
    expect(formatBytes(512 * 1024 ** 2)).toBe("512 MB");
    expect(formatBytes(null)).toBe("?");
    expect(formatDuration(3 * 3600 + 25 * 60)).toBe("3h 25m");
    expect(formatDuration(59 * 60)).toBe("59m");
  });
});

describe("linkParts", () => {
  it("turns https sources into links and leaves the sentence punctuation outside", () => {
    expect(linkParts("[1] Islamabad — https://en.wikipedia.org/wiki/Islamabad.\nDone")).toEqual([
      { text: "[1] Islamabad — " },
      { text: "https://en.wikipedia.org/wiki/Islamabad", href: "https://en.wikipedia.org/wiki/Islamabad" },
      { text: ".\nDone" },
    ]);
  });

  it("does not link plain http, file paths or javascript", () => {
    for (const t of ["http://example.com", "C:\\Users\\x\\report.md", "javascript:alert(1)"]) {
      expect(linkParts(t)).toEqual([{ text: t }]);
    }
  });
});

describe("messageBlocks", () => {
  it("separates code blocks from prose", () => {
    expect(messageBlocks('"app.py" (2 lines):\n```\nprint(1)\nprint(2)\n```\nAur kuch?')).toEqual([
      { code: false, text: '"app.py" (2 lines):' },
      { code: true, text: "print(1)\nprint(2)" },
      { code: false, text: "Aur kuch?" },
    ]);
  });

  it("leaves plain replies alone", () => {
    expect(messageBlocks("Folder bana diya.")).toEqual([{ code: false, text: "Folder bana diya." }]);
  });
});
