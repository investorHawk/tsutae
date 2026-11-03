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
import Settings from "./Settings";

afterEach(() => {
  vi.unstubAllGlobals();
});

const SKILLS = "GET /api/doctor/skills";
const CHANGES = "GET /api/doctor/skill-changes";
const CREATE = "POST /api/doctor/skill-changes";
const REQUEST = "（合成）口内炎の質問を足して";
const LOAD_ERROR = /読み込めません/;

const SKILL_LIST = { skills: [{ name: "regimen-folfox", version: 1 }] };

function change(patch: Partial<SkillChange>): SkillChange {
  return {
    id: 5,
    skill_name: "regimen-folfox",
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
    [SKILLS]: SKILL_LIST,
    [CHANGES]: { skill_changes: [] },
    ...extra,
  });
}

function renderSettings() {
  return renderRoute("/doctor/settings", "/doctor/settings", <Settings />);
}

async function requestChange() {
  await screen.findByRole("option", { name: /regimen-folfox/ });
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
