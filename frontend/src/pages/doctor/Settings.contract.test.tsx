/**
 * D4 設定を変える: 実際の API の応答（src/test/fixtures/api）で、W3 後の決定を確かめる。
 * - GET skills の invalid（読めない Skill）を表示する
 * - 承認・却下の 409 busy は確認画面のまま説明を出し、もう一度押せる
 * - approve の new_version（必須）をそのまま出す
 */
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  bodiesOf,
  mockApi,
  renderRoute,
  type RouteValue,
} from "../../components/doctor/testing";
import { apiFixture, fixtureBody } from "../../test/apiFixtures";
import { jsonResponse } from "../../test/fetchMock";
import { skillContentRoutes } from "../../components/doctor/skillTesting";
import Settings from "./Settings";

afterEach(() => {
  vi.unstubAllGlobals();
});

const SKILLS = "GET /api/doctor/skills";
const CHANGES = "GET /api/doctor/skill-changes";
const CREATE = "POST /api/doctor/skill-changes";
const CREATED = fixtureBody("doctor_skill_change_create") as { id: number };
const APPROVE = `POST /api/doctor/skill-changes/${CREATED.id}/approve`;
const REJECT = `POST /api/doctor/skill-changes/${CREATED.id}/reject`;

/** fixture の status と body をそのまま返す応答。 */
function replay(name: string): Response {
  const fixture = apiFixture(name);
  return jsonResponse(structuredClone(fixture.body), fixture.status);
}

/** 呼ばれるたびに names の次の fixture を返す（最後は繰り返す）。 */
function sequence(...names: string[]): RouteValue {
  const queue = [...names];
  return () =>
    replay(
      queue.length > 1 ? (queue.shift() as string) : names[names.length - 1],
    );
}

function api(extra: Record<string, RouteValue> = {}) {
  return mockApi({
    ...skillContentRoutes([
      "regimen-capox",
      "regimen-folfox",
      "report-format-default",
    ]),
    [SKILLS]: fixtureBody("doctor_skills") as object,
    [CHANGES]: { skill_changes: [] },
    [CREATE]: () => replay("doctor_skill_change_create"),
    ...extra,
  });
}

function renderSettings() {
  return renderRoute("/doctor/settings", "/doctor/settings", <Settings />);
}

async function openReview() {
  await screen.findByRole("option", { name: /FOLFOX の質問集/ });
  // fixture の一覧は名前順（regimen-capox が先）。依頼の fixture と同じ Skill を選ぶ
  await userEvent.selectOptions(screen.getByRole("combobox"), "regimen-folfox");
  await userEvent.type(
    screen.getByLabelText("変えたいこと（一文）"),
    "口内炎の質問で食事がとれたかも聞いて",
  );
  await userEvent.click(
    screen.getByRole("button", { name: "書き換えを依頼する" }),
  );
  return screen.findByRole("region", { name: "差分の確認" });
}

