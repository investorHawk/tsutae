/**
 * アプリを開いたとき・戻ったとき・番号を登録したときに、オンの端末の登録をサーバーへ送り直す。
 * DB を作り直した後や別の番号で登録し直した後に、設定を開かなくても通知が届くように。
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import PatientLayout from "../../layouts/PatientLayout";
import { saveNotifyTime } from "../../patient/notifyTime";
import { clearPid, loadPid, savePid } from "../../patient/pid";
import { reloadPage } from "../../patient/reload";
import Register from "../../pages/patient/Register";
import Today from "../../pages/patient/Today";
import { callsTo, mockPatientApi } from "../../pages/patient/testing/api";
import { PID, s } from "../../pages/patient/testing/fixtures";
import {
  ENDPOINT,
  KEYS,
  installFakePush,
  type FakePush,
  type FakePushOptions,
} from "../../pages/patient/testing/pushBrowser";
import { renderPatient } from "../../pages/patient/testing/render";
import { apiFixture } from "../../test/apiFixtures";
import { jsonResponse } from "../../test/fetchMock";
import NotRegistered from "./NotRegistered";

vi.mock("../../patient/reload", () => ({ reloadPage: vi.fn() }));

const SUBSCRIPTION_URL = `/api/patient/${PID}/push-subscription`;
const CONFIG_URL = "/api/patient/push-config";
const ON = { permission: "granted", subscribed: true } as const;

let fake: FakePush | null = null;

function givenPush(options: FakePushOptions = {}): FakePush {
  fake = installFakePush(options);
  return fake;
}

function renderLayout() {
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

/** 非同期の処理を一通り進める。 */
async function settle() {
  await new Promise((resolve) => setTimeout(resolve, 0));
  await new Promise((resolve) => setTimeout(resolve, 0));
}

const replyGone = () => {
  const fixture = apiFixture("patient_push_subscribe_gone");
  return jsonResponse(fixture.body, fixture.status);
};

beforeEach(() => {
  clearPid();
  savePid(PID);
  window.localStorage.removeItem("tsutae.notify_time");
  vi.mocked(reloadPage).mockClear();
});

