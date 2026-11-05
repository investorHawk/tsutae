/**
 * P1 今日の記録: 開いたまま日付が変わった画面を読み直す。戻ったとき・通知を押したときに、
 * 画面が持つ今日とサーバーの今日を比べ、違うときだけ読み直す（同じ日の書きかけは消さない）。
 */
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearPid, savePid } from "../../patient/pid";
import { OPEN_TODAY_MESSAGE } from "../../patient/pushDevice";
import { jsonResponse } from "../../test/fetchMock";
import { callsTo, mockPatientApi } from "./testing/api";
import { PID, QUESTIONS_RESPONSE, s } from "./testing/fixtures";
import { installFakePush, type FakePush } from "./testing/pushBrowser";
import { renderPatient } from "./testing/render";
import Today from "./Today";

const ROUTES = [{ path: "/today", element: <Today /> }];
const QUESTIONS_URL = `/api/patient/${PID}/questions`;
const DAY1 = "2026-11-09";
const DAY2 = "2026-11-10";
// 2026-11-09 は月曜、11-10 は火曜
const DAY1_TITLE = () => dateTitle(11, 9, 1);
const DAY2_TITLE = () => dateTitle(11, 10, 2);

function dateTitle(month: number, day: number, weekday: number): string {
  const date = s("history.date")
    .replace("{month}", String(month))
    .replace("{day}", String(day))
    .replace("{weekday}", s(`weekday.${weekday}`));
  return `${s("today.title")} ${date}`;
}

function setVisibility(state: DocumentVisibilityState) {
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => state,
  });
  fireEvent(document, new Event("visibilitychange"));
}

async function findTitle(name: string) {
  return screen.findByRole("heading", { level: 1, name });
}

function freeText() {
  return screen.findByRole("textbox", { name: s("today.free_text_label") });
}

/** 今日の分を「つらくて書けない」で記録して、完了の画面にする。 */
async function recordTooSick() {
  await userEvent.click(
    await screen.findByRole("button", { name: s("today.too_sick_button") }),
  );
  await userEvent.click(
    screen.getByRole("button", { name: s("today.too_sick_confirm_yes") }),
  );
  await screen.findByText(s("today.too_sick_done"));
}

/** サーバーの今日を途中で変えられる偽の API。 */
function givenServer() {
  const server = { today: DAY1 };
  const fetchMock = mockPatientApi({
    questions: () =>
      jsonResponse({ ...QUESTIONS_RESPONSE, today: server.today }),
  });
  return {
    server,
    fetchMock,
    questionCalls: () => callsTo(fetchMock, "GET", QUESTIONS_URL).length,
  };
}

/** 非同期の処理を一通り進める。 */
async function settle() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

let push: FakePush | null = null;

beforeEach(() => {
  clearPid();
  savePid(PID);
});

