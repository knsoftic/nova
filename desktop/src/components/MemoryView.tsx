import { useEffect, useState, type ReactNode } from "react";
import { api, fieldErrors } from "../lib/api";
import type { HistoryPeriod, HistoryRecord, MemoryFact, ShortTermMemory, UserSettings, Workflow } from "../lib/types";
import { OUTCOME_META, RETENTION_OPTIONS, SLOT_LABEL, STEP_KIND, shortDate, workflowCommand } from "../lib/ui";

type Tab = "facts" | "workflows" | "history" | "short";

const TABS: { id: Tab; label: string }[] = [
  { id: "facts", label: "Yaadein" },
  { id: "workflows", label: "Workflows" },
  { id: "history", label: "History" },
  { id: "short", label: "Abhi ki baat-cheet" },
];

const PERIODS: { value: HistoryPeriod; label: string }[] = [
  { value: "", label: "Sab" },
  { value: "today", label: "Aaj" },
  { value: "yesterday", label: "Kal" },
  { value: "week", label: "7 din" },
  { value: "month", label: "30 din" },
];

const inputClass =
  "rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-xs text-slate-100 outline-none focus:border-sky-500/60";
const buttonClass = "rounded-lg bg-sky-500/20 px-3 py-2 text-xs text-sky-100 hover:bg-sky-500/30 disabled:opacity-40";

/** Deleting is permanent: the button asks once more before doing it. */
function ConfirmButton({ label, question, onConfirm }: { label: string; question: string; onConfirm: () => void }) {
  const [asking, setAsking] = useState(false);
  if (!asking) {
    return (
      <button type="button" onClick={() => setAsking(true)} className="shrink-0 text-xs text-red-300 hover:text-red-200">
        {label}
      </button>
    );
  }
  return (
    <span className="flex shrink-0 items-center gap-2 text-xs">
      <span className="text-slate-400">{question}</span>
      <button
        type="button"
        onClick={() => {
          setAsking(false);
          onConfirm();
        }}
        className="text-red-300 hover:text-red-200"
      >
        Haan
      </button>
      <button type="button" onClick={() => setAsking(false)} className="text-slate-400 hover:text-slate-200">
        Nahi
      </button>
    </span>
  );
}

function Note({ children }: { children: ReactNode }) {
  return <p className="text-xs text-slate-500">{children}</p>;
}

function Facts({ revision }: { revision: number }) {
  const [rows, setRows] = useState<MemoryFact[] | null>(null);
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const load = () => api.memoryFacts().then(setRows).catch(() => setRows([]));
  useEffect(() => {
    void load();
  }, [revision]);

  const add = async () => {
    setError("");
    try {
      await api.addMemoryFact(text.trim());
      setText("");
      void load();
    } catch (err) {
      setError(fieldErrors(err).text ?? "Save nahi hua.");
    }
  };

  return (
    <div className="flex flex-col gap-3">
      <Note>
        NOVA sirf aap ke kehne par ("yaad rakho ke ...") ya aap ke "haan" kehne par yaad rakhta hai — kabhi chupke se nahi.
        Passwords, PIN, card/CNIC numbers kabhi nahi. Sab kuch isi PC par rehta hai.
      </Note>
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (text.trim()) void add();
        }}
      >
        <input
          className={`${inputClass} flex-1`}
          placeholder="Nayi baat, maslan: meri wife ki birthday 5 March ko hai"
          value={text}
          maxLength={300}
          onChange={(e) => setText(e.target.value)}
        />
        <button type="submit" className={buttonClass} disabled={!text.trim()}>
          Yaad rakho
        </button>
      </form>
      {error && <span className="text-xs text-red-300">{error}</span>}
      {rows === null ? (
        <Note>Load ho raha hai...</Note>
      ) : rows.length === 0 ? (
        <Note>Abhi kuch yaad nahi. Kahein "yaad rakho ke ..." ya upar likhein.</Note>
      ) : (
        <>
          <ul className="flex flex-col gap-1.5">
            {rows.map((m) => (
              <li key={m.id} className="flex items-center justify-between gap-3 rounded-lg bg-white/[0.03] px-3 py-2">
                <span className="flex min-w-0 flex-col">
                  <span className="text-sm text-slate-100">{m.text}</span>
                  <span className="text-[10px] text-slate-500">
                    {m.slot && <span className="mr-1.5 rounded bg-sky-500/15 px-1.5 text-sky-200">{SLOT_LABEL[m.slot]}</span>}
                    {shortDate(m.updated_at)} · {m.source === "user_ui" ? "yahan likha" : "aap ne kaha"}
                    {m.uses > 0 && ` · ${m.uses} dafa kaam aayi`}
                  </span>
                </span>
                <ConfirmButton
                  label="Bhool jao"
                  question="Pakka?"
                  onConfirm={() => void api.deleteMemoryFact(m.id).then(load, load)}
                />
              </li>
            ))}
          </ul>
          <div className="flex justify-end">
            <ConfirmButton
              label={`Saari ${rows.length} yaadein mitayein`}
              question="Sab hamesha ke liye mit jayengi. Pakka?"
              onConfirm={() => void api.deleteAllMemoryFacts().then(load, load)}
            />
          </div>
        </>
      )}
    </div>
  );
}

