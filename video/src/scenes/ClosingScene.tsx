import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { formatClock } from "../components/Clock";
import { COLORS, FONT_FAMILY } from "../theme";
import type { Stat } from "../types";
import { appear, CLAMP } from "./anim";
import type { SceneComponentProps } from "./types";

const COUNT_FRAMES = 30;

const statText = (stat: Stat, t: number): string => {
  const from = stat.from ?? 0;
  const value = from + (stat.to - from) * t;
  if (stat.format === "clock") return formatClock(value);
  return `${Math.round(value).toLocaleString("ja-JP")}${stat.unit ?? ""}`;
};

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

/** 最後のカード: 「つたえ」「Built with Claude Code」「症例は全て合成」 */
const EndCard: React.FC<{ frame: number; at: number }> = ({ frame, at }) => (
  <AbsoluteFill
    style={{
      justifyContent: "center",
      alignItems: "center",
      paddingBottom: 200,
      opacity: interpolate(frame, [at + 8, at + 20], [0, 1], CLAMP),
    }}
  >
    <div style={{ fontSize: 200, fontWeight: 900, letterSpacing: 24 }}>
      つたえ
    </div>
    <div
      style={{
        fontSize: 64,
        fontWeight: 800,
        color: COLORS.purple,
        ...appear(frame, at + 22),
      }}
    >
      Built with Claude Code
    </div>
    <div
      style={{
        marginTop: 24,
        fontSize: 44,
        color: COLORS.inkSoft,
        ...appear(frame, at + 32),
      }}
    >
      症例は全て合成（架空）
    </div>
  </AbsoluteFill>
);

/** 数字のカウントアップ → 最後のカード */
export const ClosingScene: React.FC<SceneComponentProps> = ({
  scene,
  durationInFrames,
}) => {
  const frame = useCurrentFrame();
  const stats = scene.props?.stats ?? [];
  const endAt = Math.round(durationInFrames * 0.6);
  const step = (endAt - 20) / Math.max(1, stats.length);
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
      <EndCard frame={frame} at={endAt} />
    </AbsoluteFill>
  );
};
