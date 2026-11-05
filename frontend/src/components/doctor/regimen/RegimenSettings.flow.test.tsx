/**
 * D4 レジメン: モック（docs/reference/d4-regimen-mock.dc.html）の2本の流れ。
 * 1. 新規: ＋ 新しいレジメン → チャットで送る → 欄が埋まる・ask に選択肢で答える → 確認 →
 *    AI の値を1行削除 → チェック → 採用 → 登録済み
 * 2. 既存の直接編集: FOLFOX を開く → 欄を直接直す → 確認（差分）→ 採用 → 版2
 * 応答は実際の API の fixture（doctor_regimen_*）を写して流れに合わせたもの。
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { RegimenDraft, RegimenPreview } from "../../../api/regimenTypes";
import { fixtureBody } from "../../../test/apiFixtures";
import { jsonResponse } from "../../../test/fetchMock";
import { bodiesOf, countOf, mockApi, renderRoute } from "../testing";
import RegimenSettings from "./RegimenSettings";
import {
  CREATE,
  DRAFTS,
  REGIMENS,
  adoptKey,
  assistantRow,
  doctorRow,
  draftOf,
  fieldsKey,
  folfoxDraft,
  previewKey,
  previewOf,
  regimensBody,
  turnKey,
} from "./regimenTesting";

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderScreen() {
  return renderRoute(
    "/doctor/settings",
    "/doctor/settings",
    <RegimenSettings />,
  );
}

function fieldOf(input: HTMLElement): HTMLElement {
  const box = input.closest<HTMLElement>("[data-field-id]");
  if (!box) {
    throw new Error("欄の枠が無い");
  }
  return box;
}

// --- 1. 新規 ---------------------------------------------------------------

const MSG1 =
  "FOLFIRI＋BV を作りたい。14日ごと、ベバシズマブも使う。下痢の質問も入れて";
const TOKEN2 = "b".repeat(64);

/** 新しい下書き（id 3。作った直後は体温の質問だけ）。 */
function createdDraft(): RegimenDraft {
  return { ...draftOf("doctor_regimen_draft_create"), id: 3 };
}

/** ask に「Day1」と答えた後: 必須がそろい、対象と だるさの言い方が標準の値。 */
function answeredDraft(): RegimenDraft {
  const turn = draftOf("doctor_regimen_draft_turn");
  const full = draftOf("doctor_regimen_draft");
  return {
    ...full,
    id: 3,
    generation: 2,
    sources: {
      ...full.sources,
      "basic.target": "standard",
      "side_effects.se-fatigue.phrases": "standard",
    },
    chat: [
      ...turn.chat,
      doctorRow("Day1", 2),
      assistantRow("点滴の日を Day1 にし、薬と副作用・質問をそろえました", 2, {
        changed: ["drugs.d-bv.days", "side_effects.se-fatigue.phrases"],
      }),
    ],
  };
}

const MSG2 = "下痢の質問は、回数が増えたかも聞いて";
const DIARRHEA_TEXT = "下痢はありましたか。いつもより回数が増えましたか";

/** 2回目の往復（チャットで質問の文を直す）の後。 */
function revisedDraft(): RegimenDraft {
  const draft = answeredDraft();
  return {
    ...draft,
    generation: 3,
    form: {
      ...draft.form,
      questions: draft.form.questions.map((q) =>
        q.row_id === "q-diarrhea" ? { ...q, text: DIARRHEA_TEXT } : q,
      ),
    },
    sources: { ...draft.sources, "questions.q-diarrhea.text": "doctor_text" },
    chat: [
      ...draft.chat,
      doctorRow(MSG2, 3),
      assistantRow("下痢の質問の文に、回数のことを足しました", 3, {
        changed: ["questions.q-diarrhea.text"],
      }),
    ],
  };
}

function firstPreview(): RegimenPreview {
  const preview = previewOf("doctor_regimen_draft_preview");
  return {
    ...preview,
    draft_id: 3,
    ai_values: [
      ...preview.ai_values,
      {
        field_id: "side_effects.se-fatigue.phrases",
        label: "だるい — 患者の言い方",
        value: ["だるい", "疲れやすい"],
        source: "standard",
      },
    ],
  };
}

