import {
  AbsoluteFill,
  Img,
  interpolate,
  staticFile,
  useCurrentFrame,
} from "remotion";
import { portraitFile } from "../footage.generated";
import { splitIntroTitle } from "../lib/introTitle";
import { COLORS, FONT_FAMILY, FONT_SIZE } from "../theme";
import { appear, CLAMP } from "./anim";
import type { SceneComponentProps } from "./types";

/** 出現の時刻（場面の割合）。字幕の塊の頭（2 文目 ≈ 35%、3 文目 ≈ 66%）に合わせる */
const AT = {
  sub: 0.08,
  career: 0.36,
  careerEnd: 0.56,
  swap: 0.62,
  line: 0.66,
} as const;

const CENTER: React.CSSProperties = {
  justifyContent: "center",
  alignItems: "center",
  paddingBottom: 160,
};

const CareerCard: React.FC<{ text: string; focus: boolean; style: object }> = ({
  text,
  focus,
  style,
}) => (
  <div
    style={{
      padding: "16px 36px",
      borderRadius: 18,
      border: `5px solid ${focus ? COLORS.navy : COLORS.line}`,
      background: focus ? COLORS.navy : COLORS.white,
      color: focus ? COLORS.white : COLORS.ink,
      fontSize: 52,
      fontWeight: 800,
      whiteSpace: "nowrap",
      ...style,
    }}
  >
    {text}
  </div>
);

/** 大きな「25 年間」と副題（scene.title を読点で分ける） */
const Hero: React.FC<{ frame: number; duration: number; title: string }> = ({
  frame,
  duration,
  title,
}) => {
  const { number, unit, sub } = splitIntroTitle(title);
  return (
    <>
      <div style={{ lineHeight: 1.1, ...appear(frame, 0, 16, 30) }}>
        <span style={{ fontSize: 260, fontWeight: 900, color: COLORS.navy }}>
          {number}
        </span>
        <span style={{ fontSize: 110, fontWeight: 800 }}>
          {number ? ` ${unit}` : unit}
        </span>
      </div>
      {sub ? (
        <div
          style={{
            marginTop: 12,
            fontSize: FONT_SIZE.heading,
            fontWeight: 800,
            ...appear(frame, Math.round(AT.sub * duration)),
          }}
        >
          {sub}
        </div>
      ) : null}
    </>
  );
};

/** 先生の写真の位置（public/private/portrait.jpg があるときだけ出す） */
const PORTRAIT = { left: 130, top: 160, width: 480, height: 600 } as const;

const Portrait: React.FC<{ file: string; frame: number }> = ({
  file,
  frame,
}) => (
  <Img
    src={staticFile(file)}
    style={{
      position: "absolute",
      ...PORTRAIT,
      objectFit: "cover",
      borderRadius: 6,
      boxShadow: "0 14px 34px rgba(0,0,0,0.16)",
      ...appear(frame, 4, 26, 0),
    }}
  />
);

/** 前半: 大きな「25 年間」と副題、経歴の札が順に出る */
const Career: React.FC<{ frame: number; duration: number } & IntroData> = ({
  frame,
  duration,
  title,
  career,
  focus,
}) => {
  const step =
    ((AT.careerEnd - AT.career) * duration) / Math.max(1, career.length);
  const out = interpolate(
    frame,
    [AT.swap * duration - 10, AT.swap * duration],
    [1, 0],
    CLAMP,
  );
  return (
    <AbsoluteFill
      style={{
        ...CENTER,
        opacity: out,
        ...(portraitFile
          ? { paddingLeft: PORTRAIT.left + PORTRAIT.width + 30 }
          : {}),
      }}
    >
      {portraitFile ? <Portrait file={portraitFile} frame={frame} /> : null}
      <Hero frame={frame} duration={duration} title={title} />
      <div style={{ marginTop: 64, display: "flex", gap: 28 }}>
        {career.map((c, i) => (
          <CareerCard
            key={c}
            text={c}
            focus={c === focus}
            style={appear(frame, Math.round(AT.career * duration + i * step))}
          />
        ))}
      </div>
    </AbsoluteFill>
  );
};

/** 後半: 大きな「つたえ」と一文 */
const Tsutae: React.FC<{
  frame: number;
  duration: number;
  lines: string[];
}> = ({ frame, duration, lines }) => {
  const at = Math.round(AT.swap * duration);
  return (
    <AbsoluteFill style={{ ...CENTER, opacity: frame < at ? 0 : 1 }}>
      <div
        style={{
          fontSize: 200,
          fontWeight: 900,
          letterSpacing: 24,
          ...appear(frame, at, 16, 30),
        }}
      >
        つたえ
      </div>
      {lines.map((line, i) => (
        <div
          key={line}
          style={{
            marginTop: 28,
            fontSize: FONT_SIZE.heading,
            fontWeight: 700,
            color: COLORS.navy,
            ...appear(frame, Math.round(AT.line * duration) + i * 20),
          }}
        >
          {line}
        </div>
      ))}
    </AbsoluteFill>
  );
};

interface IntroData {
  title: string;
  career: string[];
  focus?: string;
}

/** 自己紹介: 「25 年間」と経歴の札 → 「つたえ」と一文に切り替わる */
export const IntroScene: React.FC<SceneComponentProps> = ({
  scene,
  durationInFrames,
}) => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill
      style={{
        background: COLORS.paper,
        fontFamily: FONT_FAMILY,
        color: COLORS.ink,
      }}
    >
      <Career
        frame={frame}
        duration={durationInFrames}
        title={scene.title ?? ""}
        career={scene.props?.career ?? []}
        focus={scene.props?.careerFocus}
      />
      <Tsutae
        frame={frame}
        duration={durationInFrames}
        lines={scene.props?.lines ?? []}
      />
    </AbsoluteFill>
  );
};
