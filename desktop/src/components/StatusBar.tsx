import type { ConnectionStatus } from "../lib/types";

const CONNECTION: Record<ConnectionStatus, { label: string; dot: string }> = {
  connected: { label: "Backend connected", dot: "bg-emerald-400" },
  connecting: { label: "Connect ho raha hai...", dot: "bg-amber-400 animate-pulse" },
  disconnected: { label: "Backend offline — dobara koshish", dot: "bg-red-400 animate-pulse" },
};

export function StatusBar({
  name,
  connection,
  version,
}: {
  name: string;
  connection: ConnectionStatus;
  version: string | null;
}) {
  const c = CONNECTION[connection];
  return (
    <header className="flex items-center justify-between px-1">
      <div className="flex items-baseline gap-3">
        <span className="text-lg font-semibold tracking-[0.25em] text-slate-100">{name}</span>
        <span className="text-xs text-slate-500">Command Center · KN Softic</span>
      </div>
      <div className="flex items-center gap-4 font-mono text-xs text-slate-400">
        <span>AI: rule-based (local)</span>
        {version && <span>v{version}</span>}
        <span className="flex items-center gap-2" role="status">
          <span className={`h-2 w-2 rounded-full ${c.dot}`} />
          {c.label}
        </span>
      </div>
    </header>
  );
}
