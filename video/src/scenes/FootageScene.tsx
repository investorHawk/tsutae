import {
  AbsoluteFill,
  Sequence,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { FootageSlot } from "../components/FootageSlot";
import { FOOTAGE } from "../footage";
import { calloutAt } from "../lib/callouts";
import { footageSegments } from "../lib/timeline";
import { COLORS, FONT_FAMILY, SUBTITLE_TOP } from "../theme";
import type { SceneComponentProps } from "./types";

/** 区間の頭と尾をそれぞれ丸める（秒が小数でも区間の間に隙間・重なりを作らない） */
const frameRange = (fromSeconds: number, seconds: number, fps: number) => {
  const from = Math.round(fromSeconds * fps);
  const to = Math.round((fromSeconds + seconds) * fps);
  return { from, durationInFrames: Math.max(1, to - from) };
};

/** 早送りしている間だけ左上に出す印（実際の速さを偽らないため） */
const SpeedBadgeView: React.FC<{ rate: number }> = ({ rate }) => (
  <div
    style={{
      position: "absolute",
      top: 36,
      left: 40,
      padding: "10px 24px",
      borderRadius: 999,
      background: "rgba(26, 26, 26, 0.82)",
      color: COLORS.white,
      fontFamily: FONT_FAMILY,
      fontSize: 40,
      fontWeight: 800,
      zIndex: 80,
    }}
  >
    早送り ×{rate}
  </div>
);

/** 画面の下に小さく出す注記（出典など。字幕の帯の上） */
const Footnote: React.FC<{ text: string }> = ({ text }) => (
  <div
    style={{
      position: "absolute",
      left: 0,
      right: 0,
      top: SUBTITLE_TOP - 64,
      display: "flex",
      justifyContent: "center",
      zIndex: 80,
    }}
  >
    <div
      lang="ja"
      style={{
        padding: "6px 22px",
        borderRadius: 10,
        background: "rgba(255, 255, 255, 0.9)",
        color: COLORS.ink,
        fontFamily: FONT_FAMILY,
        fontSize: 28,
        fontWeight: 600,
      }}
    >
      {text}
    </div>
  </div>
);

/** 録画の場面。複数の録画は props.split の秒配分で順に出す。札は lib/callouts.ts の割り当てで出す */
export const FootageScene: React.FC<SceneComponentProps> = ({ scene }) => {
  const { fps } = useVideoConfig();
  const frame = useCurrentFrame();
  const segments = footageSegments(scene);
  const callouts = scene.props?.callouts ?? [];
  const seconds = frame / fps;
  const badge = (scene.props?.speedBadges ?? []).find(
    (b) => seconds >= b.from && seconds < b.to,
  );
  const footnote = scene.props?.footnote;
  return (
    <AbsoluteFill style={{ background: COLORS.paper }}>
      {segments.map((seg, i) => {
        const range = frameRange(seg.fromSeconds, seg.seconds, fps);
        const progress = (frame - range.from) / range.durationInFrames;
        return (
          <Sequence key={`${seg.id}-${i}`} {...range} layout="none">
            <FootageSlot
              id={seg.id}
              seconds={seg.seconds}
              label={
                segments.length === 1 && scene.title
                  ? scene.title
                  : FOOTAGE[seg.id].scene
              }
              callout={calloutAt(callouts, i, segments.length, progress)}
              calloutTop={scene.props?.calloutTop}
            />
          </Sequence>
        );
      })}
      {badge ? <SpeedBadgeView rate={badge.rate} /> : null}
      {footnote ? <Footnote text={footnote} /> : null}
    </AbsoluteFill>
  );
};
