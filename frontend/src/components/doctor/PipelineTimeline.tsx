import { formatDuration, formatElapsed, formatTime } from "./format";
import { LANE_LABELS, type ViewEvent } from "./pipelineEvents";

const KIND_LABELS: Readonly<Record<ViewEvent["kind"], string>> = {
  hook: "Hook",
  subagent: "サブエージェント",
  emit: "出力ツール",
  tool: "ツール",
  run: "変換",
};

function Card({ view }: { view: ViewEvent }) {
  const { source } = view;
  return (
    <li
      className={`d-pl-card d-pl-card--${view.kind} d-pl-card--${view.tone} d-pl-lane--${view.lane}`}
    >
      <div className="d-pl-card-time">
        <span className="d-pl-elapsed">
          {view.elapsedMs !== null ? formatElapsed(view.elapsedMs) : ""}
        </span>
        <span className="d-muted">{formatTime(view.ts)}</span>
      </div>
      <div className="d-pl-card-body">
        <div className="d-pl-card-tags">
          <span className="d-pl-tag">{KIND_LABELS[view.kind]}</span>
          <span className="d-pl-tag d-pl-tag--lane">
            {LANE_LABELS[view.lane].title}
          </span>
        </div>
        <p className="d-pl-card-title">{view.title}</p>
        <p className="d-pl-card-meta">
          {view.decisionLabel ? (
            <span className={`d-pl-decision d-pl-tone--${view.tone}`}>
              {view.decisionLabel}
            </span>
          ) : null}
          {view.decisionCode ? <code>{view.decisionCode}</code> : null}
          {source.tool_name && view.kind !== "tool" ? (
            <code>{source.tool_name}</code>
          ) : null}
          {source.duration_ms !== null ? (
            <span>所要 {formatDuration(source.duration_ms)}</span>
          ) : null}
          <span className="d-muted">{source.event}</span>
        </p>
      </div>
    </li>
  );
}

/** 時系列のカード（古い順）。 */
export default function PipelineTimeline({ views }: { views: ViewEvent[] }) {
  if (views.length === 0) {
    return <p className="d-muted">まだ出来事はありません</p>;
  }
  return (
    <ol className="d-pl-timeline" aria-label="時系列">
      {views.map((view) => (
        <Card key={view.index} view={view} />
      ))}
    </ol>
  );
}
