import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { Caption } from "../components/Caption";
import { Clock } from "../components/Clock";
import { SpeechBubble } from "../components/People";
import { COLORS, FONT_FAMILY } from "../theme";
import type { Bubble } from "../types";
import { appear, CLAMP } from "./anim";
import type { SceneComponentProps } from "./types";

const Conversation: React.FC<{
  bubbles: Bubble[];
  frame: number;
  step: number;
}> = ({ bubbles, frame, step }) => (
  <div
    style={{
      position: "absolute",
      top: 170,
      left: 100,
      width: 1080,
      display: "flex",
      flexDirection: "column",
      gap: 16,
    }}
  >
    {bubbles.map((b, i) => {
      const a = appear(frame, Math.round(8 + i * step));
      return (
        <SpeechBubble
          key={b.text}
          who={b.who}
          text={`${b.who === "doctor" ? "医師" : "患者"}「${b.text}」`}
          opacity={a.opacity}
          style={{
            transform: a.transform,
            alignSelf: b.who === "doctor" ? "flex-start" : "flex-end",
          }}
        />
      );
    })}
  </div>
);

const LOSS_STYLE: React.CSSProperties = {
  flex: 1,
  padding: "26px 28px",
  borderRadius: 20,
  border: `5px solid ${COLORS.reject}`,
  background: COLORS.white,
  color: COLORS.reject,
  fontSize: 50,
  fontWeight: 800,
  textAlign: "center",
};

const Losses: React.FC<{ losses: string[]; frame: number; start: number }> = ({
  losses,
  frame,
  start,
}) => (
  <div
    style={{
      position: "absolute",
      top: 680,
      left: 100,
      right: 100,
      display: "flex",
      gap: 36,
    }}
  >
    {losses.map((loss, i) => (
      <div
        key={loss}
        style={{ ...LOSS_STYLE, ...appear(frame, Math.round(start + i * 14)) }}
      >
        × {loss}
      </div>
    ))}
  </div>
);

/** 吹き出しの会話が順に出て、時計が 3:00 まで回る。最後に損失 3 つ */
export const BeforeScene: React.FC<SceneComponentProps> = ({
  scene,
  durationInFrames,
}) => {
  const frame = useCurrentFrame();
  const bubbles = scene.props?.bubbles ?? [];
  const step = (durationInFrames * 0.4) / Math.max(1, bubbles.length);
  const elapsed = interpolate(
    frame,
    [0, durationInFrames * 0.6],
    [0, 180],
    CLAMP,
  );
  return (
    <AbsoluteFill style={{ background: COLORS.paper, fontFamily: FONT_FAMILY }}>
      {scene.title ? <Caption text={scene.title} /> : null}
      <Conversation bubbles={bubbles} frame={frame} step={step} />
      <div style={{ position: "absolute", top: 150, right: 170 }}>
        <Clock
          seconds={elapsed}
          size={300}
          color={COLORS.reject}
          label="聞き取り"
        />
      </div>
      <Losses
        losses={scene.props?.losses ?? []}
        frame={frame}
        start={durationInFrames * 0.62}
      />
    </AbsoluteFill>
  );
};
