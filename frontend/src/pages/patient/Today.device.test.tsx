/**
 * P1 記録の順序（docs/plan-device-records.md §5.2・§5.4）: 印 → 端末に保存 → 完了。
 * サーバーへ送るのは印だけで、回答・体温・自由記載は送らない。
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DeviceEntry } from "../../api/types";
import { listDeviceEntries } from "../../patient/deviceStore";
import { clearPid, savePid } from "../../patient/pid";
import { jsonResponse } from "../../test/fetchMock";
import History from "./History";
import { MARK, callsTo, mockPatientApi } from "./testing/api";
import { seedDevice } from "./testing/device";
import {
  ENTRIES,
  FILE_SEPARATOR,
  LONE_SURROGATE,
  NEXT_LINE,
  PID,
  QUESTIONS_RESPONSE,
  questionText,
  s,
} from "./testing/fixtures";
import { renderPatient } from "./testing/render";
import Today from "./Today";

const MARK_URL = `/api/patient/${PID}/record-marks`;
const UNDO_URL = `${MARK_URL}/undo`;
const FREE_TEXT = "free text sample";
const UUID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

function renderToday() {
  return renderPatient(
    [
      { path: "/today", element: <Today /> },
      { path: "/history", element: <History /> },
    ],
    "/today",
  );
}

function button(key: string) {
  return screen.getByRole("button", { name: s(key) });
}

async function choose(key: string, answerKey: string) {
  const group = await screen.findByRole("group", { name: questionText(key) });
  await userEvent.click(
    within(group).getByRole("button", { name: s(answerKey) }),
  );
}

async function pressTooSick() {
  await userEvent.click(
    await screen.findByRole("button", { name: s("today.too_sick_button") }),
  );
  await userEvent.click(button("today.too_sick_confirm_yes"));
}

async function recordTooSick() {
  await pressTooSick();
  await screen.findByText(s("today.too_sick_done"));
}

/** put が1回失敗する。失敗した分の ID を返す関数を返す。 */
function failNextPut(): () => string | undefined {
  let attempted: string | undefined;
  vi.spyOn(IDBObjectStore.prototype, "put").mockImplementationOnce((value) => {
    attempted = (value as DeviceEntry).client_entry_id;
    throw new DOMException("full", "QuotaExceededError");
  });
  return () => attempted;
}

function isPressed(key: string, answerKey: string): void {
  const group = screen.getByRole("group", { name: questionText(key) });
  expect(
    within(group).getByRole("button", { name: s(answerKey) }),
  ).toHaveAttribute("aria-pressed", "true");
}

