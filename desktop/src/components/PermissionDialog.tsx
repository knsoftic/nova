import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import type { PermissionRequest, Risk } from "../lib/types";

const RISK_STYLE: Record<Risk, { label: string; badge: string; border: string }> = {
  low: { label: "Kam khatra", badge: "bg-emerald-500/15 text-emerald-200", border: "border-emerald-500/40" },
  medium: { label: "Darmiyana khatra", badge: "bg-amber-500/15 text-amber-200", border: "border-amber-500/50" },
  high: { label: "Zyada khatra", badge: "bg-red-500/20 text-red-200", border: "border-red-500/70" },
};

function useCountdown(request: PermissionRequest): number {
  const deadline = (request.received_at ?? Date.now()) + request.timeout_s * 1000;
  const [left, setLeft] = useState(() => Math.max(0, Math.ceil((deadline - Date.now()) / 1000)));
  useEffect(() => {
    const id = window.setInterval(() => setLeft(Math.max(0, Math.ceil((deadline - Date.now()) / 1000))), 250);
    return () => window.clearInterval(id);
  }, [deadline]);
  return left;
}

/**
 * Asks the user before NOVA does something risky. Safe by default: focus starts on "Nahi",
 * Escape denies, and no answer before the countdown ends counts as "no" on the backend.
 */
export function PermissionDialog({ request }: { request: PermissionRequest }) {
  const [remember, setRemember] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const noRef = useRef<HTMLButtonElement>(null);
  const left = useCountdown(request);
  const style = RISK_STYLE[request.max_risk];

  useEffect(() => {
    noRef.current?.focus();
    void window.nova?.attention?.();
  }, [request.id]);

  const decide = async (approved: boolean) => {
    setBusy(true);
    setError(null);
    try {
      await api.decidePermission(request.id, approved, approved && remember);
    } catch {
      setError("Jawab nahi bheja ja saka — shayad waqt khatam ho gaya.");
      setBusy(false);
    }
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") void decide(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 p-6">
      <div
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="perm-title"
        className={`flex w-full max-w-lg flex-col gap-4 rounded-2xl border-2 bg-slate-950 p-6 shadow-2xl ${style.border}`}
      >
        <div className="flex items-center justify-between gap-3">
          <h2 id="perm-title" className="text-lg font-semibold text-slate-100">
            NOVA aap ki ijazat chahta hai
          </h2>
          <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${style.badge}`}>{style.label}</span>
        </div>

        <ul className="flex flex-col gap-3">
          {request.items.map((item) => (
            <li key={item.step_id} className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
              <div className="text-sm text-slate-100">{item.description}</div>
              {item.reasons.length > 0 && (
                <ul className="mt-1.5 flex flex-col gap-0.5">
                  {item.reasons.map((r) => (
                    <li key={r} className={`text-xs ${item.risk === "high" ? "text-red-300" : "text-amber-200/80"}`}>
                      ⚠ {r}
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>

        {request.rememberable ? (
          <label className="flex items-center gap-2 text-sm text-slate-300">
            <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
            Aage se isi app mein ye kaam bina pooche kar dena
          </label>
        ) : (
          <p className="text-xs text-slate-500">Ye khatarnak kaam hai — NOVA har dafa poochega.</p>
        )}

        {error && <p className="text-xs text-red-300">{error}</p>}

        <div className="flex items-center justify-between gap-3">
          <span className="text-xs text-slate-500" aria-live="polite">
            {left > 0 ? `${left}s mein jawab na diya to "Nahi" samjha jayega` : "Waqt khatam"}
            {request.source === "voice" && " · Awaaz se bhi \"haan\" ya \"nahi\" keh sakte hain"}
          </span>
          <div className="flex gap-2">
            <button
              ref={noRef}
              type="button"
              disabled={busy}
              onClick={() => void decide(false)}
              className="rounded-lg border border-white/15 px-4 py-2 text-sm text-slate-200 hover:bg-white/5 disabled:opacity-50"
            >
              Nahi
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => void decide(true)}
              className={`rounded-lg px-4 py-2 text-sm font-medium text-slate-950 disabled:opacity-50 ${
                request.max_risk === "high" ? "bg-red-400 hover:bg-red-300" : "bg-sky-500 hover:bg-sky-400"
              }`}
            >
              Haan, karo
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
