import type { KeyboardEvent } from "react";
import type { FieldIssue, RegimenDraft } from "../../../api/regimenTypes";
import { H1_BLOCKED_TEXT, blockedWhere } from "./chatLabels";
import { activeAsk } from "./fieldState";

/** 1回に送れる文の長さ（backend の MAX_TURN_TEXT）。 */
export const TURN_TEXT_MAX = 1000;

interface ChatInputProps {
  draft: RegimenDraft;
  busy: boolean;
  blocked: readonly FieldIssue[] | null;
  notice: string | null;
  text: string;
  onText: (text: string) => void;
  onSend: () => void;
}

/** IME の変換を確定する Enter（送らない）。 */
function isComposing(event: KeyboardEvent<HTMLTextAreaElement>): boolean {
  return event.nativeEvent.isComposing || event.keyCode === 229;
}

/**
 * チャットの入力欄。⌘+Enter（Ctrl+Enter）か「送る」で送る。Enter・Shift+Enter・Option+Enter は
 * ブラウザのまま改行する（途中で送ってしまわないため）。変換中は送らない。
 * H1 に掛かったときは入力の文を返さず決まった文で知らせ、入力欄の文は残す。
 */
export default function ChatInput({
  draft,
  busy,
  blocked,
  notice,
  text,
  onText,
  onSend,
}: ChatInputProps) {
  const ask = activeAsk(draft);
  const existing = draft.base_version !== null;

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    const sendKey = event.metaKey || event.ctrlKey;
    if (event.key !== "Enter" || !sendKey || isComposing(event)) {
      return;
    }
    event.preventDefault();
    onSend();
  }

  return (
    <div className="rf-chat-input">
      {blocked ? (
        <p className="rf-blocked" role="alert">
          {H1_BLOCKED_TEXT}
          {blocked.length > 0 ? (
            <span className="rf-blocked-where">
              掛かった場所:{" "}
              {[...new Set(blocked.map((b) => blockedWhere(b.field_id)))].join(
                "・",
              )}
              （{[...new Set(blocked.map((b) => b.message))].join("・")}）
            </span>
          ) : null}
        </p>
      ) : null}
      {notice ? (
        <p className="rf-notice" role="status">
          {notice}
        </p>
      ) : null}
      <label htmlFor="rf-chat-text" className="rf-field-label">
        {existing
          ? `このレジメンを直す（版 ${draft.version} の下書きになります）`
          : "Claude に伝える"}
      </label>
      <textarea
        id="rf-chat-text"
        rows={3}
        value={text}
        maxLength={TURN_TEXT_MAX}
        placeholder={
          ask
            ? "答えを書くか、上の選択肢を押す"
            : existing
              ? "例: 口内炎は、食事がとれたかも聞いて"
              : "例: FOLFIRI＋BV を作りたい。14日ごと"
        }
        onChange={(e) => onText(e.target.value)}
        onKeyDown={onKeyDown}
      />
      <div className="rf-chat-actions">
        <span className="rf-chat-hint">
          ⌘+Enter（Ctrl+Enter）で送る · Enter で改行
        </span>
        <button
          type="button"
          className="d-primary"
          disabled={busy || text.trim() === ""}
          onClick={onSend}
        >
          送る
        </button>
      </div>
    </div>
  );
}
