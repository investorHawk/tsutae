import type {
  AssistantChatRow,
  ChatRow,
  RegimenDraft,
} from "../../../api/regimenTypes";
import { turnFailureText } from "./chatLabels";
import { changeGroupOf } from "./fieldLabels";
import { isAiSource } from "./fieldState";
import ReplyText from "./ReplyText";

interface ChangeChip {
  key: string;
  label: string;
  fieldId: string;
  ai: boolean;
}

/** 変えた欄の札（基本は欄ごと、行は行ごとにまとめる。押す先はまとまりの最初の欄）。 */
function changeChips(draft: RegimenDraft, row: AssistantChatRow): ChangeChip[] {
  const chips = new Map<string, ChangeChip>();
  for (const fieldId of row.changed) {
    const group = changeGroupOf(draft.form, fieldId);
    const ai = isAiSource(draft.sources[fieldId]);
    const found = chips.get(group.key);
    if (found) {
      found.ai = found.ai || ai;
    } else {
      chips.set(group.key, { ...group, fieldId, ai });
    }
  }
  return [...chips.values()];
}

interface ChatMessageProps {
  row: ChatRow;
  draft: RegimenDraft;
  /** 会話の最後の行で、応答中でない（選択肢を押せる） */
  canAnswer: boolean;
  onJump: (fieldId: string) => void;
  onAnswer: (text: string) => void;
}

/** 会話の1行（先生の文・Claude の返答・往復の失敗）。 */
export default function ChatMessage({
  row,
  draft,
  canAnswer,
  onJump,
  onAnswer,
}: ChatMessageProps) {
  if (row.role === "doctor") {
    return (
      <li className="rf-msg rf-msg--doctor">
        <span className="rf-msg-who">先生</span>
        <div className="rf-bubble">{row.text}</div>
      </li>
    );
  }
  if (row.role === "system") {
    return (
      <li className="rf-msg rf-msg--system">
        <span className="rf-msg-who">失敗</span>
        <div className="rf-bubble" role="status">
          {turnFailureText(row.reason)}
          <span className="rf-msg-code">（{row.reason}）</span>
        </div>
      </li>
    );
  }
  const chips = changeChips(draft, row);
  return (
    <li className="rf-msg rf-msg--claude">
      <span className="rf-msg-who">Claude</span>
      <div className="rf-bubble">
        <ReplyText text={row.text} />
      </div>
      {chips.length > 0 ? (
        <div className="rf-chips" role="group" aria-label="変えた欄">
          {chips.map((chip) => (
            <button
              key={chip.key}
              type="button"
              className={chip.ai ? "rf-flink rf-flink--ai" : "rf-flink"}
              onClick={() => onJump(chip.fieldId)}
            >
              {chip.label}
              {chip.ai ? (
                <span className="rf-sr-only">（AI が入れた）</span>
              ) : null}
            </button>
          ))}
        </div>
      ) : null}
      {row.ask ? (
        <div className="rf-ask">
          <p className="rf-ask-q">{row.ask.question}</p>
          {row.ask.options.length > 0 ? (
            <div className="rf-chips" role="group" aria-label="選択肢">
              {row.ask.options.map((option) => (
                <button
                  key={option}
                  type="button"
                  className="rf-choice"
                  disabled={!canAnswer}
                  onClick={() => onAnswer(option)}
                >
                  {option}
                </button>
              ))}
            </div>
          ) : null}
          {canAnswer ? (
            <p className="rf-ask-hint">
              左の赤枠の欄に直接入れても答えになります
            </p>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}
