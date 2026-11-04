import { useEffect, useState } from "react";
import type { SkillChange } from "../../api/types";
import ErrorNote from "./ErrorNote";
import { elapsedSeconds } from "./skillChangeWork";
import { skillDisplayName, versionLabel } from "./skillLabels";
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

/** Skill の呼び名（太字）と内部名（小さく）。 */
function SkillName({ name }: { name: string }) {
  return (
    <>
      <strong>{skillDisplayName(name)}</strong>（
      <code className="d-skill-code">{name}</code>）
    </>
  );
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
          生成中… Claude が <SkillName name={phase.skillName} />{" "}
          の一時コピーを書き換え、差分を作っています。数分かかることがあります。この画面のままお待ちください（
          <Elapsed startedAt={phase.startedAt} />）
        </div>
      );
    case "approved":
      return (
        <p role="status" className="d-ok d-big-note">
          承認しました。
          <SkillName name={phase.skillName} /> は
          {`${versionLabel(phase.newVersion)}（version ${phase.newVersion}）になりました。`}
          次の記録から反映されます（それまでの記録は記録したときの質問集のまま）。
        </p>
      );
    case "rejected":
      return (
        <p role="status" className="d-big-note">
          却下しました。
          <SkillName name={phase.skillName} />{" "}
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
