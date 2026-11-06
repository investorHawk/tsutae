/**
 * D4 レジメン: 表示の決まり（Claude の返答の **…** は太字・箇条書きは並び・先生の文はそのまま／新規の下書きの
 * タブは、フォームのレジメン名が入ったらその名前。空なら「新しいレジメン」）。
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type {
  RegimenDraft,
  RegimenDraftSummary,
  RegimenDraftsResponse,
} from "../../../api/regimenTypes";
import { fixtureBody } from "../../../test/apiFixtures";
import { jsonResponse } from "../../../test/fetchMock";
import { mockApi, renderRoute, type RouteValue } from "../testing";
import RegimenSettings from "./RegimenSettings";
import {
  CREATE,
  DRAFTS,
  REGIMENS,
  assistantRow,
  doctorRow,
  draftOf,
  fieldsKey,
  getKey,
  previewKey,
  previewOf,
  regimensBody,
  turnKey,
} from "./regimenTesting";

afterEach(() => {
  vi.unstubAllGlobals();
});

const SUMMARY = (fixtureBody("doctor_regimen_drafts") as RegimenDraftsResponse)
  .drafts[0];

/** 名前の無い新規の下書きの要約（作った時の一覧の値）。 */
function unnamedSummary(id: number): RegimenDraftSummary {
  return {
    ...SUMMARY,
    id,
    regimen: null,
    skill_name: null,
    display_name: null,
  };
}

/** 名前の無い新規の下書き（id 1。作った直後）。 */
function unnamedDraft(): RegimenDraft {
  return draftOf("doctor_regimen_draft_create");
}

/** レジメン名を入れた後の下書き（id 1）。 */
function namedDraft(): RegimenDraft {
  return draftOf("doctor_regimen_draft_fields");
}

function api(routes: Record<string, RouteValue>) {
  return mockApi({ [REGIMENS]: regimensBody(), ...routes });
}

function renderScreen() {
  renderRoute("/doctor/settings", "/doctor/settings", <RegimenSettings />);
}

function chatPanel(): HTMLElement {
  return screen.getByRole("complementary", { name: "Claude とのチャット" });
}

const DOCTOR_TEXT = "**FOLFIRI＋BV** を作りたい";
const REPLY = "**FOLFIRI＋BV** のフォームを作りました。\n- **識別名:** 未入力";

/** Claude の1往復の後（名前が入り、返答に **…** がある）。 */
function turnedDraft(): RegimenDraft {
  const turn = draftOf("doctor_regimen_draft_turn");
  return {
    ...turn,
    id: 1,
    generation: 1,
    chat: [doctorRow(DOCTOR_TEXT, 1), assistantRow(REPLY, 1)],
  };
}

describe("D4 レジメン: Claude の返答の記法", () => {
  it("Claude の返答の **…**・箇条書きだけを描き、先生の文は記号のまま出す", async () => {
    api({
      [DRAFTS]: { drafts: [unnamedSummary(1)] },
      [getKey(1)]: { draft: turnedDraft() },
    });
    renderScreen();
    await userEvent.click(
      await screen.findByRole("tab", { name: /^新しいレジメン 下書き/ }),
    );
    const chat = await waitFor(chatPanel);
    const strong = within(chat)
      .getAllByText((_, el) => el?.tagName === "STRONG")
      .map((el) => el.textContent);
    expect(strong).toEqual(["FOLFIRI＋BV", "識別名:"]);
    const claude = chat.querySelector(".rf-msg--claude .rf-bubble");
    // 段落と箇条書き（記号の「- 」は出さない）
    expect(claude?.querySelector("p")?.textContent).toBe(
      "FOLFIRI＋BV のフォームを作りました。",
    );
    expect(claude?.querySelector("ul > li")?.textContent).toBe(
      "識別名: 未入力",
    );
    expect(within(chat).getByText(DOCTOR_TEXT)).toBeInTheDocument();
  });
});

