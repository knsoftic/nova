import { app, BrowserWindow, ipcMain, session, shell } from "electron";
import type { ChildProcess } from "node:child_process";
import path from "node:path";
import { BACKEND_URL, ensureBackend } from "./backend";

const devServerUrl = process.env.NOVA_DEV_SERVER_URL;
let backendProcess: ChildProcess | null = null;
let mainWindow: BrowserWindow | null = null;

function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 880,
    minWidth: 1024,
    minHeight: 680,
    backgroundColor: "#05070d",
    title: "NOVA",
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      // NOVA speaks replies to voice commands without a click in between.
      autoplayPolicy: "no-user-gesture-required",
    },
  });

  // The UI must never navigate away or open arbitrary windows; external links go to the default browser.
  mainWindow.webContents.on("will-navigate", (event, url) => {
    if (devServerUrl && url.startsWith(devServerUrl)) return;
    event.preventDefault();
  });
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith("https://")) void shell.openExternal(url);
    return { action: "deny" };
  });

  if (devServerUrl) {
    void mainWindow.loadURL(devServerUrl);
  } else {
    void mainWindow.loadFile(path.join(__dirname, "..", "dist", "index.html"));
  }
  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

function isAppUrl(url: string | undefined): boolean {
  if (!url) return false;
  return devServerUrl ? url.startsWith(devServerUrl) : url.startsWith("file://");
}

/** Microphone only, only for NOVA's own page. Camera, location, notifications etc. stay denied. */
function configurePermissions(): void {
  session.defaultSession.setPermissionRequestHandler((_wc, permission, callback, details) => {
    const mediaTypes = "mediaTypes" in details ? (details.mediaTypes ?? []) : [];
    const audioOnly = mediaTypes.length > 0 && mediaTypes.every((t) => t === "audio");
    callback(permission === "media" && audioOnly && isAppUrl(details.requestingUrl));
  });
  session.defaultSession.setPermissionCheckHandler((_wc, permission, requestingOrigin, details) => {
    if (permission !== "media") return false;
    const mediaType = "mediaType" in details ? details.mediaType : undefined;
    return mediaType !== "video" && isAppUrl(requestingOrigin || details.requestingUrl);
  });
}

function stopBackend(): void {
  if (backendProcess && backendProcess.exitCode === null) backendProcess.kill();
  backendProcess = null;
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });

  // NOVA needs an answer (permission): bring its window forward even if another app is in front.
  ipcMain.handle("nova:attention", () => {
    if (!mainWindow) return;
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.show();
    mainWindow.focus();
    mainWindow.flashFrame(true);
    setTimeout(() => mainWindow?.flashFrame(false), 3000);
  });

  ipcMain.handle("nova:get-info", () => ({
    appVersion: app.getVersion(),
    platform: process.platform,
    backendUrl: BACKEND_URL,
    backendManaged: backendProcess !== null,
  }));

  app.whenReady().then(async () => {
    configurePermissions();
    backendProcess = await ensureBackend(app.getAppPath());
    createWindow();
    app.on("activate", () => {
      if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });
  });

  app.on("window-all-closed", () => {
    if (process.platform !== "darwin") app.quit();
  });
  app.on("will-quit", stopBackend);
}
