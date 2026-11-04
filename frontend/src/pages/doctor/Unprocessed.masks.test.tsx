/**
 * D6: 未処理の記載を医師が伏せ字にして、Claude で変換し直す。
 * - 記録ごとに「送らない（未処理のまま）」「送る（伏せて）」を選ぶ（初めは送らない）
 * - 送る記録は、疑われた区間を初めから伏せた状態で出し、押すと戻せる。ほかの所は選んで
 *   「伏せ字にする」で足す（位置は原文の code point）
 * - 「伏せ字を確かめる」でサーバーに再検出させ、送られる文とまだ疑われる語を出す
 * - 下のボタンで保存 → 再変換 → 変換ログの画面へ（医師は文を書かず、区間だけを送る）
 */
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { MaskCheckResponse, UnprocessedItem } from "../../api/types";
import {
  bodiesOf,
  countOf,
  mockApi,
  renderRoute,
} from "../../components/doctor/testing";
import { fixtureBody } from "../../test/apiFixtures";
import { unprocessedItemStub, visitHeaderStub } from "../../test/doctorStubs";
import { jsonResponse } from "../../test/fetchMock";
import Unprocessed from "./Unprocessed";

afterEach(() => {
  vi.unstubAllGlobals();
  window.getSelection()?.removeAllRanges();
});

const ROUTE = "/doctor/unprocessed/:visitId";
const PATH = "/doctor/unprocessed/12";
const GET = "GET /api/doctor/visits/12/unprocessed";
const CHECK = "POST /api/doctor/visits/12/masks/check";
const SAVE = "POST /api/doctor/visits/12/masks";
const REGEN = "POST /api/doctor/visits/12/regenerate";
const TEXT = "磯鷲さんにもらった漢方";
const SUBMIT = "伏せ字を保存して AI で変換し直す";

function item(patch: Partial<UnprocessedItem> = {}): UnprocessedItem {
  return unprocessedItemStub({
    entry_id: 38,
    text: TEXT,
    marks: [{ start: 0, end: 4 }],
    ...patch,
  });
}

function listing(items: UnprocessedItem[] = [item()]) {
  return { visit: visitHeaderStub(), entries: items };
}

function checkResult(
  patch: Partial<MaskCheckResponse> = {},
): MaskCheckResponse {
  return {
    entry_id: 38,
    masked_text: "[伏せ字]にもらった漢方",
    suspects: [],
    reason: null,
    sendable: true,
    confirmable: false,
    ...patch,
  };
}

async function chooseSend() {
  await userEvent.click(await screen.findByLabelText("送る（伏せて）"));
}

/** 伏せる所の表示の中で、文字の span の UTF-16 の位置 from〜to を選ぶ。 */
function selectIn(spanText: string, from: number, to: number) {
  const editor = document.querySelector(".d-mask-text") as HTMLElement;
  const holder = within(editor).getByText(spanText);
  const node = holder.firstChild as Text;
  const range = document.createRange();
  range.setStart(node, from);
  range.setEnd(node, to);
  const selection = window.getSelection() as Selection;
  selection.removeAllRanges();
  selection.addRange(range);
}

