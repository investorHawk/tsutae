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
import { bgmFile } from "./footage.generated";
import { bgmVolumeAt } from "./lib/bgm";
import { layoutScenes, type TimedScene } from "./lib/timeline";
import { SCENE_COMPONENTS } from "./scenes";
import { COLORS, FONT_FAMILY } from "./theme";
import type { Scene, Variant } from "./types";

// Composition の props は Record<string, unknown> を満たす必要があるので type で定義する
export type DemoProps = {
  variant: Variant;
  scenes: Scene[];
  /** BGM を重ねるか（案 B だけ true。public/audio/bgm.wav が無ければ鳴らさない） */
  bgm?: boolean;
};

/** 字幕 */
const SubtitleTrack: React.FC<{ timed: TimedScene }> = ({ timed }) => {
  const { scene, from, durationInFrames } = timed;
  return (
    <Sequence
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
  );
};

/** BGM。両端はフェードする（frame は動画の頭から数える） */
const BgmTrack: React.FC<{ src: string }> = ({ src }) => {
  const { fps, durationInFrames } = useVideoConfig();
  return (
    <Audio
      src={staticFile(src)}
      name="BGM"
      loop
      loopVolumeCurveBehavior="extend"
      volume={(f) => bgmVolumeAt(f, durationInFrames, fps)}
    />
  );
};

/** 構成データ（Scene[]）を累積フレームで並べ、札・字幕・BGM を重ねる */
export const Demo: React.FC<DemoProps> = ({ variant, scenes, bgm = false }) => {
  const { fps } = useVideoConfig();
  const timed = layoutScenes(scenes, fps);
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
      {timed.map((t) => (
        <SubtitleTrack key={`sub-${t.scene.id}`} timed={t} />
      ))}
      <SyntheticBadge />
      {bgm && bgmFile ? <BgmTrack src={bgmFile} /> : null}
    </AbsoluteFill>
  );
};
