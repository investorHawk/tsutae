import {
  AbsoluteFill,
  Audio,
  Sequence,
  staticFile,
  useVideoConfig,
} from "remotion";
import { SceneFade } from "./components/SceneFade";
import { Subtitle } from "./components/Subtitle";
import { SyntheticBadge } from "./components/SyntheticBadge";
import { audioFiles } from "./footage.generated";
import { layoutScenes } from "./lib/timeline";
import { SCENE_COMPONENTS } from "./scenes";
import { COLORS, FONT_FAMILY } from "./theme";
import type { Scene, Variant } from "./types";

// Composition の props は Record<string, unknown> を満たす必要があるので type で定義する
export type DemoProps = {
  variant: Variant;
  scenes: Scene[];
};

/** 構成データ（Scene[]）を累積フレームで並べ、札・字幕・音声を重ねる */
export const Demo: React.FC<DemoProps> = ({ variant, scenes }) => {
  const { fps } = useVideoConfig();
  const timed = layoutScenes(scenes, fps);
  const audioName = `narration-${variant}`;
  return (
    <AbsoluteFill style={{ background: COLORS.paper, fontFamily: FONT_FAMILY }}>
      {timed.map(({ scene, index, from, durationInFrames }) => {
        const Component = SCENE_COMPONENTS[scene.kind];
        return (
          <Sequence
            key={scene.id}
            name={`${scene.id} (${scene.kind})`}
            from={from}
            durationInFrames={durationInFrames}
          >
            <SceneFade
              durationInFrames={durationInFrames}
              fadeIn={index > 0}
              fadeOut={index < timed.length - 1}
            >
              <Component
                scene={scene}
                durationInFrames={durationInFrames}
                variant={variant}
              />
            </SceneFade>
          </Sequence>
        );
      })}
      {timed.map(({ scene, from, durationInFrames }) => (
        <Sequence
          key={`sub-${scene.id}`}
          name={`字幕 ${scene.id}`}
          from={from}
          durationInFrames={durationInFrames}
          layout="none"
        >
          <Subtitle
            text={scene.caption ?? scene.narration}
            durationInFrames={durationInFrames}
          />
        </Sequence>
      ))}
      <SyntheticBadge />
      {audioFiles.includes(audioName) ? (
        <Audio src={staticFile(`audio/${audioName}.mp3`)} />
      ) : null}
    </AbsoluteFill>
  );
};
