/**
 * D4 レジメン: 薬の名前の候補（左の欄の datalist・チャットの札）。取得に失敗しても画面は
 * 普通に使える。候補は医師の画面だけで使う。
 */
import { act, screen, waitFor, within } from "@testing-library/react";
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
import { TURN_TEXT_MAX } from "./ChatInput";
import RegimenSettings from "./RegimenSettings";
import {
  CREATE,
  DRAFTS,
  DRUG_NAMES,
  REGIMENS,
  adoptKey,
  assistantRow,
  draftOf,
  fieldsKey,
  folfoxDraft,
  getKey,
  previewKey,
  previewOf,
  regimensBody,
  turnKey,
} from "./regimenTesting";

const NAMES = ["オキサリプラチン", "パクリタキセル", "ラムシルマブ"];
const HINT = "薬の候補（押すと入ります）";

afterEach(() => {
  vi.unstubAllGlobals();
});

/** 開いている新規の下書き（id 1）。 */
function api(extra: Record<string, RouteValue> = {}) {
  return mockApi({
    [REGIMENS]: regimensBody(),
    [DRAFTS]: fixtureBody("doctor_regimen_drafts") as object,
    [getKey(1)]: fixtureBody("doctor_regimen_draft") as object,
    [DRUG_NAMES]: { names: NAMES },
    ...extra,
  });
}

function renderScreen() {
  renderRoute("/doctor/settings", "/doctor/settings", <RegimenSettings />);
}

async function openDraft() {
  renderScreen();
  await userEvent.click(
    await screen.findByRole("tab", { name: /FOLFIRI＋BV 下書き/ }),
  );
  await screen.findByRole("heading", { name: "FOLFIRI＋BV（下書き・新規）" });
}

function chatOf(): HTMLElement {
  return screen.getByRole("complementary", { name: "Claude とのチャット" });
}

function textOf(): HTMLTextAreaElement {
  return within(chatOf()).getByLabelText(
    "Claude に伝える",
  ) as HTMLTextAreaElement;
}

function draftWith(patch: Partial<RegimenDraft>): RegimenDraft {
  return { ...draftOf("doctor_regimen_draft"), ...patch };
}

describe("D4 レジメン: チャットの薬の候補", () => {
  it("新しいレジメンで会話が無ければ札を出し、押すと入力欄の末尾に足して focus する", async () => {
    const user = userEvent.setup();
    api();
    await openDraft();
    const group = await within(chatOf()).findByRole("group", { name: HINT });
    expect(group).toHaveTextContent(HINT);
    const chip = within(group).getByRole("button", { name: "パクリタキセル" });
    expect(chip).toHaveAttribute("type", "button");
    await user.click(chip);
    expect(textOf()).toHaveValue("パクリタキセル");
    expect(textOf()).toHaveFocus();
    await user.click(
      within(group).getByRole("button", { name: "ラムシルマブ" }),
    );
    expect(textOf()).toHaveValue("パクリタキセル・ラムシルマブ");
  });

  it("上限を超えるなら足さない", async () => {
    const user = userEvent.setup();
    api();
    await openDraft();
    const full = "あ".repeat(TURN_TEXT_MAX - 2);
    await user.click(textOf());
    await user.paste(full);
    const group = await within(chatOf()).findByRole("group", { name: HINT });
    await user.click(
      within(group).getByRole("button", { name: "パクリタキセル" }),
    );
    expect(textOf()).toHaveValue(full);
  });

  it("札を押しても送らず、Claude の応答中は押せない", async () => {
    const user = userEvent.setup();
    const gate = deferred<Response>();
    const fetchMock = api({ [turnKey(1)]: () => gate.promise });
    await openDraft();
    const group = await within(chatOf()).findByRole("group", { name: HINT });
    await user.click(within(group).getByRole("button", { name: NAMES[0]! }));
    expect(countOf(fetchMock, turnKey(1))).toBe(0);
    await user.click(screen.getByRole("button", { name: "送る" }));
    await waitFor(() =>
      expect(
        within(group).getByRole("button", { name: NAMES[1]! }),
      ).toBeDisabled(),
    );
    await act(async () => {
      gate.resolve(jsonResponse({ error: "h1_blocked" }, 422));
      await gate.promise;
    });
    await waitFor(() =>
      expect(
        within(group).getByRole("button", { name: NAMES[1]! }),
      ).toBeEnabled(),
    );
  });

  it("会話が始まっていれば札を出さない", async () => {
    api({
      [getKey(1)]: {
        draft: draftWith({ chat: [assistantRow("はい", 1)] }),
      },
    });
    await openDraft();
    // 候補を読み終えてから（左の欄の datalist が出てから）札が無いことを確かめる
    await waitFor(() =>
      expect(document.querySelectorAll("datalist option")).toHaveLength(
        NAMES.length,
      ),
    );
    expect(within(chatOf()).queryByText(HINT)).toBeNull();
  });

  it("既存のレジメンの下書きでは札を出さない（左の欄の候補は出す）", async () => {
    api({
      [DRAFTS]: { drafts: [] },
      [CREATE]: () =>
        jsonResponse({ draft: folfoxDraft(), created: true }, 200),
    });
    renderScreen();
    await userEvent.click(await screen.findByRole("tab", { name: /FOLFOX/ }));
    await screen.findByRole("heading", { name: /FOLFOX（版 2 の下書き）/ });
    await waitFor(() =>
      expect(document.querySelectorAll("datalist option")).toHaveLength(
        NAMES.length,
      ),
    );
    expect(within(chatOf()).queryByText(HINT)).toBeNull();
  });
});

