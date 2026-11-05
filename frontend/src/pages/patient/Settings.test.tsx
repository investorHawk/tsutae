/** P5 設定（/settings）。期待する文は patient_strings.json のキーから引く。 */
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { loadNotifyTime, saveNotifyTime } from "../../patient/notifyTime";
import { clearPid, savePid } from "../../patient/pid";
import { apiFixture } from "../../test/apiFixtures";
import { jsonResponse, type FetchMock } from "../../test/fetchMock";
import { callsTo, mockPatientApi } from "./testing/api";
import { PID, s } from "./testing/fixtures";
import {
  ENDPOINT,
  KEYS,
  installFakePush,
  type FakePush,
  type FakePushOptions,
} from "./testing/pushBrowser";
import { renderPatient } from "./testing/render";
import Settings from "./Settings";

const SUBSCRIPTION_URL = `/api/patient/${PID}/push-subscription`;
const TEST_URL = `/api/patient/${PID}/push-test`;

let fake: FakePush | null = null;

function givenPush(options: FakePushOptions = {}): FakePush {
  fake = installFakePush(options);
  return fake;
}

function renderSettings() {
  return renderPatient(
    [{ path: "/settings", element: <Settings /> }],
    "/settings",
  );
}

function button(key: string) {
  return screen.getByRole("button", { name: s(key) });
}

function timeSelect() {
  return screen.getByRole("combobox", { name: s("notify.time_label") });
}

async function findOffScreen() {
  return screen.findByRole("button", { name: s("notify.turn_on") });
}

async function findOnScreen() {
  return screen.findByRole("button", { name: s("notify.turn_off") });
}

function putCalls(mock: FetchMock) {
  return callsTo(mock, "PUT", SUBSCRIPTION_URL);
}

beforeEach(() => {
  clearPid();
  savePid(PID);
  window.localStorage.removeItem("tsutae.notify_time");
});

afterEach(() => {
  fake?.uninstall();
  fake = null;
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("Settings: screen", () => {
  it("has the title, the section and the tab of this screen", async () => {
    givenPush();
    mockPatientApi();
    renderSettings();
    expect(
      screen.getByRole("heading", { level: 1, name: s("settings.title") }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        level: 2,
        name: s("notify.section_title"),
      }),
    ).toBeInTheDocument();
    expect(screen.getByText(s("notify.about"))).toBeInTheDocument();
    const nav = screen.getByRole("navigation");
    expect(
      within(nav).getByRole("link", { name: s("nav.settings") }),
    ).toHaveAttribute("aria-current", "page");
    await findOffScreen();
  });

  it("without a saved pid: the number form and no request", () => {
    clearPid();
    givenPush();
    const fetchMock = mockPatientApi();
    renderSettings();
    expect(screen.getByText(s("error.not_registered"))).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: s("notify.turn_on") }),
    ).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("Settings: states that cannot use notifications", () => {
  it("unsupported: the reason and the next step, and no request", () => {
    const fetchMock = mockPatientApi();
    renderSettings();
    expect(screen.getByText(s("notify.unsupported"))).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: s("notify.turn_on") }),
    ).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("no key on the server: the reason and no buttons", async () => {
    const push = givenPush();
    mockPatientApi({
      pushConfig: () =>
        jsonResponse(apiFixture("patient_push_config_unavailable").body),
    });
    renderSettings();
    expect(await screen.findByText(s("notify.no_key"))).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: s("notify.turn_on") }),
    ).not.toBeInTheDocument();
    expect(push.requestPermission).not.toHaveBeenCalled();
  });

  it("denied: the device settings guide, and no way to ask again", async () => {
    const push = givenPush({ permission: "denied" });
    mockPatientApi();
    renderSettings();
    expect(await screen.findByText(s("notify.denied"))).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: s("notify.turn_on") }),
    ).not.toBeInTheDocument();
    expect(push.requestPermission).not.toHaveBeenCalled();
  });

  it("denied, then allowed in the device settings: back to off when reopened", async () => {
    const push = givenPush({ permission: "denied" });
    mockPatientApi();
    renderSettings();
    await screen.findByText(s("notify.denied"));
    push.setPermission("default");
    fireEvent(document, new Event("visibilitychange"));
    await findOffScreen();
    expect(screen.queryByText(s("notify.denied"))).not.toBeInTheDocument();
  });

  it("push-config fails: load_failed, and reload reads it again", async () => {
    givenPush();
    let fail = true;
    mockPatientApi({
      pushConfig: () =>
        fail
          ? jsonResponse({ error: "boom" }, 500)
          : jsonResponse(apiFixture("patient_push_config").body),
    });
    renderSettings();
    expect(
      await screen.findByText(s("common.load_failed")),
    ).toBeInTheDocument();
    fail = false;
    await userEvent.click(button("common.reload"));
    await findOffScreen();
  });
});

