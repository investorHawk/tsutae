import { interpolate, useCurrentFrame } from "remotion";
import { COLORS, FONT_FAMILY, FONT_SIZE } from "../theme";

interface CaptionProps {
  text: string;
  /** 左上からの位置 */
  top?: number;
  left?: number;
  size?: number;
  color?: string;
}

/** 場面の見出し（左上。少し下からすっと出る） */
export const Caption: React.FC<CaptionProps> = ({
  text,
  top = 48,
  left = 72,
  size = FONT_SIZE.heading,
  color = COLORS.ink,
}) => {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [4, 16], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const y = interpolate(frame, [4, 16], [16, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return (
    <div
      style={{
        position: "absolute",
        top,
        left,
        fontFamily: FONT_FAMILY,
        fontSize: size,
        fontWeight: 800,
        color,
        opacity,
        transform: `translateY(${y}px)`,
        borderLeft: `12px solid ${COLORS.navy}`,
        paddingLeft: 24,
        lineHeight: 1.2,
        zIndex: 20,
      }}
    >
      {text}
    </div>
  );
};
