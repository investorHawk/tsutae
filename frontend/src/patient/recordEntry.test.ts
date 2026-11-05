import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/http";
import type {
  DeviceEntry,
  EntryCreate,
  QuestionsResponse,
  RecordMarkResponse,
} from "../api/types";
import { apiFixture } from "../test/apiFixtures";
import { jsonResponse, mockFetch, type FetchMock } from "../test/fetchMock";
import { listDeviceEntries, saveDeviceEntry } from "./deviceStore";
import {
  newClientEntryId,
  recordEntry,
  toDeviceEntry,
  undoRecord,
} from "./recordEntry";

const PID = "P-DEMO0001";
const ID = "11111111-1111-4111-8111-111111111111";
const MARK_URL = `/api/patient/${PID}/record-marks`;
const UNDO_URL = `${MARK_URL}/undo`;
const QUESTIONS = apiFixture("patient_questions").body as QuestionsResponse;
const MARK = apiFixture("patient_record_mark").body as RecordMarkResponse;
/** 受付の検査と同じ ID の形（backend の visit_entries.py）。 */
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

const ANSWERED: EntryCreate = {
  by_proxy: true,
  answers: [
    { question_key: "diarrhea", value: "hard" },
    { question_key: "fever", value: "measured", temperature: 38.2 },
  ],
  free_text: "note",
};

function deviceEntry(id: string, overrides: Partial<DeviceEntry> = {}) {
  return {
    ...toDeviceEntry(PID, id, { too_sick: true }, QUESTIONS, MARK),
    ...overrides,
  };
}

