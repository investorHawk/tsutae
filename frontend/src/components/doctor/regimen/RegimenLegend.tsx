/** 欄の状態の凡例（色の意味。ai と doc は欄の下に札を見せないので、ここが説明になる）。 */
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
        <span className="rf-legend-tag rf-legend-tag--doc">先生の値</span>{" "}
        先生の文から入った欄は次の文で Claude
        が直すことがある。直接入れた欄は頼まない限り書き換えない
      </span>
    </p>
  );
}
