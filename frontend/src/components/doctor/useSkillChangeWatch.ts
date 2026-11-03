import { useEffect } from "react";
import type { SkillChange } from "../../api/types";
import { findWorking } from "./skillChangeWork";
import type { SkillPhase } from "./useSkillChangeFlow";

/** 作業中の変更を見張る間、履歴を取り直す間隔（ms）。 */
export const SKILL_HISTORY_POLL_MS = 3000;

interface WatchOptions {
  phase: SkillPhase;
  /** 新しい順。読み込み前は null */
  history: readonly SkillChange[] | null;
  reloadHistory: () => Promise<void>;
  watch: (change: SkillChange) => void;
  settle: (history: readonly SkillChange[]) => void;
}

/**
 * D4: 履歴に作業中（pending・diff なし）の変更があれば見張る（生成中と出してフォームを
 * 止める）。見張る間は履歴を SKILL_HISTORY_POLL_MS ごとに取り直し、終われば settle で
 * 差分の確認（失敗ならその code）へ進む。作業中が無ければ取り直さない。
 * 自分の依頼の応答待ち（changeId が null）・差分の確認中は、ほかの作業中に乗り換えない。
 */
export function useSkillChangeWatch({
  phase,
  history,
  reloadHistory,
  watch,
  settle,
}: WatchOptions): void {
  const working = findWorking(history);
  const idle = phase.kind !== "generating" && phase.kind !== "review";
  const watchingId = phase.kind === "generating" ? phase.changeId : null;

  useEffect(() => {
    if (idle && working) {
      watch(working);
    }
    // working は id で見る（取り直しのたびに別のオブジェクトになる）
  }, [idle, working?.id]);

  useEffect(() => {
    if (watchingId !== null && history) {
      settle(history);
    }
  }, [watchingId, history]);

  useEffect(() => {
    if (watchingId === null) {
      return undefined;
    }
    const timer = setInterval(
      () => void reloadHistory(),
      SKILL_HISTORY_POLL_MS,
    );
    return () => clearInterval(timer);
  }, [watchingId, reloadHistory]);
}
