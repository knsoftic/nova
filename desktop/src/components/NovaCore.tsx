import type { CSSProperties } from "react";
import type { NovaState } from "../lib/types";
import { STATE_META } from "../lib/ui";

const BUSY: NovaState[] = ["THINKING", "PLANNING", "WORKING", "VERIFYING", "LISTENING"];

export function NovaCore({ state, name }: { state: NovaState; name: string }) {
  const meta = STATE_META[state];
  const busy = BUSY.includes(state);
  const style = { "--nova-color": meta.color } as CSSProperties;

  return (
    <div className="flex flex-col items-center gap-6" style={style} data-state={state}>
      <div className={`nova-core ${busy ? "nova-core--busy" : ""}`} aria-hidden>
        <div className="nova-ring nova-ring--outer" />
        <div className="nova-ring nova-ring--middle" />
        <div className="nova-ring nova-ring--inner" />
        <div className="nova-orb">
          <span className="text-2xl font-semibold tracking-[0.3em] text-white/90 pl-[0.3em]">{name}</span>
        </div>
      </div>
      <div className="flex flex-col items-center gap-1" role="status" aria-live="polite">
        <span
          className="rounded-full border px-3 py-1 font-mono text-xs tracking-widest"
          style={{ borderColor: meta.color, color: meta.color }}
        >
          {state.replaceAll("_", " ")}
        </span>
        <span className="text-sm text-slate-300">{meta.label}</span>
      </div>
    </div>
  );
}
