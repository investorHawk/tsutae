import { afterEach, describe, expect, it } from "vitest";
import { callOf, jsonResponse, mockFetch } from "../test/fetchMock";
import {
  ApiError,
  INVALID_RESPONSE,
  NETWORK_ERROR,
  UNKNOWN_ERROR,
  getJson,
  postJson,
} from "./http";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("getJson", () => {
  it("GET で Cookie を送り JSON を返す", async () => {
    const fetchMock = mockFetch(() => jsonResponse({ ok: true }));
    const data = await getJson<{ ok: boolean }>("/api/x");
    expect(data).toEqual({ ok: true });
    const call = callOf(fetchMock);
    expect(call.url).toBe("/api/x");
    expect(call.method).toBe("GET");
    expect(call.init.credentials).toBe("include");
    expect(call.init.body).toBeUndefined();
    const headers = new Headers(call.init.headers);
    expect(headers.get("Accept")).toBe("application/json");
    expect(headers.get("Content-Type")).toBeNull();
  });
});

describe("postJson", () => {
  it("POST で JSON 本文と Content-Type を送る", async () => {
    const fetchMock = mockFetch(() => jsonResponse({ id: 1 }));
    const data = await postJson<{ id: number }>("/api/y", { a: 1 });
    expect(data).toEqual({ id: 1 });
    const call = callOf(fetchMock);
    expect(call.method).toBe("POST");
    expect(call.body).toEqual({ a: 1 });
    expect(call.init.credentials).toBe("include");
    const headers = new Headers(call.init.headers);
    expect(headers.get("Content-Type")).toBe("application/json");
  });

  it("本文なしの POST は body を付けない", async () => {
    const fetchMock = mockFetch(() => jsonResponse({ ok: true }));
    await postJson("/api/z");
    const call = callOf(fetchMock);
    expect(call.init.body).toBeUndefined();
    expect(new Headers(call.init.headers).get("Content-Type")).toBeNull();
  });

  it("引数のオブジェクトを書き換えない", async () => {
    mockFetch(() => jsonResponse({ ok: true }));
    const body = Object.freeze({ nested: Object.freeze({ v: 1 }) });
    await postJson("/api/z", body);
    expect(body).toEqual({ nested: { v: 1 } });
  });
});

describe("ApiError", () => {
  it("失敗時は {error} の code と status を持つ", async () => {
    mockFetch(() => jsonResponse({ error: "unknown_patient" }, 404));
    const err = await getJson("/api/a").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toBeInstanceOf(Error);
    expect((err as ApiError).code).toBe("unknown_patient");
    expect((err as ApiError).status).toBe(404);
  });

  it("本文が JSON でなければ unknown_error", async () => {
    mockFetch(() => new Response("Internal Server Error", { status: 500 }));
    const err = await getJson("/api/a").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).code).toBe(UNKNOWN_ERROR);
    expect((err as ApiError).status).toBe(500);
  });

  it("error が文字列でなければ unknown_error", async () => {
    mockFetch(() => jsonResponse({ detail: "x" }, 401));
    const err = await postJson("/api/a", {}).catch((e: unknown) => e);
    expect((err as ApiError).code).toBe(UNKNOWN_ERROR);
    expect((err as ApiError).status).toBe(401);
  });

  it("通信できなければ status 0 の network_error", async () => {
    mockFetch(() => {
      throw new TypeError("Failed to fetch");
    });
    const err = await getJson("/api/a").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).code).toBe(NETWORK_ERROR);
    expect((err as ApiError).status).toBe(0);
  });

  it("成功でも本文が JSON でなければ invalid_response", async () => {
    mockFetch(() => new Response("<html></html>", { status: 200 }));
    const err = await getJson("/api/a").catch((e: unknown) => e);
    expect((err as ApiError).code).toBe(INVALID_RESPONSE);
    expect((err as ApiError).status).toBe(200);
  });

  it("isUnauthorized は 401 だけ true", () => {
    expect(new ApiError(401, "x").isUnauthorized).toBe(true);
    expect(new ApiError(403, "x").isUnauthorized).toBe(false);
  });
});
