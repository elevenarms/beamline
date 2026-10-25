import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Backend target for the /api proxy: VITE_API_TARGET=http://localhost:8001 npm run dev  (default :8000)
const env = (globalThis as unknown as { process?: { env: Record<string, string | undefined> } }).process?.env ?? {};
const API_TARGET = env.VITE_API_TARGET || "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: API_TARGET, changeOrigin: true },
    },
  },
  build: { chunkSizeWarningLimit: 2500 },
});
