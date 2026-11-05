/**
 * D4 レジメン: チャットの決まり（⌘/Ctrl+Enter で送る・Enter は改行・IME 変換中・送信中の止め方・
 * H1 の決まった文・往復の失敗）。
 */
import {
  act,
  fireEvent,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
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
  DRAFTS,
  REGIMENS,
  draftOf,
  fieldsKey,
  getKey,
  regimensBody,
  turnKey,
} from "./regimenTesting";

afterEach(() => {
  vi.unstubAllGlobals();
});

const DRAFT_LIST = {
  drafts: [
    {
      ...(fixtureBody("doctor_regimen_drafts") as { drafts: object[] })
        .drafts[0],
      id: 3,
      display_name: "FOLFIRI＋BV",
    },
  ],
};

/** 開いている新規の下書き（id 3。turn の fixture の応答と同じ下書き）を一覧から開く。 */
function api(extra: Record<string, RouteValue> = {}) {
  return mockApi({
    [REGIMENS]: regimensBody(),
    [DRAFTS]: DRAFT_LIST,
    [getKey(3)]: { draft: draftOf("doctor_regimen_draft_turn") },
    ...extra,
  });
}

/** 送る処理（queue の await の後の fetch）まで流してから確かめる。 */
async function flush() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

async function openDraft() {
  renderRoute("/doctor/settings", "/doctor/settings", <RegimenSettings />);
  await userEvent.click(
    await screen.findByRole("tab", { name: /FOLFIRI＋BV 下書き/ }),
  );
  await screen.findByRole("heading", { name: "FOLFIRI＋BV（下書き・新規）" });
  return screen.getByLabelText("Claude に伝える");
}

