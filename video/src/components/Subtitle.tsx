import { useMemo } from "react";
import { interpolate, useCurrentFrame } from "remotion";
import { buildSubtitleChunks, chunkAt, timeChunks } from "../lib/subtitle";
import { COLORS, FONT_FAMILY, FONT_SIZE, SUBTITLE_TOP } from "../theme";

interface SubtitleProps {
  text: string;
  durationInFrames: number;
  /** 実際の声での塊の開始（秒）と場面の秒数。あれば字幕を声に合わせる */
  voiceStarts?: readonly number[];
  sceneSeconds?: number;
}

/** 下部の字幕。2 行以内の塊を字数に比例した時間で切り替える */
export const Subtitle: React.FC<SubtitleProps> = ({
  text,
  durationInFrames,
  voiceStarts,
  sceneSeconds = 0,
}) => {
  const frame = useCurrentFrame();
  const chunks = useMemo(() => {
    const built = buildSubtitleChunks(text);
    return voiceStarts ? timeChunks(built, voiceStarts, sceneSeconds) : built;
  }, [text, voiceStarts, sceneSeconds]);
  if (chunks.length === 0) return null;
  const { index, startFrame } = chunkAt(chunks, frame, durationInFrames);
  const current = chunks[index];
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
