/** D4: 読み込みの失敗からの戻り、空の差分、依頼の応答の検査（W2 第2回レビュー・§9 W2b）。 */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { SkillChange } from "../../api/types";
import {
  countOf,
  mockApi,
  renderRoute,
  type RouteValue,
} from "../../components/doctor/testing";
import { jsonResponse } from "../../test/fetchMock";
import { skillContentRoutes } from "../../components/doctor/skillTesting";
import ReportFormatSettings from "./ReportFormatSettings";

afterEach(() => {
  vi.unstubAllGlobals();
});

const SKILLS = "GET /api/doctor/skills";
const CHANGES = "GET /api/doctor/skill-changes";
const CREATE = "POST /api/doctor/skill-changes";
const REQUEST = "（合成）口内炎の質問を足して";
const LOAD_ERROR = /読み込めません/;
const APPROVE = "POST /api/doctor/skill-changes/5/approve";
const REJECT = "POST /api/doctor/skill-changes/5/reject";
const DIFF =
  "--- a/SKILL.md\n+++ b/SKILL.md\n@@ -1 +1 @@\n-version: 1\n+version: 2\n";

const SKILL_LIST = {
  skills: [{ name: "report-format-default", version: 1 }],
  invalid: [],
};

function change(patch: Partial<SkillChange>): SkillChange {
  return {
    id: 5,
    skill_name: "report-format-default",
    requested_text: REQUEST,
    diff: "",
    status: "pending",
    base_version: 1,
    new_version: null,
    error_code: null,
    created_at: "2026-11-09T10:00:00+09:00",
    decided_at: null,
    ...patch,
  };
}

function api(extra: Record<string, RouteValue> = {}) {
  return mockApi({
    ...skillContentRoutes(["report-format-default"]),
    [SKILLS]: SKILL_LIST,
    [CHANGES]: { skill_changes: [] },
    ...extra,
  });
}

function renderSettings() {
  return renderRoute(
    "/doctor/settings",
    "/doctor/settings",
    <ReportFormatSettings />,
  );
}

async function requestChange() {
  await screen.findByRole("option", { name: /レポートの形式（第/ });
  await userEvent.type(screen.getByLabelText("変えたいこと（一文）"), REQUEST);
  await userEvent.click(
    screen.getByRole("button", { name: "書き換えを依頼する" }),
  );
}

describe("Settings: 読み込みの失敗からの戻り", () => {
  it("履歴の読み込みが失敗しても、読み直しに成功すれば「読み込めません」は消える", async () => {
    const replies = [
      () => jsonResponse({ error: "boom" }, 500),
      () => jsonResponse({ skill_changes: [] }),
    ];
    api({
      [CHANGES]: () => (replies.shift() ?? replies[0]!)(),
      [CREATE]: { id: 5, status: "failed", diff: null },
    });
    renderSettings();
    expect(await screen.findByText(LOAD_ERROR)).toBeInTheDocument();
    await requestChange();
    expect(
      await screen.findByText("変更の履歴はまだありません"),
    ).toBeInTheDocument();
    expect(screen.queryByText(LOAD_ERROR)).toBeNull();
  });

  it("Skill 一覧の失敗は、履歴の読み直しの成功では消えない", async () => {
    api({
      [SKILLS]: () => jsonResponse({ error: "boom" }, 500),
    });
    renderSettings();
    expect(await screen.findByText(LOAD_ERROR)).toBeInTheDocument();
    expect(
      await screen.findByText("変更の履歴はまだありません"),
    ).toBeInTheDocument();
    expect(screen.getByText(LOAD_ERROR)).toHaveTextContent("boom");
  });
});

describe("Settings: 空の差分は失敗", () => {
  it.each([
    ["空", ""],
    ["空白だけ", " \n\t\n"],
  ])(
    "依頼の応答の diff が%sなら失敗として出し、承認させない",
    async (_l, diff) => {
      api({ [CREATE]: { id: 5, status: "pending", diff } });
      renderSettings();
      await requestChange();
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "書き換えに失敗しました",
      );
      expect(screen.queryByRole("button", { name: "承認する" })).toBeNull();
    },
  );

  it("履歴の承認待ちでも diff が空なら「確認する」を出さない", async () => {
    api({
      [CHANGES]: {
        skill_changes: [
          change({ id: 7, diff: "" }),
          change({ id: 8, diff: null }),
        ],
      },
    });
    renderSettings();
    await screen.findByRole("table", { name: "変更の履歴" });
    expect(screen.queryByRole("button", { name: "確認する" })).toBeNull();
  });
});

