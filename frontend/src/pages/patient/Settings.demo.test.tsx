/** P5 設定の「見本の記録を入れる」（plan-device-records §5.10）。 */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DemoEntriesResponse } from "../../api/types";
import { listDeviceEntries } from "../../patient/deviceStore";
import { clearPid, savePid } from "../../patient/pid";
import { apiFixture } from "../../test/apiFixtures";
import { jsonResponse } from "../../test/fetchMock";
import { callsTo, mockPatientApi } from "./testing/api";
import { seedDevice } from "./testing/device";
import { ENTRIES, PID, s } from "./testing/fixtures";
import { renderPatient } from "./testing/render";
import Settings from "./Settings";

const CONFIG_URL = `/api/patient/${PID}/demo-config`;
const ENTRIES_URL = `/api/patient/${PID}/demo-entries`;
const DEMO = (apiFixture("patient_demo_entries").body as DemoEntriesResponse)
  .entries;

const demoOn = () => jsonResponse(apiFixture("patient_demo_config").body);

function renderSettings() {
  return renderPatient(
    [{ path: "/settings", element: <Settings /> }],
    "/settings",
  );
}

function addButton() {
  return screen.findByRole("button", { name: s("demo.add_entries") });
}

beforeEach(() => {
  clearPid();
  savePid(PID);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("Settings: sample records", () => {
  it("demo_tools false: no button and demo-entries is not called", async () => {
    const fetchMock = mockPatientApi();
    renderSettings();
    await waitFor(() =>
      expect(callsTo(fetchMock, "GET", CONFIG_URL)).toHaveLength(1),
    );
    await Promise.resolve();
    expect(
      screen.queryByRole("button", { name: s("demo.add_entries") }),
    ).toBeNull();
    expect(screen.queryByText(s("demo.title"))).toBeNull();
    expect(callsTo(fetchMock, "GET", ENTRIES_URL)).toEqual([]);
  });

  it.each([
    ["404", 404],
    ["500", 500],
    ["403", 403],
  ])("demo-config %s: no button and no error", async (_label, status) => {
    const fetchMock = mockPatientApi({
      demoConfig: () => jsonResponse({ error: "x" }, status),
    });
    renderSettings();
    await waitFor(() =>
      expect(callsTo(fetchMock, "GET", CONFIG_URL)).toHaveLength(1),
    );
    await Promise.resolve();
    expect(
      screen.queryByRole("button", { name: s("demo.add_entries") }),
    ).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("demo_tools true: saves the sample records on the phone", async () => {
    mockPatientApi({ demoConfig: demoOn });
    renderSettings();
    await userEvent.click(await addButton());
    expect(await screen.findByText(s("demo.added"))).toBeInTheDocument();
    const saved = await listDeviceEntries(PID);
    expect(saved).toHaveLength(DEMO.length);
    expect(saved.map((e) => e.client_entry_id)).toEqual(
      expect.arrayContaining(DEMO.map((e) => e.client_entry_id)),
    );
  });

  it("pressing twice does not add more, and keeps the patient's own records", async () => {
    await seedDevice(ENTRIES);
    const fetchMock = mockPatientApi({ demoConfig: demoOn });
    renderSettings();
    await userEvent.click(await addButton());
    await screen.findByText(s("demo.added"));
    await userEvent.click(await addButton());
    await waitFor(() =>
      expect(callsTo(fetchMock, "GET", ENTRIES_URL)).toHaveLength(2),
    );
    await screen.findByText(s("demo.added"));
    await expect(listDeviceEntries(PID)).resolves.toHaveLength(
      DEMO.length + ENTRIES.length,
    );
  });

  it("demo-entries failure: error.generic and can press again", async () => {
    let fail = true;
    mockPatientApi({
      demoConfig: demoOn,
      demoEntries: () =>
        fail
          ? jsonResponse({ error: "not_found" }, 404)
          : jsonResponse(apiFixture("patient_demo_entries").body),
    });
    renderSettings();
    await userEvent.click(await addButton());
    expect(await screen.findByText(s("error.generic"))).toBeInTheDocument();
    await expect(listDeviceEntries(PID)).resolves.toEqual([]);
    fail = false;
    await userEvent.click(await addButton());
    expect(await screen.findByText(s("demo.added"))).toBeInTheDocument();
    expect(screen.queryByText(s("error.generic"))).toBeNull();
  });
});
