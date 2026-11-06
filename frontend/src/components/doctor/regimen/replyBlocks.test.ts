import { describe, expect, it } from "vitest";
import { replyBlocks } from "./replyBlocks";

describe("replyBlocks: 段落", () => {
  it("空の文は塊なし", () => {
    expect(replyBlocks("")).toEqual([]);
    expect(replyBlocks("\n\n")).toEqual([]);
  });

  it("空行で段落を分け、段落の中の改行は保つ", () => {
    expect(replyBlocks("一行目\n二行目\n\n三行目")).toEqual([
      { kind: "paragraph", text: "一行目\n二行目" },
      { kind: "paragraph", text: "三行目" },
    ]);
  });

  it("CRLF も行として分ける", () => {
    expect(replyBlocks("a\r\nb")).toEqual([
      { kind: "paragraph", text: "a\nb" },
    ]);
  });

  it("「-」の後に空白が無い行・横線は段落のまま", () => {
    expect(replyBlocks("-5mg\n---\n*注意*")).toEqual([
      { kind: "paragraph", text: "-5mg\n---\n*注意*" },
    ]);
  });
});

describe("replyBlocks: 箇条書き・番号付き", () => {
  it("段落の直後の箇条書き", () => {
    expect(replyBlocks("次の2つです。\n- 下痢\n- 口内炎\n\n以上")).toEqual([
      { kind: "paragraph", text: "次の2つです。" },
      {
        kind: "list",
        ordered: false,
        start: 1,
        items: [
          { text: "下痢", children: [] },
          { text: "口内炎", children: [] },
        ],
      },
      { kind: "paragraph", text: "以上" },
    ]);
  });

  it("字下げの入れ子（2段）と、浅い段へ戻る", () => {
    const text = "- 投与:\n  - Day1\n    - 点滴\n  - Day2\n- 質問";
    expect(replyBlocks(text)).toEqual([
      {
        kind: "list",
        ordered: false,
        start: 1,
        items: [
          {
            text: "投与:",
            children: [
              {
                kind: "list",
                ordered: false,
                start: 1,
                items: [
                  {
                    text: "Day1",
                    children: [
                      {
                        kind: "list",
                        ordered: false,
                        start: 1,
                        items: [{ text: "点滴", children: [] }],
                      },
                    ],
                  },
                  { text: "Day2", children: [] },
                ],
              },
            ],
          },
          { text: "質問", children: [] },
        ],
      },
    ]);
  });

  it("番号付き（始まりの番号を持つ）", () => {
    expect(replyBlocks("3. ベバシズマブ\n4. イリノテカン")).toEqual([
      {
        kind: "list",
        ordered: true,
        start: 3,
        items: [
          { text: "ベバシズマブ", children: [] },
          { text: "イリノテカン", children: [] },
        ],
      },
    ]);
  });

  it("同じ段で種類が変わったら別の並びにする", () => {
    const blocks = replyBlocks("- a\n1. b\n  - c\n  2. d");
    expect(blocks.map((b) => b.kind === "list" && b.ordered)).toEqual([
      false,
      true,
    ]);
    const second = blocks[1];
    expect(second.kind === "list" && second.items[0].children).toEqual([
      {
        kind: "list",
        ordered: false,
        start: 1,
        items: [{ text: "c", children: [] }],
      },
      {
        kind: "list",
        ordered: true,
        start: 2,
        items: [{ text: "d", children: [] }],
      },
    ]);
  });

  it("字下げした続きの行は項目の文に足す・字下げの無い行で並びを終える", () => {
    expect(replyBlocks("- 一つ目\n  続き\nおわり")).toEqual([
      {
        kind: "list",
        ordered: false,
        start: 1,
        items: [{ text: "一つ目\n続き", children: [] }],
      },
      { kind: "paragraph", text: "おわり" },
    ]);
  });

  it("中身の無い項目「- 」も項目にする", () => {
    expect(replyBlocks("- ")).toEqual([
      {
        kind: "list",
        ordered: false,
        start: 1,
        items: [{ text: "", children: [] }],
      },
    ]);
  });
});

describe("replyBlocks: 表", () => {
  it("見出し・区切り・本文の行（セルの前後の空白は除く）", () => {
    const text = "| 症状 | 用語 |\n|---|:---:|\n| 下痢 | 下痢 |\n| 熱 |  |";
    expect(replyBlocks(text)).toEqual([
      {
        kind: "table",
        header: ["症状", "用語"],
        rows: [
          ["下痢", "下痢"],
          ["熱", ""],
        ],
      },
    ]);
  });

  it("段落の直後・直前の表", () => {
    const blocks = replyBlocks("前\n| a |\n|---|\n| 1 |\n後");
    expect(blocks.map((b) => b.kind)).toEqual([
      "paragraph",
      "table",
      "paragraph",
    ]);
  });

  it.each([
    ["区切りの行が無い", "| a | b |\n| 1 | 2 |"],
    ["列の数が合わない", "| a | b |\n|---|---|\n| 1 | 2 | 3 |"],
    ["区切りの列の数が合わない", "| a | b |\n|---|\n| 1 | 2 |"],
    ["本文の行が無い", "| a | b |\n|---|---|"],
    ["途中で切れた行", "| a | b |\n|---|---|\n| 1 | 2"],
    ["本文に区切りの行", "| a |\n|---|\n| 1 |\n|---|"],
    ["| だけ", "|"],
  ])("形が崩れた表（%s）は元の文字のまま段落", (_name, text) => {
    expect(replyBlocks(text)).toEqual([{ kind: "paragraph", text }]);
  });

  it("崩れた表は前後の段落とつなげる（改行を保つ）", () => {
    expect(replyBlocks("前\n| a | b |\n後")).toEqual([
      { kind: "paragraph", text: "前\n| a | b |\n後" },
    ]);
  });
});

describe("replyBlocks: 引数", () => {
  it("同じ文には同じ塊（文を変えない）", () => {
    const text = "- a\n| x |\n|---|\n| 1 |";
    expect(replyBlocks(text)).toEqual(replyBlocks(text));
    expect(text).toBe("- a\n| x |\n|---|\n| 1 |");
  });
});
