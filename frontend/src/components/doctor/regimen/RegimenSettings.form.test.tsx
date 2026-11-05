/**
 * D4 レジメン: 左のフォーム（422 の欄の理由・409 conflict の読み直し・行の追加・部品集の小窓・
 * CAPOX への切り替え・下書きを捨てる・採用の 409）。
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { RegimenDraft } from "../../../api/regimenTypes";
import { apiFixture, fixtureBody } from "../../../test/apiFixtures";
import { jsonResponse } from "../../../test/fetchMock";
import {
  bodiesOf,
  countOf,
  deferred,
  mockApi,
  renderRoute,
  type RouteValue,
} from "../testing";
import RegimenSettings from "./RegimenSettings";
import {
  CREATE,
  DRAFTS,
  LIBRARY,
  REGIMENS,
  adoptKey,
  discardKey,
  draftOf,
  fieldsKey,
  folfoxDraft,
  getKey,
  previewKey,
  previewOf,
  regimensBody,
} from "./regimenTesting";

afterEach(() => {
  vi.unstubAllGlobals();
});

/** 開いている新規の下書き（id 1。fixture doctor_regimen_drafts・doctor_regimen_draft）。 */
function api(extra: Record<string, RouteValue> = {}) {
  return mockApi({
    [REGIMENS]: regimensBody(),
    [DRAFTS]: fixtureBody("doctor_regimen_drafts") as object,
    [getKey(1)]: fixtureBody("doctor_regimen_draft") as object,
    ...extra,
  });
}

async function openDraft() {
  renderRoute("/doctor/settings", "/doctor/settings", <RegimenSettings />);
  await userEvent.click(
    await screen.findByRole("tab", { name: /FOLFIRI＋BV 下書き/ }),
  );
  await screen.findByRole("heading", { name: "FOLFIRI＋BV（下書き・新規）" });
}

function fieldOf(input: HTMLElement): HTMLElement {
  const box = input.closest<HTMLElement>("[data-field-id]");
  if (!box) {
    throw new Error("欄の枠が無い");
  }
  return box;
}

function withQuestion(draft: RegimenDraft): RegimenDraft {
  return {
    ...draft,
    form: {
      ...draft.form,
      questions: [
        ...draft.form.questions,
        {
          row_id: "question-add-a",
          key: "numbness",
          label: "しびれ",
          text: "手足のしびれや冷たいものがさわりにくい感じはありましたか",
          answer_type: "three_level",
        },
      ],
    },
  };
}