function newFlowApi() {
  const turns = [
    fixtureBody("doctor_regimen_draft_turn"),
    { draft: answeredDraft(), turn_error: null },
    { draft: revisedDraft(), turn_error: null },
  ];
  const previews = [
    firstPreview(),
    {
      ...firstPreview(),
      ai_values: firstPreview().ai_values.slice(1),
      confirm_token: TOKEN2,
    },
  ];
  let adopted = false;
  return mockApi({
    [REGIMENS]: () =>
      jsonResponse(
        regimensBody(
          adopted
            ? [
                {
                  code: "FOLFIRI-BV",
                  skill_name: "regimen-folfiri-bv",
                  version: 1,
                  display_name: "FOLFIRI＋BV",
                },
              ]
            : [],
        ),
      ),
    [DRAFTS]: { drafts: [] },
    [CREATE]: { draft: createdDraft(), created: true },
    [turnKey(3)]: () => jsonResponse(turns.shift()),
    [fieldsKey(3)]: () => {
      const draft = revisedDraft();
      const { "basic.target": _removed, ...sources } = draft.sources;
      return jsonResponse({
        draft: {
          ...draft,
          form: { ...draft.form, basic: { ...draft.form.basic, target: null } },
          sources,
        },
      });
    },
    [previewKey(3)]: () => jsonResponse(previews.shift()),
    [adoptKey(3)]: () => {
      adopted = true;
      return jsonResponse(fixtureBody("doctor_regimen_draft_adopt"));
    },
  });
}

