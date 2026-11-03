/**
 * D3 印刷待ち: 「AI でもう一度変換」（POST /api/doctor/visits/{id}/regenerate）。
 * AI変換なし（fallback）の ready と failed の行にだけ出す。2段階の確認はしない。
 * 押したら依頼を送り、一覧を取り直す（状態は一覧の generating で変わる）。
 */
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { VisitSummary } from "../../api/types";
import {
  countOf,
  deferred,
  mockApi,
  renderRoute,
} from "../../components/doctor/testing";
import { fixtureBody } from "../../test/apiFixtures";
import { jsonResponse } from "../../test/fetchMock";
import Visits from "./Visits";

const LIST = "GET /api/doctor/visits";
const LABEL = "AI でもう一度変換";

function visit(patch: Partial<VisitSummary>): VisitSummary {
  return {
    id: 12,
    reception_no: "A-023",
    patient_id: "P-DEMO0001",
    status: "ready",
    fallback: false,
    created_at: "2026-11-09T09:40:00+09:00",
    expires_at: "2026-11-10T09:40:00+09:00",
    unprocessed_count: 0,
    ...patch,
  };
}

const VISITS: VisitSummary[] = [
  visit({ id: 12 }),
  visit({ id: 13, reception_no: "A-024", status: "generating" }),
  visit({ id: 14, reception_no: "A-025", fallback: true }),
  visit({ id: 15, reception_no: "A-026", status: "failed" }),
];
const REGEN_14 = "POST /api/doctor/visits/14/regenerate";
const REGEN_15 = "POST /api/doctor/visits/15/regenerate";

beforeEach(() => {
  vi.useFakeTimers({
    toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval"],
    shouldAdvanceTime: true,
  });
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function user() {
  return userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
}

function renderVisits() {
  return renderRoute("/doctor", "/doctor", <Visits />);
}

function rowOf(receptionNo: string): HTMLElement {
  const row = screen.getByText(receptionNo).closest("tr");
  if (!row) {
    throw new Error(`${receptionNo} の行が無い`);
  }
  return row;
}

function buttonIn(receptionNo: string): HTMLElement {
  return within(rowOf(receptionNo)).getByRole("button", { name: LABEL });
}

describe("Visits: AI でもう一度変換", () => {
  it("AI変換なしの ready と failed の行にだけ出す", async () => {
    mockApi({ [LIST]: { visits: VISITS } });
    renderVisits();
    await screen.findByText("A-025");
    expect(buttonIn("A-025")).toBeEnabled();
    expect(buttonIn("A-026")).toBeEnabled();
    for (const no of ["A-023", "A-024"]) {
      expect(
        within(rowOf(no)).queryByRole("button", { name: LABEL }),
      ).toBeNull();
    }
  });

  it("AI変換なしの ready でも印刷・印刷済みは残す", async () => {
    mockApi({ [LIST]: { visits: VISITS } });
    renderVisits();
    await screen.findByText("A-025");
    const row = within(rowOf("A-025"));
    expect(row.getByRole("button", { name: "印刷" })).toBeInTheDocument();
    expect(row.getByRole("button", { name: "印刷済み" })).toBeInTheDocument();
  });

  it("実際の API の応答（fixture）の失敗の行に出す", async () => {
    mockApi({ [LIST]: fixtureBody("doctor_visits") as object });
    renderVisits();
    await screen.findByText("C-202");
    expect(buttonIn("C-202")).toBeEnabled();
    expect(
      within(rowOf("A-023")).queryByRole("button", { name: LABEL }),
    ).toBeNull();
  });

  it("1回押すと確認なしで1回だけ送り、一覧を取り直して生成中の表示になる", async () => {
    const lists = [
      VISITS,
      [VISITS[0], VISITS[1], VISITS[2], { ...VISITS[3], status: "generating" }],
    ];
    const fetchMock = mockApi({
      [LIST]: () => jsonResponse({ visits: lists.shift() ?? [] }),
      [REGEN_15]: { ok: true },
    });
    renderVisits();
    await screen.findByText("A-026");
    await user().click(buttonIn("A-026"));
    await waitFor(() => expect(countOf(fetchMock, REGEN_15)).toBe(1));
    await waitFor(() => expect(countOf(fetchMock, LIST)).toBe(2));
    expect(
      await within(rowOf("A-026")).findByText("生成中"),
    ).toBeInTheDocument();
    expect(
      within(rowOf("A-026")).queryByRole("button", { name: LABEL }),
    ).toBeNull();
    expect(
      screen.getByText("受付 A-026 を AI でもう一度変換しています"),
    ).toHaveAttribute("role", "status");
  });

  it("送っている間はボタンを押せない（二重に送らない）", async () => {
    const pending = deferred<Response>();
    const fetchMock = mockApi({
      [LIST]: { visits: VISITS },
      [REGEN_14]: () => pending.promise,
    });
    renderVisits();
    await screen.findByText("A-025");
    const u = user();
    await u.click(buttonIn("A-025"));
    const busy = within(rowOf("A-025")).getByRole("button", {
      name: "変換を依頼中…",
    });
    expect(busy).toBeDisabled();
    // 依頼中は同じ行の印刷・印刷済みも押せない（前のレポートで印刷済みにしない）
    const row = within(rowOf("A-025"));
    expect(row.getByRole("button", { name: "印刷" })).toBeDisabled();
    expect(row.getByRole("button", { name: "印刷済み" })).toBeDisabled();
    await u.click(busy);
    expect(countOf(fetchMock, REGEN_14)).toBe(1);
    await act(async () => {
      pending.resolve(jsonResponse({ ok: true }));
    });
    await waitFor(() => expect(countOf(fetchMock, LIST)).toBe(2));
  });

  it("409 not_regenerable なら code を出し、ボタンを戻す", async () => {
    mockApi({
      [LIST]: { visits: VISITS },
      [REGEN_14]: () => jsonResponse({ error: "not_regenerable" }, 409),
    });
    renderVisits();
    await screen.findByText("A-025");
    await user().click(buttonIn("A-025"));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("もう一度変換できませんでした");
    expect(alert).toHaveTextContent("not_regenerable");
    expect(screen.queryByText(/もう一度変換しています/)).toBeNull();
    await waitFor(() => expect(buttonIn("A-025")).toBeEnabled());
  });

  it("応答が {ok:false} なら invalid_response を出す", async () => {
    mockApi({ [LIST]: { visits: VISITS }, [REGEN_15]: { ok: false } });
    renderVisits();
    await screen.findByText("A-026");
    await user().click(buttonIn("A-026"));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "invalid_response",
    );
  });

  it("401 ならログイン画面へ移す", async () => {
    mockApi({
      [LIST]: { visits: VISITS },
      [REGEN_15]: () => jsonResponse({ error: "not_logged_in" }, 401),
    });
    renderVisits();
    await screen.findByText("A-026");
    await user().click(buttonIn("A-026"));
    await waitFor(() =>
      expect(screen.getByTestId("where")).toHaveTextContent(
        /^\/doctor\/login$/,
      ),
    );
  });
});
