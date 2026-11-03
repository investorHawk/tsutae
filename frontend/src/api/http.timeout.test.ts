/**
 * 通信の打ち切り（AbortController）。患者 API は 20 秒、医師 API は 30 秒、
 * D4 の依頼（POST /api/doctor/skill-changes）は 10 分。打ち切りは通信の失敗と同じ
 * ApiError(0, network_error)。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { hangingFetch, jsonResponse, mockFetch } from "../test/fetchMock";
import {
  createSkillChange,
  getPipelineEvents,
  listSkillChanges,
  listVisits,
  markPrinted,
} from "./doctor";
import { ApiError, NETWORK_ERROR, getJson, postJson } from "./http";
import {
  createEntry,
  getPatientStrings,
  getQuestions,
  listEntries,
  registerPatient,
  submitVisit,
} from "./patient";

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

/** p が ms 経っても決まらず、さらに 1ms で network_error になることを確かめる。 */
async function expectTimeoutAt(p: Promise<unknown>, ms: number) {
  let settled = false;
  const caught = p.then(
    () => {
      settled = true;
      return null;
    },
    (e: unknown) => {
      settled = true;
      return e;
    },
  );
  await vi.advanceTimersByTimeAsync(ms - 1);
  expect(settled).toBe(false);
  await vi.advanceTimersByTimeAsync(1);
  const err = await caught;
  expect(err).toBeInstanceOf(ApiError);
  expect((err as ApiError).status).toBe(0);
  expect((err as ApiError).code).toBe(NETWORK_ERROR);
}

describe("request のタイムアウト", () => {
  it("timeoutMs を過ぎたら abort し network_error", async () => {
    const fetchMock = hangingFetch();
    await expectTimeoutAt(getJson("/api/a", { timeoutMs: 1000 }), 1000);
    const init = fetchMock.mock.calls[0]?.[1];
    expect(init?.signal).toBeInstanceOf(AbortSignal);
    expect(init?.signal?.aborted).toBe(true);
  });

  it("POST も同じ", async () => {
    hangingFetch();
    await expectTimeoutAt(
      postJson("/api/b", { a: 1 }, { timeoutMs: 500 }),
      500,
    );
  });

  it("間に合った応答ではタイマーを残さない", async () => {
    mockFetch(() => jsonResponse({ ok: true }));
    await expect(getJson("/api/a", { timeoutMs: 1000 })).resolves.toEqual({
      ok: true,
    });
    expect(vi.getTimerCount()).toBe(0);
  });

  it("失敗の応答でもタイマーを残さない", async () => {
    mockFetch(() => jsonResponse({ error: "boom" }, 500));
    await expect(getJson("/api/a", { timeoutMs: 1000 })).rejects.toThrow(
      ApiError,
    );
    expect(vi.getTimerCount()).toBe(0);
  });

  it("本文の読み込みが止まっても打ち切る", async () => {
    mockFetch((_url, init) => {
      const body = new ReadableStream<Uint8Array>({
        start(controller) {
          init?.signal?.addEventListener("abort", () =>
            controller.error(new DOMException("aborted", "AbortError")),
          );
        },
      });
      return new Response(body, { status: 200 });
    });
    await expectTimeoutAt(getJson("/api/a", { timeoutMs: 1000 }), 1000);
  });
});

describe("患者 API は 20 秒で打ち切る", () => {
  const PID = "P-DEMO0001";
  it.each([
    ["registerPatient", () => registerPatient(PID)],
    ["getPatientStrings", () => getPatientStrings()],
    ["getQuestions", () => getQuestions(PID)],
    ["createEntry", () => createEntry(PID, { too_sick: true })],
    ["listEntries", () => listEntries(PID)],
    ["submitVisit", () => submitVisit("A-1")],
  ])("%s", async (_name, call) => {
    hangingFetch();
    await expectTimeoutAt(call(), 20_000);
  });
});

describe("医師 API は 30 秒、D4 の依頼は 10 分で打ち切る", () => {
  it.each([
    ["listVisits", () => listVisits()],
    ["markPrinted", () => markPrinted(1)],
    ["getPipelineEvents", () => getPipelineEvents(1)],
    ["listSkillChanges", () => listSkillChanges()],
  ])("%s は 30 秒", async (_name, call) => {
    hangingFetch();
    await expectTimeoutAt(call(), 30_000);
  });

  it("createSkillChange は 10 分", async () => {
    hangingFetch();
    await expectTimeoutAt(
      createSkillChange("regimen-folfox", "x"),
      10 * 60 * 1000,
    );
  });
});
