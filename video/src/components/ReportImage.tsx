import { Img, staticFile } from "remotion";
import { COLORS } from "../theme";
import { REPORT_IMAGE, REPORT_SIZE, type Rect } from "../scenes/reportRegions";

export interface Camera {
  /** 画面の中央に来る画像上の点 */
  cx: number;
  cy: number;
  scale: number;
}

export interface Highlight {
  rect: Rect;
  /** 0〜1 */
  strength: number;
}

interface ReportImageProps {
  camera: Camera;
  viewport: { width: number; height: number };
  highlights?: Highlight[];
  rotate?: number;
  offsetY?: number;
}

/** 視野に収めるカメラ（margin は余白の割合） */
export const fitCamera = (
  rect: Rect,
  viewport: { width: number; height: number },
  margin = 0.9,
  maxScale = 2.4,
): Camera => ({
  cx: rect.x + rect.w / 2,
  cy: rect.y + rect.h / 2,
  scale: Math.min(
    maxScale,
    (viewport.width * margin) / rect.w,
    (viewport.height * margin) / rect.h,
  ),
});

export const lerpCamera = (a: Camera, b: Camera, t: number): Camera => ({
  cx: a.cx + (b.cx - a.cx) * t,
  cy: a.cy + (b.cy - a.cy) * t,
  scale: a.scale + (b.scale - a.scale) * t,
});

/** 受診時レポート（A4 の見本）をカメラで寄って見せる。枠は画像の座標で描く */
export const ReportImage: React.FC<ReportImageProps> = ({
  camera,
  viewport,
  highlights = [],
  rotate = 0,
  offsetY = 0,
}) => {
  const tx = viewport.width / 2 - camera.cx * camera.scale;
  const ty = viewport.height / 2 - camera.cy * camera.scale + offsetY;
  return (
    <div
      style={{
        position: "absolute",
        left: 0,
        top: 0,
        width: REPORT_SIZE.width,
        height: REPORT_SIZE.height,
        transformOrigin: "0 0",
        transform: `translate(${tx}px, ${ty}px) scale(${camera.scale}) rotate(${rotate}deg)`,
        boxShadow: "0 30px 80px rgba(0,0,0,0.25)",
      }}
    >
      <Img
        src={staticFile(REPORT_IMAGE)}
        style={{ width: REPORT_SIZE.width, height: REPORT_SIZE.height }}
      />
      {highlights.map(({ rect, strength }, i) => (
        <div
          key={i}
          style={{
            position: "absolute",
            left: rect.x - 3,
            top: rect.y - 2,
            width: rect.w + 6,
            height: rect.h + 4,
            border: `3px solid ${COLORS.reject}`,
            borderRadius: 4,
            background: `rgba(242, 183, 5, ${0.28 * strength})`,
            boxShadow: `0 0 ${14 * strength}px rgba(242, 183, 5, ${0.9 * strength})`,
            opacity: strength,
          }}
        />
      ))}
    </div>
  );
};
