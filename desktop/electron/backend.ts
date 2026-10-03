import { spawn, type ChildProcess } from "node:child_process";
import { existsSync, mkdirSync } from "node:fs";
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

/** Where NOVA keeps the user's data when installed: database, browser profile, screenshots (not the program). */
export function installedDataDir(): string {
  return path.join(process.env.LOCALAPPDATA ?? path.join(process.env.USERPROFILE ?? ".", "AppData", "Local"), "NOVA", "data");
}

interface Launch {
  python: string;
  cwd: string;
  env: NodeJS.ProcessEnv;
}

/** Installed NOVA: the private Python and the backend shipped next to the app (resources/), models read-only there. */
function installedLaunch(): Launch {
  const resources = process.resourcesPath;
  const dataDir = installedDataDir();
  mkdirSync(dataDir, { recursive: true });
  // Never let the user's own Python settings leak into NOVA's private runtime.
  const env: NodeJS.ProcessEnv = Object.fromEntries(
    Object.entries(process.env).filter(([k]) => !k.toUpperCase().startsWith("PYTHON") && k.toUpperCase() !== "VIRTUAL_ENV"),
  );
  return {
    python: path.join(resources, "python", "python.exe"),
    cwd: path.join(resources, "backend"),
    env: {
      ...env,
      PYTHONUNBUFFERED: "1",
      PYTHONNOUSERSITE: "1",
      NOVA_PACKAGED: "1",
      NOVA_DATA_DIR: dataDir,
      NOVA_MODELS_DIR: path.join(resources, "models"),
    },
  };
}

/** Development: the repository's backend and its .venv. */
function devLaunch(appPath: string): Launch {
  const backendDir = process.env.NOVA_BACKEND_DIR ?? path.resolve(appPath, "..", "backend");
  const venvPython = path.join(backendDir, ".venv", "Scripts", "python.exe");
  return {
    python: existsSync(venvPython) ? venvPython : "python",
    cwd: backendDir,
    env: { ...process.env, PYTHONUNBUFFERED: "1" },
  };
}

/**
 * Starts the Python backend unless one is already running (e.g. started manually by the developer).
 * Returns the child process only when Electron owns it, so it is stopped on quit.
 */
export async function ensureBackend(appPath: string, packaged: boolean): Promise<ChildProcess | null> {
  if (await isBackendHealthy()) return null;

  const launch = packaged ? installedLaunch() : devLaunch(appPath);
  const child = spawn(launch.python, ["-m", "nova"], { cwd: launch.cwd, env: launch.env, windowsHide: true });
  child.stdout?.on("data", (d: Buffer) => process.stdout.write(`[backend] ${d}`));
  child.stderr?.on("data", (d: Buffer) => process.stderr.write(`[backend] ${d}`));
  child.on("error", (err) => console.error("[backend] failed to start:", err.message));

  // The first start of an installed NOVA loads the voice and AI libraries from disk: give it time.
  const deadline = Date.now() + (packaged ? 90_000 : 20_000);
  while (Date.now() < deadline && child.exitCode === null) {
    if (await isBackendHealthy()) break;
    await new Promise((r) => setTimeout(r, 300));
  }
  return child;
}

export async function backendSettings(): Promise<Record<string, unknown> | null> {
  try {
    const res = await fetch(`${BACKEND_URL}/api/settings`, { signal: AbortSignal.timeout(3000) });
    return res.ok ? ((await res.json()) as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}