function mockMarks(): FetchMock {
  return mockFetch((url) =>
    url === MARK_URL
      ? jsonResponse(MARK)
      : url === UNDO_URL
        ? jsonResponse({ ok: true })
        : jsonResponse({ error: "not_found" }, 404),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("newClientEntryId", () => {
  it("受付の検査に通る小文字の UUID で、毎回違う", () => {
    const a = newClientEntryId();
    expect(a).toMatch(UUID);
    expect(a[14]).toBe("4");
    expect("89ab").toContain(a[19]);
    expect(newClientEntryId()).not.toBe(a);
  });
});

describe("toDeviceEntry", () => {
  it("時刻は印の応答、版は質問集、質問の文の写しを持つ", () => {
    expect(toDeviceEntry(PID, ID, ANSWERED, QUESTIONS, MARK)).toEqual({
      pid: PID,
      client_entry_id: ID,
      recorded_at: MARK.recorded_at,
      record_date: MARK.record_date,
      kind: "mixed",
      by_proxy: true,
      skill_version: QUESTIONS.skill_version,
      answers: [
        {
          question_key: "diarrhea",
          value: "hard",
          temperature: null,
          question_text: "下痢はありましたか",
        },
        {
          question_key: "fever",
          value: "measured",
          temperature: 38.2,
          question_text: "熱を測りましたか",
        },
      ],
      free_text: "note",
    });
  });

  it.each<[string, EntryCreate, DeviceEntry["kind"]]>([
    ["つらくて書けない", { too_sick: true }, "too_sick"],
    ["回答だけ", { answers: ANSWERED.answers }, "answers"],
    ["自由記載だけ", { answers: [], free_text: "note" }, "free_text"],
    ["両方", ANSWERED, "mixed"],
  ])("種類は backend と同じ: %s", (_label, entry, kind) => {
    expect(toDeviceEntry(PID, ID, entry, QUESTIONS, MARK).kind).toBe(kind);
  });

  it("質問集に無い質問の文は null（引数は書き換えない）", () => {
    const entry: EntryCreate = {
      answers: [{ question_key: "gone", value: "none" }],
    };
    const before = structuredClone(entry);
    const saved = toDeviceEntry(PID, ID, entry, QUESTIONS, MARK);
    expect(saved.answers[0]!.question_text).toBeNull();
    expect(entry).toEqual(before);
  });
});

describe("recordEntry", () => {
  it("印を本文なしで付けてから、応答の時刻で端末に保存する", async () => {
    const fetchMock = mockMarks();
    const saved = await recordEntry(PID, ID, ANSWERED, QUESTIONS);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(String(url)).toBe(MARK_URL);
    expect(init?.method).toBe("POST");
    expect(init?.body).toBeUndefined();
    await expect(listDeviceEntries(PID)).resolves.toEqual([saved]);
    expect(saved.recorded_at).toBe(MARK.recorded_at);
  });

  it("印が失敗したら端末に保存しない", async () => {
    mockFetch(() => jsonResponse({ error: "boom" }, 500));
    await expect(
      recordEntry(PID, ID, ANSWERED, QUESTIONS),
    ).rejects.toBeInstanceOf(ApiError);
    await expect(listDeviceEntries(PID)).resolves.toEqual([]);
  });

  it("保存が失敗したら例外。押し直すと同じ ID の1件になる", async () => {
    mockMarks();
    const put = vi
      .spyOn(IDBObjectStore.prototype, "put")
      .mockImplementationOnce(() => {
        throw new DOMException("full", "QuotaExceededError");
      });
    await expect(
      recordEntry(PID, ID, ANSWERED, QUESTIONS),
    ).rejects.toMatchObject({ name: "QuotaExceededError" });
    await expect(listDeviceEntries(PID)).resolves.toEqual([]);
    put.mockRestore();
    await recordEntry(PID, ID, ANSWERED, QUESTIONS);
    await recordEntry(PID, ID, ANSWERED, QUESTIONS);
    await expect(listDeviceEntries(PID)).resolves.toHaveLength(1);
  });
});

describe("undoRecord", () => {
  function undoBody(fetchMock: FetchMock): unknown {
    const init = fetchMock.mock.calls[0]![1];
    return JSON.parse(String(init?.body));
  }

  it("その日に他の記録が無ければ clear_mark: true で送り、端末の記録を消す", async () => {
    const fetchMock = mockMarks();
    const entry = deviceEntry(ID);
    await saveDeviceEntry(entry);
    await undoRecord(entry);
    expect(String(fetchMock.mock.calls[0]![0])).toBe(UNDO_URL);
    expect(undoBody(fetchMock)).toEqual({
      recorded_at: MARK.recorded_at,
      clear_mark: true,
    });
    await expect(listDeviceEntries(PID)).resolves.toEqual([]);
  });

  it("押し直して付けた記録は retried: true を添える", async () => {
    const fetchMock = mockMarks();
    const entry = deviceEntry(ID);
    await saveDeviceEntry(entry);
    await undoRecord(entry, { retried: true });
    expect(undoBody(fetchMock)).toEqual({
      recorded_at: MARK.recorded_at,
      clear_mark: true,
      retried: true,
    });
    await expect(listDeviceEntries(PID)).resolves.toEqual([]);
  });

  it("その日に他の記録があれば clear_mark: false", async () => {
    const fetchMock = mockMarks();
    const entry = deviceEntry(ID);
    const other = deviceEntry("other");
    await saveDeviceEntry(entry);
    await saveDeviceEntry(other);
    await undoRecord(entry);
    expect(undoBody(fetchMock)).toMatchObject({ clear_mark: false });
    await expect(listDeviceEntries(PID)).resolves.toEqual([other]);
  });

  it("別の日の記録・他の患者の記録は数えない", async () => {
    const fetchMock = mockMarks();
    const entry = deviceEntry(ID);
    await saveDeviceEntry(entry);
    await saveDeviceEntry(deviceEntry("before", { record_date: "2026-11-08" }));
    await saveDeviceEntry(deviceEntry("theirs", { pid: "P-EVAL0001" }));
    await undoRecord(entry);
    expect(undoBody(fetchMock)).toMatchObject({ clear_mark: true });
  });

  it("サーバーが断ったら端末の記録を残す", async () => {
    mockFetch(() => jsonResponse({ error: "not_undoable" }, 409));
    const entry = deviceEntry(ID);
    await saveDeviceEntry(entry);
    await expect(undoRecord(entry)).rejects.toMatchObject({ status: 409 });
    await expect(listDeviceEntries(PID)).resolves.toEqual([entry]);
  });

  it("端末の記録を消せなければ例外", async () => {
    mockMarks();
    const entry = deviceEntry(ID);
    await saveDeviceEntry(entry);
    vi.spyOn(IDBObjectStore.prototype, "get").mockImplementationOnce(() => {
      throw new DOMException("denied", "UnknownError");
    });
    await expect(undoRecord(entry)).rejects.toMatchObject({
      name: "UnknownError",
    });
  });
});
