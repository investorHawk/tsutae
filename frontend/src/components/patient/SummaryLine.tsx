import { Fragment } from "react";
import { usePatientStrings } from "../../strings/PatientStrings";
import { fillTemplate } from "../../strings/template";
import type { SummaryItem } from "./entrySummary";
import { useSymptomLabel } from "./useSymptomLabel";

/** 画面には出さず読み上げにだけ残す文字（base.css の visually-hidden）。 */
function Hidden({ children }: { children: string }) {
  return <span className="visually-hidden">{children}</span>;
}

function Tag({ item }: { item: Exclude<SummaryItem, { kind: "all_none" }> }) {
  const { t } = usePatientStrings();
  const label = useSymptomLabel();
  switch (item.kind) {
    case "answer":
      return item.value === "hard" ? (
        <span className="p-tag p-tag--hard">
          {label(item.questionKey, item.questionText)}
          <Hidden>{` ${t("answer.hard")}`}</Hidden>
        </span>
      ) : (
        <span className="p-tag p-tag--present">
          {label(item.questionKey, item.questionText)}
          <Hidden>{` ${t("answer.present")}`}</Hidden>
        </span>
      );
    case "temperature":
      return (
        <span className="p-tag p-tag--neutral">
          <Hidden>{`${label(item.questionKey, item.questionText)} `}</Hidden>
          {fillTemplate(t("history.temperature_value"), {
            value: item.temperature.toFixed(1),
          })}
        </span>
      );
    case "free_text":
      return (
        <span className="p-tag p-tag--neutral">
          {t("history.free_text")}
          <Hidden>{` ${t("history.free_text_present")}`}</Hidden>
        </span>
      );
    case "too_sick":
      return (
        <span className="p-tag p-tag--neutral">{t("history.too_sick")}</span>
      );
    case "proxy":
      return (
        <span className="p-tag p-tag--neutral">
          <span aria-hidden="true">{t("history.proxy_short")}</span>
          <Hidden>{t("history.proxy")}</Hidden>
        </span>
      );
  }
}

function Item({ item }: { item: SummaryItem }) {
  const { t } = usePatientStrings();
  if (item.kind === "all_none") {
    return <span className="p-tags-none">{t("history.all_none")}</span>;
  }
  return <Tag item={item} />;
}

/**
 * 記録1件の短い要約。タグ（小さな角丸のラベル）を折り返して並べる。
 * - ある: 淡い青の地に紺の症状名と紺の枠（「下痢」）／つらい: 紺の地に白の症状名
 *   （「しびれ」）。印は付けず、塗りと枠の明るさの差で分ける。答えは読み上げにだけ残す
 *   （「しびれ つらい」）。なしはタグにしない
 * - 体温（「37.2℃」）・書いたこと・つらくて書けない・代理は中立の見た目
 * - 全て なしなら「どれも なし」を文で出す
 * タグの間には読み上げ用の区切り（定型文 history.separator。見た目には出さない）を置く。
 * summary の中に置けるよう span だけで描く。
 */
export default function SummaryLine({
  items,
}: {
  items: readonly SummaryItem[];
}) {
  const { t } = usePatientStrings();
  return (
    <span className="p-tags">
      {items.map((item, i) => (
        <Fragment key={`${i}-${item.kind}`}>
          {i > 0 && <Hidden>{t("history.separator")}</Hidden>}
          <Item item={item} />
        </Fragment>
      ))}
    </span>
  );
}
