import { useMemo } from "react";
import { interpolate, useCurrentFrame } from "remotion";
import { buildSubtitleChunks, chunkAt } from "../lib/subtitle";
import { COLORS, FONT_FAMILY, FONT_SIZE, SUBTITLE_TOP } from "../theme";

interface SubtitleProps {
  text: string;
  durationInFrames: number;
  /** 塊を配る区間の開始（フレーム。声の開始。既定は 0） */
  activeFrom?: number;
  /** 塊を配る区間の終了（フレーム。声の終了。既定は durationInFrames） */
  activeTo?: number;
}

/**
 * 下部の字幕。2 行以内の塊を字数に比例した時間で切り替える。
 * activeFrom / activeTo があればその区間（声の区間）に塊を配る。
 */
export const Subtitle: React.FC<SubtitleProps> = ({
  text,
  durationInFrames,
  activeFrom = 0,
  activeTo = durationInFrames,
}) => {
  const frame = useCurrentFrame();
  const chunks = useMemo(() => buildSubtitleChunks(text), [text]);
  if (chunks.length === 0) return null;
  const { index, startFrame } = chunkAt(chunks, frame, activeFrom, activeTo);
  const current = chunks[index];
  // 最初の塊は場面の頭から出す（声の前の lead の間に薄いままにしない）
  const fadeFrom = index === 0 ? 0 : startFrame;
  const opacity = interpolate(frame, [fadeFrom, fadeFrom + 4], [0.4, 1], {
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
