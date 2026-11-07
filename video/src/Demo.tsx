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
import { bgmFile, voiceFiles } from "./footage.generated";
import { bgmVolumeAt } from "./lib/bgm";
import { layoutScenes, type TimedScene } from "./lib/timeline";
import {
  contentFrames,
  voiceKeyOf,
  voiceTracks,
  type VoiceTrack,
} from "./lib/voice";
import { VOICE_CUES } from "./storyboards/bVoiceCues";
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

/** 声が置いてある場面の実測。無ければ undefined（字数の割合で動く） */
const cueOf = (sceneId: string) => {
  const key = voiceKeyOf(sceneId);
  return Object.hasOwn(voiceFiles, key) && Object.hasOwn(VOICE_CUES, key)
    ? VOICE_CUES[key]
    : undefined;
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
        voiceStarts={cueOf(scene.id)?.starts}
        sceneSeconds={scene.seconds}
      />
    </Sequence>
  );
};

/** 場面の声。場面の頭 + 少しから鳴らす。声が場面より少し長くても切らない（durationInFrames を付けない） */
const VoiceAudio: React.FC<{ track: VoiceTrack }> = ({ track }) => (
  <Sequence from={track.from} layout="none" name={`声 ${track.key}`}>
    <Audio src={staticFile(track.src)} />
  </Sequence>
);

/** BGM。両端はフェードし、声がある案では全体を下げる（frame は動画の頭から数える） */
const BgmTrack: React.FC<{ src: string; hasVoice: boolean }> = ({
  src,
  hasVoice,
}) => {
  const { fps, durationInFrames } = useVideoConfig();
  return (
    <Audio
      src={staticFile(src)}
      name="BGM"
      loop
      loopVolumeCurveBehavior="extend"
      volume={(f) => bgmVolumeAt(f, durationInFrames, fps, hasVoice)}
    />
  );
};

/**
 * 構成データ（Scene[]）を累積フレームで並べ、札・字幕・声・BGM を重ねる。
 * 声は public/voice/ に場面 id の頭（b01 など）の名前で置いたものだけを鳴らす（無ければ字幕と BGM だけ）。
 */
export const Demo: React.FC<DemoProps> = ({ variant, scenes, bgm = false }) => {
  const { fps } = useVideoConfig();
  const timed = layoutScenes(scenes, fps);
  const voices = voiceTracks(timed, voiceFiles, fps);
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
                durationInFrames={contentFrames(
                  durationInFrames,
                  cueOf(scene.id)?.seconds,
                  fps,
                )}
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
      {voices.map((track) => (
        <VoiceAudio key={`voice-${track.key}`} track={track} />
      ))}
      {bgm && bgmFile ? (
        <BgmTrack src={bgmFile} hasVoice={voices.length > 0} />
      ) : null}
    </AbsoluteFill>
  );
};
