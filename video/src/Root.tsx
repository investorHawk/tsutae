import { Composition } from "remotion";
import { Demo } from "./Demo";
import { totalFrames } from "./lib/timeline";
import { STORYBOARDS } from "./storyboards";
import { demoBVoice } from "./storyboards/bVoice";
import { FPS, HEIGHT, WIDTH } from "./theme";

/**
 * 3 案（DemoA / DemoB / DemoC）。長さは構成データの秒数の合計から決める（150 秒 = 4500 フレーム）。
 * DemoBVoice は案 B に場面ごとの声をつけた版で、長さは声から決めた場面の秒の合計
 * （src/voice.generated.json が空なら案 B と同じ 150 秒・音なし）。
 * BGM は sb.bgm が true の DemoBVoice だけ（public/voice/bgm.wav があるとき）。
 */
export const Root: React.FC = () => (
  <>
    {[...STORYBOARDS, demoBVoice].map((sb) => (
      <Composition
        key={sb.compositionId}
        id={sb.compositionId}
        component={Demo}
        durationInFrames={totalFrames(sb.scenes, FPS)}
        fps={FPS}
        width={WIDTH}
        height={HEIGHT}
        defaultProps={{
          variant: sb.variant,
          scenes: sb.scenes,
          bgm: sb.bgm ?? false,
        }}
      />
    ))}
  </>
);
