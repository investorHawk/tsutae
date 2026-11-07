/**
 * P1 今日の記録: 独立レビューの指摘（つらくて書けないの確認・失敗の位置・読み込みの失敗と
 * 読み直し・体温の範囲外・不正な欄への focus・送信中の表示）。
 * 期待する文は patient_strings.json のキーから引く（このファイルに日本語を直書きしない）。
 */
import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearPid, savePid } from "../../patient/pid";
import { jsonResponse } from "../../test/fetchMock";
import { MARK, callsTo, mockPatientApi } from "./testing/api";
import { savedInputs } from "./testing/device";
import { PID, QUESTIONS_RESPONSE, questionText, s } from "./testing/fixtures";
import { renderPatient } from "./testing/render";
import Today from "./Today";

const MARK_URL = `/api/patient/${PID}/record-marks`;
const QUESTIONS_URL = `/api/patient/${PID}/questions`;

function renderToday() {
  return renderPatient([{ path: "/today", element: <Today /> }], "/today");
}

async function choose(key: string, answerKey: string) {
  const group = await screen.findByRole("group", { name: questionText(key) });
  await userEvent.click(
    within(group).getByRole("button", { name: s(answerKey) }),
  );
}

function tooSickButton() {
  return screen.getByRole("button", { name: s("today.too_sick_button") });
}

function yesButton() {
  return screen.getByRole("button", { name: s("today.too_sick_confirm_yes") });
}

function countdownText(seconds: number): string {
  return s("today.too_sick_countdown").replace("{seconds}", String(seconds));
}

/** 秒読み（setInterval）を進めて、その後の送信の Promise も流す。 */
async function advance(ms: number) {
  await act(async () => {
    vi.advanceTimersByTime(ms);
  });
}

function submitButton() {
  return screen.getByRole("button", { name: s("today.submit") });
}

