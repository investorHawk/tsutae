/** P0 登録（/register?pid=...）。期待する文は全て patient_strings.json のキーから引く。 */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearPid, loadPid, savePid } from "../../patient/pid";
import { callOf, jsonResponse, mockFetch } from "../../test/fetchMock";
import Register from "./Register";
import { PID, s } from "./testing/fixtures";
import { renderPatient } from "./testing/render";

const ROUTES = [
  { path: "/register", element: <Register /> },
  { path: "/today", element: <p>today page</p> },
];

beforeEach(() => {
  clearPid();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("Register (P0)", () => {
  it("shows the title and the synthetic-data notice", () => {
    mockFetch(() => jsonResponse({ ok: true }));
    renderPatient(ROUTES, `/register?pid=${PID}`);
    expect(
      screen.getByRole("heading", { level: 1, name: s("register.title") }),
    ).toBeInTheDocument();
    expect(screen.getByText(s("app.notice_synthetic"))).toBeInTheDocument();
  });

  it("without pid: register.required, no button, no request", () => {
    const fetchMock = mockFetch(() => jsonResponse({ ok: true }));
    renderPatient(ROUTES, "/register");
    expect(screen.getByText(s("register.required"))).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("malformed pid: register.invalid, no button, no request", () => {
    const fetchMock = mockFetch(() => jsonResponse({ ok: true }));
    renderPatient(ROUTES, "/register?pid=../doctor");
    expect(screen.getByText(s("register.invalid"))).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("registers, saves the pid and goes to /today", async () => {
    const fetchMock = mockFetch(() => jsonResponse({ ok: true }));
    renderPatient(ROUTES, `/register?pid=${PID}`);
    await userEvent.click(
      screen.getByRole("button", { name: s("register.button") }),
    );
    expect(await screen.findByText("today page")).toBeInTheDocument();
    expect(screen.getByTestId("where")).toHaveTextContent(/^\/today$/);
    const call = callOf(fetchMock);
    expect(call.method).toBe("POST");
    expect(call.url).toBe("/api/patient/register");
    expect(call.body).toEqual({ pid: PID });
    expect(loadPid()).toBe(PID);
  });

  it("unknown pid (404): register.invalid, stays, pid not saved", async () => {
    mockFetch(() => jsonResponse({ error: "unknown_patient" }, 404));
    renderPatient(ROUTES, "/register?pid=P-ZZZZ9999");
    await userEvent.click(
      screen.getByRole("button", { name: s("register.button") }),
    );
    expect(await screen.findByText(s("register.invalid"))).toBeInTheDocument();
    expect(screen.getByTestId("where")).toHaveTextContent(/^\/register$/);
    expect(loadPid()).toBeNull();
  });

  it("server error: error.generic and the button stays", async () => {
    mockFetch(() => jsonResponse({ error: "boom" }, 500));
    renderPatient(ROUTES, `/register?pid=${PID}`);
    await userEvent.click(
      screen.getByRole("button", { name: s("register.button") }),
    );
    expect(await screen.findByText(s("error.generic"))).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: s("register.button") }),
    ).toBeEnabled();
    expect(loadPid()).toBeNull();
  });

  it("storage unavailable: error.generic and no request (no cookie without a saved pid)", async () => {
    const fetchMock = mockFetch(() => jsonResponse({ ok: true }));
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    renderPatient(ROUTES, `/register?pid=${PID}`);
    await userEvent.click(
      screen.getByRole("button", { name: s("register.button") }),
    );
    expect(await screen.findByText(s("error.generic"))).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.getByTestId("where")).toHaveTextContent(/^\/register$/);
  });

  it("the pid is saved before the request (a cookie never exists without a saved pid)", async () => {
    let savedAtRequest: string | null = null;
    mockFetch(() => {
      savedAtRequest = loadPid();
      return jsonResponse({ ok: true });
    });
    renderPatient(ROUTES, `/register?pid=${PID}`);
    await userEvent.click(
      screen.getByRole("button", { name: s("register.button") }),
    );
    await screen.findByText("today page");
    expect(savedAtRequest).toBe(PID);
  });

  it("registration failing puts back the pid that was saved before", async () => {
    savePid("P-OLD00001");
    mockFetch(() => jsonResponse({ error: "boom" }, 500));
    renderPatient(ROUTES, `/register?pid=${PID}`);
    await userEvent.click(
      screen.getByRole("button", { name: s("register.button") }),
    );
    expect(await screen.findByText(s("error.generic"))).toBeInTheDocument();
    expect(loadPid()).toBe("P-OLD00001");
  });

  it("malformed 200 body: error.generic and the pid is not kept", async () => {
    mockFetch(() => jsonResponse({}));
    renderPatient(ROUTES, `/register?pid=${PID}`);
    await userEvent.click(
      screen.getByRole("button", { name: s("register.button") }),
    );
    expect(await screen.findByText(s("error.generic"))).toBeInTheDocument();
    expect(screen.getByTestId("where")).toHaveTextContent(/^\/register$/);
    expect(loadPid()).toBeNull();
  });

  it("the probe works but the real save fails: no request", async () => {
    const fetchMock = mockFetch(() => jsonResponse({ ok: true }));
    const realSetItem = Storage.prototype.setItem;
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(function (
      this: Storage,
      key: string,
      value: string,
    ) {
      if (key === "tsutae.pid") {
        throw new DOMException("full", "QuotaExceededError");
      }
      realSetItem.call(this, key, value);
    });
    renderPatient(ROUTES, `/register?pid=${PID}`);
    await userEvent.click(
      screen.getByRole("button", { name: s("register.button") }),
    );
    expect(await screen.findByText(s("error.generic"))).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(loadPid()).toBeNull();
  });
});