describe("Settings: 依頼の応答の検査", () => {
  it.each([
    ["本文が空", {}],
    ["status が未知", { id: 5, status: "done", diff: "x" }],
    ["id が文字列", { id: "5", status: "pending", diff: "x" }],
  ])("%s なら invalid_response を出し、承認させない", async (_l, body) => {
    const fetchMock = api({ [CREATE]: body });
    renderSettings();
    await requestChange();
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("invalid_response"),
    );
    expect(screen.queryByRole("button", { name: "承認する" })).toBeNull();
    expect(countOf(fetchMock, CREATE)).toBe(1);
  });
});

describe("Settings: 承認・却下の応答を失ったとき", () => {
  /** 履歴の応答を順に返す（最後のものを繰り返す）。 */
  function historyReplies(...lists: SkillChange[][]) {
    return () =>
      jsonResponse({
        skill_changes: lists.length > 1 ? lists.shift() : lists[0],
      });
  }

  const networkFailure = () => Promise.reject(new TypeError("Failed to fetch"));

  async function openReview() {
    await requestChange();
    await screen.findByRole("region", { name: "差分" });
  }

  it("承認が通信の失敗でも、履歴で approved なら「承認しました（version 2）」", async () => {
    const decided = change({
      status: "approved",
      diff: DIFF,
      new_version: 2,
      decided_at: "2026-11-09T10:05:00+09:00",
    });
    const fetchMock = api({
      [CREATE]: { id: 5, status: "pending", diff: DIFF },
      [CHANGES]: historyReplies([], [], [decided]),
      [APPROVE]: networkFailure,
    });
    renderSettings();
    await openReview();
    await userEvent.click(screen.getByRole("button", { name: "承認する" }));
    const status = await screen.findByText(/version 2/);
    expect(status).toHaveTextContent("承認しました");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByRole("region", { name: "差分" })).toBeNull();
    expect(countOf(fetchMock, APPROVE)).toBe(1);
    // 済んだので Skill の一覧も取り直す
    await waitFor(() => expect(countOf(fetchMock, SKILLS)).toBe(2));
  });

  it("却下が 409 not_pending でも、履歴で rejected なら「変わっていません」", async () => {
    const decided = change({ status: "rejected", diff: DIFF });
    api({
      [CREATE]: { id: 5, status: "pending", diff: DIFF },
      [CHANGES]: historyReplies([], [], [decided]),
      [REJECT]: () => jsonResponse({ error: "not_pending" }, 409),
    });
    renderSettings();
    await openReview();
    await userEvent.click(screen.getByRole("button", { name: "却下する" }));
    expect(await screen.findByText(/変わっていません/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("承認が通信の失敗で、履歴でまだ pending ならエラーを出し、もう一度押せる", async () => {
    let fail = true;
    const fetchMock = api({
      [CREATE]: { id: 5, status: "pending", diff: DIFF },
      [CHANGES]: historyReplies([], [], [change({ diff: DIFF })]),
      [APPROVE]: () =>
        fail ? networkFailure() : jsonResponse({ ok: true, new_version: 2 }),
    });
    renderSettings();
    await openReview();
    const before = countOf(fetchMock, CHANGES);
    await userEvent.click(screen.getByRole("button", { name: "承認する" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("network_error");
    expect(countOf(fetchMock, CHANGES)).toBe(before + 1);
    expect(screen.getByRole("region", { name: "差分" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "承認する" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "却下する" })).toBeEnabled();
    fail = false;
    await userEvent.click(screen.getByRole("button", { name: "承認する" }));
    expect(await screen.findByText(/version 2/)).toBeInTheDocument();
  });

  it("履歴の取り直しも失敗したら、元のエラーを出して確認画面に残る", async () => {
    api({
      [CREATE]: { id: 5, status: "pending", diff: DIFF },
      [CHANGES]: (() => {
        let n = 0;
        return () => {
          n += 1;
          return n <= 2
            ? jsonResponse({ skill_changes: [] })
            : jsonResponse({ error: "boom" }, 500);
        };
      })(),
      [APPROVE]: networkFailure,
    });
    renderSettings();
    await openReview();
    await userEvent.click(screen.getByRole("button", { name: "承認する" }));
    await waitFor(() =>
      expect(
        screen
          .getAllByRole("alert")
          .some((a) => a.textContent?.includes("network_error")),
      ).toBe(true),
    );
    expect(screen.getByRole("button", { name: "承認する" })).toBeEnabled();
  });

  it("409 busy は履歴を取り直さず、確認画面のまま", async () => {
    const fetchMock = api({
      [CREATE]: { id: 5, status: "pending", diff: DIFF },
      [APPROVE]: () => jsonResponse({ error: "busy" }, 409),
    });
    renderSettings();
    await openReview();
    await waitFor(() => expect(countOf(fetchMock, CHANGES)).toBe(2));
    await userEvent.click(screen.getByRole("button", { name: "承認する" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("busy");
    expect(countOf(fetchMock, CHANGES)).toBe(2);
    expect(screen.getByRole("button", { name: "承認する" })).toBeEnabled();
  });
});
