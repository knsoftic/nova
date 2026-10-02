import { useCallback, useEffect, useRef, useState } from "react";

export const VOICE_WS_URL = import.meta.env.VITE_NOVA_VOICE_WS_URL ?? "ws://127.0.0.1:8765/ws/voice";

export type ListenMode = "ptt" | "continuous";
/** listening: waiting for speech · hearing: speech in progress · processing: transcribing/handling. */
export type VoicePhase = "idle" | "listening" | "hearing" | "processing";

interface ServerMessage {
  type: "speech_start" | "processing" | "heard" | "done" | "error";
  text?: string;
  message?: string;
  heard?: boolean;
}

/** Streams microphone PCM to NOVA's local speech pipeline and tracks where an utterance is. */
export function useVoice(onDone: () => void) {
  const [phase, setPhase] = useState<VoicePhase>("idle");
  const [mode, setMode] = useState<ListenMode>("ptt");
  const [error, setError] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const phaseRef = useRef<VoicePhase>("idle");
  const onDoneRef = useRef(onDone);
  onDoneRef.current = onDone;

  const update = (p: VoicePhase) => {
    phaseRef.current = p;
    setPhase(p);
  };

  const close = useCallback(() => {
    const ws = wsRef.current;
    wsRef.current = null;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "stop" }));
    ws?.close();
    update("idle");
  }, []);

  const start = useCallback(
    (listenMode: ListenMode) =>
      new Promise<boolean>((resolve) => {
        setError(null);
        setMode(listenMode);
        const ws = new WebSocket(VOICE_WS_URL);
        ws.binaryType = "arraybuffer";
        wsRef.current = ws;
        ws.onopen = () => {
          ws.send(JSON.stringify({ type: "start", mode: listenMode }));
          update("listening");
          resolve(true);
        };
        ws.onmessage = (e) => {
          let msg: ServerMessage;
          try {
            msg = JSON.parse(e.data as string) as ServerMessage;
          } catch {
            return;
          }
          if (msg.type === "speech_start") update("hearing");
          else if (msg.type === "processing") update("processing");
          else if (msg.type === "heard") update("processing");
          else if (msg.type === "done") {
            close();
            onDoneRef.current();
          } else if (msg.type === "error") {
            setError(msg.message ?? "Voice error");
            close();
            onDoneRef.current();
          }
        };
        ws.onerror = () => {
          setError("Voice service se rabta nahi ho saka");
          resolve(false);
        };
        ws.onclose = () => {
          if (wsRef.current === ws) {
            wsRef.current = null;
            if (phaseRef.current !== "idle") {
              update("idle");
              onDoneRef.current();
            }
          }
        };
      }),
    [close],
  );

  // After a continuous-mode command NOVA goes back to waiting; reflect that once processing ends.
  const sendPcm = useCallback((chunk: ArrayBuffer) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(chunk);
  }, []);

  const markListening = useCallback(() => {
    if (phaseRef.current !== "idle") update("listening");
  }, []);

  useEffect(() => close, [close]);

  return { phase, mode, error, start, stop: close, sendPcm, markListening };
}
