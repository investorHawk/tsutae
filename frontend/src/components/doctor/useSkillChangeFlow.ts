import { useState } from "react";
import {
  approveSkillChange,
  createSkillChange,
  rejectSkillChange,
} from "../../api/doctor";
import type { CreateSkillChangeResponse, SkillChange } from "../../api/types";
import { checked } from "../../api/validate";
import { isUsableDiff } from "./diff";
import { isCreateSkillChangeResponse } from "./guards";
import type { ReviewTarget } from "./SkillReview";

/** D4 の段階: 入力 → 生成中 → 差分の確認 → 承認／却下（または失敗）。 */
export type SkillPhase =
  | { kind: "input" }
  | { kind: "generating"; skillName: string }
  | {
      kind: "review";
      target: ReviewTarget;
      busy: boolean;
      error: string | null;
    }
  | { kind: "approved"; skillName: string; newVersion: number }
  | { kind: "rejected"; skillName: string }
  | { kind: "failed"; changeId: number | null; code: string };

/** 書き換えが失敗した（diff が無い・空）が履歴に error_code が無いときの code。 */
export const SKILL_CHANGE_FAILED = "skill_change_failed";

interface FlowOptions {
  handleError: (err: unknown) => string;
  /** 依頼の応答が来た後（成功・失敗とも）。履歴を取り直す */
  onCreated: () => void;
  /** 承認・却下が通った後 */
  onDecided: (approved: boolean) => void;
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
    setPhase({ kind: "generating", skillName });
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
      // 409 busy（別の承認・却下がロックを握っている）は確認画面のまま。もう一度押せる
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

  return { phase, request, decide, review };
}
