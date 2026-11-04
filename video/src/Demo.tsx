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
import { audioFiles, bgmFile } from "./footage.generated";
import { bgmVolumeAt, voiceFrames, voiceRanges } from "./lib/bgm";
import { layoutScenes, type TimedScene } from "./lib/timeline";
import { SCENE_COMPONENTS } from "./scenes";
import { COLORS, FONT_FAMILY } from "./theme";
import type { Scene, SceneVoice, Variant } from "./types";

// Composition の props は Record<string, unknown> を満たす必要があるので type で定義する
export type DemoProps = {
  variant: Variant;
  scenes: Scene[];
  /** BGM を重ねるか（DemoBVoice だけ true。public/voice/bgm.wav が無ければ鳴らさない） */
  bgm?: boolean;
};

/** 場面の声。lead の後に鳴らす（場面の Sequence の中に置く） */
const VoiceAudio: React.FC<{ voice: SceneVoice }> = ({ voice }) => {
  const { fps } = useVideoConfig();
  return (
    <Sequence
      from={voiceFrames(voice, fps).from}
      name={`声 ${voice.file}`}
      layout="none"
    >
      <Audio src={staticFile(voice.file)} />
    </Sequence>
  );
};

/** 字幕。声のある場面は声の区間に塊を配る */
const SubtitleTrack: React.FC<{ timed: TimedScene }> = ({ timed }) => {
  const { fps } = useVideoConfig();
  const { scene, from, durationInFrames } = timed;
  const range = scene.voice ? voiceFrames(scene.voice, fps) : null;
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
        activeFrom={range?.from}
        activeTo={range?.to}
      />
    </Sequence>
  );
};

/** BGM。声の区間は音量を下げ、両端はフェードする（frame は動画の頭から数える） */
const BgmTrack: React.FC<{ src: string; timed: TimedScene[] }> = ({
  src,
  timed,
}) => {
  const { fps, durationInFrames } = useVideoConfig();
  const ranges = voiceRanges(timed, fps);
  return (
    <Audio
      src={staticFile(src)}
      name="BGM"
      loop
      loopVolumeCurveBehavior="extend"
      volume={(f) => bgmVolumeAt(f, ranges, durationInFrames, fps)}
    />
  );
};

/** 構成データ（Scene[]）を累積フレームで並べ、札・字幕・音声を重ねる */
export const Demo: React.FC<DemoProps> = ({ variant, scenes, bgm = false }) => {
  const { fps } = useVideoConfig();
  const timed = layoutScenes(scenes, fps);
  const audioName = `narration-${variant}`;
  // 場面ごとの声がある版では、案ごとの単一の mp3 は重ねない（声が二重になる）
  const hasSceneVoice = scenes.some((s) => s.voice);
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
            {scene.voice ? <VoiceAudio voice={scene.voice} /> : null}
          </Sequence>
        );
      })}
      {timed.map((t) => (
        <SubtitleTrack key={`sub-${t.scene.id}`} timed={t} />
      ))}
      <SyntheticBadge />
      {!hasSceneVoice && audioFiles.includes(audioName) ? (
        <Audio src={staticFile(`audio/${audioName}.mp3`)} />
      ) : null}
      {bgm && bgmFile ? <BgmTrack src={bgmFile} timed={timed} /> : null}
    </AbsoluteFill>
  );
};
