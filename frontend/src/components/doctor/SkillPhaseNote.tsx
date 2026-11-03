import { useEffect, useState } from "react";
import type { SkillChange } from "../../api/types";
import ErrorNote from "./ErrorNote";
import { elapsedSeconds } from "./skillChangeWork";
import type { SkillPhase } from "./useSkillChangeFlow";

/** 経過秒（1秒ごとに描き直す。生成中の間だけ置く）。 */
function Elapsed({ startedAt }: { startedAt: number }) {
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  return <>経過 {elapsedSeconds(startedAt, nowMs)} 秒</>;
}

interface SkillPhaseNoteProps {
  phase: SkillPhase;
  history: readonly SkillChange[];
}

/** D4 の段階の表示（生成中・承認・却下・失敗）。差分の確認は SkillReview。 */
export default function SkillPhaseNote({
  phase,
  history,
}: SkillPhaseNoteProps) {
  switch (phase.kind) {
    case "generating":
      return (
        <div role="status" className="d-generating">
          <span className="d-spinner" aria-hidden="true" />
          生成中… Claude が <code>{phase.skillName}</code>{" "}
          の一時コピーを書き換え、差分を作っています。数分かかることがあります。この画面のままお待ちください（
          <Elapsed startedAt={phase.startedAt} />）
        </div>
      );
    case "approved":
      return (
        <p role="status" className="d-ok d-big-note">
          承認しました。<code>{phase.skillName}</code> は version{" "}
          {phase.newVersion}{" "}
          になりました。次の記録から反映されます（それまでの記録は記録したときの質問集のまま）。
        </p>
      );
    case "rejected":
      return (
        <p role="status" className="d-big-note">
          却下しました。<code>{phase.skillName}</code>{" "}
          は変わっていません（一時コピーを捨てました）。
        </p>
      );
    case "failed": {
      const found = history.find((c) => c.id === phase.changeId);
      return (
        <ErrorNote
          code={found?.error_code ?? phase.code}
          prefix="書き換えに失敗しました"
        />
      );
    }
    default:
      return null;
  }
}
