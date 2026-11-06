import { formatClock } from "../lib/clock";
import { COLORS, FONT_FAMILY } from "../theme";

export { formatClock };

interface ClockProps {
  /** 経過秒 */
  seconds: number;
  /** リングが一周する秒（既定 180 = 3 分） */
  fullSeconds?: number;
  size?: number;
  color?: string;
  label?: string;
}

/** 文字盤: 外のリングが ratio まで進み、針が angle 度を指す */
const ClockFace: React.FC<{
  size: number;
  ratio: number;
  angle: number;
  color: string;
}> = ({ size, ratio, angle, color }) => {
  const half = size / 2;
  const r = half - 14;
  const c = 2 * Math.PI * r;
  return (
    <svg width={size} height={size}>
      <circle
        cx={half}
        cy={half}
        r={r}
        fill={COLORS.white}
        stroke={COLORS.line}
        strokeWidth={14}
      />
      <circle
        cx={half}
        cy={half}
        r={r}
        fill="none"
        stroke={color}
        strokeWidth={14}
        strokeDasharray={`${c * ratio} ${c}`}
        transform={`rotate(-90 ${half} ${half})`}
        strokeLinecap="round"
      />
      <line
        x1={half}
        y1={half}
        x2={half}
        y2={half - r + 30}
        stroke={color}
        strokeWidth={8}
        strokeLinecap="round"
        transform={`rotate(${angle} ${half} ${half})`}
      />
      <circle cx={half} cy={half} r={12} fill={color} />
    </svg>
  );
};

/** ストップウォッチ: 針は 60 秒で一周、外のリングは fullSeconds までの進み */
export const Clock: React.FC<ClockProps> = ({
  seconds,
  fullSeconds = 180,
  size = 300,
  color = COLORS.ink,
  label,
}) => (
  <div
    style={{
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      gap: 12,
      fontFamily: FONT_FAMILY,
    }}
  >
    <ClockFace
      size={size}
      ratio={Math.min(1, Math.max(0, seconds / fullSeconds))}
      angle={((seconds % 60) / 60) * 360}
      color={color}
    />
    <div
      style={{
        fontSize: size * 0.34,
        fontWeight: 800,
        color,
        fontVariantNumeric: "tabular-nums",
        lineHeight: 1,
      }}
    >
      {formatClock(seconds)}
    </div>
    {label ? (
      <div style={{ fontSize: 40, color: COLORS.inkSoft }}>{label}</div>
    ) : null}
  </div>
);
