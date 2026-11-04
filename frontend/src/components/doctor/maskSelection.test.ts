import { afterEach, describe, expect, it } from "vitest";
import { selectionSpan } from "./maskSelection";

/** MaskEditor と同じ形の表示: 「😀磯鷲」[伏せ字 = 「さん」]「と漢方」。 */
function editor(): HTMLElement {
  const box = document.createElement("div");
  box.innerHTML =
    '<span data-start="0" data-end="3">😀磯鷲</span>' +
    '<button type="button" data-start="3" data-end="5">伏せ字</button>' +
    '<span data-start="5" data-end="8">と漢方</span>';
  document.body.append(box);
  return box;
}

function select(start: [Node, number], end: [Node, number]): Selection {
  const range = document.createRange();
  range.setStart(...start);
  range.setEnd(...end);
  const selection = window.getSelection() as Selection;
  selection.removeAllRanges();
  selection.addRange(range);
  return selection;
}

afterEach(() => {
  window.getSelection()?.removeAllRanges();
  document.body.innerHTML = "";
});

describe("selectionSpan", () => {
  it("文字の中の選択を code point の区間にする", () => {
    const box = editor();
    const text = box.children[0].firstChild as Text;
    // 「磯鷲」は UTF-16 で 2〜4、code point で 1〜3
    expect(selectionSpan(box, select([text, 2], [text, 4]), 8)).toEqual({
      start: 1,
      end: 3,
    });
  });

  it("伏せた区間にかかる選択は、その区間を含める", () => {
    const box = editor();
    const first = box.children[0].firstChild as Text;
    const mask = box.children[1].firstChild as Text;
    expect(selectionSpan(box, select([first, 2], [mask, 1]), 8)).toEqual({
      start: 1,
      end: 5,
    });
  });

  it("表示の要素の境目（子の番号）でも位置を出す", () => {
    const box = editor();
    expect(selectionSpan(box, select([box, 0], [box, 3]), 8)).toEqual({
      start: 0,
      end: 8,
    });
  });

  it("空の選択・表示の外の選択は null", () => {
    const box = editor();
    const text = box.children[0].firstChild as Text;
    expect(selectionSpan(box, select([text, 1], [text, 1]), 8)).toBeNull();
    const outside = document.createElement("p");
    outside.textContent = "外の文";
    document.body.append(outside);
    const node = outside.firstChild as Text;
    expect(selectionSpan(box, select([node, 0], [node, 2]), 8)).toBeNull();
    expect(selectionSpan(box, null, 8)).toBeNull();
  });
});
