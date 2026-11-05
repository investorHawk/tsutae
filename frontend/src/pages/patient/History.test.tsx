/** P2 これまでの記録。期待する文は patient_strings.json のキーと API の質問文から引く。 */
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearPid, savePid } from "../../patient/pid";
import { jsonResponse } from "../../test/fetchMock";
import History from "./History";
import { callsTo, mockPatientApi } from "./testing/api";
import { seedDevice, seedDeviceOnly } from "./testing/device";
import { ENTRIES, PID, VISITS, questionText, s } from "./testing/fixtures";
import { renderPatient } from "./testing/render";
import { spokenText, visibleText } from "./testing/text";

const ROUTES = [{ path: "/history", element: <History /> }];

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** 「11月2日（月）8:10」の形（定型文 history.date・weekday.* から作る）。 */
function dateText(month: number, day: number, weekday: number, time: string) {
  const date = s("history.date")
    .replace("{month}", String(month))
    .replace("{day}", String(day))
    .replace("{weekday}", s(`weekday.${weekday}`));
  return `${date}${time}`;
}

/** 記録1件の開いた時の中身（表と書いたこと）。 */
function detailOf(item: HTMLElement): HTMLElement {
  const detail = item.querySelector<HTMLElement>(".p-entry-detail");
  if (!detail) {
    throw new Error("p-entry-detail is missing");
  }
  return detail;
}

function summaryOf(item: HTMLElement): HTMLElement {
  const summary = item.querySelector("summary");
  if (!summary) {
    throw new Error("summary is missing");
  }
  return summary;
}

/** 記録1件の詳しい表示の、行見出しが label の行。 */
function rowOf(item: HTMLElement, label: string): HTMLElement {
  const header = within(item).getByRole("rowheader", { name: label });
  const row = header.closest("tr");
  if (!row) {
    throw new Error("row is missing");
  }
  return row;
}

function temperatureText(value: string): string {
  return `${s("answer.measured")} ${s("history.temperature_value").replace("{value}", value)}`;
}

function renderHistory() {
  return renderPatient(ROUTES, "/history");
}

async function list(): Promise<HTMLElement> {
  return screen.findByRole("list", { name: s("history.title") });
}

/** 記録の行（受診日の区切りの行は除く）。 */
async function items(): Promise<HTMLElement[]> {
  return within(await list())
    .getAllByRole("listitem")
    .filter((li) => li.classList.contains("p-entry"));
}

/** 「受診日 10月30日（金）」の形（定型文 history.visit_day・history.date から作る）。 */
function visitDayText(month: number, day: number, weekday: number): string {
  return s("history.visit_day").replace(
    "{date}",
    dateText(month, day, weekday, ""),
  );
}

