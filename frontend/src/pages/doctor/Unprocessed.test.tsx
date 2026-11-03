import { screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { countOf, mockApi, renderRoute } from "../../components/doctor/testing";
import { jsonResponse } from "../../test/fetchMock";
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
        entries: [
          {
            entry_id: 31,
            record_date: "2026-11-03",
            reason: "unknown_before_honorific",
            text: RAW,
          },
        ],
      },
    });
    renderRoute("/doctor/unprocessed/12", ROUTE, <Unprocessed />);
    expect(
      screen.getByRole("heading", { level: 1, name: "未処理の記載" }),
    ).toBeInTheDocument();
    expect(await screen.findByText(RAW)).toHaveClass("d-raw");
    expect(screen.getByText(/2026-11-03/)).toBeInTheDocument();
    expect(screen.getByText(/unknown_before_honorific/)).toBeInTheDocument();
    expect(screen.getByText(/敬称の前/)).toBeInTheDocument();
  });

  it("「紙には載りません」の注記がある", async () => {
    mockApi({ "GET /api/doctor/visits/12/unprocessed": { entries: [] } });
    renderRoute("/doctor/unprocessed/12", ROUTE, <Unprocessed />);
    expect(screen.getByText(/紙には載りません/)).toBeInTheDocument();
    await screen.findByText("未処理の記載はありません");
  });

  it("0件なら「ありません」", async () => {
    mockApi({ "GET /api/doctor/visits/12/unprocessed": { entries: [] } });
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
    ["entries が無い", { ok: true }],
    ["要素の型が違う", { entries: [{ entry_id: 1, text: 3 }] }],
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
