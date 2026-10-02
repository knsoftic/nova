import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

const BACKEND = "127.0.0.1:8765";

// Strict CSP for the packaged app only; the dev server needs inline scripts for hot reload.
function productionCsp(): Plugin {
  const csp = [
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    `connect-src 'self' http://${BACKEND} ws://${BACKEND}`,
    // NOVA's spoken replies are WAV files served by the local backend.
    `media-src 'self' http://${BACKEND}`,
  ].join("; ");
  return {
    name: "nova-production-csp",
    apply: "build",
    transformIndexHtml: () => [
      { tag: "meta", attrs: { "http-equiv": "Content-Security-Policy", content: csp }, injectTo: "head-prepend" },
    ],
  };
}

export default defineConfig({
  plugins: [react(), tailwindcss(), productionCsp()],
  // Relative asset paths so the production build loads from file:// inside Electron.
  base: "./",
  server: { port: 5173, strictPort: true },
});
