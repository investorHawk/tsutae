// pipeline の図の部品（ノード・矢印・SDK の枠・注記・Hook の帯・背景の録画）
import {
  AbsoluteFill,
  Img,
  Loop,
  OffthreadVideo,
  staticFile,
  useVideoConfig,
} from "remotion";
import { FOOTAGE } from "../footage";
import { footageFiles } from "../footage.generated";
import { COLORS, FONT_FAMILY } from "../theme";
import type { FootageId } from "../types";
import { appear } from "./anim";
import { SDK_FRAME, type PipeEdge, type PipeNode } from "./pipelineLayout";
import { REPORT_IMAGE } from "./reportRegions";

const TONE: Record<
  PipeNode["tone"],
  { bg: string; fg: string; border: string }
> = {
  mask: { bg: COLORS.white, fg: COLORS.navy, border: COLORS.navy },
  muted: { bg: COLORS.paperDeep, fg: COLORS.inkSoft, border: COLORS.line },
  hook: { bg: COLORS.white, fg: COLORS.reject, border: COLORS.reject },
  agent: { bg: COLORS.purple, fg: COLORS.white, border: COLORS.purple },
  role: { bg: COLORS.white, fg: COLORS.purple, border: COLORS.purple },
  tool: { bg: COLORS.white, fg: COLORS.ink, border: COLORS.ink },
  paper: { bg: COLORS.white, fg: COLORS.ink, border: COLORS.line },
};

/** 箱の見出しの文字の大きさ（箱の幅に 1 行で収まる大きさ） */
const LABEL_SIZE: Record<PipeNode["tone"], number> = {
  mask: 44,
  muted: 36,
  hook: 52,
  agent: 44,
  role: 44,
  tool: 44,
  paper: 44,
};

const EDGE_COLOR: Record<NonNullable<PipeEdge["tone"]>, string> = {
  normal: COLORS.ink,
  reject: COLORS.reject,
  muted: COLORS.line,
};

/** ノードの箱の見た目。Hook は lit（0〜1）で赤く点灯する */
const nodeStyle = (node: PipeNode, lit: number): React.CSSProperties => {
  const tone = TONE[node.tone];
  const isHook = node.tone === "hook";
  return {
    position: "absolute",
    left: node.x,
    top: node.y,
    width: node.w,
    height: node.h,
    boxSizing: "border-box",
    borderRadius: isHook ? 60 : 20,
    border: `5px ${node.tone === "muted" ? "dashed" : "solid"} ${tone.border}`,
    background: isHook && lit > 0 ? `rgba(179, 38, 30, ${lit})` : tone.bg,
    color: isHook && lit > 0.5 ? COLORS.white : tone.fg,
    display: "flex",
    flexDirection: "column",
    justifyContent: "center",
    alignItems: "center",
    textAlign: "center",
    boxShadow:
      isHook && lit > 0 ? `0 0 ${30 * lit}px rgba(179,38,30,0.7)` : "none",
  };
};

export const NodeBox: React.FC<{
  node: PipeNode;
  frame: number;
  start: number;
  lit: number;
}> = ({ node, frame, start, lit }) => (
  <div style={{ ...nodeStyle(node, lit), ...appear(frame, start, 10, 16) }}>
    {node.tone === "paper" ? (
      <Img
        src={staticFile(REPORT_IMAGE)}
        style={{ width: node.w - 14, height: node.h - 14 }}
      />
    ) : (
      <>
        <div
          style={{
            fontSize: LABEL_SIZE[node.tone],
            fontWeight: 900,
            lineHeight: 1.15,
          }}
        >
          {node.label}
        </div>
        {node.sub ? (
          <div
            style={{
              fontSize: node.tone === "hook" ? 24 : 26,
              fontWeight: 600,
              marginTop: 4,
              whiteSpace: "nowrap",
            }}
          >
            {node.sub}
          </div>
        ) : null}
      </>
    )}
  </div>
);

