import { AbsoluteFill, Img, staticFile, useCurrentFrame } from "remotion";
import { slideStates } from "../lib/slides";
import { COLORS } from "../theme";

interface ScreenSlidesProps {
  /** public からのパス（screens/F1-1.png）。この順に出す */
  files: string[];
  /** この区間のフレーム数（枚数で均等に割る） */
  totalFrames: number;
  /** 全面に敷く（camera）。既定は枠に収める */
  cover?: boolean;
}

/** 撮影した静止画を順に出す。短いクロスフェードと、ゆっくりしたズームだけの控えめな動き */
export const ScreenSlides: React.FC<ScreenSlidesProps> = ({
  files,
  totalFrames,
  cover = false,
}) => {
  const frame = useCurrentFrame();
  const states = slideStates(files.length, totalFrames, frame);
  return (
    <AbsoluteFill style={{ background: COLORS.white, overflow: "hidden" }}>
      {files.map((file, i) => (
        <Img
          key={file}
          src={staticFile(file)}
          style={{
            position: "absolute",
            inset: 0,
            width: "100%",
            height: "100%",
            objectFit: cover ? "cover" : "contain",
            opacity: states[i]?.opacity ?? 0,
            transform: `scale(${states[i]?.scale ?? 1})`,
            transformOrigin: "50% 40%",
          }}
        />
      ))}
    </AbsoluteFill>
  );
};
