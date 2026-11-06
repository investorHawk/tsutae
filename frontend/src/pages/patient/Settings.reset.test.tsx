/** P5 設定の「このスマホの登録と記録を消す」（plan-device-records §5.9）。 */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { listDeviceEntries } from "../../patient/deviceStore";
import { clearPid, loadPid, savePid } from "../../patient/pid";
import { jsonResponse } from "../../test/fetchMock";
import { callsTo, mockPatientApi } from "./testing/api";
import { seedDevice } from "./testing/device";
import { ENTRIES, PID, s } from "./testing/fixtures";
import {
  ENDPOINT,
  installFakePush,
  type FakePush,
  type FakePushOptions,
} from "./testing/pushBrowser";
import { renderPatient } from "./testing/render";
import Settings from "./Settings";

const UNREGISTER_URL = `/api/patient/${PID}/unregister`;
const OTHER_PID = "P-EVAL0001";

let fake: FakePush | null = null;

function givenPush(options: FakePushOptions = {}): FakePush {
  fake = installFakePush(options);
  return fake;
}

function button(key: string) {
  return screen.getByRole("button", { name: s(key) });
}

function renderSettings() {
  return renderPatient(
    [{ path: "/settings", element: <Settings /> }],
    "/settings",
  );
}

/** 2段階の確認を通して消す。 */
async function resetThroughConfirms() {
  await userEvent.click(button("device_reset.button"));
  await userEvent.click(button("device_reset.confirm_first_yes"));
  await userEvent.click(button("device_reset.confirm_second_yes"));
}

beforeEach(() => {
  clearPid();
  savePid(PID);
});