function deferred<T>() {
  let resolve: (value: T) => void = () => {};
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

/** a が b より文書の前にある。 */
function isBefore(a: Element, b: Element): boolean {
  return Boolean(
    a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING,
  );
}

beforeEach(() => {
  clearPid();
  savePid(PID);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("Today: too_sick after something was entered asks first", () => {
  it("with an answer: confirm, and 'no' keeps the input and sends nothing", async () => {
    const fetchMock = mockPatientApi();
    renderToday();
    await choose("diarrhea", "answer.hard");
    await userEvent.click(tooSickButton());
    expect(screen.getByText(s("today.too_sick_confirm"))).toBeInTheDocument();
    expect(callsTo(fetchMock, "POST", MARK_URL)).toEqual([]);
    await userEvent.click(
      screen.getByRole("button", { name: s("today.too_sick_confirm_no") }),
    );
    expect(screen.queryByText(s("today.too_sick_confirm"))).toBeNull();
    const group = screen.getByRole("group", { name: questionText("diarrhea") });
    expect(
      within(group).getByRole("button", { name: s("answer.hard") }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(callsTo(fetchMock, "POST", MARK_URL)).toEqual([]);
  });

  it("with free text: 'yes' sends only too_sick (with by_proxy)", async () => {
    const fetchMock = mockPatientApi();
    renderToday();
    await userEvent.type(
      await screen.findByRole("textbox", { name: s("today.free_text_label") }),
      "sample",
    );
    await userEvent.click(
      screen.getByRole("checkbox", { name: s("today.proxy_toggle") }),
    );
    await userEvent.click(tooSickButton());
    await userEvent.click(
      screen.getByRole("button", { name: s("today.too_sick_confirm_yes") }),
    );
    expect(
      await screen.findByText(s("today.too_sick_done")),
    ).toBeInTheDocument();
    expect(await savedInputs()).toEqual([{ too_sick: true, by_proxy: true }]);
    expect(callsTo(fetchMock, "POST", MARK_URL)).toHaveLength(1);
  });
});

describe("Today: too_sick with nothing entered records after 3 seconds", () => {
  // 偽にするのは秒読みの setInterval だけ（setTimeout は Testing Library が使う）
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  });

  it("short confirm and countdown, then {too_sick, by_proxy} is sent once", async () => {
    const fetchMock = mockPatientApi();
    renderToday();
    await screen.findByRole("group", { name: questionText("fever") });
    await userEvent.click(
      screen.getByRole("checkbox", { name: s("today.proxy_toggle") }),
    );
    await userEvent.click(tooSickButton());
    expect(
      screen.getByText(s("today.too_sick_confirm_empty")),
    ).toBeInTheDocument();
    expect(screen.queryByText(s("today.too_sick_confirm"))).toBeNull();
    expect(screen.getByText(countdownText(3))).toBeInTheDocument();
    await advance(2000);
    expect(screen.getByText(countdownText(1))).toBeInTheDocument();
    expect(callsTo(fetchMock, "POST", MARK_URL)).toEqual([]);
    await advance(1000);
    expect(
      await screen.findByText(s("today.too_sick_done")),
    ).toBeInTheDocument();
    await advance(5000);
    expect(await savedInputs()).toEqual([{ too_sick: true, by_proxy: true }]);
  });

  it("yes before the time: sent once", async () => {
    const fetchMock = mockPatientApi();
    renderToday();
    await userEvent.click(tooSickButton());
    await advance(1000);
    await userEvent.click(yesButton());
    await screen.findByText(s("today.too_sick_done"));
    await advance(5000);
    expect(callsTo(fetchMock, "POST", MARK_URL)).toHaveLength(1);
  });

  it("no: nothing is sent, the button can be pressed again", async () => {
    const fetchMock = mockPatientApi();
    renderToday();
    await userEvent.click(tooSickButton());
    await advance(1000);
    await userEvent.click(
      screen.getByRole("button", { name: s("today.too_sick_confirm_no") }),
    );
    await advance(5000);
    expect(screen.queryByText(s("today.too_sick_confirm_empty"))).toBeNull();
    expect(callsTo(fetchMock, "POST", MARK_URL)).toEqual([]);
    expect(tooSickButton()).toHaveAttribute("aria-expanded", "false");
  });

  it("choosing an answer during the countdown: the input confirm, no auto send", async () => {
    const fetchMock = mockPatientApi();
    renderToday();
    await screen.findByRole("group", { name: questionText("fever") });
    await userEvent.click(tooSickButton());
    await advance(2000);
    await choose("diarrhea", "answer.present");
    expect(screen.getByText(s("today.too_sick_confirm"))).toBeInTheDocument();
    expect(screen.queryByText(countdownText(1))).toBeNull();
    await advance(5000);
    expect(callsTo(fetchMock, "POST", MARK_URL)).toEqual([]);
  });

  it("leaving the page stops the countdown", async () => {
    const fetchMock = mockPatientApi();
    const view = renderToday();
    await userEvent.click(tooSickButton());
    await advance(1000);
    view.unmount();
    await advance(5000);
    expect(callsTo(fetchMock, "POST", MARK_URL)).toEqual([]);
  });
});

describe("Today: where the error of too_sick is shown", () => {
  it("right after the too_sick button, before the questions", async () => {
    mockPatientApi({
      recordMark: () => jsonResponse({ error: "boom" }, 500),
    });
    renderToday();
    const firstGroup = await screen.findByRole("group", {
      name: questionText("numbness"),
    });
    await userEvent.click(tooSickButton());
    await userEvent.click(yesButton());
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(s("error.generic"));
    expect(isBefore(tooSickButton(), alert)).toBe(true);
    expect(isBefore(alert, firstGroup)).toBe(true);
  });

  it("a failed normal submit still shows the error near the submit button", async () => {
    mockPatientApi({
      recordMark: () => jsonResponse({ error: "boom" }, 500),
    });
    renderToday();
    await choose("diarrhea", "answer.present");
    await userEvent.click(submitButton());
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(s("error.generic"));
    expect(
      isBefore(
        screen.getByRole("group", { name: questionText("fever") }),
        alert,
      ),
    ).toBe(true);
    expect(isBefore(alert, submitButton())).toBe(true);
  });
});

describe("Today: loading the questions", () => {
  it("while loading: common.loading", async () => {
    const pending = deferred<Response>();
    mockPatientApi({ questions: () => pending.promise });
    renderToday();
    expect(screen.getByText(s("common.loading"))).toBeInTheDocument();
    pending.resolve(jsonResponse(QUESTIONS_RESPONSE));
    await screen.findByRole("group", { name: questionText("fever") });
    expect(screen.queryByText(s("common.loading"))).toBeNull();
  });

  it("failure: common.load_failed and a reload button that reads again", async () => {
    let fail = true;
    const fetchMock = mockPatientApi({
      questions: () =>
        fail
          ? jsonResponse({ error: "boom" }, 500)
          : jsonResponse(QUESTIONS_RESPONSE),
    });
    renderToday();
    expect(
      await screen.findByText(s("common.load_failed")),
    ).toBeInTheDocument();
    expect(screen.queryByText(s("error.generic"))).toBeNull();
    fail = false;
    await userEvent.click(
      screen.getByRole("button", { name: s("common.reload") }),
    );
    await screen.findByRole("group", { name: questionText("fever") });
    expect(screen.queryByText(s("common.load_failed"))).toBeNull();
    expect(callsTo(fetchMock, "GET", QUESTIONS_URL)).toHaveLength(2);
    expect(callsTo(fetchMock, "POST", MARK_URL)).toEqual([]);
  });
});

describe("Today: temperature messages and focus", () => {
  it("368 (no decimal point): temperature.out_of_range, focus on the field", async () => {
    const fetchMock = mockPatientApi();
    renderToday();
    await choose("fever", "answer.measured");
    const input = screen.getByRole("textbox", { name: s("temperature.label") });
    await userEvent.type(input, "368");
    await userEvent.click(submitButton());
    expect(screen.getByText(s("temperature.out_of_range"))).toBeInTheDocument();
    expect(screen.queryByText(s("temperature.invalid"))).toBeNull();
    expect(input).toHaveFocus();
    expect(callsTo(fetchMock, "POST", MARK_URL)).toEqual([]);
  });

  it("not a number: temperature.invalid", async () => {
    mockPatientApi();
    renderToday();
    await choose("fever", "answer.measured");
    const input = screen.getByRole("textbox", { name: s("temperature.label") });
    await userEvent.type(input, "abc");
    await userEvent.click(submitButton());
    expect(screen.getByText(s("temperature.invalid"))).toBeInTheDocument();
    expect(input).toHaveFocus();
  });
});

describe("Today: while sending", () => {
  it("shows today.sending until the answer comes back", async () => {
    const pending = deferred<Response>();
    mockPatientApi({ recordMark: () => pending.promise });
    renderToday();
    await choose("diarrhea", "answer.present");
    await userEvent.click(submitButton());
    expect(await screen.findByText(s("today.sending"))).toBeInTheDocument();
    pending.resolve(jsonResponse(MARK));
    await screen.findByText(s("today.saved"));
    expect(screen.queryByText(s("today.sending"))).toBeNull();
  });
});

describe("Today: a network failure while sending", () => {
  it("keeps the input, shows error.generic, and the same entry can be sent again", async () => {
    let fail = true;
    const fetchMock = mockPatientApi({
      recordMark: () =>
        fail
          ? Promise.reject(new TypeError("Failed to fetch"))
          : jsonResponse(MARK),
    });
    renderToday();
    await choose("diarrhea", "answer.present");
    await userEvent.click(submitButton());
    expect(await screen.findByRole("alert")).toHaveTextContent(
      s("error.generic"),
    );
    const group = screen.getByRole("group", { name: questionText("diarrhea") });
    expect(
      within(group).getByRole("button", { name: s("answer.present") }),
    ).toHaveAttribute("aria-pressed", "true");
    fail = false;
    await userEvent.click(submitButton());
    await screen.findByText(s("today.saved"));
    // 押し直しても端末の記録は1件（同じ client_entry_id）
    expect(callsTo(fetchMock, "POST", MARK_URL)).toHaveLength(2);
    expect(await savedInputs()).toEqual([
      {
        by_proxy: false,
        answers: [{ question_key: "diarrhea", value: "present" }],
        free_text: null,
      },
    ]);
  });
});
