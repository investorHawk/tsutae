import { vi, type Mock } from "vitest";

export type FetchMock = Mock<
  (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>
>;

/** JSON 本文の Response を作る（Node 20 の Response を使う）。 */
export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** fetch を差し替える。戻り値の mock で呼び出しを検査する。 */
export function mockFetch(
  impl: (url: string, init?: RequestInit) => Response | Promise<Response>,
): FetchMock {
  const mock: FetchMock = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit) =>
      impl(String(input), init),
  );
  vi.stubGlobal("fetch", mock);
  return mock;
}

/** n 回目（0 始まり）の呼び出しの URL・メソッド・本文。 */
export function callOf(
  mock: FetchMock,
  n = 0,
): { url: string; method: string; body: unknown; init: RequestInit } {
  const call = mock.mock.calls[n];
  if (!call) {
    throw new Error(`fetch の ${n} 回目の呼び出しが無い`);
  }
  const [input, init = {}] = call;
  const raw = init.body;
  return {
    url: String(input),
    method: init.method ?? "GET",
    body: typeof raw === "string" ? JSON.parse(raw) : raw,
    init,
  };
}

/**
 * 応答を返さない fetch（タイムアウトの検査用）。init.signal が abort されたら
 * 本物の fetch と同じく AbortError で失敗する。
 */
export function hangingFetch(): FetchMock {
  return mockFetch(
    (_url, init) =>
      new Promise<Response>((_resolve, reject) => {
        const signal = init?.signal;
        if (!signal) {
          return;
        }
        signal.addEventListener("abort", () =>
          reject(new DOMException("The operation was aborted.", "AbortError")),
        );
      }),
  );
}
