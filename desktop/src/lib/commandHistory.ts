/** Shell-style command history: Up/Down walks previous commands, keeping the unsent draft. */

export interface CommandHistory {
  items: string[]; // oldest first
  index: number | null; // position while browsing, null = editing the draft
  draft: string;
}

export const emptyHistory: CommandHistory = { items: [], index: null, draft: "" };

export function pushHistory(h: CommandHistory, command: string, max = 50): CommandHistory {
  const cmd = command.trim();
  if (!cmd) return { ...h, index: null, draft: "" };
  const items = h.items[h.items.length - 1] === cmd ? h.items : [...h.items, cmd].slice(-max);
  return { items, index: null, draft: "" };
}

export function navigateHistory(
  h: CommandHistory,
  direction: "up" | "down",
  current: string,
): { history: CommandHistory; value: string } {
  if (h.items.length === 0) return { history: h, value: current };

  if (direction === "up") {
    if (h.index === null) {
      const index = h.items.length - 1;
      return { history: { ...h, index, draft: current }, value: h.items[index] };
    }
    const index = Math.max(0, h.index - 1);
    return { history: { ...h, index }, value: h.items[index] };
  }

  if (h.index === null) return { history: h, value: current };
  if (h.index >= h.items.length - 1) return { history: { ...h, index: null }, value: h.draft };
  const index = h.index + 1;
  return { history: { ...h, index }, value: h.items[index] };
}
