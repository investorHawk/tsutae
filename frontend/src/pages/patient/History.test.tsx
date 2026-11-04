/** P2 これまでの記録。期待する文は patient_strings.json のキーと API の質問文から引く。 */
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearPid, savePid } from "../../patient/pid";
import { jsonResponse } from "../../test/fetchMock";
import History from "./History";
import { callsTo, mockPatientApi } from "./testing/api";
import { ENTRIES, PID, questionText, s } from "./testing/fixtures";
import { renderPatient } from "./testing/render";

const ROUTES = [{ path: "/history", element: <History /> }];

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function renderHistory() {
  return renderPatient(ROUTES, "/history");
}

async function items(): Promise<HTMLElement[]> {
  const list = await screen.findByRole("list", { name: s("history.title") });
  return within(list).getAllByRole("listitem");
}

beforeEach(() => {
  clearPid();
  savePid(PID);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("History (P2)", () => {
  it("without a saved pid: error.not_registered and no request", () => {
    clearPid();
    const fetchMock = mockPatientApi();
    renderHistory();
    expect(
      screen.getByRole("heading", { level: 1, name: s("history.title") }),
    ).toBeInTheDocument();
    expect(screen.getByText(s("error.not_registered"))).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("reads GET entries and lists them newest first", async () => {
    const fetchMock = mockPatientApi();
    renderHistory();
    const rows = await items();
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent("2026-11-02 08:10");
    expect(rows[1]).toHaveTextContent("2026-10-31 19:30");
    expect(rows[2]).toHaveTextContent("2026-10-29 21:05");
    expect(
      callsTo(fetchMock, "GET", `/api/patient/${PID}/entries`),
    ).toHaveLength(1);
  });

  it("shows too_sick, proxy, answers with question text, and free text", async () => {
    mockPatientApi();
    renderHistory();
    const [newest, middle, oldest] = await items();

    expect(oldest).toHaveTextContent(s("history.too_sick"));
    expect(oldest).not.toHaveTextContent(s("history.proxy"));

    expect(middle).toHaveTextContent(s("history.proxy"));
    expect(middle).toHaveTextContent(questionText("diarrhea"));
    expect(middle).toHaveTextContent(s("answer.present"));
    expect(middle).toHaveTextContent(questionText("fever"));
    expect(middle).toHaveTextContent(s("answer.measured"));
    expect(middle).toHaveTextContent(s("temperature.label"));
    expect(middle).toHaveTextContent("37.9");
    expect(middle).toHaveTextContent(s("history.free_text"));
    expect(middle).toHaveTextContent(ENTRIES[1]!.free_text!);
    expect(middle).not.toHaveTextContent(s("history.too_sick"));

    expect(newest).toHaveTextContent(ENTRIES[2]!.free_text!);
    expect(newest).not.toHaveTextContent(s("history.proxy"));
  });

  it("the free text has the wrapping class (long letters and digits wrap)", async () => {
    mockPatientApi();
    renderHistory();
    const [newest] = await items();
    const text = within(newest!).getByText(ENTRIES[2]!.free_text!);
    expect(text).toHaveClass("p-entry-free-text");
  });

  it("is read only (no buttons or fields)", async () => {
    mockPatientApi();
    renderHistory();
    await items();
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByRole("checkbox")).toBeNull();
  });

  it("shows the question text recorded with the entry, not the current question set", async () => {
    const recordedText = `${questionText("diarrhea")} (v0)`;
    const fetchMock = mockPatientApi({
      entries: () =>
        jsonResponse({
          entries: [
            {
              ...ENTRIES[1]!,
              answers: [
                {
                  question_key: "diarrhea",
                  value: "hard",
                  temperature: null,
                  question_text: recordedText,
                },
              ],
              free_text: null,
            },
          ],
        }),
    });
    renderHistory();
    const [only] = await items();
    expect(within(only!).getByRole("term")).toHaveTextContent(
      new RegExp(`^${escapeRegExp(recordedText)}$`),
    );
    expect(only).toHaveTextContent(s("answer.hard"));
    expect(
      callsTo(fetchMock, "GET", `/api/patient/${PID}/questions`),
    ).toHaveLength(0);
  });

  it("question_text null (question no longer known): history.previous_question and the value are still shown", async () => {
    mockPatientApi({
      entries: () =>
        jsonResponse({
          entries: [
            {
              ...ENTRIES[1]!,
              kind: "answers",
              answers: [
                {
                  question_key: "old_question",
                  value: "hard",
                  temperature: null,
                  question_text: null,
                },
              ],
              free_text: null,
            },
          ],
        }),
    });
    renderHistory();
    const [only] = await items();
    expect(within(only!).getByRole("term")).toHaveTextContent(
      s("history.previous_question"),
    );
    expect(within(only!).getByRole("definition")).toHaveTextContent(
      s("answer.hard"),
    );
    expect(only).not.toHaveTextContent("old_question");
  });

  it("questions failing does not matter (P2 does not read GET questions)", async () => {
    const fetchMock = mockPatientApi({
      questions: () => jsonResponse({ error: "boom" }, 500),
    });
    renderHistory();
    const rows = await items();
    expect(rows).toHaveLength(3);
    expect(rows[1]).toHaveTextContent(questionText("diarrhea"));
    expect(rows[1]).toHaveTextContent(s("answer.present"));
    expect(
      callsTo(fetchMock, "GET", `/api/patient/${PID}/questions`),
    ).toHaveLength(0);
  });

  it.each([
    ["entries missing", {}],
    ["answers missing", { entries: [{ ...ENTRIES[1]!, answers: undefined }] }],
    ["answers null", { entries: [{ ...ENTRIES[1]!, answers: null }] }],
    ["entry is a string", { entries: ["x"] }],
  ])(
    "malformed 200 body (%s): common.load_failed instead of a blank page",
    async (_label, body) => {
      mockPatientApi({ entries: () => jsonResponse(body) });
      renderHistory();
      expect(
        await screen.findByText(s("common.load_failed")),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("heading", { level: 1, name: s("history.title") }),
      ).toBeInTheDocument();
    },
  );

  it("no entries: history.empty", async () => {
    mockPatientApi({ entries: () => jsonResponse({ entries: [] }) });
    renderHistory();
    expect(await screen.findByText(s("history.empty"))).toBeInTheDocument();
  });

  it("401: error.not_registered", async () => {
    mockPatientApi({
      entries: () => jsonResponse({ error: "not_registered" }, 401),
    });
    renderHistory();
    expect(
      await screen.findByText(s("error.not_registered")),
    ).toBeInTheDocument();
  });

  it("500: common.load_failed and a reload button that reads again", async () => {
    let fail = true;
    const fetchMock = mockPatientApi({
      entries: () =>
        fail
          ? jsonResponse({ error: "boom" }, 500)
          : jsonResponse({ entries: [] }),
    });
    renderHistory();
    expect(
      await screen.findByText(s("common.load_failed")),
    ).toBeInTheDocument();
    expect(screen.queryByText(s("error.generic"))).toBeNull();
    fail = false;
    await userEvent.click(
      screen.getByRole("button", { name: s("common.reload") }),
    );
    expect(await screen.findByText(s("history.empty"))).toBeInTheDocument();
    expect(screen.queryByText(s("common.load_failed"))).toBeNull();
    expect(
      callsTo(fetchMock, "GET", `/api/patient/${PID}/entries`),
    ).toHaveLength(2);
  });

  it("while loading: common.loading", async () => {
    mockPatientApi({ entries: () => new Promise<Response>(() => {}) });
    renderHistory();
    expect(screen.getByText(s("common.loading"))).toBeInTheDocument();
  });

  it("has the bottom navigation with history as the current page", async () => {
    mockPatientApi();
    renderHistory();
    const nav = screen.getByRole("navigation");
    expect(
      within(nav).getByRole("link", { name: s("nav.history") }),
    ).toHaveAttribute("aria-current", "page");
    expect(
      within(nav).getByRole("link", { name: s("nav.today") }),
    ).toHaveAttribute("href", "/today");
  });
});
