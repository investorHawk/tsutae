import { useState } from "react";
import ErrorNote from "../../components/doctor/ErrorNote";
import SkillChangeHistory from "../../components/doctor/SkillChangeHistory";
import SkillContentPanel from "../../components/doctor/SkillContentPanel";
import SkillInvalidList from "../../components/doctor/SkillInvalidList";
import SkillPhaseNote from "../../components/doctor/SkillPhaseNote";
import SkillRequestForm from "../../components/doctor/SkillRequestForm";
import SkillReview from "../../components/doctor/SkillReview";
import SkillSteps from "../../components/doctor/SkillSteps";
import { useDoctorApiError } from "../../components/doctor/useDoctorApiError";
import { useSkillCatalog } from "../../components/doctor/useSkillCatalog";
import { useSkillChangeFlow } from "../../components/doctor/useSkillChangeFlow";
import { useSkillChangeWatch } from "../../components/doctor/useSkillChangeWatch";
import { useSkillContent } from "../../components/doctor/useSkillContent";
import { isReportFormatSkill } from "../../components/doctor/skillLabels";
import "../../components/doctor/doctor-ui.css";
import "../../components/doctor/settings.css";

/** 最初に選んでおく形式（無ければ一覧の先頭） */
const DEFAULT_SKILL = "report-format-default";

/**
 * D4「レポートの形式」（v1.1。旧 D4 の一文の書き換え）。選べるのは report-format-* だけで、
 * レジメンは D4 レジメンの画面（フォームとチャット）で直す（spec 9.2）。一文 → Agent SDK が SKILL.md の一時コピーを書き換え → 差分 → 承認／却下。
 * 履歴に作業中（pending・diff なし）の変更があれば、終わるまで生成中と出してフォームを止める。
 * 上に「依頼を書く → 差分を見る → 承認して反映」の段階を出し、依頼の前に選んだ Skill の
 * 今の中身（読み取り専用）を見せる。
 */
export default function ReportFormatSettings() {
  const handleError = useDoctorApiError();
  const catalog = useSkillCatalog(handleError);
  const [chosen, setChosen] = useState("");
  const [requestText, setRequestText] = useState("");
  const flow = useSkillChangeFlow({
    handleError,
    onCreated: () => void catalog.reloadHistory(),
    onDecided: (approved) => {
      if (approved) {
        setRequestText("");
      }
      void catalog.reloadSkills();
      void catalog.reloadHistory();
    },
  });
  const { phase } = flow;
  useSkillChangeWatch({
    phase,
    history: catalog.history,
    reloadHistory: catalog.reloadHistory,
    watch: flow.watch,
    settle: flow.settle,
  });
  const skills = catalog.skills.filter((s) => isReportFormatSkill(s.name));
  const skillName = skills.some((s) => s.name === chosen)
    ? chosen
    : (skills.find((s) => s.name === DEFAULT_SKILL)?.name ??
      skills[0]?.name ??
      "");
  const locked = phase.kind === "generating" || phase.kind === "review";
  const version = skills.find((s) => s.name === skillName)?.version ?? null;
  const content = useSkillContent(skillName, version, handleError);

  return (
    <div className="d-report-format">
      <p className="d-muted">
        レポートの形式（report-format）を、一文で頼んで書き換えます。
        差分を見て承認したものだけが反映されます。レジメンは「レジメン」のタブで直します。
      </p>
      <SkillSteps phase={phase} />
      {catalog.skillsError ? (
        <ErrorNote
          code={catalog.skillsError}
          prefix="Skill の一覧を読み込めません"
        />
      ) : null}
      <SkillInvalidList items={catalog.invalid} />
      {catalog.historyError ? (
        <ErrorNote
          code={catalog.historyError}
          prefix="変更の履歴を読み込めません"
        />
      ) : null}
      <SkillRequestForm
        skills={skills}
        skillName={skillName}
        requestText={requestText}
        locked={locked}
        onSkillChange={setChosen}
        onTextChange={setRequestText}
        onSubmit={() => void flow.request(skillName, requestText.trim())}
        preview={
          <SkillContentPanel
            skillName={skillName}
            version={version}
            state={content}
          />
        }
      />
      <SkillPhaseNote phase={phase} history={catalog.history ?? []} />
      {phase.kind === "review" ? (
        <SkillReview
          target={phase.target}
          busy={phase.busy}
          error={phase.error}
          onApprove={() => void flow.decide(true)}
          onReject={() => void flow.decide(false)}
        />
      ) : null}
      <h2>履歴</h2>
      {catalog.history ? (
        <SkillChangeHistory changes={catalog.history} onReview={flow.review} />
      ) : null}
    </div>
  );
}