export const EdgeLine: React.FC<{ edge: PipeEdge; t: number }> = ({
  edge,
  t,
}) => {
  const tone = edge.tone ?? "normal";
  const color = EDGE_COLOR[tone];
  const d = edge.points
    .map(([x, y], i) => `${i === 0 ? "M" : "L"}${x},${y}`)
    .join(" ");
  const [lx, ly] = edge.labelAt ?? edge.points[0];
  return (
    <g opacity={t}>
      <path
        d={d}
        fill="none"
        stroke={color}
        strokeWidth={6}
        markerEnd={`url(#arrow-${tone})`}
        strokeDasharray={tone === "reject" ? "16 10" : undefined}
      />
      {edge.label ? (
        <text
          x={lx}
          y={ly}
          fill={color}
          fontSize={32}
          fontWeight={800}
          fontFamily={FONT_FAMILY}
          textAnchor="middle"
        >
          {edge.label}
        </text>
      ) : null}
    </g>
  );
};

export const ArrowDefs: React.FC = () => (
  <defs>
    {(["normal", "reject", "muted"] as const).map((tone) => (
      <marker
        key={tone}
        id={`arrow-${tone}`}
        markerWidth={5}
        markerHeight={5}
        refX={4}
        refY={2.5}
        orient="auto"
      >
        <path d="M0,0 L5,2.5 L0,5 z" fill={EDGE_COLOR[tone]} />
      </marker>
    ))}
  </defs>
);

/** Claude Agent SDK の点線の枠 */
export const SdkFrame: React.FC<{ opacity: number }> = ({ opacity }) => (
  <div
    style={{
      position: "absolute",
      left: SDK_FRAME.x,
      top: SDK_FRAME.y,
      width: SDK_FRAME.w,
      height: SDK_FRAME.h,
      border: `4px dashed ${COLORS.purple}`,
      borderRadius: 28,
      opacity,
    }}
  >
    <div
      style={{
        position: "absolute",
        top: -22,
        right: 30,
        padding: "0 14px",
        background: COLORS.paper,
        color: COLORS.purple,
        fontSize: 32,
        fontWeight: 800,
      }}
    >
      Claude Agent SDK
    </div>
  </div>
);

/** 背景に薄く敷く録画（manifest にあるときだけ。最低秒の長さでループ） */
export const BackgroundFootage: React.FC<{ id?: FootageId }> = ({ id }) => {
  const { fps } = useVideoConfig();
  const src = id ? footageFiles[id] : undefined;
  if (!id || !src) return null;
  return (
    <AbsoluteFill style={{ opacity: 0.12 }}>
      <Loop durationInFrames={FOOTAGE[id].minSeconds * fps}>
        <OffthreadVideo
          src={staticFile(src)}
          muted
          style={{ width: "100%", height: "100%", objectFit: "cover" }}
        />
      </Loop>
    </AbsoluteFill>
  );
};

export const NoteChip: React.FC<{
  text: string;
  top: number;
  style: React.CSSProperties;
}> = ({ text, top, style }) => (
  <div
    style={{
      position: "absolute",
      left: 960,
      top,
      padding: "10px 26px",
      borderRadius: 16,
      background: COLORS.white,
      border: `4px solid ${COLORS.purple}`,
      color: COLORS.purple,
      fontSize: 44,
      fontWeight: 800,
      ...style,
    }}
  >
    {text}
  </div>
);

/** いま点灯している Hook の説明（案 C） */
export const HookBanner: React.FC<{
  text: string;
  style: React.CSSProperties;
}> = ({ text, style }) => (
  <div
    style={{
      position: "absolute",
      left: 420,
      right: 420,
      top: 785,
      textAlign: "center",
      padding: "10px 30px",
      borderRadius: 18,
      background: COLORS.reject,
      color: COLORS.white,
      fontSize: 48,
      fontWeight: 900,
      ...style,
    }}
  >
    {text}
  </div>
);
