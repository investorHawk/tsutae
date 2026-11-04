import { useCallback, useRef } from "react";
import { Link, useParams } from "react-router-dom";
import { getPipelineEvents } from "../../api/doctor";
import { isApiError } from "../../api/http";
import type { PipelineEvent, VisitStatus } from "../../api/types";
import ErrorNote from "../../components/doctor/ErrorNote";
import { errorCode, isUnauthorized } from "../../components/doctor/errors";
import { isPipelineEvent, isVisitStatus } from "../../components/doctor/guards";
import {
  invalidResponse,
  isRecord,
  listOf,
  parseVisitId,
} from "../../components/doctor/input";
import PipelineBoard from "../../components/doctor/PipelineBoard";
import StatusBadge from "../../components/doctor/StatusBadge";
import { usePolling } from "../../components/doctor/usePolling";
import { useDoctorApiError } from "../../components/doctor/useDoctorApiError";
import "../../components/doctor/doctor-ui.css";

const PIPELINE_POLL_MS = 2000;
const FINISHED: readonly VisitStatus[] = ["ready", "failed", "printed"];

interface Snapshot {
  status: VisitStatus;
  events: PipelineEvent[];
}

function isFinished(status: VisitStatus): boolean {
  return FINISHED.includes(status);
}

/**
 * 止める条件（ready・failed・printed）を2回続けて見たら止める（1回目の後に1回だけ
 * 取り直す）。状態が変わった直後に記録される出来事（保存・後始末）を取りこぼさない。
 * 最後の取り直しで終わっていなければ数え直す。
 */
function useStopAfterOneMore(): (snap: Snapshot) => boolean {
  const seen = useRef(false);
  return useCallback((snap: Snapshot) => {
    if (!isFinished(snap.status)) {
      seen.current = false;
      return false;
    }
    if (seen.current) {
      return true;
    }
    seen.current = true;
    return false;
  }, []);
}

/** 本文を検査して取り出す。status か events が契約と違えば invalid_response。 */
function toSnapshot(body: unknown): Snapshot {
  const status = isRecord(body) ? body.status : undefined;
  if (!isVisitStatus(status)) {
    throw invalidResponse();
  }
  return {
    status,
    events: listOf<PipelineEvent>(body, "events", isPipelineEvent),
  };
}

/**
 * D5 パイプライン可視化。2秒ごとに取り直し、ready / failed / printed を見たら
 * もう1回だけ取り直して止める。
 * 受診ごとに描き直す（別の受診へ移ったら、前の受診の状態・出来事・失敗・停止を引き継がず、
 * 前の受診の遅い応答も捨てる。usePolling の値は描いている間だけのもの）。
 */
export default function Pipeline() {
  const { visitId } = useParams();
  return <PipelineView key={visitId ?? ""} visitId={visitId} />;
}

function PipelineView({ visitId }: { visitId: string | undefined }) {
  const id = parseVisitId(visitId);
  const handleError = useDoctorApiError();
  const shouldStop = useStopAfterOneMore();
  const fetcher = useCallback(
    async () => toSnapshot(await getPipelineEvents(id ?? 0)),
    [id],
  );
  const polling = usePolling(fetcher, PIPELINE_POLL_MS, {
    enabled: id !== null,
    shouldStop,
    onError: (err) => {
      handleError(err);
      return isUnauthorized(err) || (isApiError(err) && err.status === 404);
    },
  });
  const snap = polling.data;

  return (
    <section className="page d-pipeline">
      <h1>パイプライン</h1>
      <div className="d-toolbar">
        <span>受診 #{id ?? "?"}</span>
        {snap ? <StatusBadge status={snap.status} /> : null}
        {id !== null ? (
          <span className={`d-live ${polling.stopped ? "" : "d-live--on"}`}>
            {polling.stopped ? "更新を止めました" : "2秒ごとに更新中"}
          </span>
        ) : null}
        <Link className="d-sublink" to="/doctor">
          印刷待ちへ戻る
        </Link>
      </div>
      <p className="d-muted">
        出来事の種類・時刻・判定コードだけを出します。記録の文面はログに残さないので、ここにも出ません。
      </p>
      {id === null ? <ErrorNote code="invalid_visit_id" /> : null}
      {polling.error ? <ErrorNote code={errorCode(polling.error)} /> : null}
      {snap ? (
        <PipelineBoard
          events={snap.events}
          finished={isFinished(snap.status)}
        />
      ) : null}
    </section>
  );
}
