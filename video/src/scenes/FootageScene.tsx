import { AbsoluteFill, Sequence, useVideoConfig } from "remotion";
import { FootageSlot } from "../components/FootageSlot";
import { FOOTAGE } from "../footage";
import { footageSegments } from "../lib/timeline";
import { COLORS } from "../theme";
import type { SceneComponentProps } from "./types";

/** 区間の頭と尾をそれぞれ丸める（秒が小数でも区間の間に隙間・重なりを作らない） */
const frameRange = (fromSeconds: number, seconds: number, fps: number) => {
  const from = Math.round(fromSeconds * fps);
  const to = Math.round((fromSeconds + seconds) * fps);
  return { from, durationInFrames: Math.max(1, to - from) };
};

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
          {...frameRange(seg.fromSeconds, seg.seconds, fps)}
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
