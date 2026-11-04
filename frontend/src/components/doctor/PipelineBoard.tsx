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

/**
 * D5 の盤面: Hook（検問）のタイル → 役ごとの要約のレーン → すべての出来事（折りたたみ）。
 * 一目で「3人の担当が分担し、検問が通した／止めた」が分かることを先にする。
 */
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
      <h2 className="d-pl-heading">検問（Hook）</h2>
      <PipelineHooks hooks={hooks} />
      <h2 className="d-pl-heading">担当の分担</h2>
      <PipelineLanes lanes={lanes} finished={finished} />
      {views.length === 0 ? (
        <p className="d-muted">まだ出来事はありません</p>
      ) : (
        <details className="d-pl-all">
          <summary>すべての出来事（{views.length} 件）</summary>
          <PipelineTimeline views={views} />
        </details>
      )}
    </div>
  );
}