describe("D4 レジメン: 新規の下書きのタブの名前", () => {
  it("Claude の返答でレジメン名が入ると、タブがその名前になる", async () => {
    let created = false;
    api({
      [DRAFTS]: () =>
        jsonResponse({ drafts: created ? [unnamedSummary(1)] : [] }),
      [CREATE]: () => {
        created = true;
        return jsonResponse({ draft: unnamedDraft(), created: true });
      },
      [turnKey(1)]: { draft: turnedDraft(), turn_error: null },
    });
    renderScreen();
    await userEvent.click(
      await screen.findByRole("tab", { name: /＋ 新しいレジメン/ }),
    );
    expect(
      await screen.findByRole("tab", { name: /^新しいレジメン 下書き/ }),
    ).toBeInTheDocument();
    await userEvent.type(
      screen.getByLabelText("Claude に伝える"),
      "FOLFIRI＋BV を作りたい{Meta>}{Enter}{/Meta}",
    );
    expect(
      await screen.findByRole("tab", { name: /FOLFIRI＋BV 下書き（新規）/ }),
    ).toHaveAttribute("aria-selected", "true");
    expect(
      screen.queryByRole("tab", { name: /^新しいレジメン 下書き/ }),
    ).toBeNull();
  });

  it("名前が空白だけの下書きも、タブと見出しは「新しいレジメン」", async () => {
    const blank = unnamedDraft();
    api({
      [DRAFTS]: { drafts: [{ ...unnamedSummary(1), display_name: " " }] },
      [getKey(1)]: {
        draft: {
          ...blank,
          display_name: " ",
          form: {
            ...blank.form,
            basic: { ...blank.form.basic, display_name: " " },
          },
        },
      },
    });
    renderScreen();
    await userEvent.click(
      await screen.findByRole("tab", { name: "新しいレジメン 下書き（新規）" }),
    );
    expect(
      await screen.findByRole("heading", {
        name: "新しいレジメン（下書き・新規）",
      }),
    ).toBeInTheDocument();
  });

  it("確認の見本も、空白だけの名前は「新しいレジメン」", async () => {
    const blank = unnamedDraft();
    api({
      [DRAFTS]: { drafts: [unnamedSummary(1)] },
      [getKey(1)]: {
        draft: {
          ...blank,
          missing: [],
          form: {
            ...blank.form,
            basic: { ...blank.form.basic, display_name: " " },
          },
        },
      },
      [previewKey(1)]: {
        ...previewOf("doctor_regimen_draft_preview"),
        skill_name: null,
      },
    });
    renderScreen();
    await userEvent.click(
      await screen.findByRole("tab", { name: /^新しいレジメン 下書き/ }),
    );
    await userEvent.click(
      await screen.findByRole("button", { name: "確認へ進む" }),
    );
    const phone = await screen.findByRole("group", {
      name: "患者のスマホの見本",
    });
    expect(
      within(phone).getByText("今日の記録（新しいレジメン）"),
    ).toBeInTheDocument();
  });

  it("先生がレジメン名を入れると、タブがその名前になる", async () => {
    api({
      [DRAFTS]: { drafts: [unnamedSummary(1)] },
      [getKey(1)]: { draft: unnamedDraft() },
      [fieldsKey(1)]: { draft: namedDraft() },
    });
    renderScreen();
    await userEvent.click(
      await screen.findByRole("tab", { name: /^新しいレジメン 下書き/ }),
    );
    const name = await screen.findByLabelText("レジメン名");
    await userEvent.type(name, "FOLFIRI＋BV");
    await userEvent.tab();
    expect(
      await screen.findByRole("tab", { name: /FOLFIRI＋BV 下書き（新規）/ }),
    ).toBeInTheDocument();
  });

  it("名前を入れた下書きから別の下書きへ移っても、タブの名前は残る", async () => {
    let named = false;
    const other = { ...unnamedSummary(2), display_name: "CAPIRI" };
    api({
      [DRAFTS]: () =>
        jsonResponse({
          drafts: [
            named
              ? { ...unnamedSummary(1), display_name: "FOLFIRI＋BV" }
              : unnamedSummary(1),
            other,
          ],
        }),
      [getKey(1)]: { draft: unnamedDraft() },
      [getKey(2)]: {
        draft: {
          ...unnamedDraft(),
          id: 2,
          display_name: "CAPIRI",
          form: {
            ...unnamedDraft().form,
            basic: { ...unnamedDraft().form.basic, display_name: "CAPIRI" },
          },
        },
      },
      [fieldsKey(1)]: () => {
        named = true;
        return jsonResponse({ draft: namedDraft() });
      },
    });
    renderScreen();
    await userEvent.click(
      await screen.findByRole("tab", { name: /^新しいレジメン 下書き/ }),
    );
    await userEvent.type(
      await screen.findByLabelText("レジメン名"),
      "FOLFIRI＋BV",
    );
    await userEvent.tab();
    await screen.findByRole("tab", { name: /FOLFIRI＋BV 下書き/ });
    await userEvent.click(screen.getByRole("tab", { name: /CAPIRI/ }));
    await screen.findByRole("heading", { name: "CAPIRI（下書き・新規）" });
    expect(
      screen.getByRole("tab", { name: /FOLFIRI＋BV 下書き（新規）/ }),
    ).toHaveAttribute("aria-selected", "false");
    expect(
      screen.queryByRole("tab", { name: /^新しいレジメン 下書き/ }),
    ).toBeNull();
  });
});
