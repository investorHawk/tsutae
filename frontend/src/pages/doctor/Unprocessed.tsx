import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { listUnprocessed, reportUrl } from "../../api/doctor";
import type { UnprocessedItem, VisitHeader } from "../../api/types";
import { courseDayLabel } from "../../components/doctor/courseDayLabel";
import { formatDay } from "../../components/doctor/dayLabel";
import ErrorNote from "../../components/doctor/ErrorNote";
import { isUnprocessedItem } from "../../components/doctor/guards";
import { listOf, parseVisitId } from "../../components/doctor/input";
import MarkedText from "../../components/doctor/MarkedText";
import PrintButton from "../../components/doctor/PrintButton";
import ReportLink from "../../components/doctor/ReportLink";
import { ruleLabel } from "../../components/doctor/ruleLabels";
import { useDoctorApiError } from "../../components/doctor/useDoctorApiError";
import VisitHeading from "../../components/doctor/VisitHeading";
import "../../components/doctor/doctor-ui.css";
import "../../components/doctor/board.css";

interface Loaded {
  visit: VisitHeader;
  items: UnprocessedItem[];
}

/** 「11月5日（木）・第3コース Day10」（コース外なら日付だけ）。 */
function recordDayText(item: UnprocessedItem): string {
  const course = courseDayLabel(item.course_no, item.day);
  const day = formatDay(item.record_date);
  return course === null ? day : `${day}・${course}`;
}

/**
 * 確かめたらそのまま印刷する（印刷待ちの画面と同じ PrintButton）。レポートを開けない
 * （生成中・失敗・印刷済み・期限切れ）なら出さない。
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
          setLoaded({
            visit: res.visit,
            items: listOf<UnprocessedItem>(res, "entries", isUnprocessedItem),
          });
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

  const items = loaded?.items;
  return (
    <section className="page">
      <h1>未処理の記載</h1>
      <p className="d-notice">
        伏せ字漏れの疑いがあるため、Claude
        に送らなかった記録の原文です。紙には載りません（レポートには「未処理の記載あり」と件数だけが出ます）。この画面でだけ確認してください。
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
      {items && items.length > 0 ? (
        <ol className="d-unprocessed">
          {items.map((item) => (
            <li key={item.entry_id} className="d-unprocessed-item">
              <p className="d-unprocessed-meta">
                記録日 {recordDayText(item)} ・{" "}
                <span title={item.reason}>{ruleLabel(item.reason)}</span>
              </p>
              <p className="d-raw">
                <MarkedText text={item.text} marks={item.marks} />
              </p>
            </li>
          ))}
        </ol>
      ) : null}
      {loaded ? <PrintAfterCheck visit={loaded.visit} /> : null}
    </section>
  );
}
