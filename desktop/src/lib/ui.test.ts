import { describe, expect, it } from "vitest";
import { matchesActivity } from "./activityFilter";
import { computeLevel, smoothLevel } from "./audio";
import { emptyHistory, navigateHistory, pushHistory } from "./commandHistory";
import type { AiStatus, EventType, NovaEvent } from "./types";
import {
  OUTCOME_META,
  RETENTION_OPTIONS,
  aiLabel,
  estimateText,
  LIFECYCLE,
  lifecycleIndex,
  stepSettled,
  listensAfterSetup,
  pairingTimeLeft,
  pcExamples,
  STEP_GUARD_MS,
  formatBytes,
  formatDuration,
  linkParts,
  messageBlocks,
  providerLabel,
  shortDate,
  showPhone,
  workflowCommand,
} from "./ui";

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

describe("showPhone", () => {
  it("formats Pakistani numbers and keeps others international", () => {
    expect(showPhone("923001234567")).toBe("+92 300 1234567");
    expect(showPhone("971501234567")).toBe("+971501234567");
    expect(showPhone(null)).toBe("");
  });
});

describe("memory helpers", () => {
  it("formats memory and history dates", () => {
    expect(shortDate("2026-10-02T14:05:00")).toBe("2 Oct");
    expect(shortDate("2026-03-05")).toBe("5 Mar");
    expect(shortDate(null)).toBe("");
    expect(shortDate("not a date")).toBe("");
  });

  it("runs a workflow through a normal command and offers every retention choice", () => {
    expect(workflowCommand("study")).toBe("study workflow chalao");
    expect(RETENTION_OPTIONS.map((o) => o.value)).toEqual([30, 90, 365, 0]);
    expect(Object.keys(OUTCOME_META).sort()).toEqual(["answered", "denied", "done", "failed", "not_understood"]);
  });
});

describe("behavior estimate badge", () => {
  it("is only shown for a real estimate and says it is an estimate", () => {
    expect(estimateText(null)).toBeNull();
    expect(estimateText({ label: "", reasons: [] })).toBeNull();
    const shown = estimateText({ label: "shayad jaldi mein", reasons: ["jaldi wale alfaaz", "aam se tez bole"] });
    expect(shown?.text).toBe("Andaza: shayad jaldi mein");
    expect(shown?.title).toContain("Sirf andaza");
    expect(shown?.title).toContain("aam se tez bole");
  });
});

describe("admin lifecycle", () => {
  it("orders the stages and sends problems back to the start", () => {
    expect(LIFECYCLE.map((s) => s.id)).toEqual(["implemented", "automated_test", "verified", "admin_tested", "approved"]);
    expect(lifecycleIndex("approved")).toBe(4);
    expect(lifecycleIndex("verified")).toBe(2);
    expect(lifecycleIndex("problem")).toBe(0);
    expect(lifecycleIndex("whatever")).toBe(0);
  });
});

describe("setup wizard", () => {
  it("keeps the mic listening when chosen, and always for a silent start", () => {
    expect(listensAfterSetup(true, true, "active")).toBe(true);
    expect(listensAfterSetup(false, true, "active")).toBe(false);
    expect(listensAfterSetup(false, true, "silent")).toBe(true); // in the tray NOVA is only reached by voice
    expect(listensAfterSetup(false, false, "silent")).toBe(false);
  });

  it("ignores the second click of a double-click right after a step change", () => {
    expect(stepSettled(1000, 1000 + 120)).toBe(false); // second click of a double-click
    expect(stepSettled(1000, 1000 + STEP_GUARD_MS)).toBe(true);
    expect(stepSettled(0, 5000)).toBe(true); // the first step: no change yet, the page has been open for a while
  });
});

describe("multi-PC", () => {
  it("counts the joining code down and never below zero", () => {
    expect(pairingTimeLeft(300, 1000, 1000)).toBe(300);
    expect(pairingTimeLeft(300, 1000, 61_500)).toBe(240);
    expect(pairingTimeLeft(10, 0, 60_000)).toBe(0);
  });

  it("gives example commands with the PC's name", () => {
    expect(pcExamples("Office PC")).toEqual(["Office PC par Chrome kholo", "Office PC ka haal batao", "mere PCs dikhao"]);
  });
});
