import type { CSSProperties } from "react";
import type { NovaState } from "../lib/types";
import { STATE_META } from "../lib/ui";

const BUSY: NovaState[] = ["THINKING", "PLANNING", "WORKING", "VERIFYING"];

interface Props {
  state: NovaState;
  name: string;
  /** Live microphone level 0..1; drives the orb while LISTENING. */
  level?: number;
  preview?: boolean;
  /** NOVA's voice is playing. */
  speaking?: boolean;
}

export function NovaCore({ state, name, level = 0, preview = false, speaking = false }: Props) {
  const meta = speaking ? { label: "Bol raha hoon...", color: "#22d3ee" } : STATE_META[state];
  const style = { "--nova-color": meta.color, "--nova-level": level.toFixed(3) } as CSSProperties;

  return (
    <div className="flex flex-col items-center gap-5" style={style}>
      <div
        className={`nova-core ${BUSY.includes(state) ? "nova-core--busy" : ""}`}
        data-state={state}
        data-speaking={speaking || undefined}
        aria-hidden
      >
        <div className="nova-ring nova-ring--outer" />
        <div className="nova-ring nova-ring--middle" />
        <div className="nova-ring nova-ring--inner" />
        <div className="nova-ripple" />
        <div className="nova-sweep" />
        <div className="nova-orbit">
          <span />
          <span />
          <span />
        </div>
        <div className="nova-orb">
          <span className="nova-name">{name}</span>
          <span className="nova-glyph nova-glyph--done">✓</span>
          <span className="nova-glyph nova-glyph--error">!</span>
          <span className="nova-glyph nova-glyph--permission">?</span>
        </div>
      </div>
      <div className="flex flex-col items-center gap-1" role="status" aria-live="polite">
        <span
          className="rounded-full border px-3 py-1 font-mono text-xs tracking-widest"
          style={{ borderColor: meta.color, color: meta.color }}
        >
          {speaking ? "SPEAKING" : state.replaceAll("_", " ")}
          {preview && " · PREVIEW"}
        </span>
        <span className="text-sm text-slate-300">{meta.label}</span>
      </div>
    </div>
  );
}