describe("D4 レジメン: チャットの入力", () => {
  it.each([
    ["⌘+Enter", { metaKey: true }],
    ["Ctrl+Enter", { ctrlKey: true }],
  ])("%s で送る", async (_name, init) => {
    const fetchMock = api({
      [turnKey(3)]: fixtureBody("doctor_regimen_draft_turn") as object,
    });
    const input = await openDraft();
    await userEvent.type(input, "点滴は");
    fireEvent.keyDown(input, { key: "Enter", ...init });
    await waitFor(() => expect(countOf(fetchMock, turnKey(3))).toBe(1));
    expect(bodiesOf(fetchMock, turnKey(3))).toEqual([{ text: "点滴は" }]);
  });

  it("送るボタンで送る", async () => {
    const fetchMock = api({
      [turnKey(3)]: fixtureBody("doctor_regimen_draft_turn") as object,
    });
    const input = await openDraft();
    await userEvent.type(input, "点滴は");
    await userEvent.click(screen.getByRole("button", { name: "送る" }));
    await waitFor(() => expect(countOf(fetchMock, turnKey(3))).toBe(1));
  });

  it.each([
    ["Enter", "{Enter}"],
    ["Shift+Enter", "{Shift>}{Enter}{/Shift}"],
  ])("%s は送らず改行する", async (_name, keys) => {
    const fetchMock = api({
      [turnKey(3)]: fixtureBody("doctor_regimen_draft_turn") as object,
    });
    const input = await openDraft();
    await userEvent.type(input, `点滴は${keys}Day1`);
    await flush();
    expect(input).toHaveValue("点滴は\nDay1");
    expect(countOf(fetchMock, turnKey(3))).toBe(0);
    expect(screen.queryByText(/考えています…/)).toBeNull();
  });

  it("Option+Enter では送らない（改行はブラウザに任せ、止めない）", async () => {
    const fetchMock = api({
      [turnKey(3)]: fixtureBody("doctor_regimen_draft_turn") as object,
    });
    const input = await openDraft();
    await userEvent.type(input, "点滴は");
    // fireEvent は既定の動きを止められたとき false を返す
    expect(fireEvent.keyDown(input, { key: "Enter", altKey: true })).toBe(true);
    await flush();
    expect(countOf(fetchMock, turnKey(3))).toBe(0);
  });

  it.each([
    ["isComposing", { isComposing: true }],
    ["keyCode 229", { keyCode: 229 }],
  ])(
    "IME 変換中の ⌘+Enter（%s）では送らない（送るまで待ってから確かめる）",
    async (_name, init) => {
      const fetchMock = api({
        [turnKey(3)]: fixtureBody("doctor_regimen_draft_turn") as object,
      });
      const input = await openDraft();
      await userEvent.type(input, "点滴は");
      fireEvent.keyDown(input, { key: "Enter", metaKey: true, ...init });
      await flush();
      expect(countOf(fetchMock, turnKey(3))).toBe(0);
      expect(screen.queryByText(/考えています…/)).toBeNull();
      expect(input).toHaveValue("点滴は");
      expect(screen.getByLabelText("レジメン名")).toBeEnabled();
      // 確定の後の ⌘+Enter は送る
      fireEvent.keyDown(input, { key: "Enter", metaKey: true });
      await waitFor(() => expect(countOf(fetchMock, turnKey(3))).toBe(1));
      expect(bodiesOf(fetchMock, turnKey(3))).toEqual([{ text: "点滴は" }]);
    },
  );

  it.each([
    ["isComposing", { isComposing: true }],
    ["keyCode 229", { keyCode: 229 }],
  ])("1行の欄でも変換中の Enter（%s）では保存しない", async (_name, init) => {
    const fetchMock = api({
      [fieldsKey(3)]: { draft: draftOf("doctor_regimen_draft_turn") },
    });
    await openDraft();
    const target = screen.getByLabelText("対象（任意）");
    await userEvent.clear(target);
    await userEvent.type(target, "胃がん");
    fireEvent.keyDown(target, { key: "Enter", ...init });
    await flush();
    expect(countOf(fetchMock, fieldsKey(3))).toBe(0);
    fireEvent.keyDown(target, { key: "Enter" });
    await waitFor(() => expect(countOf(fetchMock, fieldsKey(3))).toBe(1));
    expect(bodiesOf(fetchMock, fieldsKey(3))).toEqual([
      { changes: [{ field_id: "basic.target", value: "胃がん" }] },
    ]);
  });

  it("ask の選択肢を押すとその文を送り、入力欄に書きかけた文は残す", async () => {
    const fetchMock = api({
      [turnKey(3)]: fixtureBody("doctor_regimen_draft_turn") as object,
    });
    const input = await openDraft();
    await userEvent.type(input, "書きかけ");
    const log = screen.getByRole("list", { name: "会話" });
    await userEvent.click(
      within(log).getByRole("button", { name: "Day1・15" }),
    );
    await waitFor(() =>
      expect(bodiesOf(fetchMock, turnKey(3))).toEqual([{ text: "Day1・15" }]),
    );
    await waitFor(() =>
      expect(
        within(log).getByRole("button", { name: "Day1・15" }),
      ).toBeEnabled(),
    );
    expect(input).toHaveValue("書きかけ");
  });

  it("空の文は送れない", async () => {
    const fetchMock = api();
    const input = await openDraft();
    expect(screen.getByRole("button", { name: "送る" })).toBeDisabled();
    await userEvent.type(input, "   {Meta>}{Enter}{/Meta}");
    expect(countOf(fetchMock, turnKey(3))).toBe(0);
  });

  it("送信中は左のフォーム・送るボタン・タブを止め、応答中と出す", async () => {
    const pending = deferred<Response>();
    api({ [turnKey(3)]: () => pending.promise });
    const input = await openDraft();
    await userEvent.type(input, "点滴の日は Day1{Meta>}{Enter}{/Meta}");
    expect(await screen.findByText(/考えています…/)).toBeInTheDocument();
    expect(screen.getByLabelText("レジメン名")).toBeDisabled();
    expect(screen.getByLabelText("Day（ベバシズマブ）")).toBeDisabled();
    expect(screen.getByRole("button", { name: "＋ 薬を足す" })).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "部品集から選ぶ" }),
    ).toBeDisabled();
    expect(screen.getByRole("button", { name: "送る" })).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "下書きを捨てる" }),
    ).toBeDisabled();
    expect(screen.getByRole("tab", { name: /CAPOX/ })).toBeDisabled();
    pending.resolve(
      jsonResponse(fixtureBody("doctor_regimen_draft_turn_failed")),
    );
    await waitFor(() =>
      expect(screen.getByLabelText("レジメン名")).toBeEnabled(),
    );
    expect(screen.queryByText(/考えています…/)).toBeNull();
  });

  it("往復が失敗したら会話に失敗の行を出し、入力欄は空にする（文は会話に入った）", async () => {
    api({
      [turnKey(3)]: fixtureBody("doctor_regimen_draft_turn_failed") as object,
    });
    const input = await openDraft();
    await userEvent.type(input, "点滴の日は Day1{Meta>}{Enter}{/Meta}");
    const chat = screen.getByRole("complementary", {
      name: "Claude とのチャット",
    });
    expect(
      await within(chat).findByText(
        /サーバーで想定外の失敗がありました。フォームは変わっていません/,
      ),
    ).toBeInTheDocument();
    expect(within(chat).getByText("点滴の日は Day1")).toBeInTheDocument();
    expect(input).toHaveValue("");
    // 失敗の後は ask の選択肢を押せない（会話の最後ではない）
    expect(within(chat).getByRole("button", { name: "Day1" })).toBeDisabled();
  });

  it("422 h1_blocked は入力の文を返さず決まった文で知らせ、入力欄の文は残す", async () => {
    const fixture = apiFixture("doctor_regimen_draft_turn_h1");
    const text = (fixture.request as { text: string }).text;
    api({
      [turnKey(3)]: () =>
        jsonResponse(structuredClone(fixture.body), fixture.status),
    });
    const input = await openDraft();
    await userEvent.type(input, text);
    await userEvent.click(screen.getByRole("button", { name: "送る" }));
    const alert = await screen.findByText(
      /個人を特定しうる表現の疑いがあるため、送りませんでした/,
    );
    expect(alert).toHaveTextContent("先生の文");
    expect(alert).toHaveTextContent("id_like");
    expect(alert).not.toHaveTextContent("A-023");
    expect(input).toHaveValue(text);
    const log = screen.getByRole("list", { name: "会話" });
    expect(within(log).queryByText(text)).toBeNull();
  });

  it("古い往復の結果（discarded）なら読み直し、入力欄の文は残す", async () => {
    const fetchMock = api({
      [turnKey(3)]: {
        draft: draftOf("doctor_regimen_draft_turn"),
        turn_error: "discarded",
      },
    });
    const input = await openDraft();
    await userEvent.type(input, "点滴の日は Day1{Meta>}{Enter}{/Meta}");
    expect(
      await screen.findByText(/この往復の結果は反映しませんでした/),
    ).toBeInTheDocument();
    expect(input).toHaveValue("点滴の日は Day1");
    expect(countOf(fetchMock, getKey(3))).toBe(2);
  });

  it("応答中（409 working）なら説明を出して読み直す", async () => {
    const fetchMock = api({
      [turnKey(3)]: () => jsonResponse({ error: "working" }, 409),
    });
    const input = await openDraft();
    await userEvent.type(input, "点滴の日は Day1{Meta>}{Enter}{/Meta}");
    expect(await screen.findByText(/Claude の応答中です/)).toBeInTheDocument();
    expect(countOf(fetchMock, getKey(3))).toBe(2);
  });
});
