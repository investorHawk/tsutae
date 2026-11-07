import { Composition } from "remotion";
import { Demo } from "./Demo";
import { totalFrames } from "./lib/timeline";
import { STORYBOARDS } from "./storyboards";
import { FPS, HEIGHT, WIDTH } from "./theme";

/**
 * 3 案（DemoA / DemoB / DemoC）。長さは構成データの秒数の合計から決める
 * （案 A・C は 150 秒 = 4500 フレーム、案 B は 175 秒 = 5250 フレーム）。
 * BGM は sb.bgm が true の案 B だけ（public/audio/bgm.wav があるとき）。
 * 声は public/voice/ に置いた案 B の場面の分だけ鳴る（Demo.tsx）。
 */
export const Root: React.FC = () => (
  <>
    {STORYBOARDS.map((sb) => (
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
