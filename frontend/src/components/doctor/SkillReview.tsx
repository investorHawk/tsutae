import { isUsableDiff } from "./diff";
import DiffView from "./DiffView";
import ErrorNote from "./ErrorNote";
import { skillDisplayName } from "./skillLabels";

export interface ReviewTarget {
  id: number;
  skillName: string;
  requestText: string;
  diff: string;
}

interface SkillReviewProps {
  target: ReviewTarget;
  busy: boolean;
  error: string | null;
  onApprove: () => void;
  onReject: () => void;
}

/** D4 の差分の確認。承認で本体に反映、却下で一時コピーを捨てる。 */
export default function SkillReview({
  target,
  busy,
  error,
  onApprove,
  onReject,
}: SkillReviewProps) {
  return (
    <section className="d-review" aria-label="差分の確認">
      <h2>差分を確認（#{target.id}）</h2>
      <p>
        <strong>{skillDisplayName(target.skillName)}</strong>（
        <code className="d-skill-code">{target.skillName}</code>
        ）への依頼「{target.requestText}」
      </p>
      <DiffView diff={target.diff} />
      <p className="d-muted">
        承認すると Skill の version
        が上がり、次の記録から反映されます（それまでの記録は記録したときの質問集のまま）。
        却下すると一時コピーを捨てます（本体は変わりません）。
      </p>
      <div className="d-actions">
        <button
          type="button"
          className="d-primary"
          disabled={busy || !isUsableDiff(target.diff)}
          onClick={onApprove}
        >
          承認する
        </button>
        <button type="button" disabled={busy} onClick={onReject}>
          却下する
        </button>
      </div>
      {error ? <ErrorNote code={error} prefix="決められませんでした" /> : null}
    </section>
  );
}
