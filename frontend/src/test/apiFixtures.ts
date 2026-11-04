/**
 * 実際の FastAPI の応答（scripts/dump_api_fixtures.py が書く fixture）を読む。テスト専用。
 * 1件は {method, path, request, status, body}。失敗の body は {"error": code}。
 * backend/tests/test_dump_api_fixtures.py が「fixture が今の API の出力と同じ」ことを確かめる。
 */

export interface ApiFixture {
  method: "GET" | "POST" | "DELETE";
  path: string;
  /** 送った本文（無ければ null） */
  request: unknown;
  status: number;
  body: unknown;
}

const modules = import.meta.glob<ApiFixture>("./fixtures/api/*.json", {
  eager: true,
  import: "default",
});

function nameOf(path: string): string {
  return path.replace(/^.*\//, "").replace(/\.json$/, "");
}

const FIXTURES: Readonly<Record<string, ApiFixture>> = Object.freeze(
  Object.fromEntries(
    Object.entries(modules).map(([path, data]) => [nameOf(path), data]),
  ),
);

/** fixture の名前（ファイル名から .json を除いたもの）の一覧（名前順）。 */
export function fixtureNames(): string[] {
  return Object.keys(FIXTURES).sort();
}

/** 名前の fixture。無ければ例外（名前の打ち間違いを黙って通さない）。 */
export function apiFixture(name: string): ApiFixture {
  const found = FIXTURES[name];
  if (!found) {
    throw new Error(`API の fixture が無い: ${name}`);
  }
  return found;
}

/** 名前の fixture の body を深く写したもの（壊す試験で元を書き換えないように）。 */
export function fixtureBody(name: string): unknown {
  return structuredClone(apiFixture(name).body);
}
