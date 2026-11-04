/**
 * P1 今日の記録: 見出しの右の日付。日付は端末の時計ではなく、GET questions の today
 * （サーバーの今日）から作る。取れない間・取れなかった時は出さない（見出しはそのまま）。
 */
import { screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearPid, savePid } from "../../patient/pid";
import { jsonResponse } from "../../test/fetchMock";
import { mockPatientApi } from "./testing/api";
import { PID, QUESTIONS_RESPONSE, questionText, s } from "./testing/fixtures";
import { renderPatient } from "./testing/render";
import Today from "./Today";

const ROUTES = [{ path: "/today", element: <Today /> }];

/** 「11月9日（月）」の形（定型文 history.date・weekday.* から作る）。 */
function dateText(month: number, day: number, weekday: number): string {
  return s("history.date")
    .replace("{month}", String(month))
    .replace("{day}", String(day))
    .replace("{weekday}", s(`weekday.${weekday}`));
}

function title(): HTMLElement {
  return screen.getByRole("heading", { level: 1 });
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

describe("Today (P1): the date next to the title", () => {
  it("shows the server's today in the h1 (read as the title, a space, the date)", async () => {
    mockPatientApi();
    renderPatient(ROUTES, "/today");
    await screen.findByRole("group", { name: questionText("fever") });
    // 2026-11-09 は月曜
    expect(
      screen.getByRole("heading", {
        level: 1,
        name: `${s("today.title")} ${dateText(11, 9, 1)}`,
      }),
    ).toBeInTheDocument();
    const date = title().querySelector(".p-title-date");
    expect(date).toHaveTextContent(new RegExp(`^${dateText(11, 9, 1)}$`));
  });

  it("uses the server's today, not the device clock", async () => {
    // 端末の時計は 11/4。サーバーの今日は 12/1（火）
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-11-04T17:00:00+09:00"));
    mockPatientApi({
      questions: () =>
        jsonResponse({ ...QUESTIONS_RESPONSE, today: "2026-12-01" }),
    });
    renderPatient(ROUTES, "/today");
    await screen.findByRole("group", { name: questionText("fever") });
    expect(title()).toHaveTextContent(dateText(12, 1, 2));
    expect(title()).not.toHaveTextContent(dateText(11, 4, 3));
  });

  it("while loading: the title only (no date)", () => {
    mockPatientApi({ questions: () => new Promise<Response>(() => {}) });
    renderPatient(ROUTES, "/today");
    expect(
      screen.getByRole("heading", { level: 1, name: s("today.title") }),
    ).toBeInTheDocument();
    expect(title().querySelector(".p-title-date")).toBeNull();
  });

  it("questions failed: the title only (no date)", async () => {
    mockPatientApi({ questions: () => jsonResponse({ error: "boom" }, 500) });
    renderPatient(ROUTES, "/today");
    expect(
      await screen.findByText(s("common.load_failed")),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 1, name: s("today.title") }),
    ).toBeInTheDocument();
    expect(title().querySelector(".p-title-date")).toBeNull();
  });

  it("without a saved pid: the title only (no request, no date)", () => {
    clearPid();
    const fetchMock = mockPatientApi();
    renderPatient(ROUTES, "/today");
    expect(
      screen.getByRole("heading", { level: 1, name: s("today.title") }),
    ).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
