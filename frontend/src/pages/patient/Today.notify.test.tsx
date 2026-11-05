/** 記録を保存したら、バッジと表示中の通知を消す。 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import PatientLayout from "../../layouts/PatientLayout";
import { clearPid, savePid } from "../../patient/pid";
import { jsonResponse, mockFetch } from "../../test/fetchMock";
import { callsTo, mockPatientApi } from "./testing/api";
import { PID, STRINGS, s } from "./testing/fixtures";
import { installFakePush, type FakePush } from "./testing/pushBrowser";
import { renderPatient } from "./testing/render";
import Today from "./Today";

let push: FakePush;

beforeEach(() => {
  clearPid();
  savePid(PID);
  push = installFakePush({ permission: "granted", subscribed: true });
});

afterEach(() => {
  push.uninstall();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("Today: after saving", () => {
  it("clears the badge and closes the shown notifications", async () => {
    const fetchMock = mockPatientApi();
    renderPatient([{ path: "/today", element: <Today /> }], "/today");
    await userEvent.click(
      await screen.findByRole("button", { name: s("today.too_sick_button") }),
    );
    expect(push.clearAppBadge).not.toHaveBeenCalled();
    await userEvent.click(
      screen.getByRole("button", { name: s("today.too_sick_confirm_yes") }),
    );
    await screen.findByText(s("today.too_sick_done"));
    expect(
      callsTo(fetchMock, "POST", `/api/patient/${PID}/entries`),
    ).toHaveLength(1);
    await waitFor(() => expect(push.clearAppBadge).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(push.shown[0]?.close).toHaveBeenCalledTimes(1));
  });

  it("a failed save keeps the badge", async () => {
    mockPatientApi({
      createEntry: () => jsonResponse({ error: "boom" }, 500),
    });
    renderPatient([{ path: "/today", element: <Today /> }], "/today");
    await userEvent.click(
      await screen.findByRole("button", { name: s("today.too_sick_button") }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: s("today.too_sick_confirm_yes") }),
    );
    await screen.findByText(s("error.generic"));
    expect(push.clearAppBadge).not.toHaveBeenCalled();
  });
});

describe("PatientLayout: opening the app", () => {
  function renderLayout() {
    mockFetch(() => jsonResponse(STRINGS));
    return render(
      <MemoryRouter initialEntries={["/history"]}>
        <Routes>
          <Route element={<PatientLayout />}>
            <Route path="/history" element={<p>history</p>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );
  }

  function setVisibility(state: DocumentVisibilityState) {
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => state,
    });
    fireEvent(document, new Event("visibilitychange"));
  }

  afterEach(() => {
    delete (document as unknown as Record<string, unknown>).visibilityState;
  });

  it("clears the badge and the shown notifications on open", async () => {
    renderLayout();
    await screen.findByText("history");
    await waitFor(() => expect(push.clearAppBadge).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(push.shown[0]?.close).toHaveBeenCalledTimes(1));
  });

  it("clears again when coming back to the app, not when leaving", async () => {
    renderLayout();
    await screen.findByText("history");
    await waitFor(() => expect(push.clearAppBadge).toHaveBeenCalledTimes(1));
    setVisibility("hidden");
    expect(push.clearAppBadge).toHaveBeenCalledTimes(1);
    setVisibility("visible");
    await waitFor(() => expect(push.clearAppBadge).toHaveBeenCalledTimes(2));
  });

  it("stops listening after unmount", async () => {
    const view = renderLayout();
    await screen.findByText("history");
    await waitFor(() => expect(push.clearAppBadge).toHaveBeenCalledTimes(1));
    view.unmount();
    setVisibility("visible");
    expect(push.clearAppBadge).toHaveBeenCalledTimes(1);
  });
});
