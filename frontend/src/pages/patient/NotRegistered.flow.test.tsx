/**
 * Every screen that used to end on the not-registered notice now has the number field.
 * - Nothing typed to keep: the page reloads after registering.
 * - 401/403 while sending: the same number resumes with the input kept; another number
 *   reloads (one patient's input never goes out under another patient's id).
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearPid, loadPid, savePid } from "../../patient/pid";
import { reloadPage } from "../../patient/reload";
import { jsonResponse } from "../../test/fetchMock";
import History from "./History";
import { MARK, callsTo, mockPatientApi } from "./testing/api";
import { savedInputs } from "./testing/device";
import { PID, questionText, s } from "./testing/fixtures";
import { renderPatient } from "./testing/render";
import Today from "./Today";
import Visit from "./Visit";

vi.mock("../../patient/reload", () => ({ reloadPage: vi.fn() }));

const OTHER_PID = "P-OTHER001";
const MARK_URL = `/api/patient/${PID}/record-marks`;
const REGISTER_URL = "/api/patient/register";
const ROUTES = [
  { path: "/today", element: <Today /> },
  { path: "/history", element: <History /> },
  { path: "/visit", element: <Visit /> },
];

function numberField() {
  return screen.getByRole("textbox", { name: s("register.number_label") });
}

function button(key: string) {
  return screen.getByRole("button", { name: s(key) });
}

async function enterNumber(pid: string) {
  await userEvent.type(numberField(), pid);
  await userEvent.click(button("register.number_submit"));
}

async function expectPanel() {
  expect(
    await screen.findByText(s("error.not_registered")),
  ).toBeInTheDocument();
  expect(numberField()).toBeInTheDocument();
  expect(document.querySelector("form form")).toBeNull();
}

beforeEach(() => {
  clearPid();
  savePid(PID);
  vi.mocked(reloadPage).mockClear();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("no saved pid: the number field, then a reload", () => {
  it.each([
    ["/today", "Today"],
    ["/history", "History"],
  ])("%s", async (path) => {
    clearPid();
    const fetchMock = mockPatientApi();
    renderPatient(ROUTES, path);
    await expectPanel();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.getByRole("navigation")).toBeInTheDocument();
    await enterNumber(PID);
    await waitFor(() => expect(reloadPage).toHaveBeenCalledTimes(1));
    expect(loadPid()).toBe(PID);
  });
});

describe("401/403 while loading: the number field, then a reload", () => {
  it("Today: questions 403", async () => {
    mockPatientApi({
      questions: () => jsonResponse({ error: "forbidden" }, 403),
    });
    renderPatient(ROUTES, "/today");
    await expectPanel();
    await enterNumber(PID);
    await waitFor(() => expect(reloadPage).toHaveBeenCalledTimes(1));
  });

  it("History: visit-days 401", async () => {
    mockPatientApi({
      visitDays: () => jsonResponse({ error: "not_logged_in" }, 401),
    });
    renderPatient(ROUTES, "/history");
    await expectPanel();
    await enterNumber(PID);
    await waitFor(() => expect(reloadPage).toHaveBeenCalledTimes(1));
  });
});

describe("Today: 401 while sending", () => {
  /** The first POST is 401, later ones go through. */
  function apiWithExpiredCookie() {
    let registered = false;
    return mockPatientApi({
      recordMark: () =>
        registered
          ? jsonResponse(MARK)
          : jsonResponse({ error: "not_logged_in" }, 401),
      register: () => {
        registered = true;
        return jsonResponse({ ok: true });
      },
    });
  }

  async function answerAndSend() {
    const group = await screen.findByRole("group", {
      name: questionText("diarrhea"),
    });
    await userEvent.click(
      within(group).getByRole("button", { name: s("answer.present") }),
    );
    await userEvent.type(
      screen.getByRole("textbox", { name: s("today.free_text_label") }),
      "kept text",
    );
    await userEvent.click(button("today.submit"));
  }

  it("the same number: the input is back and only the second press sends it", async () => {
    const fetchMock = apiWithExpiredCookie();
    renderPatient(ROUTES, "/today");
    await answerAndSend();
    await expectPanel();
    await enterNumber(PID);

    expect(await screen.findByText(s("register.done"))).toBeInTheDocument();
    expect(reloadPage).not.toHaveBeenCalled();
    expect(
      screen.getByRole("textbox", { name: s("today.free_text_label") }),
    ).toHaveValue("kept text");
    const group = screen.getByRole("group", { name: questionText("diarrhea") });
    expect(
      within(group).getByRole("button", { name: s("answer.present") }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(callsTo(fetchMock, "POST", MARK_URL)).toHaveLength(1);

    await userEvent.click(button("today.submit"));
    expect(await screen.findByText(s("today.saved"))).toBeInTheDocument();
    expect(callsTo(fetchMock, "POST", MARK_URL)).toHaveLength(2);
    expect(await savedInputs()).toEqual([
      {
        by_proxy: false,
        answers: [{ question_key: "diarrhea", value: "present" }],
        free_text: "kept text",
      },
    ]);
  });

  it("another number: reloads and does not send the input", async () => {
    const fetchMock = apiWithExpiredCookie();
    renderPatient(ROUTES, "/today");
    await answerAndSend();
    await expectPanel();
    await enterNumber(OTHER_PID);

    await waitFor(() => expect(reloadPage).toHaveBeenCalledTimes(1));
    expect(loadPid()).toBe(OTHER_PID);
    expect(callsTo(fetchMock, "POST", MARK_URL)).toHaveLength(1);
    expect(await savedInputs()).toEqual([]);
    expect(await savedInputs(OTHER_PID)).toEqual([]);
    expect(callsTo(fetchMock, "POST", REGISTER_URL)).toHaveLength(1);
  });

  it("a wrong number: stays on the panel and the input is still kept", async () => {
    let tried = false;
    mockPatientApi({
      recordMark: () => jsonResponse({ error: "not_logged_in" }, 401),
      register: () => {
        const reply = tried
          ? jsonResponse({ ok: true })
          : jsonResponse({ error: "unknown_patient" }, 404);
        tried = true;
        return reply;
      },
    });
    renderPatient(ROUTES, "/today");
    await answerAndSend();
    await expectPanel();
    await enterNumber(OTHER_PID);
    expect(
      await screen.findByText(s("register.number_invalid")),
    ).toBeInTheDocument();
    expect(loadPid()).toBe(PID);
    await userEvent.clear(numberField());
    await enterNumber(PID);
    await screen.findByText(s("register.done"));
    expect(
      screen.getByRole("textbox", { name: s("today.free_text_label") }),
    ).toHaveValue("kept text");
  });

  it("too_sick: the same number returns to the form without sending by itself", async () => {
    const fetchMock = apiWithExpiredCookie();
    renderPatient(ROUTES, "/today");
    await userEvent.click(
      await screen.findByRole("button", {
        name: s("today.too_sick_button"),
      }),
    );
    await userEvent.click(button("today.too_sick_confirm_yes"));
    await expectPanel();
    await enterNumber(PID);
    await screen.findByText(s("register.done"));
    expect(callsTo(fetchMock, "POST", MARK_URL)).toHaveLength(1);
    expect(button("today.too_sick_button")).toBeEnabled();
  });
});

