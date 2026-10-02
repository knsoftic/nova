import { useEffect, useRef } from "react";
import type { ChatMessage } from "../lib/types";
import { formatTime } from "../lib/ui";

export function Conversation({ messages, assistantName }: { messages: ChatMessage[]; assistantName: string }) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  if (messages.length === 0) {
    return (
      <p className="text-center text-sm text-slate-500">
        Neeche command likhiye, maslan: <span className="text-slate-300">"Chrome open karo"</span>
      </p>
    );
  }

  return (
    <div className="flex w-full flex-col gap-3">
      {messages.map((m) => (
        <div key={m.id} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
          <div
            className={`max-w-[85%] rounded-xl px-4 py-2 text-sm ${
              m.role === "user"
                ? "bg-sky-500/15 text-sky-50"
                : m.failed
                  ? "border border-red-500/30 bg-red-500/10 text-red-100"
                  : "border border-white/10 bg-white/5 text-slate-100"
            }`}
          >
            <div className="mb-0.5 flex gap-2 font-mono text-[10px] text-slate-500">
              <span>{m.role === "user" ? "Aap" : assistantName}</span>
              <span>{formatTime(m.timestamp)}</span>
            </div>
            {m.text}
          </div>
        </div>
      ))}
      <div ref={endRef} />
    </div>
  );
}
