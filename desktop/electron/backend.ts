import { spawn, type ChildProcess } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";

export const BACKEND_URL = "http://127.0.0.1:8765";

export async function isBackendHealthy(): Promise<boolean> {
  try {
    const res = await fetch(`${BACKEND_URL}/api/health`, { signal: AbortSignal.timeout(1000) });
    return res.ok;
  } catch {
    return false;
  }
}

function resolvePython(backendDir: string): string {
  const venvPython = path.join(backendDir, ".venv", "Scripts", "python.exe");
  return existsSync(venvPython) ? venvPython : "python";
}

/**
 * Starts the Python backend unless one is already running (e.g. started manually by the developer).
 * Returns the child process only when Electron owns it, so it is stopped on quit.
 */
export async function ensureBackend(appPath: string): Promise<ChildProcess | null> {
  if (await isBackendHealthy()) return null;

  const backendDir = process.env.NOVA_BACKEND_DIR ?? path.resolve(appPath, "..", "backend");
  const python = resolvePython(backendDir);
  const child = spawn(python, ["-m", "nova"], {
    cwd: backendDir,
    env: { ...process.env, PYTHONUNBUFFERED: "1" },
    windowsHide: true,
  });
  child.stdout?.on("data", (d: Buffer) => process.stdout.write(`[backend] ${d}`));
  child.stderr?.on("data", (d: Buffer) => process.stderr.write(`[backend] ${d}`));
  child.on("error", (err) => console.error("[backend] failed to start:", err.message));

  const deadline = Date.now() + 20_000;
  while (Date.now() < deadline && child.exitCode === null) {
    if (await isBackendHealthy()) break;
    await new Promise((r) => setTimeout(r, 300));
  }
  return child;
}