afterEach(() => {
  fake?.uninstall();
  fake = null;
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("Settings: delete this phone's registration and records", () => {
  it("shows the section and the note about the home screen icon", () => {
    mockPatientApi();
    renderSettings();
    expect(
      screen.getByRole("heading", { level: 2, name: s("device_reset.title") }),
    ).toBeInTheDocument();
    expect(screen.getByText(s("device_reset.about"))).toBeInTheDocument();
    expect(screen.getByText(s("device_reset.icon_note"))).toBeInTheDocument();
  });

  it("deletes nothing until the second confirmation, and never uses window.confirm", async () => {
    const confirm = vi.fn(() => true);
    vi.stubGlobal("confirm", confirm);
    await seedDevice(ENTRIES);
    const fetchMock = mockPatientApi();
    renderSettings();
    await userEvent.click(button("device_reset.button"));
    expect(screen.getByText(s("device_reset.confirm_first"))).toBeVisible();
    await userEvent.click(button("device_reset.confirm_first_yes"));
    expect(screen.getByText(s("device_reset.confirm_second"))).toBeVisible();
    expect(callsTo(fetchMock, "POST", UNREGISTER_URL)).toEqual([]);
    expect(loadPid()).toBe(PID);
    await expect(listDeviceEntries(PID)).resolves.toHaveLength(ENTRIES.length);
    expect(confirm).not.toHaveBeenCalled();
  });

  it("a double tap on the first step lands on cancel, not on delete", async () => {
    mockPatientApi();
    renderSettings();
    await userEvent.click(button("device_reset.button"));
    const firstYes = button("device_reset.confirm_first_yes");
    const firstButtons: HTMLElement[] = Array.from(
      firstYes.parentElement!.querySelectorAll("button"),
    );
    expect(firstButtons.indexOf(firstYes)).toBe(0);
    await userEvent.click(firstYes);
    const secondButtons: HTMLElement[] = Array.from(
      button("device_reset.cancel").parentElement!.querySelectorAll("button"),
    );
    expect(secondButtons[0]).toBe(button("device_reset.cancel"));
  });

  it.each([
    ["first", ["device_reset.button"]],
    ["second", ["device_reset.button", "device_reset.confirm_first_yes"]],
  ])("cancel at the %s step changes nothing", async (_label, keys) => {
    await seedDevice(ENTRIES);
    const fetchMock = mockPatientApi();
    renderSettings();
    for (const key of keys) {
      await userEvent.click(button(key));
    }
    await userEvent.click(button("device_reset.cancel"));
    expect(button("device_reset.button")).toBeVisible();
    expect(callsTo(fetchMock, "POST", UNREGISTER_URL)).toEqual([]);
    expect(loadPid()).toBe(PID);
    await expect(listDeviceEntries(PID)).resolves.toHaveLength(ENTRIES.length);
  });

  it("with a subscription: unregister with the endpoint, unsubscribe, then the records and the pid", async () => {
    const push = givenPush({ subscribed: true, permission: "granted" });
    await seedDevice(ENTRIES);
    await seedDevice([{ ...ENTRIES[0]!, pid: OTHER_PID }]);
    const fetchMock = mockPatientApi();
    renderSettings();
    await resetThroughConfirms();
    expect(await screen.findByText(s("device_reset.done"))).toBeInTheDocument();
    expect(callsTo(fetchMock, "POST", UNREGISTER_URL)).toEqual([
      { endpoint: ENDPOINT },
    ]);
    expect(push.isSubscribed()).toBe(false);
    await expect(listDeviceEntries(PID)).resolves.toEqual([]);
    await expect(listDeviceEntries(OTHER_PID)).resolves.toHaveLength(1);
    expect(loadPid()).toBeNull();
    // 消した後はその場で番号を入れ直せる（撮り直し §5.10）
    expect(screen.getByText(s("error.not_registered"))).toBeInTheDocument();
    expect(
      screen.getByRole("textbox", { name: s("register.number_label") }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: s("device_reset.button") }),
    ).toBeNull();
  });

  it("without a subscription: unregister with a null endpoint", async () => {
    const fetchMock = mockPatientApi();
    renderSettings();
    await resetThroughConfirms();
    await screen.findByText(s("device_reset.done"));
    expect(callsTo(fetchMock, "POST", UNREGISTER_URL)).toEqual([
      { endpoint: null },
    ]);
  });

  it("the cookie is already gone (403): counts as unregistered", async () => {
    await seedDevice(ENTRIES);
    mockPatientApi({
      unregister: () => jsonResponse({ error: "not_registered" }, 403),
    });
    renderSettings();
    await resetThroughConfirms();
    expect(await screen.findByText(s("device_reset.done"))).toBeInTheDocument();
    await expect(listDeviceEntries(PID)).resolves.toEqual([]);
    expect(loadPid()).toBeNull();
  });

  it("the patient is not in the database (404): counts as unregistered, retry is not needed", async () => {
    await seedDevice(ENTRIES);
    mockPatientApi({
      unregister: () => jsonResponse({ error: "unknown_patient" }, 404),
    });
    renderSettings();
    await resetThroughConfirms();
    expect(await screen.findByText(s("device_reset.done"))).toBeInTheDocument();
    expect(screen.queryByText(s("device_reset.partial"))).toBeNull();
    await expect(listDeviceEntries(PID)).resolves.toEqual([]);
    expect(loadPid()).toBeNull();
  });

  it("a 404 from something other than the API (a proxy, say) is still a failure", async () => {
    mockPatientApi({
      unregister: () => jsonResponse({ error: "not_found" }, 404),
    });
    renderSettings();
    await resetThroughConfirms();
    expect(
      await screen.findByText(s("device_reset.partial")),
    ).toBeInTheDocument();
  });

  it("the browser still has the subscription: the retry sends its endpoint too", async () => {
    const push = givenPush({
      subscribed: true,
      permission: "granted",
      unsubscribeError: new Error("x"),
    });
    let fail = true;
    const fetchMock = mockPatientApi({
      unregister: () =>
        fail
          ? jsonResponse({ error: "boom" }, 500)
          : jsonResponse({ ok: true }),
    });
    renderSettings();
    await resetThroughConfirms();
    await screen.findByText(s("device_reset.partial"));
    expect(push.isSubscribed()).toBe(true);
    fail = false;
    await userEvent.click(button("device_reset.retry"));
    await screen.findByText(s("device_reset.partial"));
    expect(callsTo(fetchMock, "POST", UNREGISTER_URL)).toEqual([
      { endpoint: ENDPOINT },
      { endpoint: ENDPOINT },
    ]);
  });

  it("the server fails: the rest still runs, then says so and can retry", async () => {
    const push = givenPush({ subscribed: true, permission: "granted" });
    await seedDevice(ENTRIES);
    let fail = true;
    const fetchMock = mockPatientApi({
      unregister: () =>
        fail
          ? jsonResponse({ error: "boom" }, 500)
          : jsonResponse({ ok: true }),
    });
    renderSettings();
    await resetThroughConfirms();
    expect(
      await screen.findByText(s("device_reset.partial")),
    ).toBeInTheDocument();
    expect(push.isSubscribed()).toBe(false);
    await expect(listDeviceEntries(PID)).resolves.toEqual([]);
    expect(loadPid()).toBeNull();
    expect(screen.queryByText(s("device_reset.done"))).toBeNull();
    fail = false;
    await userEvent.click(button("device_reset.retry"));
    expect(await screen.findByText(s("device_reset.done"))).toBeInTheDocument();
    // 1回目で端末の登録は解除済み。押し直しでも同じ endpoint を送らないとサーバーの行が残る
    expect(callsTo(fetchMock, "POST", UNREGISTER_URL)).toEqual([
      { endpoint: ENDPOINT },
      { endpoint: ENDPOINT },
    ]);
  });

  it("unsubscribe fails: the records and the pid are still deleted", async () => {
    givenPush({
      subscribed: true,
      permission: "granted",
      unsubscribeError: new Error("x"),
    });
    await seedDevice(ENTRIES);
    mockPatientApi();
    renderSettings();
    await resetThroughConfirms();
    expect(
      await screen.findByText(s("device_reset.partial")),
    ).toBeInTheDocument();
    await expect(listDeviceEntries(PID)).resolves.toEqual([]);
    expect(loadPid()).toBeNull();
  });

  it("the records cannot be deleted: the pid is still removed and it says so", async () => {
    mockPatientApi();
    renderSettings();
    await userEvent.click(button("device_reset.button"));
    await userEvent.click(button("device_reset.confirm_first_yes"));
    const indexedDb = globalThis.indexedDB;
    vi.stubGlobal("indexedDB", undefined);
    await userEvent.click(button("device_reset.confirm_second_yes"));
    expect(
      await screen.findByText(s("device_reset.partial")),
    ).toBeInTheDocument();
    expect(loadPid()).toBeNull();
    vi.stubGlobal("indexedDB", indexedDb);
    await userEvent.click(button("device_reset.retry"));
    expect(await screen.findByText(s("device_reset.done"))).toBeInTheDocument();
  });

  it("waits for a re-send in flight, so it cannot bring the server's row back", async () => {
    givenPush({ subscribed: true, permission: "granted" });
    let answerPut: (response: Response) => void = () => undefined;
    const fetchMock = mockPatientApi({
      pushSubscribe: () =>
        new Promise<Response>((resolve) => {
          answerPut = resolve;
        }),
    });
    renderSettings();
    await screen.findByRole("button", { name: s("notify.turn_off") });
    await waitFor(() =>
      expect(
        callsTo(fetchMock, "PUT", `/api/patient/${PID}/push-subscription`),
      ).toHaveLength(1),
    );
    await resetThroughConfirms();
    await screen.findByText(s("device_reset.running"));
    expect(callsTo(fetchMock, "POST", UNREGISTER_URL)).toEqual([]);
    answerPut(jsonResponse({ ok: true, notify_time: "20:00" }));
    expect(await screen.findByText(s("device_reset.done"))).toBeInTheDocument();
    expect(callsTo(fetchMock, "POST", UNREGISTER_URL)).toHaveLength(1);
  });

  it("hides the notification section while deleting and after", async () => {
    givenPush({ subscribed: true, permission: "granted" });
    let answer: (response: Response) => void = () => undefined;
    const fetchMock = mockPatientApi({
      unregister: () =>
        new Promise<Response>((resolve) => {
          answer = resolve;
        }),
    });
    renderSettings();
    await screen.findByRole("button", { name: s("notify.turn_off") });
    await resetThroughConfirms();
    expect(await screen.findByText(s("device_reset.running"))).toBeVisible();
    expect(
      screen.queryByRole("heading", {
        level: 2,
        name: s("notify.section_title"),
      }),
    ).toBeNull();
    await waitFor(() =>
      expect(callsTo(fetchMock, "POST", UNREGISTER_URL)).toHaveLength(1),
    );
    answer(jsonResponse({ ok: true }));
    await screen.findByText(s("device_reset.done"));
    expect(
      screen.queryByRole("heading", {
        level: 2,
        name: s("notify.section_title"),
      }),
    ).toBeNull();
  });
});
