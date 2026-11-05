import type { DrugRow, Route } from "../../../api/regimenTypes";
import { formatDays } from "./fieldValues";

export const ROUTE_LABELS: Readonly<Record<Route, string>> = {
  infusion: "点滴",
  oral: "内服",
  pump: "持続ポンプ",
};

const MAX_DAYS = 42;

interface DayBarProps {
  cycleDays: number | null;
  drugs: readonly DrugRow[];
}

function onDay(drug: DrugRow, day: number): boolean {
  return drug.days.some((r) => r.start <= day && day <= r.end);
}

/**
 * 1コースの投与の帯。1コースの日数ぶんの升に、薬ごとの投与日を経路の色で塗る。
 * 色だけに頼らないよう、行の名前に経路と Day を文字でも添える。
 */
export default function DayBar({ cycleDays, drugs }: DayBarProps) {
  if (cycleDays === null || cycleDays < 1 || drugs.length === 0) {
    return null;
  }
  const days = Array.from(
    { length: Math.min(cycleDays, MAX_DAYS) },
    (_, i) => i + 1,
  );
  const columns = { gridTemplateColumns: `repeat(${days.length}, 1fr)` };
  return (
    <figure className="rf-daybar" aria-label="1コースの投与の帯">
      <div className="rf-daybar-row">
        <span className="rf-daybar-name">1コース {cycleDays} 日</span>
        <div className="rf-daybar-cells" style={columns} aria-hidden="true">
          {days.map((d) => (
            <span key={d} className="rf-daybar-day">
              {d === 1 || d % 7 === 0 ? d : ""}
            </span>
          ))}
        </div>
      </div>
      {drugs.map((drug) => (
        <div key={drug.row_id} className="rf-daybar-row">
          <span className="rf-daybar-name">
            {drug.name ?? "（名前なし）"}
            <span className="rf-daybar-note">
              {drug.route ? ROUTE_LABELS[drug.route] : "経路なし"}
              {drug.days.length > 0 ? ` ${formatDays(drug.days)}` : ""}
            </span>
          </span>
          <div className="rf-daybar-cells" style={columns} aria-hidden="true">
            {days.map((d) => (
              <span
                key={d}
                className={
                  onDay(drug, d)
                    ? `rf-daybar-cell rf-daybar-cell--${drug.route ?? "none"}`
                    : "rf-daybar-cell"
                }
              />
            ))}
          </div>
        </div>
      ))}
      <figcaption className="rf-daybar-legend">
        <span className="rf-swatch rf-daybar-cell--infusion" /> 点滴
        <span className="rf-swatch rf-daybar-cell--oral" /> 内服
        <span className="rf-swatch rf-daybar-cell--pump" /> 持続ポンプ
        <span>
          日付の言い方（「飲み薬が終わった日」→ Day14
          など）はこの表から自動で作ります
        </span>
      </figcaption>
    </figure>
  );
}
