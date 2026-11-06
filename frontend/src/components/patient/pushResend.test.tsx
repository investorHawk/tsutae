/**
 * アプリを開いたとき・戻ったとき・番号を登録したときに、オンの端末の登録をサーバーへ送り直す。
 * DB を作り直した後や別の番号で登録し直した後に、設定を開かなくても通知が届くように。
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Link, MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import PatientLayout from "../../layouts/PatientLayout";
import { saveNotifyTime } from "../../patient/notifyTime";
import { clearPid, loadPid, savePid } from "../../patient/pid";
import { reloadPage } from "../../patient/reload";
import Register from "../../pages/patient/Register";
import Today from "../../pages/patient/Today";
import { callsTo, mockPatientApi } from "../../pages/patient/testing/api";
import { PID, questionText, s } from "../../pages/patient/testing/fixtures";
import {
  ENDPOINT,
  KEYS,
  installFakePush,
  type FakePush,
  type FakePushOptions,
} from "../../pages/patient/testing/pushBrowser";
import { renderPatient } from "../../pages/patient/testing/render";
import Settings from "../../pages/patient/Settings";
import { apiFixture } from "../../test/apiFixtures";
import { jsonResponse } from "../../test/fetchMock";
import NotRegistered from "./NotRegistered";
import { onSubscriptionDropped, resendSubscription } from "./pushResend";

vi.mock("../../patient/reload", () => ({ reloadPage: vi.fn() }));

const SUBSCRIPTION_URL = `/api/patient/${PID}/push-subscription`;
const CONFIG_URL = "/api/patient/push-config";
const ON = { permission: "granted", subscribed: true } as const;
const OTHER_PID = "P-DEMO0002";
const OTHER_SUBSCRIPTION_URL = `/api/patient/${OTHER_PID}/push-subscription`;

let fake: FakePush | null = null;
// 止めた応答を開けたままテストを終えない（送り直しの順番はテストをまたいで続く）
let releaseHeld: () => void = () => undefined;

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

const replySaved = () => jsonResponse({ ok: true, notify_time: "20:00" });

/** PUT の応答を止める。open を呼ぶと reply の応答が返る。 */
function holdPut(reply: () => Response) {
  let open: () => void = () => undefined;
  const promise = new Promise<Response>((resolve) => {
    open = () => resolve(reply());
  });
  releaseHeld = open;
  return { reply: () => promise, open };
}

/** 外枠の下に1つの画面を置く。 */
function renderInLayout(path: string, initial: string, element: JSX.Element) {
  return render(
    <MemoryRouter initialEntries={[initial]}>
      <Routes>
        <Route element={<PatientLayout />}>
          <Route path={path} element={element} />
          <Route path="/today" element={<p>today page</p>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  clearPid();
  savePid(PID);
  window.localStorage.removeItem("tsutae.notify_time");
  vi.mocked(reloadPage).mockClear();
});

afterEach(async () => {
  releaseHeld();
  releaseHeld = () => undefined;
  await settle();
  // 聞き手のいない間の解除の知らせを、次のテストへ持ち越さない
  onSubscriptionDropped(() => undefined)();
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

describe("the banner waits for the resend", () => {
  it("while the PUT is slow it does not read the state, then shows", async () => {
    givenPush(ON);
    const held = holdPut(replyGone);
    const fetchMock = mockPatientApi({ pushSubscribe: held.reply });
    renderInLayout("/today", "/today", <Today />);
    await waitFor(() =>
      expect(callsTo(fetchMock, "PUT", SUBSCRIPTION_URL)).toHaveLength(1),
    );
    await screen.findByRole("group", { name: questionText("fever") });
    await settle();
    // 送り直し自身の1回だけ（帯は PUT の結果を待つ）
    expect(callsTo(fetchMock, "GET", CONFIG_URL)).toHaveLength(1);
    expect(screen.queryByRole("link", { name: s("notify.banner") })).toBeNull();
    held.open();
    expect(
      await screen.findByRole("link", { name: s("notify.banner") }),
    ).toBeInTheDocument();
    expect(callsTo(fetchMock, "GET", CONFIG_URL)).toHaveLength(2);
  });
});

describe("the settings screen stays open while the layout resends", () => {
  it("410 on coming back: the screen says off and what to do", async () => {
    const push = givenPush(ON);
    let isGone = false;
    mockPatientApi({
      pushSubscribe: () => (isGone ? replyGone() : replySaved()),
    });
    renderInLayout("/settings", "/settings", <Settings />);
    await screen.findByRole("button", { name: s("notify.turn_off") });
    await settle();
    isGone = true;
    setVisibility("hidden");
    setVisibility("visible");
    await waitFor(() => expect(push.isSubscribed()).toBe(false));
    expect(await screen.findByText(s("notify.expired"))).toBeInTheDocument();
    expect(screen.getByText(s("notify.status_off"))).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: s("notify.turn_on") }),
    ).toBeEnabled();
    expect(screen.queryByText(s("notify.status_on"))).toBeNull();
  });

  it("a fine resend leaves the screen on", async () => {
    givenPush(ON);
    mockPatientApi({ pushSubscribe: replySaved });
    renderInLayout("/settings", "/settings", <Settings />);
    await screen.findByRole("button", { name: s("notify.turn_off") });
    setVisibility("visible");
    await settle();
    expect(screen.getByText(s("notify.status_on"))).toBeInTheDocument();
    expect(screen.queryByText(s("notify.expired"))).toBeNull();
  });

  it("a screen that stopped listening is not told", async () => {
    const push = givenPush(ON);
    mockPatientApi({ pushSubscribe: replyGone });
    const told = vi.fn();
    const stop = onSubscriptionDropped(told);
    stop();
    await resendSubscription();
    expect(push.isSubscribed()).toBe(false);
    expect(told).not.toHaveBeenCalled();
  });

  it("a listening screen is told which subscription went", async () => {
    givenPush(ON);
    mockPatientApi({ pushSubscribe: replyGone });
    const told = vi.fn();
    const stop = onSubscriptionDropped(told);
    await resendSubscription();
    stop();
    expect(told).toHaveBeenCalledWith(ENDPOINT);
  });
});

