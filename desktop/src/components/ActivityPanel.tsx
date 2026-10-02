import { useState } from "react";
import { ACTIVITY_FILTERS, matchesActivity, type ActivityFilter } from "../lib/activityFilter";
import type { EventType, NovaEvent } from "../lib/types";
import { formatTime } from "../lib/ui";

const TONE: Partial<Record<EventType, string>> = {
  TASK_FAILED: "text-red-400",
  DISCOVERY_FAILED: "text-red-400",
  TASK_COMPLETED: "text-emerald-400",
  DISCOVERY_COMPLETED: "text-emerald-400",
  PERMISSION_REQUIRED: "text-orange-400",
  VERIFICATION_PASSED: "text-emerald-400",
  VERIFICATION_FAILED: "text-red-400",
  ACTION_EXECUTED: "text-amber-300",
  NOVA_RESPONSE: "text-sky-300",
  NOVA_LISTENING: "text-emerald-300",
  SYSTEM_READY: "text-emerald-400",
  SETTINGS_CHANGED: "text-violet-300",
  PLAN_CREATED: "text-indigo-300",
  AI_STATUS: "text-violet-300",
  AI_FALLBACK: "text-amber-300",
};

interface Props {
  events: NovaEvent[];
  agentFilter: string | null;
  onClearAgent: () => void;
  onClear: () => void;
}

export function ActivityPanel({ events, agentFilter, onClearAgent, onClear }: Props) {
  const [filter, setFilter] = useState<ActivityFilter>("all");
  const visible = events.filter((e) => matchesActivity(e, filter, agentFilter));

  return (
    <section className="panel flex min-h-0 flex-col">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="panel-title !mb-0">Live Activity</h2>
        <button
          type="button"
          onClick={onClear}
          disabled={events.length === 0}
          className="text-[10px] text-slate-500 hover:text-slate-200 disabled:opacity-40"
          title="Sirf yahan se hatata hai; Activity Log mein record rehta hai"
        >
          Saaf karein
        </button>
      </div>
      <div className="mb-2 flex flex-wrap gap-1" role="group" aria-label="Activity filter">
        {ACTIVITY_FILTERS.map((f) => (
          <button
            key={f.id}
            type="button"
            onClick={() => setFilter(f.id)}
            aria-pressed={filter === f.id}
            className={`rounded-full px-2 py-0.5 text-[10px] transition ${
              filter === f.id ? "bg-sky-500/20 text-sky-100" : "text-slate-400 hover:bg-white/5"
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>
      {agentFilter && (
        <div className="mb-2 flex items-center justify-between rounded-md bg-white/5 px-2 py-1 text-[11px] text-slate-300">
          <span>Agent: {agentFilter}</span>
          <button type="button" onClick={onClearAgent} className="text-slate-400 hover:text-slate-100" aria-label="Agent filter hatayein">
            ✕
          </button>
        </div>
      )}
      {visible.length === 0 ? (
        <p className="text-sm text-slate-500">Abhi koi activity nahi.</p>
      ) : (
        <ol className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto pr-1">
          {visible.map((e, i) => (
            <li key={`${e.timestamp}-${e.type}-${i}`} className="border-l-2 border-white/10 pl-3">
              <div className="flex items-center justify-between gap-2 font-mono text-[10px] text-slate-500">
                <span className={TONE[e.type] ?? "text-slate-400"}>{e.type}</span>
                <span>{formatTime(e.timestamp)}</span>
              </div>
              <p className="whitespace-pre-line text-xs text-slate-300">
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
