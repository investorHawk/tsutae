/**
 * Claude の返答の表（| a | b | の見出し・|---|---| の区切り・本文の行）を読む純関数。
 * 形が崩れていれば null を返し、呼ぶ側が元の文字のまま段落にする。
 */
export interface TableBlock {
  kind: "table";
  header: string[];
  rows: string[][];
}

/** 表の候補の行（前後の空白を除いて | で始まる）。 */
export function isTableLine(line: string): boolean {
  return line.trim().startsWith("|");
}

/** | で始まり | で終わる行のセル（前後の空白を除く）。そうでなければ null。 */
function cellsOf(line: string): string[] | null {
  const trimmed = line.trim();
  if (trimmed.length < 2 || !trimmed.endsWith("|")) {
    return null;
  }
  return trimmed
    .slice(1, -1)
    .split("|")
    .map((cell) => cell.trim());
}

const SEPARATOR_CELL = /^:?-+:?$/;

function isSeparator(cells: readonly string[]): boolean {
  return cells.every((cell) => SEPARATOR_CELL.test(cell));
}

/** 続いた表の候補の行（2行目が区切り・本文が1行以上・列の数がそろう）を表にする。 */
export function parseTable(lines: readonly string[]): TableBlock | null {
  const parsed = lines.map(cellsOf);
  const [header, separator, ...rows] = parsed;
  if (!header || !separator || rows.length === 0) {
    return null;
  }
  const width = header.length;
  if (separator.length !== width || !isSeparator(separator)) {
    return null;
  }
  const body: string[][] = [];
  for (const row of rows) {
    if (!row || row.length !== width || isSeparator(row)) {
      return null;
    }
    body.push(row);
  }
  return { kind: "table", header, rows: body };
}
