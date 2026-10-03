import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "../lib/api";
import type { FoundPc, PairedPc, PcsStatus, UserSettings } from "../lib/types";
import { pairingTimeLeft, pcExamples } from "../lib/ui";

const buttonClass = "rounded-md border border-white/10 px-2.5 py-1 text-xs text-slate-200 hover:bg-white/5 disabled:opacity-40";
const primaryClass = "rounded-md bg-sky-500 px-3 py-1 text-xs font-medium text-slate-950 hover:bg-sky-400 disabled:opacity-40";
const inputClass =
  "rounded-lg border border-white/10 bg-black/30 px-3 py-1.5 text-xs text-slate-100 outline-none focus:border-sky-500/60";

function errorText(err: unknown): string {
  if (err instanceof ApiError) {
    const detail = (err.detail as { detail?: unknown } | null)?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) return "Code poora likhein (12 haroof)";
  }
  return "Ye kaam nahi ho saka.";
}

/** Multi-PC (Phase 13): this PC's name and status, joining PCs with a one-time code, and the paired PCs. */
export function PcsView({
  revision,
  settings,
  onRun,
}: {
  revision: number;
  settings: UserSettings | null;
  onRun: (command: string) => void;
}) {
  const [status, setStatus] = useState<PcsStatus | null>(null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState(settings?.pc_name ?? "");
  const [joining, setJoining] = useState<string | null>(null); // a found PC's id, or "manual"
  const [code, setCode] = useState("");
  const [host, setHost] = useState("");
  const [now, setNow] = useState(() => Date.now());
  const [codeAt, setCodeAt] = useState(() => Date.now());

  const load = useCallback(() => {
    api
      .pcs()
      .then((s) => {
        setStatus(s);
        setCodeAt(Date.now());
      })
      .catch(() => undefined);
  }, []);
  useEffect(load, [load, revision]);
  useEffect(() => setName(settings?.pc_name ?? ""), [settings?.pc_name]);
  // The joining code counts down; found PCs come and go, so look again now and then while the tab is open.
  useEffect(() => {
    const tick = window.setInterval(() => setNow(Date.now()), 1000);
    const poll = window.setInterval(load, 10_000);
    return () => {
      window.clearInterval(tick);
      window.clearInterval(poll);
    };
  }, [load]);

  const act = async (fn: () => Promise<unknown>, done: string | null) => {
    setBusy(true);
    setMessage(null);
    try {
      await fn();
      if (done) setMessage({ ok: true, text: done });
      load();
      return true;
    } catch (err) {
      setMessage({ ok: false, text: errorText(err) });
      return false;
    } finally {
      setBusy(false);
    }
  };

  if (!status || !settings) return <p className="text-center text-sm text-slate-400">PCs ki maloomat aa rahi hai...</p>;

  const pairingLeft = status.pairing ? pairingTimeLeft(status.pairing.expires_in, codeAt, now) : 0;
  const net = status.networks[0];

  const join = async (pc: FoundPc | null) => {
    const ok = await act(
      () => api.pairPc(pc ? { code, peer_id: pc.id } : { code, host: host.trim(), port: 8770 }),
      `${pc?.name ?? host} se jur gaya. Ab wahan "Remote kaam" on hone par yahan se kaam karwa sakte hain.`,
    );
    if (ok) {
      setJoining(null);
      setCode("");
    }
  };

  return (
    <div className="flex flex-col gap-3 text-slate-200">
      {message && (
        <p className={`rounded-lg px-3 py-2 text-xs ${message.ok ? "bg-emerald-500/10 text-emerald-200" : "bg-red-500/10 text-red-200"}`}>
          {message.text}
        </p>
      )}

      <section className="flex flex-col gap-2 rounded-lg bg-white/[0.03] p-3">
        <div className="flex items-center justify-between gap-2">
          <span className="text-sm font-medium text-slate-100">Ye PC: {status.this.name}</span>
          <label className="flex items-center gap-2 text-xs">
            <input
              type="checkbox"
              checked={settings.multi_pc}
              disabled={busy}
              onChange={(e) => void act(() => api.updateSettings({ multi_pc: e.target.checked }), null)}
            />
            Multi-PC on
          </label>
        </div>
        <div className="flex gap-2">
          <input
            className={`${inputClass} flex-1`}
            value={name}
            maxLength={40}
            placeholder={`Naam jo doosre PCs dekhenge (khali = ${status.this.name})`}
            onChange={(e) => setName(e.target.value)}
          />
          <button
            type="button"
            className={buttonClass}
            disabled={busy || name === settings.pc_name}
            onClick={() => void act(() => api.updateSettings({ pc_name: name }), "Naam save ho gaya.")}
          >
            Save
          </button>
        </div>
        {status.running ? (
          <span className="text-xs text-emerald-300">
            Chal raha hai{net ? ` · ${net.name || net.alias} (${net.category})` : ""} · port {status.this.port}
          </span>
        ) : (
          <span className="text-xs text-amber-300">{status.reason}</span>
        )}
        {status.running && (
          <span className="text-[11px] text-slate-500">
            Pehli dafa Windows Firewall "Python" ke liye poochh sakta hai — sirf "Private networks" par Allow karein.
            Doosre PC se raabta encrypted hai aur sirf jure hue PCs hi baat kar sakte hain.
          </span>
        )}
      </section>

      {status.running && (
        <section className="flex flex-col gap-2 rounded-lg bg-white/[0.03] p-3">
          <div className="flex items-center justify-between gap-2">
            <span className="text-sm font-medium text-slate-100">PC jorein</span>
            <button type="button" className={buttonClass} disabled={busy} onClick={() => void act(api.refreshPcs, null)}>
              Refresh
            </button>
          </div>
          {status.pairing && pairingLeft > 0 ? (
            <div className="flex flex-col items-center gap-1 rounded-lg border border-sky-400/30 bg-sky-500/10 p-3">
              <span className="text-xs text-slate-300">Doosre PC par NOVA → PCs mein "{status.this.name}" chunein aur ye code likhein:</span>
              <span className="font-mono text-2xl tracking-[0.25em] text-sky-100" data-testid="pairing-code">
                {status.pairing.code}
              </span>
              <span className="text-[11px] text-slate-400">
                {Math.floor(pairingLeft / 60)}:{String(pairingLeft % 60).padStart(2, "0")} baqi · sirf ek PC ke liye
              </span>
              <button type="button" className={buttonClass} disabled={busy} onClick={() => void act(api.closePairing, null)}>
                Band karein
              </button>
            </div>
          ) : (
            <button
              type="button"
              className={`${primaryClass} self-start`}
              disabled={busy}
              onClick={() => void act(api.openPairing, null)}
            >
              Is PC ko jorne do (code dikhao)
            </button>
          )}

          <span className="mt-1 text-xs text-slate-400">Network par mile PCs:</span>
          {status.found.length === 0 && (
            <span className="text-[11px] text-slate-500">
              Koi nahi mila. Doosre PC par NOVA chalayein, Multi-PC on karein (usi Wi-Fi par), phir Refresh.
            </span>
          )}
          <ul className="flex flex-col gap-1">
            {status.found.map((pc) => (
              <li key={pc.id} className="flex flex-col gap-1 rounded-md bg-black/20 px-2 py-1.5">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs">
                    {pc.name} <span className="text-slate-500">· {pc.host}</span>
                    {pc.pairing && <span className="ml-2 text-sky-300">jorne ke liye tayyar</span>}
                  </span>
                  <button type="button" className={buttonClass} disabled={busy} onClick={() => setJoining(pc.id)}>
                    Jorein
                  </button>
                </div>
                {joining === pc.id && (
                  <div className="flex gap-2">
                    <input
                      className={`${inputClass} flex-1 font-mono uppercase`}
                      value={code}
                      placeholder={`${pc.name} par dikhaya gaya code`}
                      onChange={(e) => setCode(e.target.value)}
                    />
                    <button type="button" className={primaryClass} disabled={busy || !code.trim()} onClick={() => void join(pc)}>
                      {busy ? "Jor raha hai..." : "Jorein"}
                    </button>
                  </div>
                )}
              </li>
            ))}
          </ul>
          {joining === "manual" ? (
            <div className="flex flex-wrap gap-2">
              <input className={`${inputClass} w-36`} value={host} placeholder="IP, maslan 192.168.1.20" onChange={(e) => setHost(e.target.value)} />
              <input
                className={`${inputClass} flex-1 font-mono uppercase`}
                value={code}
                placeholder="Us PC par dikhaya gaya code"
                onChange={(e) => setCode(e.target.value)}
              />
              <button
                type="button"
                className={primaryClass}
                disabled={busy || !code.trim() || !host.trim()}
                onClick={() => void join(null)}
              >
                Jorein
              </button>
            </div>
          ) : (
            <button type="button" className="self-start text-[11px] text-slate-500 hover:text-slate-300" onClick={() => setJoining("manual")}>
              PC list mein nahi? Pata (IP) likh kar jorein
            </button>
          )}
        </section>
      )}

      <section className="flex flex-col gap-2 rounded-lg bg-white/[0.03] p-3">
        <span className="text-sm font-medium text-slate-100">Jure hue PCs</span>
        {status.peers.length === 0 && <span className="text-xs text-slate-500">Abhi koi PC jura hua nahi.</span>}
        <ul className="flex flex-col gap-2">
          {status.peers.map((pc) => (
            <PeerCard key={pc.id} pc={pc} busy={busy} act={act} onRun={onRun} />
          ))}
        </ul>
        {status.peers.length > 0 && (
          <span className="text-[11px] text-slate-500">
            Kahein ya likhein: {pcExamples(status.peers[0].name).map((e) => `"${e}"`).join(", ")}. Ijazat wale kaam
            yahan poochhe jate hain; mitana, message bhejna aur khatarnak kaam doosre PC se kabhi nahi hote.
          </span>
        )}
      </section>
    </div>
  );
}

function PeerCard({
  pc,
  busy,
  act,
  onRun,
}: {
  pc: PairedPc;
  busy: boolean;
  act: (fn: () => Promise<unknown>, done: string | null) => Promise<boolean>;
  onRun: (command: string) => void;
}) {
  const [confirm, setConfirm] = useState(false);
  return (
    <li className="flex flex-col gap-1.5 rounded-md bg-black/20 px-3 py-2">
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm">
          <span className={pc.online ? "text-emerald-300" : "text-slate-500"}>●</span> {pc.name}{" "}
          <span className="text-[11px] text-slate-500">
            {pc.online ? "online" : "offline"} · {pc.host}
          </span>
        </span>
        <span className="flex gap-1">
          <button type="button" className={buttonClass} onClick={() => onRun(`${pc.name} ka haal batao`)}>
            Haal dekho
          </button>
          {confirm ? (
            <>
              <button
                type="button"
                className={`${buttonClass} text-red-200`}
                disabled={busy}
                onClick={() => void act(() => api.unpairPc(pc.id), `${pc.name} hata diya gaya.`)}
              >
                Haan, hatao
              </button>
              <button type="button" className={buttonClass} onClick={() => setConfirm(false)}>
                Nahi
              </button>
            </>
          ) : (
            <button type="button" className={buttonClass} onClick={() => setConfirm(true)}>
              Hatao
            </button>
          )}
        </span>
      </div>
      <label className="flex items-start gap-2 text-xs">
        <input
          type="checkbox"
          className="mt-0.5"
          checked={pc.remote_allowed}
          disabled={busy}
          onChange={(e) => void act(() => api.setRemoteAllowed(pc.id, e.target.checked), null)}
        />
        <span className="flex flex-col">
          <span>Remote kaam: {pc.name} is PC par kaam karwa sake</span>
          <span className="text-[11px] text-slate-500">
            Maloomat (RAM, battery) aur cheezein kholna; ijazat wale kaam {pc.name} par poochhe jayenge.
          </span>
        </span>
      </label>
      <span className="text-[11px] text-slate-500">
        {pc.name} ki taraf se is PC ko kaam ki ijazat:{" "}
        {pc.allows_us === null ? "abhi pata nahi" : pc.allows_us ? "haan" : `nahi (${pc.name} par on karni hogi)`}
      </span>
    </li>
  );
}
