import { describe, expect, it } from "vitest";
import { diffStats, parseUnifiedDiff } from "./diff";

const SAMPLE = [
  "--- a/regimen-folfox/SKILL.md",
  "+++ b/regimen-folfox/SKILL.md",
  "@@ -1,4 +1,5 @@",
  " ---",
  "-version: 1",
  "+version: 2",
  "+  - {key: stomatitis_meal, text: 食事はとれましたか, answer_type: three_level}",
  " name: regimen-folfox",
  "\\ No newline at end of file",
  "",
].join("\n");

describe("parseUnifiedDiff", () => {
  it("行を種類（見出し・塊・削除・追加・そのまま）に分ける", () => {
    expect(parseUnifiedDiff(SAMPLE).map((line) => line.kind)).toEqual([
      "meta",
      "meta",
      "hunk",
      "context",
      "del",
      "add",
      "add",
      "context",
      "meta",
    ]);
  });

  it("行の文字はそのまま持つ（記号も残す）", () => {
    const lines = parseUnifiedDiff(SAMPLE);
    expect(lines[4]).toEqual({ kind: "del", text: "-version: 1" });
    expect(lines[5]).toEqual({ kind: "add", text: "+version: 2" });
  });

  it("最初の @@ より後は --- や +++ で始まっても削除・追加", () => {
    const diff = "--- a/x\n+++ b/x\n@@ -1 +1 @@\n----\n++++\n";
    expect(parseUnifiedDiff(diff).map((line) => line.kind)).toEqual([
      "meta",
      "meta",
      "hunk",
      "del",
      "add",
    ]);
  });

  it("2つ目のファイルの見出しも見出しとして扱い、行数に数えない", () => {
    const diff = [
      "--- a/x",
      "+++ b/x",
      "@@ -1 +1 @@",
      "-a",
      "+b",
      "--- a/y",
      "+++ b/y",
      "@@ -1 +1 @@",
      "-c",
      "+d",
      "",
    ].join("\n");
    const lines = parseUnifiedDiff(diff);
    expect(lines.map((line) => line.kind)).toEqual([
      "meta",
      "meta",
      "hunk",
      "del",
      "add",
      "meta",
      "meta",
      "hunk",
      "del",
      "add",
    ]);
    expect(diffStats(lines)).toEqual({ added: 2, removed: 2 });
  });

  it("git 形式の diff 行で次のファイルに移る", () => {
    const diff = [
      "diff --git a/x b/x",
      "--- a/x",
      "+++ b/x",
      "@@ -1 +1 @@",
      "-a",
      "diff --git a/y b/y",
      "index 1234567..89abcde 100644",
      "--- a/y",
      "+++ b/y",
      "@@ -1 +1 @@",
      "+d",
    ].join("\n");
    expect(parseUnifiedDiff(diff).map((line) => line.kind)).toEqual([
      "meta",
      "meta",
      "meta",
      "hunk",
      "del",
      "meta",
      "meta",
      "meta",
      "meta",
      "hunk",
      "add",
    ]);
  });

  it("塊の中の本文の ---（次行が +++ でない）は削除のまま", () => {
    const diff = "@@ -1,2 +1 @@\n--- a\n-b\n";
    expect(parseUnifiedDiff(diff).map((line) => line.kind)).toEqual([
      "hunk",
      "del",
      "del",
    ]);
  });

  it("CRLF の改行も扱う", () => {
    const diff = "@@ -1 +1 @@\r\n-a\r\n+b\r\n";
    expect(parseUnifiedDiff(diff)).toEqual([
      { kind: "hunk", text: "@@ -1 +1 @@" },
      { kind: "del", text: "-a" },
      { kind: "add", text: "+b" },
    ]);
  });

  it("空の差分は空の配列", () => {
    expect(parseUnifiedDiff("")).toEqual([]);
    expect(parseUnifiedDiff("\n")).toEqual([]);
  });
});

describe("diffStats", () => {
  it("追加と削除の行数を数える（見出しは数えない）", () => {
    expect(diffStats(parseUnifiedDiff(SAMPLE))).toEqual({
      added: 2,
      removed: 1,
    });
  });
});
