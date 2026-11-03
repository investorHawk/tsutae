/**
 * 医師画面のテスト用（本番コードからは import しない）。
 * 経路つきで1ページを描き、API を「メソッド 経路」ごとの偽の応答で差し替える。
 */
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import {
  callOf,
  jsonResponse,
  mockFetch,
  type FetchMock,
} from "../../test/fetchMock";

function Where() {
  const location = useLocation();
  const from = (location.state as { from?: unknown } | null)?.from;
  return (
    <span data-testid="where" data-from={typeof from === "string" ? from : ""}>
      {location.pathname}
    </span>
  );
}

/** path を開き、routePath の Route に element を置く。今の経路は data-testid="where"。 */
export function renderRoute(
  path: string,
  routePath: string,
  element: ReactElement,
  state?: unknown,
) {
  return render(
    <MemoryRouter initialEntries={[{ pathname: path, state }]}>
      <Routes>
        <Route path={routePath} element={element} />
        <Route path="*" element={null} />
      </Routes>
      <Where />
    </MemoryRouter>,
  );
}

/** 値が関数なら (本文) => Response、それ以外は 200 の JSON 本文。 */
export type RouteValue =
  | ((body: unknown) => Response | Promise<Response>)
  | object;

/** "GET /api/doctor/visits" のようなキーで応答を決める。無いキーは 404 not_found。 */
export function mockApi(routes: Record<string, RouteValue>): FetchMock {
  return mockFetch((url, init) => {
    const key = `${init?.method ?? "GET"} ${url}`;
    const value = routes[key];
    if (value === undefined) {
      return jsonResponse({ error: "not_found" }, 404);
    }
    if (typeof value === "function") {
      const raw = init?.body;
      return value(typeof raw === "string" ? JSON.parse(raw) : undefined);
    }
    return jsonResponse(value);
  });
}

/** key（"POST /api/..."）への呼び出しの本文を順に返す。 */
export function bodiesOf(mock: FetchMock, key: string): unknown[] {
  return mock.mock.calls
    .map((_, n) => callOf(mock, n))
    .filter((call) => `${call.method} ${call.url}` === key)
    .map((call) => call.body);
}

export function countOf(mock: FetchMock, key: string): number {
  return bodiesOf(mock, key).length;
}

/** 外から解決できる Promise（「生成中」の表示を確かめる用）。 */
export function deferred<T>(): {
  promise: Promise<T>;
  resolve: (value: T) => void;
} {
  let resolve: (value: T) => void = () => {};
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}
