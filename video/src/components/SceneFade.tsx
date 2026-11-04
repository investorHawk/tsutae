import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { FADE_FRAMES } from "../theme";

interface SceneFadeProps {
  durationInFrames: number;
  fadeIn: boolean;
  fadeOut: boolean;
  children: React.ReactNode;
}

/** 場面の切り替えの短いフェード */
export const SceneFade: React.FC<SceneFadeProps> = ({
  durationInFrames,
  fadeIn,
  fadeOut,
  children,
}) => {
  const frame = useCurrentFrame();
  const inOpacity = fadeIn
    ? interpolate(frame, [0, FADE_FRAMES], [0, 1], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
      })
    : 1;
  const outOpacity = fadeOut
    ? interpolate(
        frame,
        [durationInFrames - FADE_FRAMES, durationInFrames],
        [1, 0],
        { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
      )
    : 1;
  return (
    <AbsoluteFill style={{ opacity: Math.min(inOpacity, outOpacity) }}>
      {children}
    </AbsoluteFill>
  );
};
