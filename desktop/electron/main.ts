import { app, BrowserWindow, ipcMain, Menu, nativeImage, session, shell, Tray } from "electron";
import type { ChildProcess } from "node:child_process";
import path from "node:path";
import { BACKEND_URL, backendSettings, ensureBackend, installedDataDir } from "./backend";

const devServerUrl = process.env.NOVA_DEV_SERVER_URL;
// Started by Windows at login ("start with Windows"): silent mode stays in the tray.
const launchedAtLogin = process.argv.includes("--startup");
// Tests/automation can make the window's X really quit instead of hiding to the tray.
const quitOnClose = process.env.NOVA_QUIT_ON_CLOSE === "1";
let backendProcess: ChildProcess | null = null;
let mainWindow: BrowserWindow | null = null;
let tray: Tray | null = null;
let quitting = false;
let trayHintShown = false;

if (app.isPackaged) {
  // Everything NOVA keeps lives under %LOCALAPPDATA%\NOVA (the uninstaller can remove it in one go).
  app.setPath("userData", path.join(path.dirname(installedDataDir()), "ui"));
}

function showWindow(): void {
  if (!mainWindow) return;
  if (mainWindow.isMinimized()) mainWindow.restore();
  mainWindow.show();
  mainWindow.focus();
}

function createWindow(visible: boolean): void {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 880,
    minWidth: 1024,
    minHeight: 680,
    show: visible,
    backgroundColor: "#05070d",
    title: "NOVA",
    icon: path.join(__dirname, "..", "build-resources", "tray@2x.png"),
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      // NOVA speaks replies to voice commands without a click in between.
      autoplayPolicy: "no-user-gesture-required",
      // In the tray (hidden window) the microphone still has to hear the wake word.
      backgroundThrottling: false,
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
  // X hides NOVA to the tray (it keeps listening for the wake word); "Band karein" in the tray quits.
  mainWindow.on("close", (event) => {
    if (quitting || quitOnClose || !tray) return;
    event.preventDefault();
    mainWindow?.hide();
    if (!trayHintShown) {
      trayHintShown = true;
      tray.displayBalloon({
        iconType: "info",
        title: "NOVA tray mein chal raha hai",
        content: "Wapas kholne ke liye tray icon par click karein. Band karne ke liye right-click → Band karein.",
      });
    }
  });
  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

function createTray(): void {
  const icon = nativeImage.createFromPath(path.join(__dirname, "..", "build-resources", "tray.png"));
  tray = new Tray(icon);
  tray.setToolTip("NOVA");
  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: "NOVA kholo", click: showWindow },
      { type: "separator" },
      {
        label: "Band karein",
        click: () => {
          quitting = true;
          app.quit();
        },
      },
    ]),
  );
  tray.on("click", showWindow);
}

/** Windows login: register NOVA (installed only - a development copy must not start itself). */
function applyStartup(openAtLogin: boolean): { applied: boolean; reason?: string } {
  if (!app.isPackaged) return { applied: false, reason: "dev" };
  app.setLoginItemSettings({ openAtLogin, name: "NOVA", path: process.execPath, args: ["--startup"] });
  return { applied: app.getLoginItemSettings({ path: process.execPath, args: ["--startup"] }).openAtLogin === openAtLogin };
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
  app.on("second-instance", showWindow);

  // NOVA needs an answer (permission): bring its window forward even if another app is in front.
  ipcMain.handle("nova:attention", () => {
    if (!mainWindow) return;
    showWindow();
    mainWindow.flashFrame(true);
    setTimeout(() => mainWindow?.flashFrame(false), 3000);
  });

  ipcMain.handle("nova:get-info", () => ({
    appVersion: app.getVersion(),
    platform: process.platform,
    backendUrl: BACKEND_URL,
    backendManaged: backendProcess !== null,
    packaged: app.isPackaged,
    launchedAtLogin,
  }));

  ipcMain.handle("nova:set-startup", (_e, openAtLogin: unknown) => applyStartup(openAtLogin === true));
  ipcMain.handle("nova:open-folder", (_e, which: unknown) => {
    const target = which === "program" ? path.dirname(process.execPath) : app.isPackaged ? installedDataDir() : null;
    return target ? shell.openPath(target) : "dev";
  });

  app.whenReady().then(async () => {
    configurePermissions();
    backendProcess = await ensureBackend(app.getAppPath(), app.isPackaged);
    const settings = await backendSettings();
    // Keep Windows in step with the setting (it may have been changed while NOVA was closed).
    if (settings && typeof settings.start_with_windows === "boolean") applyStartup(settings.start_with_windows);
    createTray();
    const silent = launchedAtLogin && settings?.startup_mode === "silent";
    createWindow(!silent);
    if (silent) {
      tray?.displayBalloon({ iconType: "info", title: "NOVA online hai", content: "Background mein \"Hey NOVA\" ka intezar." });
    }
    app.on("activate", () => {
      if (BrowserWindow.getAllWindows().length === 0) createWindow(true);
    });
  });

  app.on("before-quit", () => {
    quitting = true;
  });
  app.on("window-all-closed", () => {
    if (process.platform !== "darwin") app.quit();
  });
  app.on("will-quit", stopBackend);
}
