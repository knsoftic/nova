import { useCallback, useEffect, useRef, useState } from "react";
import { ActivityLogView } from "./components/ActivityLogView";
import { ActivityPanel } from "./components/ActivityPanel";
import { AgentPanel } from "./components/AgentPanel";
import { CommandBar } from "./components/CommandBar";
import { Conversation } from "./components/Conversation";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { MemoryView } from "./components/MemoryView";
import { MIC_LABEL, MicControl } from "./components/MicControl";
import { NovaCore } from "./components/NovaCore";
import { PermissionDialog } from "./components/PermissionDialog";
import { SettingsDrawer } from "./components/SettingsDrawer";
import { StatusBar } from "./components/StatusBar";
import { SystemProfileView } from "./components/SystemProfileView";
import type { NovaState } from "./lib/types";
import { useMicrophone } from "./lib/useMicrophone";
import { useNova } from "./lib/useNova";
import { useSpeechPlayer } from "./lib/useSpeechPlayer";
import { useVoice, type ListenMode } from "./lib/useVoice";

type CenterView = "conversation" | "system" | "log" | "memory";

const VIEWS: { id: CenterView; label: string }[] = [
  { id: "conversation", label: "Conversation" },
  { id: "system", label: "System Profile" },
  { id: "log", label: "Activity Log" },
  { id: "memory", label: "Memory" },
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
  // Set when the user switches the mic off (or it failed), so continuous listening does not restart it.
  const userStopped = useRef(false);

  const { stop: stopMic } = mic;
  const voice = useVoice(
    useCallback(() => {
      // The server ends a push-to-talk turn after one utterance; in continuous mode "done" means an error.
      stopMic();
    }, [stopMic]),
  );
  const player = useSpeechPlayer(nova.lastSpeech, nova.sendPlayback);
  const continuous = nova.settings?.continuous_listening ?? false;
  const wakeWord = nova.settings?.wake_word ?? "Hey NOVA";

  const { start: startMic } = mic;
  const { start: startVoice, stop: stopVoice, sendPcm, markListening } = voice;

  const startListening = useCallback(
    async (mode: ListenMode) => {
      if (!(await startMic(sendPcm))) {
        userStopped.current = true;
        return;
      }
      if (!(await startVoice(mode))) {
        userStopped.current = true;
        stopMic();
      }
    },
    [startMic, startVoice, sendPcm, stopMic],
  );

  const stopListening = useCallback(() => {
    stopVoice();
    stopMic();
  }, [stopVoice, stopMic]);

  // Continuous listening: keep the mic open and wait for the wake word, unless the user switched it off.
  useEffect(() => {
    if (nova.connection !== "connected") return;
    if (continuous && mic.status === "off" && !userStopped.current) void startListening("continuous");
    if (!continuous && voice.mode === "continuous" && mic.status === "on") stopListening();
  }, [nova.connection, continuous, mic.status, voice.mode, startListening, stopListening]);

  // Never leave the microphone open when the backend is gone.
  useEffect(() => {
    if (nova.connection !== "connected") stopListening();
  }, [nova.connection, stopListening]);

  // Voice commands that need permission, or NOVA's own question ("Ye yaad rakhoon?"): once NOVA has finished
  // asking out loud, open the mic for the answer.
  const awaitingVoiceAnswer = useRef<string | null>(null);
  const wasSpeaking = useRef(false);
  const latestRequest = nova.permissions[nova.permissions.length - 1];
  const voiceQuestion = latestRequest ? (latestRequest.source === "voice" ? latestRequest.id : null) : nova.voiceFollowUp;
  useEffect(() => {
    awaitingVoiceAnswer.current = voiceQuestion;
  }, [voiceQuestion]);
  useEffect(() => {
    const finished = wasSpeaking.current && !player.speaking;
    wasSpeaking.current = player.speaking;
    if (finished && awaitingVoiceAnswer.current && mic.status === "off") {
      awaitingVoiceAnswer.current = null;
      userStopped.current = false;
      void startListening("ptt");
    }
  }, [player.speaking, mic.status, startListening]);

  // After a continuous-mode command, NOVA returns to LISTENING: show "waiting" again.
  useEffect(() => {
    if (nova.state === "LISTENING") markListening();
  }, [nova.state, markListening]);

  useEffect(() => () => window.clearTimeout(previewTimer.current), []);

  const toggleMic = () => {
    if (mic.status === "on") {
      userStopped.current = true;
      stopListening();
    } else {
      userStopped.current = false;
      player.stop(); // speaking over NOVA interrupts it
      void startListening(continuous ? "continuous" : "ptt");
    }
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

  let voiceNote: string | null = null;
  if (voice.error) voiceNote = voice.error;
  else if (["denied", "unavailable", "error"].includes(mic.status)) voiceNote = MIC_LABEL[mic.status].hint;
  else if (player.speaking) voiceNote = "Bol raha hoon... (mic button dabane se ruk jayega)";
  else if (mic.status === "on") {
    voiceNote =
      voice.phase === "hearing"
        ? "Sun raha hoon..."
        : voice.phase === "processing"
          ? "Samajh raha hoon..."
          : voice.mode === "continuous"
            ? `"${wakeWord}" keh kar command dein. Doosri baatein na save hoti hain na dikhai jati hain.`
            : "Bolein — khamosh hote hi command bhej di jayegi.";
  }

  const micLabel =
    mic.status !== "on" ? undefined : voice.mode === "continuous" ? `Mic: On · ${wakeWord}` : "Mic: Bolein";

  return (
    <div className="flex h-screen flex-col gap-4 p-4">
      <StatusBar
        name={nova.assistantName}
        connection={nova.connection}
        version={nova.version}
        micStatus={mic.status}
        micLabel={micLabel}
        aiStatus={nova.aiStatus}
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
                speaking={player.speaking && previewState === null}
              />
              <div className="min-h-0 w-full max-w-2xl flex-1 overflow-y-auto px-2 pb-2" data-scroll-container>
                <ErrorBoundary label="Conversation">
                  <Conversation messages={nova.messages} assistantName={nova.assistantName} onQuickReply={send} />
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
              ) : view === "memory" ? (
                <ErrorBoundary label="Memory">
                  <MemoryView
                    revision={nova.memoryRevision}
                    historyDays={nova.settings?.history_days ?? 90}
                    onRun={(command) => void send(command)}
                  />
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
            label={micLabel}
            deviceLabel={mic.deviceLabel}
            analyserRef={mic.analyserRef}
            onToggle={toggleMic}
            disabled={nova.connection !== "connected"}
          />
        }
      />
      {nova.permissions.length > 0 && <PermissionDialog key={nova.permissions[0].id} request={nova.permissions[0]} />}
      <SettingsDrawer
        open={settingsOpen}
        settings={nova.settings}
        aiStatus={nova.aiStatus}
        onRefreshAi={nova.refreshAiStatus}
        onClose={closeSettings}
        onPreviewState={preview}
      />
    </div>
  );
}