describe("D4 レジメン: 左の薬の欄の候補", () => {
  it("名前の欄だけが同じ datalist を指し、datalist は1つだけ", async () => {
    api();
    await openDraft();
    await waitFor(() =>
      expect(document.querySelectorAll("datalist option")).toHaveLength(
        NAMES.length,
      ),
    );
    const lists = document.querySelectorAll("datalist");
    expect(lists).toHaveLength(1);
    const options = [...lists[0]!.querySelectorAll("option")];
    expect(options.map((o) => o.value)).toEqual(NAMES);
    const name = screen.getByLabelText("薬の名前（ベバシズマブ）");
    expect(name).toHaveAttribute("list", lists[0]!.id);
    expect(screen.getByLabelText("薬の名前（イリノテカン）")).toHaveAttribute(
      "list",
      lists[0]!.id,
    );
    expect(
      screen.getByLabelText("飲み始め（ベバシズマブ）"),
    ).not.toHaveAttribute("list");
    expect(screen.getByLabelText("レジメン名")).not.toHaveAttribute("list");
  });

  it("候補に無い薬も書けて、欄を離れたときに1回だけ送る", async () => {
    const user = userEvent.setup();
    const draft = draftOf("doctor_regimen_draft");
    const fetchMock = api({ [fieldsKey(1)]: { draft } });
    await openDraft();
    const name = screen.getByLabelText("薬の名前（ベバシズマブ）");
    await user.clear(name);
    await user.type(name, "候補に無い薬");
    expect(countOf(fetchMock, fieldsKey(1))).toBe(0);
    await user.tab();
    expect(bodiesOf(fetchMock, fieldsKey(1))).toEqual([
      {
        changes: [{ field_id: "drugs.d-bv.name", value: "候補に無い薬" }],
      },
    ]);
  });
});

describe("D4 レジメン: 候補の取得", () => {
  it("取得に失敗しても、候補を出さないだけで画面は使える", async () => {
    const user = userEvent.setup();
    const fetchMock = api({
      [DRUG_NAMES]: () => jsonResponse({ error: "internal_error" }, 500),
    });
    await openDraft();
    await waitFor(() => expect(countOf(fetchMock, DRUG_NAMES)).toBe(1));
    expect(within(chatOf()).queryByText(HINT)).toBeNull();
    expect(document.querySelector("datalist")).toBeNull();
    expect(
      screen.getByLabelText("薬の名前（ベバシズマブ）"),
    ).not.toHaveAttribute("list");
    expect(screen.queryByRole("alert")).toBeNull();
    await user.type(textOf(), "作りたい");
    expect(screen.getByRole("button", { name: "送る" })).toBeEnabled();
  });

  it("形の違う応答も候補なしとして扱う", async () => {
    const fetchMock = api({ [DRUG_NAMES]: { names: [1, 2] } });
    await openDraft();
    await waitFor(() => expect(countOf(fetchMock, DRUG_NAMES)).toBe(1));
    expect(document.querySelector("datalist")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("下書きを開いても取り直さず、採用の後に読み直して次の下書きの候補に出る", async () => {
    const user = userEvent.setup();
    const after = ["オキサリプラチン", "新しい薬"];
    let adopted = false;
    const fetchMock = api({
      [DRUG_NAMES]: () => jsonResponse({ names: adopted ? after : NAMES }),
      [previewKey(1)]: previewOf("doctor_regimen_draft_preview"),
      [adoptKey(1)]: () => {
        adopted = true;
        return jsonResponse({
          ok: true,
          skill_name: "regimen-folfiri-bv",
          version: 1,
          regimen: "FOLFIRI-BV",
        });
      },
      [CREATE]: () =>
        jsonResponse(fixtureBody("doctor_regimen_draft_create") as object),
    });
    await openDraft();
    await waitFor(() => expect(countOf(fetchMock, DRUG_NAMES)).toBe(1));
    await user.click(screen.getByRole("button", { name: "確認へ進む" }));
    await user.click(await screen.findByLabelText("上の値を全て確かめました"));
    expect(countOf(fetchMock, DRUG_NAMES)).toBe(1);
    await user.click(screen.getByRole("button", { name: "採用して登録" }));
    await screen.findByRole("heading", { name: /を登録しました/ });
    await waitFor(() => expect(countOf(fetchMock, DRUG_NAMES)).toBe(2));
    await user.click(screen.getByRole("tab", { name: /＋ 新しいレジメン/ }));
    const group = await within(chatOf()).findByRole("group", { name: HINT });
    expect(
      await within(group).findByRole("button", { name: "新しい薬" }),
    ).toBeInTheDocument();
    expect(countOf(fetchMock, DRUG_NAMES)).toBe(2);
  });
});
