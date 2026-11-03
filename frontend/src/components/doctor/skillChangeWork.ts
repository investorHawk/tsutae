/**
 * D4 の「作業中」（pending で diff がまだ無い。サーバーで editor が書き換えている）の
 * 判定と、見張っている変更が終わったときの次の段階（純関数）。
 */
import { SKILL_CHANGE_TIMEOUT_MS } from "../../api/doctor";
import { isApiError } from "../../api/http";
import type { SkillChange } from "../../api/types";
import { isUsableDiff } from "./diff";
import type { SkillPhase } from "./useSkillChangeFlow";

/** 書き換えが失敗した（diff が無い・空）が履歴に error_code が無いときの code。 */
export const SKILL_CHANGE_FAILED = "skill_change_failed";

/** pending で diff がまだ無い（空文字の diff は作業中ではなく、使えない差分）。 */
export function isWorking(change: SkillChange): boolean {
  return change.status === "pending" && change.diff === null;
}

/** 新しい順の履歴から、最初の作業中の変更。無ければ null。 */
export function findWorking(
  history: readonly SkillChange[] | null,
): SkillChange | null {
  return history?.find(isWorking) ?? null;
}

/**
 * 見張っている変更（generating で changeId がある）の、取り直した履歴での次の段階。
 * まだ作業中・履歴に無い・見張っていなければ prev をそのまま返す。
 */
export function settleWatched(
  prev: SkillPhase,
  history: readonly SkillChange[],
): SkillPhase {
  if (prev.kind !== "generating" || prev.changeId === null) {
    return prev;
  }
  const found = history.find((c) => c.id === prev.changeId);
  if (!found || isWorking(found)) {
    return prev;
  }
  if (found.status === "pending") {
    const { diff } = found;
    return isUsableDiff(diff)
      ? {
          kind: "review",
          target: {
            id: found.id,
            skillName: found.skill_name,
            requestText: found.requested_text,
            diff,
          },
          busy: false,
          error: null,
        }
      : { kind: "failed", changeId: found.id, code: SKILL_CHANGE_FAILED };
  }
  if (found.status === "failed") {
    return {
      kind: "failed",
      changeId: found.id,
      code: found.error_code ?? SKILL_CHANGE_FAILED,
    };
  }
  return { kind: "input" };
}

/** startedAt（ms）から nowMs までの経過秒（切り捨て、0 未満にしない）。 */
export function elapsedSeconds(startedAt: number, nowMs: number): number {
  return Math.max(0, Math.floor((nowMs - startedAt) / 1000));
}

/**
 * 見張る変更の経過秒の起点（ms）。created_at が今より前で、依頼の打ち切り（10 分）より
 * 新しければ created_at。そうでなければ（デモの固定日 TSUTAE_TODAY などでサーバーの
 * 時計がずれている・読めない）見張り始めた今から数える。
 */
export function watchStartedAt(createdAt: string, nowMs: number): number {
  const created = Date.parse(createdAt);
  const plausible =
    !Number.isNaN(created) &&
    created <= nowMs &&
    nowMs - created <= SKILL_CHANGE_TIMEOUT_MS;
  return plausible ? created : nowMs;
}

/**
 * 承認・却下の要求の失敗が「サーバーでは済んだかもしれない」ものか。通信の失敗・
 * 打ち切り（status 0）と 409 not_pending（もう pending でない）だけ。busy・stale_base・
 * invalid_response などは済んでいないので違う。
 */
export function isLostDecision(err: unknown): boolean {
  if (!isApiError(err)) {
    return false;
  }
  return err.status === 0 || (err.status === 409 && err.code === "not_pending");
}

/**
 * 取り直した履歴で、その変更がすでに承認・却下されていればその段階。まだ pending・
 * failed・履歴に無い・approved で new_version が無いなら null（エラーのまま）。
 */
export function decidedPhase(
  changeId: number,
  history: readonly SkillChange[],
): SkillPhase | null {
  const found = history.find((c) => c.id === changeId);
  if (found?.status === "approved" && found.new_version !== null) {
    return {
      kind: "approved",
      skillName: found.skill_name,
      newVersion: found.new_version,
    };
  }
  if (found?.status === "rejected") {
    return { kind: "rejected", skillName: found.skill_name };
  }
  return null;
}