function Workflows({ revision, onRun }: { revision: number; onRun: (command: string) => void }) {
  const [rows, setRows] = useState<Workflow[] | null>(null);
  const [form, setForm] = useState({ name: "", steps: "" });
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const load = () => api.workflows().then(setRows).catch(() => setRows([]));
  useEffect(() => {
    void load();
  }, [revision]);

  const save = async () => {
    setMessage(null);
    try {
      const res = await api.saveWorkflow(form.name.trim(), form.steps.trim());
      setMessage({
        ok: true,
        text: `'${res.workflow.name}' save ho gaya.` + (res.problems.length ? ` Ye nahi mile: ${res.problems.join("; ")}.` : ""),
      });
      setForm({ name: "", steps: "" });
      void load();
    } catch (err) {
      const fe = fieldErrors(err);
      setMessage({ ok: false, text: fe.steps ?? fe.name ?? "Save nahi hua." });
    }
  };

  return (
    <div className="flex flex-col gap-3">
      <Note>
        Pehli dafa "work start karo" kahein — NOVA poochega kya kholna hai aur yaad rakh lega. Workflow mein sirf kholne
        wale kaam hote hain (apps, websites, code projects, folders, volume/brightness).
      </Note>
      {rows === null ? (
        <Note>Load ho rahe hain...</Note>
      ) : rows.length === 0 ? (
        <Note>Abhi koi workflow nahi.</Note>
      ) : (
        <ul className="flex flex-col gap-2">
          {rows.map((w) => (
            <li key={w.id} className="flex flex-col gap-2 rounded-lg bg-white/[0.03] px-3 py-2">
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-medium text-slate-100">
                  {w.name}
                  <span className="ml-2 text-[10px] font-normal text-slate-500">
                    {w.runs ? `${w.runs} dafa chala · aakhri ${shortDate(w.last_run)}` : "abhi chala nahi"}
                  </span>
                </span>
                <span className="flex shrink-0 items-center gap-3">
                  <button type="button" className="text-xs text-sky-300 hover:text-sky-200" onClick={() => onRun(workflowCommand(w.name))}>
                    Chalao
                  </button>
                  <button
                    type="button"
                    className="text-xs text-slate-300 hover:text-slate-100"
                    onClick={() => setForm({ name: w.name, steps: w.steps.map((s) => s.label).join(", ") })}
                  >
                    Badlo
                  </button>
                  <ConfirmButton label="Hatao" question="Pakka?" onConfirm={() => void api.deleteWorkflow(w.id).then(load, load)} />
                </span>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {w.steps.map((s, i) => (
                  <span key={i} className="rounded-md border border-white/10 bg-black/20 px-2 py-0.5 text-[11px] text-slate-300" title={s.value}>
                    <span className="mr-1 text-slate-500">{STEP_KIND[s.kind].icon}</span>
                    {s.label}
                  </span>
                ))}
              </div>
            </li>
          ))}
        </ul>
      )}
      <form
        className="flex flex-col gap-2 border-t border-white/10 pt-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (form.name.trim() && form.steps.trim()) void save();
        }}
      >
        <span className="text-xs font-medium text-slate-300">Naya workflow / badlein</span>
        <input
          className={inputClass}
          placeholder="Naam, maslan: study"
          value={form.name}
          maxLength={30}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
        />
        <input
          className={inputClass}
          placeholder="Kya kholna hai: Chrome, VS Code, github.com, nova project, Downloads folder, volume 30"
          value={form.steps}
          maxLength={600}
          onChange={(e) => setForm({ ...form, steps: e.target.value })}
        />
        <div className="flex items-center justify-between gap-2">
          {message ? (
            <span className={`text-xs ${message.ok ? "text-emerald-300" : "text-red-300"}`}>{message.text}</span>
          ) : (
            <span />
          )}
          <button type="submit" className={buttonClass} disabled={!form.name.trim() || !form.steps.trim()}>
            Save
          </button>
        </div>
      </form>
    </div>
  );
}

