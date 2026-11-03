import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { SkillChange } from "../../api/types";
import {
  bodiesOf,
  countOf,
  deferred,
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
const REQUEST = "口内炎は、食事がとれたかも次から聞いて";

const DIFF = [
  "--- a/regimen-folfox/SKILL.md",
  "+++ b/regimen-folfox/SKILL.md",
  "@@ -1,3 +1,4 @@",
  "-version: 1",
  "+version: 2",
  "+  - {key: stomatitis_meal, text: 食事はとれましたか, answer_type: three_level}",
  " regimen: FOLFOX",
].join("\n");

function change(patch: Partial<SkillChange>): SkillChange {
  return {
    id: 5,
    skill_name: "regimen-folfox",
    requested_text: REQUEST,
    diff: DIFF,
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
  skills: [
    { name: "regimen-folfox", version: 1 },
    { name: "report-format-default", version: 3 },
  ],
  invalid: [],
};

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

async function requestChange(text = REQUEST) {
  await screen.findByRole("option", { name: /regimen-folfox/ });
  await userEvent.type(screen.getByLabelText("変えたいこと（一文）"), text);
  await userEvent.click(
    screen.getByRole("button", { name: "書き換えを依頼する" }),
  );
}

describe("Settings（D4 設定を変える）", () => {
  it("Skill の一覧から選べる（版つき）", async () => {
    api();
    renderSettings();
    expect(
      screen.getByRole("heading", { level: 1, name: "設定を変える" }),
    ).toBeInTheDocument();
    const select = screen.getByLabelText("Skill");
    await screen.findByRole("option", { name: "regimen-folfox（version 1）" });
    expect(select).toHaveValue("regimen-folfox");
    await userEvent.selectOptions(select, "report-format-default");
    expect(select).toHaveValue("report-format-default");
  });

  it("一文が空なら依頼できない", async () => {
    api();
    renderSettings();
    await screen.findByRole("option", { name: /regimen-folfox/ });
    expect(
      screen.getByRole("button", { name: "書き換えを依頼する" }),
    ).toBeDisabled();
    await userEvent.type(screen.getByLabelText("変えたいこと（一文）"), "  ");
    expect(
      screen.getByRole("button", { name: "書き換えを依頼する" }),
    ).toBeDisabled();
  });

  it("「例を入れる」で例文が入る", async () => {
    api();
    renderSettings();
    await userEvent.click(screen.getByRole("button", { name: "例を入れる" }));
    expect(screen.getByLabelText("変えたいこと（一文）")).toHaveValue(REQUEST);
  });

  it("依頼 → 生成中 → 差分を色分けで表示", async () => {
    const pending = deferred<Response>();
    const fetchMock = api({ [CREATE]: () => pending.promise });
    renderSettings();
    await requestChange();
    expect(bodiesOf(fetchMock, CREATE)).toEqual([
      { skill_name: "regimen-folfox", request_text: REQUEST },
    ]);
    expect(screen.getByRole("status")).toHaveTextContent("生成中");
    expect(
      screen.getByRole("button", { name: "書き換えを依頼する" }),
    ).toBeDisabled();
    pending.resolve(jsonResponse({ id: 5, status: "pending", diff: DIFF }));
    const region = await screen.findByRole("region", { name: "差分" });
    expect(within(region).getByText("+version: 2")).toHaveClass("d-diff-add");
    expect(within(region).getByText("-version: 1")).toHaveClass("d-diff-del");
    expect(screen.getByRole("button", { name: "承認する" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "却下する" })).toBeEnabled();
  });

  it("承認で新しい version と「翌日の記録から反映されます」、一覧を取り直す", async () => {
    const fetchMock = api({
      [CREATE]: { id: 5, status: "pending", diff: DIFF },
      "POST /api/doctor/skill-changes/5/approve": { ok: true, new_version: 2 },
    });
    renderSettings();
    await requestChange();
    const approve = await screen.findByRole("button", { name: "承認する" });
    const historyBefore = countOf(fetchMock, CHANGES);
    await userEvent.click(approve);
    expect(countOf(fetchMock, "POST /api/doctor/skill-changes/5/approve")).toBe(
      1,
    );
    const status = await screen.findByText(/version 2/);
    expect(status).toHaveTextContent("翌日の記録から反映されます");
    expect(status).toHaveTextContent("regimen-folfox");
    await waitFor(() => expect(countOf(fetchMock, SKILLS)).toBe(2));
    expect(countOf(fetchMock, CHANGES)).toBe(historyBefore + 1);
    expect(screen.queryByRole("region", { name: "差分" })).toBeNull();
  });

  it("却下で「変わっていません」", async () => {
    const fetchMock = api({
      [CREATE]: { id: 5, status: "pending", diff: DIFF },
      "POST /api/doctor/skill-changes/5/reject": { ok: true },
    });
    renderSettings();
    await requestChange();
    await userEvent.click(
      await screen.findByRole("button", { name: "却下する" }),
    );
    expect(countOf(fetchMock, "POST /api/doctor/skill-changes/5/reject")).toBe(
      1,
    );
    expect(await screen.findByText(/変わっていません/)).toBeInTheDocument();
    expect(countOf(fetchMock, "POST /api/doctor/skill-changes/5/approve")).toBe(
      0,
    );
  });

  it("書き換えが失敗したら履歴の error_code を出す", async () => {
    const lists = [
      [],
      [change({ status: "failed", diff: null, error_code: "schema" })],
    ];
    api({
      [CREATE]: { id: 5, status: "failed", diff: null },
      [CHANGES]: () => jsonResponse({ skill_changes: lists.shift() ?? [] }),
    });
    renderSettings();
    await requestChange();
    const alert = await screen.findByRole("alert");
    await waitFor(() => expect(alert).toHaveTextContent("schema"));
    expect(alert).toHaveTextContent("書き換えに失敗しました");
    expect(screen.queryByRole("button", { name: "承認する" })).toBeNull();
  });

  it("依頼そのものが失敗したら code を出し、入力に戻れる", async () => {
    api({
      [CREATE]: () => jsonResponse({ error: "unknown_skill" }, 400),
    });
    renderSettings();
    await requestChange();
    expect(await screen.findByRole("alert")).toHaveTextContent("unknown_skill");
    expect(
      screen.getByRole("button", { name: "書き換えを依頼する" }),
    ).toBeEnabled();
  });

  it("承認できなければ code を出し、差分は残す", async () => {
    api({
      [CREATE]: { id: 5, status: "pending", diff: DIFF },
      "POST /api/doctor/skill-changes/5/approve": () =>
        jsonResponse({ error: "stale_base" }, 409),
    });
    renderSettings();
    await requestChange();
    await userEvent.click(
      await screen.findByRole("button", { name: "承認する" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("stale_base");
    expect(screen.getByRole("region", { name: "差分" })).toBeInTheDocument();
  });

  it.each([
    ["承認する", "approve", { ok: false }],
    ["承認する", "approve", {}],
    ["承認する", "approve", { ok: true, new_version: "2" }],
    ["却下する", "reject", { ok: false }],
    ["却下する", "reject", {}],
  ])(
    "「%s」（%s）の応答が %j でも済んだとしない（差分を残し invalid_response）",
    async (button, path, body) => {
      api({
        [CREATE]: { id: 5, status: "pending", diff: DIFF },
        [`POST /api/doctor/skill-changes/5/${path}`]: body,
      });
      renderSettings();
      await requestChange();
      await userEvent.click(
        await screen.findByRole("button", { name: button }),
      );
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "invalid_response",
      );
      expect(screen.getByRole("region", { name: "差分" })).toBeInTheDocument();
      // 済んだ表示に移らず、もう一度押せる（review に留まる）
      expect(screen.getByRole("button", { name: "承認する" })).toBeEnabled();
      expect(screen.getByRole("button", { name: "却下する" })).toBeEnabled();
    },
  );

  it("履歴: 依頼文・状態・版を並べ、承認待ちは確認から差分を開ける", async () => {
    api({
      [CHANGES]: {
        skill_changes: [
          change({ id: 3, status: "approved", new_version: 2 }),
          change({
            id: 4,
            status: "rejected",
            requested_text: "（合成）却下の例",
          }),
          change({
            id: 6,
            status: "pending",
            requested_text: "（合成）保留中",
          }),
        ],
      },
    });
    renderSettings();
    const table = await screen.findByRole("table", { name: "変更の履歴" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows.map((r) => r.querySelector("td")?.textContent)).toEqual([
      "#6",
      "#4",
      "#3",
    ]);
    expect(within(rows[2]).getByText("承認")).toBeInTheDocument();
    expect(within(rows[2]).getByText("1 → 2")).toBeInTheDocument();
    expect(within(rows[1]).getByText("却下")).toBeInTheDocument();
    expect(within(rows[0]).getByText("承認待ち")).toBeInTheDocument();
    await userEvent.click(
      within(rows[0]).getByRole("button", { name: "確認する" }),
    );
    expect(
      await screen.findByRole("region", { name: "差分" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "承認する" })).toBeEnabled();
  });

  it("履歴が空ならその旨", async () => {
    api();
    renderSettings();
    expect(
      await screen.findByText("変更の履歴はまだありません"),
    ).toBeInTheDocument();
  });

  it.each([
    ["skill_changes が無い", { ok: true }],
    ["要素の型が違う", { skill_changes: [{ id: "1" }] }],
  ])(
    "履歴の応答が契約と違えば（%s）invalid_response（空と言わない）",
    async (_l, b) => {
      api({ [CHANGES]: b });
      renderSettings();
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "invalid_response",
      );
      expect(screen.queryByText("変更の履歴はまだありません")).toBeNull();
    },
  );

  it("Skill 一覧の応答が契約と違えば invalid_response", async () => {
    api({ [SKILLS]: { skills: [{ name: "regimen-folfox" }], invalid: [] } });
    renderSettings();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "invalid_response",
    );
  });
});
