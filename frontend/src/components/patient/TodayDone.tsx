import { useId, useState } from "react";
import { isApiError } from "../../api/http";
import { undoEntry } from "../../api/patient";
import { usePatientStrings } from "../../strings/PatientStrings";
import SummaryLine from "./SummaryLine";
import type { SummaryItem } from "./entrySummary";
import { DoneMessage, ErrorMessage, Notices } from "./Messages";
import {
  GENERIC_ERROR_KEY,
  NOT_REGISTERED_KEY,
  isNotRegistered,
} from "./patientApi";

/** 記録できた1件（今日の記録の画面に出す分）。 */
export interface SavedRecord {
  entryId: number;
  /** today.saved か today.too_sick_done */
  messageKey: string;
  notices: readonly string[];
  items: readonly SummaryItem[];
  /** 「つらくて書けない」なら取り消せる（P2-5） */
  undoable: boolean;
}

/** 取り消しが断られた（409 not_undoable・404 not_found）。もう取り消せない。 */
const UNDO_FAILED_KEY = "today.undo_failed";

type UndoState =
  | { name: "idle" }
  | { name: "sending" }
  | { name: "failed"; errorKey: string; retry: boolean };

function undoErrorOf(err: unknown): { errorKey: string; retry: boolean } {
  if (isNotRegistered(err)) {
    return { errorKey: NOT_REGISTERED_KEY, retry: false };
  }
  if (isApiError(err) && (err.status === 404 || err.status === 409)) {
    return { errorKey: UNDO_FAILED_KEY, retry: false };
  }
  return { errorKey: GENERIC_ERROR_KEY, retry: true };
}

interface TodayDoneProps {
  pid: string;
  saved: SavedRecord;
  /** 取り消せた（記録する前の画面に戻す） */
  onUndone: () => void;
  /** 「追加で記録する」（空の入力から始める） */
  onAddMore: () => void;
}

/**
 * 記録した後（P2-4・P2-5）。「記録しました」・固定規則の案内・記録した内容の要約・
 * 「取り消す」（つらくて書けないの後だけ。押す前の確認は無い）・「追加で記録する」。
 */
export default function TodayDone({
  pid,
  saved,
  onUndone,
  onAddMore,
}: TodayDoneProps) {
  const { t } = usePatientStrings();
  const titleId = useId();
  const [undo, setUndo] = useState<UndoState>({ name: "idle" });

  async function handleUndo() {
    setUndo({ name: "sending" });
    try {
      await undoEntry(pid, saved.entryId);
      onUndone();
    } catch (err) {
      setUndo({ name: "failed", ...undoErrorOf(err) });
    }
  }

  const canUndo = saved.undoable && !(undo.name === "failed" && !undo.retry);
  return (
    <>
      <DoneMessage messageKey={saved.messageKey} />
      <Notices keys={saved.notices} />
      <section className="p-saved" aria-labelledby={titleId}>
        <h2 id={titleId} className="p-saved-title">
          {t("today.saved_summary")}
        </h2>
        <p>
          <SummaryLine items={saved.items} />
        </p>
      </section>
      {canUndo && (
        <button
          type="button"
          className="p-button--undo"
          disabled={undo.name === "sending"}
          onClick={handleUndo}
        >
          {t("today.undo")}
        </button>
      )}
      {undo.name === "failed" && <ErrorMessage messageKey={undo.errorKey} />}
      <button
        type="button"
        className="p-button--primary"
        disabled={undo.name === "sending"}
        onClick={onAddMore}
      >
        {t("today.add_more")}
      </button>
    </>
  );
}
