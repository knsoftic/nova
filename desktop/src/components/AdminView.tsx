import { useEffect, useState } from "react";
import { ApiError, api } from "../lib/api";
import type { AdminFeature, Bug, DaySummary, SelfTestResult, TestRun } from "../lib/types";
import { BUG_WORDS, CHECK_TONE, LIFECYCLE, lifecycleIndex, shortDate } from "../lib/ui";

const buttonClass = "rounded-md border border-white/10 px-2.5 py-1 text-xs text-slate-200 hover:bg-white/5 disabled:opacity-40";
const inputClass =
  "rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-xs text-slate-100 outline-none focus:border-sky-500/60";

function errorText(err: unknown): string {
  if (err instanceof ApiError) {
    const detail = (err.detail as { detail?: unknown } | null)?.detail;
    if (typeof detail === "string") return detail;
  }
  return "Ye kaam nahi ho saka.";
}

function Results({ results }: { results: SelfTestResult[] }) {
  return (
    <ul className="flex flex-col gap-0.5 text-[11px]">
      {results.map((r) => (
        <li key={r.id} className="flex gap-2">
          <span className={`w-10 shrink-0 font-mono uppercase ${CHECK_TONE[r.status]}`}>{r.status}</span>
          <span className="text-slate-300">{r.name}</span>
          <span className="truncate text-slate-500" title={r.detail}>
            — {r.detail}
          </span>
        </li>
      ))}
    </ul>
  );
}

