import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { regenerateVisit, saveMasks } from "../../api/doctor";
import type { UnprocessedItem, VisitHeader } from "../../api/types";
import ErrorNote from "./ErrorNote";
import { type MaskStates, saveEntries, sendCount } from "./maskState";
import { useDoctorApiError } from "./useDoctorApiError";

interface MaskSubmitPanelProps {
  visit: VisitHeader;
  items: readonly UnprocessedItem[];
  states: MaskStates;
}

const LABEL = "伏せ字を保存して AI で変換し直す";

/**
 * 受診1回分の「伏せ字を保存して AI で変換し直す」。保存（POST masks）→ 既存の再変換
 * （POST regenerate）→ 変換ログの画面へ移る。送れる記録が1件も無ければ変換しない
 * （Claude を呼ばない）。押す前に Claude を呼んで1〜2分かかることを出す。
 */
export default function MaskSubmitPanel({
  visit,
  items,
  states,
}: MaskSubmitPanelProps) {
  const navigate = useNavigate();
  const handleError = useDoctorApiError();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const mounted = useRef(true);
  const count = sendCount(states);
  const generating = visit.status === "generating";

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  async function submit() {
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      const saved = await saveMasks(visit.id, saveEntries(items, states));
      if (saved.sendable === 0) {
        if (mounted.current) {
          setNote(
            "伏せ字を保存しました。送れる記録が無いので変換はしていません（「伏せ字を確かめる」で疑いが残っていないかを見てください）。",
          );
        }
        return;
      }
      await regenerateVisit(visit.id);
      navigate(`/doctor/pipeline/${visit.id}`);
    } catch (err) {
      const code = handleError(err);
      if (mounted.current) {
        setError(code);
      }
    } finally {
      if (mounted.current) {
        setBusy(false);
      }
    }
  }

  return (
    <section className="d-mask-submit" aria-label="伏せ字にして変換し直す">
      <p>
        「送る（伏せて）」にした記録を伏せ字にして、この受診をもう一度 Claude
        で変換します。Claude
        を呼ぶので、1〜2分かかります。終わると紙の時系列・食い違い・引用に入ります。
      </p>
      {generating ? (
        <p className="d-muted">変換の最中です。終わってから押してください。</p>
      ) : null}
      <div className="d-actions">
        <button
          type="button"
          className="d-primary"
          disabled={busy || generating || count === 0}
          onClick={() => void submit()}
        >
          {busy ? "保存して変換を依頼中…" : LABEL}
        </button>
      </div>
      {count === 0 ? (
        <p className="d-muted">
          送る記録がありません（記録ごとに「送る（伏せて）」を選んでください）。
        </p>
      ) : null}
      {note ? (
        <p className="d-muted" role="status">
          {note}
        </p>
      ) : null}
      {error ? (
        <ErrorNote code={error} prefix="変換し直せませんでした" />
      ) : null}
    </section>
  );
}
