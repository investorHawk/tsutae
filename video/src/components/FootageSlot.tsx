import {
  AbsoluteFill,
  OffthreadVideo,
  staticFile,
  useVideoConfig,
} from "remotion";
import { FOOTAGE } from "../footage";
import { footageFiles, screenFiles } from "../footage.generated";
import { COLORS, FONT_FAMILY } from "../theme";
import type { FootageId } from "../types";
import { FootageCard } from "./FootageCard";
import { PcFrame } from "./PcFrame";
import { PhoneFrame } from "./PhoneFrame";
import { ScreenSlides } from "./ScreenSlides";

interface FootageSlotProps {
  id: FootageId;
  /** この区間の秒（録画はここで切る） */
  seconds: number;
  /** 左の帯の見出し（スマホのとき） */
  label?: string;
  /** 右の帯の一言 */
  callout?: string | null;
}

/** manifest にある録画だけを <OffthreadVideo> に渡す */
const Video: React.FC<{ src: string; seconds: number; cover?: boolean }> = ({
  src,
  seconds,
  cover = false,
}) => {
  const { fps } = useVideoConfig();
  return (
    <OffthreadVideo
      src={staticFile(src)}
      muted
      endAt={Math.round(seconds * fps)}
      style={{
        width: "100%",
        height: "100%",
        objectFit: cover ? "cover" : "contain",
        background: COLORS.ink,
      }}
    />
  );
};

/**
 * 日本語を文節で折り返し、行の長さをそろえる（「届/く」「口/内炎」のような泣き別れを防ぐ）。
 * auto-phrase は lang="ja" の要素で効く（Chrome 119 以降）。csstype に無い値なので型を外す。
 */
const PHRASE_WRAP = {
  wordBreak: "auto-phrase",
  textWrap: "balance",
} as unknown as React.CSSProperties;

const SideText: React.FC<{
  side: "left" | "right";
  text: string;
  strong?: boolean;
}> = ({ side, text, strong = false }) => (
  <div
    style={{
      position: "absolute",
      top: 0,
      bottom: 1080 - 860,
      [side]: 60,
      width: 600,
      display: "flex",
      alignItems: "center",
      justifyContent: side === "left" ? "flex-start" : "flex-end",
      fontFamily: FONT_FAMILY,
    }}
  >
    <div
      lang="ja"
      style={{
        ...PHRASE_WRAP,
        // 札の文は構成データの \n で改行できる
        whiteSpace: "pre-line",
        fontSize: strong ? 52 : 72,
        fontWeight: 800,
        lineHeight: 1.35,
        color: strong ? COLORS.navy : COLORS.ink,
        background: strong ? COLORS.white : "transparent",
        border: strong ? `5px solid ${COLORS.navy}` : "none",
        borderRadius: 24,
        padding: strong ? "28px 34px" : 0,
        textAlign: side,
      }}
    >
      {text}
    </div>
  </div>
);

const Callout: React.FC<{ text: string }> = ({ text }) => (
  <div
    lang="ja"
    style={{
      ...PHRASE_WRAP,
      // 構成データの \n で改行する（製品名を行の途中で割らない）
      whiteSpace: "pre-line",
      position: "absolute",
      top: 110,
      right: 300,
      // 「口内炎は、食事がとれたかも次から聞いて」（21 字＋括弧）が 1 行に収まる幅
      maxWidth: 1240,
      padding: "18px 30px",
      background: COLORS.white,
      border: `5px solid ${COLORS.navy}`,
      borderRadius: 20,
      fontFamily: FONT_FAMILY,
      fontSize: 48,
      fontWeight: 800,
      color: COLORS.navy,
      boxShadow: "0 10px 24px rgba(0,0,0,0.18)",
    }}
  >
    {text}
  </div>
);

/** 録画 → 静止画のスライドの順に選ぶ（どちらも無ければ null） */
const Media: React.FC<{ id: FootageId; seconds: number; cover: boolean }> = ({
  id,
  seconds,
  cover,
}) => {
  const { fps } = useVideoConfig();
  const src = footageFiles[id];
  if (src) return <Video src={src} seconds={seconds} cover={cover} />;
  const screens = screenFiles[id] ?? [];
  if (screens.length === 0) return null;
  return (
    <ScreenSlides
      files={screens}
      totalFrames={Math.round(seconds * fps)}
      cover={cover}
    />
  );
};

const hasMedia = (id: FootageId): boolean =>
  Boolean(footageFiles[id]) || (screenFiles[id]?.length ?? 0) > 0;

/** 録画 → 静止画のスライド → 撮影枠のカード の優先順で出す */
export const FootageSlot: React.FC<FootageSlotProps> = ({
  id,
  seconds,
  label,
  callout,
}) => {
  const spec = FOOTAGE[id];
  if (!hasMedia(id)) {
    return (
      <AbsoluteFill>
        <FootageCard id={id} seconds={seconds} />
      </AbsoluteFill>
    );
  }
  const media = (
    <Media id={id} seconds={seconds} cover={spec.device === "camera"} />
  );
  if (spec.device === "camera") {
    return (
      <AbsoluteFill>
        {media}
        {callout ? <Callout text={callout} /> : null}
      </AbsoluteFill>
    );
  }
  if (spec.device === "pc") {
    return (
      <AbsoluteFill>
        <PcFrame>{media}</PcFrame>
        {callout ? <Callout text={callout} /> : null}
      </AbsoluteFill>
    );
  }
  return (
    <AbsoluteFill>
      <PhoneFrame>{media}</PhoneFrame>
      <SideText side="left" text={label ?? spec.scene} />
      {callout ? <SideText side="right" text={callout} strong /> : null}
    </AbsoluteFill>
  );
};
