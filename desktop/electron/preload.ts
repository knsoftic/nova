import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("nova", {
  getInfo: () => ipcRenderer.invoke("nova:get-info"),
  attention: () => ipcRenderer.invoke("nova:attention"),
  setStartup: (openAtLogin: boolean) => ipcRenderer.invoke("nova:set-startup", openAtLogin),
  openFolder: (which: "data" | "program") => ipcRenderer.invoke("nova:open-folder", which),
});