afterEach(() => {
  push?.uninstall();
  push = null;
  delete (document as unknown as Record<string, unknown>).visibilityState;
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("Today (P1): the day changed while the screen stayed open", () => {
  it("done yesterday: back to an empty form with the new date", async () => {
    const { server } = givenServer();
    renderPatient(ROUTES, "/today");
    await findTitle(DAY1_TITLE());
    await recordTooSick();
    server.today = DAY2;
    setVisibility("visible");
    await findTitle(DAY2_TITLE());
    expect(screen.queryByText(s("today.too_sick_done"))).toBeNull();
    expect(
      await screen.findByRole("button", { name: s("today.too_sick_button") }),
    ).toBeInTheDocument();
  });

  it("a draft from yesterday is not carried over as today's record", async () => {
    const { server } = givenServer();
    renderPatient(ROUTES, "/today");
    await findTitle(DAY1_TITLE());
    await userEvent.type(await freeText(), "yesterday");
    server.today = DAY2;
    setVisibility("visible");
    await findTitle(DAY2_TITLE());
    expect(await freeText()).toHaveValue("");
  });

  it("the just-registered message goes away with the old day", async () => {
    const { server } = givenServer();
    renderPatient(ROUTES, {
      pathname: "/today",
      state: { registered: true },
    });
    await findTitle(DAY1_TITLE());
    expect(screen.getByText(s("register.done"))).toBeInTheDocument();
    server.today = DAY2;
    setVisibility("visible");
    await findTitle(DAY2_TITLE());
    expect(screen.queryByText(s("register.done"))).toBeNull();
  });
});

describe("Today (P1): the same day", () => {
  it("keeps the draft when coming back", async () => {
    const { questionCalls } = givenServer();
    renderPatient(ROUTES, "/today");
    await findTitle(DAY1_TITLE());
    await userEvent.type(await freeText(), "draft");
    setVisibility("visible");
    await waitFor(() => expect(questionCalls()).toBe(2));
    await settle();
    expect(await freeText()).toHaveValue("draft");
    expect(questionCalls()).toBe(2);
  });

  it("keeps the done screen when coming back", async () => {
    const { questionCalls } = givenServer();
    renderPatient(ROUTES, "/today");
    await findTitle(DAY1_TITLE());
    await recordTooSick();
    setVisibility("visible");
    await waitFor(() => expect(questionCalls()).toBe(2));
    await settle();
    expect(screen.getByText(s("today.too_sick_done"))).toBeInTheDocument();
  });

  it("does not ask the server when leaving", async () => {
    const { questionCalls } = givenServer();
    renderPatient(ROUTES, "/today");
    await findTitle(DAY1_TITLE());
    setVisibility("hidden");
    await settle();
    expect(questionCalls()).toBe(1);
  });
});

describe("Today (P1): tapping the notification on a visible screen", () => {
  it("the service worker's message starts the same check", async () => {
    push = installFakePush();
    const { server } = givenServer();
    renderPatient(ROUTES, "/today");
    await findTitle(DAY1_TITLE());
    await recordTooSick();
    server.today = DAY2;
    act(() => push?.postFromWorker({ type: OPEN_TODAY_MESSAGE }));
    await findTitle(DAY2_TITLE());
    expect(screen.queryByText(s("today.too_sick_done"))).toBeNull();
  });

  it("other messages are ignored", async () => {
    push = installFakePush();
    const { questionCalls } = givenServer();
    renderPatient(ROUTES, "/today");
    await findTitle(DAY1_TITLE());
    act(() => push?.postFromWorker({ type: "other" }));
    act(() => push?.postFromWorker(null));
    await settle();
    expect(questionCalls()).toBe(1);
  });

  it("both signals at once read the questions once more only", async () => {
    push = installFakePush();
    const { server, questionCalls } = givenServer();
    renderPatient(ROUTES, "/today");
    await findTitle(DAY1_TITLE());
    server.today = DAY2;
    act(() => {
      push?.postFromWorker({ type: OPEN_TODAY_MESSAGE });
      setVisibility("visible");
    });
    await findTitle(DAY2_TITLE());
    await settle();
    // 最初の読み込み・確かめる1回・読み直しの1回
    expect(questionCalls()).toBe(3);
  });
});

describe("Today (P1): when the check cannot be made", () => {
  it("the server fails: the screen stays as it is", async () => {
    const replies = { fail: false };
    mockPatientApi({
      questions: () =>
        replies.fail
          ? jsonResponse({ error: "boom" }, 500)
          : jsonResponse({ ...QUESTIONS_RESPONSE, today: DAY1 }),
    });
    renderPatient(ROUTES, "/today");
    await findTitle(DAY1_TITLE());
    await userEvent.type(await freeText(), "draft");
    replies.fail = true;
    setVisibility("visible");
    await settle();
    expect(await freeText()).toHaveValue("draft");
    expect(screen.queryByRole("alert")).toBeNull();
    await findTitle(DAY1_TITLE());
  });

  it("the first load failed: no date to compare, nothing to ask", async () => {
    const fetchMock = mockPatientApi({
      questions: () => jsonResponse({ error: "boom" }, 500),
    });
    renderPatient(ROUTES, "/today");
    await screen.findByText(s("common.load_failed"));
    setVisibility("visible");
    await settle();
    expect(callsTo(fetchMock, "GET", QUESTIONS_URL)).toHaveLength(1);
  });

  it("no saved pid: no request", async () => {
    clearPid();
    const fetchMock = mockPatientApi();
    renderPatient(ROUTES, "/today");
    setVisibility("visible");
    await settle();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("stops listening after unmount", async () => {
    push = installFakePush();
    const { questionCalls } = givenServer();
    const view = renderPatient(ROUTES, "/today");
    await findTitle(DAY1_TITLE());
    view.unmount();
    setVisibility("visible");
    push.postFromWorker({ type: OPEN_TODAY_MESSAGE });
    await settle();
    expect(questionCalls()).toBe(1);
  });
});
