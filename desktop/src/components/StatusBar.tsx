import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { AiStatus, ConnectionStatus, LiveStats } from "../lib/types";
import { aiLabel } from "../lib/ui";
import type { MicStatus } from "../lib/useMicrophone";
import { MIC_LABEL } from "./MicControl";

const CONNECTION: Record<ConnectionStatus, { label: string; dot: string }> = {
  connected: { label: "Backend connected", dot: "bg-emerald-400" },
  connecting: { label: "Connect ho raha hai...", dot: "bg-amber-400 animate-pulse" },
  disconnected: { label: "Backend offline — dobara koshish", dot: "bg-red-400 animate-pulse" },
};

const LIVE_POLL_MS = 5000;

function useLiveStats(enabled: boolean) {
  const [stats, setStats] = useState<LiveStats | null>(null);
  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    const poll = () =>
      api
        .live()
        .then((s) => !cancelled && setStats(s))
        .catch(() => undefined);
    void poll();
    const id = window.setInterval(poll, LIVE_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [enabled]);
  return stats;
}

interface Props {
  name: string;
  connection: ConnectionStatus;
  version: string | null;
  micStatus: MicStatus;
  aiStatus: AiStatus | null;
  onOpenSettings: () => void;
}

export function StatusBar({ name, connection, version, micStatus, aiStatus, onOpenSettings }: Props) {
  const c = CONNECTION[connection];
  const mic = MIC_LABEL[micStatus];
  const live = useLiveStats(connection === "connected");
  const ai = aiLabel(aiStatus);

  return (
    <header className="flex items-center justify-between px-1">
      <div className="flex items-baseline gap-3">
        <span className="text-lg font-semibold tracking-[0.25em] text-slate-100">{name}</span>
        <span className="text-xs text-slate-500">Command Center · KN Softic</span>
      </div>
      <div className="flex items-center gap-4 font-mono text-xs text-slate-400">
        {live && (
          <span title="Live system usage">
            CPU {live.cpu_percent.toFixed(0)}% · RAM {live.ram_percent.toFixed(0)}%
          </span>
        )}
        <span className="flex items-center gap-2" title={mic.hint} role="status" aria-label={mic.text}>
          <span className={`h-2 w-2 rounded-full ${mic.dot}`} />
          {mic.text}
        </span>
        <span className={ai.ok ? "" : "text-amber-300"} title="Commands kaun samajh raha hai (local, PC se bahar kuch nahi jata)">
          {ai.text}
        </span>
        {version && <span>v{version}</span>}
        <span className="flex items-center gap-2" role="status">
          <span className={`h-2 w-2 rounded-full ${c.dot}`} />
          {c.label}
        </span>
        <button
          type="button"
          onClick={onOpenSettings}
          className="rounded-lg border border-white/10 px-2.5 py-1 text-slate-300 transition hover:bg-white/5"
          aria-label="Settings kholein"
        >
          ⚙ Settings
        </button>
      </div>
    </header>
  );
}
