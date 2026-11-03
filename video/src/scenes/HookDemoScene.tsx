import { AbsoluteFill, useCurrentFrame } from "remotion";
import { Caption } from "../components/Caption";
import { COLORS, FONT_FAMILY } from "../theme";
import { appear, ramp } from "./anim";
import type { SceneComponentProps } from "./types";

const ORIGINAL_HEAD = "おとといの夜から口内炎がいたい";
const ORIGINAL_TAIL = "。おかゆにした";
const BAD_QUOTE = "口内炎がつらい";

type Phase = "submit" | "rejected" | "fixed" | "accepted";

const phaseAt = (frame: number, duration: number): Phase => {
  if (frame >= duration * 0.72) return "accepted";
  if (frame >= duration * 0.55) return "fixed";
  if (frame >= duration * 0.28) return "rejected";
  return "submit";
};

const ORIGINAL_STYLE: React.CSSProperties = {
  position: "absolute",
  left: 80,
  right: 80,
  top: 170,
  padding: "20px 32px",
  borderRadius: 20,
  background: COLORS.white,
  border: `4px solid ${COLORS.line}`,
};

const OriginalCard: React.FC<{ match: number; frame: number }> = ({
  match,
  frame,
}) => (
  <div style={{ ...ORIGINAL_STYLE, ...appear(frame, 4) }}>
    <div style={{ fontSize: 34, color: COLORS.inkSoft }}>
      原文（Day7 11/2・伏せ字後）
    </div>
    <div style={{ fontSize: 52, fontWeight: 700 }}>
      <span
        style={{
          background: `rgba(27, 127, 59, ${0.22 * match})`,
          boxShadow: `inset 0 -6px 0 rgba(27,127,59,${match})`,
        }}
      >
        {ORIGINAL_HEAD}
      </span>
      {ORIGINAL_TAIL}
    </div>
  </div>
);

const QUOTE_STYLE: React.CSSProperties = {
  position: "absolute",
  left: 80,
  top: 420,
  width: 760,
  padding: "24px 32px",
  borderRadius: 22,
  background: COLORS.white,
  border: `5px solid ${COLORS.purple}`,
};

const QuoteCard: React.FC<{
  text: string;
  note: string;
  style: React.CSSProperties;
}> = ({ text, note, style }) => (
  <div style={{ ...QUOTE_STYLE, ...style }}>
    <div style={{ fontSize: 34, color: COLORS.purple, fontWeight: 700 }}>
      {note}
    </div>
    <div style={{ fontSize: 50, fontWeight: 800, lineHeight: 1.35 }}>
      「{text}」
    </div>
  </div>
);

const GATE_COLOR: Record<Phase, string> = {
  submit: COLORS.inkSoft,
  rejected: COLORS.reject,
  fixed: COLORS.inkSoft,
  accepted: COLORS.accept,
};

const Gate: React.FC<{ phase: Phase; style: React.CSSProperties }> = ({
  phase,
  style,
}) => {
  const color = GATE_COLOR[phase];
  const filled = phase === "rejected" || phase === "accepted";
  return (
    <div
      style={{
        position: "absolute",
        left: 900,
        top: 430,
        width: 200,
        height: 160,
        borderRadius: 80,
        border: `6px solid ${color}`,
        background: filled ? color : COLORS.white,
        color: filled ? COLORS.white : color,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontSize: 64,
        fontWeight: 900,
        ...style,
      }}
    >
      H2
    </div>
  );
};

const Verdict: React.FC<{ phase: Phase; style: React.CSSProperties }> = ({
  phase,
  style,
}) => {
  if (phase !== "rejected" && phase !== "accepted") return null;
  const ok = phase === "accepted";
  return (
    <div
      style={{
        position: "absolute",
        left: 1160,
        top: 440,
        width: 680,
        fontSize: 56,
        fontWeight: 900,
        lineHeight: 1.3,
        color: ok ? COLORS.accept : COLORS.reject,
        ...style,
      }}
    >
      {ok ? "✓ 受理（原文に一致）" : "× 拒否"}
      {ok ? null : (
        <div style={{ fontSize: 40, fontWeight: 700 }}>
          引用が原文に無い → 理由を返す
        </div>
      )}
    </div>
  );
};

/** 要約した引用 → H2 が拒否（赤）→ 原文どおりに直して受理（緑） */
export const HookDemoScene: React.FC<SceneComponentProps> = ({
  scene,
  durationInFrames,
}) => {
  const frame = useCurrentFrame();
  const at = (r: number) => Math.round(durationInFrames * r);
  const phase = phaseAt(frame, durationInFrames);
  const fixed = phase === "fixed" || phase === "accepted";
  return (
    <AbsoluteFill
      style={{
        background: COLORS.paper,
        fontFamily: FONT_FAMILY,
        color: COLORS.ink,
      }}
    >
      {scene.title ? <Caption text={scene.title} /> : null}
      <OriginalCard match={ramp(frame, at(0.72), 10)} frame={frame} />
      {fixed ? (
        <QuoteCard
          text={ORIGINAL_HEAD}
          note="Claude が原文どおりに直して出し直す"
          style={appear(frame, at(0.55))}
        />
      ) : (
        <QuoteCard
          text={BAD_QUOTE}
          note="要約した引用"
          style={appear(frame, at(0.04))}
        />
      )}
      <Gate phase={phase} style={appear(frame, at(0.12))} />
      <Verdict
        phase={phase}
        style={appear(frame, at(phase === "accepted" ? 0.72 : 0.28))}
      />
      <div
        style={{
          position: "absolute",
          left: 80,
          right: 80,
          top: 690,
          textAlign: "center",
          fontSize: 44,
          color: COLORS.inkSoft,
          ...appear(frame, at(0.12)),
        }}
      >
        H2 は、引用が伏せ字後の原文に部分一致しなければ拒否する
      </div>
    </AbsoluteFill>
  );
};
