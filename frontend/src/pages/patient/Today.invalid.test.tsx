/**
 * P1 で患者 API が契約と違う 2xx の本文を返したとき（docs/architecture.md §9 W2b の決定）。
 * 画面を真っ白にせず error.generic を出す。期待する文は patient_strings.json のキーから引く。
 */
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearPid, savePid } from "../../patient/pid";
import { jsonResponse } from "../../test/fetchMock";
import { mockPatientApi } from "./testing/api";
import { PID, questionText, s } from "./testing/fixtures";
import { renderPatient } from "./testing/render";
import Today from "./Today";

const ROUTES = [{ path: "/today", element: <Today /> }];

beforeEach(() => {
  clearPid();
  savePid(PID);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function expectPageShown() {
  expect(
    screen.getByRole("heading", { level: 1, name: s("today.title") }),
  ).toBeInTheDocument();
}

describe("Today (P1): malformed 200 bodies", () => {
  it.each([
    ["questions missing", { skill_version: "regimen-folfox@1" }],
    ["questions null", { skill_version: "x", questions: null }],
    [
      "question without text",
      { skill_version: "x", questions: [{ key: "a" }] },
    ],
  ])(
    "GET questions (%s): error.generic, too_sick still offered",
    async (_label, body) => {
      mockPatientApi({ questions: () => jsonResponse(body) });
      renderToday();
      expect(await screen.findByText(s("error.generic"))).toBeInTheDocument();
      expectPageShown();
      expect(
        screen.getByRole("button", { name: s("today.too_sick_button") }),
      ).toBeEnabled();
    },
  );

  it.each([
    ["notices missing", { entry_id: 1 }],
    ["notices null", { entry_id: 1, notices: null }],
    ["notices not strings", { entry_id: 1, notices: [1] }],
  ])(
    "POST entries (%s): error.generic, the input is kept",
    async (_label, body) => {
      mockPatientApi({ createEntry: () => jsonResponse(body) });
      renderToday();
      const group = await screen.findByRole("group", {
        name: questionText("diarrhea"),
      });
      await userEvent.click(
        within(group).getByRole("button", { name: s("answer.present") }),
      );
      await userEvent.click(
        screen.getByRole("button", { name: s("today.submit") }),
      );
      expect(await screen.findByText(s("error.generic"))).toBeInTheDocument();
      expectPageShown();
      expect(screen.queryByText(s("today.saved"))).toBeNull();
      expect(
        within(group).getByRole("button", { name: s("answer.present") }),
      ).toHaveAttribute("aria-pressed", "true");
    },
  );

  it("POST entries for too_sick with a malformed body: error.generic", async () => {
    mockPatientApi({ createEntry: () => jsonResponse({ entry_id: 1 }) });
    renderToday();
    await userEvent.click(
      await screen.findByRole("button", { name: s("today.too_sick_button") }),
    );
    expect(await screen.findByText(s("error.generic"))).toBeInTheDocument();
    expect(screen.queryByText(s("today.too_sick_done"))).toBeNull();
  });
});

function renderToday() {
  return renderPatient(ROUTES, "/today");
}
