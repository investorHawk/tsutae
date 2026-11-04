/**
 * 開発の proxy は Host を書き換えない（changeOrigin: false）。書き換えると、医師 API の
 * 同一オリジンの検査（Origin と Host の照合）で全ての POST が 403 cross_origin になる。
 * ブラウザでの通し確認（2026-11-04）で見つけた不具合の回帰テスト。
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const config = readFileSync(resolve(__dirname, "../../vite.config.ts"), "utf8");

describe("vite.config.ts", () => {
  it("proxies /api to 127.0.0.1:8000 without changing the Host header", () => {
    expect(config).toMatch(
      /"\/api":\s*\{\s*target:\s*"http:\/\/127\.0\.0\.1:8000",\s*changeOrigin:\s*false\s*\}/,
    );
  });
});
