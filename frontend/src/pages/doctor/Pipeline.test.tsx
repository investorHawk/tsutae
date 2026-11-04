import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { PipelineEvent, VisitStatus } from "../../api/types";
import { countOf, mockApi, renderRoute } from "../../components/doctor/testing";
import { visitHeaderStub } from "../../test/doctorStubs";
import { jsonResponse } from "../../test/fetchMock";
import Pipeline from "./Pipeline";

const EVENTS_KEY = "GET /api/doctor/pipeline/12/events";
const ROUTE = "/doctor/pipeline/:visitId";

function ev(patch: Partial<PipelineEvent>): PipelineEvent {
  return {
    ts: "2026-11-09T10:00:00+09:00",
    event: "run_start",
    hook_name: null,
    agent_type: null,
    tool_name: null,
    decision: null,
    duration_ms: null,
    ...patch,
  };
}

const EARLY: PipelineEvent[] = [
  ev({ event: "run_start" }),
  ev({
    ts: "2026-11-09T10:00:00.400+09:00",
    event: "hook",
    hook_name: "H1",
    decision: "allow",
  }),
  ev({
    ts: "2026-11-09T10:00:02+09:00",
    event: "subagent_start",
    agent_type: "date-normalizer",
  }),
];

const LATE: PipelineEvent[] = [
  ...EARLY,
  ev({
    ts: "2026-11-09T10:00:08+09:00",
    event: "subagent_stop",
    agent_type: "date-normalizer",
    duration_ms: 6000,
  }),
  ev({
    ts: "2026-11-09T10:00:10+09:00",
    event: "hook",
    hook_name: "H2",
    tool_name: "mcp__tsutae__emit_timeline",
    decision: "deny:events.2.source_quote",
  }),
  ev({
    ts: "2026-11-09T10:00:12+09:00",
    event: "emit_timeline",
    tool_name: "mcp__tsutae__emit_timeline",
    decision: "accept",
  }),
  ev({
    ts: "2026-11-09T10:00:14+09:00",
    event: "emit_report",
    tool_name: "mcp__tsutae__emit_report",
    decision: "accept",
  }),
];

function body(status: VisitStatus, events: PipelineEvent[]) {
  const visit = visitHeaderStub({
    status,
    report_available: status === "ready",
    reception_no: status === "printed" ? null : "A-023",
  });
  return { status, visit, events };
}

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

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

function renderPipeline(path = "/doctor/pipeline/12") {
  return renderRoute(path, ROUTE, <Pipeline />);
}

/** 折りたたんだ「すべての出来事（N 件）」を開いて、時系列の一覧を返す。 */
async function openTimeline(count: number) {
  fireEvent.click(
    await screen.findByText(`すべての出来事（${count} 件）`, {
      selector: "summary",
    }),
  );
  return screen.getByRole("list", { name: "時系列" });
}

