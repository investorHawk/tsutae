import { useCurrentFrame, useVideoConfig } from "remotion";
import {
  DEVICE_LABEL,
  FOOTAGE,
  footageTargetPath,
  type Device,
} from "../footage";
import { COLORS, FONT_FAMILY, MONO_FAMILY } from "../theme";
import type { FootageId } from "../types";

interface FootageCardProps {
  id: FootageId;
  /** この場面で使う秒 */
  seconds: number;
  /** 細い列に収める（masking の左半分など） */
  compact?: boolean;
}

const DeviceOutline: React.FC<{ device: Device }> = ({ device }) => {
  const size =
    device === "phone"
      ? { width: 270, height: 480, radius: 40 }
      : { width: 440, height: 248, radius: 16 };
  return (
    <div
      style={{
        ...size,
        borderRadius: size.radius,
        border: `6px dashed ${COLORS.inkSoft}`,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontSize: 40,
        color: COLORS.inkSoft,
        flexShrink: 0,
      }}
    >
      {device === "camera" ? "カメラ" : device === "pc" ? "16:9" : "9:16"}
    </div>
  );
};

const Row: React.FC<{ label: string; children: React.ReactNode }> = ({
  label,
  children,
}) => (
  <div style={{ display: "flex", gap: 24, alignItems: "baseline" }}>
    <div
      style={{
        width: 200,
        flexShrink: 0,
        color: COLORS.inkSoft,
        whiteSpace: "nowrap",
      }}
    >
      {label}
    </div>
    <div style={{ flex: 1 }}>{children}</div>
  </div>
);

const CardInfo: React.FC<{
  id: FootageId;
  seconds: number;
  left: number;
  compact: boolean;
}> = ({ id, seconds, left, compact }) => {
  const spec = FOOTAGE[id];
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: compact ? 14 : 18,
        fontSize: 44,
        lineHeight: 1.4,
        flex: 1,
      }}
    >
      <div
        style={{
          fontSize: compact ? 60 : 72,
          fontWeight: 800,
          lineHeight: 1.2,
        }}
      >
        撮影枠 <span style={{ color: COLORS.navy }}>{id}</span>
        <span style={{ fontSize: 40, color: COLORS.inkSoft }}>
          {" "}
          {spec.slug}
        </span>
      </div>
      <Row label="場面">{spec.scene}</Row>
      <Row label="端末">{DEVICE_LABEL[spec.device]}</Row>
      <Row label="秒">
        最低 {spec.minSeconds} 秒（ここで {seconds} 秒使う・残り {left}）
      </Row>
      {compact ? null : <Row label="撮る内容">{spec.content}</Row>}
      <div
        style={{
          marginTop: 8,
          fontSize: compact ? 32 : 38,
          color: COLORS.navy,
        }}
      >
        撮影後に{" "}
        <span style={{ fontFamily: MONO_FAMILY, fontWeight: 700 }}>
          {footageTargetPath(id)}
        </span>{" "}
        に置く
      </div>
    </div>
  );
};

/** 撮影前の枠: 何を・何秒撮るか・どこに置くかを大きく出す */
export const FootageCard: React.FC<FootageCardProps> = ({
  id,
  seconds,
  compact = false,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const left = Math.max(0, Math.ceil(seconds - frame / fps));
  return (
    <div
      style={{
        position: "absolute",
        top: compact ? 140 : 120,
        left: compact ? 60 : 80,
        width: compact ? 760 : 1760,
        bottom: 1080 - 850,
        boxSizing: "border-box",
        padding: compact ? "32px 36px" : "40px 56px",
        border: `5px dashed ${COLORS.navy}`,
        borderRadius: 28,
        background: "rgba(255,255,255,0.75)",
        display: "flex",
        gap: 56,
        alignItems: "center",
        fontFamily: FONT_FAMILY,
        color: COLORS.ink,
      }}
    >
      {compact ? null : <DeviceOutline device={FOOTAGE[id].device} />}
      <CardInfo id={id} seconds={seconds} left={left} compact={compact} />
    </div>
  );
};
