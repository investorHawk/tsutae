import { AbsoluteFill } from "remotion";
import { COLORS } from "../theme";

interface PhoneFrameProps {
  /** 画面（縦 9:16）の高さ */
  height?: number;
  top?: number;
  /** 枠の中心の x（既定は画面の中央） */
  centerX?: number;
  children: React.ReactNode;
}

/** 縦 9:16 の動画を 16:9 の中に収める。両脇は紙の色の帯のまま */
export const PhoneFrame: React.FC<PhoneFrameProps> = ({
  height = 812,
  top = 30,
  centerX = 960,
  children,
}) => {
  const width = Math.round((height * 9) / 16);
  const bezel = 16;
  return (
    <AbsoluteFill style={{ background: COLORS.paper }}>
      <div
        style={{
          position: "absolute",
          top,
          left: centerX - width / 2 - bezel,
          width: width + bezel * 2,
          height: height + bezel * 2,
          background: COLORS.ink,
          borderRadius: 56,
          padding: bezel,
          boxShadow: "0 24px 60px rgba(0,0,0,0.25)",
        }}
      >
        <div
          style={{
            width,
            height,
            borderRadius: 42,
            overflow: "hidden",
            background: COLORS.white,
            position: "relative",
          }}
        >
          {children}
        </div>
      </div>
    </AbsoluteFill>
  );
};