function SelfTestCard({ revision }: { revision: number }) {
  const [run, setRun] = useState<TestRun | null>(null);
  const [summary, setSummary] = useState<DaySummary | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api.lastSelfTest().then(setRun).catch(() => undefined);
    api.adminSummary().then(setSummary).catch(() => undefined);
  }, [revision]);

  const full = async () => {
    setBusy(true);
    try {
      setRun(await api.runSelfTest("full"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="flex flex-col gap-2 rounded-lg bg-white/[0.03] p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-medium text-slate-100">Self-test</span>
        <button type="button" className={buttonClass} disabled={busy} onClick={() => void full()}>
          {busy ? "Chal raha hai... (local AI samet, 1-2 minute)" : "Poora test chalayein"}
        </button>
      </div>
      {run ? (
        <>
          <span className="text-xs text-slate-400">
            Aakhri ({run.scope}{run.started_at ? `, ${shortDate(run.started_at)} ${run.started_at.slice(11, 16)}` : ""}):{" "}
            <span className="text-emerald-300">{run.passed} theek</span>
            {run.warned > 0 && <span className="text-amber-300"> · {run.warned} kami</span>}
            {run.failed > 0 && <span className="text-red-300"> · {run.failed} nakaam</span>}
          </span>
          <Results results={run.results.filter((r) => r.status !== "pass")} />
        </>
      ) : (
        <span className="text-xs text-slate-500">Abhi koi test nahi chala.</span>
      )}
      {summary && (
        <span className="text-[11px] text-slate-500">
          Aaj: {summary.line}
          {!summary.logs_md && " (LOGS.md nahi mili — approvals aur khulasa likhe nahi ja sakte)"}
        </span>
      )}
    </section>
  );
}

function FeatureCard({ feature, onChanged }: { feature: AdminFeature; onChanged: () => void }) {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<"" | "approve" | "problem">("");
  const [problem, setProblem] = useState({ title: "", details: "" });
  const [run, setRun] = useState<TestRun | null>(null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const step = lifecycleIndex(feature.stage);

  const act = async (fn: () => Promise<unknown>, done: string) => {
    setBusy(true);
    setMessage(null);
    try {
      await fn();
      setMessage({ ok: true, text: done });
      setMode("");
      onChanged();
    } catch (err) {
      setMessage({ ok: false, text: errorText(err) });
    } finally {
      setBusy(false);
    }
  };

  const test = (retest: boolean) =>
    act(async () => {
      const r = retest ? await api.retestFeature(feature.phase) : await api.testFeature(feature.phase);
      setRun(r);
    }, retest ? "Retest ho gaya — ab khud check kar ke approve karein." : "Test ho gaya.");

  return (
    <li className="flex flex-col gap-2 rounded-lg bg-white/[0.03] px-3 py-2">
      <button type="button" className="flex items-start justify-between gap-2 text-left" onClick={() => setOpen(!open)}>
        <span className="flex min-w-0 flex-col">
          <span className="text-sm text-slate-100">{feature.title}</span>
          <span className="text-[11px] text-slate-500">
            {feature.admin_approval || "Pending"}
            {feature.bugs_active > 0 && <span className="text-red-300"> · {feature.bugs_active} bug khule</span>}
          </span>
        </span>
        <span className="shrink-0 text-xs text-slate-500">{open ? "▲" : "▼"}</span>
      </button>
      <ol className="flex flex-wrap gap-1 text-[10px]">
        {LIFECYCLE.map((s, i) => (
          <li
            key={s.id}
            className={`rounded px-1.5 py-0.5 ${
              feature.stage === "problem" && i === 0
                ? "bg-red-500/20 text-red-200"
                : i <= step
                  ? "bg-emerald-500/15 text-emerald-200"
                  : "bg-white/5 text-slate-500"
            }`}
          >
            {feature.stage === "problem" && i === 0 ? "Problem → fix" : s.label}
          </li>
        ))}
      </ol>
      {open && (
        <div className="flex flex-col gap-2 border-t border-white/10 pt-2">
          {feature.steps.length > 0 && (
            <ol className="list-decimal pl-5 text-xs text-slate-300">
              {feature.steps.map((s, i) => (
                <li key={i} className="mb-0.5">
                  {s.replaceAll("**", "").replaceAll("`", "")}
                </li>
              ))}
            </ol>
          )}
          {(run?.results ?? feature.self_test.results).length > 0 && <Results results={run?.results ?? feature.self_test.results} />}
          <div className="flex flex-wrap gap-2">
            <button type="button" className={buttonClass} disabled={busy} onClick={() => void test(false)}>
              Test Feature
            </button>
            {!feature.approved && (
              <button type="button" className={buttonClass} disabled={busy} onClick={() => setMode(mode === "approve" ? "" : "approve")}>
                Approve
              </button>
            )}
            <button type="button" className={buttonClass} disabled={busy} onClick={() => setMode(mode === "problem" ? "" : "problem")}>
              Report Problem
            </button>
            <button type="button" className={buttonClass} disabled={busy} onClick={() => void test(true)}>
              Retest
            </button>
          </div>
          {mode === "approve" && (
            <div className="flex flex-col gap-2 rounded-md border border-emerald-400/20 bg-emerald-500/5 p-2 text-xs">
              <span className="text-emerald-100">
                Kya aap ne upar wale steps khud test kar liye hain? Approve karne par LOGS.md mein "Approved (... Admin panel
                se)" likha jayega.
              </span>
              <span className="flex gap-3">
                <button
                  type="button"
                  className="text-emerald-300 hover:text-emerald-200"
                  onClick={() => void act(() => api.approveFeature(feature.phase), "Approve ho gaya — LOGS.md mein likh diya.")}
                >
                  Haan, approve
                </button>
                <button type="button" className="text-slate-400" onClick={() => setMode("")}>
                  Nahi
                </button>
              </span>
            </div>
          )}
          {mode === "problem" && (
            <form
              className="flex flex-col gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                void act(() => api.reportProblem(feature.phase, problem.title.trim(), problem.details.trim()), "Bug log ho gaya.");
              }}
            >
              <input
                className={inputClass}
                placeholder="Kya masla hai? (maslan: volume 30 nahi hua)"
                value={problem.title}
                maxLength={160}
                onChange={(e) => setProblem({ ...problem, title: e.target.value })}
              />
              <textarea
                className={`${inputClass} min-h-16`}
                placeholder="Kaise hua (kya kaha, kya hua, kya hona chahiye tha)"
                value={problem.details}
                maxLength={2000}
                onChange={(e) => setProblem({ ...problem, details: e.target.value })}
              />
              <button type="submit" className={`${buttonClass} self-end`} disabled={busy || problem.title.trim().length < 3}>
                Bug log karein
              </button>
            </form>
          )}
          {message && <span className={`text-xs ${message.ok ? "text-emerald-300" : "text-red-300"}`}>{message.text}</span>}
        </div>
      )}
    </li>
  );
}

