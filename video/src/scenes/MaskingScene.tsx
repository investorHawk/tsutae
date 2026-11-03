import {
  AbsoluteFill,
  OffthreadVideo,
  Sequence,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { Caption } from "../components/Caption";
import { FootageCard } from "../components/FootageCard";
import { PhoneFrame } from "../components/PhoneFrame";
import { footageFiles } from "../footage.generated";
import { footageSegments } from "../lib/timeline";
import { COLORS, FONT_FAMILY } from "../theme";
import { appear, ramp } from "./anim";
import type { SceneComponentProps } from "./types";

interface Token {
  text: string;
  masked?: string;
}

// 自由記載の例（架空）。人名・病院名・電話が伏せ字に置き換わる
const TOKENS: Token[] = [
  { text: "きのうは" },
  { text: "山田さん", masked: "○○さん" },
  { text: "に付き添ってもらい、" },
  { text: "みどり台病院", masked: "[病院]" },
  { text: "で点滴。何かあれば" },
  { text: "090-1234-5678", masked: "[電話]" },
  { text: "に。" },
];

const MaskedText: React.FC<{ frame: number; start: number; step: number }> = ({
  frame,
  start,
  step,
}) => {
  let maskIndex = 0;
  return (
    <div style={{ fontSize: 50, lineHeight: 1.7, fontWeight: 600 }}>
      {TOKENS.map((tok, i) => {
        if (!tok.masked) return <span key={i}>{tok.text}</span>;
        const t = ramp(frame, start + maskIndex * step, 10);
        maskIndex += 1;
        const done = t >= 1;
        return (
          <span
            key={i}
            style={{
              padding: "2px 8px",
              borderRadius: 8,
              background: done
                ? COLORS.navy
                : `rgba(179, 38, 30, ${0.18 + 0.2 * t})`,
              color: done ? COLORS.white : COLORS.reject,
              textDecoration: done ? "none" : t > 0 ? "line-through" : "none",
            }}
          >
            {done ? tok.masked : tok.text}
          </span>
        );
      })}
    </div>
  );
};

const Check: React.FC<{
  ok: boolean;
  text: string;
  style: React.CSSProperties;
}> = ({ ok, text, style }) => (
  <div
    style={{
      fontSize: 44,
      fontWeight: 800,
      color: ok ? COLORS.accept : COLORS.reject,
      borderLeft: `10px solid ${ok ? COLORS.accept : COLORS.reject}`,
      paddingLeft: 20,
      ...style,
    }}
  >
    {text}
  </div>
);

/** 左半分: F4 の録画（場面の最初の区間だけ）。無ければ細い枠のカード */
const LeftFootage: React.FC<{ scene: SceneComponentProps["scene"] }> = ({
  scene,
}) => {
  const { fps } = useVideoConfig();
  const seg = footageSegments(scene)[0];
  if (!seg) return null;
  const src = footageFiles[seg.id];
  const frames = Math.round(seg.seconds * fps);
  return (
    <Sequence durationInFrames={frames} layout="none">
      {src ? (
        <PhoneFrame height={780} top={50} centerX={430}>
          <OffthreadVideo
            src={staticFile(src)}
            muted
            endAt={frames}
            style={{ width: "100%", height: "100%", objectFit: "contain" }}
          />
        </PhoneFrame>
      ) : (
        <FootageCard id={seg.id} seconds={seg.seconds} compact />
      )}
    </Sequence>
  );
};

/** 右半分: 自由記載の伏せ字と、送る・送らないの判定 */
const MaskPanel: React.FC<{ frame: number; duration: number }> = ({
  frame,
  duration,
}) => {
  const at = (r: number) => Math.round(duration * r);
  return (
    <div
      style={{
        position: "absolute",
        top: 170,
        left: 900,
        right: 80,
        display: "flex",
        flexDirection: "column",
        gap: 26,
        color: COLORS.ink,
      }}
    >
      <div style={{ fontSize: 40, color: COLORS.inkSoft, ...appear(frame, 6) }}>
        自由記載（送る前）
      </div>
      <div
        style={{
          background: COLORS.white,
          border: `4px solid ${COLORS.line}`,
          borderRadius: 20,
          padding: "24px 32px",
          ...appear(frame, 10),
        }}
      >
        <MaskedText frame={frame} start={at(0.22)} step={22} />
      </div>
      <Check
        ok
        text="二次検出: 取り残しなし → Claude へ"
        style={appear(frame, at(0.55))}
      />
      <Check
        ok={false}
        text="疑いあり → 送らない（院内画面だけ）"
        style={appear(frame, at(0.65))}
      />
      <Check
        ok={false}
        text="受付番号 A-023 → 送らない"
        style={appear(frame, at(0.78))}
      />
    </div>
  );
};

/** 案 C: 受診（F4）の横で、自由記載の伏せ字が置き換わる */
export const MaskingScene: React.FC<SceneComponentProps> = ({
  scene,
  durationInFrames,
}) => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill style={{ background: COLORS.paper, fontFamily: FONT_FAMILY }}>
      <LeftFootage scene={scene} />
      {scene.title ? <Caption text={scene.title} top={48} left={900} /> : null}
      <MaskPanel frame={frame} duration={durationInFrames} />
    </AbsoluteFill>
  );
};
