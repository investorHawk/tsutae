/**
 * 時刻の変更と送り直しが重なっても、サーバーへ最後に届く時刻・端末の控え・画面の時刻を揃える。
 * PUT は1本ずつ順に送り、送り直しは順番が来たときの端末の時刻を送る。
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Link, MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import PatientLayout from "../../layouts/PatientLayout";
import { loadNotifyTime, saveNotifyTime } from "../../patient/notifyTime";
import { clearPid, savePid } from "../../patient/pid";
import { mockPatientApi } from "../../pages/patient/testing/api";
import { PID, s } from "../../pages/patient/testing/fixtures";
import {
  installFakePush,
  type FakePush,
} from "../../pages/patient/testing/pushBrowser";
import Settings from "../../pages/patient/Settings";
import { jsonResponse } from "../../test/fetchMock";

const ON = { permission: "granted", subscribed: true } as const;
const LEAVE = "leave";
const BACK = "back";

let fake: FakePush | null = null;

/** 非同期の処理を一通り進める。 */
async function settle() {
  await new Promise((resolve) => setTimeout(resolve, 0));
  await new Promise((resolve) => setTimeout(resolve, 0));
}

function setVisibility(state: DocumentVisibilityState) {
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => state,
  });
  fireEvent(document, new Event("visibilitychange"));
}

interface HeldPut {
  answer: () => void;
  fail: () => void;
}

/** PUT の応答を1本ずつ手で返す。sent はサーバーへ届いた順の時刻。 */
function holdPuts() {
  const sent: string[] = [];
  const waiting: HeldPut[] = [];
  const reply = (body: unknown) =>
    new Promise<Response>((resolve) => {
      const notify_time = (body as { notify_time: string }).notify_time;
      sent.push(notify_time);
      waiting.push({
        answer: () => resolve(jsonResponse({ ok: true, notify_time })),
        fail: () => resolve(jsonResponse({ error: "boom" }, 500)),
      });
    });
  /** 止まっている PUT を順に返す（返した後に出てくる分も）。 */
  async function drain() {
    await settle();
    while (waiting.length > 0) {
      waiting.shift()?.answer();
      await settle();
    }
  }
  return { sent, waiting, reply, drain };
}

let puts = holdPuts();

function renderInLayout() {
  return render(
    <MemoryRouter initialEntries={["/settings"]}>
      <Routes>
        <Route element={<PatientLayout />}>
          <Route
            path="/settings"
            element={
              <>
                <Link to="/other">{LEAVE}</Link>
                <Settings />
              </>
            }
          />
          <Route path="/other" element={<Link to="/settings">{BACK}</Link>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

function timeSelect() {
  return screen.getByRole("combobox", { name: s("notify.time_label") });
}

/** 06:00 でオンの設定の画面を、開いたときの PUT を止めた状態まで進める。 */
async function openSettingsWithOpeningPutHeld() {
  givenOn();
  renderInLayout();
  // 外枠の送り直しが終わるまで、設定の画面は状態を読まない
  await waitFor(() => expect(puts.waiting).toHaveLength(1));
  puts.waiting.shift()?.answer();
  await screen.findByRole("button", { name: s("notify.turn_off") });
  await waitFor(() => expect(puts.waiting).toHaveLength(1));
}

function givenOn() {
  fake = installFakePush(ON);
  saveNotifyTime("06:00");
  mockPatientApi({ pushSubscribe: puts.reply });
}

async function openSettingsIdle() {
  await openSettingsWithOpeningPutHeld();
  await puts.drain();
}

beforeEach(() => {
  clearPid();
  savePid(PID);
  window.localStorage.removeItem("tsutae.notify_time");
  puts = holdPuts();
});

afterEach(async () => {
  // 止めた応答を開けたまま終えない（PUT の順番はテストをまたいで続く）
  await puts.drain();
  fake?.uninstall();
  fake = null;
  delete (document as unknown as Record<string, unknown>).visibilityState;
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("changing the time while the app resends", () => {
  it("coming back while the new time is saving: all end on the new time", async () => {
    await openSettingsIdle();
    await userEvent.selectOptions(timeSelect(), "21:30");
    await waitFor(() => expect(puts.sent[puts.sent.length - 1]).toBe("21:30"));
    const changedAt = puts.sent.length - 1;
    setVisibility("hidden");
    setVisibility("visible");
    await puts.drain();
    expect(await screen.findByText(s("notify.time_saved"))).toBeInTheDocument();
    await puts.drain();
    expect(puts.sent.slice(changedAt)).toEqual(["21:30", "21:30"]);
    expect(loadNotifyTime()).toBe("21:30");
    expect(timeSelect()).toHaveValue("21:30");
  });

  it("the opening PUT is slow: the new time goes after it, and is the one kept", async () => {
    await openSettingsWithOpeningPutHeld();
    const before = puts.sent.length;
    await userEvent.selectOptions(timeSelect(), "21:30");
    await settle();
    // 前の PUT の応答を待つ間は出さない（応答の順が入れ替わらないように）
    expect(puts.sent).toHaveLength(before);
    await puts.drain();
    expect(await screen.findByText(s("notify.time_saved"))).toBeInTheDocument();
    expect(puts.sent[puts.sent.length - 1]).toBe("21:30");
    expect(loadNotifyTime()).toBe("21:30");
    expect(timeSelect()).toHaveValue("21:30");
  });

  it("the new time is refused: the resend behind it sends the previous time", async () => {
    await openSettingsIdle();
    await userEvent.selectOptions(timeSelect(), "21:30");
    await waitFor(() => expect(puts.sent[puts.sent.length - 1]).toBe("21:30"));
    setVisibility("hidden");
    setVisibility("visible");
    await settle();
    puts.waiting.shift()?.fail();
    expect(await screen.findByText(s("error.generic"))).toBeInTheDocument();
    await puts.drain();
    expect(puts.sent[puts.sent.length - 1]).toBe("06:00");
    expect(loadNotifyTime()).toBe("06:00");
    expect(timeSelect()).toHaveValue("06:00");
  });

  it("leaving the tab while saving: the screen shows the new time on return", async () => {
    await openSettingsIdle();
    await userEvent.selectOptions(timeSelect(), "21:30");
    await waitFor(() => expect(puts.sent[puts.sent.length - 1]).toBe("21:30"));
    await userEvent.click(screen.getByRole("link", { name: LEAVE }));
    await userEvent.click(await screen.findByRole("link", { name: BACK }));
    await puts.drain();
    await screen.findByRole("button", { name: s("notify.turn_off") });
    await puts.drain();
    expect(timeSelect()).toHaveValue("21:30");
    expect(puts.sent[puts.sent.length - 1]).toBe("21:30");
    expect(loadNotifyTime()).toBe("21:30");
  });
});
