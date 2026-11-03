import { useState } from "react";
import {
  approveSkillChange,
  createSkillChange,
  listSkillChanges,
  rejectSkillChange,
} from "../../api/doctor";
import type { CreateSkillChangeResponse, SkillChange } from "../../api/types";
import { checked } from "../../api/validate";
import { isUsableDiff } from "./diff";
import { isCreateSkillChangeResponse } from "./guards";
import {
  SKILL_CHANGE_FAILED,
  decidedPhase,
  isLostDecision,
  settleWatched,
  watchStartedAt,
} from "./skillChangeWork";
import type { ReviewTarget } from "./SkillReview";

export { SKILL_CHANGE_FAILED };

/**
 * D4 の段階: 入力 → 生成中 → 差分の確認 → 承認／却下（または失敗）。
 * 生成中の changeId は、履歴で見張っている作業中の変更（自分の依頼の応答待ちなら null）。
 * startedAt は経過秒の起点（ms。見張りでは変更の created_at）。
 */
export type SkillPhase =
  | { kind: "input" }
  | {
      kind: "generating";
      skillName: string;
      startedAt: number;
      changeId: number | null;
    }
  | {
      kind: "review";
      target: ReviewTarget;
      busy: boolean;
      error: string | null;
    }
  | { kind: "approved"; skillName: string; newVersion: number }
  | { kind: "rejected"; skillName: string }
  | { kind: "failed"; changeId: number | null; code: string };

interface FlowOptions {
  handleError: (err: unknown) => string;
  /** 依頼の応答が来た後（成功・失敗とも）。履歴を取り直す */
  onCreated: () => void;
  /** 承認・却下が通った後 */
  onDecided: (approved: boolean) => void;
}

/**
 * 承認・却下の応答を失った（通信の失敗・打ち切り・409 not_pending）とき、履歴を
 * 取り直して、その変更がすでに承認・却下されていればその段階。そうでなければ null。
 */
async function recoverDecision(
  changeId: number,
  err: unknown,
): Promise<SkillPhase | null> {
  if (!isLostDecision(err)) {
    return null;
  }
  try {
    const { skill_changes: history } = await listSkillChanges();
    return decidedPhase(changeId, history);
  } catch {
    return null; // 取り直しも失敗したら元のエラーを出す
  }
}

function reviewOf(
  target: ReviewTarget,
  error: string | null = null,
): SkillPhase {
  return { kind: "review", target, busy: false, error };
}

export function useSkillChangeFlow({
  handleError,
  onCreated,
  onDecided,
}: FlowOptions) {
  const [phase, setPhase] = useState<SkillPhase>({ kind: "input" });

  async function request(skillName: string, requestText: string) {
    setPhase({
      kind: "generating",
      skillName,
      startedAt: Date.now(),
      changeId: null,
    });
    try {
      const res = checked<CreateSkillChangeResponse>(
        await createSkillChange(skillName, requestText),
        isCreateSkillChangeResponse,
      );
      const diff = res.status === "pending" ? res.diff : null;
      setPhase(
        isUsableDiff(diff)
          ? reviewOf({ id: res.id, skillName, requestText, diff })
          : { kind: "failed", changeId: res.id, code: SKILL_CHANGE_FAILED },
      );
    } catch (err) {
      setPhase({ kind: "failed", changeId: null, code: handleError(err) });
    }
    onCreated();
  }

  async function decide(approve: boolean) {
    if (phase.kind !== "review") {
      return;
    }
    const { target } = phase;
    setPhase({ ...phase, busy: true, error: null });
    try {
      if (approve) {
        // new_version は必須（無い応答は approveSkillChange が invalid_response にする）
        const { new_version: newVersion } = await approveSkillChange(target.id);
        setPhase({ kind: "approved", skillName: target.skillName, newVersion });
      } else {
        await rejectSkillChange(target.id);
        setPhase({ kind: "rejected", skillName: target.skillName });
      }
      onDecided(approve);
    } catch (err) {
      // 応答を失ったかもしれない（通信の失敗・打ち切り・not_pending）なら履歴で確かめる。
      // 済んでいればその結果を出す（押したボタンではなく履歴の状態に従う）
      const recovered = await recoverDecision(target.id, err);
      if (recovered !== null) {
        setPhase(recovered);
        onDecided(recovered.kind === "approved");
        return;
      }
      // まだ pending・409 busy（別の承認・却下がロックを握っている）などは確認画面のまま。
      // もう一度押せる
      setPhase(reviewOf(target, handleError(err)));
    }
  }

  /** 履歴の承認待ちを開く。差分が空なら開かない（承認させない）。 */
  function review(change: SkillChange) {
    const { diff } = change;
    if (change.status !== "pending" || !isUsableDiff(diff)) {
      return;
    }
    setPhase(
      reviewOf({
        id: change.id,
        skillName: change.skill_name,
        requestText: change.requested_text,
        diff,
      }),
    );
  }

  /** 履歴の作業中の変更を見張る（生成中と出し、終わるのを settle で待つ）。 */
  function watch(change: SkillChange) {
    setPhase({
      kind: "generating",
      skillName: change.skill_name,
      startedAt: watchStartedAt(change.created_at, Date.now()),
      changeId: change.id,
    });
  }

  /** 取り直した履歴で、見張っている変更が終わっていれば次の段階へ。 */
  function settle(history: readonly SkillChange[]) {
    setPhase((prev) => settleWatched(prev, history));
  }

  return { phase, request, decide, review, watch, settle };
}
