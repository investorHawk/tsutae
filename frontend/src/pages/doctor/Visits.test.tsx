import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { VisitSummary } from "../../api/types";
import { countOf, mockApi, renderRoute } from "../../components/doctor/testing";
import { fixtureBody } from "../../test/apiFixtures";
import { jsonResponse } from "../../test/fetchMock";
import Visits from "./Visits";

const LIST = "GET /api/doctor/visits";

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
  visit({ id: 12, unprocessed_count: 1 }),
  visit({
    id: 13,
    reception_no: "A-024",
    patient_id: "P-EVALA001",
    status: "generating",
  }),
  visit({
    id: 14,
    reception_no: "A-025",
    patient_id: "P-EVALB001",
    fallback: true,
  }),
  visit({ id: 15, reception_no: "A-026", status: "failed" }),
];

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

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
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

describe("Visits（D3 印刷待ち）", () => {
  it("受付番号・仮名ID・状態を並べる", async () => {
    mockApi({ [LIST]: { visits: VISITS } });
    renderVisits();
    expect(
      screen.getByRole("heading", { level: 1, name: "印刷待ち" }),
    ).toBeInTheDocument();
    await screen.findByText("A-023");
    const row = within(rowOf("A-023"));
    expect(row.getByText("P-DEMO0001")).toBeInTheDocument();
    expect(row.getByText("印刷待ち")).toHaveClass("d-status--ready");
    expect(within(rowOf("A-024")).getByText("生成中")).toBeInTheDocument();
    expect(within(rowOf("A-026")).getByText("失敗")).toBeInTheDocument();
  });

  it("実際の API の応答（fixture）をそのまま並べる", async () => {
    mockApi({ [LIST]: fixtureBody("doctor_visits") as object });
    renderVisits();
    await screen.findByText("A-023");
    expect(within(rowOf("A-023")).getByText("印刷待ち")).toBeInTheDocument();
    expect(
      within(rowOf("A-023")).getByRole("link", { name: "未処理 1 件を見る →" }),
    ).toHaveAttribute("href", "/doctor/unprocessed/1");
    expect(within(rowOf("B-101")).getByText("生成中")).toBeInTheDocument();
    expect(within(rowOf("C-202")).getByText("失敗")).toBeInTheDocument();
    expect(
      screen.getByText("印刷待ち 1 件 ・ 生成中 1 件 ・ 失敗 1 件"),
    ).toBeInTheDocument();
  });

  it("一覧に印刷済み（printed）が来たら契約違反として出す（W3 後の決定）", async () => {
    const printed = { ...VISITS[0], id: 11, status: "printed" };
    mockApi({ [LIST]: { visits: [VISITS[1], printed] } });
    renderVisits();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "invalid_response",
    );
    expect(screen.queryByText("A-024")).toBeNull();
  });

  it("受付番号の無い受診が来たら契約違反として出す", async () => {
    const bare = { ...VISITS[0], reception_no: null };
    mockApi({ [LIST]: { visits: [bare] } });
    renderVisits();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "invalid_response",
    );
  });

  it("件数のまとめを出す", async () => {
    mockApi({ [LIST]: { visits: VISITS } });
    renderVisits();
    expect(
      await screen.findByText("印刷待ち 2 件 ・ 生成中 1 件 ・ 失敗 1 件"),
    ).toBeInTheDocument();
  });

  it("AI変換なし（fallback）の印は副の注記（主の状態のバッジと別の見た目）", async () => {
    mockApi({ [LIST]: { visits: VISITS } });
    renderVisits();
    await screen.findByText("A-025");
    const note = within(rowOf("A-025")).getByText("AI変換なし");
    expect(note).toHaveClass("d-status-note");
    expect(note).not.toHaveClass("d-status");
    expect(within(rowOf("A-023")).queryByText("AI変換なし")).toBeNull();
  });

  it("印刷は非表示の iframe で開くボタンと、別タブで開くリンク", async () => {
    mockApi({ [LIST]: { visits: VISITS } });
    renderVisits();
    await screen.findByText("A-023");
    const row = within(rowOf("A-023"));
    expect(row.getByRole("button", { name: "印刷" })).toBeInTheDocument();
    const link = row.getByRole("link", { name: "レポートを開く" });
    expect(link).toHaveAttribute("href", "/api/doctor/visits/12/report");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link.getAttribute("rel")).toContain("noopener");
    expect(row.queryByText(/印刷ダイアログが開きます/)).toBeNull();
    const generating = within(rowOf("A-024"));
    expect(generating.queryByRole("button", { name: "印刷" })).toBeNull();
    expect(
      generating.queryByRole("link", { name: "レポートを開く" }),
    ).toBeNull();
  });

  it("印刷の案内は表の上に1回だけ出す（行ごとにくり返さない）", async () => {
    mockApi({ [LIST]: { visits: VISITS } });
    renderVisits();
    await screen.findByText("A-023");
    const hints = screen.getAllByText(/印刷ダイアログが開きます/);
    expect(hints).toHaveLength(1);
    expect(hints[0].closest("table")).toBeNull();
  });

  it("印刷できる行が無ければ印刷の案内を出さない", async () => {
    mockApi({ [LIST]: { visits: [VISITS[1]] } });
    renderVisits();
    await screen.findByText("A-024");
    expect(screen.queryByText(/印刷ダイアログが開きます/)).toBeNull();
  });

  it("未処理の件数があれば D6 への導線", async () => {
    mockApi({ [LIST]: { visits: VISITS } });
    renderVisits();
    await screen.findByText("A-023");
    expect(
      within(rowOf("A-023")).getByRole("link", { name: "未処理 1 件を見る →" }),
    ).toHaveAttribute("href", "/doctor/unprocessed/12");
    expect(
      within(rowOf("A-025")).queryByRole("link", { name: /未処理/ }),
    ).toBeNull();
  });

  it("生成中なら D5 への導線", async () => {
    mockApi({ [LIST]: { visits: VISITS } });
    renderVisits();
    await screen.findByText("A-024");
    expect(
      within(rowOf("A-024")).getByRole("link", { name: "変換の様子を見る" }),
    ).toHaveAttribute("href", "/doctor/pipeline/13");
  });

  it("5秒ごとに一覧を取り直す", async () => {
    const fetchMock = mockApi({ [LIST]: { visits: VISITS } });
    renderVisits();
    await screen.findByText("A-023");
    expect(countOf(fetchMock, LIST)).toBe(1);
    await advance(4900);
    expect(countOf(fetchMock, LIST)).toBe(1);
    await advance(100);
    expect(countOf(fetchMock, LIST)).toBe(2);
    await advance(5000);
    expect(countOf(fetchMock, LIST)).toBe(3);
  });

  it("取り直しで増えた受付が出る", async () => {
    const lists = [[VISITS[0]], VISITS];
    mockApi({
      [LIST]: () => jsonResponse({ visits: lists.shift() ?? VISITS }),
    });
    renderVisits();
    await screen.findByText("A-023");
    expect(screen.queryByText("A-024")).toBeNull();
    await advance(5000);
    expect(await screen.findByText("A-024")).toBeInTheDocument();
  });

  it("印刷済みは2段階: 1回目では送らず、確認の後に POST して取り直す", async () => {
    const fetchMock = mockApi({
      [LIST]: { visits: VISITS },
      "POST /api/doctor/visits/12/printed": { ok: true },
    });
    renderVisits();
    await screen.findByText("A-023");
    const u = user();
    await u.click(
      within(rowOf("A-023")).getByRole("button", { name: "印刷済み" }),
    );
    expect(countOf(fetchMock, "POST /api/doctor/visits/12/printed")).toBe(0);
    expect(within(rowOf("A-023")).getByText(/削除します/)).toBeInTheDocument();
    await u.click(
      within(rowOf("A-023")).getByRole("button", {
        name: "削除する（印刷済み）",
      }),
    );
    await waitFor(() =>
      expect(countOf(fetchMock, "POST /api/doctor/visits/12/printed")).toBe(1),
    );
    await waitFor(() => expect(countOf(fetchMock, LIST)).toBe(2));
  });

  it("印刷済みにできたら「受付 <番号> のレポートを削除しました」を status で出す", async () => {
    mockApi({
      [LIST]: { visits: VISITS },
      "POST /api/doctor/visits/12/printed": { ok: true },
    });
    renderVisits();
    await screen.findByText("A-023");
    const u = user();
    await u.click(
      within(rowOf("A-023")).getByRole("button", { name: "印刷済み" }),
    );
    await u.click(
      within(rowOf("A-023")).getByRole("button", {
        name: "削除する（印刷済み）",
      }),
    );
    expect(
      await screen.findByText("受付 A-023 のレポートを削除しました"),
    ).toHaveAttribute("role", "status");
  });

  it("印刷済みにできなければ削除の知らせは出さない", async () => {
    mockApi({
      [LIST]: { visits: VISITS },
      "POST /api/doctor/visits/12/printed": () =>
        jsonResponse({ error: "visit_closed" }, 409),
    });
    renderVisits();
    await screen.findByText("A-023");
    const u = user();
    await u.click(
      within(rowOf("A-023")).getByRole("button", { name: "印刷済み" }),
    );
    await u.click(
      within(rowOf("A-023")).getByRole("button", {
        name: "削除する（印刷済み）",
      }),
    );
    await screen.findByRole("alert");
    expect(screen.queryByText(/のレポートを削除しました/)).toBeNull();
  });

  it("印刷済みの確認は「やめる」で取り消せる", async () => {
    const fetchMock = mockApi({ [LIST]: { visits: VISITS } });
    renderVisits();
    await screen.findByText("A-023");
    const u = user();
    await u.click(
      within(rowOf("A-023")).getByRole("button", { name: "印刷済み" }),
    );
    await u.click(
      within(rowOf("A-023")).getByRole("button", { name: "やめる" }),
    );
    expect(
      within(rowOf("A-023")).getByRole("button", { name: "印刷済み" }),
    ).toBeInTheDocument();
    expect(countOf(fetchMock, "POST /api/doctor/visits/12/printed")).toBe(0);
  });

  it("印刷済みにできなければ code を出す", async () => {
    mockApi({
      [LIST]: { visits: VISITS },
      "POST /api/doctor/visits/12/printed": () =>
        jsonResponse({ error: "visit_closed" }, 409),
    });
    renderVisits();
    await screen.findByText("A-023");
    const u = user();
    await u.click(
      within(rowOf("A-023")).getByRole("button", { name: "印刷済み" }),
    );
    await u.click(
      within(rowOf("A-023")).getByRole("button", {
        name: "削除する（印刷済み）",
      }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("visit_closed");
  });

  it.each([
    ["{ok:false}", { ok: false }],
    ["本文が空", {}],
  ])(
    "印刷済みの応答が 200 %s なら invalid_response を出す",
    async (_l, body) => {
      mockApi({
        [LIST]: { visits: VISITS },
        "POST /api/doctor/visits/12/printed": body,
      });
      renderVisits();
      await screen.findByText("A-023");
      const u = user();
      await u.click(
        within(rowOf("A-023")).getByRole("button", { name: "印刷済み" }),
      );
      await u.click(
        within(rowOf("A-023")).getByRole("button", {
          name: "削除する（印刷済み）",
        }),
      );
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "invalid_response",
      );
    },
  );

  it("受付が無ければその旨", async () => {
    mockApi({ [LIST]: { visits: [] } });
    renderVisits();
    expect(await screen.findByText("受付はまだありません")).toBeInTheDocument();
  });

  it.each([
    ["visits が無い", { ok: true }],
    ["visits が配列でない", { visits: "x" }],
    ["要素の必須項目が欠けている", { visits: [{ id: 1 }] }],
  ])(
    "応答が契約と違えば（%s）invalid_response を出し、0件と言わない",
    async (_label, body) => {
      mockApi({ [LIST]: body });
      renderVisits();
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "invalid_response",
      );
      expect(screen.queryByText("受付はまだありません")).toBeNull();
    },
  );

  it("取れなければ code を出し、取り直しは続ける", async () => {
    const fetchMock = mockApi({});
    renderVisits();
    expect(await screen.findByRole("alert")).toHaveTextContent("not_found");
    await advance(5000);
    expect(countOf(fetchMock, LIST)).toBe(2);
  });

  it("401 ならログイン画面へ移り、取り直しを止める", async () => {
    const fetchMock = mockApi({
      [LIST]: () => jsonResponse({ error: "not_logged_in" }, 401),
    });
    renderVisits();
    await waitFor(() =>
      expect(screen.getByTestId("where")).toHaveTextContent(
        /^\/doctor\/login$/,
      ),
    );
    await advance(10_000);
    expect(countOf(fetchMock, LIST)).toBe(1);
  });

  it("画面を離れたら取り直しを止める", async () => {
    const fetchMock = mockApi({ [LIST]: { visits: VISITS } });
    const { unmount } = renderVisits();
    await screen.findByText("A-023");
    unmount();
    await advance(10_000);
    expect(countOf(fetchMock, LIST)).toBe(1);
  });
});
