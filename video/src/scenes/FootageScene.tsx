import { AbsoluteFill, Sequence, useVideoConfig } from "remotion";
import { FootageSlot } from "../components/FootageSlot";
import { FOOTAGE } from "../footage";
import { footageSegments } from "../lib/timeline";
import { COLORS } from "../theme";
import type { SceneComponentProps } from "./types";

/** 録画の場面。複数の録画は props.split の秒配分で順に出す */
export const FootageScene: React.FC<SceneComponentProps> = ({ scene }) => {
  const { fps } = useVideoConfig();
  const segments = footageSegments(scene);
  const callouts = scene.props?.callouts ?? [];
  return (
    <AbsoluteFill style={{ background: COLORS.paper }}>
      {segments.map((seg, i) => (
        <Sequence
          key={`${seg.id}-${i}`}
          from={Math.round(seg.fromSeconds * fps)}
          durationInFrames={Math.round(seg.seconds * fps)}
          layout="none"
        >
          <FootageSlot
            id={seg.id}
            seconds={seg.seconds}
            label={
              segments.length === 1 && scene.title
                ? scene.title
                : FOOTAGE[seg.id].scene
            }
            callout={callouts[i] ?? null}
          />
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};
