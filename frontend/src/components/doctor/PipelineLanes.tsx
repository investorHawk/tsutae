import { formatElapsed } from "./format";
import type { LaneState, LaneSummary } from "./pipelineEvents";

const STATE_LABELS: Readonly<Record<LaneState, string>> = {
  waiting: "待機",
  running: "実行中",
  done: "完了",
  ended: "終了",
};

/** 主エージェントと3役のレーン。各レーンに自分の出来事をチップで積む。 */
export default function PipelineLanes({ lanes }: { lanes: LaneSummary[] }) {
  return (
    <section className="d-pl-lanes" aria-label="3役のレーン">
      {lanes.map((lane) => (
        <div
          key={lane.lane}
          role="group"
          aria-label={lane.title}
          className={`d-pl-lane d-pl-lane--${lane.lane} d-pl-lane--${lane.state}`}
        >
          <div className="d-pl-lane-head">
            <span className="d-pl-lane-title">{lane.title}</span>
            <span className={`d-pl-state d-pl-state--${lane.state}`}>
              {STATE_LABELS[lane.state]}
            </span>
          </div>
          <p className="d-pl-lane-desc">{lane.description}</p>
          <ul className="d-pl-chips">
            {lane.events.map((v) => (
              <li
                key={v.index}
                className={`d-pl-chip d-pl-chip--${v.kind} d-pl-tone--${v.tone}`}
              >
                <span className="d-pl-chip-time">
                  {v.elapsedMs !== null ? formatElapsed(v.elapsedMs) : ""}
                </span>
                {v.title}
                {v.decisionLabel ? ` ・ ${v.decisionLabel}` : ""}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </section>
  );
}
