import { useCallback, useEffect, useRef, useState } from "react";
import type { ChatMessage, ConnectionStatus, NovaEvent, NovaState, ServerMessage } from "./types";

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
    if (next === "IDLE" && wait > 0) {
      holdTimer.current = window.setTimeout(() => setState("IDLE"), wait);
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
        setState(msg.data.state);
        setEvents(msg.data.history.filter((e) => e.type !== "STATE_CHANGED").reverse());
        return;
      }
      if (msg.type === "pong" || msg.type === "ERROR") return;

      if (msg.type === "STATE_CHANGED") {
        applyState(msg.data.state as NovaState);
        return;
      }
      setEvents((prev) => [msg, ...prev].slice(0, MAX_EVENTS));
      if (msg.type === "NOVA_RESPONSE" || msg.type === "TASK_FAILED") {
        const text = msg.message ?? "";
        setMessages((prev) =>
          [
            ...prev,
            { id: nextId(), role: "nova" as const, text, timestamp: msg.timestamp, failed: msg.type === "TASK_FAILED" },
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

  return { connection, state, assistantName, version, events, messages, sendCommand };
}
