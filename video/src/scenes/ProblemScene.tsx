import { AbsoluteFill, useCurrentFrame } from "remotion";
import { Caption } from "../components/Caption";
import { Person, SpeechBubble } from "../components/People";
import { COLORS, FONT_FAMILY } from "../theme";
import type { Bubble } from "../types";
import { appear } from "./anim";
import type { SceneComponentProps } from "./types";

const BubbleColumn: React.FC<{
  bubbles: { bubble: Bubble; start: number }[];
  side: "left" | "right";
  frame: number;
}> = ({ bubbles, side, frame }) => (
  <div
    style={{
      position: "absolute",
      top: 170,
      [side]: 120,
      display: "flex",
      flexDirection: "column",
      alignItems: side === "left" ? "flex-start" : "flex-end",
      gap: 18,
      maxWidth: 820,
    }}
  >
    {bubbles.map(({ bubble, start }) => {
      const a = appear(frame, start);
      return (
        <SpeechBubble
          key={bubble.text}
          who={bubble.who}
          text={bubble.text}
          opacity={a.opacity}
          style={{ transform: a.transform }}
        />
      );
    })}
  </div>
);

/** 診察室の図: 医師と患者・吹き出しが順に出る・中央に「2 週間 → 3 分」 */
export const ProblemScene: React.FC<SceneComponentProps> = ({
  scene,
  durationInFrames,
}) => {
  const frame = useCurrentFrame();
  const bubbles = scene.props?.bubbles ?? [];
  const step = (durationInFrames * 0.7) / Math.max(1, bubbles.length);
  const timed = bubbles.map((bubble, i) => ({
    bubble,
    start: Math.round(12 + i * step),
  }));
  return (
    <AbsoluteFill style={{ background: COLORS.paper, fontFamily: FONT_FAMILY }}>
      {scene.title ? <Caption text={scene.title} /> : null}
      <BubbleColumn
        side="left"
        frame={frame}
        bubbles={timed.filter((b) => b.bubble.who === "doctor")}
      />
      <BubbleColumn
        side="right"
        frame={frame}
        bubbles={timed.filter((b) => b.bubble.who === "patient")}
      />
      <Person who="doctor" x={240} y={430} />
      <Person who="patient" x={1460} y={430} />
      <div
        style={{
          position: "absolute",
          left: 520,
          width: 880,
          top: 500,
          display: "flex",
          justifyContent: "center",
          alignItems: "center",
          gap: 36,
          fontSize: 88,
          fontWeight: 900,
          color: COLORS.ink,
          ...appear(frame, Math.round(durationInFrames * 0.25)),
        }}
      >
        <span>2 週間</span>
        <span style={{ color: COLORS.inkSoft, fontSize: 72 }}>→</span>
        <span style={{ color: COLORS.reject }}>3 分</span>
      </div>
      <div
        style={{
          position: "absolute",
          left: 440,
          width: 1040,
          top: 700,
          height: 36,
          background: COLORS.paperDeep,
          border: `4px solid ${COLORS.line}`,
          borderRadius: 10,
        }}
      />
    </AbsoluteFill>
  );
};
