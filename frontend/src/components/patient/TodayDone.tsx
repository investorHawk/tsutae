import { useId, useState } from "react";
import { isApiError } from "../../api/http";
import type { DeviceEntry } from "../../api/types";
import { undoRecord } from "../../patient/recordEntry";
import { reloadPage } from "../../patient/reload";
import { usePatientStrings } from "../../strings/PatientStrings";
import EntryDetail from "./EntryDetail";
import { summarySourceOf } from "./entrySummary";
import { DoneMessage, ErrorMessage, Notices } from "./Messages";
import NotRegistered from "./NotRegistered";
import { GENERIC_ERROR_KEY, isNotRegistered } from "./patientApi";

/** 記録できた1件（今日の記録の画面に出す分）。 */
export interface SavedRecord {
  /** 端末に保存した記録（回答の表の元。なし・測っていないも含む） */
  entry: DeviceEntry;
  /** today.saved か today.too_sick_done */
  messageKey: string;
  /** 固定規則の案内（patient_strings のキー） */
  notices: readonly string[];
}

/** 取り消しが断られた（409 not_undoable）。もう取り消せない。 */
const UNDO_FAILED_KEY = "today.undo_failed";

/** 取り消しで未登録と分かり、番号を入れて戻った */
const REGISTERED_KEY = "register.done";

type UndoState =
  | { name: "idle"; registered?: boolean }
  | { name: "sending" }
  | { name: "not_registered" }
  | { name: "failed"; errorKey: string; retry: boolean };

function undoErrorOf(err: unknown): { errorKey: string; retry: boolean } {
  if (isApiError(err) && err.status === 409) {
    return { errorKey: UNDO_FAILED_KEY, retry: false };
  }
  return { errorKey: GENERIC_ERROR_KEY, retry: true };
}

interface TodayDoneProps {
  saved: SavedRecord;
  /** 取り消せた（記録する前の画面に戻す） */
  onUndone: () => void;
  /** 「追加で記録する」（空の入力から始める） */
  onAddMore: () => void;
}

/**
 * 取り消しの送信（サーバーが通したら端末の記録を消す）。401/403 の後は同じ番号なら押し直せる
 * ように戻し、違う番号は読み直す。
 */
function useUndo(entry: DeviceEntry, onUndone: () => void) {
  const [undo, setUndo] = useState<UndoState>({ name: "idle" });

  async function handleUndo() {
    setUndo({ name: "sending" });
    try {
      await undoRecord(entry);
      onUndone();
    } catch (err) {
      setUndo(
        isNotRegistered(err)
          ? { name: "not_registered" }
          : { name: "failed", ...undoErrorOf(err) },
      );
    }
  }

  function resumeAfterRegister(registeredPid: string) {
    if (registeredPid !== entry.pid) {
      reloadPage();
      return;
    }
    setUndo({ name: "idle", registered: true });
  }

  return { undo, handleUndo, resumeAfterRegister };
}

/**
 * 記録した後（P2-4・P2-5）。「記録しました」・固定規則の案内・記録した内容（これまでの
 * 記録と同じ回答の表。書いたことは「あり」だけで本文は出さない）・
 * 「取り消す」（つらくて書けないの後だけ。押す前の確認は無い）・「追加で記録する」。
 * 取り消しが 401/403 なら番号の入力欄を出す。同じ番号ならこの画面のまま取り消しを押し直せる
 * （読み直すと取り消しのボタンが消えて戻れない）。違う番号は読み直す（この記録は別の人のもの）。
 */
export default function TodayDone({
  saved,
  onUndone,
  onAddMore,
}: TodayDoneProps) {
  const { t } = usePatientStrings();
  const titleId = useId();
  const { undo, handleUndo, resumeAfterRegister } = useUndo(
    saved.entry,
    onUndone,
  );

  // 「つらくて書けない」なら取り消せる（P2-5）
  const canUndo =
    saved.entry.kind === "too_sick" &&
    undo.name !== "not_registered" &&
    !(undo.name === "failed" && !undo.retry);
  return (
    <>
      {undo.name === "idle" && undo.registered && (
        <DoneMessage messageKey={REGISTERED_KEY} />
      )}
      <DoneMessage messageKey={saved.messageKey} />
      <Notices keys={saved.notices} />
      <section className="p-saved" aria-labelledby={titleId}>
        <h2 id={titleId} className="p-saved-title">
          {t("today.saved_summary")}
        </h2>
        <EntryDetail
          byProxy={saved.entry.by_proxy}
          source={summarySourceOf(saved.entry)}
          showFreeTextBody={false}
        />
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
      {undo.name === "not_registered" && (
        <NotRegistered onRegistered={resumeAfterRegister} />
      )}
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
