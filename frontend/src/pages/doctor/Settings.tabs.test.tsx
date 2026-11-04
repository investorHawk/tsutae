/**
 * D4 設定を変える（v1.1）: 「レジメン」（フォーム＋チャット）と「レポートの形式」
 * （旧 D4 の一文 → 差分 → 承認。report-format-* だけ）のタブ。
 */
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, renderRoute } from "../../components/doctor/testing";
import { skillContentRoutes } from "../../components/doctor/skillTesting";
import { fixtureBody } from "../../test/apiFixtures";
import Settings from "./Settings";

afterEach(() => {
  vi.unstubAllGlobals();
});

function api() {
  return mockApi({
    "GET /api/doctor/regimens": fixtureBody("doctor_regimens") as object,
    "GET /api/doctor/regimen-drafts": { drafts: [] },
    // 実際の一覧（regimen-capox・regimen-folfox・report-format-default）
    "GET /api/doctor/skills": fixtureBody("doctor_skills") as object,
    "GET /api/doctor/skill-changes": { skill_changes: [] },
    ...skillContentRoutes(["report-format-default"]),
  });
}

describe("Settings（D4 設定を変える）", () => {
  it("初めはレジメンのタブ（FOLFOX・CAPOX・＋ 新しいレジメン）", async () => {
    api();
    renderRoute("/doctor/settings", "/doctor/settings", <Settings />);
    expect(
      screen.getByRole("heading", { level: 1, name: "設定を変える" }),
    ).toBeInTheDocument();
    const kinds = screen.getByRole("tablist", { name: "設定の種類" });
    expect(
      within(kinds).getByRole("tab", { name: "レジメン" }),
    ).toHaveAttribute("aria-selected", "true");
    const regimens = screen.getByRole("tablist", { name: "レジメン" });
    expect(
      await within(regimens).findByRole("tab", { name: /FOLFOX 版 1/ }),
    ).toBeInTheDocument();
    expect(
      within(regimens).getByRole("tab", { name: /CAPOX 版 1/ }),
    ).toBeInTheDocument();
    expect(
      within(regimens).getByRole("tab", { name: "＋ 新しいレジメン" }),
    ).toBeInTheDocument();
    // タブを開くまで下書きを作らない
    expect(screen.queryByRole("combobox", { name: "Skill" })).toBeNull();
  });

  it("「レポートの形式」は旧 D4 で、report-format だけを選べる（初めは report-format-default）", async () => {
    api();
    renderRoute("/doctor/settings", "/doctor/settings", <Settings />);
    await userEvent.click(
      screen.getByRole("tab", { name: "レポートの形式（一文で頼む）" }),
    );
    const select = screen.getByLabelText("Skill");
    await screen.findByRole("option", { name: "レポートの形式（第1版）" });
    expect(select).toHaveValue("report-format-default");
    expect(within(select).getAllByRole("option")).toHaveLength(1);
    expect(screen.queryByRole("option", { name: /FOLFOX|CAPOX/ })).toBeNull();
    expect(screen.queryByRole("tablist", { name: "レジメン" })).toBeNull();
  });

  it("種類を替えて戻っても、開いていた下書きの画面はそのまま（開き直さない）", async () => {
    const fetchMock = mockApi({
      "GET /api/doctor/regimens": fixtureBody("doctor_regimens") as object,
      "GET /api/doctor/regimen-drafts": { drafts: [] },
      "POST /api/doctor/regimen-drafts": fixtureBody(
        "doctor_regimen_draft_create_existing",
      ) as object,
      "GET /api/doctor/skills": fixtureBody("doctor_skills") as object,
      "GET /api/doctor/skill-changes": { skill_changes: [] },
      ...skillContentRoutes(["report-format-default"]),
    });
    renderRoute("/doctor/settings", "/doctor/settings", <Settings />);
    await userEvent.click(await screen.findByRole("tab", { name: /CAPOX/ }));
    expect(
      await screen.findByRole("heading", { name: "CAPOX（版 2 の下書き）" }),
    ).toBeInTheDocument();
    const name = screen.getByLabelText("レジメン名");
    await userEvent.clear(name);
    await userEvent.type(name, "CAPOX（書きかけ）");
    await userEvent.click(
      screen.getByRole("tab", { name: "レポートの形式（一文で頼む）" }),
    );
    expect(await screen.findByLabelText("Skill")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "レジメン" }));
    expect(
      screen.getByRole("heading", { name: "CAPOX（版 2 の下書き）" }),
    ).toBeInTheDocument();
    const creates = fetchMock.mock.calls.filter(
      ([url, init]) =>
        init?.method === "POST" && String(url) === "/api/doctor/regimen-drafts",
    );
    expect(creates).toHaveLength(1);
  });

  it("タブは ← → で focus が移り、Tab で入るのは選んだタブだけ", async () => {
    api();
    renderRoute("/doctor/settings", "/doctor/settings", <Settings />);
    const kinds = screen.getByRole("tablist", { name: "設定の種類" });
    const [regimen, format] = within(kinds).getAllByRole("tab");
    expect(regimen).toHaveAttribute("tabindex", "0");
    expect(format).toHaveAttribute("tabindex", "-1");
    regimen.focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(format).toHaveFocus();
    await userEvent.keyboard("{ArrowRight}");
    expect(regimen).toHaveFocus();
    expect(
      screen.getByRole("tabpanel", { name: "レジメン" }),
    ).toBeInTheDocument();

    const regimens = screen.getByRole("tablist", { name: "レジメン" });
    const folfox = await within(regimens).findByRole("tab", {
      name: /FOLFOX 版 1/,
    });
    const tabs = within(regimens).getAllByRole("tab");
    expect(tabs.map((t) => t.getAttribute("tabindex"))).toEqual([
      "0",
      "-1",
      "-1",
    ]);
    folfox.focus();
    await userEvent.keyboard("{End}");
    expect(
      within(regimens).getByRole("tab", { name: "＋ 新しいレジメン" }),
    ).toHaveFocus();
    await userEvent.keyboard("{Home}");
    expect(folfox).toHaveFocus();
  });
});
