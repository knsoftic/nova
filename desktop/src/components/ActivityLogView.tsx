import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { ActivityKind, ActivityRecord } from "../lib/types";

const STATUS_TONE: Record<string, string> = {
  success: "text-emerald-300",
  passed: "text-emerald-300",
  approved: "text-emerald-300",
  failed: "text-red-300",
  denied: "text-red-300",
  intent_only: "text-slate-400",
  problem: "text-red-300",
  retry: "text-amber-300",
  not_required: "text-slate-500",
  pending: "text-amber-300",
};

function Status({ value }: { value: string }) {
  return <span className={STATUS_TONE[value] ?? "text-slate-300"}>{value.replaceAll("_", " ")}</span>;
}

const FILTERS: { value: ActivityKind; label: string }[] = [
  { value: "", label: "Sab" },
  { value: "failed", label: "Nakaam / errors" },
  { value: "unverified", label: "Verify nahi hua" },
  { value: "permission", label: "Ijazat ke sawal" },
  { value: "denied", label: "Inkaar" },
  { value: "tests", label: "Tests" },
  { value: "admin", label: "Admin" },
];

/** The persisted, structured activity log from SQLite (spec section 30), with filters. */
export function ActivityLogView({ revision }: { revision: number }) {
  const [rows, setRows] = useState<ActivityRecord[] | null>(null);
  const [error, setError] = useState(false);
  const [kind, setKind] = useState<ActivityKind>("");
  const [query, setQuery] = useState("");

  useEffect(() => {
    let cancelled = false;
    const timer = window.setTimeout(() => {
      api
        .activity(200, kind, query.trim())
        .then((r) => {
          if (cancelled) return;
          setRows(r);
          setError(false);
        })
        .catch(() => !cancelled && setError(true));
    }, 150);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [revision, kind, query]);

  const filters = (
    <div className="flex flex-wrap items-center gap-2">
      <select
        className="rounded-lg border border-white/10 bg-black/30 px-2 py-1.5 text-xs text-slate-100"
        value={kind}
        onChange={(e) => setKind(e.target.value as ActivityKind)}
      >
        {FILTERS.map((f) => (
          <option key={f.value} value={f.value}>
            {f.label}
          </option>
        ))}
      </select>
      <input
        className="min-w-40 flex-1 rounded-lg border border-white/10 bg-black/30 px-2 py-1.5 text-xs text-slate-100"
        placeholder="Dhoondein (task, action, nateeja ya task id)"
        value={query}
        maxLength={100}
        onChange={(e) => setQuery(e.target.value)}
      />
    </div>
  );

  if (error) return <p className="text-center text-sm text-red-300">Activity log load nahi ho saka.</p>;
  if (!rows) return <p className="text-center text-sm text-slate-400">Load ho raha hai...</p>;
  if (rows.length === 0)
    return (
      <div className="flex w-full flex-col gap-2">
        {filters}
        <p className="text-center text-sm text-slate-400">{kind || query ? "Is filter mein kuch nahi." : "Abhi tak koi record nahi."}</p>
      </div>
    );

  return (
    <div className="flex w-full flex-col gap-2">
      {filters}
      <p className="text-xs text-slate-400">
        Aakhri {rows.length} records. Passwords/tokens record hone se pehle chhupa diye jate hain.
      </p>
      <div className="overflow-x-auto rounded-xl border border-white/10">
        <table className="w-full text-left text-xs">
          <thead className="bg-white/5 font-mono text-[10px] uppercase tracking-wider text-slate-400">
            <tr>
              <th className="px-2 py-2">Waqt</th>
              <th className="px-2 py-2">Task</th>
              <th className="px-2 py-2">Agent / Action</th>
              <th className="px-2 py-2">Permission</th>
              <th className="px-2 py-2">Execution</th>
              <th className="px-2 py-2">Verification</th>
              <th className="px-2 py-2">Admin</th>
              <th className="px-2 py-2">Result</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="border-t border-white/5 align-top">
                <td className="whitespace-nowrap px-2 py-1.5 font-mono text-slate-400">
                  {r.date}
                  <br />
                  {r.time}
                </td>
                <td className="px-2 py-1.5">
                  <div className="text-slate-100">{r.task_name}</div>
                  <div className="font-mono text-[10px] text-slate-500">{r.task_id}</div>
                </td>
                <td className="px-2 py-1.5">
                  <div className="text-slate-200">{r.agent}</div>
                  <div className="text-slate-500">{r.action}</div>
                </td>
                <td className="px-2 py-1.5">
                  <Status value={r.permission_status} />
                </td>
                <td className="px-2 py-1.5">
                  <Status value={r.execution_status} />
                </td>
                <td className="px-2 py-1.5">
                  <Status value={r.verification_status} />
                </td>
                <td className="px-2 py-1.5">
                  <Status value={r.admin_status} />
                </td>
                <td className="max-w-[180px] px-2 py-1.5 text-slate-300">
                  {r.final_result}
                  {r.error && <div className="text-red-300">{r.error}</div>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
