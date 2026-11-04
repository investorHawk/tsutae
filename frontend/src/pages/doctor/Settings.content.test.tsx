/**
 * D4 設定を変える: 医師向けの呼び名（D5-1）・依頼の前に今の中身を見せる（D5-2）・
 * 「依頼 → 差分を見る → 承認」の段階の表示（D5-3）。
 * 今の中身は実際の API の応答（fixture doctor_skill）を使う。
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { SkillContentResponse } from "../../api/types";
import {
  countOf,
  deferred,
  mockApi,
  renderRoute,
  type RouteValue,
} from "../../components/doctor/testing";
import { fixtureBody } from "../../test/apiFixtures";
import { jsonResponse } from "../../test/fetchMock";
import Settings from "./Settings";

afterEach(() => {
  vi.unstubAllGlobals();
});

const SKILLS = "GET /api/doctor/skills";
const CHANGES = "GET /api/doctor/skill-changes";
const CREATE = "POST /api/doctor/skill-changes";
const APPROVE = "POST /api/doctor/skill-changes/5/approve";
const FOLFOX = "GET /api/doctor/skills/regimen-folfox";
const REPORT = "GET /api/doctor/skills/report-format-default";
const FOLFOX_BODY = fixtureBody("doctor_skill") as SkillContentResponse;
const REPORT_BODY: SkillContentResponse = {
  name: "report-format-default",
  version: 3,
  description: "医師が決めたレポートの形式（合成）",
  questions: [],
  text: "---\nname: report-format-default\nversion: 3\n---\n\n# レポートの形式（既定）\n",
};
const DIFF =
  "--- a/SKILL.md\n+++ b/SKILL.md\n@@ -1 +1 @@\n-version: 1\n+version: 2\n";

function list(folfoxVersion = 1) {
  return {
    skills: [
      { name: "regimen-folfox", version: folfoxVersion },
      { name: "report-format-default", version: 3 },
    ],
    invalid: [],
  };
}

function api(extra: Record<string, RouteValue> = {}) {
  return mockApi({
    [SKILLS]: list(),
    [CHANGES]: { skill_changes: [] },
    [FOLFOX]: FOLFOX_BODY,
    [REPORT]: REPORT_BODY,
    ...extra,
  });
}

function renderSettings() {
  return renderRoute("/doctor/settings", "/doctor/settings", <Settings />);
}

function contentPanel() {
  return screen.findByRole("region", { name: "選んだ Skill の今の中身" });
}

function steps() {
  return within(screen.getByRole("list", { name: "手順" })).getAllByRole(
    "listitem",
  );
}

function currentStep() {
  return steps().find((li) => li.getAttribute("aria-current") === "step");
}

async function requestChange() {
  await screen.findByRole("option", { name: /FOLFOX の質問集/ });
  await userEvent.type(
    screen.getByLabelText("変えたいこと（一文）"),
    "（合成）口内炎の質問を足して",
  );
  await userEvent.click(
    screen.getByRole("button", { name: "書き換えを依頼する" }),
  );
}

describe("Settings: 医師向けの呼び名（D5-1）", () => {
  it("選択肢は呼び名と版。内部名は小さく添える", async () => {
    api();
    renderSettings();
    const option = await screen.findByRole("option", {
      name: "FOLFOX の質問集（第1版）",
    });
    expect(option).toHaveValue("regimen-folfox");
    expect(
      screen.getByRole("option", { name: "レポートの形式（第3版）" }),
    ).toHaveValue("report-format-default");
    expect(screen.queryByRole("option", { name: /version/ })).toBeNull();
    expect(
      screen.getByText("regimen-folfox", { selector: "code" }),
    ).toHaveClass("d-skill-code");
  });
});

describe("Settings: 依頼の前に今の中身を見せる（D5-2）", () => {
  it("選んだ Skill の今の質問の一覧と SKILL.md の全文", async () => {
    const fetchMock = api();
    renderSettings();
    const panel = await contentPanel();
    expect(
      within(panel).getByText("今の中身（FOLFOX の質問集・第1版）"),
    ).toBeInTheDocument();
    const questions = await within(panel).findByRole("list", {
      name: "今の質問",
    });
    const items = within(questions).getAllByRole("listitem");
    expect(items).toHaveLength(FOLFOX_BODY.questions.length);
    expect(items[1]).toHaveTextContent("下痢はありましたか");
    expect(items[1]).toHaveTextContent("3段階で答える");
    expect(items[4]).toHaveTextContent("体温を入れる");
    expect(within(panel).getByText("SKILL.md の全文")).toBeInTheDocument();
    expect(panel.querySelector("pre")).toHaveTextContent(
      "name: regimen-folfox",
    );
    expect(countOf(fetchMock, FOLFOX)).toBe(1);
  });

  it("選び直すと、その Skill の中身を取り直す（質問の無い Skill は全文だけ）", async () => {
    const fetchMock = api();
    renderSettings();
    await within(await contentPanel()).findByRole("list", { name: "今の質問" });
    await userEvent.selectOptions(
      screen.getByLabelText("Skill"),
      "report-format-default",
    );
    const panel = await contentPanel();
    expect(
      await within(panel).findByText("今の中身（レポートの形式・第3版）"),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(panel.querySelector("pre")).toHaveTextContent(
        "# レポートの形式（既定）",
      ),
    );
    expect(within(panel).queryByRole("list", { name: "今の質問" })).toBeNull();
    expect(countOf(fetchMock, REPORT)).toBe(1);
  });

  it("中身を読めなければ code を出す（依頼の入力は止めない）", async () => {
    api({ [FOLFOX]: () => jsonResponse({ error: "format" }, 409) });
    renderSettings();
    const panel = await contentPanel();
    const alert = await within(panel).findByRole("alert");
    expect(alert).toHaveTextContent("今の中身を出せません");
    expect(alert).toHaveTextContent("format");
    expect(screen.getByLabelText("変えたいこと（一文）")).toBeEnabled();
  });

  it("契約と違う中身は invalid_response（空の中身と言わない）", async () => {
    api({ [FOLFOX]: { name: "regimen-folfox", version: 1 } });
    renderSettings();
    const panel = await contentPanel();
    expect(await within(panel).findByRole("alert")).toHaveTextContent(
      "invalid_response",
    );
    expect(within(panel).queryByRole("list", { name: "今の質問" })).toBeNull();
  });

  it("承認で版が上がったら、今の中身を取り直す", async () => {
    const lists = [list(1), list(2)];
    const fetchMock = api({
      [SKILLS]: () => jsonResponse(lists.length > 1 ? lists.shift() : lists[0]),
      [CREATE]: { id: 5, status: "pending", diff: DIFF },
      [APPROVE]: { ok: true, new_version: 2 },
      [FOLFOX]: () =>
        jsonResponse({
          ...FOLFOX_BODY,
          version: countOf(fetchMock, FOLFOX) > 1 ? 2 : 1,
        }),
    });
    renderSettings();
    await requestChange();
    await userEvent.click(
      await screen.findByRole("button", { name: "承認する" }),
    );
    await waitFor(() => expect(countOf(fetchMock, FOLFOX)).toBe(2));
    expect(
      await screen.findByText("今の中身（FOLFOX の質問集・第2版）"),
    ).toBeInTheDocument();
  });
});

describe("Settings: 依頼 → 差分を見る → 承認 の段階（D5-3）", () => {
  it("入力中は「依頼を書く」が今", async () => {
    api();
    renderSettings();
    await screen.findByRole("option", { name: /FOLFOX の質問集/ });
    expect(steps().map((li) => li.textContent)).toEqual([
      expect.stringContaining("依頼を書く"),
      expect.stringContaining("差分を見る"),
      expect.stringContaining("承認して反映"),
    ]);
    expect(currentStep()).toHaveTextContent("依頼を書く");
  });

  it("生成中 → 差分の確認 → 承認 と進む", async () => {
    const pending = deferred<Response>();
    api({
      [CREATE]: () => pending.promise,
      [APPROVE]: { ok: true, new_version: 2 },
    });
    renderSettings();
    await requestChange();
    expect(currentStep()).toHaveTextContent("差分を見る");
    expect(currentStep()).toHaveTextContent("Claude が差分を作成中");
    expect(steps()[0]).toHaveClass("d-step--done");
    pending.resolve(jsonResponse({ id: 5, status: "pending", diff: DIFF }));
    await screen.findByRole("region", { name: "差分の確認" });
    expect(currentStep()).toHaveTextContent("差分を見て、承認か却下を選ぶ");
    await userEvent.click(screen.getByRole("button", { name: "承認する" }));
    await waitFor(() => expect(currentStep()).toBeUndefined());
    expect(steps()[2]).toHaveClass("d-step--done");
    expect(steps()[2]).toHaveTextContent("第2版になりました");
  });

  it("却下したら「承認して反映」で止まる", async () => {
    api({
      [CREATE]: { id: 5, status: "pending", diff: DIFF },
      "POST /api/doctor/skill-changes/5/reject": { ok: true },
    });
    renderSettings();
    await requestChange();
    await userEvent.click(
      await screen.findByRole("button", { name: "却下する" }),
    );
    await waitFor(() => expect(steps()[2]).toHaveClass("d-step--stopped"));
    expect(steps()[2]).toHaveTextContent("却下（反映しない）");
  });
});