afterEach(() => {
  fake?.uninstall();
  fake = null;
  delete (document as unknown as Record<string, unknown>).visibilityState;
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("opening the app", () => {
  it("on: sends the subscription once with the saved time (DB rebuilt)", async () => {
    givenPush(ON);
    saveNotifyTime("06:00");
    const fetchMock = mockPatientApi();
    renderLayout();
    await waitFor(() =>
      expect(callsTo(fetchMock, "PUT", SUBSCRIPTION_URL)).toEqual([
        { endpoint: ENDPOINT, keys: KEYS, notify_time: "06:00" },
      ]),
    );
    await settle();
    expect(callsTo(fetchMock, "PUT", SUBSCRIPTION_URL)).toHaveLength(1);
  });

  it("off: sends nothing and touches nothing on the device", async () => {
    const push = givenPush();
    const fetchMock = mockPatientApi();
    renderLayout();
    await waitFor(() =>
      expect(callsTo(fetchMock, "GET", CONFIG_URL)).toHaveLength(1),
    );
    await settle();
    expect(callsTo(fetchMock, "PUT", SUBSCRIPTION_URL)).toEqual([]);
    expect(push.calls).toEqual([]);
  });

  it("unsupported device: not even a request", async () => {
    const fetchMock = mockPatientApi();
    renderLayout();
    await settle();
    expect(callsTo(fetchMock, "GET", CONFIG_URL)).toEqual([]);
  });

  it("no saved pid: not even a request", async () => {
    clearPid();
    givenPush(ON);
    const fetchMock = mockPatientApi();
    renderLayout();
    await settle();
    expect(callsTo(fetchMock, "GET", CONFIG_URL)).toEqual([]);
  });

  it.each([
    ["500", 500, "boom"],
    ["401", 401, "not_registered"],
    ["403", 403, "forbidden"],
  ])("%s: stays subscribed and shows nothing", async (_l, status, error) => {
    const push = givenPush(ON);
    const fetchMock = mockPatientApi({
      pushSubscribe: () => jsonResponse({ error }, status),
    });
    renderLayout();
    await waitFor(() =>
      expect(callsTo(fetchMock, "PUT", SUBSCRIPTION_URL)).toHaveLength(1),
    );
    await settle();
    expect(push.isSubscribed()).toBe(true);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("push-config fails: shows nothing", async () => {
    givenPush(ON);
    const fetchMock = mockPatientApi({
      pushConfig: () => jsonResponse({ error: "boom" }, 500),
    });
    renderLayout();
    await waitFor(() =>
      expect(callsTo(fetchMock, "GET", CONFIG_URL)).toHaveLength(1),
    );
    await settle();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("the service removed it (410): the device lets go, so the screen says off", async () => {
    const push = givenPush(ON);
    mockPatientApi({ pushSubscribe: replyGone });
    renderLayout();
    await waitFor(() => expect(push.isSubscribed()).toBe(false));
    expect(push.calls).toEqual(["unsubscribe"]);
  });
});

describe("coming back to the app", () => {
  it("sends again when coming back, not when leaving (the DB may be new)", async () => {
    givenPush(ON);
    const fetchMock = mockPatientApi();
    const puts = () => callsTo(fetchMock, "PUT", SUBSCRIPTION_URL);
    const view = renderLayout();
    await waitFor(() => expect(puts()).toHaveLength(1));
    setVisibility("hidden");
    await settle();
    expect(puts()).toHaveLength(1);
    setVisibility("visible");
    await waitFor(() => expect(puts()).toHaveLength(2));
    view.unmount();
    setVisibility("visible");
    await settle();
    expect(puts()).toHaveLength(2);
  });
});

describe("the banner on Today", () => {
  it("410 while opening: the banner shows on the same screen", async () => {
    givenPush(ON);
    mockPatientApi({ pushSubscribe: replyGone });
    render(
      <MemoryRouter initialEntries={["/today"]}>
        <Routes>
          <Route element={<PatientLayout />}>
            <Route path="/today" element={<Today />} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );
    expect(
      await screen.findByRole("link", { name: s("notify.banner") }),
    ).toBeInTheDocument();
  });
});

describe("after registering a number", () => {
  it("Register: the subscription moves to the new patient", async () => {
    clearPid();
    givenPush(ON);
    saveNotifyTime("07:30");
    const fetchMock = mockPatientApi();
    renderPatient(
      [
        { path: "/register", element: <Register /> },
        { path: "/today", element: <p>today page</p> },
      ],
      `/register?pid=${PID}`,
    );
    await userEvent.click(
      screen.getByRole("button", { name: s("register.button") }),
    );
    await screen.findByText("today page");
    await waitFor(() =>
      expect(callsTo(fetchMock, "PUT", SUBSCRIPTION_URL)).toEqual([
        { endpoint: ENDPOINT, keys: KEYS, notify_time: "07:30" },
      ]),
    );
    const order = fetchMock.mock.calls.map(([url]) => String(url));
    expect(order.indexOf("/api/patient/register")).toBeLessThan(
      order.indexOf(SUBSCRIPTION_URL),
    );
  });

  it("the number form: the subscription moves to the new patient", async () => {
    clearPid();
    givenPush(ON);
    const fetchMock = mockPatientApi();
    const onRegistered = vi.fn();
    renderPatient(
      [
        {
          path: "/x",
          element: <NotRegistered onRegistered={onRegistered} />,
        },
      ],
      "/x",
    );
    await userEvent.type(
      screen.getByRole("textbox", { name: s("register.number_label") }),
      PID,
    );
    await userEvent.click(
      screen.getByRole("button", { name: s("register.number_submit") }),
    );
    await waitFor(() => expect(onRegistered).toHaveBeenCalledWith(PID));
    expect(loadPid()).toBe(PID);
    await waitFor(() =>
      expect(callsTo(fetchMock, "PUT", SUBSCRIPTION_URL)).toHaveLength(1),
    );
  });

  it("registering fails: nothing is sent", async () => {
    clearPid();
    givenPush(ON);
    const fetchMock = mockPatientApi({
      register: () => jsonResponse({ error: "invalid_pid" }, 422),
    });
    renderPatient([{ path: "/x", element: <NotRegistered /> }], "/x");
    await userEvent.type(
      screen.getByRole("textbox", { name: s("register.number_label") }),
      PID,
    );
    await userEvent.click(
      screen.getByRole("button", { name: s("register.number_submit") }),
    );
    await waitFor(() =>
      expect(callsTo(fetchMock, "POST", "/api/patient/register")).toHaveLength(
        1,
      ),
    );
    await settle();
    expect(callsTo(fetchMock, "PUT", SUBSCRIPTION_URL)).toEqual([]);
  });
});