function BugList({ revision, onChanged }: { revision: number; onChanged: () => void }) {
  const [bugs, setBugs] = useState<Bug[] | null>(null);
  const [all, setAll] = useState(false);
  useEffect(() => {
    api.bugs(all ? "" : "active").then(setBugs).catch(() => setBugs([]));
  }, [revision, all]);

  const set = async (bug: Bug, status: Bug["status"]) => {
    await api.setBugStatus(bug.id, status).catch(() => undefined);
    onChanged();
  };

  return (
    <section className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-slate-100">Bugs</span>
        <label className="flex items-center gap-1.5 text-xs text-slate-400">
          <input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} /> band wale bhi
        </label>
      </div>
      {!bugs ? (
        <span className="text-xs text-slate-500">Load ho rahe hain...</span>
      ) : bugs.length === 0 ? (
        <span className="text-xs text-slate-500">Koi khula bug nahi.</span>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {bugs.map((b) => (
            <li key={b.id} className="flex flex-col gap-1 rounded-lg bg-white/[0.03] px-3 py-2">
              <span className="flex items-start justify-between gap-2">
                <span className="text-sm text-slate-100">
                  #{b.id} {b.title}
                </span>
                <span className={`shrink-0 text-[11px] ${b.status === "closed" ? "text-slate-500" : "text-amber-300"}`}>
                  {BUG_WORDS[b.status]}
                </span>
              </span>
              <span className="text-[11px] text-slate-500">
                {b.phase ? `Phase ${b.phase}` : "aam"} · {b.source === "admin" ? "aap ne report kiya" : b.source === "automatic" ? "khud log hua (crash)" : "self-test"}
                {b.occurrences > 1 && ` · ${b.occurrences} dafa`} · {shortDate(b.created_at)}
              </span>
              {b.details && <span className="whitespace-pre-line text-xs text-slate-400">{b.details}</span>}
              <span className="flex gap-3 text-xs">
                {(b.status === "open" || b.status === "reopened") && (
                  <button type="button" className="text-sky-300 hover:text-sky-200" onClick={() => void set(b, "fixed")}>
                    Fix ho gaya
                  </button>
                )}
                {b.status === "fixed" && (
                  <button type="button" className="text-emerald-300 hover:text-emerald-200" onClick={() => void set(b, "closed")}>
                    Retest theek — band karein
                  </button>
                )}
                {b.status !== "open" && b.status !== "reopened" && (
                  <button type="button" className="text-red-300 hover:text-red-200" onClick={() => void set(b, "reopened")}>
                    Dobara kholein
                  </button>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** Administrator testing (spec 28): Test Feature, Approve, Report Problem, Retest - and the bug log. */
export function AdminView({ revision }: { revision: number }) {
  const [features, setFeatures] = useState<AdminFeature[] | null>(null);
  const [local, setLocal] = useState(0);
  const changed = () => setLocal((n) => n + 1);
  useEffect(() => {
    api.adminFeatures().then(setFeatures).catch(() => setFeatures([]));
  }, [revision, local]);

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-4">
      <p className="text-xs text-slate-500">
        Har phase ke manual test steps, automated test aur aap ki approval. Approve sirf aap ke click (aur pakka karne) par
        hota hai — NOVA khud kabhi approve nahi karta. Masla ho to "Report Problem": bug log → fix → retest → approval.
      </p>
      <SelfTestCard revision={revision + local} />
      {!features ? (
        <span className="text-xs text-slate-500">Load ho raha hai...</span>
      ) : features.length === 0 ? (
        <span className="text-xs text-slate-500">LOGS.md mein koi phase nahi mila.</span>
      ) : (
        <ul className="flex flex-col gap-2">
          {[...features].reverse().map((f) => (
            <FeatureCard key={f.phase} feature={f} onChanged={changed} />
          ))}
        </ul>
      )}
      <BugList revision={revision + local} onChanged={changed} />
    </div>
  );
}