describe("Pipeline（D5 変換ログ）", () => {
  // D6-1: 印刷待ちのリンク「変換ログ」と見出しをそろえる。
  // D6-2: ready を見た時点で「止めました（完了）」と出す（取り直しの1回は裏で続ける）
  it("2秒ごとに取り直し、ready になったら1回だけ取り直してから止める", async () => {
    const answers = [
      body("generating", EARLY),
      body("generating", EARLY),
      body("ready", LATE),
    ];
    const fetchMock = mockApi({
      [EVENTS_KEY]: () => jsonResponse(answers.shift() ?? body("ready", LATE)),
    });
    renderPipeline();
    expect(
      screen.getByRole("heading", { level: 1, name: "変換ログ" }),
    ).toBeInTheDocument();
    expect(await screen.findByText("生成中")).toBeInTheDocument();
    expect(countOf(fetchMock, EVENTS_KEY)).toBe(1);
    await advance(2000);
    expect(countOf(fetchMock, EVENTS_KEY)).toBe(2);
    expect(screen.getByText("2秒ごとに更新中")).toHaveClass("d-live--on");
    await advance(2000);
    expect(countOf(fetchMock, EVENTS_KEY)).toBe(3);
    expect(await screen.findByText("印刷待ち")).toBeInTheDocument();
    expect(screen.getByText("更新を止めました（完了）")).not.toHaveClass(
      "d-live--on",
    );
    expect(screen.queryByText("2秒ごとに更新中")).toBeNull();
    await advance(2000);
    expect(countOf(fetchMock, EVENTS_KEY)).toBe(4);
    await advance(10_000);
    expect(countOf(fetchMock, EVENTS_KEY)).toBe(4);
    expect(screen.getByText("更新を止めました（完了）")).toBeInTheDocument();
  });

  it("終わった後の最後の取り直しで、遅れて記録された出来事も出す", async () => {
    const TAIL = ev({
      ts: "2026-11-09T10:00:15+09:00",
      event: "report_saved",
      decision: "ready",
    });
    const answers = [body("ready", LATE), body("ready", [...LATE, TAIL])];
    const fetchMock = mockApi({
      [EVENTS_KEY]: () =>
        jsonResponse(answers.shift() ?? body("ready", [...LATE, TAIL])),
    });
    renderPipeline();
    expect(await screen.findByText("印刷待ち")).toBeInTheDocument();
    await openTimeline(LATE.length);
    const list = () => screen.getByRole("list", { name: "時系列" });
    expect(within(list()).getAllByRole("listitem")).toHaveLength(LATE.length);
    await advance(2000);
    expect(countOf(fetchMock, EVENTS_KEY)).toBe(2);
    await waitFor(() =>
      expect(within(list()).getAllByRole("listitem")).toHaveLength(
        LATE.length + 1,
      ),
    );
    await advance(10_000);
    expect(countOf(fetchMock, EVENTS_KEY)).toBe(2);
    expect(screen.getByText(/更新を止めました/)).toBeInTheDocument();
  });

  it("failed でも1回だけ取り直してから止める", async () => {
    const fetchMock = mockApi({ [EVENTS_KEY]: body("failed", EARLY) });
    renderPipeline();
    expect(await screen.findByText("失敗")).toBeInTheDocument();
    expect(
      screen.getByText("更新を止めました（失敗で終了）"),
    ).toBeInTheDocument();
    await advance(10_000);
    expect(countOf(fetchMock, EVENTS_KEY)).toBe(2);
  });

  it("印刷済みも完了として止める", async () => {
    const fetchMock = mockApi({ [EVENTS_KEY]: body("printed", LATE) });
    renderPipeline();
    expect(
      await screen.findByText("更新を止めました（完了）"),
    ).toBeInTheDocument();
    await advance(10_000);
    expect(countOf(fetchMock, EVENTS_KEY)).toBe(2);
  });

  it("最後の取り直しでまだ終わっていなければ、取り直しを続ける", async () => {
    const answers = [body("ready", LATE), body("generating", EARLY)];
    const fetchMock = mockApi({
      [EVENTS_KEY]: () => jsonResponse(answers.shift() ?? body("ready", LATE)),
    });
    renderPipeline();
    expect(await screen.findByText("印刷待ち")).toBeInTheDocument();
    await advance(2000);
    expect(countOf(fetchMock, EVENTS_KEY)).toBe(2);
    await advance(2000);
    expect(countOf(fetchMock, EVENTS_KEY)).toBe(3);
    await advance(2000);
    expect(countOf(fetchMock, EVENTS_KEY)).toBe(4);
    await advance(10_000);
    expect(countOf(fetchMock, EVENTS_KEY)).toBe(4);
  });

  // D6-3: 時系列は「すべての出来事（N 件）」に折りたたむ（レーンと二重に出して縦に伸ばさない）
  // D6-4: カードは日本語の一行が主。内部のコードは小さく（d-pl-code）添える
  it("出来事を時系列のカードで出す（Hook の拒否と規則コードつき）", async () => {
    mockApi({ [EVENTS_KEY]: body("ready", LATE) });
    renderPipeline();
    const details = (
      await screen.findByText(`すべての出来事（${LATE.length} 件）`)
    ).closest("details");
    expect(details).not.toHaveAttribute("open");
    const list = await openTimeline(LATE.length);
    expect(details).toHaveAttribute("open");
    const cards = within(list).getAllByRole("listitem");
    expect(cards).toHaveLength(LATE.length);
    expect(cards[0]).toHaveTextContent("変換を開始");
    expect(within(cards[0]).getByText("run_start")).toHaveClass("d-pl-code");
    expect(cards[1]).toHaveTextContent("H1 送信前の伏せ字漏れ検査");
    expect(cards[2]).toHaveTextContent("日付の担当が作業を開始");
    expect(cards[4]).toHaveTextContent("H2 引用と原文の照合：時系列の提出");
    expect(cards[4]).toHaveTextContent("拒否");
    expect(cards[4]).toHaveTextContent("events.2.source_quote");
    expect(cards[4]).toHaveClass("d-pl-card--deny");
    expect(
      within(cards[4]).getByText("mcp__tsutae__emit_timeline"),
    ).toHaveClass("d-pl-code");
    expect(cards[5]).toHaveTextContent("時系列を提出");
    expect(cards[5]).toHaveTextContent("受理");
    expect(cards[6]).toHaveTextContent("レポートの項目を提出");
    expect(cards[6]).toHaveTextContent("emit_report");
    expect(cards[3]).toHaveTextContent("+8.0秒");
    expect(cards[3]).toHaveTextContent("6.0秒");
  });

  it("主エージェントと3役のレーンに状態を出す", async () => {
    mockApi({ [EVENTS_KEY]: body("generating", EARLY) });
    renderPipeline();
    const lanes = await screen.findByRole("region", { name: "3役のレーン" });
    const lane = (name: string) =>
      within(lanes).getByRole("group", { name: new RegExp(name) });
    await waitFor(() =>
      expect(lane("date-normalizer")).toHaveTextContent("実行中"),
    );
    expect(lane("主エージェント")).toHaveTextContent("実行中");
    expect(lane("term-mapper")).toHaveTextContent("待機");
    expect(lane("contradiction-finder")).toHaveTextContent("待機");
  });

  // D6-3: レーンは役ごとの要約（件数・最後の出来事・状態）。出来事を1件ずつ並べない
  // D6-5: まだ動いていない役は低くし、その旨を出す
  it("レーンは件数と最後の出来事の要約。空の役は「まだ動いていません」", async () => {
    mockApi({ [EVENTS_KEY]: body("generating", EARLY) });
    renderPipeline();
    const lanes = await screen.findByRole("region", { name: "3役のレーン" });
    const lane = (name: string) =>
      within(lanes).getByRole("group", { name: new RegExp(name) });
    await waitFor(() => expect(lane("日付の担当")).toHaveTextContent("1 件"));
    expect(lane("日付の担当")).toHaveTextContent("日付の担当が作業を開始");
    expect(lane("日付の担当")).toHaveTextContent("date-normalizer");
    expect(lane("主エージェント")).toHaveTextContent("2 件");
    expect(lane("主エージェント")).toHaveTextContent(
      "H1 送信前の伏せ字漏れ検査",
    );
    expect(lane("用語の担当")).toHaveTextContent("まだ動いていません");
    expect(lane("用語の担当")).toHaveClass("d-pl-lane--waiting");
    expect(within(lanes).queryAllByRole("listitem")).toHaveLength(0);
  });

  it("変換が終わっても動かなかった役は「この変換では動いていません」", async () => {
    mockApi({ [EVENTS_KEY]: body("ready", LATE) });
    renderPipeline();
    const lanes = await screen.findByRole("region", { name: "3役のレーン" });
    const lane = (name: string) =>
      within(lanes).getByRole("group", { name: new RegExp(name) });
    await waitFor(() =>
      expect(lane("用語の担当")).toHaveTextContent(
        "この変換では動いていません",
      ),
    );
    expect(lane("日付の担当")).toHaveTextContent("日付の担当が作業を終了");
    expect(lane("主エージェント")).toHaveTextContent("止めた 1 件");
  });

  it("Hook H1〜H4 の発火数と拒否数", async () => {
    mockApi({ [EVENTS_KEY]: body("ready", LATE) });
    renderPipeline();
    const hooks = await screen.findByRole("region", { name: "Hook" });
    const tile = (id: string) =>
      within(hooks).getByRole("group", { name: new RegExp(`^${id}`) });
    await waitFor(() => expect(tile("H1")).toHaveTextContent("発火 1"));
    expect(tile("H2")).toHaveTextContent("拒否 1");
    expect(tile("H3")).toHaveTextContent("発火 0");
    expect(tile("H4")).toHaveTextContent("発火 0");
  });

  it("文面は出さない旨の注記", async () => {
    mockApi({ [EVENTS_KEY]: body("ready", []) });
    renderPipeline();
    expect(screen.getByText(/文面/)).toBeInTheDocument();
    expect(
      await screen.findByText("まだ出来事はありません"),
    ).toBeInTheDocument();
  });

  it("受診の番号が数でなければ API を呼ばない", async () => {
    const fetchMock = mockApi({});
    renderPipeline("/doctor/pipeline/x1");
    expect(screen.getByRole("alert")).toHaveTextContent("invalid_visit_id");
    await advance(5000);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("404 なら code を出して止める", async () => {
    const fetchMock = mockApi({});
    renderPipeline();
    expect(await screen.findByRole("alert")).toHaveTextContent("not_found");
    await advance(10_000);
    expect(countOf(fetchMock, EVENTS_KEY)).toBe(1);
  });

  it("通信の失敗では取り直しを続ける", async () => {
    const answers: Array<() => Response> = [
      () => jsonResponse({ error: "server_error" }, 500),
      () => jsonResponse(body("generating", EARLY)),
    ];
    const fetchMock = mockApi({
      [EVENTS_KEY]: () => (answers.shift() ?? answers[0])(),
    });
    renderPipeline();
    expect(await screen.findByRole("alert")).toHaveTextContent("server_error");
    await advance(2000);
    expect(countOf(fetchMock, EVENTS_KEY)).toBe(2);
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  });

  it("同じ画面のまま別の受診へ移ったら、その受診を取り直す", async () => {
    const other = "GET /api/doctor/pipeline/13/events";
    const fetchMock = mockApi({
      [EVENTS_KEY]: body("ready", LATE),
      [other]: body("generating", EARLY),
    });
    function GoTo() {
      const navigate = useNavigate();
      return (
        <button type="button" onClick={() => navigate("/doctor/pipeline/13")}>
          go
        </button>
      );
    }
    render(
      <MemoryRouter initialEntries={["/doctor/pipeline/12"]}>
        <Routes>
          <Route path={ROUTE} element={<Pipeline />} />
        </Routes>
        <GoTo />
      </MemoryRouter>,
    );
    expect(await screen.findByText("印刷待ち")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "go" }));
    await waitFor(() => expect(countOf(fetchMock, other)).toBe(1));
    expect(await screen.findByText("生成中")).toBeInTheDocument();
    expect(countOf(fetchMock, EVENTS_KEY)).toBe(1);
  });

  it("見出しは受付番号・仮名ID・受付の日時（内部の番号「受診 #」は出さない）", async () => {
    mockApi({ [EVENTS_KEY]: body("ready", LATE) });
    renderPipeline();
    expect(
      await screen.findByText("A-023 ・ P-DEMO0001 ・ 11月9日（月）18:16 受付"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/受診 #/)).toBeNull();
  });

  it("印刷済みで受付番号が消えていれば、受付番号を出さない", async () => {
    mockApi({ [EVENTS_KEY]: body("printed", LATE) });
    renderPipeline();
    expect(
      await screen.findByText("P-DEMO0001 ・ 11月9日（月）18:16 受付"),
    ).toBeInTheDocument();
  });

  it.each([
    ["events が無い", { status: "generating", visit: visitHeaderStub() }],
    ["visit が無い", { status: "generating", events: [] }],
    [
      "status が知らない値",
      { status: "weird", visit: visitHeaderStub(), events: [] },
    ],
    [
      "要素の型が違う",
      { status: "ready", visit: visitHeaderStub(), events: [{ event: 1 }] },
    ],
  ])(
    "応答が契約と違えば（%s）invalid_response（出来事0件と言わない）",
    async (_l, b) => {
      mockApi({ [EVENTS_KEY]: b });
      renderPipeline();
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "invalid_response",
      );
      expect(screen.queryByText("まだ出来事はありません")).toBeNull();
    },
  );
});
