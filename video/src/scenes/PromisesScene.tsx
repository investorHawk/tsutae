import { AbsoluteFill, useCurrentFrame } from "remotion";
import { COLORS, FONT_FAMILY } from "../theme";
import { appear } from "./anim";
import type { SceneComponentProps } from "./types";

const Column: React.FC<{
  title: string;
  items: string[];
  color: string;
  mark: string;
  starts: number[];
  frame: number;
  left: number;
  width: number;
}> = ({ title, items, color, mark, starts, frame, left, width }) => (
  <div style={{ position: "absolute", top: 120, left, width }}>
    <div
      style={{
        fontSize: 72,
        fontWeight: 900,
        color,
        borderBottom: `6px solid ${color}`,
        paddingBottom: 10,
        marginBottom: 26,
        ...appear(frame, Math.max(0, (starts[0] ?? 0) - 10)),
      }}
    >
      {title}
    </div>
    {items.map((item, i) => (
      <div
        key={item}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 22,
          fontSize: 52,
          fontWeight: 700,
          lineHeight: 1.25,
          padding: "12px 0",
          ...appear(frame, starts[i] ?? 0),
        }}
      >
        <span
          style={{
            width: 64,
            height: 64,
            flexShrink: 0,
            borderRadius: 14,
            background: color,
            color: COLORS.white,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: 44,
            fontWeight: 900,
          }}
        >
          {mark}
        </span>
        {item}
      </div>
    ))}
  </div>
);

/** 「AI がしないこと」5 つと「患者情報の扱い」3 つが順に出る */
export const PromisesScene: React.FC<SceneComponentProps> = ({
  scene,
  durationInFrames,
}) => {
  const frame = useCurrentFrame();
  const dont = scene.props?.dont ?? [];
  const privacy = scene.props?.privacy ?? [];
  const total = dont.length + privacy.length;
  // 字幕の順（しないこと → 情報の扱い）に、場面の 8 割で出し切る
  const step = (durationInFrames * 0.8) / Math.max(1, total);
  const startAt = (i: number) => Math.round(14 + i * step);
  return (
    <AbsoluteFill
      style={{
        background: COLORS.paper,
        fontFamily: FONT_FAMILY,
        color: COLORS.ink,
      }}
    >
      <Column
        title="AI がしないこと"
        items={dont}
        color={COLORS.reject}
        mark="×"
        starts={dont.map((_, i) => startAt(i))}
        frame={frame}
        left={110}
        width={800}
      />
      <Column
        title="患者情報の扱い"
        items={privacy}
        color={COLORS.navy}
        mark="✓"
        starts={privacy.map((_, i) => startAt(dont.length + i))}
        frame={frame}
        left={1010}
        width={820}
      />
    </AbsoluteFill>
  );
};
