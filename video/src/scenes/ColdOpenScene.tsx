import {
  AbsoluteFill,
  interpolate,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { formatClock } from "../components/Clock";
import { COLORS, FONT_FAMILY, FONT_SIZE } from "../theme";
import { appear, CLAMP } from "./anim";
import type { SceneComponentProps } from "./types";

/** 大きな数字: 3:00 から 0:30 まで数えて下がり、タイトルが出ると上へ縮む */
const BigClock: React.FC<{ frame: number; titleAt: number }> = ({
  frame,
  titleAt,
}) => {
  const { fps } = useVideoConfig();
  const swapAt = Math.round(1.6 * fps);
  const t = interpolate(frame, [swapAt, swapAt + 0.8 * fps], [0, 1], CLAMP);
  const lift = interpolate(frame, [titleAt, titleAt + 14], [0, -150], CLAMP);
  const shrink = interpolate(frame, [titleAt, titleAt + 14], [1, 0.62], CLAMP);
  return (
    <>
      <div
        style={{
          fontSize: 44,
          color: COLORS.inkSoft,
          transform: `translateY(${lift}px)`,
          opacity: interpolate(frame, [titleAt, titleAt + 10], [1, 0], CLAMP),
        }}
      >
        診察室の聞き取り
      </div>
      <div
        style={{
          fontSize: 360,
          fontWeight: 900,
          lineHeight: 1,
          color: t < 1 ? COLORS.ink : COLORS.navy,
          fontVariantNumeric: "tabular-nums",
          transform: `translateY(${lift}px) scale(${shrink})`,
        }}
      >
        {formatClock(180 - 150 * t)}
      </div>
    </>
  );
};

const TitleBlock: React.FC<{ frame: number; at: number; lines: string[] }> = ({
  frame,
  at,
  lines,
}) => (
  <div
    style={{
      position: "absolute",
      top: 560,
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
    }}
  >
    <div
      style={{
        fontSize: 180,
        fontWeight: 900,
        letterSpacing: 20,
        color: COLORS.ink,
        ...appear(frame, at + 6, 14, 30),
      }}
    >
      つたえ
    </div>
    {lines.map((line, i) => (
      <div
        key={line}
        style={{
          fontSize: FONT_SIZE.body,
          fontWeight: 600,
          color: COLORS.navy,
          ...appear(frame, at + 20 + i * 10),
        }}
      >
        {line}
      </div>
    ))}
  </div>
);

/** 大きな「3:00」が「0:30」に変わり、「つたえ」が出る */
export const ColdOpenScene: React.FC<SceneComponentProps> = ({
  scene,
  durationInFrames,
}) => {
  const frame = useCurrentFrame();
  const titleAt = Math.round(durationInFrames * 0.55);
  return (
    <AbsoluteFill
      style={{
        background: COLORS.paper,
        justifyContent: "center",
        alignItems: "center",
        fontFamily: FONT_FAMILY,
        paddingBottom: 140,
      }}
    >
      <BigClock frame={frame} titleAt={titleAt} />
      <TitleBlock frame={frame} at={titleAt} lines={scene.props?.lines ?? []} />
    </AbsoluteFill>
  );
};
