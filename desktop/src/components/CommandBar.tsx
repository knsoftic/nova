import { useEffect, useRef, useState, type FormEvent } from "react";

export function CommandBar({ onSend, disabled }: { onSend: (text: string) => boolean; disabled: boolean }) {
  const [text, setText] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  // autoFocus only applies at mount, when the input is usually still disabled (backend connecting).
  useEffect(() => {
    if (!disabled) inputRef.current?.focus();
  }, [disabled]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (onSend(text)) setText("");
  };

  return (
    <form onSubmit={submit} className="panel flex items-center gap-3 !py-3">
      <button
        type="button"
        disabled
        className="flex shrink-0 items-center gap-2 rounded-lg border border-white/10 px-3 py-2 text-xs text-slate-400"
        title="Voice input Phase 5 mein add hoga"
        aria-label="Microphone off. Voice input Phase 5 mein add hoga"
      >
        <span className="h-2 w-2 rounded-full bg-slate-500" />
        Mic: Off
      </button>
      <input
        ref={inputRef}
        value={text}
        onChange={(e) => setText(e.target.value)}
        maxLength={2000}
        placeholder={disabled ? "Backend se connect ho raha hai..." : 'Command likhiye, maslan "VS Code open karo"'}
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
    </form>
  );
}
