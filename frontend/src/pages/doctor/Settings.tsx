import { useState } from "react";
import ErrorNote from "../../components/doctor/ErrorNote";
import SkillChangeHistory from "../../components/doctor/SkillChangeHistory";
import SkillPhaseNote from "../../components/doctor/SkillPhaseNote";
import SkillRequestForm from "../../components/doctor/SkillRequestForm";
import SkillReview from "../../components/doctor/SkillReview";
import { useDoctorApiError } from "../../components/doctor/useDoctorApiError";
import { useSkillCatalog } from "../../components/doctor/useSkillCatalog";
import { useSkillChangeFlow } from "../../components/doctor/useSkillChangeFlow";
import "../../components/doctor/doctor-ui.css";

/** D4 設定を変える。一文 → Agent SDK が SKILL.md の一時コピーを書き換え → 差分 → 承認／却下。 */
export default function Settings() {
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
  const skillName = catalog.skills.some((s) => s.name === chosen)
    ? chosen
    : (catalog.skills[0]?.name ?? "");
  const locked = phase.kind === "generating" || phase.kind === "review";

  return (
    <section className="page">
      <h1>設定を変える</h1>
      <p className="d-muted">
        質問集（regimen）やレポートの形式（report-format）を、一文で頼んで書き換えます。
        差分を見て承認したものだけが反映されます。
      </p>
      {catalog.skillsError ? (
        <ErrorNote
          code={catalog.skillsError}
          prefix="Skill の一覧を読み込めません"
        />
      ) : null}
      {catalog.historyError ? (
        <ErrorNote
          code={catalog.historyError}
          prefix="変更の履歴を読み込めません"
        />
      ) : null}
      <SkillRequestForm
        skills={catalog.skills}
        skillName={skillName}
        requestText={requestText}
        locked={locked}
        onSkillChange={setChosen}
        onTextChange={setRequestText}
        onSubmit={() => void flow.request(skillName, requestText.trim())}
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
    </section>
  );
}
