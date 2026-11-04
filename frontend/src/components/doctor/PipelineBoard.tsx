import { useMemo } from "react";
import type { PipelineEvent } from "../../api/types";
import { formatElapsed } from "./format";
import PipelineHooks from "./PipelineHooks";
import PipelineLanes from "./PipelineLanes";
import PipelineTimeline from "./PipelineTimeline";
import {
  hookSummaries,
  laneSummaries,
  runSummary,
  toViewEvents,
} from "./pipelineEvents";
import "./pipeline.css";

interface PipelineBoardProps {
  events: readonly PipelineEvent[];
  /** 変換が終わった（ready / failed / printed） */
  finished: boolean;
}

/** D5 の盤面: Hook のタイル → 3役のレーン → 時系列のカード。 */
export default function PipelineBoard({
  events,
  finished,
}: PipelineBoardProps) {
  const views = useMemo(() => toViewEvents(events), [events]);
  const lanes = useMemo(
    () => laneSummaries(views, finished),
    [views, finished],
  );
  const hooks = useMemo(() => hookSummaries(views), [views]);
  const summary = runSummary(views);

  return (
    <div className="d-pl-board">
      <p className="d-pl-summary">
        出来事 {summary.count} 件 ・ 拒否 {summary.denied} 件
        {summary.elapsedMs !== null
          ? ` ・ 経過 ${formatElapsed(summary.elapsedMs)}`
          : ""}
      </p>
      <PipelineHooks hooks={hooks} />
      <PipelineLanes lanes={lanes} />
      <h2>時系列</h2>
      <PipelineTimeline views={views} />
    </div>
  );
}
