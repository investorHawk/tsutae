import { useEffect, useRef, useState } from "react";
import type { FieldIssue, RegimenDraft } from "../../../api/regimenTypes";
import ChatInput from "./ChatInput";
import ChatMessage from "./ChatMessage";

interface RegimenChatProps {
  draft: RegimenDraft;
  busy: boolean;
  blocked: readonly FieldIssue[] | null;
  notice: string | null;
  onSend: (text: string) => Promise<boolean>;
  onJump: (fieldId: string) => void;
}

/**
 * 右のチャット（固定表示・新しい行で下へ送る）。1回送ると1回答える。応答中は送れない。
 * 選択肢を押すと、その文を送る。
 */
export default function RegimenChat({
  draft,
  busy,
  blocked,
  notice,
  onSend,
  onJump,
}: RegimenChatProps) {
  const [text, setText] = useState("");
  const logRef = useRef<HTMLOListElement>(null);
  const existing = draft.base_version !== null;

  useEffect(() => {
    const log = logRef.current;
    if (log) {
      log.scrollTop = log.scrollHeight;
    }
  }, [draft.chat.length, busy]);

  /** 入力欄の文を送ったときだけ、送れたら入力欄を空にする（選択肢は入力欄を触らない）。 */
  async function send(value: string, fromInput: boolean) {
    const body = value.trim();
    if (busy || body === "") {
      return;
    }
    if ((await onSend(body)) && fromInput) {
      setText("");
    }
  }

  const lastIndex = draft.chat.length - 1;
  return (
    <aside className="rf-chat" aria-label="Claude とのチャット">
      <div className="rf-chat-head">
        <span className="rf-chat-title">Claude と決める</span>
        <span className="rf-chat-sub">
          Claude の文はこの院内の画面だけに出ます。患者の名前・ID
          は書かないでください（送る前に検査します）
        </span>
      </div>
      <ol
        ref={logRef}
        className="rf-chat-log"
        aria-live="polite"
        aria-label="会話"
      >
        <li className="rf-msg rf-msg--guide">
          <div className="rf-bubble">
            {existing
              ? `直したいところを書くと、Claude が左の欄を書き換えます（版 ${draft.version} の下書き）。左の欄を直接直しても同じです。採用するまで患者の画面は版 ${draft.base_version} のままです。`
              : "作りたいレジメンを自由に書いてください。薬・飲み方・注意する副作用など、分かるところからで構いません。足りないところは Claude が聞きます。"}
          </div>
        </li>
        {draft.chat.map((row, i) => (
          <ChatMessage
            key={`${row.generation}-${row.role}-${i}`}
            row={row}
            draft={draft}
            canAnswer={!busy && i === lastIndex}
            onJump={onJump}
            onAnswer={(option) => void send(option, false)}
          />
        ))}
        {busy ? (
          <li className="rf-msg rf-msg--claude" role="status">
            <span className="rf-msg-who">Claude</span>
            <div className="rf-bubble rf-bubble--busy">
              考えています…（この間、左の欄は編集できません）
            </div>
          </li>
        ) : null}
      </ol>
      <ChatInput
        draft={draft}
        busy={busy}
        blocked={blocked}
        notice={notice}
        text={text}
        onText={setText}
        onSend={() => void send(text, true)}
      />
    </aside>
  );
}
