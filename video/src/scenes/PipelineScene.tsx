import { AbsoluteFill, useCurrentFrame } from "remotion";
import { Caption } from "../components/Caption";
import { COLORS, FONT_FAMILY } from "../theme";
import type { HookId } from "../types";
import { appear, ramp } from "./anim";
import { BUILD_ORDER, EDGES, HOOK_TEXT, NODES } from "./pipelineLayout";
import {
  ArrowDefs,
  BackgroundFootage,
  EdgeLine,
  HookBanner,
  NodeBox,
  NoteChip,
  SdkFrame,
} from "./PipelineParts";
import type { SceneComponentProps } from "./types";

/** 各ノードの出る時刻と、Hook の点灯の強さを決める */
const useSchedule = (durationInFrames: number, hooks: HookId[]) => {
  const frame = useCurrentFrame();
  const sequential = hooks.length > 0;
  const buildEnd = durationInFrames * (sequential ? 0.42 : 0.8);
  const order = BUILD_ORDER.filter((id) =>
    id === "H3" || id === "H4" ? hooks.includes(id) : true,
  );
  const startOf = (id: string) =>
    Math.round(
      8 +
        (order.indexOf(id as (typeof order)[number]) / order.length) * buildEnd,
    );
  const hookSlot = (durationInFrames * 0.55) / Math.max(1, hooks.length);
  const hookStart = (h: HookId) =>
    durationInFrames * 0.44 + hooks.indexOf(h) * hookSlot;
  const litOf = (h: HookId): number => {
    if (!sequential) return ramp(frame, startOf(h) + 6, 10);
    const s = hookStart(h);
    const on = ramp(frame, s, 8);
    const after = ramp(frame, s + hookSlot, 8);
    return on * (1 - 0.6 * after);
  };
  const current = sequential
    ? hooks.find(
        (h) => frame >= hookStart(h) && frame < hookStart(h) + hookSlot,
      )
    : undefined;
  return { frame, startOf, litOf, current, hookStartOf: hookStart };
};

/** README の図を簡略化: 伏せ字 → H1 → 主エージェント → 3 役 → emit → H2 → A4。Hook は赤で点灯 */
export const PipelineScene: React.FC<SceneComponentProps> = ({
  scene,
  durationInFrames,
}) => {
  const hooks = scene.props?.hooks ?? [];
  const { frame, startOf, litOf, current, hookStartOf } = useSchedule(
    durationInFrames,
    hooks,
  );
  const nodes = NODES.filter(
    (n) => !n.onlyWithHooks || (n.hook && hooks.includes(n.hook)),
  );
  const noteStyle = appear(frame, Math.round(durationInFrames * 0.78));
  return (
    <AbsoluteFill style={{ background: COLORS.paper, fontFamily: FONT_FAMILY }}>
      <BackgroundFootage id={scene.props?.backgroundFootage} />
      {scene.title ? <Caption text={scene.title} /> : null}
      <SdkFrame opacity={ramp(frame, startOf("main"), 10) * 0.8} />
      <svg
        width={1920}
        height={1080}
        style={{ position: "absolute", inset: 0 }}
      >
        <ArrowDefs />
        {EDGES.map((e) => (
          <EdgeLine
            key={`${e.from}-${e.to}`}
            edge={e}
            t={ramp(frame, startOf(e.tone === "reject" ? "reject" : e.to), 10)}
          />
        ))}
      </svg>
      {nodes.map((n) => (
        <NodeBox
          key={n.id}
          node={n}
          frame={frame}
          start={startOf(n.id)}
          lit={n.hook ? litOf(n.hook) : 0}
        />
      ))}
      {(scene.props?.notes ?? []).map((note, i) => (
        <NoteChip key={note} text={note} top={780 - i * 80} style={noteStyle} />
      ))}
      {current ? (
        <HookBanner
          text={HOOK_TEXT[current]}
          style={appear(frame, Math.round(hookStartOf(current)), 8, 12)}
        />
      ) : null}
    </AbsoluteFill>
  );
};
