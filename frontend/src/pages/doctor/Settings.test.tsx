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
import { skillContentRoutes } from "../../components/doctor/skillTesting";
import ReportFormatSettings from "./ReportFormatSettings";

afterEach(() => {
  vi.unstubAllGlobals();
});

const SKILLS = "GET /api/doctor/skills";
const CHANGES = "GET /api/doctor/skill-changes";
const CREATE = "POST /api/doctor/skill-changes";
const REQUEST = "口内炎は、食事がとれたかも次から聞いて";
const SKILL = "report-format-default";

const DIFF = [
  "--- a/report-format-default/SKILL.md",
  "+++ b/report-format-default/SKILL.md",
  "@@ -1,3 +1,4 @@",
  "-version: 1",
  "+version: 2",
  "+low_confidence_threshold: 0.6",
  " name: report-format-default",
].join("\n");

function change(patch: Partial<SkillChange>): SkillChange {
  return {
    id: 5,
    skill_name: SKILL,
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
    // レジメンは一覧に来ても選べない（D4 レジメンの画面で直す）
    { name: "regimen-folfox", version: 1 },
    { name: "report-format-default", version: 1 },
    { name: "report-format-short", version: 3 },
  ],
  invalid: [],
};

function api(extra: Record<string, RouteValue> = {}) {
  return mockApi({
    ...skillContentRoutes(["report-format-default", "report-format-short"]),
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

async function requestChange(text = REQUEST) {
  await screen.findByRole("option", { name: /レポートの形式（第/ });
  await userEvent.type(screen.getByLabelText("変えたいこと（一文）"), text);
  await userEvent.click(
    screen.getByRole("button", { name: "書き換えを依頼する" }),
  );
}

describe("ReportFormatSettings（D4 レポートの形式）", () => {
  it("report-format の一覧から選べる（版つき。初めは report-format-default。レジメンは出さない）", async () => {
    api();
    renderSettings();
    const select = screen.getByLabelText("Skill");
    await screen.findByRole("option", {
      name: "レポートの形式（第1版）",
    });
    expect(select).toHaveValue("report-format-default");
    expect(within(select).getAllByRole("option")).toHaveLength(2);
    expect(screen.queryByRole("option", { name: /FOLFOX/ })).toBeNull();
    await userEvent.selectOptions(select, "report-format-short");
    expect(select).toHaveValue("report-format-short");
  });

  it("一文が空なら依頼できない", async () => {
    api();
    renderSettings();
    await screen.findByRole("option", { name: /レポートの形式（第/ });
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
      { skill_name: SKILL, request_text: REQUEST },
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

  it("承認で新しい version と「次の記録から反映されます」、一覧を取り直す", async () => {
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
    expect(status).toHaveTextContent("次の記録から反映されます");
    expect(status).toHaveTextContent(SKILL);
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

  it("履歴: T95 より前のレジメンの承認待ちは「確認する」を出さず、レジメンの画面へ案内する", async () => {
    api({
      [CHANGES]: {
        skill_changes: [
          change({
            id: 7,
            status: "pending",
            skill_name: "regimen-folfox",
            requested_text: "（合成）レジメンの例",
          }),
        ],
      },
    });
    renderSettings();
    const table = await screen.findByRole("table", { name: "変更の履歴" });
    const row = within(table).getAllByRole("row")[1];
    expect(within(row).queryByRole("button", { name: "確認する" })).toBeNull();
    expect(
      within(row).getByText(/レジメンは「レジメン」のタブで直します/),
    ).toBeInTheDocument();
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
    api({ [SKILLS]: { skills: [{ name: SKILL }], invalid: [] } });
    renderSettings();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "invalid_response",
    );
  });
});
