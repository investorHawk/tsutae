import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { listUnprocessed } from "../../api/doctor";
import type { UnprocessedItem } from "../../api/types";
import ErrorNote from "../../components/doctor/ErrorNote";
import { isUnprocessedItem } from "../../components/doctor/guards";
import { listOf, parseVisitId } from "../../components/doctor/input";
import MarkedText from "../../components/doctor/MarkedText";
import { ruleLabel } from "../../components/doctor/ruleLabels";
import { useDoctorApiError } from "../../components/doctor/useDoctorApiError";
import "../../components/doctor/doctor-ui.css";

/**
 * D6 未処理の記載。伏せ字漏れの疑いで Claude に送らなかった記録の原文（院内画面だけ）。
 * 疑われた語は <mark> で強調する（位置は API の marks）。規則は日本語の説明だけを出し、
 * 規則名は title に残す。
 * 受診ごとに描き直す（別の受診へ移ったら前の受診の原文・失敗を引き継がない）。
 */
export default function Unprocessed() {
  const { visitId } = useParams();
  return <UnprocessedView key={visitId ?? ""} visitId={visitId} />;
}

function UnprocessedView({ visitId }: { visitId: string | undefined }) {
  const id = parseVisitId(visitId);
  const handleError = useDoctorApiError();
  const [items, setItems] = useState<UnprocessedItem[] | null>(null);
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
          setItems(listOf<UnprocessedItem>(res, "entries", isUnprocessedItem));
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

  return (
    <section className="page">
      <h1>未処理の記載</h1>
      <p className="d-notice">
        伏せ字漏れの疑いがあるため、Claude
        に送らなかった記録の原文です。紙には載りません（レポートには「未処理の記載あり」と件数だけが出ます）。この画面でだけ確認してください。
      </p>
      <p>
        <Link to="/doctor">← 印刷待ちへ戻る</Link>
        {id !== null ? <span className="d-muted">　受診 #{id}</span> : null}
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
                記録日 {item.record_date} ・ 記録 #{item.entry_id} ・{" "}
                <span title={item.reason}>{ruleLabel(item.reason)}</span>
              </p>
              <p className="d-raw">
                <MarkedText text={item.text} marks={item.marks} />
              </p>
            </li>
          ))}
        </ol>
      ) : null}
    </section>
  );
}