beforeEach(async () => {
  clearPid();
  savePid(PID);
  await seedDevice(ENTRIES);
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

  it("reads the records on the device and lists them newest first", async () => {
    const fetchMock = mockPatientApi();
    renderHistory();
    const rows = await items();
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent(dateText(11, 2, 1, "8:10"));
    expect(rows[1]).toHaveTextContent(dateText(10, 31, 6, "19:30"));
    expect(rows[2]).toHaveTextContent(dateText(10, 29, 4, "21:05"));
    expect(
      callsTo(fetchMock, "GET", `/api/patient/${PID}/visit-days`),
    ).toHaveLength(1);
    // The records do not come from the server
    expect(callsTo(fetchMock, "GET", `/api/patient/${PID}/entries`)).toEqual(
      [],
    );
  });

  it("shows too_sick, proxy, a table of answers, and free text", async () => {
    mockPatientApi();
    renderHistory();
    const [newest, middle, oldest] = await items();

    expect(oldest).toHaveTextContent(s("history.too_sick"));
    expect(oldest).not.toHaveTextContent(s("history.proxy"));
    expect(within(oldest!).queryByRole("table")).toBeNull();

    expect(within(detailOf(middle!)).getByText(s("history.proxy"))).toHaveClass(
      "p-entry-flag",
    );
    // 行は短い症状名、列は なし／ある／つらい。読み上げは「下痢 ある」
    expect(
      within(middle!)
        .getAllByRole("columnheader")
        .map((th) => th.textContent),
    ).toEqual([s("answer.none"), s("answer.present"), s("answer.hard")]);
    expect(
      within(middle!).getByRole("row", {
        name: `${s("symptom.diarrhea")} ${s("answer.present")}`,
      }),
    ).toBeInTheDocument();
    // 体温は3列をまたいで「測った 37.9℃」
    expect(
      within(middle!).getByRole("row", {
        name: `${s("symptom.fever")} ${temperatureText("37.9")}`,
      }),
    ).toBeInTheDocument();
    expect(within(middle!).getByText(ENTRIES[1]!.free_text!)).toHaveClass(
      "p-entry-free-text",
    );
    expect(middle).not.toHaveTextContent(s("history.too_sick"));

    expect(newest).toHaveTextContent(ENTRIES[2]!.free_text!);
    expect(newest).not.toHaveTextContent(s("history.proxy"));
  });

  it("the free text has a small heading and a box, apart from the table", async () => {
    mockPatientApi();
    renderHistory();
    const [, middle] = await items();
    const body = within(middle!).getByText(ENTRIES[1]!.free_text!);
    const box = body.closest(".p-entry-free");
    expect(box).not.toBeNull();
    expect(
      within(box as HTMLElement).getByText(s("history.free_text")),
    ).toHaveClass("p-entry-label");
    expect(box!.closest("table")).toBeNull();
  });

  it("each record is one line: the date and a short summary, closed until opened", async () => {
    mockPatientApi();
    renderHistory();
    const [newest, middle, oldest] = await items();
    for (const item of [newest!, middle!, oldest!]) {
      expect(item.querySelector("details")).not.toHaveAttribute("open");
    }
    const line = summaryOf(middle!);
    expect(line).toHaveTextContent(dateText(10, 31, 6, "19:30"));
    expect(line).toHaveTextContent(
      `${s("symptom.diarrhea")} ${s("answer.present")}`,
    );
    expect(line).toHaveTextContent(
      `${s("symptom.fever")} ${s("history.temperature_value").replace("{value}", "37.9")}`,
    );
    expect(line).toHaveTextContent(
      `${s("history.free_text")} ${s("history.free_text_present")}`,
    );
    // 日時の下にタグが並ぶ。代理の記録には代理のタグ
    const tags = line.querySelector(".p-tags");
    expect(line.querySelector(".p-entry-time")?.nextElementSibling).toBe(tags);
    expect(
      Array.from(line.querySelectorAll(".p-tag")).map(visibleText),
    ).toEqual([
      s("symptom.diarrhea"),
      s("history.temperature_value").replace("{value}", "37.9"),
      s("history.free_text"),
      s("history.proxy_short"),
    ]);
    expect(summaryOf(newest!).querySelector(".p-tag")).toHaveTextContent(
      s("history.free_text"),
    );
    expect(summaryOf(newest!)).not.toHaveTextContent(s("history.proxy"));
    // 一行には質問文と自由記載の中身を出さない（開くと出る）
    expect(line).not.toHaveTextContent(questionText("diarrhea"));
    expect(line).not.toHaveTextContent(ENTRIES[1]!.free_text!);
    expect(summaryOf(oldest!)).toHaveTextContent(s("history.too_sick"));
    expect(summaryOf(newest!)).toHaveTextContent(
      `${s("history.free_text")} ${s("history.free_text_present")}`,
    );
  });

  it("the line shows a tag read with the answer; the details mark the chosen answer", async () => {
    mockPatientApi();
    renderHistory();
    const [, middle] = await items();
    const tag = summaryOf(middle!).querySelector(".p-tag--present");
    expect(tag).not.toBeNull();
    expect(spokenText(tag!)).toBe(
      `${s("symptom.diarrhea")} ${s("answer.present")}`,
    );
    const chosen = rowOf(middle!, s("symptom.diarrhea")).querySelector(
      ".p-answer-cell--chosen strong",
    );
    expect(chosen).toHaveTextContent(s("answer.present"));
  });

  it("the line is a native summary (focusable) and opens the details", async () => {
    // Tab で届く・Enter や Space で開くのはブラウザの summary の働き（jsdom は Tab の順に
    // summary を入れず、押下を click にしない）。ここでは focus できることと、押すと開くことを見る
    mockPatientApi();
    renderHistory();
    const [newest] = await items();
    const details = newest!.querySelector("details")!;
    summaryOf(newest!).focus();
    expect(summaryOf(newest!)).toHaveFocus();
    await userEvent.click(summaryOf(newest!));
    expect(details).toHaveAttribute("open");
  });

  it("an unknown question key: the recorded question text is used in the line", async () => {
    await seedDeviceOnly([
      {
        ...ENTRIES[1]!,
        kind: "answers",
        answers: [
          {
            question_key: "new_question",
            value: "hard",
            temperature: null,
            question_text: "new question text",
          },
        ],
        free_text: null,
      },
    ]);
    mockPatientApi();
    renderHistory();
    const [only] = await items();
    expect(spokenText(summaryOf(only!))).toContain(
      `new question text ${s("answer.hard")}`,
    );
    expect(summaryOf(only!).querySelector(".p-tag--hard")).toHaveTextContent(
      "new question text",
    );
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

  it("an unknown key in the details: the question text recorded with the entry", async () => {
    const recordedText = `${questionText("diarrhea")} (v0)`;
    await seedDeviceOnly([
      {
        ...ENTRIES[1]!,
        answers: [
          {
            question_key: "diarrhea_v0",
            value: "hard",
            temperature: null,
            question_text: recordedText,
          },
        ],
        free_text: null,
      },
    ]);
    const fetchMock = mockPatientApi();
    renderHistory();
    const [only] = await items();
    expect(within(only!).getByRole("rowheader")).toHaveTextContent(
      new RegExp(`^${escapeRegExp(recordedText)}$`),
    );
    expect(
      within(only!).getByRole("row", {
        name: `${recordedText} ${s("answer.hard")}`,
      }),
    ).toBeInTheDocument();
    expect(
      callsTo(fetchMock, "GET", `/api/patient/${PID}/questions`),
    ).toHaveLength(0);
  });

  it("question_text null (question no longer known): history.previous_question and the value are still shown", async () => {
    await seedDeviceOnly([
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
    ]);
    mockPatientApi();
    renderHistory();
    const [only] = await items();
    expect(
      within(only!).getByRole("row", {
        name: `${s("history.previous_question")} ${s("answer.hard")}`,
      }),
    ).toBeInTheDocument();
    expect(only).not.toHaveTextContent("old_question");
  });

  it("questions failing does not matter (P2 does not read GET questions)", async () => {
    const fetchMock = mockPatientApi({
      questions: () => jsonResponse({ error: "boom" }, 500),
    });
    renderHistory();
    const rows = await items();
    expect(rows).toHaveLength(3);
    expect(
      within(rows[1]!).getByRole("row", {
        name: `${s("symptom.diarrhea")} ${s("answer.present")}`,
      }),
    ).toBeInTheDocument();
    expect(
      callsTo(fetchMock, "GET", `/api/patient/${PID}/questions`),
    ).toHaveLength(0);
  });

  it.each([
    ["visits missing", {}],
    ["a visit is a string", { visits: ["x"] }],
    ["a visit without received_at", { visits: [{ visit_date: "2026-10-30" }] }],
  ])(
    "malformed visit-days body (%s): common.load_failed instead of a blank page",
    async (_label, body) => {
      mockPatientApi({ visitDays: () => jsonResponse(body) });
      renderHistory();
      expect(
        await screen.findByText(s("common.load_failed")),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("heading", { level: 1, name: s("history.title") }),
      ).toBeInTheDocument();
    },
  );

  it("the device cannot be read: common.load_failed", async () => {
    mockPatientApi();
    vi.stubGlobal("indexedDB", {
      open: () => {
        throw new DOMException("denied", "SecurityError");
      },
    });
    renderHistory();
    expect(
      await screen.findByText(s("common.load_failed")),
    ).toBeInTheDocument();
  });

  it("records of another number on the same device are not shown", async () => {
    await seedDeviceOnly([]);
    await seedDevice([{ ...ENTRIES[2]!, pid: "P-EVAL0001" }]);
    mockPatientApi();
    renderHistory();
    expect(await screen.findByText(s("history.empty"))).toBeInTheDocument();
    expect(screen.queryByText(ENTRIES[2]!.free_text!)).toBeNull();
  });

  describe("visit-day dividers (the days of a reception at the hospital)", () => {
    function withVisits() {
      return mockPatientApi({
        visitDays: () => jsonResponse({ visits: [...VISITS] }),
      });
    }

    function dividersOf(ul: HTMLElement): HTMLElement[] {
      return within(ul)
        .getAllByRole("listitem")
        .filter((li) => li.classList.contains("p-visit-day"));
    }

    it("no visits: no divider", async () => {
      mockPatientApi();
      renderHistory();
      expect(dividersOf(await list())).toHaveLength(0);
    });

    it("a divider sits at the reception time: later records above, earlier below", async () => {
      withVisits();
      renderHistory();
      const ul = await list();
      const rows = within(ul).getAllByRole("listitem");
      expect(rows.map((li) => li.className)).toEqual([
        "p-entry",
        "p-entry",
        "p-visit-day",
        "p-entry",
      ]);
      expect(rows[1]).toHaveTextContent(dateText(10, 31, 6, "19:30"));
      expect(rows[3]).toHaveTextContent(dateText(10, 29, 4, "21:05"));
    });

    it("the divider reads history.visit_day with the date (10-30, Fri) and carries it", async () => {
      withVisits();
      renderHistory();
      const [divider] = dividersOf(await list());
      expect(spokenText(divider!)).toBe(visitDayText(10, 30, 5));
      expect(visibleText(divider!)).toBe(visitDayText(10, 30, 5));
      expect(divider!.querySelector("time")).toHaveAttribute(
        "datetime",
        "2026-10-30",
      );
      // 押せるものではない（開く・閉じるは無い）
      expect(divider!.querySelector("details, summary, button, a")).toBeNull();
    });

    it("shows only the date of the visit (no reception number or state)", async () => {
      withVisits();
      renderHistory();
      const [divider] = dividersOf(await list());
      expect(divider!.textContent).not.toMatch(/[A-Za-z]/);
    });

    it("no records but a visit: history.empty and the divider", async () => {
      await seedDeviceOnly([]);
      mockPatientApi({
        visitDays: () => jsonResponse({ visits: [...VISITS] }),
      });
      renderHistory();
      expect(await screen.findByText(s("history.empty"))).toBeInTheDocument();
      const ul = await list();
      expect(within(ul).getAllByRole("listitem")).toHaveLength(1);
      expect(spokenText(dividersOf(ul)[0]!)).toBe(visitDayText(10, 30, 5));
    });

    it("still read only with dividers (no buttons or fields)", async () => {
      withVisits();
      renderHistory();
      await list();
      expect(screen.queryByRole("button")).toBeNull();
      expect(screen.queryByRole("textbox")).toBeNull();
    });
  });

  it("no entries: history.empty", async () => {
    await seedDeviceOnly([]);
    mockPatientApi();
    renderHistory();
    expect(await screen.findByText(s("history.empty"))).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: s("history.title") })).toBeNull();
  });

  it("401: error.not_registered", async () => {
    mockPatientApi({
      visitDays: () => jsonResponse({ error: "not_registered" }, 401),
    });
    renderHistory();
    expect(
      await screen.findByText(s("error.not_registered")),
    ).toBeInTheDocument();
  });

  it("500: common.load_failed and a reload button that reads again", async () => {
    await seedDeviceOnly([]);
    let fail = true;
    const fetchMock = mockPatientApi({
      visitDays: () =>
        fail
          ? jsonResponse({ error: "boom" }, 500)
          : jsonResponse({ visits: [] }),
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
      callsTo(fetchMock, "GET", `/api/patient/${PID}/visit-days`),
    ).toHaveLength(2);
  });

  it("while loading: common.loading", async () => {
    mockPatientApi({ visitDays: () => new Promise<Response>(() => {}) });
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
