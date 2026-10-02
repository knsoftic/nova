import { useCallback, useEffect, useRef, useState } from "react";
import { computeLevel, smoothLevel } from "./audio";

export type MicStatus = "off" | "starting" | "on" | "denied" | "unavailable" | "error";

const LEVEL_UPDATE_MS = 50;

/** Path of the AudioWorklet (served from public/, relative so it works from file:// in Electron). */
const WORKLET_URL = "./pcm-worklet.js";

/**
 * Opens the microphone: live level meter, plus (when `onPcm` is given) a 16 kHz mono int16 stream
 * for NOVA's local speech recognition. Audio only goes to NOVA's own backend on this PC.
 */
export function useMicrophone() {
  const [status, setStatus] = useState<MicStatus>("off");
  const [level, setLevel] = useState(0);
  const [deviceLabel, setDeviceLabel] = useState<string | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const resources = useRef<{ stream: MediaStream; ctx: AudioContext; raf: number } | null>(null);

  const release = useCallback(() => {
    const r = resources.current;
    resources.current = null;
    analyserRef.current = null;
    if (!r) return;
    cancelAnimationFrame(r.raf);
    r.stream.getTracks().forEach((t) => t.stop());
    void r.ctx.close().catch(() => undefined);
  }, []);

  const stop = useCallback(() => {
    release();
    setLevel(0);
    setStatus("off");
  }, [release]);

  const start = useCallback(async (onPcm?: (chunk: ArrayBuffer) => void) => {
    if (resources.current) return true;
    if (!navigator.mediaDevices?.getUserMedia) {
      setStatus("unavailable");
      return false;
    }
    setStatus("starting");
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
        video: false,
      });
    } catch (err) {
      const name = err instanceof DOMException ? err.name : "";
      setStatus(
        name === "NotAllowedError" || name === "SecurityError"
          ? "denied"
          : name === "NotFoundError" || name === "OverconstrainedError"
            ? "unavailable"
            : "error",
      );
      return false;
    }

    const ctx = new AudioContext();
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 1024;
    const source = ctx.createMediaStreamSource(stream);
    source.connect(analyser);
    analyserRef.current = analyser;

    if (onPcm) {
      try {
        await ctx.audioWorklet.addModule(WORKLET_URL);
        const node = new AudioWorkletNode(ctx, "pcm-downsampler");
        node.port.onmessage = (e: MessageEvent<ArrayBuffer>) => onPcm(e.data);
        // A muted path to the output keeps the worklet running without playing the mic back.
        const mute = ctx.createGain();
        mute.gain.value = 0;
        source.connect(node).connect(mute).connect(ctx.destination);
      } catch {
        stream.getTracks().forEach((t) => t.stop());
        void ctx.close().catch(() => undefined);
        analyserRef.current = null;
        setStatus("error");
        return false;
      }
    }

    const track = stream.getAudioTracks()[0];
    setDeviceLabel(track?.label || null);
    track?.addEventListener("ended", () => {
      // Device unplugged or disabled in Windows.
      release();
      setLevel(0);
      setStatus("unavailable");
    });

    const buffer = new Float32Array(analyser.fftSize);
    let smoothed = 0;
    let lastPush = 0;
    const tick = (now: number) => {
      analyser.getFloatTimeDomainData(buffer);
      smoothed = smoothLevel(smoothed, computeLevel(buffer));
      if (now - lastPush >= LEVEL_UPDATE_MS) {
        lastPush = now;
        setLevel(smoothed);
      }
      if (resources.current) resources.current.raf = requestAnimationFrame(tick);
    };
    resources.current = { stream, ctx, raf: requestAnimationFrame(tick) };
    setStatus("on");
    return true;
  }, [release]);

  useEffect(() => release, [release]);

  return { status, level, deviceLabel, analyserRef, start, stop };
}
