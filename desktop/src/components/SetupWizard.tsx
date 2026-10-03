import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import type { SetupProgress, SetupStatus, UserSettings } from "../lib/types";
import { listensAfterSetup, stepSettled } from "../lib/ui";

const OLLAMA_DOWNLOAD = "https://ollama.com/download";
const STEPS = ["Salam", "Windows start", "AI model", "Awaaz", "Tayyar"];

const buttonClass = "rounded-lg px-4 py-2 text-sm transition disabled:opacity-40";
const primary = `${buttonClass} bg-sky-500 font-medium text-slate-950 hover:bg-sky-400`;
const secondary = `${buttonClass} border border-white/10 text-slate-200 hover:bg-white/5`;

function Check({ ok, children }: { ok: boolean; children: React.ReactNode }) {
  return (
    <li className="flex items-start gap-2 text-sm">
      <span className={ok ? "text-emerald-300" : "text-amber-300"}>{ok ? "✓" : "•"}</span>
      <span className="text-slate-200">{children}</span>
    </li>
  );
}

/** First run (Phase 12): start with Windows (silent/active), the local AI model, the voice. Everything can be
 * changed later in Settings; "Abhi nahi" skips it. Nothing is downloaded without the user's click. */
export function SetupWizard({
  settings,
  progress,
  onDone,
}: {
  settings: UserSettings;
  progress: SetupProgress | null;
  onDone: () => void;
}) {
  const [step, setStep] = useState(0);
  const stepAt = useRef(0);
  const [status, setStatus] = useState<SetupStatus | null>(null);
  const [startWithWindows, setStartWithWindows] = useState(settings.start_with_windows);
  const [micOn, setMicOn] = useState(settings.continuous_listening);
  const [mode, setMode] = useState<UserSettings["startup_mode"]>(settings.startup_mode);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  const settled = () => stepSettled(stepAt.current, performance.now());
  const go = (next: number) => {
    if (next > step && !settled()) return;
    stepAt.current = performance.now();
    setStep(next);
  };

  const refresh = () => api.setupStatus().then(setStatus).catch(() => setStatus(null));
  useEffect(() => {
    void refresh();
  }, []);
  useEffect(() => {
    if (progress?.done) void refresh();
  }, [progress?.done]);

  const finish = async (skip: boolean) => {
    setSaving(true);
    setError("");
    try {
      const patch: Partial<UserSettings> = { setup_done: true };
      if (!skip) {
        patch.start_with_windows = startWithWindows;
        patch.startup_mode = mode;
        patch.continuous_listening = listensAfterSetup(micOn, startWithWindows, mode);
      }
      await api.updateSettings(patch);
      if (!skip) await window.nova?.setStartup?.(startWithWindows);
      onDone();
    } catch {
      setError("Settings save nahi ho sakin — backend chal raha hai?");
    } finally {
      setSaving(false);
    }
  };

  const pull = async () => {
    setError("");
    try {
      await api.pullModel();
    } catch {
      setError("Ollama nahi chal raha — pehle Ollama install/start karein, phir \"Dobara check\".");
    }
  };

  const ollama = status?.ollama;
  const packaged = status?.install.packaged ?? false;
  const voice = status?.install.voice_models;
  const pulling = Boolean(ollama?.pulling || (progress && !progress.done));

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/70 p-6 backdrop-blur-sm">
      <section className="panel flex w-full max-w-xl flex-col gap-4" role="dialog" aria-label="NOVA setup">
        <ol className="flex gap-1 text-[10px]">
          {STEPS.map((s, i) => (
            <li
              key={s}
              className={`flex-1 rounded px-2 py-1 text-center ${i === step ? "bg-sky-500/25 text-sky-100" : i < step ? "bg-emerald-500/15 text-emerald-200" : "bg-white/5 text-slate-500"}`}
            >
              {s}
            </li>
          ))}
        </ol>

        {step === 0 && (
          <div className="flex flex-col gap-2">
            <h2 className="text-lg font-semibold text-slate-100">Assalam-o-Alaikum! NOVA mein khush aamdeed.</h2>
            <p className="text-sm text-slate-300">
              Chand aasaan sawal: NOVA Windows ke sath kaise start ho, aur local AI model tayyar hai ya nahi. Sab kuch isi PC
              par rehta hai. Baad mein ⚙ Settings se sab badal sakte hain.
            </p>
          </div>
        )}

        {step === 1 && (
          <div className="flex flex-col gap-3">
            <h2 className="text-base font-semibold text-slate-100">Windows start hone par</h2>
            <label className="flex items-center gap-2 text-sm text-slate-200">
              <input type="checkbox" checked={startWithWindows} onChange={(e) => setStartWithWindows(e.target.checked)} />
              NOVA ko Windows ke sath start karein
            </label>
            {startWithWindows && (
              <div className="flex flex-col gap-2 pl-6">
                <label className="flex items-start gap-2">
                  <input type="radio" name="mode" className="mt-1" checked={mode === "silent"} onChange={() => setMode("silent")} />
                  <span className="flex flex-col">
                    <span className="text-sm text-slate-200">Silent</span>
                    <span className="text-xs text-slate-500">
                      Background (tray) mein chupchaap — "{settings.wake_word}" kehne par sunta hai. Is ke liye mic hamesha
                      khula rahega (sirf wake word ke baad wali baat command banti hai).
                    </span>
                  </span>
                </label>
                <label className="flex items-start gap-2">
                  <input type="radio" name="mode" className="mt-1" checked={mode === "active"} onChange={() => setMode("active")} />
                  <span className="flex flex-col">
                    <span className="text-sm text-slate-200">Active</span>
                    <span className="text-xs text-slate-500">Window khulti hai aur NOVA kehta hai: "Assalam-o-Alaikum. NOVA online hai."</span>
                  </span>
                </label>
              </div>
            )}
            <label className="flex items-start gap-2 text-sm text-slate-200">
              <input
                type="checkbox"
                className="mt-1"
                checked={listensAfterSetup(micOn, startWithWindows, mode)}
                disabled={startWithWindows && mode === "silent"}
                onChange={(e) => setMicOn(e.target.checked)}
              />
              <span className="flex flex-col">
                <span>Mic hamesha on — "{settings.wake_word}" kehne par sune</span>
                <span className="text-xs text-slate-500">
                  Sirf "{settings.wake_word}" ke baad wali baat command banti hai; baqi na save hoti hai na dikhai jati hai.
                  Mic button se kabhi bhi band kar sakte hain.
                </span>
              </span>
            </label>
            {!packaged && (
              <p className="text-xs text-amber-300">Ye development copy hai — Windows ke sath start sirf installed NOVA mein lagta hai.</p>
            )}
          </div>
        )}

        {step === 2 && (
          <div className="flex flex-col gap-3">
            <h2 className="text-base font-semibold text-slate-100">Local AI (Ollama)</h2>
            <p className="text-xs text-slate-400">
              NOVA AI model ke baghair bhi seedhi commands samajhta hai; sawalon ke jawab aur mushkil jumlon ke liye local AI
              chahiye (internet par kuch nahi jata).
            </p>
            {!status ? (
              <p className="text-sm text-slate-400">Check ho raha hai...</p>
            ) : (
              <ul className="flex flex-col gap-1">
                <Check ok={!!ollama?.installed}>Ollama {ollama?.installed ? "install hai" : "install nahi"}</Check>
                <Check ok={!!ollama?.reachable}>Ollama {ollama?.reachable ? "chal raha hai" : "nahi chal raha"}</Check>
                <Check ok={!!ollama?.model_ready}>
                  Model {ollama?.model} {ollama?.model_ready ? "tayyar" : "download nahi hua (~2.5 GB)"}
                </Check>
              </ul>
            )}
            {progress && (
              <div className="flex flex-col gap-1">
                <div className="h-2 overflow-hidden rounded bg-white/10">
                  <div className="h-full bg-sky-400 transition-all" style={{ width: `${progress.percent ?? (progress.done ? 100 : 5)}%` }} />
                </div>
                <span className={`text-xs ${progress.done && !progress.ok ? "text-red-300" : "text-slate-400"}`}>{progress.message}</span>
              </div>
            )}
            <div className="flex flex-wrap gap-2">
              {status && !ollama?.installed && (
                <button type="button" className={secondary} onClick={() => window.open(OLLAMA_DOWNLOAD)}>
                  Ollama download page kholo
                </button>
              )}
              {ollama?.reachable && !ollama.model_ready && (
                <button type="button" className={secondary} disabled={pulling} onClick={() => void pull()}>
                  {pulling ? "Download ho raha hai..." : `${ollama.model} download karein`}
                </button>
              )}
              <button type="button" className={secondary} onClick={() => void refresh()}>
                Dobara check
              </button>
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="flex flex-col gap-3">
            <h2 className="text-base font-semibold text-slate-100">Awaaz</h2>
            <ul className="flex flex-col gap-1">
              <Check ok={!!voice?.whisper}>Awaaz pehchanne ka model (Whisper) {voice?.whisper ? "maujood" : "nahi mila"}</Check>
              <Check ok={!!voice?.piper}>Urdu awaaz (Piper) {voice?.piper ? "maujood" : "nahi mili"}</Check>
            </ul>
            <p className="text-xs text-slate-400">
              Mic ka button neeche hai. Pehli dafa Windows mic ki ijazat maang sakta hai. Awaaz PC se bahar nahi jati.
            </p>
          </div>
        )}

        {step === 4 && (
          <div className="flex flex-col gap-2">
            <h2 className="text-base font-semibold text-slate-100">Tayyar!</h2>
            <ul className="flex flex-col gap-1">
              <Check ok>{startWithWindows ? `Windows ke sath start: ${mode === "silent" ? "Silent" : "Active"}` : "Windows ke sath khud start nahi"}</Check>
              <Check ok>
                {listensAfterSetup(micOn, startWithWindows, mode)
                  ? `Mic on — "${settings.wake_word}" kahein`
                  : "Mic button se (khud nahi sunega)"}
              </Check>
              <Check ok={!!ollama?.model_ready}>{ollama?.model_ready ? "Local AI tayyar" : "Local AI baad mein (Settings → AI brain)"}</Check>
              <Check ok={!!voice?.whisper && !!voice?.piper}>Awaaz</Check>
            </ul>
            <p className="text-xs text-slate-400">Kahein ya likhein: "Chrome kholo", "RAM batao", "work start karo".</p>
          </div>
        )}

        {error && <p className="text-xs text-red-300">{error}</p>}
        <div className="flex items-center justify-between gap-2">
          <button type="button" className="text-xs text-slate-500 hover:text-slate-300" disabled={saving} onClick={() => void finish(true)}>
            Abhi nahi
          </button>
          <div className="flex gap-2">
            {step > 0 && (
              <button type="button" className={secondary} onClick={() => go(step - 1)}>
                Peeche
              </button>
            )}
            {step < STEPS.length - 1 ? (
              <button key="next" type="button" className={primary} onClick={() => go(step + 1)}>
                Aage
              </button>
            ) : (
              <button
                key="finish"
                type="button"
                className={primary}
                disabled={saving}
                onClick={() => settled() && void finish(false)}
              >
                {saving ? "Save ho raha hai..." : "Shuru karein"}
              </button>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}
