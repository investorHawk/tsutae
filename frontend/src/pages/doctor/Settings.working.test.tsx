/**
 * D4: 作業中（pending で diff の無い）の変更がある間は「生成中」と出してフォームを止め、
 * 履歴を数秒ごとに取り直す。終わったら差分の確認（失敗ならその code）に進む。
 */
import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SkillChange } from "../../api/types";
import {
  countOf,
  deferred,
  mockApi,
  renderRoute,
  type RouteValue,
} from "../../components/doctor/testing";
import { SKILL_HISTORY_POLL_MS } from "../../components/doctor/useSkillChangeWatch";
import { jsonResponse } from "../../test/fetchMock";
import { skillContentRoutes } from "../../components/doctor/skillTesting";
import ReportFormatSettings from "./ReportFormatSettings";

const SKILLS = "GET /api/doctor/skills";
const CHANGES = "GET /api/doctor/skill-changes";
const CREATE = "POST /api/doctor/skill-changes";
const REQUEST = "口内炎は、食事がとれたかも次から聞いて";
const DIFF = [
  "--- a/report-format-default/SKILL.md",
  "+++ b/report-format-default/SKILL.md",
  "@@ -1,2 +1,2 @@",
  "-version: 1",
  "+version: 2",
].join("\n");
const NOW = new Date("2026-11-09T10:00:30+09:00");

function change(patch: Partial<SkillChange>): SkillChange {
  return {
    id: 5,
    skill_name: "report-format-default",
    requested_text: REQUEST,
    diff: null,
    status: "pending",
    base_version: 1,
    new_version: null,
    error_code: null,
    created_at: "2026-11-09T10:00:00+09:00",
    decided_at: null,
    ...patch,
  };
}

const SKILL_LIST = {
  skills: [{ name: "report-format-default", version: 1 }],
  invalid: [],
};

function api(
  changes: () => SkillChange[],
  extra: Record<string, RouteValue> = {},
) {
  return mockApi({
    ...skillContentRoutes(["report-format-default"]),
    [SKILLS]: SKILL_LIST,
    [CHANGES]: () => jsonResponse({ skill_changes: changes() }),
    ...extra,
  });
}

beforeEach(() => {
  vi.useFakeTimers({
    toFake: [
      "setTimeout",
      "clearTimeout",
      "setInterval",
      "clearInterval",
      "Date",
    ],
    shouldAdvanceTime: true,
  });
  vi.setSystemTime(NOW);
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

function renderSettings() {
  return renderRoute(
    "/doctor/settings",
    "/doctor/settings",
    <ReportFormatSettings />,
  );
}

function historyRow(id: number): HTMLElement {
  const table = screen.getByRole("table", { name: "変更の履歴" });
  const cell = within(table).getByText(`#${id}`);
  const row = cell.closest("tr");
  if (!row) {
    throw new Error("行が無い");
  }
  return row;
}

describe("Settings: 作業中の変更", () => {
  it("開いた時に作業中があれば生成中（経過秒）・フォームを止め、終われば差分の確認へ", async () => {
    let rows = [change({})];
    const fetchMock = api(() => rows);
    renderSettings();
    const note = await screen.findByRole("status");
    expect(note).toHaveTextContent("生成中");
    expect(note).toHaveTextContent(
      "数分かかることがあります。この画面のままお待ちください",
    );
    expect(note).toHaveTextContent("経過 30 秒");
    expect(screen.getByLabelText("変えたいこと（一文）")).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "書き換えを依頼する" }),
    ).toBeDisabled();
    expect(within(historyRow(5)).getByText("生成中")).toBeInTheDocument();
    expect(within(historyRow(5)).queryByText("承認待ち")).toBeNull();

    expect(countOf(fetchMock, CHANGES)).toBe(1);
    await advance(SKILL_HISTORY_POLL_MS);
    expect(countOf(fetchMock, CHANGES)).toBe(2);
    expect(screen.getByRole("status")).toHaveTextContent("経過 33 秒");

    rows = [change({ diff: DIFF })];
    await advance(SKILL_HISTORY_POLL_MS);
    expect(
      await screen.findByRole("region", { name: "差分の確認" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "承認する" })).toBeEnabled();
    await advance(SKILL_HISTORY_POLL_MS * 3);
    expect(countOf(fetchMock, CHANGES)).toBe(3);
  });

  it("作業中が失敗（取り残し）になったら、その code を出してフォームを戻す", async () => {
    let rows = [change({})];
    api(() => rows);
    renderSettings();
    await screen.findByText(/経過 30 秒/);
    rows = [change({ status: "failed", error_code: "stale_request" })];
    await advance(SKILL_HISTORY_POLL_MS);
    expect(await screen.findByRole("alert")).toHaveTextContent("stale_request");
    expect(screen.getByLabelText("変えたいこと（一文）")).toBeEnabled();
  });

  it("作業中が無ければ履歴を取り直さない", async () => {
    const fetchMock = api(() => [change({ diff: DIFF })]);
    renderSettings();
    await screen.findByRole("table", { name: "変更の履歴" });
    await advance(SKILL_HISTORY_POLL_MS * 4);
    expect(countOf(fetchMock, CHANGES)).toBe(1);
  });

  it("自分の依頼の生成中も経過秒と待ち時間の案内を出す", async () => {
    const pending = deferred<Response>();
    api(() => [], { [CREATE]: () => pending.promise });
    renderSettings();
    const u = user();
    await screen.findByRole("option", { name: /レポートの形式（第/ });
    await u.type(screen.getByLabelText("変えたいこと（一文）"), REQUEST);
    await u.click(screen.getByRole("button", { name: "書き換えを依頼する" }));
    const note = screen.getByRole("status");
    expect(note).toHaveTextContent(
      "数分かかることがあります。この画面のままお待ちください",
    );
    expect(note).toHaveTextContent("経過 0 秒");
    await advance(5000);
    expect(screen.getByRole("status")).toHaveTextContent("経過 5 秒");
    await act(async () => {
      pending.resolve(jsonResponse({ id: 6, status: "pending", diff: DIFF }));
    });
    expect(
      await screen.findByRole("region", { name: "差分の確認" }),
    ).toBeInTheDocument();
  });

  it("依頼が 409 busy（ほかの依頼が作業中）なら、その作業中を見張る", async () => {
    let rows: SkillChange[] = [];
    const fetchMock = api(() => rows, {
      [CREATE]: () => {
        rows = [change({ id: 9 })];
        return jsonResponse({ error: "busy" }, 409);
      },
    });
    renderSettings();
    const u = user();
    await screen.findByRole("option", { name: /レポートの形式（第/ });
    await u.type(screen.getByLabelText("変えたいこと（一文）"), REQUEST);
    await u.click(screen.getByRole("button", { name: "書き換えを依頼する" }));
    expect(await screen.findByText(/経過 30 秒/)).toBeInTheDocument();
    expect(within(historyRow(9)).getByText("生成中")).toBeInTheDocument();
    const before = countOf(fetchMock, CHANGES);
    await advance(SKILL_HISTORY_POLL_MS);
    expect(countOf(fetchMock, CHANGES)).toBe(before + 1);
  });
});
