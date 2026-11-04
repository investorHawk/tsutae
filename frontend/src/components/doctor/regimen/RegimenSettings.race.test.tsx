/**
 * D4 レジメン: 重なったときの決まり（検証で見つかった問題の再発防止）。
 * - 確認の画面を取りに行っている間はタブを止め、遅れて返った別の下書きの確認は捨てる
 * - 入れている途中の文字を PATCH の返事で上書きしない・同じ値の PATCH を2回出さない
 * - 応答中は確認の画面も止め、往復の後は確認を取り直す（印も外れる）
 * - サーバーの下書きが working なら欄を止める
 * - 行を足すボタンの二度押し・行の単位の 422・issues の無い失敗
 * - Claude が聞いている間は確認へ進めない（赤枠の欄を直接直せば答えたことになる）
 */
import {
  act,
  renderHook,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { RegimenDraft } from "../../../api/regimenTypes";
import { fixtureBody } from "../../../test/apiFixtures";
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
import { useRegimenConfirm } from "./useRegimenConfirm";

afterEach(() => {
  vi.unstubAllGlobals();
});

/** 開いている新規の下書き（id 1。必須はそろっている）。 */
function base(): RegimenDraft {
  return draftOf("doctor_regimen_draft");
}

function withTarget(draft: RegimenDraft, target: string): RegimenDraft {
  return {
    ...draft,
    form: { ...draft.form, basic: { ...draft.form.basic, target } },
  };
}

function api(extra: Record<string, RouteValue> = {}) {
  return mockApi({
    [REGIMENS]: regimensBody(),
    [DRAFTS]: fixtureBody("doctor_regimen_drafts") as object,
    [getKey(1)]: { draft: base() },
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

describe("D4 レジメン: 確認と下書きの取り違え", () => {
  it("確認の画面を取りに行っている間はタブを止める", async () => {
    const pending = deferred<Response>();
    api({ [previewKey(1)]: () => pending.promise });
    await openDraft();
    await userEvent.click(screen.getByRole("button", { name: "確認へ進む" }));
    await waitFor(() =>
      expect(screen.getByRole("tab", { name: /CAPOX/ })).toBeDisabled(),
    );
    pending.resolve(jsonResponse(previewOf("doctor_regimen_draft_preview")));
    expect(
      await screen.findByRole("heading", { name: /AI が入れた値/ }),
    ).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /CAPOX/ })).toBeEnabled();
  });

  it("遅れて返った前の下書きの確認は捨てる（下書きが替わった・閉じた）", async () => {
    const pending = deferred<Response>();
    const fetchMock = mockApi({ [previewKey(1)]: () => pending.promise });
    const { result, rerender } = renderHook(
      ({ id }: { id: number | null }) =>
        useRegimenConfirm(id, () => "internal_error"),
      { initialProps: { id: 1 as number | null } },
    );
    let loaded: Promise<unknown> = Promise.resolve();
    act(() => {
      loaded = result.current.load();
    });
    await waitFor(() => expect(countOf(fetchMock, previewKey(1))).toBe(1));
    rerender({ id: 2 });
    await act(async () => {
      pending.resolve(jsonResponse(previewOf("doctor_regimen_draft_preview")));
      expect(await loaded).toBeNull();
    });
    expect(result.current.preview).toBeNull();
    expect(result.current.loading).toBe(false);
  });

  it("別のタブの下書きを開いている間は、前の下書きの確認へ進めない・捨てられない", async () => {
    const create = deferred<Response>();
    const fetchMock = api({
      [previewKey(1)]: previewOf("doctor_regimen_draft_preview"),
      [CREATE]: () => create.promise,
    });
    await openDraft();
    await userEvent.click(screen.getByRole("tab", { name: /CAPOX/ }));
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
    const confirmButton = screen.queryByRole("button", { name: "確認へ進む" });
    if (confirmButton) {
      expect(confirmButton).toBeDisabled();
      await userEvent.click(confirmButton);
    }
    const discardButton = screen.queryByRole("button", {
      name: "下書きを捨てる",
    });
    if (discardButton) {
      expect(discardButton).toBeDisabled();
    }
    expect(countOf(fetchMock, previewKey(1))).toBe(0);
    await act(async () => {
      create.resolve(
        jsonResponse(fixtureBody("doctor_regimen_draft_create_existing")),
      );
      await new Promise((r) => setTimeout(r, 0));
    });
    expect(
      await screen.findByRole("heading", { name: /CAPOX/ }),
    ).toBeInTheDocument();
    expect(document.getElementById("rf-skill-h")).toBeNull();
  });

  it("確認は取りに行った下書きのものだけを返す（下書きが替わったら null）", async () => {
    mockApi({ [previewKey(1)]: previewOf("doctor_regimen_draft_preview") });
    const { result, rerender } = renderHook(
      ({ id }: { id: number | null }) =>
        useRegimenConfirm(id, () => "internal_error"),
      { initialProps: { id: 1 as number | null } },
    );
    await act(async () => {
      await result.current.load();
    });
    expect(result.current.preview).not.toBeNull();
    rerender({ id: 2 });
    expect(result.current.preview).toBeNull();
    expect(result.current.confirmed).toBe(false);
  });

  it("clear の後に返った確認も捨てる", async () => {
    const pending = deferred<Response>();
    mockApi({ [previewKey(1)]: () => pending.promise });
    const { result } = renderHook(() =>
      useRegimenConfirm(1, () => "internal_error"),
    );
    let loaded: Promise<unknown> = Promise.resolve();
    act(() => {
      loaded = result.current.load();
    });
    act(() => result.current.clear());
    await act(async () => {
      pending.resolve(jsonResponse(previewOf("doctor_regimen_draft_preview")));
      expect(await loaded).toBeNull();
    });
    expect(result.current.preview).toBeNull();
  });
});

describe("D4 レジメン: 入れている途中の欄", () => {
  it("Enter の PATCH の返事が、その後に足した文字を消さない（離れたら続きを送る）", async () => {
    const first = deferred<Response>();
    const responses: (() => Response | Promise<Response>)[] = [
      () => first.promise,
      () => jsonResponse({ draft: withTarget(base(), "胃がんと食道がん") }),
    ];
    const fetchMock = api({
      [fieldsKey(1)]: () => {
        const next = responses.shift();
        if (!next) {
          throw new Error("PATCH が多すぎる");
        }
        return next();
      },
    });
    await openDraft();
    const target = screen.getByLabelText("対象（任意）");
    await userEvent.clear(target);
    await userEvent.type(target, "胃がん{Enter}");
    await userEvent.type(target, "と食道がん");
    first.resolve(jsonResponse({ draft: withTarget(base(), "胃がん") }));
    await waitFor(() => expect(countOf(fetchMock, getKey(1))).toBe(1));
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(target).toHaveValue("胃がんと食道がん");
    await userEvent.tab();
    await waitFor(() =>
      expect(bodiesOf(fetchMock, fieldsKey(1))).toEqual([
        { changes: [{ field_id: "basic.target", value: "胃がん" }] },
        { changes: [{ field_id: "basic.target", value: "胃がんと食道がん" }] },
      ]),
    );
    expect(target).toHaveValue("胃がんと食道がん");
  });

  it("Enter の後に欄を離れても、同じ値の PATCH は1回だけ", async () => {
    const pending = deferred<Response>();
    const fetchMock = api({ [fieldsKey(1)]: () => pending.promise });
    await openDraft();
    const target = screen.getByLabelText("対象（任意）");
    await userEvent.clear(target);
    await userEvent.type(target, "胃がん{Enter}");
    await userEvent.tab();
    pending.resolve(jsonResponse({ draft: withTarget(base(), "胃がん") }));
    await waitFor(() => expect(target).toHaveValue("胃がん"));
    expect(countOf(fetchMock, fieldsKey(1))).toBe(1);
  });

  it("issues の無い失敗でも、その欄の前の理由は消す", async () => {
    const responses = [
      () =>
        jsonResponse(
          {
            error: "invalid_fields",
            issues: [
              {
                field_id: "basic.target",
                code: "too_long",
                message: "前の理由",
              },
            ],
          },
          422,
        ),
      () => jsonResponse({ error: "h1_blocked" }, 422),
    ];
    api({ [fieldsKey(1)]: () => (responses.shift() ?? responses[0])() });
    await openDraft();
    const target = screen.getByLabelText("対象（任意）");
    await userEvent.clear(target);
    await userEvent.type(target, "胃がん{Enter}");
    expect(
      await within(fieldOf(target)).findByText("前の理由"),
    ).toBeInTheDocument();
    await userEvent.type(target, "x{Enter}");
    await waitFor(() =>
      expect(within(fieldOf(target)).queryByText("前の理由")).toBeNull(),
    );
  });
});

describe("D4 レジメン: 行を足す", () => {
  it("足している間はボタンを止め、二度押しで同じ行を2回送らない", async () => {
    const pending = deferred<Response>();
    const fetchMock = api({ [fieldsKey(1)]: () => pending.promise });
    await openDraft();
    const add = screen.getByRole("button", { name: "＋ 薬を足す" });
    await userEvent.click(add);
    expect(add).toBeDisabled();
    await userEvent.click(add);
    expect(countOf(fetchMock, fieldsKey(1))).toBe(1);
    pending.resolve(jsonResponse({ draft: base() }));
    await waitFor(() => expect(add).toBeEnabled());
  });

  it("行の単位の 422（row_exists）は節の見出しの下に出す", async () => {
    api({
      [fieldsKey(1)]: () =>
        jsonResponse(
          {
            error: "invalid_fields",
            issues: [
              {
                field_id: "drugs.drug-add-a",
                code: "row_exists",
                message: "同じ行がもうあります",
              },
            ],
          },
          422,
        ),
    });
    await openDraft();
    await userEvent.click(screen.getByRole("button", { name: "＋ 薬を足す" }));
    const section = screen
      .getByRole("heading", { name: "投与スケジュール（内服・注射）" })
      .closest("section");
    if (!section) {
      throw new Error("節が無い");
    }
    expect(
      await within(section).findByText("同じ行がもうあります"),
    ).toBeInTheDocument();
  });
});

const TOKEN2 = "c".repeat(64);

describe("D4 レジメン: 確認の画面と Claude の往復", () => {
  it("応答中は確認の画面の操作を止め、往復の後は確認を取り直す（印も外れる）", async () => {
    const turn = deferred<Response>();
    const previews = [
      previewOf("doctor_regimen_draft_preview"),
      { ...previewOf("doctor_regimen_draft_preview"), confirm_token: TOKEN2 },
    ];
    const fetchMock = api({
      [previewKey(1)]: () => jsonResponse(previews.shift()),
      [turnKey(1)]: () => turn.promise,
    });
    await openDraft();
    await userEvent.click(screen.getByRole("button", { name: "確認へ進む" }));
    const check = await screen.findByLabelText("上の値を全て確かめました");
    await userEvent.click(check);
    expect(check).toBeChecked();

    await userEvent.type(
      screen.getByLabelText("Claude に伝える"),
      "1コースは21日{Enter}",
    );
    expect(await screen.findByText(/考えています…/)).toBeInTheDocument();
    expect(check).toBeDisabled();
    for (const button of screen.getAllByRole("button", { name: /値を削除/ })) {
      expect(button).toBeDisabled();
    }
    expect(screen.getByRole("button", { name: "採用して登録" })).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "下書きを捨てる" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "フォームに戻る" }),
    ).toBeDisabled();

    const draft = base();
    turn.resolve(
      jsonResponse({
        draft: {
          ...draft,
          generation: 1,
          form: {
            ...draft.form,
            basic: { ...draft.form.basic, cycle_days: 21 },
          },
          chat: [
            doctorRow("1コースは21日", 1),
            assistantRow("1コースを21日にしました", 1, {
              changed: ["basic.cycle_days"],
            }),
          ],
        },
        turn_error: null,
      }),
    );
    await waitFor(() => expect(countOf(fetchMock, previewKey(1))).toBe(2));
    await waitFor(() =>
      expect(screen.getByLabelText("上の値を全て確かめました")).toBeEnabled(),
    );
    expect(screen.getByLabelText("上の値を全て確かめました")).not.toBeChecked();
  });
});

