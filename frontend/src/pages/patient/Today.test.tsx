/**
 * P1 今日の記録。期待する文は patient_strings.json のキー、質問文は API の questions[].text から引く
 * （このファイルに日本語を直書きしない。患者画面のアーキテクチャテストの対象になるため）。
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearPid, savePid } from "../../patient/pid";
import { jsonResponse } from "../../test/fetchMock";
import { callsTo, mockPatientApi } from "./testing/api";
import { PID, QUESTIONS, questionText, s } from "./testing/fixtures";
import { renderPatient, type InitialEntry } from "./testing/render";
import History from "./History";
import Today from "./Today";

const ENTRIES_URL = `/api/patient/${PID}/entries`;
const FREE_TEXT = "free text sample";

const ROUTES = [
  { path: "/today", element: <Today /> },
  { path: "/history", element: <History /> },
];

function renderToday(initial: InitialEntry = "/today") {
  return renderPatient(ROUTES, initial);
}

async function choose(key: string, answerKey: string) {
  const group = await screen.findByRole("group", { name: questionText(key) });
  await userEvent.click(
    within(group).getByRole("button", { name: s(answerKey) }),
  );
}

function submitButton() {
  return screen.getByRole("button", { name: s("today.submit") });
}

beforeEach(() => {
  clearPid();
  savePid(PID);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("Today (P1): registration", () => {
  it("without a saved pid: error.not_registered and no request", () => {
    clearPid();
    const fetchMock = mockPatientApi();
    renderToday();
    expect(
      screen.getByRole("heading", { level: 1, name: s("today.title") }),
    ).toBeInTheDocument();
    expect(screen.getByText(s("error.not_registered"))).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("questions 403: error.not_registered", async () => {
    mockPatientApi({
      questions: () => jsonResponse({ error: "forbidden" }, 403),
    });
    renderToday();
    expect(
      await screen.findByText(s("error.not_registered")),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: s("today.too_sick_button") }),
    ).toBeNull();
  });

  it("right after registering: register.done", async () => {
    mockPatientApi();
    renderToday({ pathname: "/today", state: { registered: true } });
    expect(screen.getByText(s("register.done"))).toBeInTheDocument();
    await screen.findByRole("group", { name: questionText("fever") });
  });

  it("bottom navigation links to today and history", async () => {
    mockPatientApi();
    renderToday();
    const nav = screen.getByRole("navigation");
    const today = within(nav).getByRole("link", { name: s("nav.today") });
    const history = within(nav).getByRole("link", { name: s("nav.history") });
    expect(today).toHaveAttribute("href", "/today");
    expect(today).toHaveAttribute("aria-current", "page");
    expect(history).toHaveAttribute("href", "/history");
    await userEvent.click(history);
    expect(screen.getByTestId("where")).toHaveTextContent(/^\/history$/);
  });
});

describe("Today (P1): stage 0 too_sick", () => {
  it("one tap sends {too_sick, by_proxy:false} and finishes", async () => {
    const fetchMock = mockPatientApi();
    renderToday();
    await userEvent.click(
      screen.getByRole("button", { name: s("today.too_sick_button") }),
    );
    expect(
      await screen.findByText(s("today.too_sick_done")),
    ).toBeInTheDocument();
    expect(callsTo(fetchMock, "POST", ENTRIES_URL)).toEqual([
      { too_sick: true, by_proxy: false },
    ]);
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.queryByRole("group")).toBeNull();
  });

  it("works before the questions arrive and with the proxy toggle", async () => {
    const fetchMock = mockPatientApi({
      questions: () => new Promise<Response>(() => {}),
    });
    renderToday();
    await userEvent.click(
      screen.getByRole("checkbox", { name: s("today.proxy_toggle") }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: s("today.too_sick_button") }),
    );
    await screen.findByText(s("today.too_sick_done"));
    expect(callsTo(fetchMock, "POST", ENTRIES_URL)).toEqual([
      { too_sick: true, by_proxy: true },
    ]);
  });
});

describe("Today (P1): stage 1-2 questions and free text", () => {
  it("shows each question text from the API with three big choices", async () => {
    mockPatientApi();
    renderToday();
    for (const q of QUESTIONS.filter((x) => x.answer_type === "three_level")) {
      const group = await screen.findByRole("group", { name: q.text });
      const names = within(group)
        .getAllByRole("button")
        .map((b) => b.textContent);
      expect(names).toEqual([
        s("answer.none"),
        s("answer.present"),
        s("answer.hard"),
      ]);
    }
    const fever = screen.getByRole("group", { name: questionText("fever") });
    expect(
      within(fever)
        .getAllByRole("button")
        .map((b) => b.textContent),
    ).toEqual([s("answer.not_measured"), s("answer.measured")]);
    expect(
      screen.queryByRole("textbox", { name: s("temperature.label") }),
    ).toBeNull();
  });

  it("empty form is not sent (submit disabled)", async () => {
    const fetchMock = mockPatientApi();
    renderToday();
    await screen.findByRole("group", { name: questionText("diarrhea") });
    expect(submitButton()).toBeDisabled();
    await userEvent.type(
      screen.getByRole("textbox", { name: s("today.free_text_label") }),
      "   ",
    );
    expect(submitButton()).toBeDisabled();
    await userEvent.click(
      screen.getByRole("checkbox", { name: s("today.proxy_toggle") }),
    );
    expect(submitButton()).toBeDisabled();
    expect(callsTo(fetchMock, "POST", ENTRIES_URL)).toEqual([]);
  });

  it("sends only the answered questions as EntryCreate", async () => {
    const fetchMock = mockPatientApi();
    renderToday();
    await choose("numbness", "answer.none");
    await choose("diarrhea", "answer.hard");
    expect(screen.getByText(s("today.incomplete"))).toBeInTheDocument();
    await userEvent.type(
      screen.getByRole("textbox", { name: s("today.free_text_label") }),
      `  ${FREE_TEXT}  `,
    );
    await userEvent.click(
      screen.getByRole("checkbox", { name: s("today.proxy_toggle") }),
    );
    await userEvent.click(submitButton());
    expect(await screen.findByText(s("today.saved"))).toBeInTheDocument();
    expect(callsTo(fetchMock, "POST", ENTRIES_URL)).toEqual([
      {
        by_proxy: true,
        answers: [
          { question_key: "numbness", value: "none" },
          { question_key: "diarrhea", value: "hard" },
        ],
        free_text: FREE_TEXT,
      },
    ]);
    expect(screen.queryByRole("group")).toBeNull();
  });

  it("free text only is sent with empty answers", async () => {
    const fetchMock = mockPatientApi();
    renderToday();
    await userEvent.type(
      await screen.findByRole("textbox", { name: s("today.free_text_label") }),
      FREE_TEXT,
    );
    await userEvent.click(submitButton());
    await screen.findByText(s("today.saved"));
    expect(callsTo(fetchMock, "POST", ENTRIES_URL)).toEqual([
      { by_proxy: false, answers: [], free_text: FREE_TEXT },
    ]);
  });

  it("pressing the same choice again clears it", async () => {
    mockPatientApi();
    renderToday();
    const group = await screen.findByRole("group", {
      name: questionText("diarrhea"),
    });
    const present = within(group).getByRole("button", {
      name: s("answer.present"),
    });
    expect(present).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(present);
    expect(present).toHaveAttribute("aria-pressed", "true");
    expect(submitButton()).toBeEnabled();
    await userEvent.click(present);
    expect(present).toHaveAttribute("aria-pressed", "false");
    expect(submitButton()).toBeDisabled();
  });

  it("all answered: no incomplete hint", async () => {
    mockPatientApi();
    renderToday();
    for (const q of QUESTIONS) {
      await choose(
        q.key,
        q.answer_type === "temperature" ? "answer.not_measured" : "answer.none",
      );
    }
    expect(screen.queryByText(s("today.incomplete"))).toBeNull();
  });
});

describe("Today (P1): temperature", () => {
  it("measured shows a number field; invalid values block sending", async () => {
    const fetchMock = mockPatientApi();
    renderToday();
    await choose("fever", "answer.measured");
    const input = screen.getByRole("textbox", { name: s("temperature.label") });
    for (const [bad, key] of [
      ["", "temperature.invalid"],
      ["50", "temperature.out_of_range"],
      ["45.1", "temperature.out_of_range"],
      ["abc", "temperature.invalid"],
    ] as const) {
      await userEvent.clear(input);
      if (bad) {
        await userEvent.type(input, bad);
      }
      await userEvent.click(submitButton());
      expect(screen.getByText(s(key))).toBeInTheDocument();
      expect(input).toHaveAttribute("aria-invalid", "true");
    }
    expect(callsTo(fetchMock, "POST", ENTRIES_URL)).toEqual([]);
    await userEvent.clear(input);
    await userEvent.type(input, "36.8");
    expect(screen.queryByText(s("temperature.invalid"))).toBeNull();
    expect(screen.queryByText(s("temperature.out_of_range"))).toBeNull();
  });

  it("not measured sends without temperature", async () => {
    const fetchMock = mockPatientApi();
    renderToday();
    await choose("fever", "answer.not_measured");
    await userEvent.click(submitButton());
    await screen.findByText(s("today.saved"));
    expect(callsTo(fetchMock, "POST", ENTRIES_URL)).toEqual([
      {
        by_proxy: false,
        answers: [{ question_key: "fever", value: "not_measured" }],
        free_text: null,
      },
    ]);
  });

  it("38.2 is sent and the fever notice is shown verbatim", async () => {
    const fetchMock = mockPatientApi({
      createEntry: () =>
        jsonResponse({ entry_id: 5, notices: ["fixed_rule.fever_38"] }),
    });
    renderToday();
    await choose("fever", "answer.measured");
    await userEvent.type(
      screen.getByRole("textbox", { name: s("temperature.label") }),
      "38.2",
    );
    await userEvent.click(submitButton());
    const notice = await screen.findByRole("alert");
    expect(notice.textContent).toBe(s("fixed_rule.fever_38"));
    expect(notice).toHaveClass("p-notice");
    expect(screen.getByText(s("today.saved"))).toBeInTheDocument();
    expect(callsTo(fetchMock, "POST", ENTRIES_URL)).toEqual([
      {
        by_proxy: false,
        answers: [
          { question_key: "fever", value: "measured", temperature: 38.2 },
        ],
        free_text: null,
      },
    ]);
  });

  it("no notices: no notice box", async () => {
    mockPatientApi();
    renderToday();
    await choose("fever", "answer.measured");
    await userEvent.type(
      screen.getByRole("textbox", { name: s("temperature.label") }),
      "37.9",
    );
    await userEvent.click(submitButton());
    await screen.findByText(s("today.saved"));
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("Today (P1): two temperature questions", () => {
  const EVENING = {
    key: "fever_evening",
    text: "fever evening sample",
    answer_type: "temperature" as const,
  };

  function mockTwoFevers() {
    return mockPatientApi({
      questions: () =>
        jsonResponse({
          skill_version: "regimen-folfox@2",
          questions: [...QUESTIONS, EVENING],
        }),
    });
  }

  async function measure(name: string) {
    const group = await screen.findByRole("group", { name });
    await userEvent.click(
      within(group).getByRole("button", { name: s("answer.measured") }),
    );
    return within(group).getByRole("textbox", {
      name: s("temperature.label"),
    });
  }

  it("each question has its own field and value", async () => {
    const fetchMock = mockTwoFevers();
    renderToday();
    const morning = await measure(questionText("fever"));
    const evening = await measure(EVENING.text);
    await userEvent.type(morning, "38.2");
    expect(evening).toHaveValue("");
    await userEvent.type(evening, "36.5");
    expect(morning).toHaveValue("38.2");
    await userEvent.click(submitButton());
    await screen.findByText(s("today.saved"));
    expect(callsTo(fetchMock, "POST", ENTRIES_URL)).toEqual([
      {
        by_proxy: false,
        answers: [
          { question_key: "fever", value: "measured", temperature: 38.2 },
          {
            question_key: "fever_evening",
            value: "measured",
            temperature: 36.5,
          },
        ],
        free_text: null,
      },
    ]);
  });

  it("only the empty field is marked invalid", async () => {
    const fetchMock = mockTwoFevers();
    renderToday();
    const morning = await measure(questionText("fever"));
    const evening = await measure(EVENING.text);
    await userEvent.type(morning, "38.2");
    await userEvent.click(submitButton());
    expect(morning).toHaveAttribute("aria-invalid", "false");
    expect(evening).toHaveAttribute("aria-invalid", "true");
    expect(screen.getAllByText(s("temperature.invalid"))).toHaveLength(1);
    expect(callsTo(fetchMock, "POST", ENTRIES_URL)).toEqual([]);
  });
});

describe("Today (P1): errors and starting over", () => {
  it("POST 500: error.generic and the form stays for a retry", async () => {
    let fail = true;
    const fetchMock = mockPatientApi({
      createEntry: () =>
        fail
          ? jsonResponse({ error: "boom" }, 500)
          : jsonResponse({ entry_id: 2, notices: [] }),
    });
    renderToday();
    await choose("diarrhea", "answer.present");
    await userEvent.click(submitButton());
    expect(await screen.findByText(s("error.generic"))).toBeInTheDocument();
    fail = false;
    await userEvent.click(submitButton());
    await screen.findByText(s("today.saved"));
    expect(callsTo(fetchMock, "POST", ENTRIES_URL)).toHaveLength(2);
  });

  it("POST 401: error.not_registered", async () => {
    mockPatientApi({
      createEntry: () => jsonResponse({ error: "not_registered" }, 401),
    });
    renderToday();
    await userEvent.click(
      await screen.findByRole("button", { name: s("today.too_sick_button") }),
    );
    expect(
      await screen.findByText(s("error.not_registered")),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("questions 500: common.load_failed, too_sick still works", async () => {
    const fetchMock = mockPatientApi({
      questions: () => jsonResponse({ error: "boom" }, 500),
    });
    renderToday();
    expect(
      await screen.findByText(s("common.load_failed")),
    ).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: s("today.too_sick_button") }),
    );
    await screen.findByText(s("today.too_sick_done"));
    expect(callsTo(fetchMock, "POST", ENTRIES_URL)).toHaveLength(1);
  });

  it("after saving, the today link starts a new record", async () => {
    mockPatientApi();
    renderToday();
    await choose("diarrhea", "answer.present");
    await userEvent.click(submitButton());
    await screen.findByText(s("today.saved"));
    await userEvent.click(screen.getByRole("link", { name: s("nav.today") }));
    const group = await screen.findByRole("group", {
      name: questionText("diarrhea"),
    });
    expect(
      within(group).getByRole("button", { name: s("answer.present") }),
    ).toHaveAttribute("aria-pressed", "false");
    await waitFor(() =>
      expect(screen.queryByText(s("today.saved"))).toBeNull(),
    );
  });
});