describe("Unprocessed の伏せ字", () => {
  it("初めは「送らない」で、伏せる所の編集は出さない", async () => {
    mockApi({ [GET]: listing() });
    renderRoute(PATH, ROUTE, <Unprocessed />);
    expect(
      await screen.findByLabelText("送らない（未処理のまま）"),
    ).toBeChecked();
    expect(screen.queryByRole("button", { name: /伏せ字「/ })).toBeNull();
    expect(screen.getByRole("button", { name: SUBMIT })).toBeDisabled();
  });

  it("送ると、疑われた区間を初めから伏せ、押すと戻せる", async () => {
    mockApi({ [GET]: listing() });
    renderRoute(PATH, ROUTE, <Unprocessed />);
    await chooseSend();
    const mask = screen.getByRole("button", {
      name: "伏せ字「磯鷲さん」を戻す",
    });
    expect(mask).toHaveTextContent("伏せ字");
    expect(mask).toHaveClass("d-mask");
    await userEvent.click(mask);
    expect(screen.queryByRole("button", { name: /伏せ字「/ })).toBeNull();
    const editor = document.querySelector(".d-mask-text") as HTMLElement;
    expect(editor).toHaveTextContent(TEXT);
  });

  it("伏せた印はキーボードでも戻せる", async () => {
    mockApi({ [GET]: listing() });
    renderRoute(PATH, ROUTE, <Unprocessed />);
    await chooseSend();
    const mask = screen.getByRole("button", {
      name: "伏せ字「磯鷲さん」を戻す",
    });
    mask.focus();
    await userEvent.keyboard("{Enter}");
    expect(screen.queryByRole("button", { name: /伏せ字「/ })).toBeNull();
  });

  it("選んだ所を「伏せ字にする」で足す（位置は code point）", async () => {
    const text = "😀磯鷲さんと漢方";
    const fetchMock = mockApi({
      [GET]: listing([item({ text, marks: [] })]),
      [CHECK]: checkResult(),
    });
    renderRoute(PATH, ROUTE, <Unprocessed />);
    await chooseSend();
    // 「磯鷲」（UTF-16 では 2〜4。絵文字が2つ分）
    selectIn(text, 2, 4);
    fireEvent.click(screen.getByRole("button", { name: "伏せ字にする" }));
    expect(
      screen.getByRole("button", { name: "伏せ字「磯鷲」を戻す" }),
    ).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "伏せ字を確かめる" }),
    );
    await screen.findByText("送られる文（Claude に届く形）");
    expect(bodiesOf(fetchMock, CHECK)).toEqual([
      { entry_id: 38, spans: [{ start: 1, end: 3 }] },
    ]);
  });

  it("伏せた区間と重なる選択は1つにまとめる", async () => {
    mockApi({ [GET]: listing([item({ marks: [{ start: 0, end: 2 }] })]) });
    renderRoute(PATH, ROUTE, <Unprocessed />);
    await chooseSend();
    // 伏せた「磯鷲」の後の「さんに」を選ぶ（隣り合う → まとめる）
    selectIn("さんにもらった漢方", 0, 3);
    fireEvent.click(screen.getByRole("button", { name: "伏せ字にする" }));
    expect(
      screen.getByRole("button", { name: "伏せ字「磯鷲さんに」を戻す" }),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /伏せ字「/ })).toHaveLength(1);
  });

  it("何も選ばずに押したら、選び方を知らせる", async () => {
    mockApi({ [GET]: listing() });
    renderRoute(PATH, ROUTE, <Unprocessed />);
    await chooseSend();
    fireEvent.click(screen.getByRole("button", { name: "伏せ字にする" }));
    expect(screen.getByRole("status")).toHaveTextContent("マウスで選んで");
  });

  it("確かめて疑いが残れば、強調と「確かめた」のチェックを出す", async () => {
    mockApi({
      [GET]: listing(),
      [CHECK]: fixtureBody("doctor_masks_check") as object,
    });
    renderRoute(PATH, ROUTE, <Unprocessed />);
    await chooseSend();
    await userEvent.click(
      screen.getByRole("button", { name: "伏せ字を確かめる" }),
    );
    const sent = (await screen.findByText("磯鷲さん", {
      selector: ".d-sent mark",
    })) as HTMLElement;
    expect(sent.tagName).toBe("MARK");
    expect(screen.getByText(/まだ疑わしい語があります/)).toBeInTheDocument();
    expect(
      screen.getByLabelText("個人を特定する語は無いことを確かめた"),
    ).not.toBeChecked();
  });

  it("仮名ID・受付番号が残れば確かめて送れない", async () => {
    mockApi({
      [GET]: listing(),
      [CHECK]: checkResult({
        masked_text: "受付はA-023",
        suspects: [{ start: 3, end: 8, rule: "known_identifier" }],
        reason: "known_identifier",
        sendable: false,
        confirmable: false,
      }),
    });
    renderRoute(PATH, ROUTE, <Unprocessed />);
    await chooseSend();
    await userEvent.click(
      screen.getByRole("button", { name: "伏せ字を確かめる" }),
    );
    expect(await screen.findByText(/確かめても送れない語/)).toBeInTheDocument();
    expect(
      screen.queryByLabelText("個人を特定する語は無いことを確かめた"),
    ).toBeNull();
  });

  it("区間を変えたら確かめた結果を捨てる", async () => {
    mockApi({
      [GET]: listing(),
      [CHECK]: fixtureBody("doctor_masks_check") as object,
    });
    renderRoute(PATH, ROUTE, <Unprocessed />);
    await chooseSend();
    await userEvent.click(
      screen.getByRole("button", { name: "伏せ字を確かめる" }),
    );
    await screen.findByText("送られる文（Claude に届く形）");
    await userEvent.click(
      screen.getByRole("button", { name: "伏せ字「磯鷲さん」を戻す" }),
    );
    expect(screen.queryByText("送られる文（Claude に届く形）")).toBeNull();
  });

  it("保存 → 再変換 → 変換ログの画面へ（区間と確かめだけを送る）", async () => {
    const fetchMock = mockApi({
      [GET]: listing(),
      [CHECK]: fixtureBody("doctor_masks_check") as object,
      [SAVE]: { ok: true, sendable: 1 },
      [REGEN]: { ok: true },
    });
    renderRoute(PATH, ROUTE, <Unprocessed />);
    expect(await screen.findByText(/1〜2分かかります/)).toBeInTheDocument();
    await chooseSend();
    await userEvent.click(
      screen.getByRole("button", { name: "伏せ字を確かめる" }),
    );
    await userEvent.click(
      await screen.findByLabelText("個人を特定する語は無いことを確かめた"),
    );
    await userEvent.click(screen.getByRole("button", { name: SUBMIT }));
    await waitFor(() =>
      expect(screen.getByTestId("where")).toHaveTextContent(
        /^\/doctor\/pipeline\/12$/,
      ),
    );
    expect(bodiesOf(fetchMock, SAVE)).toEqual([
      {
        entries: [
          {
            entry_id: 38,
            send: true,
            spans: [{ start: 0, end: 4 }],
            confirmed_clear: true,
          },
        ],
      },
    ]);
    expect(countOf(fetchMock, REGEN)).toBe(1);
  });

  it("送れる記録が無ければ変換しない", async () => {
    const fetchMock = mockApi({
      [GET]: listing(),
      [SAVE]: { ok: true, sendable: 0 },
      [REGEN]: { ok: true },
    });
    renderRoute(PATH, ROUTE, <Unprocessed />);
    await chooseSend();
    await userEvent.click(screen.getByRole("button", { name: SUBMIT }));
    expect(await screen.findByText(/変換はしていません/)).toBeInTheDocument();
    expect(countOf(fetchMock, REGEN)).toBe(0);
    expect(screen.getByTestId("where")).toHaveTextContent(PATH);
  });

  it("保存できなければ code を出す（印刷済み・期限切れ）", async () => {
    mockApi({
      [GET]: listing(),
      [SAVE]: () => jsonResponse({ error: "visit_closed" }, 409),
    });
    renderRoute(PATH, ROUTE, <Unprocessed />);
    await chooseSend();
    await userEvent.click(screen.getByRole("button", { name: SUBMIT }));
    expect(await screen.findByRole("alert")).toHaveTextContent("visit_closed");
  });

  it("保存済みの伏せ字があれば「送る」で、その区間を出す", async () => {
    mockApi({
      "GET /api/doctor/visits/1/unprocessed": fixtureBody(
        "doctor_unprocessed_masked",
      ) as object,
    });
    renderRoute("/doctor/unprocessed/1", ROUTE, <Unprocessed />);
    expect(await screen.findByLabelText("送る（伏せて）")).toBeChecked();
    expect(
      screen.getByRole("button", { name: "伏せ字「磯鷲」を戻す" }),
    ).toBeInTheDocument();
  });

  it("生成中の受診では変換し直しを押せない", async () => {
    mockApi({
      [GET]: {
        visit: visitHeaderStub({ status: "generating" }),
        entries: [item()],
      },
    });
    renderRoute(PATH, ROUTE, <Unprocessed />);
    await chooseSend();
    expect(screen.getByRole("button", { name: SUBMIT })).toBeDisabled();
    expect(screen.getByText(/変換の最中です/)).toBeInTheDocument();
  });

  it("変換し直さない時のために印刷の欄は残す", async () => {
    mockApi({ [GET]: listing() });
    renderRoute(PATH, ROUTE, <Unprocessed />);
    expect(
      await screen.findByRole("region", { name: "この受診のレポート" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: "伏せ字にして変換し直す" }),
    ).toBeInTheDocument();
  });
});
