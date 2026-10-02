import { useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "../lib/api";
import type { LiveStats, SystemProfile } from "../lib/types";
import { formatBytes, formatDuration, formatTime } from "../lib/ui";

const LIVE_POLL_MS = 5000;

function pcName(p: SystemProfile): string {
  const maker = p.windows.manufacturer ?? "";
  const model = p.windows.model ?? "";
  // OEMs often repeat the brand in the model string ("HP" + "HP EliteBook 845 G8").
  if (maker && model.toLowerCase().startsWith(maker.toLowerCase())) return model;
  return [maker, model].filter(Boolean).join(" ") || "—";
}

function Card({ title, children, className = "" }: { title: string; children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-xl border border-white/10 bg-black/20 p-3 ${className}`}>
      <h3 className="mb-2 font-mono text-[10px] uppercase tracking-[0.2em] text-slate-400">{title}</h3>
      <div className="flex flex-col gap-1.5 text-sm">{children}</div>
    </section>
  );
}

function Row({ label, value, ok }: { label: string; value: ReactNode; ok?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="shrink-0 text-xs text-slate-400">{label}</span>
      <span className={`text-right ${ok === false ? "text-amber-300" : "text-slate-100"}`}>{value}</span>
    </div>
  );
}

function Bar({ percent, warn = 85 }: { percent: number; warn?: number }) {
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/10">
      <div
        className={`h-full rounded-full ${percent >= warn ? "bg-amber-400" : "bg-sky-400"}`}
        style={{ width: `${Math.min(100, Math.max(0, percent))}%` }}
      />
    </div>
  );
}

export function SystemProfileView({ revision, scanning }: { revision: number; scanning: boolean }) {
  const [profile, setProfile] = useState<SystemProfile | null>(null);
  const [serverScanning, setServerScanning] = useState(false);
  const [live, setLive] = useState<LiveStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [appQuery, setAppQuery] = useState("");

  useEffect(() => {
    let cancelled = false;
    api
      .profile()
      .then((r) => {
        if (cancelled) return;
        setProfile(r.profile);
        setServerScanning(r.scanning);
        setError(null);
      })
      .catch(() => !cancelled && setError("System profile load nahi ho saka."));
    return () => {
      cancelled = true;
    };
  }, [revision]);

  useEffect(() => {
    let cancelled = false;
    const poll = () =>
      api
        .live()
        .then((s) => !cancelled && setLive(s))
        .catch(() => undefined);
    void poll();
    const id = window.setInterval(poll, LIVE_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  const filteredApps = useMemo(() => {
    const apps = profile?.apps ?? [];
    const q = appQuery.trim().toLowerCase();
    return q ? apps.filter((a) => a.name.toLowerCase().includes(q)) : apps;
  }, [profile, appQuery]);

  const busy = scanning || serverScanning;
  const rescan = () => {
    setServerScanning(true);
    api.scan().catch(() => setError("Scan nakam raha."));
  };

  const header = (
    <div className="flex items-center justify-between gap-3">
      <div className="text-xs text-slate-400">
        {profile ? (
          <>
            Aakhri scan: {formatTime(profile.scanned_at)} · {(profile.scan_duration_ms / 1000).toFixed(1)}s
          </>
        ) : (
          "Abhi tak koi scan nahi hua"
        )}
      </div>
      <button
        type="button"
        onClick={rescan}
        disabled={busy}
        className="rounded-lg border border-sky-500/40 px-3 py-1.5 text-xs text-sky-200 transition hover:bg-sky-500/10 disabled:opacity-50"
      >
        {busy ? "Scan ho raha hai..." : "Dobara scan karo"}
      </button>
    </div>
  );

  if (!profile) {
    return (
      <div className="flex w-full flex-col gap-4">
        {header}
        <p className="text-center text-sm text-slate-400">
          {error ?? (busy ? "NOVA aapke system ko scan kar raha hai..." : "System profile abhi available nahi.")}
        </p>
      </div>
    );
  }

  const p = profile;
  const ramUsedPct = live ? live.ram_percent : null;
  const drives = live?.drives ?? p.drives;

  return (
    <div className="flex w-full flex-col gap-3">
      {header}
      {error && <p className="text-xs text-red-300">{error}</p>}

      <div className="grid grid-cols-3 gap-3">
        <Card title="CPU (live)">
          <span className="text-2xl font-semibold text-slate-100">{live ? `${live.cpu_percent.toFixed(0)}%` : "—"}</span>
          {live && <Bar percent={live.cpu_percent} />}
        </Card>
        <Card title="RAM (live)">
          <span className="text-2xl font-semibold text-slate-100">
            {live ? `${formatBytes(live.ram_total_bytes - live.ram_available_bytes)}` : "—"}
            <span className="text-sm text-slate-400"> / {formatBytes(live?.ram_total_bytes ?? p.ram_total_bytes)}</span>
          </span>
          {ramUsedPct !== null && <Bar percent={ramUsedPct} />}
        </Card>
        <Card title="Uptime">
          <span className="text-2xl font-semibold text-slate-100">{live ? formatDuration(live.uptime_seconds) : "—"}</span>
        </Card>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <Card title="Hardware">
          <Row label="PC" value={pcName(p)} />
          <Row label="CPU" value={p.cpu.name ?? "—"} />
          <Row label="Cores / Threads" value={`${p.cpu.cores ?? "?"} / ${p.cpu.threads ?? "?"}`} />
          <Row label="RAM" value={formatBytes(p.ram_total_bytes)} />
          {p.gpus.length === 0 && <Row label="GPU" value="Nahi mila" ok={false} />}
          {p.gpus.map((g) => (
            <Row
              key={g.name}
              label="GPU"
              value={`${g.name} · ${g.dedicated ? "dedicated" : g.dedicated === false ? "integrated" : "?"} · ${formatBytes(g.memory_bytes)}`}
            />
          ))}
        </Card>

        <Card title="Windows">
          <Row label="Edition" value={p.windows.caption ?? "—"} />
          <Row label="Version" value={p.windows.display_version ?? p.windows.version ?? "—"} />
          <Row label="Build" value={p.windows.build ?? "—"} />
          <Row label="Architecture" value={p.windows.architecture ?? "—"} />
          <Row label="Computer" value={p.windows.computer_name ?? "—"} />
          <Row
            label="Administrator"
            value={
              p.permissions.is_elevated
                ? "NOVA elevated hai"
                : p.permissions.user_is_admin
                  ? "User admin hai (NOVA elevated nahi)"
                  : "Standard user"
            }
          />
        </Card>

        <Card title="Storage">
          {drives.map((d) => {
            const usedPct = ((d.total_bytes - d.free_bytes) / d.total_bytes) * 100;
            return (
              <div key={d.mountpoint} className="flex flex-col gap-1">
                <Row label={d.mountpoint} value={`${formatBytes(d.free_bytes)} free / ${formatBytes(d.total_bytes)}`} />
                <Bar percent={usedPct} warn={90} />
              </div>
            );
          })}
        </Card>

        <Card title="Devices">
          <Row label="Microphone" value={p.microphones[0]?.name ?? "Nahi mila"} ok={p.microphones.length > 0} />
          <Row label="Speaker" value={p.speakers[0]?.name ?? "Nahi mila"} ok={p.speakers.length > 0} />
          <Row label="Camera" value={p.cameras.join(", ") || "Nahi mila"} ok={p.cameras.length > 0} />
          <Row
            label="Displays"
            value={p.displays.map((d) => `${d.width}x${d.height}${d.primary ? " (primary)" : ""}`).join(", ") || "—"}
          />
          <Row label="Network" value={p.network_connected ? "Connected" : "Disconnected"} ok={p.network_connected} />
        </Card>
      </div>

      <Card title="Self-configuration">
        {p.recommendations.map((r) => (
          <div key={r.key} className="flex items-start justify-between gap-3 border-b border-white/5 pb-1.5 last:border-0">
            <div>
              <div className="font-mono text-xs text-slate-300">
                {r.key} = <span className="text-sky-300">{r.value}</span>
              </div>
              <div className="text-xs text-slate-400">{r.reason}</div>
            </div>
            <span
              className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] ${
                r.auto_applied ? "bg-emerald-500/15 text-emerald-300" : "bg-white/5 text-slate-400"
              }`}
            >
              {r.auto_applied ? "Applied" : "Suggestion"}
            </span>
          </div>
        ))}
      </Card>

      <div className="grid grid-cols-2 gap-3">
        <Card title={`Browsers (${p.browsers.length})`}>
          {p.browsers.map((b) => (
            <Row key={b.name} label={b.is_default ? "Default" : ""} value={b.name} />
          ))}
        </Card>
        <Card title={`Khuli applications (${p.running_apps.length})`}>
          {p.running_apps.map((r) => (
            <Row key={r.pid} label={r.name} value={<span className="line-clamp-1 text-xs">{r.title}</span>} />
          ))}
        </Card>
      </div>

      <Card title={`Installed applications (${p.apps.length})`}>
        <input
          value={appQuery}
          onChange={(e) => setAppQuery(e.target.value)}
          placeholder="Application dhoondein..."
          aria-label="Search installed applications"
          className="mb-1 rounded-lg border border-white/10 bg-black/30 px-3 py-1.5 text-sm text-slate-100 outline-none placeholder:text-slate-500 focus:border-sky-500/60"
        />
        <ul className="max-h-64 overflow-y-auto pr-1">
          {filteredApps.map((a) => (
            <li key={a.name} className="flex items-baseline justify-between gap-2 border-b border-white/5 py-1 last:border-0">
              <span className="text-slate-100">{a.name}</span>
              <span className="shrink-0 font-mono text-[10px] text-slate-500">
                {a.version ? `${a.version} · ` : ""}
                {a.sources.join(", ")}
              </span>
            </li>
          ))}
          {filteredApps.length === 0 && <li className="text-xs text-slate-500">Koi application nahi mili.</li>}
        </ul>
      </Card>

      <div className="grid grid-cols-2 gap-3">
        <Card title={`Startup items (${p.startup_items.length})`}>
          <ul className="max-h-40 overflow-y-auto pr-1 text-xs">
            {p.startup_items.map((s, i) => (
              <li key={`${s.name}-${i}`} className="flex justify-between gap-2 py-0.5">
                <span className="truncate text-slate-200">{s.name}</span>
                <span className="shrink-0 text-slate-500">{s.location}</span>
              </li>
            ))}
          </ul>
        </Card>
        <Card title="Windows services">
          {p.services.map((s) => (
            <Row key={s.name} label={s.display_name ?? s.name} value={s.status ?? "?"} ok={s.status === "running"} />
          ))}
        </Card>
      </div>

      {p.errors.length > 0 && (
        <Card title="Detect nahi ho saka" className="border-amber-500/30">
          {p.errors.map((e) => (
            <span key={e} className="font-mono text-xs text-amber-300">
              {e}
            </span>
          ))}
        </Card>
      )}
    </div>
  );
}
