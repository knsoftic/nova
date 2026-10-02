import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("nova", {
  getInfo: () => ipcRenderer.invoke("nova:get-info"),
});
