import { AbsoluteFill, interpolate } from "remotion";
import { COLORS } from "../theme";
import { appear, CLAMP } from "./anim";

interface EndCardProps {
  frame: number;
  /** カードに切り替わる時刻（場面の中のフレーム） */
  at: number;
  /** 最後に出す文（無ければ今までのカードのまま） */
  messages: string[];
  durationInFrames: number;
}

/** 最後の文（2 つ目）を出す時刻（場面の割合）。narration の最後の文の頭に合わせる */
const LAST_MESSAGE_AT = 0.8;

const fadeIn = (frame: number, at: number): number =>
  interpolate(frame, [at + 8, at + 20], [0, 1], CLAMP);

/** 今までのカード: 「つたえ」「Built with Claude Code」「症例は全て合成」（案 A・C） */
const PlainCard: React.FC<{ frame: number; at: number }> = ({ frame, at }) => (
  <AbsoluteFill
    style={{
      justifyContent: "center",
      alignItems: "center",
      paddingBottom: 200,
      opacity: fadeIn(frame, at),
    }}
  >
    <div style={{ fontSize: 200, fontWeight: 900, letterSpacing: 24 }}>
      つたえ
    </div>
    <div
      style={{
        fontSize: 64,
        fontWeight: 800,
        color: COLORS.purple,
        ...appear(frame, at + 22),
      }}
    >
      Built with Claude Code
    </div>
    <div
      style={{
        marginTop: 24,
        fontSize: 44,
        color: COLORS.inkSoft,
        ...appear(frame, at + 32),
      }}
    >
      症例は全て合成（架空）
    </div>
  </AbsoluteFill>
);

/** 文つきのカードの 1 行（style に大きさ・色、start に出る時刻） */
const Line: React.FC<{
  frame: number;
  start: number;
  style: React.CSSProperties;
  children: React.ReactNode;
}> = ({ frame, start, style, children }) => (
  <div style={{ ...style, ...appear(frame, start) }}>{children}</div>
);

/**
 * 文つきのカード（案 B）: 「つたえ」→ 1 つ目の文（大きく）→ Built with Claude Code・症例は全て合成
 * → 最後に 2 つ目の文。全体を縮めて字幕の帯（872px）より上に収める。
 */
const MessageCard: React.FC<
  Omit<EndCardProps, "messages"> & { first: string; rest: string[] }
> = ({ frame, at, durationInFrames, first, rest }) => {
  const lastAt = Math.max(
    at + 60,
    Math.round(durationInFrames * LAST_MESSAGE_AT),
  );
  return (
    <AbsoluteFill
      style={{
        justifyContent: "center",
        alignItems: "center",
        paddingBottom: 200,
        opacity: fadeIn(frame, at),
        lineHeight: 1.25,
      }}
    >
      <div style={{ fontSize: 150, fontWeight: 900, letterSpacing: 20 }}>
        つたえ
      </div>
      <Line frame={frame} start={at + 22} style={FIRST_STYLE}>
        {first}
      </Line>
      <Line frame={frame} start={at + 40} style={BUILT_STYLE}>
        Built with Claude Code
      </Line>
      <Line frame={frame} start={at + 48} style={SYNTHETIC_STYLE}>
        症例は全て合成（架空）
      </Line>
      {rest.map((text, i) => (
        <Line
          key={text}
          frame={frame}
          start={lastAt + i * 12}
          style={LAST_STYLE}
        >
          {text}
        </Line>
      ))}
    </AbsoluteFill>
  );
};

const FIRST_STYLE: React.CSSProperties = {
  marginTop: 28,
  fontSize: 64,
  fontWeight: 900,
  color: COLORS.navy,
};
const BUILT_STYLE: React.CSSProperties = {
  marginTop: 40,
  fontSize: 48,
  fontWeight: 800,
  color: COLORS.purple,
};
const SYNTHETIC_STYLE: React.CSSProperties = {
  marginTop: 12,
  fontSize: 36,
  color: COLORS.inkSoft,
};
const LAST_STYLE: React.CSSProperties = {
  marginTop: 36,
  fontSize: 52,
  fontWeight: 800,
  color: COLORS.ink,
};

/** 最後のカード。messages があれば文つき、無ければ今までのまま */
export const EndCard: React.FC<EndCardProps> = ({
  frame,
  at,
  messages,
  durationInFrames,
}) => {
  const [first, ...rest] = messages;
  if (first === undefined) return <PlainCard frame={frame} at={at} />;
  return (
    <MessageCard
      frame={frame}
      at={at}
      durationInFrames={durationInFrames}
      first={first}
      rest={rest}
    />
  );
};
