/**
 * P1 今日の記録: 記録した後（修正ボード P2-2〜P2-5）。
 * - 押せない「記録する」の理由（today.submit_hint）
 * - 記録した後は登録の案内を消す・記録した内容の要約・「追加で記録する」
 * - 「つらくて書けない」の後だけ「取り消す」（押す前の確認は無い）
 * 期待する文は patient_strings.json のキーから引く（このファイルに日本語を直書きしない）。
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearPid, savePid } from "../../patient/pid";
import { jsonResponse } from "../../test/fetchMock";
import { callsTo, mockPatientApi } from "./testing/api";
import { PID, questionText, s } from "./testing/fixtures";
import { renderPatient, type InitialEntry } from "./testing/render";
import Today from "./Today";

const ENTRIES_URL = `/api/patient/${PID}/entries`;
const ENTRY_ID = 41;
const UNDO_URL = `${ENTRIES_URL}/${ENTRY_ID}/undo`;

function renderToday(initial: InitialEntry = "/today") {
  return renderPatient([{ path: "/today", element: <Today /> }], initial);
}

async function choose(key: string, answerKey: string) {
  const group = await screen.findByRole("group", { name: questionText(key) });
  await userEvent.click(
    within(group).getByRole("button", { name: s(answerKey) }),
  );
}

function button(key: string) {
  return screen.getByRole("button", { name: s(key) });
}

function savedReply() {
  return jsonResponse({ entry_id: ENTRY_ID, notices: [] });
}

function summary(): HTMLElement {
  return screen.getByRole("region", { name: s("today.saved_summary") });
}

beforeEach(() => {
  clearPid();
  savePid(PID);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("Today: why the submit button is disabled (P2-2)", () => {
  it("nothing chosen: today.submit_hint describes the disabled button", async () => {
    mockPatientApi();
    renderToday();
    await screen.findByRole("group", { name: questionText("fever") });
    const hint = screen.getByText(s("today.submit_hint"));
    expect(button("today.submit")).toBeDisabled();
    expect(button("today.submit")).toHaveAttribute("aria-describedby", hint.id);
  });

  it("after choosing one: no hint, the button is enabled", async () => {
    mockPatientApi();
    renderToday();
    await choose("diarrhea", "answer.present");
    expect(screen.queryByText(s("today.submit_hint"))).toBeNull();
    expect(button("today.submit")).toBeEnabled();
    expect(button("today.submit")).not.toHaveAttribute("aria-describedby");
  });
});

describe("Today: after saving (P2-3, P2-4)", () => {
  it("register.done is removed once something is recorded", async () => {
    mockPatientApi({ createEntry: savedReply });
    renderToday({ pathname: "/today", state: { registered: true } });
    expect(screen.getByText(s("register.done"))).toBeInTheDocument();
    await choose("diarrhea", "answer.present");
    await userEvent.click(button("today.submit"));
    expect(await screen.findByText(s("today.saved"))).toBeInTheDocument();
    expect(screen.queryByText(s("register.done"))).toBeNull();
  });

  it("shows a short summary of what was recorded", async () => {
    mockPatientApi({ createEntry: savedReply });
    renderToday();
    await choose("numbness", "answer.hard");
    await choose("diarrhea", "answer.present");
    await choose("stomatitis", "answer.none");
    await choose("fever", "answer.measured");
    await userEvent.type(
      screen.getByRole("textbox", { name: s("temperature.label") }),
      "37.8",
    );
    await userEvent.type(
      screen.getByRole("textbox", { name: s("today.free_text_label") }),
      "free text sample",
    );
    await userEvent.click(button("today.submit"));
    await screen.findByText(s("today.saved"));

    const box = summary();
    expect(box).toHaveTextContent(
      `${s("symptom.numbness")} ${s("answer.hard")}`,
    );
    expect(box).toHaveTextContent(
      `${s("symptom.diarrhea")} ${s("answer.present")}`,
    );
    expect(box).toHaveTextContent(
      `${s("symptom.fever")} ${s("history.temperature_value").replace("{value}", "37.8")}`,
    );
    expect(box).toHaveTextContent(
      `${s("history.free_text")} ${s("history.free_text_present")}`,
    );
    expect(box).not.toHaveTextContent(s("symptom.stomatitis"));
    expect(box).not.toHaveTextContent("free text sample");
    // 答えは太字
    expect(within(box).getByText(s("answer.hard")).tagName).toBe("STRONG");
  });

  it("all none: history.all_none", async () => {
    mockPatientApi({ createEntry: savedReply });
    renderToday();
    await choose("diarrhea", "answer.none");
    await userEvent.click(button("today.submit"));
    await screen.findByText(s("today.saved"));
    expect(summary()).toHaveTextContent(s("history.all_none"));
  });

  it("normal records have no undo button", async () => {
    mockPatientApi({ createEntry: savedReply });
    renderToday();
    await choose("diarrhea", "answer.present");
    await userEvent.click(button("today.submit"));
    await screen.findByText(s("today.saved"));
    expect(screen.queryByRole("button", { name: s("today.undo") })).toBeNull();
  });

  it("today.add_more starts a new empty record on the same page", async () => {
    const fetchMock = mockPatientApi({ createEntry: savedReply });
    renderToday();
    await choose("diarrhea", "answer.present");
    await userEvent.click(button("today.submit"));
    await screen.findByText(s("today.saved"));
    await userEvent.click(button("today.add_more"));

    const group = await screen.findByRole("group", {
      name: questionText("diarrhea"),
    });
    expect(
      within(group).getByRole("button", { name: s("answer.present") }),
    ).toHaveAttribute("aria-pressed", "false");
    expect(screen.queryByText(s("today.saved"))).toBeNull();
    expect(button("today.submit")).toBeDisabled();

    await choose("numbness", "answer.hard");
    await userEvent.click(button("today.submit"));
    await screen.findByText(s("today.saved"));
    expect(callsTo(fetchMock, "POST", ENTRIES_URL)).toEqual([
      {
        by_proxy: false,
        answers: [{ question_key: "diarrhea", value: "present" }],
        free_text: null,
      },
      {
        by_proxy: false,
        answers: [{ question_key: "numbness", value: "hard" }],
        free_text: null,
      },
    ]);
  });
});

describe("Today: undo too_sick (P2-5)", () => {
  async function recordTooSick() {
    await userEvent.click(button("today.too_sick_button"));
    await screen.findByText(s("today.too_sick_done"));
  }

  it("too_sick is recorded with one tap and can be undone", async () => {
    const fetchMock = mockPatientApi({ createEntry: savedReply });
    renderToday();
    await recordTooSick();
    expect(summary()).toHaveTextContent(s("history.too_sick"));

    await userEvent.click(button("today.undo"));
    expect(await screen.findByText(s("today.undone"))).toBeInTheDocument();
    expect(callsTo(fetchMock, "POST", UNDO_URL)).toHaveLength(1);
    // 記録する前の画面に戻る
    expect(screen.queryByText(s("today.too_sick_done"))).toBeNull();
    expect(button("today.too_sick_button")).toBeEnabled();
    await screen.findByRole("group", { name: questionText("fever") });
  });

  it("the input before too_sick is kept after undoing", async () => {
    mockPatientApi({ createEntry: savedReply });
    renderToday();
    await choose("diarrhea", "answer.present");
    await userEvent.click(button("today.too_sick_button"));
    await userEvent.click(button("today.too_sick_confirm_yes"));
    await screen.findByText(s("today.too_sick_done"));
    await userEvent.click(button("today.undo"));
    await screen.findByText(s("today.undone"));
    const group = screen.getByRole("group", { name: questionText("diarrhea") });
    expect(
      within(group).getByRole("button", { name: s("answer.present") }),
    ).toHaveAttribute("aria-pressed", "true");
  });

  it("409 not_undoable: today.undo_failed and no undo button", async () => {
    mockPatientApi({
      createEntry: savedReply,
      undo: () => jsonResponse({ error: "not_undoable" }, 409),
    });
    renderToday();
    await recordTooSick();
    await userEvent.click(button("today.undo"));
    expect(await screen.findByText(s("today.undo_failed"))).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: s("today.undo") })).toBeNull();
    expect(screen.getByText(s("today.too_sick_done"))).toBeInTheDocument();
  });

  it("network failure: error.generic, the undo button stays for a retry", async () => {
    const fetchMock = mockPatientApi({
      createEntry: savedReply,
      undo: () => jsonResponse({ error: "internal_error" }, 500),
    });
    renderToday();
    await recordTooSick();
    await userEvent.click(button("today.undo"));
    expect(await screen.findByText(s("error.generic"))).toBeInTheDocument();
    expect(button("today.undo")).toBeEnabled();
    await userEvent.click(button("today.undo"));
    await waitFor(() =>
      expect(callsTo(fetchMock, "POST", UNDO_URL)).toHaveLength(2),
    );
  });

  it("while undoing, the undo button is disabled", async () => {
    mockPatientApi({
      createEntry: savedReply,
      undo: () => new Promise<Response>(() => {}),
    });
    renderToday();
    await recordTooSick();
    await userEvent.click(button("today.undo"));
    expect(button("today.undo")).toBeDisabled();
  });
});
