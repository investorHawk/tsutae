import type { LaneState, LaneSummary } from "./pipelineEvents";

const STATE_LABELS: Readonly<Record<LaneState, string>> = {
  waiting: "待機",
  running: "実行中",
  done: "完了",
  ended: "終了",
};

interface PipelineLanesProps {
  lanes: LaneSummary[];
  /** 変換が終わった（空のレーンの言い方を変える） */
  finished: boolean;
}

function LaneBody({
  lane,
  finished,
}: {
  lane: LaneSummary;
  finished: boolean;
}) {
  if (lane.last === null) {
    return (
      <p className="d-pl-lane-empty">
        {finished ? "この変換では動いていません" : "まだ動いていません"}
      </p>
    );
  }
  return (
    <>
      <p className="d-pl-lane-count">
        出来事 {lane.count} 件
        {lane.denied > 0 ? (
          <span className="d-pl-lane-denied"> ・ 止めた {lane.denied} 件</span>
        ) : null}
      </p>
      <p className={`d-pl-lane-last d-pl-tone--${lane.last.tone}`}>
        <span className="d-pl-lane-last-label">最後:</span> {lane.last.title}
        {lane.last.decisionLabel ? ` ・ ${lane.last.decisionLabel}` : ""}
      </p>
    </>
  );
}

/**
 * 主エージェントと3役のレーン。役ごとの要約（状態・件数・最後の出来事）だけを出す。
 * 出来事の1件ずつは下の「すべての出来事」にまとめる（同じものを2回出さない）。
 */
export default function PipelineLanes({ lanes, finished }: PipelineLanesProps) {
  return (
    <section className="d-pl-lanes" aria-label="3役のレーン">
      {lanes.map((lane) => (
        <div
          key={lane.lane}
          role="group"
          aria-label={lane.code ? `${lane.title}（${lane.code}）` : lane.title}
          className={`d-pl-lane d-pl-lane--${lane.lane} d-pl-lane--${lane.state}`}
        >
          <div className="d-pl-lane-head">
            <span className="d-pl-lane-title">{lane.title}</span>
            <span className={`d-pl-state d-pl-state--${lane.state}`}>
              {STATE_LABELS[lane.state]}
            </span>
          </div>
          {lane.code ? <code className="d-pl-code">{lane.code}</code> : null}
          <p className="d-pl-lane-desc">{lane.description}</p>
          <LaneBody lane={lane} finished={finished} />
        </div>
      ))}
    </section>
  );
}