describe("Today: 401 when undoing too_sick", () => {
  const UNDO_URL = `${MARK_URL}/undo`;

  function apiWithExpiredUndo() {
    let registered = false;
    return mockPatientApi({
      undo: () =>
        registered
          ? jsonResponse({ ok: true })
          : jsonResponse({ error: "not_logged_in" }, 401),
      register: () => {
        registered = true;
        return jsonResponse({ ok: true });
      },
    });
  }

  async function recordAndUndo() {
    await userEvent.click(
      await screen.findByRole("button", {
        name: s("today.too_sick_button"),
      }),
    );
    await userEvent.click(button("today.too_sick_confirm_yes"));
    await screen.findByText(s("today.too_sick_done"));
    await userEvent.click(button("today.undo"));
  }

  it("the same number: the saved record stays and the undo can be pressed again", async () => {
    const fetchMock = apiWithExpiredUndo();
    renderPatient(ROUTES, "/today");
    await recordAndUndo();
    await expectPanel();
    expect(screen.queryByRole("button", { name: s("today.undo") })).toBeNull();
    await enterNumber(PID);

    expect(await screen.findByText(s("register.done"))).toBeInTheDocument();
    expect(reloadPage).not.toHaveBeenCalled();
    expect(screen.getByText(s("today.too_sick_done"))).toBeInTheDocument();
    await userEvent.click(button("today.undo"));
    expect(await screen.findByText(s("today.undone"))).toBeInTheDocument();
    expect(callsTo(fetchMock, "POST", UNDO_URL)).toHaveLength(2);
  });

  it("another number: reloads and does not undo", async () => {
    const fetchMock = apiWithExpiredUndo();
    renderPatient(ROUTES, "/today");
    await recordAndUndo();
    await expectPanel();
    await enterNumber(OTHER_PID);
    await waitFor(() => expect(reloadPage).toHaveBeenCalledTimes(1));
    expect(callsTo(fetchMock, "POST", UNDO_URL)).toHaveLength(1);
    // The record of this number stays on the device
    expect(await savedInputs()).toHaveLength(1);
  });
});

describe("Visit: 401 while sending", () => {
  it("the reception number stays and it can be sent again", async () => {
    let registered = false;
    const fetchMock = mockPatientApi({
      visit: () =>
        registered
          ? jsonResponse({ ok: true, message_key: "visit.done" })
          : jsonResponse({ error: "not_logged_in" }, 401),
      register: () => {
        registered = true;
        return jsonResponse({ ok: true });
      },
    });
    renderPatient(ROUTES, "/visit");
    await userEvent.type(
      screen.getByRole("textbox", { name: s("visit.reception_label") }),
      "A-023",
    );
    await userEvent.click(button("visit.submit"));
    await expectPanel();
    await enterNumber(OTHER_PID);

    expect(await screen.findByText(s("register.done"))).toBeInTheDocument();
    expect(reloadPage).not.toHaveBeenCalled();
    expect(
      screen.getByRole("textbox", { name: s("visit.reception_label") }),
    ).toHaveValue("A-023");
    await userEvent.click(button("visit.submit"));
    expect(await screen.findByText(s("visit.done"))).toBeInTheDocument();
    expect(callsTo(fetchMock, "POST", "/api/visit")).toHaveLength(2);
    expect(screen.queryByText(s("register.done"))).toBeNull();
  });
});
