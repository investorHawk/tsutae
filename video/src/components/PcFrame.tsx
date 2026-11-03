import { AbsoluteFill } from "remotion";
import { COLORS, FONT_FAMILY } from "../theme";

interface PcFrameProps {
  /** 画面（横 16:9）の幅 */
  width?: number;
  top?: number;
  label?: string;
  children: React.ReactNode;
}

const Dot: React.FC<{ color: string }> = ({ color }) => (
  <div style={{ width: 18, height: 18, borderRadius: 9, background: color }} />
);

/** 横の動画をブラウザ風の枠に入れる */
export const PcFrame: React.FC<PcFrameProps> = ({
  width = 1408,
  top = 24,
  label = "院内 PC — つたえ（医師）",
  children,
}) => {
  const height = Math.round((width * 9) / 16);
  const bar = 48;
  return (
    <AbsoluteFill style={{ background: COLORS.paper }}>
      <div
        style={{
          position: "absolute",
          top,
          left: (1920 - width) / 2,
          width,
          height: height + bar,
          borderRadius: 16,
          overflow: "hidden",
          border: `2px solid ${COLORS.line}`,
          boxShadow: "0 24px 60px rgba(0,0,0,0.18)",
          background: COLORS.white,
        }}
      >
        <div
          style={{
            height: bar,
            background: COLORS.paperDeep,
            display: "flex",
            alignItems: "center",
            gap: 10,
            padding: "0 18px",
          }}
        >
          <Dot color="#e0675c" />
          <Dot color="#e8b84a" />
          <Dot color="#6bbf59" />
          <div
            style={{
              marginLeft: 24,
              padding: "4px 20px",
              borderRadius: 8,
              background: COLORS.white,
              fontFamily: FONT_FAMILY,
              fontSize: 24,
              color: COLORS.inkSoft,
            }}
          >
            {label}
          </div>
        </div>
        <div style={{ width, height, position: "relative" }}>{children}</div>
      </div>
    </AbsoluteFill>
  );
};
