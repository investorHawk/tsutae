import type { ChatAsk, RegimenDraft } from "../../../api/regimenTypes";
import TwoStepButton from "../TwoStepButton";

interface RegimenBarProps {
  draft: RegimenDraft;
  /** まだ答えていない Claude の ask（あれば確認へ進めない） */
  ask: ChatAsk | null;
  busy: boolean;
  /** AI が入れた値（標準の値）の、確認の画面の行の数 */
  aiCount: number;
  onConfirm: () => void;
  onDiscard: () => Promise<void>;
}

/**
 * 下のバー: 確認へ進む（未入力が 0 で、Claude の ask に答えた後で押せる）／下書きを捨てる
 * （画面内の確認）。
 */
export default function RegimenBar({
  draft,
  ask,
  busy,
  aiCount,
  onConfirm,
  onDiscard,
}: RegimenBarProps) {
  const missing = draft.missing.length;
  const note = ask
    ? missing > 0
      ? `Claude の質問に答えてください（赤枠の欄） · 未入力 ${missing}`
      : "Claude の質問に答えてください（赤枠の欄）"
    : missing > 0
      ? `未入力 ${missing}`
      : aiCount > 0
        ? `そろいました。AI が入れた ${aiCount} 行は確認の画面でも一覧にします`
        : "そろいました";
  return (
    <div className="rf-bar rf-bar--sticky">
      <button
        type="button"
        className="d-primary"
        disabled={busy || missing > 0 || ask !== null}
        onClick={onConfirm}
      >
        確認へ進む
      </button>
      <TwoStepButton
        label="下書きを捨てる"
        prompt="この下書きを捨てます（チャットの会話も消えます）。よろしいですか。"
        confirmLabel="捨てる"
        disabled={busy}
        onConfirm={onDiscard}
      />
      <span className="rf-bar-note" role="status">
        {note}
      </span>
    </div>
  );
}
