import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent, type ReactNode } from "react";
import { emptyHistory, navigateHistory, pushHistory } from "../lib/commandHistory";

interface Props {
  onSend: (text: string) => boolean;
  disabled: boolean;
  mic: ReactNode;
  voiceNote: string | null;
}

export function CommandBar({ onSend, disabled, mic, voiceNote }: Props) {
  const [text, setText] = useState("");
  const [history, setHistory] = useState(emptyHistory);
  const inputRef = useRef<HTMLInputElement>(null);

  // autoFocus only applies at mount, when the input is usually still disabled (backend connecting).
  useEffect(() => {
    if (!disabled) inputRef.current?.focus();
  }, [disabled]);

  // Ctrl+K (or /) focuses the command box from anywhere.
  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      const typing = e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement;
      if ((e.ctrlKey && e.key.toLowerCase() === "k") || (e.key === "/" && !typing)) {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (onSend(text)) {
      setHistory((h) => pushHistory(h, text));
      setText("");
    }
  };

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowUp" || e.key === "ArrowDown") {
      e.preventDefault();
      const r = navigateHistory(history, e.key === "ArrowUp" ? "up" : "down", text);
      setHistory(r.history);
      setText(r.value);
    } else if (e.key === "Escape") {
      setText("");
      setHistory((h) => ({ ...h, index: null }));
    }
  };

  return (
    <form onSubmit={submit} className="panel flex flex-col gap-1.5 !py-3">
      <div className="flex items-center gap-3">
        {mic}
        <input
          ref={inputRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDown}
          maxLength={2000}
          placeholder={disabled ? "Backend se connect ho raha hai..." : 'Command likhiye, maslan "VS Code open karo"  (Ctrl+K, ↑ pichli command)'}
          disabled={disabled}
          className="min-w-0 flex-1 rounded-lg border border-white/10 bg-black/30 px-4 py-2 text-sm text-slate-100 outline-none placeholder:text-slate-500 focus:border-sky-500/60 disabled:opacity-50"
          aria-label="NOVA command"
        />
        <button
          type="submit"
          disabled={disabled || !text.trim()}
          className="shrink-0 rounded-lg bg-sky-500 px-5 py-2 text-sm font-medium text-slate-950 transition hover:bg-sky-400 disabled:cursor-not-allowed disabled:opacity-40"
        >
          Bhejein
        </button>
      </div>
      {voiceNote && <p className="pl-1 text-[11px] text-slate-400">{voiceNote}</p>}
    </form>
  );
}
