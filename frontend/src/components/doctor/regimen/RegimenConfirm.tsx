import type { ChatAsk, RegimenDraft } from "../../../api/regimenTypes";
import DiffView from "../DiffView";
import ErrorNote from "../ErrorNote";
import TwoStepButton from "../TwoStepButton";
import { describeRegimenError } from "../errors";
import AiValueList from "./AiValueList";
import type { AiRow } from "./aiRows";
import PhonePreview from "./PhonePreview";
import type { RegimenConfirmApi } from "./useRegimenConfirm";

interface RegimenConfirmProps {
  draft: RegimenDraft;
  confirm: RegimenConfirmApi;
  /** Claude の応答中（確認・採用・破棄・削除を止める。spec 9.1 の手順5） */
  editorBusy: boolean;
  /** まだ答えていない Claude の ask（確認の画面で送った往復が聞き返したとき。採用を止める） */
  ask: ChatAsk | null;
  /** 一覧の「削除」（行を消すか、標準の値の欄を空にする直接編集）。必須が欠ければフォームへ戻る */
  onDeleteValue: (row: AiRow) => Promise<void>;
  onBack: () => void;
  onDiscard: () => Promise<void>;
  onAdopt: () => Promise<void>;
}

/**
 * 確認: AI が入れた値（行ごとの削除・チェック1回）→ SKILL.md（新規は全文、既存は版 N との
 * 差分）→ 患者のスマホの見本 → 採用。確かめは確認の画面の版（confirm_token）に結びつく。
 */
export default function RegimenConfirm({
  draft,
  confirm,
  editorBusy,
  ask,
  onDeleteValue,
  onBack,
  onDiscard,
  onAdopt,
}: RegimenConfirmProps) {
  const { preview } = confirm;
  if (!preview) {
    return confirm.error ? (
      <ErrorNote
        code={confirm.error}
        prefix="確認の画面を出せません"
        describe={describeRegimenError}
      />
    ) : (
      <p className="d-muted">確認の画面を作っています…</p>
    );
  }
  const existing = preview.base_version !== null;
  const needCheck = preview.ai_values.length > 0 && !confirm.confirmed;
  const issues = [...preview.issues, ...confirm.issues];
  const busy = confirm.adopting || confirm.loading || editorBusy;
  const cantAdopt =
    busy ||
    ask !== null ||
    preview.skill_md === null ||
    issues.length > 0 ||
    needCheck;
  const name =
    draft.form.basic.display_name ?? preview.skill_name ?? "新しいレジメン";
  return (
    <div className="rf-confirm">
      {preview.ai_values.length > 0 ? (
        <AiValueList
          values={preview.ai_values}
          questions={draft.form.questions}
          confirmed={confirm.confirmed}
          disabled={busy}
          onToggle={confirm.setConfirmed}
          onDelete={(row) => void onDeleteValue(row)}
        />
      ) : null}
      <div className="rf-confirm-grid">
        <section className="rf-section" aria-labelledby="rf-skill-h">
          <h3 id="rf-skill-h" tabIndex={-1}>
            {existing
              ? `SKILL.md の差分（版 ${preview.base_version} → 版 ${preview.version}）`
              : `SKILL.md（${preview.skill_name ?? "識別名が未入力"}・新規）`}
          </h3>
          <p className="d-muted rf-hint">
            フォームの値からコードが決まった形で描いたもの。AI は SKILL.md
            を書いていません。
          </p>
          {preview.skill_md === null ? (
            <p className="rf-empty">検査に掛かったため描けませんでした。</p>
          ) : preview.skill_md.kind === "diff" ? (
            <DiffView diff={preview.skill_md.text} label="SKILL.md の差分" />
          ) : (
            <pre
              className="rf-skill-md"
              role="region"
              aria-label="SKILL.md の全文"
              tabIndex={0}
            >
              {preview.skill_md.text}
            </pre>
          )}
          {issues.length > 0 ? (
            <div role="alert" className="rf-issues">
              <p>
                採用の前の検査に掛かりました。フォームに戻って直してください。
              </p>
              <ul>
                {issues.map((issue, i) => (
                  <li key={`${issue.field_id}-${issue.code}-${i}`}>
                    {issue.message}（<code>{issue.field_id}</code>）
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <p className="rf-ok">
              検査に通りました（必須の項目・CTCAE の用語・質問の
              key・個人を特定しうる表現の検査）
            </p>
          )}
        </section>
        <PhonePreview regimenName={name} questions={preview.patient_preview} />
      </div>
      {confirm.error ? (
        <ErrorNote
          code={confirm.error}
          prefix="採用できませんでした"
          describe={describeRegimenError}
        />
      ) : null}
      <div className="rf-bar">
        <button
          type="button"
          className="d-primary"
          disabled={cantAdopt}
          onClick={() => void onAdopt()}
        >
          {existing ? `採用して版 ${preview.version} にする` : "採用して登録"}
        </button>
        <button type="button" disabled={busy} onClick={onBack}>
          フォームに戻る
        </button>
        <TwoStepButton
          label="下書きを捨てる"
          prompt="この下書きを捨てます（チャットの会話も消えます）。よろしいですか。"
          confirmLabel="捨てる"
          disabled={busy}
          onConfirm={onDiscard}
        />
        <span className="rf-bar-note">
          {ask
            ? "Claude の質問に答えてください（チャットか、フォームに戻って赤枠の欄）"
            : needCheck
              ? "「上の値を全て確かめました」に印を付けると採用できます"
              : "採用するまで患者の画面は変わりません"}
        </span>
      </div>
    </div>
  );
}
