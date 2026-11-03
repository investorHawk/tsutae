import {
  AbsoluteFill,
  OffthreadVideo,
  staticFile,
  useVideoConfig,
} from "remotion";
import { FOOTAGE } from "../footage";
import { footageFiles } from "../footage.generated";
import { COLORS, FONT_FAMILY } from "../theme";
import type { FootageId } from "../types";
import { FootageCard } from "./FootageCard";
import { PcFrame } from "./PcFrame";
import { PhoneFrame } from "./PhoneFrame";

interface FootageSlotProps {
  id: FootageId;
  /** この区間の秒（録画はここで切る） */
  seconds: number;
  /** 左の帯の見出し（スマホのとき） */
  label?: string;
  /** 右の帯の一言 */
  callout?: string | null;
}

/** manifest にある録画だけを <OffthreadVideo> に渡す（無ければ枠のカード） */
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
      style={{
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
    style={{
      position: "absolute",
      top: 110,
      right: 300,
      maxWidth: 1000,
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

export const FootageSlot: React.FC<FootageSlotProps> = ({
  id,
  seconds,
  label,
  callout,
}) => {
  const spec = FOOTAGE[id];
  const src = footageFiles[id];
  if (!src) {
    return (
      <AbsoluteFill>
        <FootageCard id={id} seconds={seconds} />
      </AbsoluteFill>
    );
  }
  if (spec.device === "camera") {
    return (
      <AbsoluteFill>
        <Video src={src} seconds={seconds} cover />
        {callout ? <Callout text={callout} /> : null}
      </AbsoluteFill>
    );
  }
  if (spec.device === "pc") {
    return (
      <AbsoluteFill>
        <PcFrame>
          <Video src={src} seconds={seconds} />
        </PcFrame>
        {callout ? <Callout text={callout} /> : null}
      </AbsoluteFill>
    );
  }
  return (
    <AbsoluteFill>
      <PhoneFrame>
        <Video src={src} seconds={seconds} />
      </PhoneFrame>
      <SideText side="left" text={label ?? spec.scene} />
      {callout ? <SideText side="right" text={callout} strong /> : null}
    </AbsoluteFill>
  );
};
