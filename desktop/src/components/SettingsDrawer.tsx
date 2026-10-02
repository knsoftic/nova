import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { api, fieldErrors } from "../lib/api";
import type { NovaState, UserSettings } from "../lib/types";
import { STATE_META } from "../lib/ui";

interface Props {
  open: boolean;
  settings: UserSettings | null;
  onClose: () => void;
  onPreviewState: (state: NovaState) => void;
}

function Field({ label, hint, error, children }: { label: string; hint?: string; error?: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs font-medium text-slate-300">{label}</span>
      {children}
      {error ? <span className="text-xs text-red-300">{error}</span> : hint && <span className="text-xs text-slate-500">{hint}</span>}
    </label>
  );
}

const inputClass =
  "rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm text-slate-100 outline-none focus:border-sky-500/60";

export function SettingsDrawer({ open, settings, onClose, onPreviewState }: Props) {
  const [draft, setDraft] = useState<UserSettings | null>(settings);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  // Reset the form each time the drawer opens. Not on every settings change, or our own save
  // (echoed back as SETTINGS_CHANGED) would wipe the "saved" confirmation.
  const [wasOpen, setWasOpen] = useState(false);
  if (open !== wasOpen) {
    setWasOpen(open);
    if (open) {
      setDraft(settings);
      setErrors({});
      setSaved(false);
    }
  }
  if (open && !draft && settings) setDraft(settings);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const save = async (e: FormEvent) => {
    e.preventDefault();
    if (!draft) return;
    // Send only what changed, so the activity log records exactly what the user edited.
    const patch = Object.fromEntries(
      (Object.keys(draft) as (keyof UserSettings)[])
        .filter((k) => !settings || draft[k] !== settings[k])
        .map((k) => [k, draft[k]]),
    ) as Partial<UserSettings>;
    if (Object.keys(patch).length === 0) {
      setSaved(true);
      return;
    }
    setSaving(true);
    setErrors({});
    try {
      await api.updateSettings(patch);
      setSaved(true);
    } catch (err) {
      const fe = fieldErrors(err);
      setErrors(Object.keys(fe).length ? fe : { form: "Settings save nahi ho sakin. Backend connected hai?" });
    } finally {
      setSaving(false);
    }
  };

  const set = <K extends keyof UserSettings>(key: K, value: UserSettings[K]) => {
    setSaved(false);
    setDraft((d) => (d ? { ...d, [key]: value } : d));
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/50" onClick={onClose}>
      <aside
        role="dialog"
        aria-modal="true"
        aria-label="Settings"
        onClick={(e) => e.stopPropagation()}
        className="flex h-full w-[420px] flex-col gap-5 overflow-y-auto border-l border-white/10 bg-slate-950 p-5"
      >
        <div className="flex items-center justify-between">
          <h2 className="font-mono text-sm uppercase tracking-[0.2em] text-slate-300">Settings</h2>
          <button type="button" onClick={onClose} className="text-slate-400 hover:text-slate-100" aria-label="Band karein">
            ✕
          </button>
        </div>

        {!draft ? (
          <p className="text-sm text-slate-400">Settings load ho rahi hain...</p>
        ) : (
          <form onSubmit={save} className="flex flex-col gap-4">
            <Field label="Assistant ka naam" hint="Default: NOVA. Urdu naam bhi chal sakta hai." error={errors.assistant_name}>
              <input
                className={inputClass}
                value={draft.assistant_name}
                maxLength={24}
                onChange={(e) => set("assistant_name", e.target.value)}
              />
            </Field>
            <Field
              label="Wake word"
              hint='Text commands ke shuru mein bhi pehchana jata hai. Awaaz se "Hey NOVA" Phase 5 mein.'
              error={errors.wake_word}
            >
              <input
                className={inputClass}
                value={draft.wake_word}
                maxLength={40}
                onChange={(e) => set("wake_word", e.target.value)}
              />
            </Field>
            <label className="flex items-start gap-3">
              <input
                type="checkbox"
                className="mt-1"
                checked={draft.continuous_listening}
                onChange={(e) => set("continuous_listening", e.target.checked)}
              />
              <span className="flex flex-col">
                <span className="text-xs font-medium text-slate-300">Continuous listening</span>
                <span className="text-xs text-slate-500">
                  Setting save hogi; mic ko lagatar sun'ne ka kaam Phase 5 (voice) mein shuru hoga.
                </span>
              </span>
            </label>
            <fieldset className="flex flex-col gap-2">
              <legend className="mb-1 text-xs font-medium text-slate-300">Windows startup mode</legend>
              {(
                [
                  ["active", "Active — window khule aur salam kare"],
                  ["silent", 'Silent — background mein "Hey NOVA" ka intezar'],
                ] as const
              ).map(([value, label]) => (
                <label key={value} className="flex items-center gap-2 text-sm text-slate-200">
                  <input
                    type="radio"
                    name="startup_mode"
                    checked={draft.startup_mode === value}
                    onChange={() => set("startup_mode", value)}
                  />
                  {label}
                </label>
              ))}
              <span className="text-xs text-slate-500">Windows ke sath auto-start Phase 12 (installer) mein lagega.</span>
            </fieldset>

            {errors.form && <p className="text-xs text-red-300">{errors.form}</p>}
            <div className="flex items-center gap-3">
              <button
                type="submit"
                disabled={saving}
                className="rounded-lg bg-sky-500 px-4 py-2 text-sm font-medium text-slate-950 hover:bg-sky-400 disabled:opacity-50"
              >
                {saving ? "Save ho raha hai..." : "Save karein"}
              </button>
              {saved && <span className="text-xs text-emerald-300">Save ho gaya ✓</span>}
            </div>
          </form>
        )}

        <section className="flex flex-col gap-2 border-t border-white/10 pt-4">
          <h3 className="text-xs font-medium text-slate-300">Avatar states (admin preview)</h3>
          <p className="text-xs text-slate-500">
            Sirf UI preview hai — backend ko kuch nahi bheja jata. Har state 4 second dikhegi.
          </p>
          <div className="grid grid-cols-3 gap-1.5">
            {(Object.keys(STATE_META) as NovaState[]).map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => onPreviewState(s)}
                className="rounded-md border border-white/10 px-2 py-1.5 text-[10px] font-mono tracking-wide transition hover:bg-white/5"
                style={{ color: STATE_META[s].color }}
              >
                {s.replaceAll("_", " ")}
              </button>
            ))}
          </div>
        </section>
      </aside>
    </div>
  );
}
