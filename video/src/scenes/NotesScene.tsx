import { AbsoluteFill, useCurrentFrame } from "remotion";
import { Caption } from "../components/Caption";
import { COLORS, FONT_FAMILY } from "../theme";
import { appear, ramp } from "./anim";
import type { SceneComponentProps } from "./types";

/**
 * 札の出る時刻（場面の割合）。声の位置（文字数の割合）に合わせる（テストで検査）:
 * 「書式は」≈ 23%、「患者さんは」≈ 32.5%、「医師は」≈ 47%、「そこで」≈ 66.3%
 */
export const NOTES_AT = {
  label: 0.229,
  burdens: [0.325, 0.47],
  answer: 0.663,
} as const;

/** 1 冊の大きさ（中の線はこの座標で描く）と並び */
const NOTE = { width: 320, height: 420 } as const;
const NOTE_GAP = 70;
const NOTE_TOP = 150;
/** 表紙の綴じの幅と、中の線の余白 */
const SPINE = 26;
const PAD = 26;
const LINE_WIDTH = 4;
/** 書式の違いが一目で分かるよう、少しずつ傾けて置く */
const NOTE_TILTS = [-2, 1.2, -1] as const;

const INNER = {
  left: SPINE + PAD,
  right: NOTE.width - PAD,
  top: PAD + 8,
  bottom: NOTE.height - PAD,
} as const;

/** 表の形: 見出しの帯と、格子の線 */
const TablePage: React.FC = () => {
  const { left, right, top, bottom } = INNER;
  const width = right - left;
  const height = bottom - top;
  const rows = [0.14, 0.31, 0.48, 0.65, 0.82].map((r) => top + height * r);
  const cols = [0.3, 0.65].map((r) => left + width * r);
  return (
    <g stroke={COLORS.inkSoft} strokeWidth={LINE_WIDTH} fill="none">
      <rect
        x={left}
        y={top}
        width={width}
        height={rows[0] - top}
        fill={COLORS.line}
      />
      <rect x={left} y={top} width={width} height={height} />
      {rows.map((y) => (
        <line key={y} x1={left} x2={right} y1={y} y2={y} />
      ))}
      {cols.map((x) => (
        <line key={x} x1={x} x2={x} y1={top} y2={bottom} />
      ))}
    </g>
  );
};

/** チェック欄の形: 四角の欄と短い線の行 */
const CheckPage: React.FC = () => {
  const { left, right, top, bottom } = INNER;
  const box = 34;
  const step = (bottom - top) / 6;
  const rows = [0, 1, 2, 3, 4, 5].map((i) => top + i * step);
  return (
    <g stroke={COLORS.inkSoft} strokeWidth={LINE_WIDTH} fill="none">
      {rows.map((y, i) => (
        <g key={y}>
          <rect x={left} y={y + 6} width={box} height={box} rx={4} />
          <line
            x1={left + box + 20}
            x2={i % 2 === 0 ? right : right - 50}
            y1={y + 6 + box / 2}
            y2={y + 6 + box / 2}
            stroke={COLORS.line}
            strokeWidth={LINE_WIDTH + 4}
          />
        </g>
      ))}
    </g>
  );
};

/** 罫線だけの形 */
const RuledPage: React.FC = () => {
  const { left, right, top, bottom } = INNER;
  const step = (bottom - top) / 9;
  const rows = Array.from({ length: 9 }, (_, i) => top + (i + 1) * step);
  return (
    <g stroke={COLORS.line} strokeWidth={LINE_WIDTH}>
      {rows.map((y) => (
        <line key={y} x1={left} x2={right} y1={y} y2={y} />
      ))}
    </g>
  );
};

/** 書式の違う 3 冊（実在の出版物を写さない、抽象的な線と枠だけ） */
const NOTE_PAGES = [TablePage, CheckPage, RuledPage] as const;

const Notebook: React.FC<{
  page: React.FC;
  tilt: number;
  style: object;
}> = ({ page: Page, tilt, style }) => (
  <div style={style}>
    <svg
      width={NOTE.width}
      height={NOTE.height}
      style={{
        display: "block",
        transform: `rotate(${tilt}deg)`,
        filter: "drop-shadow(0 10px 14px rgba(0,0,0,0.16))",
      }}
    >
      <rect
        x={2}
        y={2}
        width={NOTE.width - 4}
        height={NOTE.height - 4}
        rx={10}
        fill={COLORS.white}
        stroke={COLORS.inkSoft}
        strokeWidth={LINE_WIDTH}
      />
      <rect
        x={2}
        y={2}
        width={SPINE}
        height={NOTE.height - 4}
        rx={6}
        fill={COLORS.inkSoft}
      />
      <Page />
    </svg>
  </div>
);

