import { useCallback, useEffect, useRef, useState } from "react";
import { ActivityLogView } from "./components/ActivityLogView";
import { ActivityPanel } from "./components/ActivityPanel";
import { AgentPanel } from "./components/AgentPanel";
import { CommandBar } from "./components/CommandBar";
import { Conversation } from "./components/Conversation";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { MIC_LABEL, MicControl } from "./components/MicControl";
import { NovaCore } from "./components/NovaCore";
import { SettingsDrawer } from "./components/SettingsDrawer";
import { StatusBar } from "./components/StatusBar";
import { SystemProfileView } from "./components/SystemProfileView";
import type { NovaState } from "./lib/types";
import { useMicrophone } from "./lib/useMicrophone";
import { useNova } from "./lib/useNova";

type CenterView = "conversation" | "system" | "log";

const VIEWS: { id: CenterView; label: string }[] = [
  { id: "conversation", label: "Conversation" },
  { id: "system", label: "System Profile" },
  { id: "log", label: "Activity Log" },
];

const PREVIEW_MS = 4000;

export default function App() {
  const nova = useNova();
  const mic = useMicrophone();
  const [view, setView] = useState<CenterView>("conversation");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [agentFilter, setAgentFilter] = useState<string | null>(null);
  const [previewState, setPreviewState] = useState<NovaState | null>(null);
  const previewTimer = useRef<number | undefined>(undefined);

  const { sendVoiceState } = nova;
  // Keep the backend's LISTENING state in sync with the real microphone (incl. device unplugged).
  useEffect(() => {
    sendVoiceState(mic.status === "on");
  }, [mic.status, sendVoiceState]);

  // Never leave the microphone open when the backend is gone.
  const { stop: stopMic } = mic;
  useEffect(() => {
    if (nova.connection !== "connected") stopMic();
  }, [nova.connection, stopMic]);

  useEffect(() => () => window.clearTimeout(previewTimer.current), []);

  const toggleMic = () => {
    if (mic.status === "on") mic.stop();
    else void mic.start();
  };

  const send = (text: string) => {
    const sent = nova.sendCommand(text);
    if (sent) setView("conversation");
    return sent;
  };

  const preview = useCallback((s: NovaState) => {
    window.clearTimeout(previewTimer.current);
    setPreviewState(s);
    setView("conversation");
    previewTimer.current = window.setTimeout(() => setPreviewState(null), PREVIEW_MS);
  }, []);

  const closeSettings = useCallback(() => setSettingsOpen(false), []);

  const shownState = previewState ?? nova.state;
  const voiceNote =
    mic.status === "on"
      ? "Mic on hai — abhi sirf awaaz ka level dikhaya ja raha hai; awaaz se command Phase 5 mein aayegi. Audio na save hota hai na kahin bheja jata hai."
      : ["denied", "unavailable", "error"].includes(mic.status)
        ? MIC_LABEL[mic.status].hint
        : null;

  return (
    <div className="flex h-screen flex-col gap-4 p-4">
      <StatusBar
        name={nova.assistantName}
        connection={nova.connection}
        version={nova.version}
        micStatus={mic.status}
        onOpenSettings={() => setSettingsOpen(true)}
      />
      <main className="grid min-h-0 flex-1 grid-cols-[260px_1fr_320px] gap-4">
        <AgentPanel state={nova.state} events={nova.events} selected={agentFilter} onSelect={setAgentFilter} />
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
                {v.id === "system" && nova.scanning && <span className="ml-2 animate-pulse text-amber-300">●</span>}
              </button>
            ))}
          </nav>
          {view === "conversation" && (
            <>
              <NovaCore
                state={shownState}
                name={nova.assistantName}
                level={shownState === "LISTENING" ? mic.level : 0}
                preview={previewState !== null}
              />
              <div className="min-h-0 w-full max-w-2xl flex-1 overflow-y-auto px-2 pb-2" data-scroll-container>
                <ErrorBoundary label="Conversation">
                  <Conversation messages={nova.messages} assistantName={nova.assistantName} />
                </ErrorBoundary>
              </div>
            </>
          )}
          {view !== "conversation" && (
            <div className="min-h-0 w-full flex-1 overflow-y-auto px-1 pb-2">
              {nova.connection !== "connected" ? (
                <p className="text-center text-sm text-slate-400">Backend se connection ka intezar...</p>
              ) : view === "system" ? (
                <ErrorBoundary label="System Profile">
                  <SystemProfileView revision={nova.profileRevision} scanning={nova.scanning} />
                </ErrorBoundary>
              ) : (
                <ErrorBoundary label="Activity Log">
                  <ActivityLogView revision={nova.activityRevision} />
                </ErrorBoundary>
              )}
            </div>
          )}
        </section>
        <ActivityPanel
          events={nova.events}
          agentFilter={agentFilter}
          onClearAgent={() => setAgentFilter(null)}
          onClear={nova.clearEvents}
        />
      </main>
      <CommandBar
        onSend={send}
        disabled={nova.connection !== "connected"}
        voiceNote={voiceNote}
        mic={
          <MicControl
            status={mic.status}
            deviceLabel={mic.deviceLabel}
            analyserRef={mic.analyserRef}
            onToggle={toggleMic}
            disabled={nova.connection !== "connected"}
          />
        }
      />
      <SettingsDrawer
        open={settingsOpen}
        settings={nova.settings}
        onClose={closeSettings}
        onPreviewState={preview}
      />
    </div>
  );
}
