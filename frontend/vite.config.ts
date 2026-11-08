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
  // 端末に見せる preview だけに付ける（開発サーバーは React のインラインの前置きが CSP に触れる）
  preview: {
    cors: false,
    headers: {
      "Content-Security-Policy":
        "default-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
      "X-Content-Type-Options": "nosniff",
      "Referrer-Policy": "no-referrer",
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: "src/test/setup.ts",
    globals: true,
  },
});
