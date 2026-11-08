/** P0 登録で、すでに別の番号が入っているスマホの確認（docs/decisions.md）。 */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearPid, loadPid, savePid } from "../../patient/pid";
import { jsonResponse, mockFetch } from "../../test/fetchMock";
import Register from "./Register";
import { PID, s } from "./testing/fixtures";
import { renderPatient } from "./testing/render";

const SAVED = "P-OLD00001";
const ROUTES = [
  { path: "/register", element: <Register /> },
  { path: "/today", element: <p>today page</p> },
];

function button(key: string): HTMLElement {
  return screen.getByRole("button", { name: s(key) });
}

function neverReplies(): Promise<Response> {
  return new Promise(() => undefined);
}

beforeEach(() => {
  clearPid();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("Register on a phone that has another number", () => {
  it("shows both numbers and sends nothing until the patient chooses", () => {
    savePid(SAVED);
    const fetchMock = mockFetch(() => jsonResponse({ ok: true }));
    renderPatient(ROUTES, `/register?pid=${PID}`);
    expect(screen.getByText(s("register.switch_notice"))).toBeInTheDocument();
    expect(screen.getByText(s("register.switch_about"))).toBeInTheDocument();
    expect(
      screen.getByText(s("register.switch_current_label")).nextElementSibling,
    ).toHaveTextContent(SAVED);
    expect(
      screen.getByText(s("register.switch_new_label")).nextElementSibling,
    ).toHaveTextContent(PID);
    expect(
      screen.queryByRole("button", { name: s("register.button") }),
    ).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(loadPid()).toBe(SAVED);
  });

  it("makes keeping the number the prominent choice", () => {
    savePid(SAVED);
    mockFetch(() => jsonResponse({ ok: true }));
    renderPatient(ROUTES, `/register?pid=${PID}`);
    expect(button("register.switch_cancel")).toHaveClass("p-button--primary");
    expect(button("register.switch_confirm")).not.toHaveClass(
      "p-button--primary",
    );
  });

  it("cancel keeps the number, sends nothing and goes to /today", async () => {
    savePid(SAVED);
    const fetchMock = mockFetch(() => jsonResponse({ ok: true }));
    renderPatient(ROUTES, `/register?pid=${PID}`);
    await userEvent.click(button("register.switch_cancel"));
    expect(await screen.findByText("today page")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(loadPid()).toBe(SAVED);
  });

  it("confirm registers the new number and goes to /today", async () => {
    savePid(SAVED);
    mockFetch(() => jsonResponse({ ok: true }));
    renderPatient(ROUTES, `/register?pid=${PID}`);
    await userEvent.click(button("register.switch_confirm"));
    expect(await screen.findByText("today page")).toBeInTheDocument();
    expect(loadPid()).toBe(PID);
  });

  it("a failed switch keeps the old number and both choices", async () => {
    savePid(SAVED);
    mockFetch(() => jsonResponse({ error: "boom" }, 500));
    renderPatient(ROUTES, `/register?pid=${PID}`);
    await userEvent.click(button("register.switch_confirm"));
    expect(await screen.findByText(s("error.generic"))).toBeInTheDocument();
    expect(loadPid()).toBe(SAVED);
    expect(button("register.switch_cancel")).toBeEnabled();
    expect(button("register.switch_confirm")).toBeEnabled();
  });

  it("both choices wait while the switch is being sent", async () => {
    savePid(SAVED);
    mockFetch(neverReplies);
    renderPatient(ROUTES, `/register?pid=${PID}`);
    await userEvent.click(button("register.switch_confirm"));
    expect(button("register.switch_cancel")).toBeDisabled();
    expect(button("register.switch_confirm")).toBeDisabled();
  });

  it("the same number needs no confirmation", () => {
    savePid(PID);
    mockFetch(() => jsonResponse({ ok: true }));
    renderPatient(ROUTES, `/register?pid=${PID}`);
    expect(button("register.button")).toBeInTheDocument();
    expect(screen.queryByText(s("register.switch_notice"))).toBeNull();
  });

  it("a malformed QR shows the error, not the confirmation", () => {
    savePid(SAVED);
    mockFetch(() => jsonResponse({ ok: true }));
    renderPatient(ROUTES, "/register?pid=../doctor");
    expect(screen.getByText(s("register.invalid"))).toBeInTheDocument();
    expect(screen.queryByText(s("register.switch_notice"))).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });
});
