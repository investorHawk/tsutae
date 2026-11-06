import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { formatClock } from "../components/Clock";
import { statText } from "../lib/stat";
import { COLORS, FONT_FAMILY } from "../theme";
import type { Stat } from "../types";
import { ClosingCompare } from "./ClosingCompare";
import { EndCard } from "./ClosingEndCard";
import { appear, CLAMP } from "./anim";
import type { SceneComponentProps } from "./types";

const COUNT_FRAMES = 30;

/**
 * 数字から最後のカードへ切り替える時刻（場面の割合）。
 * messages がある案 B は、1 つ目の文の読み上げ（約 30%）に間に合うよう早めに切り替える。
 */
const END_AT = { plain: 0.6, withMessages: 0.38 } as const;

const StatCard: React.FC<{ stat: Stat; start: number; frame: number }> = ({
  stat,
  start,
  frame,
}) => {
  const t = interpolate(frame, [start, start + COUNT_FRAMES], [0, 1], CLAMP);
  const isClock = stat.format === "clock";
  return (
    <div
      style={{
        minWidth: 330,
        padding: "22px 30px",
        borderRadius: 24,
        background: COLORS.white,
        border: `4px solid ${isClock ? COLORS.navy : COLORS.line}`,
        textAlign: "center",
        ...appear(frame, start - 6, 10),
      }}
    >
      <div style={{ fontSize: 44, color: COLORS.inkSoft, fontWeight: 700 }}>
        {stat.label}
      </div>
      <div
        style={{
          fontSize: isClock ? 120 : 104,
          fontWeight: 900,
          color: isClock ? COLORS.navy : COLORS.ink,
          fontVariantNumeric: "tabular-nums",
          lineHeight: 1.15,
        }}
      >
        {isClock && stat.from !== undefined ? (
          <span style={{ fontSize: 56, color: COLORS.inkSoft }}>
            {formatClock(stat.from)} →{" "}
          </span>
        ) : null}
        {statText(stat, t)}
      </div>
    </div>
  );
};

/** 数字の札のカウントアップ（案 A・C） */
const StatCards: React.FC<{ stats: Stat[]; endAt: number; frame: number }> = ({
  stats,
  endAt,
  frame,
}) => {
  const step = (endAt - 20) / Math.max(1, stats.length);
  return (
    <AbsoluteFill
      style={{
        flexDirection: "row",
        flexWrap: "wrap",
        justifyContent: "center",
        alignContent: "center",
        gap: 36,
        padding: "60px 80px 240px",
      }}
    >
      {stats.map((s, i) => (
        <StatCard
          key={s.label}
          stat={s}
          start={Math.round(10 + i * step)}
          frame={frame}
        />
      ))}
    </AbsoluteFill>
  );
};

/** 数字の札（compare があれば時間の棒グラフと事実）→ 最後のカード */
export const ClosingScene: React.FC<SceneComponentProps> = ({
  scene,
  durationInFrames,
}) => {
  const frame = useCurrentFrame();
  const { stats = [], compare, facts = [], messages = [] } = scene.props ?? {};
  const endRatio = messages.length > 0 ? END_AT.withMessages : END_AT.plain;
  const endAt = Math.round(durationInFrames * endRatio);
  return (
    <AbsoluteFill
      style={{
        background: COLORS.paper,
        fontFamily: FONT_FAMILY,
        color: COLORS.ink,
      }}
    >
      <AbsoluteFill
        style={{
          opacity: interpolate(frame, [endAt, endAt + 12], [1, 0], CLAMP),
        }}
      >
        {compare ? (
          <ClosingCompare compare={compare} facts={facts} frame={frame} />
        ) : (
          <StatCards stats={stats} endAt={endAt} frame={frame} />
        )}
      </AbsoluteFill>
      <EndCard
        frame={frame}
        at={endAt}
        messages={messages}
        durationInFrames={durationInFrames}
      />
    </AbsoluteFill>
  );
};
