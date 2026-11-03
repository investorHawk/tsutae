/**
 * D5: 同じ画面のまま別の受診へ移ったとき、前の受診の状態・出来事を新しい受診の見出しの
 * 下に残さない（新しい受診の取得が 404・保留中・通信失敗でも）。
 */
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
import type { PipelineEvent } from "../../api/types";
import {
  countOf,
  deferred,
  mockApi,
  type RouteValue,
} from "../../components/doctor/testing";
import { jsonResponse } from "../../test/fetchMock";
import Pipeline from "./Pipeline";

const FIRST = "GET /api/doctor/pipeline/12/events";
const NEXT = "GET /api/doctor/pipeline/13/events";

const EVENTS: PipelineEvent[] = [
  {
    ts: "2026-11-09T10:00:00+09:00",
    event: "run_start",
    hook_name: null,
    agent_type: null,
    tool_name: null,
    decision: null,
    duration_ms: null,
  },
  {
    ts: "2026-11-09T10:00:14.250+09:00",
    event: "emit_report",
    hook_name: null,
    agent_type: null,
    tool_name: "mcp__tsutae__emit_report",
    decision: "accept",
    duration_ms: null,
  },
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

function GoTo() {
  const navigate = useNavigate();
  return (
    <button type="button" onClick={() => navigate("/doctor/pipeline/13")}>
      go
    </button>
  );
}

async function openFirstThenNext(next: RouteValue) {
  const fetchMock = mockApi({
    [FIRST]: { status: "ready", events: EVENTS },
    [NEXT]: next,
  });
  render(
    <MemoryRouter initialEntries={["/doctor/pipeline/12"]}>
      <Routes>
        <Route path="/doctor/pipeline/:visitId" element={<Pipeline />} />
      </Routes>
      <GoTo />
    </MemoryRouter>,
  );
  expect(await screen.findByText("印刷待ち")).toBeInTheDocument();
  const list = screen.getByRole("list", { name: "時系列" });
  expect(within(list).getAllByRole("listitem")).toHaveLength(EVENTS.length);
  fireEvent.click(screen.getByRole("button", { name: "go" }));
  return fetchMock;
}

function expectNothingFromFirst() {
  expect(screen.getByText("受診 #13")).toBeInTheDocument();
  expect(screen.queryByText("印刷待ち")).toBeNull();
  expect(screen.queryByRole("list", { name: "時系列" })).toBeNull();
}

describe("Pipeline の受診の切り替え", () => {
  it("移った先が 404 なら not_found だけを出し、前の受診の状態・出来事を残さない", async () => {
    const fetchMock = await openFirstThenNext(() =>
      jsonResponse({ error: "not_found" }, 404),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("not_found");
    expectNothingFromFirst();
    expect(screen.getByText("更新を止めました")).toBeInTheDocument();
    expect(countOf(fetchMock, FIRST)).toBe(1);
    expect(countOf(fetchMock, NEXT)).toBe(1);
  });

  it("移った先の取得が保留中の間は、前の受診のものを出さず更新中と出す", async () => {
    const pending = deferred<Response>();
    await openFirstThenNext(() => pending.promise);
    expectNothingFromFirst();
    expect(screen.getByText("2秒ごとに更新中")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
    await act(async () => {
      pending.resolve(jsonResponse({ status: "generating", events: [] }));
    });
    expect(await screen.findByText("生成中")).toBeInTheDocument();
  });

  it("移った先が通信の失敗でも、前の受診の状態・出来事を残さない", async () => {
    await openFirstThenNext(() => jsonResponse({ error: "server_error" }, 500));
    expect(await screen.findByRole("alert")).toHaveTextContent("server_error");
    expectNothingFromFirst();
  });

  it("前の受診の遅い応答は、移った後に返っても使わない", async () => {
    const slowFirst = deferred<Response>();
    const fetchMock = mockApi({
      [FIRST]: () => slowFirst.promise,
      [NEXT]: { status: "generating", events: [] },
    });
    render(
      <MemoryRouter initialEntries={["/doctor/pipeline/12"]}>
        <Routes>
          <Route path="/doctor/pipeline/:visitId" element={<Pipeline />} />
        </Routes>
        <GoTo />
      </MemoryRouter>,
    );
    await waitFor(() => expect(countOf(fetchMock, FIRST)).toBe(1));
    fireEvent.click(screen.getByRole("button", { name: "go" }));
    expect(await screen.findByText("生成中")).toBeInTheDocument();
    await act(async () => {
      slowFirst.resolve(jsonResponse({ status: "ready", events: EVENTS }));
    });
    expect(screen.getByText("生成中")).toBeInTheDocument();
    expectNothingFromFirst();
  });
});
