import { AbsoluteFill, useCurrentFrame } from "remotion";
import { Caption } from "../components/Caption";
import { fitCamera, ReportImage } from "../components/ReportImage";
import { COLORS, FONT_FAMILY } from "../theme";
import { appear } from "./anim";
import { REPORT_SIZE } from "./reportRegions";
import type { SceneComponentProps } from "./types";

/** 画面の札（構成データに持たせるほど変わらない語） */
const LABEL = { chart: "電子カルテ", paper: "紙", turn: "あえて今" } as const;

/** 出現の時刻（場面の割合）。字幕の塊の頭（2 文目 ≈ 46%、3 文目 ≈ 72%）に合わせる */
const AT = {
  barriers: 0.06,
  barriersEnd: 0.4,
  turn: 0.45,
  paper: 0.5,
  gains: 0.6,
};

/** 左右の列（字幕の帯 872px より上に収める） */
const TOP = 190;
const LEFT_COL = { left: 80, width: 720 };
const RIGHT_COL = { left: 1110, width: 740 };
/** 見本の A4 を小さく（列の見出しの下に置き、その下に得られることを並べる） */
const PAPER = {
  width: 230,
  height: Math.round((230 * REPORT_SIZE.height) / REPORT_SIZE.width),
};
const WHOLE_PAGE = fitCamera(
  { x: 0, y: 0, w: REPORT_SIZE.width, h: REPORT_SIZE.height },
  PAPER,
  1,
);

const ColumnHead: React.FC<{ text: string; color: string; style: object }> = ({
  text,
  color,
  style,
}) => (
  <div
    style={{
      fontSize: 64,
      fontWeight: 900,
      color,
      borderBottom: `6px solid ${color}`,
      paddingBottom: 8,
      marginBottom: 24,
      ...style,
    }}
  >
    {text}
  </div>
);

const Item: React.FC<{
  text: string;
  mark: string;
  color: string;
  style: object;
}> = ({ text, mark, color, style }) => (
  <div
    style={{
      display: "flex",
      alignItems: "center",
      gap: 18,
      fontSize: 40,
      fontWeight: 700,
      lineHeight: 1.25,
      padding: "10px 0",
      ...style,
    }}
  >
    <span
      style={{
        width: 56,
        height: 56,
        flexShrink: 0,
        borderRadius: 12,
        background: color,
        color: COLORS.white,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontSize: 38,
        fontWeight: 900,
      }}
    >
      {mark}
    </span>
    {text}
  </div>
);

/** 左: 電子カルテと、変えるときの壁（順に出る） */
const Barriers: React.FC<{
  items: string[];
  frame: number;
  duration: number;
}> = ({ items, frame, duration }) => {
  const step =
    ((AT.barriersEnd - AT.barriers) * duration) / Math.max(1, items.length);
  return (
    <div style={{ position: "absolute", top: TOP, ...LEFT_COL }}>
      <ColumnHead
        text={LABEL.chart}
        color={COLORS.reject}
        style={appear(frame, 4)}
      />
      {items.map((b, i) => (
        <Item
          key={b}
          text={b}
          mark="×"
          color={COLORS.reject}
          style={appear(frame, Math.round(AT.barriers * duration + i * step))}
        />
      ))}
    </div>
  );
};

/** 中央: 矢印と「あえて今」 */
const Turn: React.FC<{ frame: number; duration: number }> = ({
  frame,
  duration,
}) => (
  <div
    style={{
      position: "absolute",
      top: 360,
      left: LEFT_COL.left + LEFT_COL.width,
      width: RIGHT_COL.left - LEFT_COL.left - LEFT_COL.width,
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      color: COLORS.navy,
      ...appear(frame, Math.round(AT.turn * duration), 12, 0),
    }}
  >
    <div style={{ fontSize: 48, fontWeight: 900, whiteSpace: "nowrap" }}>
      {LABEL.turn}
    </div>
    <div style={{ fontSize: 140, fontWeight: 900, lineHeight: 1 }}>→</div>
  </div>
);

/** 右: A4 の紙（見本を小さく）と、その下に紙にして得られること */
const Paper: React.FC<{ items: string[]; frame: number; duration: number }> = ({
  items,
  frame,
  duration,
}) => {
  const at = Math.round(AT.paper * duration);
  const step = (duration * (0.85 - AT.gains)) / Math.max(1, items.length);
  return (
    <div style={{ position: "absolute", top: TOP, ...RIGHT_COL }}>
      <ColumnHead
        text={LABEL.paper}
        color={COLORS.navy}
        style={appear(frame, at)}
      />
      <div
        style={{
          position: "relative",
          margin: "0 auto 16px",
          overflow: "hidden",
          ...PAPER,
          ...appear(frame, at + 4),
        }}
      >
        <ReportImage viewport={PAPER} camera={WHOLE_PAGE} />
      </div>
      {items.map((g, i) => (
        <Item
          key={g}
          text={g}
          mark="✓"
          color={COLORS.navy}
          style={appear(frame, Math.round(AT.gains * duration + i * step))}
        />
      ))}
    </div>
  );
};

/** なぜ紙か: 電子カルテの壁 → 「あえて今」→ A4 の紙と得られること */
export const WhyPaperScene: React.FC<SceneComponentProps> = ({
  scene,
  durationInFrames,
}) => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill
      style={{
        background: COLORS.paper,
        fontFamily: FONT_FAMILY,
        color: COLORS.ink,
      }}
    >
      {scene.title ? <Caption text={scene.title} /> : null}
      <Barriers
        items={scene.props?.barriers ?? []}
        frame={frame}
        duration={durationInFrames}
      />
      <Turn frame={frame} duration={durationInFrames} />
      <Paper
        items={scene.props?.gains ?? []}
        frame={frame}
        duration={durationInFrames}
      />
    </AbsoluteFill>
  );
};