describe("D4 レジメン: 欄の直接編集", () => {
  it("422 の理由（薬の量）を欄の下に出し、入れた文字は残す", async () => {
    const fixture = apiFixture("doctor_regimen_draft_fields_invalid");
    const fetchMock = api({
      [fieldsKey(1)]: () =>
        jsonResponse(structuredClone(fixture.body), fixture.status),
    });
    await openDraft();
    const name = screen.getByLabelText("薬の名前（ベバシズマブ）");
    await userEvent.clear(name);
    await userEvent.type(name, "ベバシズマブ 5mg/kg{Enter}");
    expect(bodiesOf(fetchMock, fieldsKey(1))).toEqual([fixture.request]);
    expect(
      await within(fieldOf(name)).findByText("薬の量（数値＋mg 等）は持たない"),
    ).toBeInTheDocument();
    expect(name).toHaveAttribute("aria-invalid", "true");
    expect(name).toHaveValue("ベバシズマブ 5mg/kg");
  });

  it("読めない Day は送らずに理由を出す", async () => {
    const fetchMock = api();
    await openDraft();
    const days = screen.getByLabelText("Day（ベバシズマブ）");
    await userEvent.clear(days);
    await userEvent.type(days, "毎週");
    await userEvent.tab();
    expect(
      within(fieldOf(days)).getByText(/Day は「Day1・8・15」/),
    ).toBeInTheDocument();
    expect(countOf(fetchMock, fieldsKey(1))).toBe(0);
  });

  it("Day の範囲（複数）は {start, end} の一覧で送る", async () => {
    const fetchMock = api({
      [fieldsKey(1)]: fixtureBody("doctor_regimen_draft") as object,
    });
    await openDraft();
    const days = screen.getByLabelText("Day（ベバシズマブ）");
    await userEvent.clear(days);
    await userEvent.type(days, "Day1・15");
    await userEvent.tab();
    expect(bodiesOf(fetchMock, fieldsKey(1))).toEqual([
      {
        changes: [
          {
            field_id: "drugs.d-bv.days",
            value: [
              { start: 1, end: 1 },
              { start: 15, end: 15 },
            ],
          },
        ],
      },
    ]);
  });

  it("409 conflict なら読み直して説明を出す", async () => {
    const fetchMock = api({
      [fieldsKey(1)]: () => jsonResponse({ error: "conflict" }, 409),
    });
    await openDraft();
    const target = screen.getByLabelText("対象（任意）");
    await userEvent.clear(target);
    await userEvent.type(target, "胃がん{Enter}");
    expect(
      await screen.findByText(
        /ほかの変更（Claude の返答など）が先に入りました/,
      ),
    ).toBeInTheDocument();
    expect(countOf(fetchMock, getKey(1))).toBe(2);
  });

  it("欄を離れた直後に「確認へ進む」を押しても、PATCH が済んでから確認を作る", async () => {
    const pending = deferred<Response>();
    const fetchMock = api({
      [fieldsKey(1)]: () => pending.promise,
      [previewKey(1)]: previewOf("doctor_regimen_draft_preview"),
    });
    await openDraft();
    const target = screen.getByLabelText("対象（任意）");
    await userEvent.clear(target);
    await userEvent.type(target, "胃がん");
    await userEvent.click(screen.getByRole("button", { name: "確認へ進む" }));
    expect(countOf(fetchMock, fieldsKey(1))).toBe(1);
    expect(countOf(fetchMock, previewKey(1))).toBe(0);
    pending.resolve(jsonResponse(fixtureBody("doctor_regimen_draft")));
    expect(
      await screen.findByRole("heading", { name: /AI が入れた値（1 件）/ }),
    ).toBeInTheDocument();
    expect(countOf(fetchMock, previewKey(1))).toBe(1);
    const order = fetchMock.mock.calls.map(
      ([url, init]) => `${init?.method ?? "GET"} ${String(url)}`,
    );
    expect(
      order.indexOf(`GET /api/doctor/regimen-drafts/1/preview`),
    ).toBeGreaterThan(
      order.indexOf(`PATCH /api/doctor/regimen-drafts/1/fields`),
    );
  });

  it("「＋ 薬を足す」は Claude の行と重ならない row_id で行を足す", async () => {
    const fetchMock = api({
      [fieldsKey(1)]: fixtureBody("doctor_regimen_draft") as object,
    });
    await openDraft();
    await userEvent.click(screen.getByRole("button", { name: "＋ 薬を足す" }));
    expect(bodiesOf(fetchMock, fieldsKey(1))).toEqual([
      { adds: [{ section: "drugs", row_id: "drug-add-a" }], changes: [] },
    ]);
  });

  it("体温の質問は消せない（固定規則の注記）", async () => {
    api();
    await openDraft();
    const list = screen.getByRole("list", { name: "患者への質問" });
    expect(
      within(list).queryByRole("button", { name: "質問「体温」を消す" }),
    ).toBeNull();
    expect(
      within(list).getByRole("button", { name: "質問「下痢」を消す" }),
    ).toBeEnabled();
    expect(
      screen.getByText(/固定規則（外せない）: 体温が 38.0℃/),
    ).toBeInTheDocument();
  });
});

describe("D4 レジメン: 部品集の小窓", () => {
  it("Esc で閉じて focus を戻す。選ぶと質問の節に足す（adds＋changes の1回）", async () => {
    const fetchMock = api({
      [LIBRARY]: fixtureBody("doctor_question_library") as object,
      [fieldsKey(1)]: () =>
        jsonResponse({ draft: withQuestion(draftOf("doctor_regimen_draft")) }),
    });
    await openDraft();
    const opener = screen.getByRole("button", { name: "部品集から選ぶ" });
    await userEvent.click(opener);
    const dialog = await screen.findByRole("dialog", {
      name: "質問の部品集から選ぶ",
    });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(
      within(dialog).getByRole("button", { name: "閉じる" }),
    ).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(opener).toHaveFocus();

    await userEvent.click(opener);
    const again = await screen.findByRole("dialog");
    // フォームにある質問（下痢・体温など）は選択肢に出さない
    expect(
      await within(again).findByRole("button", { name: "「しびれ」を足す" }),
    ).toBeInTheDocument();
    expect(
      within(again).queryByRole("button", { name: "「下痢」を足す" }),
    ).toBeNull();
    expect(
      within(again).queryByRole("button", { name: "「体温」を足す" }),
    ).toBeNull();
    await userEvent.click(
      within(again).getByRole("button", { name: "「しびれ」を足す" }),
    );
    expect(bodiesOf(fetchMock, fieldsKey(1))).toEqual([
      {
        adds: [{ section: "questions", row_id: "question-add-a" }],
        changes: [
          { field_id: "questions.question-add-a.key", value: "numbness" },
          { field_id: "questions.question-add-a.label", value: "しびれ" },
          {
            field_id: "questions.question-add-a.text",
            value: "手足のしびれや冷たいものがさわりにくい感じはありましたか",
          },
          {
            field_id: "questions.question-add-a.answer_type",
            value: "three_level",
          },
        ],
      },
    ]);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.getByDisplayValue("しびれ")).toBeInTheDocument();
  });
});

