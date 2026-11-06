/** P3 受診時（/visit）。期待する文は patient_strings.json のキーから引く。 */
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DeviceEntry } from "../../api/types";
import { clearPid, savePid } from "../../patient/pid";
import { fixtureBody } from "../../test/apiFixtures";
import { jsonResponse } from "../../test/fetchMock";
import { callsTo, mockPatientApi } from "./testing/api";
import { savedInputs, seedDevice } from "./testing/device";
import { ENTRIES, NEXT_LINE, PID, s } from "./testing/fixtures";
import { renderPatient } from "./testing/render";
import Visit from "./Visit";

const ROUTES = [{ path: "/visit", element: <Visit /> }];
const WINDOW_URL = `/api/patient/${PID}/visit-window`;

// 患者画面のテストは文字列リテラルに ASCII 以外を書かない約束なので、コードポイントから作る
const EMOJI = String.fromCodePoint(0x1f600);
const HIRAGANA_A = String.fromCodePoint(0x3042);
const KANJI = String.fromCodePoint(0x53d7, 0x4ed8);
const ZERO_WIDTH_SPACE = String.fromCodePoint(0x200b);
const ZERO_WIDTH_JOINER = String.fromCodePoint(0x200d);
/** 全角の "A-023"（NFKC で半角の "A-023" になる）。 */
const FULLWIDTH_A_023 = String.fromCodePoint(
  0xff21,
  0xff0d,
  0xff10,
  0xff12,
  0xff13,
);

function field() {
  return screen.getByRole("textbox", { name: s("visit.reception_label") });
}

function submit() {
  return screen.getByRole("button", { name: s("visit.submit") });
}

