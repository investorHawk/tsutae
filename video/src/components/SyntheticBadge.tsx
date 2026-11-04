import { COLORS, FONT_FAMILY, FONT_SIZE } from "../theme";

/** 右上の札（150 秒ずっと出す） */
export const SyntheticBadge: React.FC = () => (
  <div
    style={{
      position: "absolute",
      top: 28,
      right: 32,
      padding: "10px 22px",
      background: COLORS.white,
      border: `3px solid ${COLORS.ink}`,
      borderRadius: 10,
      fontFamily: FONT_FAMILY,
      fontSize: FONT_SIZE.badge,
      fontWeight: 700,
      color: COLORS.ink,
      letterSpacing: 1,
      boxShadow: "0 4px 14px rgba(0,0,0,0.12)",
      zIndex: 100,
    }}
  >
    症例は全て合成（架空）
  </div>
);