describe("Settings: off", () => {
  it("opening never asks, registers or subscribes", async () => {
    const push = givenPush();
    const fetchMock = mockPatientApi();
    renderSettings();
    await findOffScreen();
    expect(screen.getByText(s("notify.status_off"))).toBeInTheDocument();
    expect(push.calls).toEqual([]);
    expect(putCalls(fetchMock)).toEqual([]);
    expect(
      screen.queryByRole("button", { name: s("notify.test") }),
    ).not.toBeInTheDocument();
  });

  it("the time defaults to 20:00 and has 48 choices", async () => {
    givenPush();
    mockPatientApi();
    renderSettings();
    await findOffScreen();
    expect(timeSelect()).toHaveValue("20:00");
    expect(within(timeSelect()).getAllByRole("option")).toHaveLength(48);
  });

  it("asks for permission inside the click, before anything is awaited", async () => {
    const push = givenPush();
    mockPatientApi();
    renderSettings();
    const on = await findOffScreen();
    fireEvent.click(on);
    // await を挟まずに呼ばれている（iPhone は押した直後でないと許可を求められない）
    expect(push.requestPermission).toHaveBeenCalledTimes(1);
    await findOnScreen();
  });

  it("turning on: permission, register, subscribe, then PUT", async () => {
    const push = givenPush();
    const order = push.calls;
    const fetchMock = mockPatientApi({
      pushSubscribe: (body) => {
        order.push("PUT");
        return jsonResponse({
          ok: true,
          notify_time: (body as { notify_time: string }).notify_time,
        });
      },
    });
    renderSettings();
    await userEvent.click(await findOffScreen());
    await findOnScreen();
    expect(order).toEqual([
      "requestPermission",
      "register",
      "subscribe",
      "PUT",
    ]);
    expect(push.register).toHaveBeenCalledWith("/sw.js");
    expect(putCalls(fetchMock)).toEqual([
      { endpoint: ENDPOINT, keys: KEYS, notify_time: "20:00" },
    ]);
    expect(screen.getByText(s("notify.status_on"))).toBeInTheDocument();
    expect(button("notify.test")).toBeInTheDocument();
  });

  it("a time chosen while off stays on the device (leaving and coming back)", async () => {
    givenPush();
    mockPatientApi();
    const first = renderSettings();
    await findOffScreen();
    await userEvent.selectOptions(timeSelect(), "07:30");
    expect(loadNotifyTime()).toBe("07:30");
    first.unmount();
    renderSettings();
    await findOffScreen();
    expect(timeSelect()).toHaveValue("07:30");
  });

  it("the chosen time goes with the PUT and is kept on the device", async () => {
    givenPush();
    const fetchMock = mockPatientApi();
    renderSettings();
    await findOffScreen();
    await userEvent.selectOptions(timeSelect(), "07:30");
    expect(putCalls(fetchMock)).toEqual([]);
    await userEvent.click(button("notify.turn_on"));
    await findOnScreen();
    expect(putCalls(fetchMock)).toEqual([
      { endpoint: ENDPOINT, keys: KEYS, notify_time: "07:30" },
    ]);
    expect(loadNotifyTime()).toBe("07:30");
  });

  it("permission refused: the device settings guide and no subscribe", async () => {
    const push = givenPush({ answer: "denied" });
    const fetchMock = mockPatientApi();
    renderSettings();
    await userEvent.click(await findOffScreen());
    expect(await screen.findByText(s("notify.denied"))).toBeInTheDocument();
    expect(push.register).not.toHaveBeenCalled();
    expect(push.subscribe).not.toHaveBeenCalled();
    expect(putCalls(fetchMock)).toEqual([]);
  });

  it("permission dismissed: can press again", async () => {
    const push = givenPush({ answer: "default" });
    mockPatientApi();
    renderSettings();
    await userEvent.click(await findOffScreen());
    expect(
      await screen.findByText(s("notify.not_allowed")),
    ).toBeInTheDocument();
    expect(push.subscribe).not.toHaveBeenCalled();
    expect(button("notify.turn_on")).toBeEnabled();
  });

  it("subscribe fails: stays off with enable_failed", async () => {
    givenPush({ subscribeError: new Error("push service is down") });
    const fetchMock = mockPatientApi();
    renderSettings();
    await userEvent.click(await findOffScreen());
    expect(
      await screen.findByText(s("notify.enable_failed")),
    ).toBeInTheDocument();
    expect(putCalls(fetchMock)).toEqual([]);
    expect(button("notify.turn_on")).toBeEnabled();
  });

  it("PUT fails: undoes the subscribe (not on only in the browser)", async () => {
    const push = givenPush();
    mockPatientApi({
      pushSubscribe: () => jsonResponse({ error: "boom" }, 500),
    });
    renderSettings();
    await userEvent.click(await findOffScreen());
    expect(
      await screen.findByText(s("notify.enable_failed")),
    ).toBeInTheDocument();
    expect(push.isSubscribed()).toBe(false);
    expect(button("notify.turn_on")).toBeEnabled();
  });

  it("PUT says not registered: undoes the subscribe and shows the number form", async () => {
    const push = givenPush();
    mockPatientApi({
      pushSubscribe: () => jsonResponse({ error: "not_registered" }, 401),
    });
    renderSettings();
    await userEvent.click(await findOffScreen());
    expect(
      await screen.findByText(s("error.not_registered")),
    ).toBeInTheDocument();
    expect(push.isSubscribed()).toBe(false);
  });
});