describe("D4 レジメン: 新規（チャットで作って採用する）", () => {
  it("新しいレジメン → 送る → 欄が埋まる → 選択肢で答える → 確認 → 1行削除 → チェック → 採用 → 登録済み", async () => {
    const user = userEvent.setup();
    const fetchMock = newFlowApi();
    renderScreen();

    // ＋ 新しいレジメン → 下書き（体温の質問を初めから持つ）
    await user.click(
      await screen.findByRole("tab", { name: /＋ 新しいレジメン/ }),
    );
    expect(bodiesOf(fetchMock, CREATE)).toEqual([{ from: "new" }]);
    expect(
      await screen.findByRole("heading", {
        name: "新しいレジメン（下書き・新規）",
      }),
    ).toBeInTheDocument();
    const name = screen.getByLabelText("レジメン名");
    expect(fieldOf(name)).toHaveAttribute("data-state", "missing");
    expect(within(fieldOf(name)).getByText("未入力（必須）")).toHaveClass(
      "rf-tag",
    );
    expect(screen.getByRole("button", { name: "確認へ進む" })).toBeDisabled();

    // チャットで送る（⌘+Enter）→ 欄が埋まる
    await user.type(
      screen.getByLabelText("Claude に伝える"),
      `${MSG1}{Meta>}{Enter}{/Meta}`,
    );
    expect(bodiesOf(fetchMock, turnKey(3))).toEqual([{ text: MSG1 }]);
    await waitFor(() =>
      expect(screen.getByLabelText("レジメン名")).toHaveValue("FOLFIRI＋BV"),
    );
    expect(screen.getByLabelText("Claude に伝える")).toHaveValue("");
    const chat = screen.getByRole("complementary", {
      name: "Claude とのチャット",
    });
    expect(within(chat).getByText(MSG1)).toBeInTheDocument();
    const cycle = screen.getByLabelText("1コースの日数（7〜42）");
    expect(cycle).toHaveValue("14");
    // 先生の文からの欄は青枠、標準の値の欄は AI が入れた
    expect(fieldOf(cycle)).toHaveAttribute("data-state", "doc");
    // 札は読み上げにだけ残す（色で見せる）。aria-describedby は同じ札を指す
    const cycleTag = within(fieldOf(cycle)).getByText("先生の文から");
    expect(cycleTag).toHaveClass("rf-sr-only");
    expect(cycle).toHaveAttribute("aria-describedby", cycleTag.id);
    const target = fieldOf(screen.getByLabelText("対象（任意）"));
    expect(target).toHaveAttribute("data-state", "ai");
    const targetTag = within(target).getByText("AI が入れた（標準の値）");
    expect(targetTag).toHaveClass("rf-sr-only");
    expect(screen.getByLabelText("対象（任意）")).toHaveAttribute(
      "aria-describedby",
      targetTag.id,
    );
    // ask の欄は赤枠と札（見せる）
    const days = screen.getByLabelText("Day（ベバシズマブ）");
    expect(fieldOf(days)).toHaveAttribute("data-state", "asked");
    const askedTag = within(fieldOf(days)).getByText("Claude が聞いています");
    expect(askedTag).toHaveClass("rf-tag");
    expect(askedTag).not.toHaveClass("rf-sr-only");

    // 変えた欄の札を押すと、その欄へ focus
    const changed = within(chat).getByRole("group", { name: "変えた欄" });
    expect(
      within(changed).getByRole("button", {
        name: "基本 · 対象 （AI が入れた）",
      }),
    ).toBeInTheDocument();
    await user.click(
      within(changed).getByRole("button", { name: "基本 · 1コースの日数" }),
    );
    await waitFor(() => expect(cycle).toHaveFocus());

    // ask に選択肢で答える
    expect(
      within(chat).getByText("ベバシズマブは何日目に点滴しますか"),
    ).toBeInTheDocument();
    await user.click(within(chat).getByRole("button", { name: "Day1" }));
    expect(bodiesOf(fetchMock, turnKey(3))).toEqual([
      { text: MSG1 },
      { text: "Day1" },
    ]);
    await waitFor(() =>
      expect(
        within(chat).getByText("Day1", { selector: ".rf-bubble" }),
      ).toBeInTheDocument(),
    );
    const confirmButton = screen.getByRole("button", { name: "確認へ進む" });
    await waitFor(() => expect(confirmButton).toBeEnabled());
    expect(
      screen.getByText(
        "そろいました。AI が入れた 2 行は確認の画面でも一覧にします",
      ),
    ).toBeInTheDocument();
    // 答えた後は赤枠が消える
    expect(
      fieldOf(screen.getByLabelText("Day（ベバシズマブ）")),
    ).not.toHaveAttribute("data-state", "asked");
    expect(document.querySelectorAll('[data-state="asked"]')).toHaveLength(0);

    // 2回目の往復: チャットで質問の文を直す → 欄が変わり、変えた欄の札が付く
    await user.type(
      screen.getByLabelText("Claude に伝える"),
      `${MSG2}{Meta>}{Enter}{/Meta}`,
    );
    const diarrhea = await screen.findByDisplayValue(DIARRHEA_TEXT);
    expect(fieldOf(diarrhea)).toHaveAttribute("data-state", "doc");
    expect(
      within(fieldOf(diarrhea)).getByText("先生の文から"),
    ).toBeInTheDocument();
    const groups = within(chat).getAllByRole("group", { name: "変えた欄" });
    expect(
      within(groups[groups.length - 1]).getByRole("button", {
        name: /質問 · 下痢/,
      }),
    ).toBeInTheDocument();
    // 先生の文からの欄は増えても、AI が入れた行は増えない
    expect(
      screen.getByText(/そろいました。AI が入れた 2 行/),
    ).toBeInTheDocument();

    // 確認: AI の値の一覧・SKILL.md の全文・患者の見本
    await user.click(confirmButton);
    expect(
      await screen.findByRole("heading", { name: /AI が入れた値（2 件）/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: "SKILL.md の全文" }),
    ).toHaveTextContent("name: regimen-folfiri-bv");
    const phone = screen.getByRole("group", { name: "患者のスマホの見本" });
    expect(
      within(phone).getByText("だるさや疲れやすさはありましたか"),
    ).toBeInTheDocument();
    expect(within(phone).queryByText(/点滴の日を Day1/)).toBeNull();
    const adopt = screen.getByRole("button", { name: "採用して登録" });
    expect(adopt).toBeDisabled();
    // 印の前でも、戻る・捨てるは押せる
    expect(
      screen.getByRole("button", { name: "フォームに戻る" }),
    ).toBeEnabled();
    expect(
      screen.getByRole("button", { name: "下書きを捨てる" }),
    ).toBeEnabled();

    // 印を付けてから1行削除 → 欄を空にする PATCH → 確認を取り直す（印は外れる）
    await user.click(screen.getByLabelText("上の値を全て確かめました"));
    expect(screen.getByLabelText("上の値を全て確かめました")).toBeChecked();
    await user.click(screen.getByRole("button", { name: "対象 の値を削除" }));
    expect(bodiesOf(fetchMock, fieldsKey(3))).toEqual([
      { changes: [{ field_id: "basic.target", value: null }] },
    ]);
    expect(
      await screen.findByRole("heading", { name: /AI が入れた値（1 件）/ }),
    ).toBeInTheDocument();
    expect(countOf(fetchMock, previewKey(3))).toBe(2);
    expect(screen.getByLabelText("上の値を全て確かめました")).not.toBeChecked();

    // チェック → 採用 → 登録済み
    await user.click(screen.getByLabelText("上の値を全て確かめました"));
    await user.click(screen.getByRole("button", { name: "採用して登録" }));
    expect(bodiesOf(fetchMock, adoptKey(3))).toEqual([
      { confirm_token: TOKEN2, ai_values_confirmed: true },
    ]);
    expect(
      await screen.findByRole("heading", {
        name: "regimen-folfiri-bv 版 1 を登録しました",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /部品集に無かった質問があれば、それも部品集に入れました/,
      ),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole("tab", { name: /FOLFIRI＋BV 版 1/ }),
    ).toBeInTheDocument();
  });
});

// --- 2. 既存の直接編集 -------------------------------------------------------

const NEW_TEXT = "口の中の痛みや口内炎はありましたか。食事はとれましたか";

function editedDraft(): RegimenDraft {
  const draft = folfoxDraft();
  return {
    ...draft,
    form: {
      ...draft.form,
      questions: draft.form.questions.map((q) =>
        q.row_id === "q-stomatitis" ? { ...q, text: NEW_TEXT } : q,
      ),
    },
    sources: { "questions.q-stomatitis.text": "doctor_edit" },
  };
}

function diffPreview(): RegimenPreview {
  const preview = previewOf("doctor_regimen_draft_preview_diff");
  return {
    ...preview,
    draft_id: 4,
    skill_name: "regimen-folfox",
    skill_md: {
      kind: "diff",
      text: [
        "--- a/regimen-folfox/SKILL.md",
        "+++ b/regimen-folfox/SKILL.md",
        "@@ -1,7 +1,7 @@",
        "-version: 1",
        "+version: 2",
        "-  - {key: stomatitis, text: 口の中の痛みや口内炎はありましたか, answer_type: three_level}",
        `+  - {key: stomatitis, text: ${NEW_TEXT}, answer_type: three_level}`,
      ].join("\n"),
    },
  };
}

describe("D4 レジメン: 既存の直接編集（版 N+1 の下書き）", () => {
  it("FOLFOX を開く → 欄を直す → 確認（差分）→ 採用 → 版2", async () => {
    const user = userEvent.setup();
    let adopted = false;
    let opened = false;
    const fetchMock = mockApi({
      [REGIMENS]: () => {
        const body = regimensBody();
        return jsonResponse({
          regimens: body.regimens.map((r) =>
            adopted && r.code === "FOLFOX" ? { ...r, version: 2 } : r,
          ),
        });
      },
      // 開いた後は一覧に版2の下書きが出る（採用の後は消える）
      [DRAFTS]: () => {
        const {
          form: _f,
          sources: _s,
          chat: _c,
          missing: _m,
          ...summary
        } = folfoxDraft();
        return jsonResponse({ drafts: opened && !adopted ? [summary] : [] });
      },
      [CREATE]: () => {
        opened = true;
        return jsonResponse({ draft: folfoxDraft(), created: true });
      },
      [fieldsKey(4)]: { draft: editedDraft() },
      [previewKey(4)]: diffPreview(),
      [adoptKey(4)]: () => {
        adopted = true;
        return jsonResponse({
          ok: true,
          skill_name: "regimen-folfox",
          version: 2,
          regimen: "FOLFOX",
        });
      },
    });
    renderScreen();

    await user.click(await screen.findByRole("tab", { name: /FOLFOX 版 1/ }));
    expect(bodiesOf(fetchMock, CREATE)).toEqual([{ skill: "regimen-folfox" }]);
    expect(
      await screen.findByRole("heading", { name: "FOLFOX（版 2 の下書き）" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("下書き（採用するまで患者の画面は版 1 のまま）"),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole("tab", { name: /FOLFOX 版 2 の下書き/ }),
    ).toHaveAttribute("aria-selected", "true");
    expect(screen.getByLabelText("識別名（英大文字・数字・-）")).toBeDisabled();

    // 欄を直接直す（欄を離れたときに PATCH）→ 先生が入れた
    const questions = screen.getByRole("list", { name: "患者への質問" });
    const text =
      within(questions).getByDisplayValue("口の中の痛みや口内炎はありましたか");
    await user.clear(text);
    await user.type(text, NEW_TEXT);
    expect(countOf(fetchMock, fieldsKey(4))).toBe(0);
    await user.tab();
    expect(bodiesOf(fetchMock, fieldsKey(4))).toEqual([
      {
        changes: [{ field_id: "questions.q-stomatitis.text", value: NEW_TEXT }],
      },
    ]);
    await waitFor(() =>
      expect(fieldOf(text)).toHaveAttribute("data-state", "doc"),
    );
    expect(within(fieldOf(text)).getByText("先生が入れた")).toBeInTheDocument();

    // 確認（版 1 との差分。AI の値は無いのでチェックも無い）→ 採用
    await user.click(screen.getByRole("button", { name: "確認へ進む" }));
    expect(
      await screen.findByRole("heading", {
        name: "SKILL.md の差分（版 1 → 版 2）",
      }),
    ).toBeInTheDocument();
    const diff = screen.getByRole("region", { name: "SKILL.md の差分" });
    expect(within(diff).getByText("+version: 2")).toHaveClass("d-diff-add");
    expect(screen.queryByLabelText("上の値を全て確かめました")).toBeNull();
    const phone = screen.getByRole("group", { name: "患者のスマホの見本" });
    expect(phone).toHaveTextContent("今日の記録（FOLFOX）");
    await user.click(
      screen.getByRole("button", { name: "採用して版 2 にする" }),
    );
    expect(bodiesOf(fetchMock, adoptKey(4))).toEqual([
      {
        confirm_token: diffPreview().confirm_token,
        ai_values_confirmed: false,
      },
    ]);
    expect(
      await screen.findByRole("heading", { name: "FOLFOX を版 2 にしました" }),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole("tab", { name: /FOLFOX 版 2/ }),
    ).toBeInTheDocument();
  });
});