describe("the resend finds it gone before the settings screen is there", () => {
  it("410 on opening /settings: the screen says off and what to do", async () => {
    const push = givenPush(ON);
    const fetchMock = mockPatientApi({ pushSubscribe: replyGone });
    renderInLayout("/settings", "/settings", <Settings />);
    expect(await screen.findByText(s("notify.expired"))).toBeInTheDocument();
    expect(screen.getByText(s("notify.status_off"))).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: s("notify.turn_on") }),
    ).toBeEnabled();
    expect(push.isSubscribed()).toBe(false);
    // オフと読めたので、設定の画面からはもう送らない（外枠の1本だけ）
    expect(callsTo(fetchMock, "PUT", SUBSCRIPTION_URL)).toHaveLength(1);
  });

  it("gone on another tab: said when the settings tab is opened, and only once", async () => {
    const push = givenPush(ON);
    mockPatientApi({ pushSubscribe: replyGone });
    render(
      <MemoryRouter initialEntries={["/history"]}>
        <Routes>
          <Route element={<PatientLayout />}>
            <Route path="/history" element={<Link to="/settings">go</Link>} />
            <Route path="/settings" element={<Settings />} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );
    const go = await screen.findByRole("link", { name: "go" });
    await waitFor(() => expect(push.isSubscribed()).toBe(false));
    await settle();
    await userEvent.click(go);
    expect(await screen.findByText(s("notify.expired"))).toBeInTheDocument();
    expect(screen.getByText(s("notify.status_off"))).toBeInTheDocument();
  });

  it("does not say it again when the screen is opened the next time", async () => {
    const push = givenPush(ON);
    mockPatientApi({ pushSubscribe: replyGone });
    const first = renderInLayout("/settings", "/settings", <Settings />);
    await screen.findByText(s("notify.expired"));
    first.unmount();
    expect(push.isSubscribed()).toBe(false);
    renderInLayout("/settings", "/settings", <Settings />);
    await screen.findByRole("button", { name: s("notify.turn_on") });
    expect(screen.queryByText(s("notify.expired"))).toBeNull();
  });

  it("the next listener is told once, the one after is not", async () => {
    givenPush(ON);
    mockPatientApi({ pushSubscribe: replyGone });
    await resendSubscription();
    const first = vi.fn();
    onSubscriptionDropped(first)();
    expect(first).toHaveBeenCalledTimes(1);
    expect(first).toHaveBeenCalledWith(ENDPOINT);
    const second = vi.fn();
    onSubscriptionDropped(second)();
    expect(second).not.toHaveBeenCalled();
  });
});

describe("after registering a number", () => {
  it("the new number's PUT waits for the previous number's PUT", async () => {
    givenPush(ON);
    const held = holdPut(replySaved);
    const fetchMock = mockPatientApi({ pushSubscribe: held.reply });
    renderInLayout("/register", `/register?pid=${OTHER_PID}`, <Register />);
    await waitFor(() =>
      expect(callsTo(fetchMock, "PUT", SUBSCRIPTION_URL)).toHaveLength(1),
    );
    await userEvent.click(
      await screen.findByRole("button", { name: s("register.button") }),
    );
    await screen.findByText("today page");
    await settle();
    expect(loadPid()).toBe(OTHER_PID);
    // 前の番号の応答を待つ間は、新しい番号の分を出さない（前の分が後から届かないように）
    expect(callsTo(fetchMock, "PUT", OTHER_SUBSCRIPTION_URL)).toEqual([]);
    held.open();
    await waitFor(() =>
      expect(callsTo(fetchMock, "PUT", OTHER_SUBSCRIPTION_URL)).toHaveLength(1),
    );
    expect(callsTo(fetchMock, "PUT", SUBSCRIPTION_URL)).toHaveLength(1);
  });

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
