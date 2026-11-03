import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { listUnprocessed } from "../../api/doctor";
import type { UnprocessedItem } from "../../api/types";
import ErrorNote from "../../components/doctor/ErrorNote";
import { isUnprocessedItem } from "../../components/doctor/guards";
import { listOf, parseVisitId } from "../../components/doctor/input";
import { useDoctorApiError } from "../../components/doctor/useDoctorApiError";
import "../../components/doctor/doctor-ui.css";

/** 二次検出（H1 の規則）の名前と説明。tsutae.masking.detect_identifiers の規則名。 */
const RULE_LABELS: Readonly<Record<string, string>> = {
  unknown_before_honorific: "敬称の前に、辞書にない語がある（人名の疑い）",
  long_digits: "7桁以上の数字列がある（電話番号・番号の疑い）",
  at_mark: "@ がある（メールアドレスの疑い）",
  before_facility: "施設名らしき語がある（病院名の疑い）",
};

function ruleLabel(reason: string): string {
  return RULE_LABELS[reason] ?? "伏せ字漏れの疑い";
}

/** D6 未処理の記載。伏せ字漏れの疑いで Claude に送らなかった記録の原文（院内画面だけ）。 */
export default function Unprocessed() {
  const { visitId } = useParams();
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
                記録日 {item.record_date} ・ 記録 #{item.entry_id} ・ 規則{" "}
                <code>{item.reason}</code>（{ruleLabel(item.reason)}）
              </p>
              <p className="d-raw">{item.text}</p>
            </li>
          ))}
        </ol>
      ) : null}
    </section>
  );
}