const Notebooks: React.FC<{ frame: number }> = ({ frame }) => {
  const total = NOTE_PAGES.length * NOTE.width + 2 * NOTE_GAP;
  return (
    <div
      style={{
        position: "absolute",
        top: NOTE_TOP,
        left: (1920 - total) / 2,
        display: "flex",
        gap: NOTE_GAP,
      }}
    >
      {NOTE_PAGES.map((page, i) => (
        <Notebook
          key={i}
          page={page}
          tilt={NOTE_TILTS[i]}
          style={appear(frame, 8 + i * 12)}
        />
      ))}
    </div>
  );
};

const CHIP_STYLE: React.CSSProperties = {
  padding: "14px 36px",
  borderRadius: 20,
  border: `5px solid ${COLORS.reject}`,
  background: COLORS.white,
  color: COLORS.reject,
  fontSize: 46,
  fontWeight: 800,
  whiteSpace: "nowrap",
  lineHeight: 1.3,
};

/** 札の行（中央に並べる）。字幕の帯（872px）より上に収める */
const ChipRow: React.FC<{ top: number; children: React.ReactNode }> = ({
  top,
  children,
}) => (
  <div
    style={{
      position: "absolute",
      top,
      left: 0,
      right: 0,
      display: "flex",
      justifyContent: "center",
      gap: 44,
    }}
  >
    {children}
  </div>
);

/** 専門用語の説明。見出しと右上の札の間、ノートの上に収める */
const Definition: React.FC<{ lines: string[]; frame: number }> = ({
  lines,
  frame,
}) => (
  <div
    lang="ja"
    style={{
      position: "absolute",
      top: 18,
      left: 780,
      padding: "8px 24px",
      borderRadius: 14,
      border: `4px solid ${COLORS.navy}`,
      background: COLORS.white,
      color: COLORS.navy,
      fontSize: 38,
      fontWeight: 800,
      lineHeight: 1.3,
      whiteSpace: "pre-line",
      ...appear(frame, 6),
    }}
  >
    {lines.join("\n")}
  </div>
);

/** 3 段階目: 使いやすいアプリへ、と「つたえ」を紺で強調する */
const Answer: React.FC<{
  answer: string;
  brand: string;
  frame: number;
  at: number;
}> = ({ answer, brand, frame, at }) => (
  <AbsoluteFill
    style={{
      alignItems: "center",
      justifyContent: "center",
      paddingBottom: 1080 - 872,
      color: COLORS.navy,
    }}
  >
    <div
      lang="ja"
      style={{
        fontSize: 76,
        fontWeight: 900,
        whiteSpace: "nowrap",
        ...appear(frame, at + 6),
      }}
    >
      {answer}
    </div>
    <div
      style={{
        fontSize: 200,
        fontWeight: 900,
        lineHeight: 1.3,
        ...appear(frame, at + 16),
      }}
    >
      {brand}
    </div>
  </AbsoluteFill>
);

/** レジメン別のノートの課題: 書式の違う 3 冊 → 患者と医師の負担 → 使いやすいアプリへ（つたえ） */
export const NotesScene: React.FC<SceneComponentProps> = ({
  scene,
  durationInFrames,
}) => {
  const frame = useCurrentFrame();
  const {
    definition = [],
    formatLabel,
    burdens = [],
    answer,
    brand,
  } = scene.props ?? {};
  const at = (ratio: number) => Math.round(durationInFrames * ratio);
  const answerAt = at(NOTES_AT.answer);
  return (
    <AbsoluteFill
      style={{
        background: COLORS.paper,
        fontFamily: FONT_FAMILY,
        color: COLORS.ink,
      }}
    >
      <AbsoluteFill style={{ opacity: 1 - ramp(frame, answerAt, 10) }}>
        {scene.title ? <Caption text={scene.title} /> : null}
        {definition.length > 0 ? (
          <Definition lines={definition} frame={frame} />
        ) : null}
        <Notebooks frame={frame} />
        <ChipRow top={NOTE_TOP + NOTE.height + 22}>
          <div style={{ ...CHIP_STYLE, ...appear(frame, at(NOTES_AT.label)) }}>
            {formatLabel}
          </div>
        </ChipRow>
        <ChipRow top={NOTE_TOP + NOTE.height + 136}>
          {burdens.map((b, i) => (
            <div
              key={b}
              style={{
                ...CHIP_STYLE,
                ...appear(frame, at(NOTES_AT.burdens[i] ?? NOTES_AT.answer)),
              }}
            >
              {b}
            </div>
          ))}
        </ChipRow>
      </AbsoluteFill>
      <Answer
        answer={answer ?? ""}
        brand={brand ?? ""}
        frame={frame}
        at={answerAt}
      />
    </AbsoluteFill>
  );
};
