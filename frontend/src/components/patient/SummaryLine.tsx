import { Fragment } from "react";
import { usePatientStrings } from "../../strings/PatientStrings";
import { fillTemplate } from "../../strings/template";
import type { SummaryItem } from "./entrySummary";
import { useSymptomLabel } from "./useSymptomLabel";

function Item({ item }: { item: SummaryItem }) {
  const { t } = usePatientStrings();
  const label = useSymptomLabel();
  switch (item.kind) {
    case "too_sick":
      return <strong>{t("history.too_sick")}</strong>;
    case "all_none":
      return <strong>{t("history.all_none")}</strong>;
    case "free_text":
      return (
        <>
          {t("history.free_text")}{" "}
          <strong>{t("history.free_text_present")}</strong>
        </>
      );
    case "answer":
      return (
        <>
          {label(item.questionKey, item.questionText)}{" "}
          <strong>{t(`answer.${item.value}`)}</strong>
        </>
      );
    case "temperature":
      return (
        <>
          {label(item.questionKey, item.questionText)}{" "}
          <strong>
            {fillTemplate(t("history.temperature_value"), {
              value: item.temperature.toFixed(1),
            })}
          </strong>
        </>
      );
  }
}

/**
 * 記録1件の短い要約（「しびれ つらい／下痢 ある／体温 37.8℃」）。答えは太字。
 * 区切りの「／」は定型文 history.separator。summary の中にも置けるよう span だけで描く。
 */
export default function SummaryLine({
  items,
}: {
  items: readonly SummaryItem[];
}) {
  const { t } = usePatientStrings();
  return (
    <span className="p-summary">
      {items.map((item, i) => (
        <Fragment key={`${i}-${item.kind}`}>
          {i > 0 && (
            <span className="p-summary-sep">{t("history.separator")}</span>
          )}
          <span className="p-summary-item">
            <Item item={item} />
          </span>
        </Fragment>
      ))}
    </span>
  );
}
