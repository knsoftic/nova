import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { api, fieldErrors } from "../lib/api";
import type {
  AiMode,
  AiStatus,
  Contact,
  FileRoot,
  NovaState,
  OpenAIStatus,
  PermissionRule,
  SetupStatus,
  UserSettings,
  VoiceStatus,
  WebStatus,
} from "../lib/types";
import { STATE_META, showPhone } from "../lib/ui";

interface Props {
  open: boolean;
  settings: UserSettings | null;
  aiStatus: AiStatus | null;
  onRefreshAi: () => void;
  onClose: () => void;
  onPreviewState: (state: NovaState) => void;
}

const AI_MODES: { value: AiMode; label: string; hint: string }[] = [
  { value: "hybrid", label: "Hybrid (tajweez)", hint: "Seedhi commands rules se fauran, sawal aur mushkil jumle local AI se." },
  { value: "llm", label: "Sirf local AI", hint: "Har command AI model samjhega — zyada samajhdar, lekin CPU par slow." },
  { value: "rules", label: "Sirf rules", hint: "AI model istemal nahi hoga. Sab se tez, lekin sawalon ke jawab nahi." },
];

function AiStatusLine({ status }: { status: AiStatus | null }) {
  if (!status) return <span className="text-xs text-slate-500">Status maloom nahi.</span>;
  if (!status.ollama.reachable)
    return <span className="text-xs text-amber-300">Ollama nahi chal raha — NOVA rules se kaam karega.</span>;
  if (!status.model_ready)
    return (
      <span className="text-xs text-amber-300">
        Model "{status.model}" install nahi. Terminal mein chalayein: ollama pull {status.model}
      </span>
    );
  return (
    <span className="text-xs text-emerald-300">
      Ollama {status.ollama.version} · {status.model} tayyar
      {status.last_latency_ms !== null && ` · aakhri jawab ${(status.last_latency_ms / 1000).toFixed(1)}s`}
    </span>
  );
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

const SPEAK_MODES: { value: UserSettings["speak_responses"]; label: string }[] = [
  { value: "voice_only", label: "Sirf awaaz wali commands ka jawab bolein" },
  { value: "always", label: "Har jawab bolein" },
  { value: "never", label: "Kabhi na bolein (sirf likh kar)" },
];

const STT_LANGUAGES: { value: UserSettings["stt_language"]; label: string }[] = [
  { value: "ur", label: "Urdu (tajweez)" },
  { value: "hi", label: "Hindi" },
  { value: "en", label: "English" },
  { value: "auto", label: "Khud pehchane" },
];

const TEST_SENTENCE = "Assalam-o-Alaikum! Main aapki awaaz test kar raha hoon. Kya aap mujhe saaf sun sakte hain?";

/** People NOVA may message. NOVA never searches WhatsApp chats: only these numbers/emails (or typed ones) are used. */
function Contacts({ open }: { open: boolean }) {
  const [contacts, setContacts] = useState<Contact[] | null>(null);
  const [form, setForm] = useState({ name: "", phone: "", email: "" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const load = () => api.contacts().then(setContacts).catch(() => setContacts([]));
  useEffect(() => {
    if (open) void load();
  }, [open]);

  const add = async () => {
    setErrors({});
    try {
      await api.addContact({
        name: form.name.trim(),
        ...(form.phone.trim() ? { phone: form.phone.trim() } : {}),
        ...(form.email.trim() ? { email: form.email.trim() } : {}),
      });
      setForm({ name: "", phone: "", email: "" });
      void load();
    } catch (err) {
      const fe = fieldErrors(err);
      setErrors(Object.keys(fe).length ? fe : { form: "Contact save nahi hua." });
    }
  };

  const remove = async (id: number) => {
    await api.deleteContact(id).catch(() => undefined);
    void load();
  };

  return (
    <section className="flex flex-col gap-2 border-t border-white/10 pt-4">
      <h3 className="text-xs font-medium text-slate-300">Contacts (WhatsApp / email ke liye)</h3>
      <p className="text-xs text-slate-500">
        NOVA sirf inhi ko (ya command mein likhe number/email ko) message bhejta hai — aap ki WhatsApp chats mein khud
        nahi dhoondta. Har message bhejne se pehle poochta hai.
      </p>
      {contacts === null ? (
        <span className="text-xs text-slate-500">Load ho rahe hain...</span>
      ) : contacts.length === 0 ? (
        <span className="text-xs text-slate-500">Abhi koi contact nahi.</span>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {contacts.map((c) => (
            <li key={c.id} className="flex items-center justify-between gap-2 rounded-lg bg-white/[0.03] px-3 py-2">
              <span className="flex min-w-0 flex-col">
                <span className="text-xs text-slate-200">{c.name}</span>
                <span className="truncate font-mono text-[10px] text-slate-500">
                  {[showPhone(c.phone), c.email].filter(Boolean).join(" · ")}
                </span>
              </span>
              <button type="button" onClick={() => void remove(c.id)} className="shrink-0 text-xs text-red-300 hover:text-red-200">
                Hatao
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="grid grid-cols-[1fr_1fr] gap-2">
        <input
          className={`${inputClass} col-span-2 text-xs`}
          placeholder="Naam (maslan Ali)"
          value={form.name}
          maxLength={60}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
        />
        <input
          className={`${inputClass} font-mono text-xs`}
          placeholder="0300 1234567"
          value={form.phone}
          maxLength={30}
          onChange={(e) => setForm({ ...form, phone: e.target.value })}
        />
        <input
          className={`${inputClass} text-xs`}
          placeholder="email (ikhtiyari)"
          value={form.email}
          maxLength={120}
          onChange={(e) => setForm({ ...form, email: e.target.value })}
        />
      </div>
      {(errors.phone || errors.email || errors.name || errors.form) && (
        <span className="text-xs text-red-300">{errors.phone || errors.email || errors.name || errors.form}</span>
      )}
      <button
        type="button"
        onClick={() => void add()}
        disabled={!form.name.trim() || (!form.phone.trim() && !form.email.trim())}
        className="self-start rounded-lg border border-sky-500/40 px-3 py-1.5 text-xs text-sky-200 hover:bg-sky-500/10 disabled:opacity-40"
      >
        Contact add karein
      </button>
    </section>
  );
}

/** Approvals the user chose to remember ("don't ask again"), with a way to take them back. */
function PermissionRules({ open }: { open: boolean }) {
  const [rules, setRules] = useState<PermissionRule[] | null>(null);
  const load = () => api.permissionRules().then(setRules).catch(() => setRules([]));
  useEffect(() => {
    if (open) void load();
  }, [open]);

  const remove = async (id: number) => {
    await api.deletePermissionRule(id).catch(() => undefined);
    void load();
  };

  return (
    <section className="flex flex-col gap-2 border-t border-white/10 pt-4">
      <h3 className="text-xs font-medium text-slate-300">Yaad rakhi gayi ijazatein</h3>
      <p className="text-xs text-slate-500">
        In kaamon ke liye NOVA dobara nahi poochta. Khatarnak (high risk) kaam kabhi yaad nahi rakhe jate.
      </p>
      {rules === null ? (
        <span className="text-xs text-slate-500">Load ho rahi hain...</span>
      ) : rules.length === 0 ? (
        <span className="text-xs text-slate-500">Koi nahi — NOVA har dafa poochta hai.</span>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {rules.map((r) => (
            <li key={r.id} className="flex items-center justify-between gap-2 rounded-lg bg-white/[0.03] px-3 py-2">
              <span className="flex flex-col">
                <span className="text-xs text-slate-200">{r.description}</span>
                <span className="font-mono text-[10px] text-slate-500">
                  {r.scope} · {r.uses} dafa istemal
                </span>
              </span>
              <button
                type="button"
                onClick={() => void remove(r.id)}
                className="shrink-0 text-xs text-red-300 hover:text-red-200"
              >
                Hatao
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function VoiceSettings({
  draft,
  set,
  errors,
  open,
}: {
  draft: UserSettings;
  set: <K extends keyof UserSettings>(key: K, value: UserSettings[K]) => void;
  errors: Record<string, string>;
  open: boolean;
}) {
  const [status, setStatus] = useState<VoiceStatus | null>(null);
  const [testing, setTesting] = useState<string | null>(null);

  useEffect(() => {
    if (open) api.voiceStatus().then(setStatus).catch(() => setStatus(null));
  }, [open]);

  const test = async () => {
    setTesting("Bol raha hai...");
    try {
      await api.speak(TEST_SENTENCE); // playback starts via the NOVA_SPEAK event
      setTesting(null);
    } catch {
      setTesting("Awaaz test nahi ho saki — voice model check karein.");
    }
  };

  const voices = status?.tts.voices ?? [];
  return (
    <fieldset className="flex flex-col gap-3 border-t border-white/10 pt-4">
      <legend className="mb-1 text-xs font-medium text-slate-300">Awaaz (local — audio PC se bahar nahi jata)</legend>
      {status && (
        <span className={`text-xs ${status.stt.downloaded && status.tts.available ? "text-emerald-300" : "text-amber-300"}`}>
          {status.stt.downloaded ? `Sun'na: whisper ${status.stt.model}${status.stt.loaded ? " (tayyar)" : ""}` : "Whisper model download nahi hua"}
          {" · "}
          {status.tts.available ? "Bolna: tayyar" : "Urdu voice download nahi hui"}
        </span>
      )}
      <Field label="Bolne wali zaban (sun'ne ke liye)" error={errors.stt_language}>
        <select
          className={inputClass}
          value={draft.stt_language}
          onChange={(e) => set("stt_language", e.target.value as UserSettings["stt_language"])}
        >
          {STT_LANGUAGES.map((l) => (
            <option key={l.value} value={l.value}>
              {l.label}
            </option>
          ))}
        </select>
      </Field>
      <Field label="NOVA ki awaaz" error={errors.tts_voice}>
        <select className={inputClass} value={draft.tts_voice} onChange={(e) => set("tts_voice", e.target.value)}>
          {[...new Map([[draft.tts_voice, draft.tts_voice], ...voices.map((v) => [v.id, v.label] as [string, string])])].map(
            ([id, label]) => (
              <option key={id} value={id}>
                {label}
              </option>
            ),
          )}
        </select>
      </Field>
      <div className="flex flex-col gap-1.5">
        {SPEAK_MODES.map((m) => (
          <label key={m.value} className="flex items-center gap-2 text-sm text-slate-200">
            <input
              type="radio"
              name="speak_responses"
              checked={draft.speak_responses === m.value}
              onChange={() => set("speak_responses", m.value)}
            />
            {m.label}
          </label>
        ))}
      </div>
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={test}
          disabled={!status?.tts.available}
          className="rounded-lg border border-sky-500/40 px-3 py-1.5 text-xs text-sky-200 hover:bg-sky-500/10 disabled:opacity-40"
        >
          🔊 Awaaz test karein
        </button>
        <span className="text-xs text-slate-500">{testing ?? "Abhi wali (save ki hui) awaaz se bolega."}</span>
      </div>
    </fieldset>
  );
}

/** OpenAI (optional): a write-only key, and where speech/understanding happen. Without a key everything stays local. */
function OpenAISettings({
  draft,
  set,
  errors,
  open,
}: {
  draft: UserSettings;
  set: <K extends keyof UserSettings>(key: K, value: UserSettings[K]) => void;
  errors: Record<string, string>;
  open: boolean;
}) {
  const [status, setStatus] = useState<OpenAIStatus | null>(null);
  const [key, setKey] = useState("");
  const [note, setNote] = useState<{ text: string; ok: boolean } | null>(null);
  const [busy, setBusy] = useState(false);

  const load = () => api.openaiStatus().then(setStatus).catch(() => setStatus(null));
  useEffect(() => {
    if (open) {
      setKey("");
      setNote(null);
      void load();
    }
  }, [open]);

  const saveKey = async () => {
    if (!key.trim() || busy) return;
    setBusy(true);
    try {
      const r = await api.setSecret("openai_api_key", key.trim());
      setKey("");
      const test = await api.openaiTest();
      setNote({ text: `Key save ho gayi (${r.masked}) — ${test.message}`, ok: test.ok });
      void load();
    } catch {
      setNote({ text: "Key save nahi hui — format check karein (sirf letters, numbers, - _ .).", ok: false });
    } finally {
      setBusy(false);
    }
  };

  const removeKey = async () => {
    setBusy(true);
    await api.deleteSecret("openai_api_key").catch(() => undefined);
    setNote({ text: "Key hata di — awaaz aur AI ab sirf is PC par (local).", ok: true });
    setBusy(false);
    void load();
  };

  const test = async () => {
    setBusy(true);
    try {
      const r = await api.openaiTest();
      setNote({ text: r.message, ok: r.ok });
    } catch {
      setNote({ text: "Test nahi ho saka.", ok: false });
    } finally {
      setBusy(false);
    }
  };

  return (
    <fieldset className="flex flex-col gap-3 border-t border-white/10 pt-4">
      <legend className="mb-1 text-xs font-medium text-slate-300">OpenAI (tez awaaz aur AI)</legend>
      {status && (
        <span className={`text-xs ${status.configured ? "text-emerald-300" : "text-slate-400"}`}>
          {status.configured
            ? `Key ${status.key_masked} · awaaz: ${status.stt_active === "openai" ? `OpenAI (${status.stt_model})` : "local Whisper"} · AI: ${status.llm_active === "openai" ? `OpenAI (${status.llm_model})` : "local"}`
            : "Key nahi — awaaz aur AI is PC par (local) chal rahe hain."}
        </span>
      )}
      {(status?.stt_error || status?.llm_error) && (
        <span className="text-xs text-amber-300">
          Aakhri masla: {status.stt_error || status.llm_error} — us waqt local se kaam hua.
        </span>
      )}
      <Field
        label="OpenAI API key"
        hint="platform.openai.com → API keys. Encrypted save hoti hai, dobara dikhai nahi jati. Istemal ka kharcha aap ke OpenAI account par."
      >
        <div className="flex gap-2">
          <input
            type="password"
            className={`${inputClass} min-w-0 flex-1`}
            value={key}
            placeholder={status?.configured ? "Nayi key se badlein" : "sk-... yahan paste karein"}
            autoComplete="off"
            spellCheck={false}
            maxLength={200}
            onChange={(e) => setKey(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault(); // not the settings form's submit
                void saveKey();
              }
            }}
          />
          <button
            type="button"
            onClick={() => void saveKey()}
            disabled={!key.trim() || busy}
            className="shrink-0 rounded-lg border border-sky-500/40 px-3 text-xs text-sky-200 hover:bg-sky-500/10 disabled:opacity-40"
          >
            Save key
          </button>
          {status?.configured && (
            <>
              <button
                type="button"
                onClick={() => void test()}
                disabled={busy}
                className="shrink-0 rounded-lg border border-white/10 px-3 text-xs text-slate-200 hover:bg-white/5 disabled:opacity-40"
              >
                Test
              </button>
              <button
                type="button"
                onClick={() => void removeKey()}
                disabled={busy}
                className="shrink-0 text-xs text-red-300 hover:text-red-200 disabled:opacity-40"
              >
                Hatao
              </button>
            </>
          )}
        </div>
      </Field>
      {note && <span className={`text-xs ${note.ok ? "text-emerald-300" : "text-red-300"}`}>{note.text}</span>}
      <Field
        label="Awaaz ko text kaun banaye"
        hint="Auto: key ho to OpenAI (~1s), warna is PC ka Whisper (~3s). OpenAI na mile to khud local par aa jata hai."
        error={errors.stt_engine}
      >
        <select
          className={inputClass}
          value={draft.stt_engine}
          onChange={(e) => set("stt_engine", e.target.value as UserSettings["stt_engine"])}
        >
          <option value="auto">Auto (key ho to OpenAI)</option>
          <option value="openai">OpenAI</option>
          <option value="local">Sirf is PC par (Whisper)</option>
        </select>
      </Field>
      <Field label="AI brain" hint="Mushkil jumle aur sawal. Seedhi commands hamesha foran (rules) se." error={errors.llm_provider}>
        <select
          className={inputClass}
          value={draft.llm_provider}
          onChange={(e) => set("llm_provider", e.target.value as UserSettings["llm_provider"])}
        >
          <option value="auto">Auto (key ho to OpenAI)</option>
          <option value="openai">OpenAI</option>
          <option value="ollama">Sirf is PC par (Ollama)</option>
        </select>
      </Field>
      <div className="grid grid-cols-2 gap-2">
        <Field label="Chat model" error={errors.openai_model}>
          <input className={inputClass} value={draft.openai_model} onChange={(e) => set("openai_model", e.target.value)} />
        </Field>
        <Field label="Awaaz model" error={errors.openai_stt_model}>
          <input
            className={inputClass}
            value={draft.openai_stt_model}
            onChange={(e) => set("openai_stt_model", e.target.value)}
          />
        </Field>
      </div>
      {status?.configured && draft.stt_engine !== "local" && (
        <span className="text-[11px] text-amber-200/80">
          Privacy: awaaz internet par OpenAI ko jati hai — "Mic hamesha on" mein har suni hui awaaz (jo "Hey NOVA" ke
          baghair ho wo bhi). NOVA aisi baat na dikhata hai na save karta hai; OpenAI ki apni data policy lagu hoti hai.
        </span>
      )}
    </fieldset>
  );
}

const SEARCH_ENGINES: { value: UserSettings["search_engine"]; label: string }[] = [
  { value: "google", label: "Google" },
  { value: "bing", label: "Bing" },
  { value: "duckduckgo", label: "DuckDuckGo" },
];

const BROWSER_CHANNELS: { value: UserSettings["browser_channel"]; label: string }[] = [
  { value: "chrome", label: "Google Chrome" },
  { value: "msedge", label: "Microsoft Edge" },
];

/** Browser + web search. The Brave key is write-only: typed here, encrypted by the backend, never shown again. */
function WebSettings({
  draft,
  set,
  errors,
  open,
}: {
  draft: UserSettings;
  set: <K extends keyof UserSettings>(key: K, value: UserSettings[K]) => void;
  errors: Record<string, string>;
  open: boolean;
}) {
  const [status, setStatus] = useState<WebStatus | null>(null);
  const [key, setKey] = useState("");
  const [note, setNote] = useState<{ text: string; ok: boolean } | null>(null);
  const [busy, setBusy] = useState(false);

  const load = () => api.webStatus().then(setStatus).catch(() => setStatus(null));
  useEffect(() => {
    if (open) {
      setKey("");
      setNote(null);
      void load();
    }
  }, [open]);

  const saveKey = async () => {
    if (!key.trim() || busy) return;
    setBusy(true);
    try {
      const r = await api.setSecret("brave_api_key", key.trim());
      setNote({ text: `Key save ho gayi (${r.masked}) — encrypted, sirf is PC par.`, ok: true });
      setKey("");
      void load();
    } catch {
      setNote({ text: "Key save nahi hui — format check karein (sirf letters, numbers, - _ .).", ok: false });
    } finally {
      setBusy(false);
    }
  };

  const removeKey = async () => {
    setBusy(true);
    await api.deleteSecret("brave_api_key").catch(() => undefined);
    setNote({ text: "Key hata di — ab search Wikipedia se hogi.", ok: true });
    setBusy(false);
    void load();
  };

  return (
    <fieldset className="flex flex-col gap-3 border-t border-white/10 pt-4">
      <legend className="mb-1 text-xs font-medium text-slate-300">Web aur browser</legend>
      {status && (
        <span className={`text-xs ${status.brave_configured ? "text-emerald-300" : "text-amber-300"}`}>
          {status.brave_configured
            ? `Search: Brave API (key ${status.brave_key_masked})`
            : "Search: sirf Wikipedia — taza khabron ke liye Brave key daalein."}
        </span>
      )}
      <Field
        label="Brave Search API key"
        hint="brave.com/search/api se free key milti hai. Key encrypted save hoti hai aur dobara dikhai nahi jati."
      >
        <div className="flex gap-2">
          <input
            type="password"
            className={`${inputClass} min-w-0 flex-1`}
            value={key}
            placeholder={status?.brave_configured ? "Nayi key se badlein" : "Key yahan paste karein"}
            autoComplete="off"
            spellCheck={false}
            maxLength={200}
            onChange={(e) => setKey(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault(); // not the settings form's submit
                void saveKey();
              }
            }}
          />
          <button
            type="button"
            onClick={() => void saveKey()}
            disabled={!key.trim() || busy}
            className="shrink-0 rounded-lg border border-sky-500/40 px-3 text-xs text-sky-200 hover:bg-sky-500/10 disabled:opacity-40"
          >
            Save key
          </button>
          {status?.brave_configured && (
            <button
              type="button"
              onClick={() => void removeKey()}
              disabled={busy}
              className="shrink-0 text-xs text-red-300 hover:text-red-200 disabled:opacity-40"
            >
              Hatao
            </button>
          )}
        </div>
      </Field>
      {note && <span className={`text-xs ${note.ok ? "text-emerald-300" : "text-red-300"}`}>{note.text}</span>}
      <Field label="Browser mein search engine" hint='"YouTube search karo" jaisi commands ke liye.' error={errors.search_engine}>
        <select
          className={inputClass}
          value={draft.search_engine}
          onChange={(e) => set("search_engine", e.target.value as UserSettings["search_engine"])}
        >
          {SEARCH_ENGINES.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </select>
      </Field>
      <Field
        label="NOVA ka browser"
        hint="NOVA apni alag profile istemal karta hai — aap ke passwords aur cookies use nahi hote. Badalne ka asar agli dafa browser khulne par hoga."
        error={errors.browser_channel}
      >
        <select
          className={inputClass}
          value={draft.browser_channel}
          onChange={(e) => set("browser_channel", e.target.value as UserSettings["browser_channel"])}
        >
          {BROWSER_CHANNELS.map((b) => (
            <option key={b.value} value={b.value}>
              {b.label}
            </option>
          ))}
        </select>
      </Field>
    </fieldset>
  );
}

/** Which NOVA this is (installed or development), where it keeps data, and whether Windows starts it. */
function AboutInstall({ open }: { open: boolean }) {
  const [status, setStatus] = useState<SetupStatus | null>(null);
  useEffect(() => {
    if (open) api.setupStatus().then(setStatus).catch(() => setStatus(null));
  }, [open]);
  if (!status) return null;
  const i = status.install;
  const rows: [string, string][] = [
    ["Version", `${i.version} (${i.packaged ? "installed" : "development copy"})`],
    ["Program", i.program_dir],
    ["Data (yaadein, history...)", i.data_dir],
    ["Voice models", i.models_dir],
    ["Python", i.python],
    ["Windows ke sath start", i.startup_registered ? "registered" : "nahi"],
  ];
  return (
    <section className="flex flex-col gap-2 border-t border-white/10 pt-4">
      <h3 className="text-xs font-medium text-slate-300">NOVA ke baare mein</h3>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
        {rows.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-slate-500">{k}</dt>
            <dd className="break-all font-mono text-[11px] text-slate-300">{v}</dd>
          </div>
        ))}
      </dl>
      {i.packaged && window.nova?.openFolder && (
        <div className="flex gap-3 text-xs">
          <button type="button" className="text-sky-300 hover:text-sky-200" onClick={() => void window.nova?.openFolder?.("data")}>
            Data folder kholo
          </button>
          <button type="button" className="text-sky-300 hover:text-sky-200" onClick={() => void window.nova?.openFolder?.("program")}>
            Program folder kholo
          </button>
        </div>
      )}
    </section>
  );
}

const REPLY_STYLES:{ value: UserSettings["reply_style"]; label: string; hint: string }[] = [
  { value: "auto", label: "Khud adapt (tajweez)", hint: "Aam tor par normal; jaldi/pareshani mein chhote, uljhan mein misaal ke sath." },
  { value: "short", label: "Hamesha chhote", hint: "Mukhtasar jawab; verify ka nishan (✓) phir bhi rehta hai." },
  { value: "detailed", label: "Hamesha tafseel se", hint: "Poori wazahat ke sath." },
];

const BEHAVIOR_TOGGLES: { key: "emotion_awareness" | "voice_signals" | "show_estimate" | "learn_patterns" | "suggest_routines"; label: string; hint: string }[] = [
  {
    key: "emotion_awareness",
    label: "Andaza lagayein (pareshan, jaldi mein, uljhan...)",
    hint: "Alfaaz aur baat-cheet se — sirf andaza, kabhi pakki baat nahi. Kahin save nahi hota.",
  },
  {
    key: "voice_signals",
    label: "Awaaz se bhi (raftaar, zor, pitch)",
    hint: "Usi waqt PC par hisaab; awaaz ya ye numbers save nahi hote.",
  },
  { key: "show_estimate", label: "Andaza dikhayein", hint: "\"Andaza: shayad jaldi mein\" label aur Live Activity mein wajah." },
  {
    key: "learn_patterns",
    label: "Aadatein seekhein",
    hint: "Kaun si apps/websites/projects kab kholte hain — isi PC par, history ki tarah mit jati hain (Memory → Aadatein).",
  },
  { key: "suggest_routines", label: "Routine dikhe to workflow ki tajweez", hint: "Sirf aap ke \"haan\" par workflow banta hai." },
];

/** Tone and habits (Phase 10). Saved with the rest of the form. */
function BehaviorSettings({
  draft,
  set,
}: {
  draft: UserSettings;
  set: <K extends keyof UserSettings>(key: K, value: UserSettings[K]) => void;
}) {
  return (
    <fieldset className="flex flex-col gap-2 border-t border-white/10 pt-4">
      <legend className="mb-1 text-xs font-medium text-slate-300">Andaz aur aadatein</legend>
      {REPLY_STYLES.map((s) => (
        <label key={s.value} className="flex items-start gap-2">
          <input
            type="radio"
            name="reply_style"
            className="mt-1"
            checked={draft.reply_style === s.value}
            onChange={() => set("reply_style", s.value)}
          />
          <span className="flex flex-col">
            <span className="text-sm text-slate-200">{s.label}</span>
            <span className="text-xs text-slate-500">{s.hint}</span>
          </span>
        </label>
      ))}
      {BEHAVIOR_TOGGLES.map((t) => (
        <label key={t.key} className="flex items-start gap-3">
          <input
            type="checkbox"
            className="mt-1"
            checked={draft[t.key]}
            disabled={
              (t.key === "voice_signals" || t.key === "show_estimate") && !draft.emotion_awareness
                ? true
                : t.key === "suggest_routines" && !draft.learn_patterns
            }
            onChange={(e) => set(t.key, e.target.checked)}
          />
          <span className="flex flex-col">
            <span className="text-xs font-medium text-slate-300">{t.label}</span>
            <span className="text-xs text-slate-500">{t.hint}</span>
          </span>
        </label>
      ))}
    </fieldset>
  );
}

/** Where the File and Coding agents may work. Project folders are saved with the rest of the form. */
function FileSettings({
  draft,
  set,
  errors,
  open,
}: {
  draft: UserSettings;
  set: <K extends keyof UserSettings>(key: K, value: UserSettings[K]) => void;
  errors: Record<string, string>;
  open: boolean;
}) {
  const [roots, setRoots] = useState<FileRoot[] | null>(null);
  const [adding, setAdding] = useState("");

  useEffect(() => {
    if (open) api.fileRoots().then(setRoots).catch(() => setRoots(null));
  }, [open]);

  const add = () => {
    const path = adding.trim().replace(/^"|"$/g, "");
    if (!path) return;
    if (!draft.project_folders.some((p) => p.toLowerCase() === path.toLowerCase())) {
      set("project_folders", [...draft.project_folders, path]);
    }
    setAdding("");
  };

  const userFolders = roots?.filter((r) => r.kind === "folder") ?? [];
  return (
    <fieldset className="flex flex-col gap-3 border-t border-white/10 pt-4">
      <legend className="mb-1 text-xs font-medium text-slate-300">Files aur code projects</legend>
      <span className="text-xs text-slate-500">
        NOVA sirf in folders mein kaam karta hai. Delete hamesha Recycle Bin mein jata hai; .env, keys aur NOVA ki
        apni files kabhi nahi chhui jatin.
      </span>
      {userFolders.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {userFolders.map((r) => (
            <span key={r.path} title={r.path} className="rounded-md bg-white/[0.05] px-2 py-0.5 text-[11px] text-slate-300">
              {r.name}
            </span>
          ))}
        </div>
      )}
      <div className="flex flex-col gap-1">
        <span className="text-xs font-medium text-slate-300">Project folders</span>
        <ul className="flex flex-col gap-1">
          {draft.project_folders.map((p) => (
            <li key={p} className="flex items-center justify-between gap-2 rounded-lg bg-white/[0.03] px-3 py-1.5">
              <span className="truncate font-mono text-xs text-slate-200" title={p}>
                {p}
              </span>
              <button
                type="button"
                onClick={() => set("project_folders", draft.project_folders.filter((x) => x !== p))}
                className="shrink-0 text-xs text-red-300 hover:text-red-200"
              >
                Hatao
              </button>
            </li>
          ))}
          {draft.project_folders.length === 0 && <li className="text-xs text-slate-500">Koi project folder nahi.</li>}
        </ul>
        <div className="flex gap-2">
          <input
            className={`${inputClass} min-w-0 flex-1 font-mono text-xs`}
            value={adding}
            placeholder="C:\Users\...\Projects"
            spellCheck={false}
            onChange={(e) => setAdding(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault(); // not the settings form's submit
                add();
              }
            }}
          />
          <button
            type="button"
            onClick={add}
            disabled={!adding.trim()}
            className="shrink-0 rounded-lg border border-sky-500/40 px-3 text-xs text-sky-200 hover:bg-sky-500/10 disabled:opacity-40"
          >
            Add
          </button>
        </div>
        {errors.project_folders ? (
          <span className="text-xs text-red-300">{errors.project_folders}</span>
        ) : (
          <span className="text-xs text-slate-500">In ke andar har folder ek project hai (maslan C:\xampp\htdocs\nova). Save karein.</span>
        )}
      </div>
    </fieldset>
  );
}

const inputClass =
  "rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm text-slate-100 outline-none focus:border-sky-500/60";

export function SettingsDrawer({ open, settings, aiStatus, onRefreshAi, onClose, onPreviewState }: Props) {
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
              hint="Awaaz aur text dono mein pehchana jata hai. Doosre alfaaz ke sath naam zaroor rakhein (maslan 'Suno Zara')."
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
                  Mic khula rahega aur sirf wake word ke baad wali baat command banegi. Baqi baatein na save hoti
                  hain na dikhai jati hain. Band ho to mic button dabane par ek command suni jati hai.
                </span>
              </span>
            </label>
            <fieldset className="flex flex-col gap-2">
              <legend className="mb-1 text-xs font-medium text-slate-300">Windows startup</legend>
              <label className="flex items-center gap-2 text-sm text-slate-200">
                <input
                  type="checkbox"
                  checked={draft.start_with_windows}
                  onChange={(e) => set("start_with_windows", e.target.checked)}
                />
                Windows ke sath NOVA start ho
              </label>
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
              <span className="text-xs text-slate-500">
                Silent ke liye "Continuous listening" on rakhein. Windows ke sath start sirf installed NOVA mein lagta hai.
              </span>
            </fieldset>

            <VoiceSettings draft={draft} set={set} errors={errors} open={open} />

            <OpenAISettings draft={draft} set={set} errors={errors} open={open} />
            <WebSettings draft={draft} set={set} errors={errors} open={open} />

            <FileSettings draft={draft} set={set} errors={errors} open={open} />

            <BehaviorSettings draft={draft} set={set} />

            <fieldset className="flex flex-col gap-2 border-t border-white/10 pt-4">
              <legend className="mb-1 text-xs font-medium text-slate-300">AI brain (local, PC se bahar kuch nahi jata)</legend>
              {AI_MODES.map((m) => (
                <label key={m.value} className="flex items-start gap-2">
                  <input
                    type="radio"
                    name="ai_mode"
                    className="mt-1"
                    checked={draft.ai_mode === m.value}
                    onChange={() => set("ai_mode", m.value)}
                  />
                  <span className="flex flex-col">
                    <span className="text-sm text-slate-200">{m.label}</span>
                    <span className="text-xs text-slate-500">{m.hint}</span>
                  </span>
                </label>
              ))}
              <Field label="Model" error={errors.ai_model}>
                <select
                  className={inputClass}
                  value={draft.ai_model}
                  disabled={draft.ai_mode === "rules"}
                  onChange={(e) => set("ai_model", e.target.value)}
                >
                  {[...new Set([draft.ai_model, ...(aiStatus?.ollama.models ?? [])])].map((m) => (
                    <option key={m} value={m}>
                      {m}
                      {aiStatus && !aiStatus.ollama.models.includes(m) ? " (install nahi)" : ""}
                    </option>
                  ))}
                </select>
              </Field>
              <div className="flex items-center justify-between gap-2">
                <AiStatusLine status={aiStatus} />
                <button type="button" onClick={onRefreshAi} className="shrink-0 text-xs text-sky-300 hover:text-sky-200">
                  Refresh
                </button>
              </div>
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

        <Contacts open={open} />

        <PermissionRules open={open} />

        <AboutInstall open={open} />

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
