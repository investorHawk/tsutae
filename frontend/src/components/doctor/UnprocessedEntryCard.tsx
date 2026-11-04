import { useEffect, useRef, useState } from "react";
import { checkMasks } from "../../api/doctor";
import type { MaskCheckResponse, UnprocessedItem } from "../../api/types";
import { courseDayLabel } from "./courseDayLabel";
import { formatDay } from "./dayLabel";
import ErrorNote from "./ErrorNote";
import MarkedText from "./MarkedText";
import MaskCheckResult from "./MaskCheckResult";
import MaskEditor from "./MaskEditor";
import type { Span } from "./maskSpans";
import { type EntryMaskState, withConfirmed, withSend } from "./maskState";
import { ruleLabel } from "./ruleLabels";
import { useDoctorApiError } from "./useDoctorApiError";

interface UnprocessedEntryCardProps {
  visitId: number;
  item: UnprocessedItem;
  state: EntryMaskState;
  /** 状態を変える（今の状態から次の状態を作る関数を渡す） */
  onUpdate: (update: (state: EntryMaskState) => EntryMaskState) => void;
  onSpans: (spans: Span[]) => void;
  /** 確かめた結果（requested はその時の区間。区間が変わっていれば捨てる） */
  onChecked: (requested: Span[], check: MaskCheckResponse) => void;
}

/** 「11月5日（木）・第3コース Day10」（コース外なら日付だけ）。 */
function recordDayText(item: UnprocessedItem): string {
  const course = courseDayLabel(item.course_no, item.day);
  const day = formatDay(item.record_date);
  return course === null ? day : `${day}・${course}`;
}

/**
 * 未処理の記載（D6）の記録1件。原文（疑われた語は <mark>）と、送るか送らないかの選択。
 * 「送る（伏せて）」なら伏せる所の編集・「伏せ字を確かめる」（サーバーで再検出）を出す。
 */
export default function UnprocessedEntryCard({
  visitId,
  item,
  state,
  onUpdate,
  onSpans,
  onChecked,
}: UnprocessedEntryCardProps) {
  const handleError = useDoctorApiError();
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);
  const name = `send-${item.entry_id}`;

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  async function runCheck() {
    const requested = state.spans;
    setChecking(true);
    setError(null);
    try {
      const check = await checkMasks(visitId, item.entry_id, requested);
      onChecked(requested, check);
    } catch (err) {
      const code = handleError(err);
      if (mounted.current) {
        setError(code);
      }
    } finally {
      if (mounted.current) {
        setChecking(false);
      }
    }
  }

  return (
    <li className="d-unprocessed-item">
      <p className="d-unprocessed-meta">
        記録日 {recordDayText(item)} ・{" "}
        <span title={item.reason}>{ruleLabel(item.reason)}</span>
      </p>
      <p className="d-raw">
        <MarkedText text={item.text} marks={item.marks} />
      </p>
      <fieldset className="d-mask-choice">
        <legend>この記録を</legend>
        <label>
          <input
            type="radio"
            name={name}
            checked={!state.send}
            onChange={() => onUpdate((s) => withSend(s, false))}
          />
          送らない（未処理のまま）
        </label>
        <label>
          <input
            type="radio"
            name={name}
            checked={state.send}
            onChange={() => onUpdate((s) => withSend(s, true))}
          />
          送る（伏せて）
        </label>
      </fieldset>
      {state.send ? (
        <>
          <MaskEditor text={item.text} spans={state.spans} onChange={onSpans} />
          <div className="d-actions">
            <button
              type="button"
              disabled={checking}
              onClick={() => void runCheck()}
            >
              {checking ? "確かめています…" : "伏せ字を確かめる"}
            </button>
          </div>
          {error ? (
            <ErrorNote code={error} prefix="確かめられませんでした" />
          ) : null}
          {state.check ? (
            <MaskCheckResult
              check={state.check}
              confirmed={state.confirmed}
              onConfirm={(value) => onUpdate((s) => withConfirmed(s, value))}
            />
          ) : null}
          {!state.check && state.confirmed ? (
            <p className="d-muted">
              「個人を特定する語は無いことを確かめた」として保存してあります。
            </p>
          ) : null}
        </>
      ) : null}
    </li>
  );
}
