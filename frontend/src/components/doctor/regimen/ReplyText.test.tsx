/**
 * Claude の返答の描き方。本物の返答（docs/eval/demo-regimen-*.json の turns[].reply）を全部
 * 描き、記法の記号が残らず、文字が欠けないことを確かめる。
 */
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import ReplyText from "./ReplyText";

interface DemoRegimen {
  turns: { reply: string | null }[];
}

const DEMOS = import.meta.glob<DemoRegimen>(
  "../../../../../docs/eval/demo-regimen-*.json",
  { eager: true, import: "default" },
);

const REPLIES: [string, string][] = Object.entries(DEMOS).flatMap(
  ([path, demo]) =>
    demo.turns
      .map((turn, n) => [`${path.replace(/^.*\//, "")}#${n}`, turn.reply])
      .filter((pair): pair is [string, string] => typeof pair[1] === "string"),
);

function draw(text: string): HTMLElement {
  return render(
    <div>
      <ReplyText text={text} />
    </div>,
  ).container.firstElementChild as HTMLElement;
}

/** 記法の記号（太字・行頭の項目・表の | と区切りの行）と空白を除いた文字。 */
function plain(text: string): string {
  return text
    .split("\n")
    .filter((line) => !/^\s*\|(\s*:?-+:?\s*\|)+\s*$/.test(line))
    .map((line) => line.replace(/^\s*(-|\d+\.) /, ""))
    .join("")
    .replace(/\*\*/g, "")
    .replace(/\|/g, "")
    .replace(/\s/g, "");
}

describe("ReplyText: 本物の返答", () => {
  it("返答が3件以上ある", () => {
    expect(REPLIES.length).toBeGreaterThanOrEqual(3);
  });

  it.each(REPLIES)("%s: 記号が残らず、文字が欠けない", (_name, reply) => {
    const box = draw(reply);
    const shown = box.textContent ?? "";
    expect(shown).not.toContain("**");
    expect(shown).not.toContain("|");
    expect(shown.replace(/\s/g, "")).toBe(plain(reply));
    for (const li of box.querySelectorAll("li")) {
      expect(li.textContent).not.toMatch(/^\s*(-|\d+\.) /);
    }
    expect(box.querySelectorAll("li").length).toBeGreaterThan(0);
  });

  it.each(REPLIES)("%s: 記法が塊の要素になる", (_name, reply) => {
    const box = draw(reply);
    const has = (selector: string) => box.querySelector(selector) !== null;
    expect(has("table thead th")).toBe(/^\|/m.test(reply));
    expect(has("ol > li")).toBe(/^ *\d+\. /m.test(reply));
    expect(has("ul > li")).toBe(/^ *- /m.test(reply));
    expect(has("li > ul > li")).toBe(/^ +- /m.test(reply));
    expect(has("strong")).toBe(reply.includes("**"));
  });

  it.each(REPLIES)("%s: 塊の間に空白だけの文字を残さない", (_name, reply) => {
    const box = draw(reply);
    const walker = document.createTreeWalker(box, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      expect(walker.currentNode.textContent?.trim()).not.toBe("");
    }
    for (const p of box.querySelectorAll("p")) {
      expect(p.textContent).toBe(p.textContent?.trim());
    }
  });
});

describe("ReplyText: 塊ごとの要素", () => {
  it("段落（改行を保つ）・箇条書き・入れ子・番号付き・太字", () => {
    const box = draw(
      "**まとめ**\n二行目\n- **基本:** 14日\n  - Day1\n1. ベバシズマブ\n2. イリノテカン",
    );
    const p = box.querySelector("p");
    expect(p?.textContent).toBe("まとめ\n二行目");
    expect(p?.querySelector("strong")?.textContent).toBe("まとめ");
    const ul = box.querySelector(":scope > ul");
    expect(ul?.querySelector("li strong")?.textContent).toBe("基本:");
    expect(ul?.querySelector("li > ul > li")?.textContent).toBe("Day1");
    const ol = box.querySelector(":scope > ol");
    expect(
      [...(ol?.querySelectorAll("li") ?? [])].map((li) => li.textContent),
    ).toEqual(["ベバシズマブ", "イリノテカン"]);
    expect(ol).not.toHaveAttribute("start");
  });

  it("番号付きが 1 以外で始まるなら start", () => {
    expect(draw("3. a").querySelector("ol")).toHaveAttribute("start", "3");
  });

  it("表は見出しの行が th（scope=col）・本文が td。セルの太字も描く", () => {
    const box = draw("| 症状 | 用語 |\n|---|---|\n| **下痢** | 下痢 |");
    const table = box.querySelector("table");
    expect(
      [...(table?.querySelectorAll("thead th") ?? [])].map((th) => [
        th.textContent,
        th.getAttribute("scope"),
      ]),
    ).toEqual([
      ["症状", "col"],
      ["用語", "col"],
    ]);
    const cells = table?.querySelectorAll("tbody td") ?? [];
    expect([...cells].map((td) => td.textContent)).toEqual(["下痢", "下痢"]);
    expect(cells[0]?.querySelector("strong")).not.toBeNull();
  });

  it("崩れた表は記号のまま段落に出す", () => {
    const box = draw("| a | b |\n| 1 | 2 |");
    expect(box.querySelector("table")).toBeNull();
    expect(box.querySelector("p")?.textContent).toBe("| a | b |\n| 1 | 2 |");
  });

  it("HTML のような文字は文字のまま（要素にしない）", () => {
    const box = draw("<b>x</b>\n- <img src=x onerror=alert(1)>");
    expect(box.querySelector("b")).toBeNull();
    expect(box.querySelector("img")).toBeNull();
    expect(box.textContent).toContain("<b>x</b>");
  });
});
