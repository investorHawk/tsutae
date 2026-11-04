import { AbsoluteFill, Easing, interpolate, useCurrentFrame } from "remotion";
import {
  fitCamera,
  lerpCamera,
  ReportImage,
  type Camera,
  type Highlight,
} from "../components/ReportImage";
import { COLORS, FONT_FAMILY, SUBTITLE_TOP } from "../theme";
import type { ReportFocus } from "../types";
import { appear, CLAMP, ramp } from "./anim";
import {
  HIGHLIGHTS,
  REGION_LABEL,
  REGIONS,
  REPORT_SIZE,
} from "./reportRegions";
import type { SceneComponentProps } from "./types";

const VIEWPORT = { width: 1920, height: SUBTITLE_TOP };
const INTRO = 36; // 全体を見せるフレーム
const MOVE = 22; // 次の領域へ寄るフレーム
const CHIP_SPACE = 130; // 左上の見出しのチップの分、寄ったときは下へずらす
const FOCUS_VIEW = { width: 1920, height: SUBTITLE_TOP - CHIP_SPACE };

interface Stop {
  focus: ReportFocus | null;
  camera: Camera;
  start: number;
}

/** 全体 → focus の順に寄るカメラの停留点 */
const buildStops = (focus: ReportFocus[], duration: number): Stop[] => {
  const whole = fitCamera(
    { x: 0, y: 0, w: REPORT_SIZE.width, h: REPORT_SIZE.height },
    VIEWPORT,
    0.96,
  );
  const each = (duration - INTRO) / Math.max(1, focus.length);
  return [
    { focus: null, camera: whole, start: 0 },
    ...focus.map((f, i) => ({
      focus: f,
      camera: fitCamera(REGIONS[f], FOCUS_VIEW, 0.92),
      start: Math.round(INTRO + i * each),
    })),
  ];
};

const cameraAt = (stops: Stop[], frame: number): Camera => {
  let cam = stops[0].camera;
  for (let i = 1; i < stops.length; i += 1) {
    const t = interpolate(
      frame,
      [stops[i].start, stops[i].start + MOVE],
      [0, 1],
      {
        ...CLAMP,
        easing: Easing.inOut(Easing.cubic),
      },
    );
    cam = lerpCamera(cam, stops[i].camera, t);
  }
  return cam;
};

const currentStop = (stops: Stop[], frame: number): Stop =>
  [...stops].reverse().find((s) => frame >= s.start) ?? stops[0];

/** sample-report.png をパン・ズーム。focus の順に領域へ寄り、Day5 口腔粘膜炎と引用の行に枠 */
export const ReportScene: React.FC<SceneComponentProps> = ({
  scene,
  durationInFrames,
}) => {
  const frame = useCurrentFrame();
  const stops = buildStops(scene.props?.focus ?? [], durationInFrames);
  const stop = currentStop(stops, frame);
  const camera = cameraAt(stops, frame);
  const firstMove = stops[1]?.start ?? durationInFrames;
  const offsetY = (CHIP_SPACE / 2) * ramp(frame, firstMove, MOVE);
  const highlights: Highlight[] = stop.focus
    ? HIGHLIGHTS[stop.focus].map((rect) => ({
        rect,
        strength:
          ramp(frame, stop.start + MOVE, 10) *
          (0.8 + 0.2 * Math.sin((frame - stop.start) / 6)),
      }))
    : [];
  return (
    <AbsoluteFill
      style={{ background: COLORS.paperDeep, fontFamily: FONT_FAMILY }}
    >
      <AbsoluteFill style={{ overflow: "hidden" }}>
        <ReportImage
          camera={camera}
          viewport={VIEWPORT}
          offsetY={offsetY}
          highlights={highlights}
        />
      </AbsoluteFill>
      <div
        key={stop.focus ?? "whole"}
        style={{
          position: "absolute",
          top: 36,
          left: 48,
          padding: "12px 30px",
          borderRadius: 18,
          background: COLORS.ink,
          color: COLORS.white,
          fontSize: 72,
          fontWeight: 900,
          boxShadow: "0 10px 30px rgba(0,0,0,0.25)",
          ...appear(frame, stop.start + (stop.focus ? MOVE / 2 : 4), 10, 12),
        }}
      >
        {stop.focus
          ? REGION_LABEL[stop.focus]
          : (scene.title ?? "受診時レポート")}
      </div>
    </AbsoluteFill>
  );
};