describe("D4 レジメン: 確認の画面で Claude が聞き返した", () => {
  it("答えるまで採用できない", async () => {
    const draft = base();
    api({
      [previewKey(1)]: previewOf("doctor_regimen_draft_preview"),
      [turnKey(1)]: {
        draft: {
          ...draft,
          generation: 1,
          chat: [
            doctorRow("補足も入れて", 1),
            assistantRow("補足の指示を聞かせてください", 1, {
              ask: {
                field_id: "notes",
                question: "補足の指示はありますか",
                options: ["なし", "施設の決まりを書く"],
              },
            }),
          ],
        },
        turn_error: null,
      },
    });
    await openDraft();
    await userEvent.click(screen.getByRole("button", { name: "確認へ進む" }));
    await userEvent.click(
      await screen.findByLabelText("上の値を全て確かめました"),
    );
    expect(screen.getByRole("button", { name: "採用して登録" })).toBeEnabled();
    await userEvent.type(
      screen.getByLabelText("Claude に伝える"),
      "補足も入れて{Enter}",
    );
    expect(
      await screen.findByText(/Claude の質問に答えてください（チャットか/),
    ).toBeInTheDocument();
    const again = screen.getByLabelText("上の値を全て確かめました");
    await waitFor(() => expect(again).toBeEnabled());
    await userEvent.click(again);
    expect(again).toBeChecked();
    expect(screen.getByRole("button", { name: "採用して登録" })).toBeDisabled();
  });
});

