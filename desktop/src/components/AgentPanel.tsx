import type { NovaEvent, NovaState } from "../lib/types";
import { AGENTS } from "../lib/ui";

const IDLE_STATES: NovaState[] = ["IDLE", "LISTENING", "COMPLETED", "ERROR"];

interface Props {
  state: NovaState;
  events: NovaEvent[];
  selected: string | null;
  onSelect: (agent: string | null) => void;
}

export function AgentPanel({ state, events, selected, onSelect }: Props) {
  const lastByAgent = new Map<string, NovaEvent>();
  for (const e of events) if (e.agent && !lastByAgent.has(e.agent)) lastByAgent.set(e.agent, e);
  // An agent is "working" while the latest task's events come from it and NOVA is busy.
  const activeAgent = !IDLE_STATES.includes(state) ? events.find((e) => e.agent)?.agent : undefined;

  return (
    <section className="panel flex min-h-0 flex-col">
      <h2 className="panel-title">Agents</h2>
      <ul className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto pr-1">
        {AGENTS.map((agent) => {
          const available = agent.phase === null;
          const working = available && activeAgent === agent.name;
          const last = lastByAgent.get(agent.name);
          const isSelected = selected === agent.name;
          return (
            <li key={agent.name}>
              <button
                type="button"
                disabled={!available}
                onClick={() => onSelect(isSelected ? null : agent.name)}
                aria-pressed={isSelected}
                title={available ? "Is agent ki activity dekhein" : undefined}
                className={`w-full rounded-lg border px-3 py-2 text-left transition ${
                  isSelected
                    ? "border-sky-400/70 bg-sky-500/15"
                    : available
                      ? "border-sky-500/30 bg-sky-500/5 hover:bg-sky-500/10"
                      : "cursor-default border-white/5 bg-white/[0.02] opacity-60"
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium text-slate-100">{agent.name}</span>
                  <span
                    className={`h-2 w-2 shrink-0 rounded-full ${
                      working ? "animate-pulse bg-amber-400" : available ? "bg-emerald-400" : "bg-slate-600"
                    }`}
                    title={working ? "Kaam kar raha hai" : available ? "Online" : "Offline"}
                  />
                </div>
                <p className="mt-0.5 text-xs text-slate-400">{agent.description}</p>
                <p className="mt-1 line-clamp-2 font-mono text-[10px] uppercase tracking-wider text-slate-500">
                  {available ? (working ? "Kaam kar raha hai..." : (last?.message ?? "Online")) : `Phase ${agent.phase} mein aayega`}
                </p>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
