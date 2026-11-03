import { useMemo } from "react";
import { interpolate, useCurrentFrame } from "remotion";
import { buildSubtitleChunks } from "../lib/subtitle";
import { COLORS, FONT_FAMILY, FONT_SIZE, SUBTITLE_TOP } from "../theme";

interface SubtitleProps {
  text: string;
  durationInFrames: number;
}

/** 下部の字幕。2 行以内の塊を字数に比例した時間で切り替える */
export const Subtitle: React.FC<SubtitleProps> = ({
  text,
  durationInFrames,
}) => {
  const frame = useCurrentFrame();
  const chunks = useMemo(() => buildSubtitleChunks(text), [text]);
  const progress = frame / durationInFrames;
  const current =
    chunks.find((c) => progress >= c.start && progress < c.end) ??
    chunks[chunks.length - 1];
  if (!current) return null;
  const startFrame = current.start * durationInFrames;
  const opacity = interpolate(frame, [startFrame, startFrame + 4], [0.4, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return (
    <div
      style={{
        position: "absolute",
        left: 0,
        right: 0,
        top: SUBTITLE_TOP,
        bottom: 0,
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
        zIndex: 90,
        pointerEvents: "none",
      }}
    >
      <div
        style={{
          background: "rgba(26, 26, 26, 0.86)",
          color: COLORS.white,
          fontFamily: FONT_FAMILY,
          fontSize: FONT_SIZE.subtitle,
          fontWeight: 600,
          lineHeight: 1.42,
          padding: "14px 40px",
          borderRadius: 14,
          textAlign: "center",
          maxWidth: 1640,
          opacity,
        }}
      >
        {current.lines.map((line, i) => (
          <div key={i} style={{ whiteSpace: "nowrap" }}>
            {line}
          </div>
        ))}
      </div>
    </div>
  );
};
