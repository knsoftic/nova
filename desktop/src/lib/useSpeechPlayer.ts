import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";

/**
 * Plays each new utterance NOVA speaks and reports playback to the backend, so the microphone
 * pipeline ignores NOVA's own voice. A newer utterance interrupts an older one.
 */
export function useSpeechPlayer(lastSpeech: { id: string } | null, sendPlayback: (active: boolean) => void) {
  const [speaking, setSpeaking] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const stop = useCallback(() => {
    const audio = audioRef.current;
    audioRef.current = null;
    if (audio) {
      audio.pause();
      audio.src = "";
    }
    setSpeaking(false);
    sendPlayback(false);
  }, [sendPlayback]);

  useEffect(() => {
    if (!lastSpeech) return;
    audioRef.current?.pause();
    const audio = new Audio(api.speechUrl(lastSpeech.id));
    audioRef.current = audio;
    const finish = () => {
      if (audioRef.current !== audio) return;
      audioRef.current = null;
      setSpeaking(false);
      sendPlayback(false);
    };
    audio.onplaying = () => {
      setSpeaking(true);
      sendPlayback(true);
    };
    audio.onended = finish;
    audio.onerror = finish;
    void audio.play().catch(finish);
  }, [lastSpeech, sendPlayback]);

  useEffect(() => () => audioRef.current?.pause(), []);

  return { speaking, stop };
}
