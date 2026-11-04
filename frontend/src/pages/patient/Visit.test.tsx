/** P3 受診時（/visit）。期待する文は patient_strings.json のキーから引く。 */
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearPid, savePid } from "../../patient/pid";
import { jsonResponse } from "../../test/fetchMock";
import { callsTo, mockPatientApi } from "./testing/api";
import { PID, s } from "./testing/fixtures";
import { renderPatient } from "./testing/render";
import Visit from "./Visit";

const ROUTES = [{ path: "/visit", element: <Visit /> }];

// 患者画面のテストは文字列リテラルに ASCII 以外を書かない約束なので、コードポイントから作る
const EMOJI = String.fromCodePoint(0x1f600);
const HIRAGANA_A = String.fromCodePoint(0x3042);
const KANJI = String.fromCodePoint(0x53d7, 0x4ed8);
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
      { reception_no: text },
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
      { reception_no: "A-023" },
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

  it("uses the cookie only (works without a saved pid)", async () => {
    clearPid();
    const fetchMock = mockPatientApi();
    renderPatient(ROUTES, "/visit");
    await userEvent.type(field(), "A-023");
    await userEvent.click(submit());
    await screen.findByText(s("visit.done"));
    expect(callsTo(fetchMock, "POST", "/api/visit")).toHaveLength(1);
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
