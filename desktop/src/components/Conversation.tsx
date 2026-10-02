import { useEffect, useRef } from "react";
import type { ChatMessage, PlanStepSummary } from "../lib/types";
import { formatTime, linkParts, messageBlocks, providerLabel } from "../lib/ui";

const STEP_BADGE: Record<PlanStepSummary["status"], { icon: string; tone: string }> = {
  done: { icon: "✓", tone: "text-emerald-300" },
  ready: { icon: "•", tone: "text-slate-300" },
  unavailable: { icon: "⏳", tone: "text-slate-400" },
  needs_permission: { icon: "🔒", tone: "text-orange-300" },
  denied: { icon: "⛔", tone: "text-slate-400" },
  failed: { icon: "✕", tone: "text-red-300" },
  skipped: { icon: "–", tone: "text-slate-500" },
};

function stepNote(s: PlanStepSummary): string {
  if (s.status === "unavailable" && s.available_from_phase) return `Phase ${s.available_from_phase} mein`;
  if (s.status === "needs_permission") return "ijazat chahiye";
  if (s.status === "denied") return s.permission === "timeout" ? "jawab nahi aaya — nahi kiya" : "ijazat nahi mili";
  if (s.status === "done" && s.permission === "rule") return "ho gaya (pehle di gayi ijazat se)";
  if (s.status === "done" && s.permission === "approved") return "ijazat se ho gaya";
  if (s.status === "done") return "ho gaya";
  return s.status;
}

/** A reply written by the language model (a general question), not by NOVA's fixed templates. */
function isModelAnswer(m: ChatMessage): boolean {
  return (
    m.role === "nova" &&
    !!m.provider &&
    m.provider !== "rule_based" &&
    !!m.steps?.some((s) => s.intent === "chat")
  );
}

/** Shown under a reply when NOVA planned more than one step, or a step could not run yet. */
function PlanSteps({ steps }: { steps: PlanStepSummary[] }) {
  return (
    <ol className="mt-2 flex flex-col gap-0.5 border-t border-white/10 pt-1.5 text-[11px]">
      {steps.map((s) => {
        const b = STEP_BADGE[s.status];
        return (
          <li key={s.id} className="flex items-center gap-2">
            <span className={`w-4 text-center ${b.tone}`}>{b.icon}</span>
            <span className="text-slate-300">
              {s.id}. {s.description}
            </span>
            <span className="text-slate-500">
              · {s.agent} · {stepNote(s)}
              {s.risk !== "low" && ` · risk ${s.risk}`}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

export function Conversation({ messages, assistantName }: { messages: ChatMessage[]; assistantName: string }) {
  const endRef = useRef<HTMLDivElement>(null);
  // Scroll only our own container: scrollIntoView would also scroll overflow-hidden ancestors and
  // push the view tabs out of sight on short windows.
  useEffect(() => {
    const scroller = endRef.current?.closest<HTMLElement>("[data-scroll-container]");
    scroller?.scrollTo({ top: scroller.scrollHeight, behavior: "smooth" });
  }, [messages]);

  if (messages.length === 0) {
    return (
      <p className="text-center text-sm text-slate-500">
        Neeche command likhiye, maslan: <span className="text-slate-300">"Chrome open karo aur RAM batao"</span>
      </p>
    );
  }

  return (
    <div className="flex w-full flex-col gap-3">
      {messages.map((m) => {
        const provider = providerLabel(m.provider);
        const showSteps = m.steps && (m.steps.length > 1 || m.steps.some((s) => s.status !== "done"));
        return (
          <div key={m.id} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
            <div
              className={`max-w-[85%] whitespace-pre-line rounded-xl px-4 py-2 text-sm ${
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
                {provider && <span title="Kis ne samjha">· {provider}</span>}
              </div>
              {messageBlocks(m.text).map((block, b) =>
                block.code ? (
                  <pre
                    key={b}
                    className="my-1.5 max-h-72 overflow-auto whitespace-pre rounded-lg border border-white/10 bg-black/40 p-2.5 font-mono text-[11px] leading-relaxed text-slate-200"
                  >
                    {block.text}
                  </pre>
                ) : (
                  <span key={b}>
                    {linkParts(block.text).map((p, i) =>
                      p.href ? (
                        <a
                          key={i}
                          href={p.href}
                          target="_blank"
                          rel="noreferrer"
                          className="break-all text-sky-300 underline decoration-sky-300/40 hover:text-sky-200"
                        >
                          {p.text}
                        </a>
                      ) : (
                        p.text
                      ),
                    )}
                  </span>
                ),
              )}
              {isModelAnswer(m) && (
                <div className="mt-1.5 text-[10px] text-slate-500">
                  AI ka jawab ({provider}) — chhota local model hai, ghalti ho sakti hai.
                </div>
              )}
              {showSteps && m.steps && <PlanSteps steps={m.steps} />}
            </div>
          </div>
        );
      })}
      <div ref={endRef} />
    </div>
  );
}