describe("Settings: on", () => {
  it("opening re-sends the subscription with the saved time (DB rebuilt)", async () => {
    givenPush({ permission: "granted", subscribed: true });
    saveNotifyTime("06:00");
    const fetchMock = mockPatientApi();
    renderSettings();
    await findOnScreen();
    expect(screen.getByText(s("notify.status_on"))).toBeInTheDocument();
    expect(timeSelect()).toHaveValue("06:00");
    await waitFor(() =>
      expect(putCalls(fetchMock)).toEqual([
        { endpoint: ENDPOINT, keys: KEYS, notify_time: "06:00" },
      ]),
    );
  });

  it("re-send fails: stays on without an error (tried again next time)", async () => {
    givenPush({ permission: "granted", subscribed: true });
    const fetchMock = mockPatientApi({
      pushSubscribe: () => jsonResponse({ error: "boom" }, 500),
    });
    renderSettings();
    await findOnScreen();
    await waitFor(() => expect(putCalls(fetchMock)).toHaveLength(1));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("re-send says not registered: shows the number form", async () => {
    givenPush({ permission: "granted", subscribed: true });
    mockPatientApi({
      pushSubscribe: () => jsonResponse({ error: "forbidden" }, 403),
    });
    renderSettings();
    expect(
      await screen.findByText(s("error.not_registered")),
    ).toBeInTheDocument();
  });

  it("turning off: unsubscribe, then DELETE with the endpoint", async () => {
    const push = givenPush({ permission: "granted", subscribed: true });
    const order = push.calls;
    const fetchMock = mockPatientApi({
      pushUnsubscribe: () => {
        order.push("DELETE");
        return jsonResponse({ ok: true });
      },
    });
    renderSettings();
    await userEvent.click(await findOnScreen());
    await findOffScreen();
    expect(order).toEqual(["unsubscribe", "DELETE"]);
    expect(callsTo(fetchMock, "DELETE", SUBSCRIPTION_URL)).toEqual([
      { endpoint: ENDPOINT },
    ]);
    expect(screen.getByText(s("notify.status_off"))).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: s("notify.test") }),
    ).not.toBeInTheDocument();
  });

  it("DELETE fails: off anyway (the device no longer receives)", async () => {
    givenPush({ permission: "granted", subscribed: true });
    mockPatientApi({
      pushUnsubscribe: () => jsonResponse({ error: "boom" }, 500),
    });
    renderSettings();
    await userEvent.click(await findOnScreen());
    await findOffScreen();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("unsubscribe fails: stays on with the error, no DELETE", async () => {
    givenPush({
      permission: "granted",
      subscribed: true,
      unsubscribeError: new Error("failed"),
    });
    const fetchMock = mockPatientApi();
    renderSettings();
    await userEvent.click(await findOnScreen());
    expect(await screen.findByText(s("error.generic"))).toBeInTheDocument();
    expect(button("notify.turn_off")).toBeEnabled();
    expect(callsTo(fetchMock, "DELETE", SUBSCRIPTION_URL)).toEqual([]);
  });

  it("unsubscribe returns false: stays on with the error, no DELETE", async () => {
    const push = givenPush({
      permission: "granted",
      subscribed: true,
      unsubscribeReturnsFalse: true,
    });
    const fetchMock = mockPatientApi();
    renderSettings();
    await userEvent.click(await findOnScreen());
    expect(await screen.findByText(s("error.generic"))).toBeInTheDocument();
    expect(button("notify.turn_off")).toBeEnabled();
    expect(screen.getByText(s("notify.status_on"))).toBeInTheDocument();
    expect(callsTo(fetchMock, "DELETE", SUBSCRIPTION_URL)).toEqual([]);
    expect(push.isSubscribed()).toBe(true);
  });

  it("already let go on the device: turning off still ends off, without an error", async () => {
    const push = givenPush({ permission: "granted", subscribed: true });
    const fetchMock = mockPatientApi();
    renderSettings();
    const off = await findOnScreen();
    const registration = await navigator.serviceWorker.getRegistration();
    const current = await registration?.pushManager.getSubscription();
    await current?.unsubscribe();
    await userEvent.click(off);
    await findOffScreen();
    expect(screen.queryByText(s("error.generic"))).toBeNull();
    expect(screen.getByText(s("notify.status_off"))).toBeInTheDocument();
    expect(callsTo(fetchMock, "DELETE", SUBSCRIPTION_URL)).toEqual([
      { endpoint: ENDPOINT },
    ]);
    expect(push.isSubscribed()).toBe(false);
  });

  it("changing the time sends PUT and is kept on the device", async () => {
    givenPush({ permission: "granted", subscribed: true });
    const fetchMock = mockPatientApi();
    renderSettings();
    await findOnScreen();
    await userEvent.selectOptions(timeSelect(), "21:30");
    expect(await screen.findByText(s("notify.time_saved"))).toBeInTheDocument();
    expect(putCalls(fetchMock).slice(-1)[0]).toEqual({
      endpoint: ENDPOINT,
      keys: KEYS,
      notify_time: "21:30",
    });
    expect(loadNotifyTime()).toBe("21:30");
  });

  it("changing the time fails: back to the previous time with the error", async () => {
    givenPush({ permission: "granted", subscribed: true });
    saveNotifyTime("06:00");
    let fail = false;
    mockPatientApi({
      pushSubscribe: (body) =>
        fail
          ? jsonResponse({ error: "boom" }, 500)
          : jsonResponse({
              ok: true,
              notify_time: (body as { notify_time: string }).notify_time,
            }),
    });
    renderSettings();
    await findOnScreen();
    fail = true;
    await userEvent.selectOptions(timeSelect(), "21:30");
    expect(await screen.findByText(s("error.generic"))).toBeInTheDocument();
    expect(timeSelect()).toHaveValue("06:00");
    expect(loadNotifyTime()).toBe("06:00");
  });
});

describe("Settings: the service removed the subscription (410)", () => {
  const gone = () => {
    const fixture = apiFixture("patient_push_subscribe_gone");
    return jsonResponse(fixture.body, fixture.status);
  };

  // 外枠の下で開く場合は外枠の送り直しが先に 410 を受ける（pushResend.test.tsx）。
  // ここは設定の画面自身の PUT が 410 を受けたとき
  it("the screen's own re-send: lets go on the device, says off and what to do", async () => {
    const push = givenPush({ permission: "granted", subscribed: true });
    mockPatientApi({ pushSubscribe: gone });
    renderSettings();
    expect(await screen.findByText(s("notify.expired"))).toBeInTheDocument();
    await findOffScreen();
    expect(screen.getByText(s("notify.status_off"))).toBeInTheDocument();
    await waitFor(() => expect(push.isSubscribed()).toBe(false));
    expect(
      screen.queryByRole("button", { name: s("notify.test") }),
    ).not.toBeInTheDocument();
  });

  it("then turning on again gets a new subscription", async () => {
    const push = givenPush({ permission: "granted", subscribed: true });
    let isGone = true;
    mockPatientApi({
      pushSubscribe: (body) =>
        isGone
          ? gone()
          : jsonResponse({
              ok: true,
              notify_time: (body as { notify_time: string }).notify_time,
            }),
    });
    renderSettings();
    const on = await findOffScreen();
    isGone = false;
    await userEvent.click(on);
    await findOnScreen();
    expect(push.subscribe).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(s("notify.expired"))).not.toBeInTheDocument();
  });

  it("test notification: 404, then the retry says gone", async () => {
    const push = givenPush({ permission: "granted", subscribed: true });
    let isGone = false;
    const fetchMock = mockPatientApi({
      pushSubscribe: (body) =>
        isGone
          ? gone()
          : jsonResponse({
              ok: true,
              notify_time: (body as { notify_time: string }).notify_time,
            }),
      pushTest: () => {
        const fixture = apiFixture("patient_push_test_not_found");
        return jsonResponse(fixture.body, fixture.status);
      },
    });
    renderSettings();
    await findOnScreen();
    await waitFor(() => expect(putCalls(fetchMock)).toHaveLength(1));
    isGone = true;
    await userEvent.click(button("notify.test"));
    expect(await screen.findByText(s("notify.expired"))).toBeInTheDocument();
    await findOffScreen();
    expect(push.isSubscribed()).toBe(false);
    expect(screen.queryByText(s("notify.test_sent"))).not.toBeInTheDocument();
  });

  it("changing the time: says off and keeps the chosen time on the device", async () => {
    const push = givenPush({ permission: "granted", subscribed: true });
    saveNotifyTime("06:00");
    let isGone = false;
    const fetchMock = mockPatientApi({
      pushSubscribe: (body) =>
        isGone
          ? gone()
          : jsonResponse({
              ok: true,
              notify_time: (body as { notify_time: string }).notify_time,
            }),
    });
    renderSettings();
    await findOnScreen();
    await waitFor(() => expect(putCalls(fetchMock)).toHaveLength(1));
    isGone = true;
    await userEvent.selectOptions(timeSelect(), "21:30");
    expect(await screen.findByText(s("notify.expired"))).toBeInTheDocument();
    await findOffScreen();
    expect(push.isSubscribed()).toBe(false);
    expect(timeSelect()).toHaveValue("21:30");
    expect(loadNotifyTime()).toBe("21:30");
  });
});

