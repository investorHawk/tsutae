// closing（案 B）: 聞き取りの時間の棒グラフと、その下の事実。数字の札（StatCard）の代わりに出す。
import { interpolate } from "remotion";
import { barRatios, compareSchedule } from "../lib/compare";
import { formatClock } from "../lib/clock";
import { COLORS } from "../theme";
import type { Compare, CompareItem, Fact } from "../types";
import { appear, CLAMP } from "./anim";

/** 行の見出し・時間の欄の幅（px）。残りが棒の長さの最大 */
const LABEL_WIDTH = 240;
const TIME_WIDTH = 300;

const BarRow: React.FC<{
  item: CompareItem;
  ratio: number;
  /** 0〜1 の伸び */
  grow: number;
  emphasis: boolean;
}> = ({ item, ratio, grow, emphasis }) => {
  const color = emphasis ? COLORS.navy : COLORS.inkSoft;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 32 }}>
      <div
        style={{
          width: LABEL_WIDTH,
          textAlign: "right",
          fontSize: 52,
          fontWeight: 800,
          color,
        }}
      >
        {item.label}
      </div>
      <div style={{ flex: 1, height: 72, position: "relative" }}>
        <div
          style={{
            position: "absolute",
            left: 0,
            top: 0,
            bottom: 0,
            width: `${ratio * grow * 100}%`,
            minWidth: grow > 0 ? 8 : 0,
            borderRadius: 14,
            background: color,
            opacity: emphasis ? 1 : 0.55,
          }}
        />
      </div>
      <div
        style={{
          width: TIME_WIDTH,
          fontSize: emphasis ? 112 : 72,
          fontWeight: 900,
          color,
          fontVariantNumeric: "tabular-nums",
          lineHeight: 1.1,
          whiteSpace: "nowrap",
        }}
      >
        {formatClock(item.seconds * grow)}
      </div>
    </div>
  );
};

const FactCard: React.FC<{ fact: Fact }> = ({ fact }) => (
  <div
    style={{
      padding: "22px 48px",
      borderRadius: 24,
      background: COLORS.white,
      border: `4px solid ${COLORS.line}`,
      textAlign: "center",
      lineHeight: 1.3,
    }}
  >
    <div style={{ fontSize: 44, fontWeight: 800, color: COLORS.inkSoft }}>
      {fact.label}
    </div>
    <div
      style={{
        fontSize: 104,
        fontWeight: 900,
        color: COLORS.navy,
        lineHeight: 1.15,
      }}
    >
      {fact.value}
    </div>
    {fact.note ? (
      <div style={{ fontSize: 32, color: COLORS.inkSoft }}>{fact.note}</div>
    ) : null}
  </div>
);

/** 見出し → 棒が 1 行目から順に伸びる（最後の行を紺で大きく）→ 事実 */
export const ClosingCompare: React.FC<{
  compare: Compare;
  facts: Fact[];
  frame: number;
}> = ({ compare, facts, frame }) => {
  const ratios = barRatios(compare.items);
  const { barStarts, barFrames, factsAt } = compareSchedule(
    compare.items.length,
  );
  const last = compare.items.length - 1;
  return (
    <div
      style={{
        position: "absolute",
        top: 120,
        left: 160,
        right: 160,
        display: "flex",
        flexDirection: "column",
        gap: 36,
        lineHeight: 1.3,
      }}
    >
      <div
        style={{
          fontSize: 60,
          fontWeight: 900,
          textAlign: "center",
          ...appear(frame, 4, 10),
        }}
      >
        {compare.title}
      </div>
      {compare.items.map((item, i) => (
        <BarRow
          key={item.label}
          item={item}
          ratio={ratios[i] ?? 0}
          grow={interpolate(
            frame,
            [barStarts[i], barStarts[i] + barFrames],
            [0, 1],
            CLAMP,
          )}
          emphasis={i === last}
        />
      ))}
      <div
        style={{
          marginTop: 24,
          display: "flex",
          justifyContent: "center",
          gap: 36,
          ...appear(frame, factsAt, 10),
        }}
      >
        {facts.map((f) => (
          <FactCard key={f.label} fact={f} />
        ))}
      </div>
    </div>
  );
};
