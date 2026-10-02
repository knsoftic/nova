import { ActivityPanel } from "./components/ActivityPanel";
import { AgentPanel } from "./components/AgentPanel";
import { CommandBar } from "./components/CommandBar";
import { Conversation } from "./components/Conversation";
import { NovaCore } from "./components/NovaCore";
import { StatusBar } from "./components/StatusBar";
import { useNova } from "./lib/useNova";

export default function App() {
  const { connection, state, assistantName, version, events, messages, sendCommand } = useNova();

  return (
    <div className="flex h-screen flex-col gap-4 p-4">
      <StatusBar name={assistantName} connection={connection} version={version} />
      <main className="grid min-h-0 flex-1 grid-cols-[260px_1fr_320px] gap-4">
        <AgentPanel state={state} events={events} />
        <section className="panel flex min-h-0 flex-col items-center gap-6 overflow-hidden">
          <div className="pt-6">
            <NovaCore state={state} name={assistantName} />
          </div>
          <div className="min-h-0 w-full max-w-2xl flex-1 overflow-y-auto px-2 pb-2">
            <Conversation messages={messages} assistantName={assistantName} />
          </div>
        </section>
        <ActivityPanel events={events} />
      </main>
      <CommandBar onSend={sendCommand} disabled={connection !== "connected"} />
    </div>
  );
}
