import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import DiffView from "./DiffView";

const DIFF = [
  "--- a/regimen-folfox/SKILL.md",
  "+++ b/regimen-folfox/SKILL.md",
  "@@ -3,3 +3,4 @@",
  "-version: 1",
  "+version: 2",
  "+  - {key: stomatitis_meal, text: 食事はとれましたか}",
  " regimen: FOLFOX",
].join("\n");

describe("DiffView", () => {
  it("+ の行は緑（d-diff-add）、- の行は赤（d-diff-del）", () => {
    render(<DiffView diff={DIFF} />);
    expect(screen.getByText("+version: 2")).toHaveClass("d-diff-add");
    // 連続する空白は Testing Library が1つに詰めて比べる
    expect(
      screen.getByText("+ - {key: stomatitis_meal, text: 食事はとれましたか}"),
    ).toHaveClass("d-diff-add");
    expect(screen.getByText("-version: 1")).toHaveClass("d-diff-del");
  });

  it("見出し・塊・そのままの行は色を付けない", () => {
    render(<DiffView diff={DIFF} />);
    const hunk = screen.getByText("@@ -3,3 +3,4 @@");
    expect(hunk).toHaveClass("d-diff-hunk");
    expect(hunk).not.toHaveClass("d-diff-add");
    const header = screen.getByText("--- a/regimen-folfox/SKILL.md");
    expect(header).toHaveClass("d-diff-meta");
    expect(header).not.toHaveClass("d-diff-del");
    const context = screen.getByText("regimen: FOLFOX", { exact: false });
    expect(context).not.toHaveClass("d-diff-add");
    expect(context).not.toHaveClass("d-diff-del");
  });

  it("追加・削除の行数を出す", () => {
    render(<DiffView diff={DIFF} />);
    expect(screen.getByText("追加 2 行 / 削除 1 行")).toBeInTheDocument();
  });

  it("差分が空なら「変更はありません」", () => {
    render(<DiffView diff="" />);
    expect(screen.getByText("変更はありません")).toBeInTheDocument();
  });
});
