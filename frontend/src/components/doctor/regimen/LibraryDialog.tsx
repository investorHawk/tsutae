import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { listQuestionLibrary } from "../../../api/doctor";
import type { LibraryQuestion, QuestionOrigin } from "../../../api/types";
import ErrorNote from "../ErrorNote";
import { ANSWER_TYPE_LABELS } from "./QuestionsSection";

interface LibraryDialogProps {
  /** フォームにある質問の key（同じ key は選べない） */
  usedKeys: ReadonlySet<string>;
  handleError: (err: unknown) => string;
  onPick: (question: LibraryQuestion) => Promise<boolean>;
  onClose: () => void;
}

const ORIGIN_LABELS: Readonly<Record<QuestionOrigin, string>> = {
  seed: "初期の質問",
  doctor: "先生が足した質問",
  adopted: "採用したレジメンの質問",
};

const FOCUSABLE = "button:not([disabled]), [href], input:not([disabled])";

/**
 * 質問の部品集から選ぶ小窓（画面内のダイアログ。window の確認は使わない）。
 * Esc（focus が小窓の外にあっても）・「閉じる」・背景を押すと閉じ、Tab は小窓の中を回る。
 * 閉じたら開いたボタンへ focus を戻すのは呼び出し側。
 */
export default function LibraryDialog({
  usedKeys,
  handleError,
  onPick,
  onClose,
}: LibraryDialogProps) {
  const [items, setItems] = useState<LibraryQuestion[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState<string | null>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    closeRef.current?.focus();
    let live = true;
    listQuestionLibrary()
      .then((res) => live && setItems(res.questions))
      .catch((err: unknown) => live && setError(handleError(err)));
    return () => {
      live = false;
    };
  }, [handleError]);

  // Esc は document で受ける（背景を押した後など、focus が小窓の外にあるときも閉じる）
  useEffect(() => {
    function onEscape(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
      }
    }
    document.addEventListener("keydown", onEscape);
    return () => document.removeEventListener("keydown", onEscape);
  }, [onClose]);

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key !== "Tab" || !boxRef.current) {
      return;
    }
    const nodes = [...boxRef.current.querySelectorAll<HTMLElement>(FOCUSABLE)];
    const first = nodes[0];
    const last = nodes[nodes.length - 1];
    if (!first || !last) {
      return;
    }
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  async function pick(question: LibraryQuestion) {
    setAdding(question.key);
    const ok = await onPick(question);
    setAdding(null);
    if (ok) {
      onClose();
    }
  }

  const choices = (items ?? []).filter((q) => !usedKeys.has(q.key));
  return (
    <div
      className="rf-overlay"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          // 背景への focus の移動を止める（閉じた後に開いたボタンへ戻すため）
          event.preventDefault();
          onClose();
        }
      }}
    >
      <div
        ref={boxRef}
        className="rf-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="rf-lib-h"
        onKeyDown={onKeyDown}
      >
        <div className="rf-dialog-head">
          <h3 id="rf-lib-h">質問の部品集から選ぶ</h3>
          <button ref={closeRef} type="button" onClick={onClose}>
            閉じる
          </button>
        </div>
        {error ? (
          <ErrorNote code={error} prefix="部品集を読めません" />
        ) : items === null ? (
          <p className="d-muted">読み込み中…</p>
        ) : choices.length === 0 ? (
          <p className="d-muted">
            足せる質問はありません（全て入っています）。
          </p>
        ) : (
          <ul className="rf-lib-list">
            {choices.map((q) => (
              <li key={q.key} className="rf-lib-item">
                <span className="rf-lib-label">{q.label}</span>
                <span>{q.text}</span>
                <span className="d-muted">
                  {ANSWER_TYPE_LABELS[q.answer_type]}・{ORIGIN_LABELS[q.origin]}
                </span>
                <button
                  type="button"
                  disabled={adding !== null}
                  aria-label={`「${q.label}」を足す`}
                  onClick={() => void pick(q)}
                >
                  足す
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