describe("Settings: test notification", () => {
  function replyOf(name: string) {
    const fixture = apiFixture(name);
    return () => jsonResponse(fixture.body, fixture.status);
  }

  it("sends the endpoint and says to wait with the screen closed", async () => {
    givenPush({ permission: "granted", subscribed: true });
    const fetchMock = mockPatientApi();
    renderSettings();
    await findOnScreen();
    await userEvent.click(button("notify.test"));
    expect(await screen.findByText(s("notify.test_sent"))).toBeInTheDocument();
    expect(callsTo(fetchMock, "POST", TEST_URL)).toEqual([
      { endpoint: ENDPOINT },
    ]);
  });

  it("429: says to wait a minute", async () => {
    givenPush({ permission: "granted", subscribed: true });
    mockPatientApi({ pushTest: replyOf("patient_push_test_too_soon") });
    renderSettings();
    await findOnScreen();
    await userEvent.click(button("notify.test"));
    expect(
      await screen.findByText(s("notify.test_too_soon")),
    ).toBeInTheDocument();
  });

  it("404 (the server lost the row): registers again and retries once", async () => {
    givenPush({ permission: "granted", subscribed: true });
    let first = true;
    const fetchMock = mockPatientApi({
      pushTest: () => {
        if (first) {
          first = false;
          return replyOf("patient_push_test_not_found")();
        }
        return jsonResponse({ ok: true });
      },
    });
    renderSettings();
    await findOnScreen();
    await waitFor(() => expect(putCalls(fetchMock)).toHaveLength(1));
    await userEvent.click(button("notify.test"));
    expect(await screen.findByText(s("notify.test_sent"))).toBeInTheDocument();
    expect(putCalls(fetchMock)).toHaveLength(2);
    expect(callsTo(fetchMock, "POST", TEST_URL)).toHaveLength(2);
  });

  it("other failures: the generic error", async () => {
    givenPush({ permission: "granted", subscribed: true });
    mockPatientApi({ pushTest: () => jsonResponse({ error: "boom" }, 500) });
    renderSettings();
    await findOnScreen();
    await userEvent.click(button("notify.test"));
    expect(await screen.findByText(s("error.generic"))).toBeInTheDocument();
  });

  it("the next action clears the previous message", async () => {
    givenPush({ permission: "granted", subscribed: true });
    mockPatientApi();
    renderSettings();
    await findOnScreen();
    await userEvent.click(button("notify.test"));
    await screen.findByText(s("notify.test_sent"));
    await userEvent.selectOptions(timeSelect(), "21:30");
    await screen.findByText(s("notify.time_saved"));
    expect(screen.queryByText(s("notify.test_sent"))).not.toBeInTheDocument();
  });
});
