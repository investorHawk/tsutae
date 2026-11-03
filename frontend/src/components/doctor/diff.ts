/**
 * unified diff を行ごとに分ける（D4 の差分表示）。色分けは DiffView が行う。
 * 塊（@@）の外の `---` `+++` `diff` `index` はファイルの見出しとして扱う。塊の中は
 * 先頭の1文字だけで追加・削除を決める（本文が `---` で始まっても削除）。塊の終わりは
 * @@ の見出しの行数で決めるので、複数ファイルの diff の2つ目の見出しも見出しになる。
 */

export type DiffLineKind = "meta" | "hunk" | "add" | "del" | "context";

export interface DiffLine {
  kind: DiffLineKind;
  text: string;
}

export interface DiffStats {
  added: number;
  removed: number;
}

const HEADER_PREFIXES = ["---", "+++", "diff ", "index "];
const HUNK_HEADER = /^@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@/;

/** 塊の残りの行数（旧・新）。0 と 0 になったら塊の外（次のファイルの見出し）に戻る。 */
interface Remaining {
  old: number;
  new: number;
}

const OUTSIDE: Remaining = { old: 0, new: 0 };

function countsOf(header: string): Remaining {
  const match = HUNK_HEADER.exec(header);
  if (!match) {
    // 読めない塊の見出しは、次の diff 行まで塊の中として扱う
    return { old: Infinity, new: Infinity };
  }
  return { old: Number(match[1] ?? 1), new: Number(match[2] ?? 1) };
}

function inHunk(rest: Remaining): boolean {
  return rest.old > 0 || rest.new > 0;
}

function kindOf(line: string, rest: Remaining): DiffLineKind {
  if (line.startsWith("@@")) {
    return "hunk";
  }
  if (line.startsWith("\\")) {
    return "meta";
  }
  if (
    line.startsWith("diff ") ||
    (!inHunk(rest) && HEADER_PREFIXES.some((p) => line.startsWith(p)))
  ) {
    return "meta";
  }
  if (line.startsWith("+")) {
    return "add";
  }
  if (line.startsWith("-")) {
    return "del";
  }
  return "context";
}

/** その行を読んだ後の残りの行数。 */
function advance(rest: Remaining, kind: DiffLineKind, text: string): Remaining {
  switch (kind) {
    case "hunk":
      return countsOf(text);
    case "meta":
      return text.startsWith("diff ") ? OUTSIDE : rest;
    case "add":
      return { ...rest, new: rest.new - 1 };
    case "del":
      return { ...rest, old: rest.old - 1 };
    default:
      return { old: rest.old - 1, new: rest.new - 1 };
  }
}

export function parseUnifiedDiff(diff: string): DiffLine[] {
  if (diff.trim() === "") {
    return [];
  }
  const rows = diff.replace(/\r\n/g, "\n").split("\n");
  if (rows.length > 0 && rows[rows.length - 1] === "") {
    rows.pop();
  }
  let rest = OUTSIDE;
  return rows.map((text) => {
    const kind = kindOf(text, rest);
    rest = advance(rest, kind, text);
    return { kind, text };
  });
}

export function diffStats(lines: readonly DiffLine[]): DiffStats {
  return {
    added: lines.filter((line) => line.kind === "add").length,
    removed: lines.filter((line) => line.kind === "del").length,
  };
}

/**
 * 承認に回せる差分か。空・空白だけ・null は「変わらない書き換え」で、承認すると version
 * だけが上がりうるので失敗として扱う（docs/architecture.md §9 W2b の決定）。
 */
export function isUsableDiff(diff: string | null | undefined): diff is string {
  return typeof diff === "string" && diff.trim() !== "";
}