beforeEach(() => {
  clearPid();
  savePid(PID);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("Today: the order of recording", () => {
  async function recordAll() {
    await choose("diarrhea", "answer.hard");
    await choose("fever", "answer.measured");
    await userEvent.type(
      screen.getByRole("textbox", { name: s("temperature.label") }),
      "38.2",
    );
    await userEvent.type(
      screen.getByRole("textbox", { name: s("today.free_text_label") }),
      FREE_TEXT,
    );
    await userEvent.click(button("today.submit"));
    await screen.findByText(s("today.saved"));
  }

  it("saves the time and date of the mark, the version and the question texts", async () => {
    mockPatientApi();
    renderToday();
    await recordAll();
    const [saved] = await listDeviceEntries(PID);
    expect(saved!.client_entry_id).toMatch(UUID);
    expect(saved).toEqual({
      pid: PID,
      client_entry_id: saved!.client_entry_id,
      recorded_at: MARK.recorded_at,
      record_date: MARK.record_date,
      kind: "mixed",
      by_proxy: false,
      skill_version: "regimen-folfox@1",
      answers: [
        {
          question_key: "diarrhea",
          value: "hard",
          temperature: null,
          question_text: questionText("diarrhea"),
        },
        {
          question_key: "fever",
          value: "measured",
          temperature: 38.2,
          question_text: questionText("fever"),
        },
      ],
      free_text: FREE_TEXT,
    });
  });

  it("sends the server only an empty mark (no answers, temperature or free text)", async () => {
    const fetchMock = mockPatientApi();
    renderToday();
    await recordAll();
    expect(callsTo(fetchMock, "POST", MARK_URL)).toEqual([undefined]);
    const everything = JSON.stringify(
      fetchMock.mock.calls.map(([url, init]) => [String(url), init?.body]),
    );
    expect(everything).not.toContain(FREE_TEXT);
    expect(everything).not.toContain("38.2");
    expect(everything).not.toContain("diarrhea");
  });

  it("the fever notice comes from the rule in GET questions", async () => {
    mockPatientApi();
    renderToday();
    await recordAll();
    expect(screen.getByRole("alert").textContent).toBe(
      s("fixed_rule.fever_38"),
    );
  });

  it("too_sick is saved without answers", async () => {
    mockPatientApi();
    renderToday();
    await recordTooSick();
    const [saved] = await listDeviceEntries(PID);
    expect(saved).toMatchObject({
      kind: "too_sick",
      answers: [],
      free_text: null,
      recorded_at: MARK.recorded_at,
    });
  });

  it("the saved record is on the history page", async () => {
    mockPatientApi();
    renderToday();
    await recordAll();
    await userEvent.click(screen.getByRole("link", { name: s("nav.history") }));
    expect(await screen.findByText(FREE_TEXT)).toBeInTheDocument();
  });
});

describe("Today: when recording fails", () => {
  it("the mark fails: error.generic, input kept, nothing saved", async () => {
    mockPatientApi({
      recordMark: () => jsonResponse({ error: "boom" }, 500),
    });
    renderToday();
    await choose("diarrhea", "answer.present");
    await userEvent.click(button("today.submit"));
    expect(await screen.findByText(s("error.generic"))).toBeInTheDocument();
    isPressed("diarrhea", "answer.present");
    await expect(listDeviceEntries(PID)).resolves.toEqual([]);
  });

  it("saving fails: error.generic, input kept; pressing again keeps the same id", async () => {
    const fetchMock = mockPatientApi();
    const attempted = failNextPut();
    renderToday();
    await choose("diarrhea", "answer.present");
    await userEvent.click(button("today.submit"));
    expect(await screen.findByText(s("error.generic"))).toBeInTheDocument();
    isPressed("diarrhea", "answer.present");
    expect(screen.queryByText(s("today.saved"))).toBeNull();
    await expect(listDeviceEntries(PID)).resolves.toEqual([]);

    await userEvent.click(button("today.submit"));
    await screen.findByText(s("today.saved"));
    const saved = await listDeviceEntries(PID);
    expect(saved).toHaveLength(1);
    expect(saved[0]!.client_entry_id).toBe(attempted());
    expect(callsTo(fetchMock, "POST", MARK_URL)).toHaveLength(2);
  });

  describe("undo after pressing again (the first mark may be on the server)", () => {
    const FIRST = "2026-11-09T20:00:00.000000+09:00";
    const SECOND = "2026-11-09T20:00:30.000000+09:00";

    /** 呼ぶたびに時刻が進む印と、取り消しの本文の控え。 */
    function mockAdvancingMarks(first: () => Promise<Response> | Response) {
      const undone: unknown[] = [];
      let calls = 0;
      const fetchMock = mockPatientApi({
        recordMark: () => {
          calls += 1;
          return calls === 1
            ? first()
            : jsonResponse({ ...MARK, recorded_at: SECOND });
        },
        undo: (body) => {
          undone.push(body);
          return jsonResponse({ ok: true });
        },
      });
      return { fetchMock, undone };
    }

    async function pressUndo() {
      await userEvent.click(button("today.undo"));
      await screen.findByText(s("today.undone"));
    }

    it("the save failed: the undo says so, with the time of the second mark", async () => {
      const { fetchMock, undone } = mockAdvancingMarks(() =>
        jsonResponse({ ...MARK, recorded_at: FIRST }),
      );
      failNextPut();
      renderToday();
      await pressTooSick();
      await screen.findByRole("alert");
      await recordTooSick();
      await pressUndo();
      expect(callsTo(fetchMock, "POST", MARK_URL)).toHaveLength(2);
      expect(undone).toEqual([
        { recorded_at: SECOND, clear_mark: true, retried: true },
      ]);
      await expect(listDeviceEntries(PID)).resolves.toEqual([]);
    });

    it("the reply never came: the undo says so too", async () => {
      const { undone } = mockAdvancingMarks(() =>
        Promise.reject(new TypeError("Failed to fetch")),
      );
      renderToday();
      await pressTooSick();
      await screen.findByRole("alert");
      await recordTooSick();
      await pressUndo();
      expect(undone).toEqual([
        { recorded_at: SECOND, clear_mark: true, retried: true },
      ]);
      await expect(listDeviceEntries(PID)).resolves.toEqual([]);
    });

    it("pressed once: the undo does not say it was retried", async () => {
      const { undone } = mockAdvancingMarks(() =>
        jsonResponse({ ...MARK, recorded_at: FIRST }),
      );
      renderToday();
      await recordTooSick();
      await pressUndo();
      expect(undone).toEqual([{ recorded_at: FIRST, clear_mark: true }]);
    });

    it("a new record after the undo is not a retry of the old one", async () => {
      const { undone } = mockAdvancingMarks(() =>
        Promise.reject(new TypeError("Failed to fetch")),
      );
      renderToday();
      await pressTooSick();
      await screen.findByRole("alert");
      await recordTooSick();
      await pressUndo();
      await recordTooSick();
      await pressUndo();
      expect(undone).toEqual([
        { recorded_at: SECOND, clear_mark: true, retried: true },
        { recorded_at: SECOND, clear_mark: true },
      ]);
    });

    it("a new record after add_more is not a retry of the old one", async () => {
      const { undone } = mockAdvancingMarks(() =>
        Promise.reject(new TypeError("Failed to fetch")),
      );
      renderToday();
      await pressTooSick();
      await screen.findByRole("alert");
      await recordTooSick();
      await userEvent.click(button("today.add_more"));
      await recordTooSick();
      await pressUndo();
      // 端末に前の記録があるので印は消さない。押し直しでもない
      expect(undone).toEqual([{ recorded_at: SECOND, clear_mark: false }]);
    });

    it("questions that could not be read are not a mark on the server", async () => {
      let questionCalls = 0;
      const undone: unknown[] = [];
      mockPatientApi({
        questions: () => {
          questionCalls += 1;
          return questionCalls <= 2
            ? jsonResponse({ error: "internal_error" }, 500)
            : jsonResponse(QUESTIONS_RESPONSE);
        },
        undo: (body) => {
          undone.push(body);
          return jsonResponse({ ok: true });
        },
      });
      renderToday();
      await pressTooSick();
      // 質問集の読み込みと送信の両方の失敗が出る
      await screen.findAllByRole("alert");
      await recordTooSick();
      await pressUndo();
      expect(undone).toEqual([
        { recorded_at: MARK.recorded_at, clear_mark: true },
      ]);
    });
  });

  it("too_sick that could not be saved shows the error at its button", async () => {
    mockPatientApi();
    failNextPut();
    renderToday();
    await pressTooSick();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      s("error.generic"),
    );
    expect(button("today.too_sick_button")).toBeEnabled();
  });

  it("a new record gets a new id", async () => {
    mockPatientApi();
    renderToday();
    await choose("diarrhea", "answer.present");
    await userEvent.click(button("today.submit"));
    await screen.findByText(s("today.saved"));
    await userEvent.click(button("today.add_more"));
    await choose("diarrhea", "answer.hard");
    await userEvent.click(button("today.submit"));
    await screen.findByText(s("today.saved"));
    const ids = (await listDeviceEntries(PID)).map((e) => e.client_entry_id);
    expect(new Set(ids).size).toBe(2);
  });
});

/** 受付で断られる自由記載を保存しない（1件で受診の全体が 422 になる）。貼り付けでしか入らない文字。 */
describe("Today: free text the reception would refuse", () => {
  async function paste(text: string) {
    const box = await screen.findByRole("textbox", {
      name: s("today.free_text_label"),
    });
    await userEvent.click(box);
    await userEvent.paste(text);
  }

  it.each([NEXT_LINE, FILE_SEPARATOR, LONE_SURROGATE])(
    "only %j: cannot be recorded, and no mark is sent",
    async (text) => {
      const fetchMock = mockPatientApi();
      renderToday();
      await paste(text);
      expect(button("today.submit")).toBeDisabled();
      expect(callsTo(fetchMock, "POST", MARK_URL)).toEqual([]);
      await expect(listDeviceEntries(PID)).resolves.toEqual([]);
    },
  );

  it("with an answer: saved as answers only", async () => {
    mockPatientApi();
    renderToday();
    await choose("diarrhea", "answer.hard");
    await paste(NEXT_LINE);
    await userEvent.click(button("today.submit"));
    await screen.findByText(s("today.saved"));
    const [saved] = await listDeviceEntries(PID);
    expect(saved).toMatchObject({ kind: "answers", free_text: null });
  });

  it("saves the text without those characters at the edges", async () => {
    mockPatientApi();
    renderToday();
    await paste(`${NEXT_LINE}${FREE_TEXT}${FILE_SEPARATOR}`);
    await userEvent.click(button("today.submit"));
    await screen.findByText(s("today.saved"));
    const [saved] = await listDeviceEntries(PID);
    expect(saved).toMatchObject({ kind: "free_text", free_text: FREE_TEXT });
  });
});

describe("Today: undoing too_sick", () => {
  const OTHER_TODAY: DeviceEntry = {
    ...ENTRIES[2]!,
    recorded_at: "2026-11-09T08:00:00.000000+09:00",
    record_date: MARK.record_date,
  };

  it("sends the time of the mark with clear_mark true, then removes the record", async () => {
    const fetchMock = mockPatientApi();
    renderToday();
    await recordTooSick();
    await userEvent.click(button("today.undo"));
    await screen.findByText(s("today.undone"));
    expect(callsTo(fetchMock, "POST", UNDO_URL)).toEqual([
      { recorded_at: MARK.recorded_at, clear_mark: true },
    ]);
    await expect(listDeviceEntries(PID)).resolves.toEqual([]);
  });

  it("another record that day: clear_mark false and the other record stays", async () => {
    await seedDevice([OTHER_TODAY]);
    const fetchMock = mockPatientApi();
    renderToday();
    await recordTooSick();
    await userEvent.click(button("today.undo"));
    await screen.findByText(s("today.undone"));
    expect(callsTo(fetchMock, "POST", UNDO_URL)).toEqual([
      { recorded_at: MARK.recorded_at, clear_mark: false },
    ]);
    await expect(listDeviceEntries(PID)).resolves.toEqual([OTHER_TODAY]);
  });

  it("a record on another day does not count", async () => {
    await seedDevice([ENTRIES[2]!]);
    const fetchMock = mockPatientApi();
    renderToday();
    await recordTooSick();
    await userEvent.click(button("today.undo"));
    await screen.findByText(s("today.undone"));
    expect(callsTo(fetchMock, "POST", UNDO_URL)).toEqual([
      { recorded_at: MARK.recorded_at, clear_mark: true },
    ]);
  });

  it("409: the record stays on the device", async () => {
    mockPatientApi({
      undo: () => jsonResponse({ error: "not_undoable" }, 409),
    });
    renderToday();
    await recordTooSick();
    await userEvent.click(button("today.undo"));
    await screen.findByText(s("today.undo_failed"));
    await expect(listDeviceEntries(PID)).resolves.toHaveLength(1);
  });

  it("the record cannot be removed: error.generic and pressing again finishes", async () => {
    const fetchMock = mockPatientApi();
    renderToday();
    await recordTooSick();
    vi.spyOn(IDBObjectStore.prototype, "get").mockImplementationOnce(() => {
      throw new DOMException("denied", "UnknownError");
    });
    await userEvent.click(button("today.undo"));
    expect(await screen.findByText(s("error.generic"))).toBeInTheDocument();
    expect(button("today.undo")).toBeEnabled();
    await userEvent.click(button("today.undo"));
    await screen.findByText(s("today.undone"));
    await waitFor(() =>
      expect(callsTo(fetchMock, "POST", UNDO_URL)).toHaveLength(2),
    );
    await expect(listDeviceEntries(PID)).resolves.toEqual([]);
  });

  it("after undoing, the next record gets a new id", async () => {
    mockPatientApi();
    renderToday();
    await recordTooSick();
    const [first] = await listDeviceEntries(PID);
    await userEvent.click(button("today.undo"));
    await screen.findByText(s("today.undone"));
    await recordTooSick();
    const [second] = await listDeviceEntries(PID);
    expect(second!.client_entry_id).not.toBe(first!.client_entry_id);
  });
});
