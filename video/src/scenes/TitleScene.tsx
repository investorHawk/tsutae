import { AbsoluteFill, useCurrentFrame } from "remotion";
import { COLORS, FONT_FAMILY, FONT_SIZE } from "../theme";
import { appear } from "./anim";
import type { SceneComponentProps } from "./types";

/** タイトル・一文・札 */
export const TitleScene: React.FC<SceneComponentProps> = ({ scene }) => {
  const frame = useCurrentFrame();
  const lines = scene.props?.lines ?? [];
  return (
    <AbsoluteFill
      style={{
        background: COLORS.paper,
        justifyContent: "center",
        alignItems: "center",
        fontFamily: FONT_FAMILY,
        color: COLORS.ink,
        paddingBottom: 160,
      }}
    >
      <div
        style={{
          fontSize: 200,
          fontWeight: 900,
          letterSpacing: 24,
          ...appear(frame, 0, 18, 30),
        }}
      >
        つたえ
      </div>
      <div style={{ marginTop: 36, textAlign: "center" }}>
        {lines.map((line, i) => (
          <div
            key={line}
            style={{
              fontSize: FONT_SIZE.heading,
              fontWeight: 700,
              lineHeight: 1.4,
              color: i === lines.length - 1 ? COLORS.navy : COLORS.ink,
              ...appear(frame, 24 + i * 30),
            }}
          >
            {line}
          </div>
        ))}
      </div>
      {scene.props?.tag ? (
        <div
          style={{
            marginTop: 44,
            padding: "10px 28px",
            border: `3px solid ${COLORS.purple}`,
            borderRadius: 999,
            color: COLORS.purple,
            fontSize: FONT_SIZE.body,
            fontWeight: 600,
            ...appear(frame, 24 + lines.length * 30),
          }}
        >
          {scene.props.tag}
        </div>
      ) : null}
    </AbsoluteFill>
  );
};
