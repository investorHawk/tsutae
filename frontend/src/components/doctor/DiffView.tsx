import { useMemo } from "react";
import { diffStats, parseUnifiedDiff, type DiffLineKind } from "./diff";

const LINE_CLASS: Readonly<Record<DiffLineKind, string>> = {
  add: "d-diff-add",
  del: "d-diff-del",
  hunk: "d-diff-hunk",
  meta: "d-diff-meta",
  context: "d-diff-context",
};

interface DiffViewProps {
  diff: string;
  label?: string;
}

/** unified diff を行ごとに色分けする（+ 緑・- 赤。記号も残すので色だけに頼らない）。 */
export default function DiffView({ diff, label = "差分" }: DiffViewProps) {
  const lines = useMemo(() => parseUnifiedDiff(diff), [diff]);
  if (lines.length === 0) {
    return <p className="d-muted">変更はありません</p>;
  }
  const { added, removed } = diffStats(lines);
  return (
    <figure className="d-diffview">
      <figcaption className="d-diffview-stats">
        追加 {added} 行 / 削除 {removed} 行
      </figcaption>
      <div className="d-diff" role="region" aria-label={label}>
        {lines.map((line, i) => (
          <div
            key={i}
            className={`d-diff-line ${LINE_CLASS[line.kind]}`}
            data-kind={line.kind}
          >
            {line.text === "" ? " " : line.text}
          </div>
        ))}
      </div>
    </figure>
  );
}
