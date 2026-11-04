/** 欄の状態の凡例（色と文字の札の対応）。 */
export default function RegimenLegend() {
  return (
    <p className="rf-legend" aria-label="欄の状態">
      <span>
        <span className="rf-legend-tag rf-legend-tag--missing">未入力</span>{" "}
        必須
      </span>
      <span>
        <span className="rf-legend-tag rf-legend-tag--asked">
          Claude が聞いています
        </span>
      </span>
      <span>
        <span className="rf-legend-tag rf-legend-tag--ai">AI が入れた</span>{" "}
        採用の前に確かめる
      </span>
      <span>
        <span className="rf-legend-tag rf-legend-tag--doc">先生が入れた</span>{" "}
        頼まない限り Claude は書き換えない
      </span>
    </p>
  );
}
