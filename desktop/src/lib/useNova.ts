import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import type {
  AiStatus,
  ChatMessage,
  ConnectionStatus,
  NovaEvent,
  NovaState,
  PermissionRequest,
  PlanStepSummary,
  ServerMessage,
  UserSettings,
} from "./types";

export const BACKEND_WS_URL = import.meta.env.VITE_NOVA_WS_URL ?? "ws://127.0.0.1:8765/ws";

const MAX_EVENTS = 200;
const MAX_MESSAGES = 100;
// Terminal states are shown briefly before returning to IDLE so the user can see the outcome.
const RESULT_HOLD_MS = 1600;

let messageCounter = 0;
const nextId = () => `${Date.now()}-${++messageCounter}`;

export function useNova() {
  const [connection, setConnection] = useState<ConnectionStatus>("connecting");
  const [state, setState] = useState<NovaState>("IDLE");
  const [assistantName, setAssistantName] = useState("NOVA");
  const [version, setVersion] = useState<string | null>(null);
  const [events, setEvents] = useState<NovaEvent[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [scanning, setScanning] = useState(false);
  // Bumped after every finished scan so profile views know to refetch.
  const [profileRevision, setProfileRevision] = useState(0);
  // Bumped when something lands in the persisted activity log.
  const [activityRevision, setActivityRevision] = useState(0);
  const [settings, setSettings] = useState<UserSettings | null>(null);
  const [aiStatus, setAiStatus] = useState<AiStatus | null>(null);
  // Open permission questions, oldest first.
  const [permissions, setPermissions] = useState<PermissionRequest[]>([]);
  // Latest speech NOVA produced; the UI fetches and plays it.
  const [lastSpeech, setLastSpeech] = useState<{ id: string; duration: number } | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const holdUntil = useRef(0);
  const holdTimer = useRef<number | undefined>(undefined);

  const applyState = useCallback((next: NovaState) => {
    window.clearTimeout(holdTimer.current);
    if (next === "COMPLETED" || next === "ERROR") {
      holdUntil.current = Date.now() + RESULT_HOLD_MS;
      setState(next);
      return;
    }
    const wait = holdUntil.current - Date.now();
    if ((next === "IDLE" || next === "LISTENING") && wait > 0) {
      holdTimer.current = window.setTimeout(() => setState(next), wait);
      return;
    }
    holdUntil.current = 0;
    setState(next);
  }, []);

  const handleMessage = useCallback(
    (msg: ServerMessage) => {
      if (msg.type === "HELLO") {
        setAssistantName(msg.data.assistant_name);
        setVersion(msg.data.version);
        setSettings(msg.data.settings);
        setState(msg.data.state);
        api.aiStatus().then(setAiStatus).catch(() => undefined);
        // Questions asked before this window connected (e.g. after a reload) must still be answerable.
        api
          .pendingPermissions()
          .then((reqs) => setPermissions(reqs.map((r) => ({ ...r, received_at: Date.now() }))))
          .catch(() => undefined);
        setEvents(msg.data.history.filter((e) => e.type !== "STATE_CHANGED").reverse());
        return;
      }
      if (msg.type === "pong" || msg.type === "ERROR") return;

      if (msg.type === "STATE_CHANGED") {
        applyState(msg.data.state as NovaState);
        return;
      }
      setEvents((prev) => [msg, ...prev].slice(0, MAX_EVENTS));
      if (msg.type === "DISCOVERY_STARTED") setScanning(true);
      if (msg.type === "SETTINGS_CHANGED") {
        const next = msg.data as unknown as UserSettings;
        setSettings(next);
        setAssistantName(next.assistant_name);
      }
      if (["TASK_COMPLETED", "TASK_FAILED", "DISCOVERY_COMPLETED", "DISCOVERY_FAILED", "SETTINGS_CHANGED"].includes(msg.type)) {
        setActivityRevision((n) => n + 1);
      }
      if (msg.type === "DISCOVERY_COMPLETED" || msg.type === "DISCOVERY_FAILED") {
        setScanning(false);
        setProfileRevision((n) => n + 1);
      }
      if (msg.type === "AI_STATUS") setAiStatus(msg.data as unknown as AiStatus);
      if (msg.type === "PERMISSION_REQUIRED") {
        const req = { ...(msg.data as unknown as PermissionRequest), received_at: Date.now() };
        setPermissions((prev) => [...prev.filter((p) => p.id !== req.id), req]);
      }
      if (msg.type === "PERMISSION_DECIDED") {
        const id = (msg.data as { request_id?: string }).request_id;
        setPermissions((prev) => prev.filter((p) => p.id !== id));
      }
      if (msg.type === "NOVA_SPEAK") {
        const d = msg.data as { speech_id: string; duration_s: number };
        setLastSpeech({ id: d.speech_id, duration: d.duration_s });
      }
      if (msg.type === "VOICE_TRANSCRIBED") {
        const text = String((msg.data as { text?: string }).text ?? "");
        setMessages((prev) =>
          [...prev, { id: nextId(), role: "user" as const, text, timestamp: msg.timestamp, voice: true }].slice(
            -MAX_MESSAGES,
          ),
        );
      }
      if (msg.type === "NOVA_RESPONSE" || msg.type === "TASK_FAILED") {
        const text = msg.message ?? "";
        const data = msg.data as { provider?: string; steps?: PlanStepSummary[] };
        setMessages((prev) =>
          [
            ...prev,
            {
              id: nextId(),
              role: "nova" as const,
              text,
              timestamp: msg.timestamp,
              failed: msg.type === "TASK_FAILED",
              provider: data.provider,
              steps: data.steps,
            },
          ].slice(-MAX_MESSAGES),
        );
      }
    },
    [applyState],
  );

  useEffect(() => {
    let closed = false;
    let retry = 0;
    let retryTimer: number | undefined;
    let pingTimer: number | undefined;

    const connect = () => {
      setConnection("connecting");
      const ws = new WebSocket(BACKEND_WS_URL);
      wsRef.current = ws;
      ws.onopen = () => {
        retry = 0;
        setConnection("connected");
        pingTimer = window.setInterval(() => ws.send(JSON.stringify({ type: "ping" })), 15_000);
      };
      ws.onmessage = (e) => {
        try {
          handleMessage(JSON.parse(e.data as string) as ServerMessage);
        } catch {
          /* ignore malformed frames */
        }
      };
      ws.onclose = () => {
        window.clearInterval(pingTimer);
        // Only clear the ref if it still points at this socket; a newer one may already be live.
        if (wsRef.current === ws) wsRef.current = null;
        if (closed) return;
        setConnection("disconnected");
        retry = Math.min(retry + 1, 6);
        retryTimer = window.setTimeout(connect, 500 * 2 ** retry);
      };
      ws.onerror = () => ws.close();
    };

    connect();
    return () => {
      closed = true;
      window.clearTimeout(retryTimer);
      window.clearInterval(pingTimer);
      window.clearTimeout(holdTimer.current);
      wsRef.current?.close();
    };
  }, [handleMessage]);

  const sendCommand = useCallback((text: string, source: "text" | "voice" = "text") => {
    const trimmed = text.trim();
    const ws = wsRef.current;
    if (!trimmed || !ws || ws.readyState !== WebSocket.OPEN) return false;
    ws.send(JSON.stringify({ type: "command", text: trimmed, source }));
    setMessages((prev) =>
      [...prev, { id: nextId(), role: "user" as const, text: trimmed, timestamp: new Date().toISOString() }].slice(
        -MAX_MESSAGES,
      ),
    );
    return true;
  }, []);


  const clearEvents = useCallback(() => setEvents([]), []);

  /** Tell the backend NOVA's voice is playing, so the microphone pipeline ignores it. */
  const sendPlayback = useCallback((active: boolean) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "playback", active }));
  }, []);

  const refreshAiStatus = useCallback(async () => {
    try {
      setAiStatus(await api.aiStatus(true));
    } catch {
      /* backend offline: keep the last known status */
    }
  }, []);

  return {
    connection,
    state,
    assistantName,
    version,
    events,
    messages,
    sendCommand,
    clearEvents,
    scanning,
    profileRevision,
    activityRevision,
    settings,
    aiStatus,
    refreshAiStatus,
    lastSpeech,
    sendPlayback,
    permissions,
  };
}
