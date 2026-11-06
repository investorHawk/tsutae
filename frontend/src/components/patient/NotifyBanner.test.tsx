/** 今日の記録の、お知らせがオフのあいだの案内の帯。使えない端末では何も出さない。 */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearPid, savePid } from "../../patient/pid";
import { apiFixture } from "../../test/apiFixtures";
import { jsonResponse } from "../../test/fetchMock";
import Today from "../../pages/patient/Today";
import { callsTo, mockPatientApi } from "../../pages/patient/testing/api";
import { PID, questionText, s } from "../../pages/patient/testing/fixtures";
import {
  installFakePush,
  type FakePush,
  type FakePushOptions,
} from "../../pages/patient/testing/pushBrowser";
import { renderPatient } from "../../pages/patient/testing/render";

let fake: FakePush | null = null;

function givenPush(options: FakePushOptions = {}) {
  fake = installFakePush(options);
  return fake;
}

const SETTINGS_PAGE = "settings page";

function renderToday() {
  return renderPatient(
    [
      { path: "/today", element: <Today /> },
      { path: "/settings", element: <p>{SETTINGS_PAGE}</p> },
    ],
    "/today",
  );
}

function queryBanner() {
  return screen.queryByRole("link", { name: s("notify.banner") });
}

/** 質問集と通知の状態を読み終えるまで待つ。 */
async function settled(fetchMock: ReturnType<typeof mockPatientApi>) {
  await screen.findByRole("button", { name: s("today.too_sick_button") });
  await screen.findByRole("group", { name: questionText("diarrhea") });
  await waitFor(() => expect(fetchMock).toHaveBeenCalled());
  // 帯の読み込みは非同期なので、応答が画面に届くまで一度待つ
  await new Promise((resolve) => setTimeout(resolve, 0));
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

describe("NotifyBanner on Today", () => {
  it("off: one banner that goes to /settings", async () => {
    givenPush();
    mockPatientApi();
    renderToday();
    const banner = await screen.findByRole("link", {
      name: s("notify.banner"),
    });
    expect(banner).toHaveAttribute("href", "/settings");
    expect(
      screen.getAllByRole("link", { name: s("notify.banner") }),
    ).toHaveLength(1);
    await userEvent.click(banner);
    expect(screen.getByText(SETTINGS_PAGE)).toBeInTheDocument();
  });

  it("opening Today never asks, registers or subscribes", async () => {
    const push = givenPush();
    mockPatientApi();
    renderToday();
    await screen.findByRole("link", { name: s("notify.banner") });
    expect(push.calls).toEqual([]);
  });

  it("the banner sits after the form (it does not push the too-sick button)", async () => {
    givenPush();
    mockPatientApi();
    renderToday();
    const banner = await screen.findByRole("link", {
      name: s("notify.banner"),
    });
    const submit = screen.getByRole("button", { name: s("today.submit") });
    expect(
      submit.compareDocumentPosition(banner) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("on: no banner", async () => {
    givenPush({ permission: "granted", subscribed: true });
    const fetchMock = mockPatientApi();
    renderToday();
    await settled(fetchMock);
    expect(queryBanner()).not.toBeInTheDocument();
  });

  it("denied: no banner", async () => {
    givenPush({ permission: "denied" });
    const fetchMock = mockPatientApi();
    renderToday();
    await settled(fetchMock);
    expect(queryBanner()).not.toBeInTheDocument();
  });

  it("no key: no banner", async () => {
    givenPush();
    const fetchMock = mockPatientApi({
      pushConfig: () =>
        jsonResponse(apiFixture("patient_push_config_unavailable").body),
    });
    renderToday();
    await settled(fetchMock);
    expect(queryBanner()).not.toBeInTheDocument();
  });

  it("push-config fails: no banner and no error on the record screen", async () => {
    givenPush();
    const fetchMock = mockPatientApi({
      pushConfig: () => jsonResponse({ error: "boom" }, 500),
    });
    renderToday();
    await settled(fetchMock);
    expect(queryBanner()).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("unsupported device: no banner and not even a request", async () => {
    const fetchMock = mockPatientApi();
    renderToday();
    await settled(fetchMock);
    expect(queryBanner()).not.toBeInTheDocument();
    expect(callsTo(fetchMock, "GET", "/api/patient/push-config")).toEqual([]);
  });

  it("no saved pid: no banner", () => {
    clearPid();
    givenPush();
    const fetchMock = mockPatientApi();
    renderToday();
    expect(queryBanner()).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("not registered on the server: no banner under the number form", async () => {
    givenPush();
    const fetchMock = mockPatientApi({
      questions: () => jsonResponse({ error: "forbidden" }, 403),
    });
    renderToday();
    await screen.findByText(s("error.not_registered"));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(queryBanner()).not.toBeInTheDocument();
    expect(callsTo(fetchMock, "GET", "/api/patient/push-config")).toEqual([]);
  });
});
