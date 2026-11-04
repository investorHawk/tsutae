import { usePatientStrings } from "../../strings/PatientStrings";
import AnswerTable from "./AnswerTable";
import type { SummarySource } from "./entrySummary";

interface EntryDetailProps {
  byProxy: boolean;
  source: SummarySource;
  /**
   * 自由記載の本文を出す（これまでの記録）。false なら「書いたこと あり」の1行だけ
   * （記録した後の確認。本文は出さない）
   */
  showFreeTextBody: boolean;
}

/** 書いたこと（自由記載）。見出しは小さく、本文は淡い地の枠で囲む。 */
function FreeText({ text, showBody }: { text: string; showBody: boolean }) {
  const { t } = usePatientStrings();
  if (!showBody) {
    return (
      <p className="p-entry-label">
        {t("history.free_text")}{" "}
        <strong className="p-entry-label-value">
          {t("history.free_text_present")}
        </strong>
      </p>
    );
  }
  return (
    <div className="p-entry-free">
      <p className="p-entry-label">{t("history.free_text")}</p>
      <p className="p-entry-free-text">{text}</p>
    </div>
  );
}

/**
 * 記録1件の中身（これまでの記録の詳しい表示と、記録した後の確認で同じ見た目）。
 * 上に「家族が代わりに入力」「つらくて書けない」、真ん中に回答の表、下に書いたこと。
 */
export default function EntryDetail({
  byProxy,
  source,
  showFreeTextBody,
}: EntryDetailProps) {
  const { t } = usePatientStrings();
  const freeText = source.freeText ?? "";
  const hasFreeText = showFreeTextBody
    ? freeText.length > 0
    : freeText.trim().length > 0;
  return (
    <div className="p-entry-content">
      {byProxy && <p className="p-entry-flag">{t("history.proxy")}</p>}
      {source.tooSick && (
        <p className="p-entry-flag">{t("history.too_sick")}</p>
      )}
      {source.answers.length > 0 && <AnswerTable answers={source.answers} />}
      {hasFreeText && <FreeText text={freeText} showBody={showFreeTextBody} />}
    </div>
  );
}
