import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { listUnprocessed, reportUrl } from "../../api/doctor";
import type {
  MaskCheckResponse,
  UnprocessedItem,
  VisitHeader,
} from "../../api/types";
import ErrorNote from "../../components/doctor/ErrorNote";
import { isUnprocessedItem } from "../../components/doctor/guards";
import { listOf, parseVisitId } from "../../components/doctor/input";
import MaskSubmitPanel from "../../components/doctor/MaskSubmitPanel";
import { sameSpans, type Span } from "../../components/doctor/maskSpans";
import {
  type EntryMaskState,
  type MaskStates,
  initialMaskState,
  initialMaskStates,
  withCheck,
  withSpans,
} from "../../components/doctor/maskState";
import PrintButton from "../../components/doctor/PrintButton";
import ReportLink from "../../components/doctor/ReportLink";
import UnprocessedEntryCard from "../../components/doctor/UnprocessedEntryCard";
import { useDoctorApiError } from "../../components/doctor/useDoctorApiError";
import VisitHeading from "../../components/doctor/VisitHeading";
import "../../components/doctor/doctor-ui.css";
import "../../components/doctor/board.css";
import "../../components/doctor/mask.css";

interface Loaded {
  visit: VisitHeader;
  items: UnprocessedItem[];
}

/**
 * 確かめたらそのまま印刷する（印刷待ちの画面と同じ PrintButton）。変換し直さない時の
 * ため。レポートを開けない（生成中・失敗・印刷済み・期限切れ）なら出さない。
 */
function PrintAfterCheck({ visit }: { visit: VisitHeader }) {
  if (!visit.report_available) {
    return null;
  }
  return (
    <section className="d-unprocessed-print" aria-label="この受診のレポート">
      <p>確かめたら、この受診のレポートをそのまま印刷できます。</p>
      <div className="d-actions">
        <PrintButton url={reportUrl(visit.id)} />
        <ReportLink visitId={visit.id} />
      </div>
    </section>
  );
}

/**
 * D6 未処理の記載。伏せ字漏れの疑いで Claude に送らなかった記録の原文（院内画面だけ）。
 * 疑われた語は <mark> で強調する（位置は API の marks）。規則は日本語の説明だけを出し、
 * 規則名は title に残す。見出しは受付番号・仮名ID・受付の日時（内部の番号は出さない）。
 * 記録ごとに「送る（伏せて）」を選ぶと、伏せる所を選んで確かめ、下のボタンで保存して
 * Claude で変換し直せる（医師は文を書かず、伏せる区間だけを送る）。
 * 受診ごとに描き直す（別の受診へ移ったら前の受診の原文・失敗を引き継がない）。
 */
export default function Unprocessed() {
  const { visitId } = useParams();
  return <UnprocessedView key={visitId ?? ""} visitId={visitId} />;
}

function UnprocessedView({ visitId }: { visitId: string | undefined }) {
  const id = parseVisitId(visitId);
  const handleError = useDoctorApiError();
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [states, setStates] = useState<MaskStates>({});
  const [error, setError] = useState<string | null>(
    id === null ? "invalid_visit_id" : null,
  );

  useEffect(() => {
    if (id === null) {
      return undefined;
    }
    let active = true;
    listUnprocessed(id)
      .then((res) => {
        if (active) {
          const items = listOf<UnprocessedItem>(
            res,
            "entries",
            isUnprocessedItem,
          );
          setLoaded({ visit: res.visit, items });
          setStates(initialMaskStates(items));
        }
      })
      .catch((err: unknown) => {
        const code = handleError(err);
        if (active) {
          setError(code);
        }
      });
    return () => {
      active = false;
    };
  }, [id, handleError]);

  const update = useCallback(
    (item: UnprocessedItem, fn: (s: EntryMaskState) => EntryMaskState) => {
      setStates((prev) => ({
        ...prev,
        [item.entry_id]: fn(prev[item.entry_id] ?? initialMaskState(item)),
      }));
    },
    [],
  );

  const items = loaded?.items;
  return (
    <section className="page">
      <h1>未処理の記載</h1>
      <p className="d-notice">
        伏せ字漏れの疑いがあるため、Claude
        に送らなかった記録の原文です。紙には載りません（レポートには「未処理の記載あり」と件数だけが出ます）。この画面でだけ確認してください。伏せ字にすれば、Claude
        で変換し直して紙に載せられます。
      </p>
      <p className="d-toolbar">
        {loaded ? <VisitHeading visit={loaded.visit} /> : null}
        <Link className="d-sublink" to="/doctor">
          ← 印刷待ちへ戻る
        </Link>
      </p>
      {error ? <ErrorNote code={error} /> : null}
      {items?.length === 0 ? (
        <p className="d-muted">未処理の記載はありません</p>
      ) : null}
      {loaded && items && items.length > 0 ? (
        <>
          <ol className="d-unprocessed">
            {items.map((item) => (
              <UnprocessedEntryCard
                key={item.entry_id}
                visitId={loaded.visit.id}
                item={item}
                state={states[item.entry_id] ?? initialMaskState(item)}
                onUpdate={(fn) => update(item, fn)}
                onSpans={(spans: Span[]) =>
                  update(item, (s) => withSpans(s, spans))
                }
                onChecked={(requested: Span[], check: MaskCheckResponse) =>
                  update(item, (s) =>
                    sameSpans(s.spans, requested) ? withCheck(s, check) : s,
                  )
                }
              />
            ))}
          </ol>
          <MaskSubmitPanel visit={loaded.visit} items={items} states={states} />
        </>
      ) : null}
      {loaded ? <PrintAfterCheck visit={loaded.visit} /> : null}
    </section>
  );
}
