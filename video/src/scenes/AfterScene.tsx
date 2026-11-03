import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { Caption } from "../components/Caption";
import { Clock } from "../components/Clock";
import { fitCamera, lerpCamera, ReportImage } from "../components/ReportImage";
import { COLORS, FONT_FAMILY } from "../theme";
import { appear, CLAMP } from "./anim";
import { ALERT_ROWS, REGIONS, REPORT_SIZE } from "./reportRegions";
import type { SceneComponentProps } from "./types";

const DESK = { left: 60, top: 40, width: 1040, height: 810 };
const VIEWPORT = { width: DESK.width, height: DESK.height };

/** A4 が机に置かれ（下から滑り込む）、要確認の領域へ寄る */
const Desk: React.FC<{
  frame: number;
  zoomAt: number;
  pulse: (i: number) => number;
}> = ({ frame, zoomAt, pulse }) => {
  const whole = fitCamera(
    { x: 0, y: 0, w: REPORT_SIZE.width, h: REPORT_SIZE.height },
    VIEWPORT,
    0.94,
  );
  const close = fitCamera(REGIONS.alerts, VIEWPORT, 0.94, 1.4);
  const zoom = interpolate(frame, [zoomAt, zoomAt + 24], [0, 1], CLAMP);
  const slide = interpolate(frame, [0, 22], [0, 1], CLAMP);
  return (
    <div
      style={{
        position: "absolute",
        ...DESK,
        overflow: "hidden",
        borderRadius: 28,
        background: "#d9cdb4",
      }}
    >
      <ReportImage
        viewport={VIEWPORT}
        camera={lerpCamera(whole, close, zoom)}
        rotate={(1 - zoom) * -2}
        offsetY={(1 - slide) * 900}
        highlights={ALERT_ROWS.map((rect, i) => ({ rect, strength: pulse(i) }))}
      />
    </div>
  );
};

const AlertList: React.FC<{
  alerts: string[];
  frame: number;
  startOf: (i: number) => number;
  pulse: (i: number) => number;
}> = ({ alerts, frame, startOf, pulse }) => (
  <div
    style={{
      position: "absolute",
      top: 260,
      left: 1410,
      right: 40,
      display: "flex",
      flexDirection: "column",
      gap: 22,
    }}
  >
    {alerts.map((a, i) => (
      <div
        key={a}
        style={{
          fontSize: 44,
          fontWeight: 800,
          lineHeight: 1.3,
          padding: "12px 18px",
          borderRadius: 14,
          background: `rgba(242, 183, 5, ${0.35 * pulse(i)})`,
          borderLeft: `10px solid ${COLORS.reject}`,
          ...appear(frame, startOf(i)),
        }}
      >
        {a}
      </div>
    ))}
  </div>
);

/** 机に A4 = sample-report.png がすっと置かれ、要確認の 3 行が光る。時計 0:30 */
export const AfterScene: React.FC<SceneComponentProps> = ({
  scene,
  durationInFrames,
}) => {
  const frame = useCurrentFrame();
  const zoomAt = durationInFrames * 0.3;
  const glowAt = (i: number) => zoomAt + 30 + i * 30;
  const pulse = (i: number) =>
    interpolate(frame, [glowAt(i), glowAt(i) + 10], [0, 1], CLAMP) *
    (0.75 + 0.25 * Math.sin((frame - glowAt(i)) / 5));
  const elapsed = interpolate(
    frame,
    [zoomAt, durationInFrames * 0.75],
    [0, 30],
    CLAMP,
  );
  return (
    <AbsoluteFill style={{ background: COLORS.paper, fontFamily: FONT_FAMILY }}>
      <Desk frame={frame} zoomAt={zoomAt} pulse={pulse} />
      {scene.title ? (
        <Caption text={scene.title} top={130} left={1160} />
      ) : null}
      <div style={{ position: "absolute", top: 270, left: 1150 }}>
        <Clock
          seconds={elapsed}
          size={210}
          color={COLORS.navy}
          label="聞き取り"
        />
      </div>
      <AlertList
        alerts={scene.props?.alerts ?? []}
        frame={frame}
        startOf={glowAt}
        pulse={pulse}
      />
    </AbsoluteFill>
  );
};
