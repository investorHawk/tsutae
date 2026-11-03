import { describe, expect, it } from "vitest";
import type { SkillChange } from "../../api/types";
import { ApiError, NETWORK_ERROR } from "../../api/http";
import {
  decidedPhase,
  elapsedSeconds,
  findWorking,
  isLostDecision,
  watchStartedAt,
  isWorking,
  settleWatched,
} from "./skillChangeWork";
import type { SkillPhase } from "./useSkillChangeFlow";

const DIFF = "--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n";

function change(patch: Partial<SkillChange>): SkillChange {
  return {
    id: 7,
    skill_name: "regimen-folfox",
    requested_text: "x",
    diff: null,
    status: "pending",
    base_version: 1,
    new_version: null,
    error_code: null,
    created_at: "2026-11-09T10:00:00+09:00",
    decided_at: null,
    ...patch,
  };
}

const WATCHING: SkillPhase = {
  kind: "generating",
  skillName: "regimen-folfox",
  startedAt: 0,
  changeId: 7,
};

describe("isWorking / findWorking", () => {
  it("pending で diff が無い行だけが作業中", () => {
    expect(isWorking(change({}))).toBe(true);
    expect(isWorking(change({ diff: DIFF }))).toBe(false);
    expect(isWorking(change({ diff: "" }))).toBe(false);
    expect(isWorking(change({ status: "failed" }))).toBe(false);
  });

  it("新しい順の一覧から最初の作業中を返す", () => {
    const list = [
      change({ id: 9, status: "failed" }),
      change({ id: 8 }),
      change({ id: 6 }),
    ];
    expect(findWorking(list)?.id).toBe(8);
    expect(findWorking([change({ diff: DIFF })])).toBeNull();
    expect(findWorking(null)).toBeNull();
  });
});

describe("settleWatched", () => {
  it("差分ができたら確認へ", () => {
    const next = settleWatched(WATCHING, [change({ diff: DIFF })]);
    expect(next).toEqual({
      kind: "review",
      target: {
        id: 7,
        skillName: "regimen-folfox",
        requestText: "x",
        diff: DIFF,
      },
      busy: false,
      error: null,
    });
  });

  it("まだ作業中・一覧に無いならそのまま（同じオブジェクト）", () => {
    expect(settleWatched(WATCHING, [change({})])).toBe(WATCHING);
    expect(settleWatched(WATCHING, [])).toBe(WATCHING);
  });

  it("失敗なら failed と error_code", () => {
    expect(
      settleWatched(WATCHING, [
        change({ status: "failed", error_code: "stale_request" }),
      ]),
    ).toEqual({ kind: "failed", changeId: 7, code: "stale_request" });
  });

  it("差分が空の pending は失敗として扱う（承認させない）", () => {
    expect(settleWatched(WATCHING, [change({ diff: "   " })])).toEqual({
      kind: "failed",
      changeId: 7,
      code: "skill_change_failed",
    });
  });

  it("ほかで承認・却下されたら入力に戻る", () => {
    expect(
      settleWatched(WATCHING, [change({ status: "rejected", diff: DIFF })]),
    ).toEqual({ kind: "input" });
  });

  it("見張っていない段階は変えない", () => {
    const own: SkillPhase = { ...WATCHING, changeId: null };
    expect(settleWatched(own, [change({ diff: DIFF })])).toBe(own);
    const input: SkillPhase = { kind: "input" };
    expect(settleWatched(input, [change({ diff: DIFF })])).toBe(input);
  });
});

describe("elapsedSeconds", () => {
  it("切り捨てた秒。負にしない", () => {
    expect(elapsedSeconds(1000, 4999)).toBe(3);
    expect(elapsedSeconds(5000, 1000)).toBe(0);
  });
});

describe("watchStartedAt", () => {
  const NOW = Date.parse("2026-11-09T10:00:30+09:00");

  it("created_at が少し前ならそこから数える", () => {
    expect(watchStartedAt("2026-11-09T10:00:00+09:00", NOW)).toBe(
      Date.parse("2026-11-09T10:00:00+09:00"),
    );
  });

  it("サーバーの時計がずれている（デモの固定日など）なら見張り始めから数える", () => {
    expect(watchStartedAt("2026-11-12T10:00:00+09:00", NOW)).toBe(NOW);
    expect(watchStartedAt("2026-11-01T10:00:00+09:00", NOW)).toBe(NOW);
    expect(watchStartedAt("not a date", NOW)).toBe(NOW);
  });
});

describe("isLostDecision", () => {
  it("通信の失敗・打ち切り（status 0）と 409 not_pending は応答を失ったかもしれない", () => {
    expect(isLostDecision(new ApiError(0, NETWORK_ERROR))).toBe(true);
    expect(isLostDecision(new ApiError(409, "not_pending"))).toBe(true);
  });

  it("それ以外（busy・stale_base・invalid_response・401・ApiError でない）は違う", () => {
    expect(isLostDecision(new ApiError(409, "busy"))).toBe(false);
    expect(isLostDecision(new ApiError(409, "stale_base"))).toBe(false);
    expect(isLostDecision(new ApiError(200, "invalid_response"))).toBe(false);
    expect(isLostDecision(new ApiError(401, "not_logged_in"))).toBe(false);
    expect(isLostDecision(new Error("x"))).toBe(false);
  });
});

describe("decidedPhase", () => {
  it("履歴で approved なら承認の表示（version は履歴の new_version）", () => {
    const history = [
      change({ status: "approved", diff: DIFF, new_version: 2 }),
    ];
    expect(decidedPhase(7, history)).toEqual({
      kind: "approved",
      skillName: "regimen-folfox",
      newVersion: 2,
    });
  });

  it("履歴で rejected なら却下の表示", () => {
    const history = [change({ status: "rejected", diff: DIFF })];
    expect(decidedPhase(7, history)).toEqual({
      kind: "rejected",
      skillName: "regimen-folfox",
    });
  });

  it("まだ pending・failed・履歴に無い・approved で new_version が無いなら null", () => {
    expect(decidedPhase(7, [change({ diff: DIFF })])).toBeNull();
    expect(decidedPhase(7, [change({ status: "failed" })])).toBeNull();
    expect(decidedPhase(7, [change({ id: 8, status: "approved" })])).toBeNull();
    expect(
      decidedPhase(7, [change({ status: "approved", new_version: null })]),
    ).toBeNull();
    expect(decidedPhase(7, [])).toBeNull();
  });
});
