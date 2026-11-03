import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // changeOrigin: false で Host をブラウザのまま渡す（文字列の省略形は true になり、
      // Host が 127.0.0.1:8000 に書き換わって医師 API の同一オリジンの検査で 403 になる）
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: false },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: "src/test/setup.ts",
    globals: true,
  },
});
