import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { Caption } from "../components/Caption";
import { Clock } from "../components/Clock";
import { clockSecondsOf } from "../lib/clock";
import { SpeechBubble } from "../components/People";
import { COLORS, FONT_FAMILY } from "../theme";
import type { Bubble } from "../types";
import { appear, CLAMP } from "./anim";
import type { SceneComponentProps } from "./types";

/** 吹き出しが 5 つ以上なら、下の札にかからないよう小さく詰める */
const COMPACT_FROM = 5;
const COMPACT_BUBBLE: React.CSSProperties = {
  padding: "8px 30px",
  fontSize: 40,
  lineHeight: 1.35,
};

const Conversation: React.FC<{
  bubbles: Bubble[];
  frame: number;
  step: number;
}> = ({ bubbles, frame, step }) => {
  const compact = bubbles.length >= COMPACT_FROM;
  return (
    <div
      style={{
        position: "absolute",
        top: compact ? 148 : 170,
        left: 100,
        width: 1080,
        display: "flex",
        flexDirection: "column",
        gap: compact ? 8 : 10,
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
              ...(compact ? COMPACT_BUBBLE : {}),
              transform: a.transform,
              alignSelf: b.who === "doctor" ? "flex-start" : "flex-end",
            }}
          />
        );
      })}
    </div>
  );
};

const LOSS_STYLE: React.CSSProperties = {
  flex: 1,
  padding: "18px 20px",
  borderRadius: 20,
  border: `5px solid ${COLORS.reject}`,
  background: COLORS.white,
  color: COLORS.reject,
  fontSize: 42,
  whiteSpace: "nowrap",
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
      top: 720,
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

/** 吹き出しの会話が順に出て、時計が clockSeconds（既定 3:00。案 B は 2:00）まで回る。最後に損失 3 つ */
export const BeforeScene: React.FC<SceneComponentProps> = ({
  scene,
  durationInFrames,
}) => {
  const frame = useCurrentFrame();
  const bubbles = scene.props?.bubbles ?? [];
  const step = (durationInFrames * 0.4) / Math.max(1, bubbles.length);
  const full = clockSecondsOf("before", scene.props);
  const elapsed = interpolate(
    frame,
    [0, durationInFrames * 0.6],
    [0, full],
    CLAMP,
  );
  return (
    <AbsoluteFill style={{ background: COLORS.paper, fontFamily: FONT_FAMILY }}>
      {scene.title ? <Caption text={scene.title} /> : null}
      <Conversation bubbles={bubbles} frame={frame} step={step} />
      <div style={{ position: "absolute", top: 150, right: 170 }}>
        <Clock
          seconds={elapsed}
          fullSeconds={full}
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