describe("Settings: 読めない Skill（GET skills の invalid）", () => {
  it("invalid が空なら何も出さない", async () => {
    api();
    renderSettings();
    await screen.findByRole("option", { name: /FOLFOX の質問集/ });
    expect(screen.queryByRole("alert", { name: "読めない Skill" })).toBeNull();
  });

  it("実際の応答の invalid（任意の Skill）を名前と code で出す", async () => {
    api({ [SKILLS]: fixtureBody("doctor_skills_invalid") as object });
    renderSettings();
    const note = await screen.findByRole("alert", { name: "読めない Skill" });
    expect(note).toHaveTextContent("読めない Skill が 1 件あります");
    expect(note).toHaveTextContent("regimen-extra");
    expect(note).toHaveTextContent("frontmatter の項目が合いません");
    expect(note).toHaveTextContent("schema");
    expect(within(note).queryByText("必須")).toBeNull();
    // 読める Skill は今までどおり選べる（読めない Skill は選択肢に出さない）
    expect(
      screen.getByRole("option", { name: /FOLFOX の質問集/ }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /EXTRA の質問集/ })).toBeNull();
  });

  it("必須の Skill が読めなければ「必須」と、記録・レポートが作れない旨を出す", async () => {
    api({
      [SKILLS]: {
        skills: [{ name: "regimen-capox", version: 1 }],
        invalid: [
          { name: "regimen-extra", error_code: "schema", required: false },
          { name: "regimen-folfox", error_code: "format", required: true },
          {
            name: "report-format-default",
            error_code: "missing",
            required: true,
          },
        ],
      },
    });
    renderSettings();
    const note = await screen.findByRole("alert", { name: "読めない Skill" });
    expect(note).toHaveTextContent("読めない Skill が 3 件あります");
    expect(note).toHaveTextContent("必須の Skill が直るまで");
    const items = within(note).getAllByRole("listitem");
    // 必須を先に、名前順
    expect(items.map((li) => li.textContent)).toEqual([
      expect.stringContaining("regimen-folfox"),
      expect.stringContaining("report-format-default"),
      expect.stringContaining("regimen-extra"),
    ]);
    expect(within(items[0]).getByText("必須")).toBeInTheDocument();
    expect(items[1]).toHaveTextContent("SKILL.md がありません");
    expect(within(items[2]).queryByText("必須")).toBeNull();
  });

  it("invalid の無い応答は契約違反（invalid_response）として出す", async () => {
    api({ [SKILLS]: { skills: [{ name: "regimen-folfox", version: 1 }] } });
    renderSettings();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "invalid_response",
    );
  });
});

describe("Settings: 承認・却下の 409 busy", () => {
  it("承認が busy なら確認画面のまま説明を出し、押し直して承認できる", async () => {
    const fetchMock = api({
      [APPROVE]: sequence(
        "doctor_skill_change_approve_busy",
        "doctor_skill_change_approve",
      ),
    });
    renderSettings();
    const review = await openReview();
    expect(bodiesOf(fetchMock, CREATE)).toEqual([
      apiFixture("doctor_skill_change_create").request,
    ]);
    await userEvent.click(
      within(review).getByRole("button", { name: "承認する" }),
    );
    const alert = await within(review).findByRole("alert");
    expect(alert).toHaveTextContent("ほかの書き換え・承認・却下を処理中です");
    expect(alert).toHaveTextContent("busy");
    const again = within(review).getByRole("button", { name: "承認する" });
    expect(again).toBeEnabled();
    await userEvent.click(again);
    const done = await screen.findByText(/第2版（version 2）になりました/);
    expect(done).toHaveTextContent("regimen-folfox");
    expect(screen.queryByRole("region", { name: "差分の確認" })).toBeNull();
  });

  it("却下が busy なら確認画面のまま説明を出し、押し直して却下できる", async () => {
    api({
      [REJECT]: sequence(
        "doctor_skill_change_reject_busy",
        "doctor_skill_change_reject",
      ),
    });
    renderSettings();
    const review = await openReview();
    await userEvent.click(
      within(review).getByRole("button", { name: "却下する" }),
    );
    expect(await within(review).findByRole("alert")).toHaveTextContent(
      "ほかの書き換え・承認・却下を処理中です",
    );
    await userEvent.click(
      within(review).getByRole("button", { name: "却下する" }),
    );
    expect(await screen.findByText(/変わっていません/)).toBeInTheDocument();
  });

  it("もう承認待ちでなければ（not_pending）その旨を出す", async () => {
    api({ [APPROVE]: () => replay("doctor_skill_change_approve_not_pending") });
    renderSettings();
    const review = await openReview();
    await userEvent.click(
      within(review).getByRole("button", { name: "承認する" }),
    );
    expect(await within(review).findByRole("alert")).toHaveTextContent(
      "もう承認待ちではありません",
    );
  });

  it("承認の応答に new_version が無ければ済んだとしない（invalid_response）", async () => {
    api({ [APPROVE]: { ok: true } });
    renderSettings();
    const review = await openReview();
    await userEvent.click(
      within(review).getByRole("button", { name: "承認する" }),
    );
    expect(await within(review).findByRole("alert")).toHaveTextContent(
      "invalid_response",
    );
    expect(screen.queryByText(/になりました/)).toBeNull();
  });
});
