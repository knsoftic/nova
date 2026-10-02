import type { EventType, NovaEvent } from "../lib/types";
import { formatTime } from "../lib/ui";

const TONE: Partial<Record<EventType, string>> = {
  TASK_FAILED: "text-red-400",
  TASK_COMPLETED: "text-emerald-400",
  PERMISSION_REQUIRED: "text-orange-400",
  VERIFICATION_PASSED: "text-emerald-400",
  NOVA_RESPONSE: "text-sky-300",
  SYSTEM_READY: "text-emerald-400",
};

export function ActivityPanel({ events }: { events: NovaEvent[] }) {
  return (
    <section className="panel flex min-h-0 flex-col">
      <h2 className="panel-title">Live Activity</h2>
      {events.length === 0 ? (
        <p className="text-sm text-slate-500">Abhi koi activity nahi.</p>
      ) : (
        <ol className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto pr-1">
          {events.map((e, i) => (
            <li key={`${e.timestamp}-${i}`} className="border-l-2 border-white/10 pl-3">
              <div className="flex items-center justify-between gap-2 font-mono text-[10px] text-slate-500">
                <span className={TONE[e.type] ?? "text-slate-400"}>{e.type}</span>
                <span>{formatTime(e.timestamp)}</span>
              </div>
              <p className="text-xs text-slate-300">
                {e.agent && <span className="text-slate-500">{e.agent} → </span>}
                {e.message ?? ""}
              </p>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
