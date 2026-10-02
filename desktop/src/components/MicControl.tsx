import type { RefObject } from "react";
import type { MicStatus } from "../lib/useMicrophone";
import { Waveform } from "./Waveform";

export const MIC_LABEL: Record<MicStatus, { text: string; dot: string; hint: string }> = {
  off: { text: "Mic: Off", dot: "bg-slate-500", hint: "Click karke bolein — NOVA awaaz se command samjhega" },
  starting: { text: "Mic: ...", dot: "bg-amber-400 animate-pulse", hint: "Microphone shuru ho raha hai" },
  on: { text: "Mic: On", dot: "bg-emerald-400 animate-pulse", hint: "Sun raha hoon. Band karne ke liye click karein" },  denied: { text: "Mic: Blocked", dot: "bg-red-400", hint: "Microphone ki permission nahi mili (Windows privacy settings dekhein)" },
  unavailable: { text: "Mic: Nahi mila", dot: "bg-red-400", hint: "Koi microphone connect nahi hai" },
  error: { text: "Mic: Error", dot: "bg-red-400", hint: "Microphone shuru nahi ho saka" },
};

interface Props {
  status: MicStatus;
  /** Overrides the default text while listening (e.g. "Mic: On · Hey NOVA"). */
  label?: string;
  deviceLabel: string | null;
  analyserRef: RefObject<AnalyserNode | null>;
  onToggle: () => void;
  disabled: boolean;
}

export function MicControl({ status, label: labelOverride, deviceLabel, analyserRef, onToggle, disabled }: Props) {
  const label = MIC_LABEL[status];
  const on = status === "on";
  return (
    <div className="flex shrink-0 items-center gap-2">
      <button
        type="button"
        onClick={onToggle}
        disabled={disabled || status === "starting"}
        aria-pressed={on}
        title={on && deviceLabel ? `${label.hint}\n${deviceLabel}` : label.hint}
        className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-xs transition disabled:opacity-50 ${
          on ? "border-emerald-500/50 bg-emerald-500/10 text-emerald-200" : "border-white/10 text-slate-300 hover:bg-white/5"
        }`}
      >
        <span className={`h-2 w-2 rounded-full ${label.dot}`} />
        {labelOverride ?? label.text}
      </button>
      {on && <Waveform analyserRef={analyserRef} active={on} />}
    </div>
  );
}