function History({
  revision,
  historyDays,
  onRetention,
}: {
  revision: number;
  historyDays: UserSettings["history_days"];
  onRetention: (days: UserSettings["history_days"]) => void;
}) {
  const [rows, setRows] = useState<HistoryRecord[] | null>(null);
  const [query, setQuery] = useState("");
  const [period, setPeriod] = useState<HistoryPeriod>("");
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const timer = window.setTimeout(() => {
      api
        .history(query.trim(), period, 100)
        .then((r) => {
          if (cancelled) return;
          setRows(r);
          setError(false);
        })
        .catch(() => !cancelled && setError(true));
    }, 200);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [query, period, revision]);

  const remove = (taskId: string) =>
    void api.deleteHistoryEntry(taskId).then(
      () => setRows((prev) => prev?.filter((r) => r.task_id !== taskId) ?? null),
      () => setError(true),
    );

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <input
          className={`${inputClass} min-w-48 flex-1`}
          placeholder="Dhoondein (maslan: report, Chrome, message)"
          value={query}
          maxLength={100}
          onChange={(e) => setQuery(e.target.value)}
        />
        <select className={inputClass} value={period} onChange={(e) => setPeriod(e.target.value as HistoryPeriod)}>
          {PERIODS.map((p) => (
            <option key={p.value} value={p.value}>
              {p.label}
            </option>
          ))}
        </select>
      </div>
      <label className="flex items-center gap-2 text-xs text-slate-400">
        History kitni der rakhein:
        <select
          className={inputClass}
          value={historyDays}
          onChange={(e) => onRetention(Number(e.target.value) as UserSettings["history_days"])}
        >
          {RETENTION_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </label>
      {error && <span className="text-xs text-red-300">History load nahi ho saki.</span>}
      {rows === null ? (
        <Note>Load ho rahi hai...</Note>
      ) : rows.length === 0 ? (
        <Note>{query || period ? "Is talash mein kuch nahi mila." : "Abhi koi history nahi."}</Note>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {rows.map((r) => {
            const meta = OUTCOME_META[r.outcome];
            return (
              <li key={r.task_id} className="flex items-start justify-between gap-3 rounded-lg bg-white/[0.03] px-3 py-2">
                <span className="flex min-w-0 flex-col gap-0.5">
                  <span className="font-mono text-[10px] text-slate-500">
                    {shortDate(r.date)} {r.time.slice(0, 5)} · {r.source === "voice" ? "awaaz" : "likh kar"}
                    <span className={`ml-2 ${meta.tone}`}>{meta.label}</span>
                    {r.permission !== "not_required" && <span className="ml-2">ijazat: {r.permission.replaceAll("_", " ")}</span>}
                    {r.verification !== "not_applicable" && <span className="ml-2">verify: {r.verification}</span>}
                  </span>
                  <span className="text-sm text-sky-100">“{r.request}”</span>
                  {r.response && <span className="line-clamp-2 whitespace-pre-line text-xs text-slate-300">{r.response}</span>}
                  {r.actions.length > 0 && <span className="text-[10px] text-slate-500">{r.actions.join(" · ")}</span>}
                  {r.error && <span className="text-[10px] text-red-300">{r.error}</span>}
                </span>
                <ConfirmButton label="Mitao" question="Pakka?" onConfirm={() => remove(r.task_id)} />
              </li>
            );
          })}
        </ul>
      )}
      <div className="flex justify-end">
        <ConfirmButton
          label="Saari history mitayein"
          question="Saari baatein aur activity log hamesha ke liye mit jayenge. Pakka?"
          onConfirm={() => void api.deleteAllHistory().then(() => setRows([]), () => setError(true))}
        />
      </div>
    </div>
  );
}

