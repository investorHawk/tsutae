import { screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { countOf, mockApi, renderRoute } from "../../components/doctor/testing";
import { fixtureBody } from "../../test/apiFixtures";
import { jsonResponse } from "../../test/fetchMock";
import { visitHeaderStub } from "../../test/doctorStubs";
import Unprocessed from "./Unprocessed";

afterEach(() => {
  vi.unstubAllGlobals();
});

const ROUTE = "/doctor/unprocessed/:visitId";
const RAW = "（合成）今日は架空野さんに送ってもらった。";

describe("Unprocessed", () => {
  it("送らなかった記録の原文・記録日・規則名を出す", async () => {
    mockApi({
      "GET /api/doctor/visits/12/unprocessed": {
        visit: visitHeaderStub(),
        entries: [
          {
            entry_id: 31,
            record_date: "2026-11-03",
            course_no: 3,
            day: 8,
            reason: "unknown_before_honorific",
            text: RAW,
            marks: [],
            doctor_mask: null,
          },
        ],
      },
    });
    renderRoute("/doctor/unprocessed/12", ROUTE, <Unprocessed />);
    expect(
      screen.getByRole("heading", { level: 1, name: "未処理の記載" }),
    ).toBeInTheDocument();
    expect(await screen.findByText(RAW)).toHaveClass("d-raw");
    expect(
      screen.getByText(/記録日 11月3日（火）・第3コース Day8 ・/),
    ).toBeInTheDocument();
    // 内部の番号（記録 #・受診 #）は出さない
    expect(screen.queryByText(/記録 #/)).toBeNull();
    expect(screen.queryByText(/受診 #/)).toBeNull();
    expect(screen.queryByText(/unknown_before_honorific/)).toBeNull();
    expect(screen.getByText(/敬称の前/)).toHaveAttribute(
      "title",
      "unknown_before_honorific",
    );
  });

  it("見出しは受付番号・仮名ID・受付の日時", async () => {
    mockApi({
      "GET /api/doctor/visits/12/unprocessed": {
        visit: visitHeaderStub(),
        entries: [],
      },
    });
    renderRoute("/doctor/unprocessed/12", ROUTE, <Unprocessed />);
    expect(
      await screen.findByText("A-023 ・ P-DEMO0001 ・ 11月9日（月）18:16 受付"),
    ).toBeInTheDocument();
  });

  it("コース外の記録は日付だけ", async () => {
    mockApi({
      "GET /api/doctor/visits/12/unprocessed": {
        visit: visitHeaderStub(),
        entries: [
          {
            entry_id: 31,
            record_date: "2026-09-20",
            course_no: null,
            day: null,
            reason: "unknown_before_honorific",
            text: RAW,
            marks: [],
            doctor_mask: null,
          },
        ],
      },
    });
    renderRoute("/doctor/unprocessed/12", ROUTE, <Unprocessed />);
    expect(
      await screen.findByText(/記録日 9月20日（日） ・/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/コース/)).toBeNull();
  });

  it("レポートを開ける受診なら、確かめた後にそのまま印刷できる（印刷待ちと同じ部品）", async () => {
    mockApi({
      "GET /api/doctor/visits/1/unprocessed": fixtureBody(
        "doctor_unprocessed",
      ) as object,
    });
    renderRoute("/doctor/unprocessed/1", ROUTE, <Unprocessed />);
    const box = await screen.findByRole("region", {
      name: "この受診のレポート",
    });
    expect(within(box).getByRole("button", { name: "印刷" })).toHaveClass(
      "d-linkbutton--primary",
    );
    expect(
      within(box).getByRole("link", { name: "レポートを開く" }),
    ).toHaveAttribute("href", "/api/doctor/visits/1/report");
  });

  it.each([
    ["生成中", { status: "generating", report_available: false }],
    ["失敗", { status: "failed", report_available: false }],
  ] as const)(
    "レポートを開けない受診（%s）では印刷を出さない",
    async (_l, patch) => {
      mockApi({
        "GET /api/doctor/visits/12/unprocessed": {
          visit: visitHeaderStub(patch),
          entries: [],
        },
      });
      renderRoute("/doctor/unprocessed/12", ROUTE, <Unprocessed />);
      await screen.findByText("未処理の記載はありません");
      expect(screen.queryByRole("button", { name: "印刷" })).toBeNull();
      expect(screen.queryByRole("link", { name: "レポートを開く" })).toBeNull();
    },
  );

  it("疑われた語に印（<mark>）を付ける（D7-2）", async () => {
    const text = "磯鷲さんにもらった漢方をのんでみた";
    mockApi({
      "GET /api/doctor/visits/12/unprocessed": {
        visit: visitHeaderStub(),
        entries: [
          {
            entry_id: 38,
            record_date: "2026-11-05",
            course_no: 3,
            day: 10,
            reason: "unknown_before_honorific",
            text,
            marks: [{ start: 0, end: 4 }],
            doctor_mask: null,
          },
        ],
      },
    });
    const { container } = renderRoute(
      "/doctor/unprocessed/12",
      ROUTE,
      <Unprocessed />,
    );
    const mark = await screen.findByText("磯鷲さん");
    expect(mark.tagName).toBe("MARK");
    expect(container.querySelector(".d-raw")).toHaveTextContent(text);
    expect(container.querySelectorAll("mark")).toHaveLength(1);
  });

  it("実際の API の応答（fixture）の印をそのまま描く", async () => {
    mockApi({
      "GET /api/doctor/visits/12/unprocessed": fixtureBody(
        "doctor_unprocessed",
      ) as object,
    });
    renderRoute("/doctor/unprocessed/12", ROUTE, <Unprocessed />);
    expect((await screen.findByText("磯鷲さん")).tagName).toBe("MARK");
  });

  it("規則を知らなければ一般の説明にする（コードは出さない）", async () => {
    mockApi({
      "GET /api/doctor/visits/12/unprocessed": {
        visit: visitHeaderStub(),
        entries: [
          {
            entry_id: 31,
            record_date: "2026-11-03",
            course_no: 3,
            day: 8,
            reason: "new_rule",
            text: RAW,
            marks: [],
            doctor_mask: null,
          },
        ],
      },
    });
    renderRoute("/doctor/unprocessed/12", ROUTE, <Unprocessed />);
    expect(await screen.findByText(/伏せ字漏れの疑い$/)).toBeInTheDocument();
    expect(screen.queryByText(/new_rule/)).toBeNull();
  });

  it.each([
    ["address_number", /住所の疑い/],
    ["id_like", /受付番号の疑い/],
    ["known_identifier", /仮名ID か受付番号/],
  ])("W2b で増えた規則 %s にも説明を出す", async (reason, label) => {
    mockApi({
      "GET /api/doctor/visits/12/unprocessed": {
        visit: visitHeaderStub(),
        entries: [
          {
            entry_id: 31,
            record_date: "2026-11-03",
            course_no: 3,
            day: 8,
            reason,
            text: RAW,
            marks: [],
            doctor_mask: null,
          },
        ],
      },
    });
    renderRoute("/doctor/unprocessed/12", ROUTE, <Unprocessed />);
    expect(await screen.findByText(label)).toBeInTheDocument();
  });

  it("「紙には載りません」の注記がある", async () => {
    mockApi({
      "GET /api/doctor/visits/12/unprocessed": {
        visit: visitHeaderStub(),
        entries: [],
      },
    });
    renderRoute("/doctor/unprocessed/12", ROUTE, <Unprocessed />);
    expect(screen.getByText(/紙には載りません/)).toBeInTheDocument();
    await screen.findByText("未処理の記載はありません");
  });

  it("0件なら「ありません」", async () => {
    mockApi({
      "GET /api/doctor/visits/12/unprocessed": {
        visit: visitHeaderStub(),
        entries: [],
      },
    });
    renderRoute("/doctor/unprocessed/12", ROUTE, <Unprocessed />);
    expect(
      await screen.findByText("未処理の記載はありません"),
    ).toBeInTheDocument();
  });

  it("受診の番号が数でなければ API を呼ばずに知らせる", () => {
    const fetchMock = mockApi({});
    renderRoute("/doctor/unprocessed/abc", ROUTE, <Unprocessed />);
    expect(screen.getByRole("alert")).toHaveTextContent("invalid_visit_id");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("取れなければ code を出す", async () => {
    mockApi({});
    renderRoute("/doctor/unprocessed/12", ROUTE, <Unprocessed />);
    expect(await screen.findByRole("alert")).toHaveTextContent("not_found");
  });

  it("401 ならログイン画面へ（元の経路つき）", async () => {
    const fetchMock = mockApi({
      "GET /api/doctor/visits/12/unprocessed": () =>
        jsonResponse({ error: "not_logged_in" }, 401),
    });
    renderRoute("/doctor/unprocessed/12", ROUTE, <Unprocessed />);
    await waitFor(() =>
      expect(screen.getByTestId("where")).toHaveTextContent(
        /^\/doctor\/login$/,
      ),
    );
    expect(screen.getByTestId("where")).toHaveAttribute(
      "data-from",
      "/doctor/unprocessed/12",
    );
    expect(countOf(fetchMock, "GET /api/doctor/visits/12/unprocessed")).toBe(1);
  });

  it.each([
    ["entries が無い", { visit: visitHeaderStub() }],
    ["visit が無い", { entries: [] }],
    [
      "要素の型が違う",
      { visit: visitHeaderStub(), entries: [{ entry_id: 1, text: 3 }] },
    ],
  ])(
    "応答が契約と違えば（%s）invalid_response（0件と言わない）",
    async (_l, b) => {
      mockApi({ "GET /api/doctor/visits/12/unprocessed": b });
      renderRoute("/doctor/unprocessed/12", ROUTE, <Unprocessed />);
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "invalid_response",
      );
      expect(screen.queryByText("未処理の記載はありません")).toBeNull();
    },
  );
});
