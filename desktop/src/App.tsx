import { useState } from "react";
import { ActivityPanel } from "./components/ActivityPanel";
import { AgentPanel } from "./components/AgentPanel";
import { CommandBar } from "./components/CommandBar";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { Conversation } from "./components/Conversation";
import { NovaCore } from "./components/NovaCore";
import { StatusBar } from "./components/StatusBar";
import { SystemProfileView } from "./components/SystemProfileView";
import { useNova } from "./lib/useNova";

type CenterView = "conversation" | "system";

const VIEWS: { id: CenterView; label: string }[] = [
  { id: "conversation", label: "Conversation" },
  { id: "system", label: "System Profile" },
];

export default function App() {
  const { connection, state, assistantName, version, events, messages, sendCommand, scanning, profileRevision } =
    useNova();
  const [view, setView] = useState<CenterView>("conversation");

  const send = (text: string) => {
    const sent = sendCommand(text);
    if (sent) setView("conversation");
    return sent;
  };

  return (
    <div className="flex h-screen flex-col gap-4 p-4">
      <StatusBar name={assistantName} connection={connection} version={version} />
      <main className="grid min-h-0 flex-1 grid-cols-[260px_1fr_320px] gap-4">
        <AgentPanel state={state} events={events} />
        <section className="panel flex min-h-0 flex-col items-center gap-4 overflow-hidden">
          <nav className="flex gap-1 self-stretch rounded-lg bg-black/20 p-1" aria-label="Center view">
            {VIEWS.map((v) => (
              <button
                key={v.id}
                type="button"
                onClick={() => setView(v.id)}
                aria-pressed={view === v.id}
                className={`flex-1 rounded-md px-3 py-1.5 text-xs transition ${
                  view === v.id ? "bg-sky-500/20 text-sky-100" : "text-slate-400 hover:text-slate-200"
                }`}
              >
                {v.label}
                {v.id === "system" && scanning && <span className="ml-2 animate-pulse text-amber-300">●</span>}
              </button>
            ))}
          </nav>
          {view === "conversation" ? (
            <>
              <NovaCore state={state} name={assistantName} />
              <div className="min-h-0 w-full max-w-2xl flex-1 overflow-y-auto px-2 pb-2">
                <ErrorBoundary label="Conversation">
                  <Conversation messages={messages} assistantName={assistantName} />
                </ErrorBoundary>
              </div>
            </>
          ) : (
            <div className="min-h-0 w-full flex-1 overflow-y-auto px-1 pb-2">
              {connection === "connected" ? (
                <ErrorBoundary label="System Profile">
                  <SystemProfileView revision={profileRevision} scanning={scanning} />
                </ErrorBoundary>
              ) : (
                <p className="text-center text-sm text-slate-400">Backend se connection ka intezar...</p>
              )}
            </div>
          )}
        </section>
        <ActivityPanel events={events} />
      </main>
      <CommandBar onSend={send} disabled={connection !== "connected"} />
    </div>
  );
}