describe("D4 レジメン: タブ", () => {
  it("FOLFOX ↔ CAPOX を切り替えると、それぞれの版 N+1 の下書きを開く", async () => {
    const capox = draftOf("doctor_regimen_draft_create_existing");
    const fetchMock = mockApi({
      [REGIMENS]: regimensBody(),
      [DRAFTS]: { drafts: [] },
      [CREATE]: (body) =>
        jsonResponse({
          draft:
            (body as { skill: string }).skill === "regimen-capox"
              ? capox
              : folfoxDraft(),
          created: false,
        }),
    });
    renderRoute("/doctor/settings", "/doctor/settings", <RegimenSettings />);
    await userEvent.click(await screen.findByRole("tab", { name: /FOLFOX/ }));
    expect(
      await screen.findByRole("heading", { name: "FOLFOX（版 2 の下書き）" }),
    ).toBeInTheDocument();
    expect(
      screen.getByDisplayValue("フルオロウラシル（46時間）"),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: /CAPOX/ }));
    expect(
      await screen.findByRole("heading", { name: "CAPOX（版 2 の下書き）" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /CAPOX/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByDisplayValue("カペシタビン")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("フルオロウラシル（46時間）")).toBeNull();
    expect(bodiesOf(fetchMock, CREATE)).toEqual([
      { skill: "regimen-folfox" },
      { skill: "regimen-capox" },
    ]);
    // 患者のいるレジメン（schedule_locked）は日程の欄を止め、その旨を出す
    expect(
      screen.getByText(/このレジメンには患者がいるため/),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("1コースの日数（7〜42）")).toBeDisabled();
    expect(screen.getByLabelText("Day（カペシタビン）")).toBeDisabled();
    expect(screen.getByLabelText("薬の名前（カペシタビン）")).toBeEnabled();
    // Day の帯（内服は Day1〜14 の文字も添える）
    const bar = screen.getByRole("figure", { name: "1コースの投与の帯" });
    expect(bar).toHaveTextContent("1コース 21 日");
    expect(bar).toHaveTextContent("内服 Day1〜14");
  });

  it("下書きを捨てる（画面内の確認）→ 一覧を読み直す", async () => {
    const fetchMock = api({
      [discardKey(1)]: fixtureBody("doctor_regimen_draft_discard") as object,
    });
    await openDraft();
    await userEvent.click(
      screen.getByRole("button", { name: "下書きを捨てる" }),
    );
    expect(countOf(fetchMock, discardKey(1))).toBe(0);
    expect(screen.getByText(/この下書きを捨てます/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "捨てる" }));
    expect(countOf(fetchMock, discardKey(1))).toBe(1);
    expect(await screen.findByText("下書きを捨てました")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /FOLFIRI＋BV/ })).toBeNull();
    expect(countOf(fetchMock, DRAFTS)).toBe(2);
  });
});

describe("D4 レジメン: 採用の 409", () => {
  it.each([
    [
      "doctor_regimen_draft_adopt_token_mismatch",
      "確認の画面を出した後に値が変わりました",
      2,
    ],
    [
      "doctor_regimen_draft_adopt_unconfirmed",
      "AI が入れた値を確かめていません",
      2,
    ],
  ])("%s は説明を出し、確認の画面を出し直す", async (name, text, previews) => {
    const fixture = apiFixture(name);
    const fetchMock = api({
      [previewKey(1)]: previewOf("doctor_regimen_draft_preview"),
      [adoptKey(1)]: () =>
        jsonResponse(structuredClone(fixture.body), fixture.status),
    });
    await openDraft();
    await userEvent.click(screen.getByRole("button", { name: "確認へ進む" }));
    await userEvent.click(
      await screen.findByLabelText("上の値を全て確かめました"),
    );
    await userEvent.click(screen.getByRole("button", { name: "採用して登録" }));
    expect(await screen.findByText(new RegExp(text))).toBeInTheDocument();
    expect(countOf(fetchMock, previewKey(1))).toBe(previews);
    expect(screen.getByLabelText("上の値を全て確かめました")).not.toBeChecked();
  });

  it.each([
    ["schedule_locked", "患者がいるため"],
    ["code_taken", "識別名はもう使われています"],
    ["stale", "版が変わりました"],
  ])("%s は文で知らせる", async (code, text) => {
    api({
      [previewKey(1)]: previewOf("doctor_regimen_draft_preview"),
      [adoptKey(1)]: () => jsonResponse({ error: code }, 409),
    });
    await openDraft();
    await userEvent.click(screen.getByRole("button", { name: "確認へ進む" }));
    await userEvent.click(
      await screen.findByLabelText("上の値を全て確かめました"),
    );
    await userEvent.click(screen.getByRole("button", { name: "採用して登録" }));
    const alert = await screen.findByText(new RegExp(text));
    expect(alert).toHaveTextContent("採用できませんでした");
    expect(alert).toHaveTextContent(code);
  });
});