describe("D4 レジメン: サーバーの下書きが応答中（working）", () => {
  it("欄と送るボタンを止め、考えていますと出す。working が終われば読み直して戻す", async () => {
    const drafts = [
      { draft: { ...base(), status: "working" } },
      { draft: base() },
    ];
    api({
      [getKey(1)]: () =>
        jsonResponse(drafts.length > 1 ? drafts.shift() : drafts[0]),
    });
    await openDraft();
    expect(screen.getByLabelText("レジメン名")).toBeDisabled();
    expect(screen.getByText(/考えています…/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "確認へ進む" })).toBeDisabled();
    await waitFor(
      () => expect(screen.getByLabelText("レジメン名")).toBeEnabled(),
      { timeout: 4000 },
    );
    expect(screen.queryByText(/考えています…/)).toBeNull();
  });
});

describe("D4 レジメン: Claude が聞いている間", () => {
  function asking(): RegimenDraft {
    const draft = base();
    return {
      ...draft,
      generation: 1,
      chat: [
        doctorRow("補足を入れて", 1),
        assistantRow("補足の指示はどう書きますか", 1, {
          ask: {
            field_id: "notes",
            question: "補足の指示はありますか",
            options: ["なし", "施設の決まりを書く"],
          },
        }),
      ],
    };
  }

  it("確認へ進めない。赤枠の欄を直接直せば答えたことになり、進める", async () => {
    const fetchMock = mockApi({
      [REGIMENS]: regimensBody(),
      [DRAFTS]: fixtureBody("doctor_regimen_drafts") as object,
      [getKey(1)]: { draft: asking() },
      // 返る下書きの会話は ask のまま（サーバーは「答えた」を持たない）
      [fieldsKey(1)]: () =>
        jsonResponse({
          draft: {
            ...asking(),
            form: { ...asking().form, notes: "施設の決まり" },
          },
        }),
      [CREATE]: { draft: asking(), created: false },
    });
    await openDraft();
    const notes = screen.getByLabelText(/型に入らない施設の決まり/);
    expect(fieldOf(notes)).toHaveAttribute("data-state", "asked");
    expect(screen.getByRole("button", { name: "確認へ進む" })).toBeDisabled();
    expect(
      screen.getByText("Claude の質問に答えてください（赤枠の欄）"),
    ).toBeInTheDocument();
    await userEvent.type(notes, "施設の決まり");
    await userEvent.tab();
    await waitFor(() => expect(countOf(fetchMock, fieldsKey(1))).toBe(1));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "確認へ進む" })).toBeEnabled(),
    );
    expect(fieldOf(notes)).not.toHaveAttribute("data-state", "asked");
  });
});
