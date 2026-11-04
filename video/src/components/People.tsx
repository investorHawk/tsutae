import { COLORS, FONT_FAMILY } from "../theme";

interface PersonProps {
  who: "doctor" | "patient";
  x: number;
  y: number;
  scale?: number;
}

/** 医師・患者の簡単な図形（頭の円＋胴の角丸） */
export const Person: React.FC<PersonProps> = ({ who, x, y, scale = 1 }) => {
  const isDoctor = who === "doctor";
  const body = isDoctor ? COLORS.white : COLORS.purple;
  return (
    <div
      style={{
        position: "absolute",
        left: x,
        top: y,
        width: 220 * scale,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        fontFamily: FONT_FAMILY,
      }}
    >
      <div
        style={{
          width: 110 * scale,
          height: 110 * scale,
          borderRadius: "50%",
          background: "#e8c9a8",
          border: `5px solid ${COLORS.ink}`,
        }}
      />
      <div
        style={{
          marginTop: 10 * scale,
          width: 200 * scale,
          height: 190 * scale,
          borderRadius: `${90 * scale}px ${90 * scale}px 24px 24px`,
          background: body,
          border: `5px solid ${COLORS.ink}`,
          display: "flex",
          justifyContent: "center",
          paddingTop: 30 * scale,
          boxSizing: "border-box",
        }}
      >
        {isDoctor ? (
          <div
            style={{
              width: 18 * scale,
              height: 110 * scale,
              background: COLORS.navy,
              borderRadius: 9,
            }}
          />
        ) : null}
      </div>
      <div style={{ marginTop: 12, fontSize: 40, fontWeight: 700 }}>
        {isDoctor ? "医師" : "患者さん"}
      </div>
    </div>
  );
};

interface SpeechBubbleProps {
  text: string;
  who: "doctor" | "patient";
  opacity?: number;
  offsetY?: number;
  style?: React.CSSProperties;
}

/** 吹き出し（医師は紺、患者は紫の縁） */
export const SpeechBubble: React.FC<SpeechBubbleProps> = ({
  text,
  who,
  opacity = 1,
  offsetY = 0,
  style,
}) => {
  const color = who === "doctor" ? COLORS.navy : COLORS.purple;
  return (
    <div
      style={{
        position: "relative",
        background: COLORS.white,
        border: `5px solid ${color}`,
        borderRadius: 28,
        padding: "20px 34px",
        fontFamily: FONT_FAMILY,
        fontSize: 48,
        fontWeight: 600,
        color: COLORS.ink,
        opacity,
        transform: `translateY(${offsetY}px)`,
        boxShadow: "0 8px 20px rgba(0,0,0,0.08)",
        ...style,
      }}
    >
      {text}
    </div>
  );
};