beforeEach(() => {
  clearPid();
  savePid(PID);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("Visit (P3)", () => {
  it("shows the reception number field", () => {
    mockPatientApi();
    renderPatient(ROUTES, "/visit");
    expect(
      screen.getByRole("heading", { level: 1, name: s("visit.title") }),
    ).toBeInTheDocument();
    expect(field()).toHaveAttribute(
      "placeholder",
      s("visit.reception_placeholder"),
    );
    expect(screen.getByRole("navigation")).toBeInTheDocument();
  });

  it("says what happens when sending (visit.about) and shows an example number", () => {
    mockPatientApi();
    renderPatient(ROUTES, "/visit");
    expect(screen.getByText(s("visit.about"))).toBeInTheDocument();
    const example = screen.getByText(s("visit.example"));
    expect(field()).toHaveAttribute("aria-describedby", example.id);
  });

  it("empty or malformed: visit.invalid and no request", async () => {
    const fetchMock = mockPatientApi();
    renderPatient(ROUTES, "/visit");
    await userEvent.click(submit());
    expect(screen.getByText(s("visit.invalid"))).toBeInTheDocument();
    await userEvent.type(field(), "   ");
    await userEvent.click(submit());
    expect(screen.getByText(s("visit.invalid"))).toBeInTheDocument();
    await userEvent.clear(field());
    await userEvent.click(field());
    await userEvent.paste(EMOJI.repeat(33));
    await userEvent.click(submit());
    expect(screen.getByText(s("visit.invalid"))).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it.each([
    ["a pasted U+200B", `A-023${ZERO_WIDTH_SPACE}`],
    ["an emoji with ZWJ", `${EMOJI}${ZERO_WIDTH_JOINER}${EMOJI}`],
    ["a control character", `A${String.fromCodePoint(0)}B`],
  ])(
    "a number only the server would refuse (%s): visit.invalid and no request",
    async (_label, text) => {
      const fetchMock = mockPatientApi();
      renderPatient(ROUTES, "/visit");
      await userEvent.click(field());
      await userEvent.paste(text);
      await userEvent.click(submit());
      expect(screen.getByText(s("visit.invalid"))).toBeInTheDocument();
      expect(screen.queryByText(s("visit.records_rejected"))).toBeNull();
      expect(callsTo(fetchMock, "POST", "/api/visit")).toEqual([]);
    },
  );

  it.each([
    ["with Japanese and a space", `${KANJI} 12`],
    ["21 chars", "A".repeat(21)],
    ["32 Japanese chars", HIRAGANA_A.repeat(32)],
    ["32 emoji (64 UTF-16 units)", EMOJI.repeat(32)],
  ])("a valid number (%s) is sent as is, not cut", async (_label, text) => {
    const fetchMock = mockPatientApi();
    renderPatient(ROUTES, "/visit");
    expect(field()).not.toHaveAttribute("maxlength");
    await userEvent.click(field());
    await userEvent.paste(text);
    await userEvent.click(submit());
    await screen.findByText(s("visit.done"));
    expect(callsTo(fetchMock, "POST", "/api/visit")).toEqual([
      { reception_no: text, entries: [] },
    ]);
  });

  it("POST /api/visit with the normalized number, then only visit.done", async () => {
    const fetchMock = mockPatientApi();
    renderPatient(ROUTES, "/visit");
    await userEvent.type(field(), ` ${FULLWIDTH_A_023} `);
    await userEvent.click(submit());
    const done = await screen.findByText(s("visit.done"));
    expect(done.textContent).toBe(s("visit.done"));
    expect(callsTo(fetchMock, "POST", "/api/visit")).toEqual([
      { reception_no: "A-023", entries: [] },
    ]);
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
    const nav = screen.getByRole("navigation");
    expect(
      within(nav).getByRole("link", { name: s("nav.today") }),
    ).toHaveAttribute("href", "/today");
    expect(
      within(nav).getByRole("link", { name: s("nav.history") }),
    ).toHaveAttribute("href", "/history");
    expect(
      within(nav).getByRole("link", { name: s("nav.visit") }),
    ).toHaveAttribute("href", "/visit");
    expect(
      within(nav).getByRole("link", { name: s("nav.settings") }),
    ).toHaveAttribute("href", "/settings");
  });

  it("409 no_course: visit.no_course and the form stays", async () => {
    mockPatientApi({
      visit: () => jsonResponse({ error: "no_course" }, 409),
    });
    renderPatient(ROUTES, "/visit");
    await userEvent.type(field(), "A-023");
    await userEvent.click(submit());
    expect(await screen.findByText(s("visit.no_course"))).toBeInTheDocument();
    expect(screen.queryByText(s("error.generic"))).toBeNull();
    expect(field()).toHaveValue("A-023");
  });

  it("409 already_printed: visit.already_printed, the form stays and the records stay", async () => {
    await seedDevice(ENTRIES);
    mockPatientApi({
      visit: () => jsonResponse(fixtureBody("visit_already_printed"), 409),
    });
    renderPatient(ROUTES, "/visit");
    await userEvent.type(field(), "A-023");
    await userEvent.click(submit());
    expect(
      await screen.findByText(s("visit.already_printed")),
    ).toBeInTheDocument();
    expect(screen.queryByText(s("error.generic"))).toBeNull();
    expect(screen.queryByText(s("visit.done"))).toBeNull();
    expect(field()).toHaveValue("A-023");
    await expect(savedInputs()).resolves.toHaveLength(ENTRIES.length);
  });

  it("409 too_many_visits: visit.too_many, the form stays and the records stay", async () => {
    await seedDevice(ENTRIES);
    mockPatientApi({
      visit: () => jsonResponse(fixtureBody("visit_too_many"), 409),
    });
    renderPatient(ROUTES, "/visit");
    await userEvent.type(field(), "A-023");
    await userEvent.click(submit());
    expect(await screen.findByText(s("visit.too_many"))).toBeInTheDocument();
    expect(screen.queryByText(s("error.generic"))).toBeNull();
    expect(screen.queryByText(s("visit.done"))).toBeNull();
    expect(field()).toHaveValue("A-023");
    await expect(savedInputs()).resolves.toHaveLength(ENTRIES.length);
  });

  it("without a saved pid: the number form and no request", async () => {
    clearPid();
    const fetchMock = mockPatientApi();
    renderPatient(ROUTES, "/visit");
    expect(screen.getByText(s("error.not_registered"))).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
    await userEvent.type(
      screen.getByRole("textbox", { name: s("register.number_label") }),
      PID,
    );
    await userEvent.click(
      screen.getByRole("button", { name: s("register.number_submit") }),
    );
    expect(await screen.findByText(s("register.done"))).toBeInTheDocument();
    await userEvent.type(field(), "A-023");
    await userEvent.click(submit());
    await screen.findByText(s("visit.done"));
    expect(callsTo(fetchMock, "GET", WINDOW_URL)).toHaveLength(1);
  });

  it("401/403: error.not_registered", async () => {
    mockPatientApi({
      visit: () => jsonResponse({ error: "not_registered" }, 403),
    });
    renderPatient(ROUTES, "/visit");
    await userEvent.type(field(), "A-023");
    await userEvent.click(submit());
    expect(
      await screen.findByText(s("error.not_registered")),
    ).toBeInTheDocument();
    expect(screen.queryByText(s("visit.done"))).toBeNull();
  });

  it("server error: error.generic and the form stays", async () => {
    mockPatientApi({ visit: () => jsonResponse({ error: "boom" }, 500) });
    renderPatient(ROUTES, "/visit");
    await userEvent.type(field(), "A-023");
    await userEvent.click(submit());
    expect(await screen.findByText(s("error.generic"))).toBeInTheDocument();
    expect(submit()).toBeEnabled();
    expect(field()).toHaveValue("A-023");
  });

  it("400 from the server: visit.invalid", async () => {
    mockPatientApi({
      visit: () => jsonResponse({ error: "invalid_reception_no" }, 400),
    });
    renderPatient(ROUTES, "/visit");
    await userEvent.type(field(), "A-023");
    await userEvent.click(submit());
    expect(await screen.findByText(s("visit.invalid"))).toBeInTheDocument();
  });
});

describe("Visit: records on this phone", () => {
  /** ENTRIES は 10-29・10-31・11-02。範囲で 10-29 を外す。 */
  const WINDOW = { start: "2026-10-30", end: "2026-11-09" };

  async function send() {
    await userEvent.type(field(), "A-023");
    await userEvent.click(submit());
  }

  it("sends only the records in the window, without the pid and the question text", async () => {
    await seedDevice(ENTRIES);
    const fetchMock = mockPatientApi({
      visitWindow: () => jsonResponse(WINDOW),
    });
    renderPatient(ROUTES, "/visit");
    await send();
    await screen.findByText(s("visit.done"));
    const [body] = callsTo(fetchMock, "POST", "/api/visit") as [
      { reception_no: string; entries: Record<string, unknown>[] },
    ];
    expect(body.reception_no).toBe("A-023");
    expect(body.entries.map((e) => e.client_entry_id)).toEqual([
      ENTRIES[1]!.client_entry_id,
      ENTRIES[2]!.client_entry_id,
    ]);
    expect(body.entries[0]).not.toHaveProperty("pid");
    expect(body.entries[0]!.answers).toEqual([
      { question_key: "diarrhea", value: "present", temperature: null },
      { question_key: "fever", value: "measured", temperature: 37.9 },
    ]);
  });

  it("does not send the records of another patient", async () => {
    await seedDevice([{ ...ENTRIES[1]!, pid: "P-EVAL0001" }]);
    const fetchMock = mockPatientApi();
    renderPatient(ROUTES, "/visit");
    await send();
    await screen.findByText(s("visit.done"));
    expect(callsTo(fetchMock, "POST", "/api/visit")).toEqual([
      { reception_no: "A-023", entries: [] },
    ]);
  });

  it("a saved record the reception would refuse does not stop the others", async () => {
    const refused: DeviceEntry = {
      ...ENTRIES[2]!,
      client_entry_id: "refused",
      kind: "free_text",
      answers: [],
      free_text: NEXT_LINE,
    };
    await seedDevice([ENTRIES[1]!, refused]);
    const fetchMock = mockPatientApi({
      visitWindow: () => jsonResponse(WINDOW),
    });
    renderPatient(ROUTES, "/visit");
    await send();
    await screen.findByText(s("visit.done"));
    const [body] = callsTo(fetchMock, "POST", "/api/visit") as [
      { entries: Record<string, unknown>[] },
    ];
    expect(body.entries.map((e) => e.client_entry_id)).toEqual([
      ENTRIES[1]!.client_entry_id,
    ]);
  });

  it("keeps the records on the phone after sending", async () => {
    await seedDevice(ENTRIES);
    mockPatientApi();
    renderPatient(ROUTES, "/visit");
    await send();
    await screen.findByText(s("visit.done"));
    await expect(savedInputs()).resolves.toHaveLength(ENTRIES.length);
  });

  it("no course from visit-window: visit.no_course and nothing sent", async () => {
    const fetchMock = mockPatientApi({
      visitWindow: () => jsonResponse({ error: "no_course" }, 409),
    });
    renderPatient(ROUTES, "/visit");
    await send();
    expect(await screen.findByText(s("visit.no_course"))).toBeInTheDocument();
    expect(callsTo(fetchMock, "POST", "/api/visit")).toEqual([]);
  });

  it("visit-window 403: the number form, then sends with the new number", async () => {
    let registered = false;
    const fetchMock = mockPatientApi({
      visitWindow: () =>
        registered
          ? jsonResponse(WINDOW)
          : jsonResponse({ error: "not_registered" }, 403),
      register: () => {
        registered = true;
        return jsonResponse({ ok: true });
      },
    });
    renderPatient(ROUTES, "/visit");
    await send();
    await userEvent.type(
      await screen.findByRole("textbox", { name: s("register.number_label") }),
      PID,
    );
    await userEvent.click(
      screen.getByRole("button", { name: s("register.number_submit") }),
    );
    expect(await screen.findByText(s("register.done"))).toBeInTheDocument();
    expect(field()).toHaveValue("A-023");
    await userEvent.click(submit());
    await screen.findByText(s("visit.done"));
    expect(callsTo(fetchMock, "POST", "/api/visit")).toHaveLength(1);
  });

  it("visit-window failure: error.generic, nothing sent, the number stays", async () => {
    const fetchMock = mockPatientApi({
      visitWindow: () => jsonResponse({ error: "boom" }, 500),
    });
    renderPatient(ROUTES, "/visit");
    await send();
    expect(await screen.findByText(s("error.generic"))).toBeInTheDocument();
    expect(callsTo(fetchMock, "POST", "/api/visit")).toEqual([]);
    expect(field()).toHaveValue("A-023");
  });

  it("cannot read the records: error.generic and never sends an empty list", async () => {
    const fetchMock = mockPatientApi();
    vi.stubGlobal("indexedDB", undefined);
    renderPatient(ROUTES, "/visit");
    await send();
    expect(await screen.findByText(s("error.generic"))).toBeInTheDocument();
    expect(callsTo(fetchMock, "POST", "/api/visit")).toEqual([]);
  });

  it.each([
    ["422", 422, "invalid_input"],
    ["413", 413, "body_too_large"],
  ])(
    "the server refuses the records (%s): visit.records_rejected, not the number message",
    async (_label, status, error) => {
      mockPatientApi({ visit: () => jsonResponse({ error }, status) });
      renderPatient(ROUTES, "/visit");
      await send();
      expect(
        await screen.findByText(s("visit.records_rejected")),
      ).toBeInTheDocument();
      expect(screen.queryByText(s("visit.invalid"))).toBeNull();
      expect(field()).toHaveValue("A-023");
    },
  );
});