function ShortTerm({ revision }: { revision: number }) {
  const [snap, setSnap] = useState<ShortTermMemory | null>(null);
  const load = () => api.shortTerm().then(setSnap).catch(() => setSnap(null));
  useEffect(() => {
    void load();
  }, [revision]);

  return (
    <div className="flex flex-col gap-3">
      <Note>
        Abhi ki baat-cheet (short-term memory) sirf RAM mein hai: pichli {snap?.turns.length ?? 0} baatein, taa ke "isko",
        "dobara karo" aur NOVA ke sawal ("Ye yaad rakhoon?") samajh aayein. {snap?.idle_reset_min ?? 30} minute khamoshi ya
        NOVA band hone par khud saaf ho jati hai. PC ki maloomat (system memory) System Profile tab mein hai.
      </Note>
      {snap?.pending && (
        <div className="rounded-lg border border-amber-400/30 bg-amber-400/10 px-3 py-2 text-xs text-amber-100">
          NOVA jawab ka intezar kar raha hai: {snap.pending}
        </div>
      )}
      {snap && snap.turns.length > 0 ? (
        <ul className="flex flex-col gap-1.5">
          {snap.turns.map((t, i) => (
            <li key={i} className="rounded-lg bg-white/[0.03] px-3 py-2 text-xs">
              <div className="text-sky-100">Aap: {t.user}</div>
              <div className="line-clamp-2 whitespace-pre-line text-slate-400">NOVA: {t.assistant}</div>
            </li>
          ))}
        </ul>
      ) : (
        <Note>Abhi koi baat-cheet yaad nahi.</Note>
      )}
      <div className="flex items-center justify-between">
        <span className="text-[10px] text-slate-500">
          {snap?.last_command ? `"Dobara karo" ye karega: ${snap.last_command}` : ""}
          {snap?.resets_in_s ? ` · ${Math.ceil(snap.resets_in_s / 60)} minute mein khud saaf` : ""}
        </span>
        <button type="button" className={buttonClass} onClick={() => void api.clearShortTerm().then(load, load)}>
          Abhi saaf karein
        </button>
      </div>
    </div>
  );
}

/** Everything NOVA remembers, and the user's control over it (spec: "The user must have control over stored memory"). */
export function MemoryView({
  revision,
  historyDays,
  onRun,
}: {
  revision: number;
  historyDays: UserSettings["history_days"];
  onRun: (command: string) => void;
}) {
  const [tab, setTab] = useState<Tab>("facts");
  const [days, setDays] = useState(historyDays);
  useEffect(() => setDays(historyDays), [historyDays]);

  const setRetention = (value: UserSettings["history_days"]) => {
    setDays(value);
    void api.updateSettings({ history_days: value }).catch(() => setDays(historyDays));
  };

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-3">
      <nav className="flex gap-1 rounded-lg bg-black/20 p-1" aria-label="Memory sections">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            aria-pressed={tab === t.id}
            onClick={() => setTab(t.id)}
            className={`flex-1 rounded-md px-2 py-1 text-xs transition ${
              tab === t.id ? "bg-white/10 text-slate-100" : "text-slate-400 hover:text-slate-200"
            }`}
          >
            {t.label}
          </button>
        ))}
      </nav>
      {tab === "facts" && <Facts revision={revision} />}
      {tab === "workflows" && <Workflows revision={revision} onRun={onRun} />}
      {tab === "history" && <History revision={revision} historyDays={days} onRetention={setRetention} />}
      {tab === "short" && <ShortTerm revision={revision} />}
    </div>
  );
}
