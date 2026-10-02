import { app, BrowserWindow, ipcMain, shell } from "electron";
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

  ipcMain.handle("nova:get-info", () => ({
    appVersion: app.getVersion(),
    platform: process.platform,
    backendUrl: BACKEND_URL,
    backendManaged: backendProcess !== null,
  }));

  app.whenReady().then(async () => {
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
